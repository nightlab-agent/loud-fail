"""Command validation happens before probes; supported input templates still run."""
import contextlib, io, subprocess, unittest
from unittest.mock import patch

import loud_fail
from test_loud_fail import CliBase


EMPTY_COMMANDS = (("{}",), ("{}", "{}"), ("--in={}",), ("prefix{}suffix", "{}{}"))


class CommandValidationTests(CliBase):
    def test_command_removed_by_empty_stdin_is_a_cli_usage_error(self):
        for command in EMPTY_COMMANDS:
            with self.subTest(command=command):
                argv = self.argv("")
                argv[argv.index("--") + 1:] = command
                result = subprocess.run(argv, capture_output=True, env=self.env, timeout=15)
                self.assertEqual(result.returncode, 2, result)
                self.assertEqual(result.stdout, b"")
                self.assertIn(b"no command remains", result.stderr)
                self.assertIn(b"Usage:", result.stderr)
                self.assertNotIn(b"Traceback", result.stderr)
        self.assertEqual(list(self.root.glob("loud-fail-*")), [])

    def test_command_removed_by_empty_stdin_starts_no_subprocess(self):
        for command in EMPTY_COMMANDS:
            out, err = io.StringIO(), io.StringIO()
            with self.subTest(command=command), contextlib.redirect_stdout(out), \
                    contextlib.redirect_stderr(err), patch("loud_fail.subprocess.Popen") as spawn:
                spawn.side_effect = AssertionError("target started before command validation")
                self.assertEqual(loud_fail.main(["--", *command]), 2)
                spawn.assert_not_called()
                self.assertEqual(out.getvalue(), "")
                self.assertIn("no command remains", err.getvalue())

    def test_command_with_input_templates_still_runs(self):
        for inputs in ((), ("{}",), ("--in={}",), ("{}{}",), ("{}", "--copy={}")):
            with self.subTest(inputs=inputs):
                argv = self.argv("print('ran')", "--valid", str(self.valid))
                argv[-1:] = inputs
                result = subprocess.run(argv, capture_output=True, env=self.env, timeout=15)
                rows = self.rows(result)
                self.assertEqual(result.returncode, 0, result.stdout)
                self.assertEqual(len(rows), 7)
                self.assertTrue(all(row[0] == "OK" for row in rows.values()), rows)
                self.assertIn("ran", rows["empty-stdin"][2])

    def test_input_templates_keep_their_existing_substitution(self):
        file_case = loud_fail.make_case("empty-file", expectation="observe")
        stdin_case = loud_fail.make_case("empty-stdin", expectation="observe")
        for inputs, expected in (([], ["/r/empty.txt"]),
                                 (["{}"], ["/r/empty.txt"]),
                                 (["--in={}"], ["--in=/r/empty.txt"]),
                                 (["{}{}"], ["/r/empty.txt/r/empty.txt"]),
                                 (["{}", "--copy={}"], ["/r/empty.txt", "--copy=/r/empty.txt"])):
            with self.subTest(inputs=inputs):
                cmd = ["tool", *inputs]
                self.assertEqual(loud_fail.argv_for(cmd, file_case, "/r", None),
                                 ["tool", *expected])
                self.assertEqual(loud_fail.argv_for(cmd, stdin_case, "/r", None), ["tool"])


if __name__ == "__main__":
    unittest.main()
