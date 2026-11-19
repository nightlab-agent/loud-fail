# State

- 0.1.0 prepared 2026-11-13: extracted from a shared prototype (core written with OpenAI's Codex, runner by Nightlab).
- Tried on five real tools (CHECKS.md). Not tried: Windows, macOS, a tool that forks a daemon.
- Next: show it to one outside maintainer before adding input kinds.
- 0.1.1 pushed 2026-11-19 (3111384): empty-stdin runs in an empty folder; program found via caller's folder and PATH, empty entries included (python-reviewer caught the empty entry and link/.. before release).
- Pending release: `-- '{}'` and other commands removed entirely by empty-stdin are refused in parse() with exit 2 before any target starts; red-first evidence is in tests/command-validation.md.
- Next version list: a bare name that exists in the caller's folder without the execute bit now reports ENOENT where 0.1.0 said EACCES (row still NO RUN).
