#!/usr/bin/env python3
"""loud-fail: probe a command and check caller-declared exit expectations.

Usage: loud_fail.py [--timeout S] [--expect CASE=reject|accept|observe]... [--valid FILE | --valid-dir DIR] -- CMD ARGS...
  {} in CMD ARGS marks where the input path goes (appended when absent).
  The command must remain nonempty when arguments containing {} are dropped for empty-stdin.
  --timeout S: seconds each run may take, default 10, more than 0 and at most 86400.
  Every case defaults to observe. Declare accept or reject with --expect.
  CASE is one of: missing-file empty-file directory-as-file non-utf8-file
  unknown-flag empty-stdin path-with-spaces
  --valid FILE: bytes this command accepts; adds the path-with-spaces control and
  the unknown-flag case (which needs a good input beside the extra argument).
  --valid-dir DIR: instead copy a valid directory, including nested files and empty
  directories, into independent controls. Symlinks and special entries are usage
  errors before any target runs. Requires POSIX no-follow directory access.
  Controls supply input, not policy; use --expect path-with-spaces=accept to check it.
Exit 0 when no row is a finding, 1 when one is, 2 on usage.
On POSIX, SIGTERM during a probe exits 143 after direct-child and fixture cleanup.
The interrupted case gets no policy verdict.
"""
import math, os, signal, subprocess, sys, tempfile
import shutil, stat

from loud_fail_core import CASE_IDS, CompletedRun, IncompleteRun, classify, make_case

__version__ = "0.1.1"


def argv_for(cmd, case, root, valid_path):
    """The command line for one case, or None when the case cannot be built."""
    path = None
    if case.replace_input:
        path = os.path.join(root, case.replace_input)
    elif case.extra_args:
        if valid_path is None:
            return None
        path = valid_path
    if path is None:                       # empty-stdin: drop the input argument
        argv = [a for a in cmd if "{}" not in a]
    else:
        argv = [a.replace("{}", path) for a in cmd]
        if argv == cmd:
            argv = cmd + [path]
    if case.extra_args:                    # before any "--" delimiter
        cut = argv.index("--") if "--" in argv[1:] else len(argv)
        argv = argv[:cut] + list(case.extra_args) + argv[cut:]
    return argv


def build(case, root):
    for f in case.fixtures:
        p = os.path.join(root, f.name)
        if f.kind == "file":
            with open(p, "wb") as fh:
                fh.write(f.content)
        elif f.kind == "directory":
            os.mkdir(p)


def read_directory(path, parent_fd=None):
    """Snapshot ordinary entries using handles; never follow an entry's symlink."""
    mode = os.stat(path, dir_fd=parent_fd, follow_symlinks=False).st_mode
    if stat.S_ISLNK(mode):
        raise ValueError(f"symlink is not allowed: {path!r}")
    if not stat.S_ISDIR(mode):
        raise ValueError(f"not a directory: {path!r}")
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
    try:
        entries = []
        for name in sorted(os.listdir(fd)):
            mode = os.stat(name, dir_fd=fd, follow_symlinks=False).st_mode
            if stat.S_ISDIR(mode):
                content = read_directory(name, fd)
            elif stat.S_ISREG(mode):
                # O_NONBLOCK also prevents a swapped-in FIFO from hanging setup.
                child = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                with os.fdopen(child, "rb") as fh:
                    if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
                        raise ValueError(f"special entry is not allowed: {name!r}")
                    content = fh.read()
            elif stat.S_ISLNK(mode):
                raise ValueError(f"symlink is not allowed: {name!r}")
            else:
                raise ValueError(f"special entry is not allowed: {name!r}")
            entries.append((name, content))
        return tuple(entries)
    finally:
        os.close(fd)


def write_directory(entries, destination):
    """Materialize a snapshot as fresh files and directories, without links."""
    os.mkdir(destination)
    for name, content in entries:
        path = os.path.join(destination, name)
        if isinstance(content, bytes):
            with open(path, "xb") as fh:
                fh.write(content)
        else:
            write_directory(content, path)


def resolve_executable(argv):
    """argv with its program made absolute against the caller's folder and PATH; the rest literal."""
    prog = argv[0]
    found = shutil.which(prog) if os.sep not in prog else prog
    if found and not os.path.isabs(found):      # which() gives a bare name for an empty PATH entry
        found = os.path.join(os.getcwd(), found)  # not abspath: keep link/.. for the kernel to resolve
    return [found or prog] + argv[1:]


def run(argv, stdin, timeout, cwd=None):
    try:
        p = subprocess.run(argv, input=stdin if stdin is not None else b"", capture_output=True,
                           timeout=timeout, cwd=cwd)
        return CompletedRun(returncode=p.returncode, stdout=p.stdout, stderr=p.stderr)
    except subprocess.TimeoutExpired as e:
        return IncompleteRun(reason="timeout", detail=f"no exit in {timeout:g} s",
                             stdout=e.stdout or b"", stderr=e.stderr or b"")
    except OSError as e:
        return IncompleteRun(reason="setup-failure", detail=str(e))


def verdict(result):
    """(word, is a finding, why) for one classified run."""
    if isinstance(result, IncompleteRun):
        return ("HANG" if result.reason == "timeout" else "NO RUN"), True, result.detail
    if result.stacks:
        s = result.stacks[0]
        return "TRACEBACK", True, f"exit {result.returncode}, {s.signature} on {s.stream}"
    if result.mismatch == "unexpected-success":
        return "SAYS OK", True, "exit 0 on an input it should refuse"
    if result.mismatch == "unexpected-failure":
        return "REFUSED", True, f"exit {result.returncode} on an input it should take"
    if result.silent and result.returncode != 0:
        return "SILENT", True, f"exit {result.returncode}, no message"
    if result.silent:
        return "QUIET OK", False, "exit 0, no output"
    return "LOUD" if result.returncode else "OK", False, f"exit {result.returncode}"


def first_line(raw):
    text = (raw.stderr.strip() or raw.stdout.strip()).decode("utf-8", "replace")
    return text.splitlines()[0][:70] if text else ""


def parse(args):
    timeout, expect, valid, valid_dir = 10.0, {}, None, None
    while args and args[0] != "--":
        if args[0] == "--timeout" and len(args) > 1:
            timeout = float(args[1])
            if not math.isfinite(timeout) or not 0 < timeout <= 86400:
                raise ValueError(f"--timeout {args[1]}: must be more than 0 and at most 86400 seconds")
        elif args[0] == "--expect" and len(args) > 1 and "=" in args[1]:
            k, v = args[1].split("=", 1)
            if k not in CASE_IDS or v not in ("reject", "accept", "observe"):
                raise ValueError(f"--expect {args[1]}: unknown case or expectation")
            expect[k] = v
        elif args[0] == "--valid" and len(args) > 1:
            if valid_dir is not None:
                raise ValueError("--valid and --valid-dir are mutually exclusive")
            with open(args[1], "rb") as fh:
                valid = fh.read()
        elif args[0] == "--valid-dir" and len(args) > 1 and args[1] != "--":
            if valid is not None:
                raise ValueError("--valid and --valid-dir are mutually exclusive")
            if not args[1]:
                raise ValueError("--valid-dir: empty directory path")
            if (not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY")
                    or os.open not in os.supports_dir_fd or os.listdir not in os.supports_fd):
                raise ValueError("--valid-dir requires POSIX no-follow directory access")
            try:
                # A trailing slash must not turn a root symlink into a directory.
                valid_dir = read_directory(args[1].rstrip(os.sep) or os.sep)
            except (OSError, ValueError) as e:
                raise ValueError(f"--valid-dir {args[1]!r}: {e}") from e
        else:
            raise ValueError(f"unknown argument {args[0]}")
        args = args[2:]
    if len(args) < 2:
        raise ValueError("no command after --")
    if all("{}" in a for a in args[1:]):
        raise ValueError("no command remains after removing {} input arguments; include an executable without {}")
    return timeout, expect, valid, valid_dir, args[1:]


def main(args):
    if args[:1] in (["-h"], ["--help"]):
        print(__doc__.strip())
        return 0
    try:
        timeout, expect, valid, valid_dir, cmd = parse(args)
    except (ValueError, OSError) as e:
        print(f"loud-fail: {e}\n\n{__doc__.strip()}", file=sys.stderr)
        return 2
    findings = 0
    with tempfile.TemporaryDirectory(prefix="loud-fail-") as root:
        valid_path = None
        if valid_dir is not None:
            valid_path = os.path.join(root, "good-input")
            try:
                write_directory(valid_dir, valid_path)
                write_directory(valid_dir, os.path.join(root, "valid input"))
            except OSError as e:
                print(f"loud-fail: --valid-dir: cannot copy controls: {e}", file=sys.stderr)
                return 2
        elif valid is not None:
            valid_path = os.path.join(root, "good-input.txt")
            with open(valid_path, "wb") as fh:
                fh.write(valid)
        for cid in CASE_IDS:
            if cid == "path-with-spaces":
                if valid is None and valid_dir is None:
                    continue
                case = make_case(cid, expectation=expect.get(cid, "observe"), valid_content=valid,
                                 valid_directory=valid_dir is not None)
            else:
                case = make_case(cid, expectation=expect.get(cid, "observe"))
            argv = argv_for(cmd, case, root, valid_path)
            if argv is None:
                print(f"{'SKIPPED':10} {cid:18} {case.expectation:8} needs --valid or --valid-dir")
                continue
            if cid != "path-with-spaces" or valid_dir is None:
                build(case, root)
            cwd = None
            if cid == "empty-stdin":       # no input path: start in an empty folder, not the caller's
                cwd = os.path.join(root, "empty-stdin")
                os.mkdir(cwd)
                argv = resolve_executable(argv)
            raw = run(argv, case.stdin, timeout, cwd)
            result = classify(case.expectation, raw)
            word, bad, why = verdict(result)
            print(f"{word:10} {cid:18} {case.expectation:8} {why:42} {first_line(raw)}".rstrip())
            findings += bad
    return 1 if findings else 0


def terminate(signum, frame):
    # Unwind subprocess.run and TemporaryDirectory, without classifying a killed probe.
    raise SystemExit(128 + signum)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, terminate)
    sys.exit(main(sys.argv[1:]))
