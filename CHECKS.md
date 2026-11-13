# Checks

What was run before 0.1.0, and what was not.

## The test suite

`sh tests/release.sh` runs 43 tests with `python3 -X dev -W error`. They start real child
processes: tools that crash, stay silent, hang, accept everything, or refuse an unknown flag,
and check the row loud-fail prints for each. They also cover running twice in a row, two
runs at the same time, a valid file or folder control, refused controls (symlinks, FIFOs,
missing paths), and a real SIGTERM or SIGINT sent mid-probe (the direct child is stopped
and the temporary folder removed).

Run on Linux with Python 3.12. Not run: other Python versions, Windows, macOS.

## Five real tools

Before release, loud-fail was run on five command-line tools Nightlab maintains, with the
rules each tool's README promises declared as `--expect`. Across those runs every one of
the seven inputs ran on every tool.

| Tool | What loud-fail showed |
| --- | --- |
| plugin-lag | Bad inputs refused with a message (exit 2); unknown flag refused; a folder with spaces in its path accepted. An empty folder given as the root is accepted, which is that tool's rule. |
| npm-release-check | Bad inputs refused with a message (exit 2); unknown flag refused; a package folder with spaces in its path accepted. |
| still-true | Rules held. An empty or non-UTF-8 note exits 0 with "no claims", reported under observe. |
| short-preflight | Four bad-file inputs and the unknown flag refused; a path with spaces accepted. |
| mod-api-index | An earlier version accepted an unknown flag and exited 0 (SAYS OK). Fixed in 0.1.3, which refuses it with exit 64 and a message; the four bad-file inputs exit 2. |

These are integration runs on tools from the same maintainer, not a survey of other
people's tools.

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
- Children inherit your working directory and environment. A tool that writes to a fixed
  path can collide with itself across runs.
