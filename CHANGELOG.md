# Changelog

## 0.1.0 (2026-11-13)

First release. Seven probe inputs (missing-file, empty-file, directory-as-file,
non-utf8-file, unknown-flag, empty-stdin, path-with-spaces), caller-declared
`--expect` rules that default to observe, `--valid FILE` and `--valid-dir DIR`
controls, a timeout per run, SIGTERM cleanup of the direct child and fixtures, and
`--help`. Integration runs on five tools in `examples/trials/`.
