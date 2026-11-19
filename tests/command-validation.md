# Command validation regression evidence

Base: 0.1.1 (3111384). Python 3.12.3 on Linux. The unmodified release check
passed all 52 tests before the regression was added.

## Red, before the repair

Only `test_loud_fail_command.py` had been added when this command ran:

```sh
python3 -X dev -W error -m unittest -v test_loud_fail_command
```

Test process exit: **1**. Retained output excerpts:

```text
test_command_removed_by_empty_stdin_is_a_cli_usage_error ... FAIL
test_command_removed_by_empty_stdin_starts_no_subprocess ... FAIL
test_command_with_input_templates_still_runs ... ok
test_input_templates_keep_their_existing_substitution ... ok

AssertionError: 1 != 2
IndexError: list index out of range
AssertionError: target started before command validation

Ran 4 tests in 1.020s

FAILED (failures=8)
```

Each rejection test failed for all four commands: `('{}',)`, `('{}', '{}')`,
`('--in={}',)` and `('prefix{}suffix', '{}{}')`. The real CLI returned 1,
printed NO RUN rows and crashed at `resolve_executable`'s `argv[0]` during
empty-stdin. The second test stopped the first attempted subprocess launch
with an assertion. The two passing tests cover nearby executable commands
and exact substitution for omitted, standalone, embedded, repeated and
multiple placeholder arguments.

## Repair and checks

`parse()` already owns usage validation, and `main()` already translates its
`ValueError` into a diagnostic, usage text and exit 2. Reject only when every
command argument contains `{}`: empty-stdin removes all such arguments.
Do not impose a new placeholder position or count rule.

After the two-line validation repair, the same regression command exits 0:
4 tests pass. `sh tests/release.sh` and the warning/encoding check documented
in `INTERFACE.md` pass all 56 tests. Help, README, changelog and state describe
the same nonempty-command rule. No version bump or publication is included.

The new check reads only local arguments, before fixture creation or launching:

- Twice: no state is retained; the suite also checks repeat invocations.
- Concurrently: the check shares no mutable state; the suite checks overlapping runs.
- Interrupted: rejection owns no child or fixtures to clean up; existing timeout
  and real SIGTERM/SIGINT tests still pass for valid commands.
- Real system: CLI regressions use the actual Python entry point, while the
  separate Popen assertion proves that no target launch is attempted.

Not run: other Python versions, Windows, macOS, and the five real-tool trials in
CHECKS.md. Executable permission messages and working-directory behaviour are
outside this change.
