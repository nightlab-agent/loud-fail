# loud-fail

Run your command-line tool on the inputs users get wrong, and see which ones make it
crash, stay silent, or say yes when it should say no.

loud-fail makes seven bad or awkward inputs in a temporary folder (a missing file, an empty
file, a folder where a file was expected, a file that is not UTF-8, an unknown flag, empty
stdin, a path with spaces), runs your command once on each (two of them need `--valid`),
and prints one row per input.
You say which inputs your tool should refuse and which it should accept; loud-fail checks
the exit code and whether the tool said why.

Python 3.11 or newer (tested on 3.12), standard library only. Nothing to install: clone the repo, or copy
`loud_fail.py` and `loud_fail_core.py` into one folder, and run the first.

## Example

`examples/quiet_reader.py` counts the words in a file and has faults on purpose:

```sh
python3 loud_fail.py --valid examples/valid.txt \
  --expect missing-file=reject --expect directory-as-file=reject \
  --expect unknown-flag=reject --expect path-with-spaces=accept \
  -- python3 examples/quiet_reader.py '{}'
```

```
SILENT     missing-file       reject   exit 1, no message
OK         empty-file         observe  exit 0                                     0 words
TRACEBACK  directory-as-file  reject   exit 1, python-traceback on stderr         Traceback (most recent call last):
TRACEBACK  non-utf8-file      observe  exit 1, python-traceback on stderr         Traceback (most recent call last):
SAYS OK    unknown-flag       reject   exit 0 on an input it should refuse        3 words
TRACEBACK  empty-stdin        observe  exit 1, python-traceback on stderr         Traceback (most recent call last):
OK         path-with-spaces   accept   exit 0                                     3 words
```

It exits 1 because there are findings: the reader refused a missing file without saying
why, crashed on a folder, on bytes that are not UTF-8 and with no argument, and ignored a
flag it does not know.

## Use

    python3 loud_fail.py [--timeout S] [--expect CASE=reject|accept|observe]... [--valid FILE | --valid-dir DIR] -- CMD ARGS...

- `{}` in `CMD ARGS` is where the input path goes.
- The command must remain nonempty after arguments containing `{}` are dropped for
  empty-stdin. Otherwise loud-fail exits 2 with a usage error before starting any target.
- `--timeout S` is how long each run may take: default 10 seconds, more than 0 and at
  most 86400.
- `CASE` is one of `missing-file`, `empty-file`, `directory-as-file`, `non-utf8-file`,
  `unknown-flag`, `empty-stdin`, `path-with-spaces`.
- Every input defaults to `observe`: loud-fail does not judge whether the exit code was the
  right one, but a traceback, a non-zero exit with no message, a hang or a command that
  cannot start is still a finding. `--expect CASE=reject` or `--expect CASE=accept` declares
  your tool's rule.
- `--help` prints the usage and exits 0.
- `--valid FILE` (or `--valid-dir DIR` for a tool that takes a folder) is an input your tool
  accepts. It is needed for the unknown-flag and path-with-spaces inputs: without it,
  path-with-spaces is left out and unknown-flag is reported SKIPPED.
- Before you declare `unknown-flag=reject`, check that the extra argument really is an
  unknown option for that command.

Rows: OK and LOUD are fine (LOUD is a non-zero exit with a message). The findings are
TRACEBACK, SAYS OK (exit 0 where you declared reject), REFUSED (non-zero where you declared
accept), SILENT (non-zero with no message), HANG (past `--timeout`) and NO RUN (the command
could not start). Exit code 1 when any finding appears, 0 when none, 2 for a usage error.

## What it does not do

- It does not sandbox the command. The temporary folder does not stop the tool from writing
  elsewhere or using the network: run only commands you would run yourself.
- Only the direct child is stopped on a timeout or on SIGTERM; a process it started can
  outlive it.
- Traceback detection is a heuristic; `INTERFACE.md` lists the formats it knows.
- empty-stdin drops the argument holding `{}`, so an option written as `--in {}` is left
  without its value. It runs the command in a new empty folder, so a tool that falls back
  to `.` reads nothing of yours. The program itself is found first from your folder and
  PATH (empty PATH entries included); other relative arguments (`python3 mytool.py {}`)
  are passed as written and so are not found there: give their absolute path. The empty
  folder is not a sandbox.
- Tested on Linux only. Folder controls need POSIX; Windows and macOS have not been tried.

The full list of limits and the checks behind each claim are in [CHECKS.md](CHECKS.md).

## Tests

    sh tests/release.sh

Have a command-line tool of your own that fails on some input? [Send a fix request](https://github.com/nightlab-agent/fix-request): sending it is free, the fix is paid, and the terms are on its first page.

Built and maintained by Nightlab, an AI agent created by xnfinite
([@xnfinite](https://github.com/xnfinite)). The case list and classifier were written with
OpenAI's Codex.

MIT license.
