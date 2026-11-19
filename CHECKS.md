# Checks

What was run before each release, and what was not.

## The test suite

`sh tests/release.sh` runs 52 tests with `python3 -X dev -W error`. They start real child
processes: tools that crash, stay silent, hang, accept everything, or refuse an unknown flag,
and check the row loud-fail prints for each. They also cover running twice in a row, two
runs at the same time, a valid file or folder control, refused controls (symlinks, FIFOs,
missing paths), and a real SIGTERM or SIGINT sent mid-probe (the direct child is stopped
and the temporary folder removed).

Run on Linux with Python 3.12. Not run: other Python versions, Windows, macOS.

## Five real tools

Before release, loud-fail was run on five command-line tools Nightlab maintains, with the
rules each tool's README promises declared as `--expect`. Every one of the seven inputs ran
on every tool. The commands are in `examples/trials/run-trials.sh` and the output of the
2026-11-13 run, one file per tool, is beside it (temporary paths shown as `$TMPDIR`).

| Tool | What loud-fail showed |
| --- | --- |
| plugin-lag | Bad inputs refused with a message (exit 2); unknown flag refused; a folder with spaces in its path accepted. An empty folder given as the root is accepted, which is that tool's rule. |
| npm-release-check | Bad inputs refused with a message (exit 2); unknown flag refused; a package folder with spaces in its path accepted. |
| still-true | Rules held. An empty or non-UTF-8 note exits 0 with "no claims", reported under observe. |
| short-preflight | Four bad-file inputs and the unknown flag refused; a path with spaces accepted. |
| mod-api-index | An earlier version accepted an unknown flag and exited 0 (SAYS OK). Fixed in 0.1.3, which refuses it with exit 64 and a message; the four bad-file inputs exit 2. |

These are integration runs on tools from the same maintainer, not a survey of other
people's tools.

## empty-stdin in an empty folder (0.1.1)

Before 0.1.1 the empty-stdin case ran in the caller's folder, so a tool that falls back to
`.` was measured on that folder. On 2026-11-19, `archy cycles {}` with `--timeout 10` gave
empty-stdin OK (exit 0) when started from an empty folder and HANG (no exit in 10 s) when
started from a large one. From 0.1.1 the case runs in a new empty folder inside the run's
temporary folder; `archy cycles {}` then gives OK from both (rerun the same day). Three
tests cover it: a tool that walks `.` gets no finding when the caller's folder is full, the
folder starts empty and is removed after each of two runs, and after a timeout the child is
stopped and the folder removed. Four more check that the program is still found when it is
named `./tool` or `link/../tool`, or found through a `.` or empty PATH entry (an empty entry
means the current folder; a review caught that the first version missed it).

## Known limits

- Only the direct child is stopped on timeout, SIGTERM or SIGINT. A process the target
  starts can survive, and if it keeps the output pipe open, cleanup waits for it past
  `--timeout`. SIGKILL or a crash of loud-fail itself can leave the temporary folder behind.
- Captured output has no size cap; the table shows the first 70 characters of the first
  message line.
- Folder controls copy names, bytes and empty folders, not permissions, timestamps or links,
  and are read into memory without a cap. Use a small folder.
- Traceback detection matches the formats listed in `INTERFACE.md`; colored, localized or
  custom output can be missed, and no match does not prove a graceful failure.
- Children inherit your environment, and every case but empty-stdin starts in your working
  directory. A tool that writes to a fixed path can collide with itself across runs.
