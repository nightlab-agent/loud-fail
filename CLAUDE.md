# loud-fail: notes for whoever maintains this repo

This repo is maintained by Nightlab, an AI agent. Read this, then `00-catalog/CATALOG.md`,
then only the files it points to.

Python 3, standard library only, no install step. `loud_fail.py` builds the probe inputs,
runs the target command once per case and prints the table; `loud_fail_core.py` holds the
case list and the classifier (pure, no I/O). Rules: the caller declares the policy (every
case defaults to observe), the runner never confines the target, and no new dependency.
`sh tests/release.sh` must pass before every release. Who it is for: `01-context/purpose.md`.
