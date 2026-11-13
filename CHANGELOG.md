# Changelog

## Unreleased

`--timeout` now accepts more than 0 and at most 86400 seconds; `nan`, `inf`,
zero, negative and larger values exit 2 with a message (`1e100` was a traceback).

## 0.1.0 (2026-11-13)

First release. Seven probe inputs (missing-file, empty-file, directory-as-file,
non-utf8-file, unknown-flag, empty-stdin, path-with-spaces), caller-declared
`--expect` rules that default to observe, `--valid FILE` and `--valid-dir DIR`
controls, a timeout per run, SIGTERM cleanup of the direct child and fixtures, and
`--help`. Integration runs on five tools in `examples/trials/`.
