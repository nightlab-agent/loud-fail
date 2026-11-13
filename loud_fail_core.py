"""Describe inputs and classify supplied results without I/O (Python 3.11+).

See INTERFACE.md for runner obligations and heuristic limits. This module does
not create fixtures, launch commands, detect target languages or provide
filesystem/network isolation.
"""

from dataclasses import dataclass
import re
from typing import Literal


Expectation = Literal["reject", "accept", "observe"]
_Signature = Literal["python-traceback", "node-stack", "rust-panic", "go-panic"]
_Stream = Literal["stdout", "stderr"]
CASE_IDS = ("missing-file", "empty-file", "directory-as-file", "non-utf8-file",
            "unknown-flag", "empty-stdin", "path-with-spaces")
EXCERPT_LIMIT = 512


@dataclass(frozen=True, slots=True, kw_only=True)
class Fixture:
    """Require one named entry under the runner's temporary fixture directory."""

    name: str
    kind: Literal["absent", "file", "directory"]
    content: bytes | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Case:
    """Describe input changes; names in replace_input refer to fixtures."""

    id: str
    expectation: Expectation
    fixtures: tuple[Fixture, ...] = ()
    replace_input: str | None = None
    extra_args: tuple[str, ...] = ()
    stdin: bytes | None = None


def _validate_expectation(expectation: Expectation) -> None:
    if expectation not in ("reject", "accept", "observe"):
        raise ValueError("expectation must be reject, accept or observe")


def make_case(case_id: str, *, expectation: Expectation,
              valid_content: bytes | None = None, valid_directory: bool = False) -> Case:
    """Select one case with explicit policy and a file or directory control.

    Raise ValueError for an unknown id, expectation or inappropriate control
    configuration; raise TypeError for non-bytes valid_content or non-bool
    valid_directory.
    """
    _validate_expectation(expectation)
    if case_id not in CASE_IDS:
        raise ValueError(f"unknown case id: {case_id!r}")
    if valid_content is not None and not isinstance(valid_content, bytes):
        raise TypeError("valid_content must be bytes")
    if not isinstance(valid_directory, bool):
        raise TypeError("valid_directory must be bool")
    if valid_directory and (case_id != "path-with-spaces" or valid_content is not None):
        raise ValueError("valid_directory is only used by path-with-spaces, without valid_content")
    if case_id == "path-with-spaces":
        if valid_directory:
            fixture = Fixture(name="valid input", kind="directory")
        elif valid_content is None:
            raise ValueError("path-with-spaces requires valid_content or valid_directory=True")
        else:
            fixture = Fixture(name="valid input.txt", kind="file", content=valid_content)
    elif valid_content is not None:
        raise ValueError("valid_content is only used by path-with-spaces")
    elif case_id == "unknown-flag":
        return Case(id=case_id, expectation=expectation,
                    extra_args=("--loud-fail-unknown-option",))
    elif case_id == "empty-stdin":
        return Case(id=case_id, expectation=expectation, stdin=b"")
    elif case_id == "missing-file":
        fixture = Fixture(name="missing.txt", kind="absent")
    elif case_id == "empty-file":
        fixture = Fixture(name="empty.txt", kind="file", content=b"")
    elif case_id == "directory-as-file":
        fixture = Fixture(name="directory", kind="directory")
    else:
        fixture = Fixture(name="non-utf8.bin", kind="file", content=b"\xff\xfe\x80\n")
    return Case(id=case_id, expectation=expectation, fixtures=(fixture,),
                replace_input=fixture.name)


def _validate_streams(stdout: bytes, stderr: bytes) -> None:
    if not isinstance(stdout, bytes) or not isinstance(stderr, bytes):
        raise TypeError("stdout and stderr must be separate bytes")


@dataclass(frozen=True, slots=True, kw_only=True)
class CompletedRun:
    """Carry a completed target's subprocess-style status and captured bytes."""

    returncode: int
    stdout: bytes
    stderr: bytes

    def __post_init__(self) -> None:
        if type(self.returncode) is not int:
            raise TypeError("returncode must be an integer from a completed target")
        _validate_streams(self.stdout, self.stderr)


@dataclass(frozen=True, slots=True, kw_only=True)
class IncompleteRun:
    """Carry runner failure or timeout context and any partial, unclassified bytes."""

    reason: Literal["setup-failure", "timeout"]
    detail: str
    stdout: bytes = b""
    stderr: bytes = b""

    def __post_init__(self) -> None:
        if self.reason not in ("setup-failure", "timeout"):
            raise ValueError("incomplete reason must be setup-failure or timeout")
        if not isinstance(self.detail, str):
            raise TypeError("detail must be text")
        _validate_streams(self.stdout, self.stderr)


@dataclass(frozen=True, slots=True, kw_only=True)
class StackEvidence:
    """Identify a heuristic signature, its stream and a bounded matched prefix."""

    signature: _Signature
    stream: _Stream
    excerpt: str
    truncated: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class Assessment:
    """Keep observed behavior separate from the caller's exit expectation."""

    returncode: int
    exit_outcome: Literal["zero", "nonzero", "signal"]
    stdout_present: bool
    stderr_present: bool
    stacks: tuple[StackEvidence, ...]
    mismatch: Literal["unexpected-success", "unexpected-failure"] | None

    @property
    def silent(self) -> bool:
        """Return whether neither decoded stream has non-whitespace output."""
        return not (self.stdout_present or self.stderr_present)


# Require adjacent structural lines, not just error vocabulary. Match each
# stream independently. These deliberately recognize only a few plain formats.
_PATTERNS: tuple[tuple[_Signature, re.Pattern[str]], ...] = (
    ("python-traceback", re.compile(
        r'^Traceback \(most recent call last\):\n'
        r'  File "[^\n]+", line [0-9]+(?:, in [^\n]+)?\n'
        r'(?:[ \t][^\n]*\n){0,80}'
        r'[A-Za-z_][\w.]*(?::[^\n]*)?$', re.MULTILINE)),
    ("node-stack", re.compile(
        r'^(?:[A-Za-z_$][\w.$]*Error|Error)(?: \[[A-Z_0-9]+\])?:[^\n]*\n'
        r'(?:[ \t]+at [^\n]*:[0-9]+:[0-9]+\)?(?:\n|$))+', re.MULTILINE)),
    ("rust-panic", re.compile(
        r"^thread '[^'\n]+' panicked at (?:"
        r'[^\n]+:[0-9]+:[0-9]+:\n[^\n]+'
        r'(?:\nnote: [^\n]+)?'
        r"|'[^\n]*', [^\n]+:[0-9]+(?::[0-9]+)?"
        r'\n(?:note: [^\n]+|stack backtrace:))$', re.MULTILINE)),
    ("go-panic", re.compile(
        r'^panic: [^\n]+\n\n'
        r'goroutine [0-9]+ \[[^\n]+\]:\n'
        r'[^\s\n]+\([^\n]*\)\n'
        r'[ \t]+[^\n]+\.go:[0-9]+[^\n]*$', re.MULTILINE)),
)


def classify(expectation: Expectation,
             run: CompletedRun | IncompleteRun) -> Assessment | IncompleteRun:
    """Classify captured bytes; pass incomplete runs through without a verdict.

    UTF-8 replacement decoding never rejects invalid bytes. Evidence is the
    first match per signature per stream, capped at EXCERPT_LIMIT characters.
    Stack evidence is a finding regardless of expectation or returncode.
    Silence is an observation, including on normally silent accepted input.
    """
    _validate_expectation(expectation)
    if isinstance(run, IncompleteRun):
        return run
    if not isinstance(run, CompletedRun):
        raise TypeError("run must be CompletedRun or IncompleteRun")
    stdout = run.stdout.decode("utf-8", errors="replace").replace("\r\n", "\n")
    stderr = run.stderr.decode("utf-8", errors="replace").replace("\r\n", "\n")
    stacks: list[StackEvidence] = []
    streams: tuple[tuple[_Stream, str], ...] = (("stdout", stdout), ("stderr", stderr))
    for stream, text in streams:
        for signature, pattern in _PATTERNS:
            match = pattern.search(text)
            if match is not None:
                excerpt = match.group().rstrip("\n")
                stacks.append(StackEvidence(
                    signature=signature, stream=stream,
                    excerpt=excerpt[:EXCERPT_LIMIT],
                    truncated=len(excerpt) > EXCERPT_LIMIT,
                ))
    mismatch: Literal["unexpected-success", "unexpected-failure"] | None = None
    if expectation == "reject" and run.returncode == 0:
        mismatch = "unexpected-success"
    elif expectation == "accept" and run.returncode != 0:
        mismatch = "unexpected-failure"
    outcome: Literal["zero", "nonzero", "signal"] = (
        "zero" if run.returncode == 0 else "nonzero")
    if run.returncode < 0:
        outcome = "signal"
    return Assessment(returncode=run.returncode, exit_outcome=outcome,
                      stdout_present=bool(stdout.strip()),
                      stderr_present=bool(stderr.strip()), stacks=tuple(stacks),
                      mismatch=mismatch)
