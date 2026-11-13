# Core contract for the runner

Python 3.11+; standard library only. Import `loud_fail_core` from this directory.
It has no entry point, process calls, file access or language selection.

```python
from loud_fail_core import CompletedRun, IncompleteRun, classify, make_case

case = make_case("missing-file", expectation="reject")
# Runner creates the described fixtures and invokes its selected command.
result = classify(case.expectation, CompletedRun(
    returncode=2, stdout=b"missing file\n", stderr=b""))
assert result.mismatch is None
assert result.stdout_present and not result.silent

control = make_case("path-with-spaces", expectation="accept",
                    valid_content=b"valid contents for this particular tool\n")
unfinished = classify(control.expectation, IncompleteRun(
    reason="timeout", detail="runner deadline exceeded", stdout=b"partial"))
assert isinstance(unfinished, IncompleteRun)
```

`make_case(id, *, expectation, valid_content=None, valid_directory=False)` selects exactly one case.
`CASE_IDS` lists the seven stable ids; it is not a default execution plan.
Expectations are `reject`, `accept`, or `observe`, with no default. Unknown ids,
expectations and inappropriate control settings raise `ValueError`.
Non-bytes `valid_content` raises `TypeError`.
Non-bool `valid_directory` raises `TypeError`. For path-with-spaces only,
`valid_directory=True` describes a directory named `valid input` instead of a file;
it cannot be combined with `valid_content`. The core does not read a source tree
or store its contents. The runner must populate that directory with a valid copy
before invoking the target. Other ids with `valid_directory=True` raise `ValueError`.

All returned descriptions and results are frozen dataclasses with immutable
fields. A `Case` carries `id`, `expectation` and these input instructions:

| Field | Runner responsibility |
| --- | --- |
| `fixtures` | Tuple of `Fixture(name, kind, content)` descriptions. Resolve names under a fresh temporary fixture directory. `absent`: leave that name absent; `directory`: create an empty directory; `file`: write the exact bytes in `content`. |
| `replace_input` | A fixture name, or `None`. Replace the caller-designated input argument with the resolved path as **one argv element**, preserving spaces. The core does not parse argument templates or shell quoting. |
| `extra_args` | Literal arguments to place in the command's option position. No shell expansion. |
| `stdin` | Exact bytes to supply and then close stdin; `b""` means immediate EOF. `None` means this case does not specify stdin; the runner must choose its own explicit stdin policy. |

| Id | Input description |
| --- | --- |
| `missing-file` | Absent `missing.txt`, substituted as input. |
| `empty-file` | Empty `empty.txt`, substituted as input. |
| `directory-as-file` | Empty `directory`, substituted in the input file position. |
| `non-utf8-file` | `non-utf8.bin` containing `ff fe 80 0a`, substituted as input. |
| `unknown-flag` | Option `--loud-fail-unknown-option`; caller verifies it is actually unknown and places it before any `--` delimiter. |
| `empty-stdin` | No fixtures or argument changes; zero stdin bytes followed by EOF. |
| `path-with-spaces` | `valid input.txt` with caller-supplied `valid_content`, or directory `valid input` when `valid_directory=True`, substituted as input. Caller chooses the expectation. |

For the file control, supply bytes known to be valid for the selected invocation;
empty bytes are permitted when valid. Select it only when that invocation also
accepts the `.txt` filename. All cases permit all three expectations: empty
input, directories, binary data and even missing paths can be legitimate inputs
to particular tools. No case id establishes invalidity. The core does not check
tool semantics, create fixtures, choose commands or promise isolation. A temporary
working directory does not confine a child's filesystem or network access.

The CLI accepts mutually exclusive `--valid FILE` and `--valid-dir DIR`.
Both add unknown-flag with a valid copied operand and path-with-spaces; neither
declares an expectation. Every CLI expectation still defaults to observe.
The directory option reads ordinary file bytes and directory layout, including
nested/hidden files and empty directories. It prepares independent `good-input`
and `valid input` copies under the invocation's temporary root before running any
target. Changes to one control do not change the other or the source. Root/entry
symlinks (including dangling links) and special entries are usage errors, exit 2,
with no target execution. Missing/unreadable inputs also produce usage errors.
Traversal uses directory descriptors and no-follow opens; platforms without that
POSIX support refuse `--valid-dir`. The file option's behavior is unchanged.
This is a bytes/layout copy, without metadata or hard-link preservation, dependency
discovery or rewriting embedded paths. Keep the source unchanged while it is read;
reads are not atomic across the tree. Setup holds the tree in memory with no size
cap and is outside the target timeout. Use small self-contained directories.

`classify(expectation, run)` accepts one of two distinct records:

- `CompletedRun(returncode=int, stdout=bytes, stderr=bytes)`: the target finished.
  All three keyword fields are required. Use subprocess return codes: zero,
  positive nonzero, or negative signal number. `None`, booleans and non-integers
  raise `TypeError`; text streams raise `TypeError`.
- `IncompleteRun(reason="setup-failure" | "timeout", detail=str, stdout=b"",
  stderr=b"")`: launch/fixture/setup failed, or the runner deadline expired.
  Preserve any partial bytes here, even if killing the target produced an exit
  code. `classify` returns this record unchanged, without a target verdict or
  stack classification. Unknown reasons raise `ValueError`. Do not fabricate a
  completed target status from runner errors or timeout cleanup.

A completed run returns `Assessment` with the original `returncode`, observed
`exit_outcome` (`zero`, `nonzero`, `signal`), independent `stdout_present` and
`stderr_present`, derived `silent`, a tuple of `stacks`, and `mismatch`:

| Expectation | Exit zero | Exit nonzero or signal |
| --- | --- | --- |
| `reject` | `unexpected-success` | `None` |
| `accept` | `None` | `unexpected-failure` |
| `observe` | `None` | `None` |

Output does not change this table. Exit zero with diagnostic text is still an
unexpected success for `reject`. A stdout-only diagnostic with nonzero exit is
a normal rejection. Silence is a separate observation on every run, including
legitimately silent acceptance. Signals remain visible even for `observe`.
`stacks` are findings independent of this table, including on exit zero.
There is no aggregate CLI verdict in the core.

## Stack evidence and heuristic limits

Each stream is decoded as UTF-8 with replacement and CRLF normalized to LF.
Decoded whitespace-only output is silent; invalid bytes count as output.
Streams are never joined. Each `StackEvidence` has `signature`, `stream`,
`excerpt`, and `truncated`. The excerpt is the matching text's prefix, excluding
trailing newlines, capped at `EXCERPT_LIMIT` (512 Unicode code points).
It can omit later structural evidence when a message is long. Keep the original
bytes if a reviewer needs full context; the core does not retain them in an
assessment. Evidence is not escaped for terminal or HTML display.

The first match per signature per stream is returned, in stdout/stderr order,
then Python/Node/Rust/Go order (at most eight records, not occurrence order):

- `python-traceback`: exact traceback header, adjacent file/line frame,
  up to 80 subsequent indented lines, then an exception identifier and optional
  message. Covers ordinary tracebacks, not exception-group layouts.
- `node-stack`: an Error-family heading, optional bracketed error code, then
  adjacent indented `at` frames with numeric line and column locations.
- `rust-panic`: named-thread panic with source line/column followed by message;
  older quoted-message/source format requires an adjacent note/backtrace header.
- `go-panic`: panic heading, blank line, goroutine heading, function call and
  indented `.go` source location.

Words such as `panic`, `Error` and `Traceback` alone do not match. These patterns
recognize plain representative formats, not runtime provenance or proof that an
exception was unhandled: copied full examples, caught-and-printed stacks or a
different runtime can imitate them. ANSI colors, localized/custom formatting,
interleaved output, truncated captures, very deep Python traces and other crash
formats can be missed. No match does not prove a graceful failure. The core
scans the full supplied streams and allocates decoded text; capture limits,
execution timeouts and resource management belong to the runner. Let the five
real-tool trials determine any expansion of these heuristics.

Run the suite from the extracted loud-fail repository root:
`python3 -X dev -X warn_default_encoding -W error -m unittest discover -s . -v`.
