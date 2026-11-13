# Purpose

For people who maintain a command-line or agent tool and want to know, before a user does,
how it behaves on bad input: a missing file, an empty one, an unknown flag, a path with
spaces, empty stdin. Most of the pull requests Nightlab has had merged fix exactly that kind
of fault (a crash, silence, or the wrong message), so this tool checks for it directly.
Free, MIT. It reports; it never changes the target.
