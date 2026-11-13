"""Contract tests for the descriptions and pure classifier; no target processes."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
import unittest

import loud_fail_core as core


PYTHON = (b'Traceback (most recent call last):\n'
          b'  File "tool.py", line 4, in main\n'
          b'    read_input()\nValueError: bad input\n')
NODE = (b'TypeError: bad input\n'
        b'    at main (/tmp/tool.js:4:12)\n'
        b'    at /tmp/tool.js:8:1\n')
RUST = (b"thread 'main' panicked at src/main.rs:4:12:\n"
        b'bad input\nnote: run with `RUST_BACKTRACE=1` to display a backtrace\n')
GO = (b'panic: bad input\n\ngoroutine 1 [running]:\n'
      b'main.main()\n\t/tmp/main.go:4 +0x25\n')
STACKS = (("python-traceback", PYTHON), ("node-stack", NODE),
          ("rust-panic", RUST), ("go-panic", GO))


class CaseTests(unittest.TestCase):
    def test_explicit_selection_and_expectation(self):
        self.assertEqual(core.CASE_IDS, (
            "missing-file", "empty-file", "directory-as-file", "non-utf8-file",
            "unknown-flag", "empty-stdin", "path-with-spaces",
        ))
        with self.assertRaises(TypeError):
            core.make_case("empty-file")
        for expectation in ("reject", "accept", "observe"):
            case = core.make_case("empty-file", expectation=expectation)
            self.assertEqual(case.expectation, expectation)
            self.assertEqual(case.id, "empty-file")
        for case_id, expectation in (("typo", "reject"), ("empty-file", "typo")):
            with self.subTest(case_id=case_id, expectation=expectation):
                with self.assertRaises(ValueError):
                    core.make_case(case_id, expectation=expectation)

    def test_fixture_requirements_and_input_substitution(self):
        expected = (
            ("missing-file", "absent", "missing.txt", None),
            ("empty-file", "file", "empty.txt", b""),
            ("directory-as-file", "directory", "directory", None),
            ("non-utf8-file", "file", "non-utf8.bin", b"\xff\xfe\x80\n"),
        )
        for case_id, kind, name, content in expected:
            with self.subTest(case_id=case_id):
                case = core.make_case(case_id, expectation="observe")
                self.assertEqual(len(case.fixtures), 1)
                fixture = case.fixtures[0]
                self.assertEqual((fixture.kind, fixture.name, fixture.content),
                                 (kind, name, content))
                self.assertEqual(case.replace_input, name)
                self.assertEqual(case.extra_args, ())
                self.assertIsNone(case.stdin)

    def test_flag_and_empty_stdin_are_distinct_inputs(self):
        flag = core.make_case("unknown-flag", expectation="reject")
        self.assertEqual(flag.fixtures, ())
        self.assertIsNone(flag.replace_input)
        self.assertEqual(flag.extra_args, ("--loud-fail-unknown-option",))
        self.assertIsNone(flag.stdin)
        stdin = core.make_case("empty-stdin", expectation="accept")
        self.assertEqual(stdin.fixtures, ())
        self.assertIsNone(stdin.replace_input)
        self.assertEqual(stdin.extra_args, ())
        self.assertEqual(stdin.stdin, b"")

    def test_space_path_is_a_valid_input_control(self):
        with self.assertRaises(ValueError):
            core.make_case("path-with-spaces", expectation="accept")
        for expectation in ("reject", "observe"):
            case = core.make_case("path-with-spaces", expectation=expectation,
                                  valid_content=b"valid for this tool\n")
            self.assertEqual(case.expectation, expectation)
        case = core.make_case("path-with-spaces", expectation="accept",
                              valid_content=b'{"valid": true}\n')
        self.assertEqual(case.replace_input, "valid input.txt")
        self.assertEqual(case.fixtures[0].content, b'{"valid": true}\n')
        empty = core.make_case("path-with-spaces", expectation="accept",
                               valid_content=b"")
        self.assertEqual(empty.fixtures[0].content, b"")
        with self.assertRaises(ValueError):
            core.make_case("empty-file", expectation="accept", valid_content=b"x")

    def test_directory_space_control_has_explicit_policy_and_no_file_bytes(self):
        for expectation in ("observe", "accept", "reject"):
            case = core.make_case("path-with-spaces", expectation=expectation,
                                  valid_directory=True)
            self.assertEqual(case.expectation, expectation)
            self.assertEqual(case.fixtures[0].kind, "directory")
            self.assertIsNone(case.fixtures[0].content)
            self.assertIn(" ", case.replace_input)
        with self.assertRaises(ValueError):
            core.make_case("path-with-spaces", expectation="observe",
                           valid_content=b"", valid_directory=True)
        with self.assertRaises(ValueError):
            core.make_case("empty-file", expectation="observe", valid_directory=True)
        with self.assertRaises(TypeError):
            core.make_case("path-with-spaces", expectation="observe", valid_directory="yes")

    def test_descriptions_are_immutable_and_repeatable(self):
        case = core.make_case("missing-file", expectation="reject")
        self.assertEqual(case, core.make_case("missing-file", expectation="reject"))
        with self.assertRaises(FrozenInstanceError):
            case.expectation = "accept"
        with self.assertRaises(FrozenInstanceError):
            case.fixtures[0].name = "elsewhere"


class ClassificationTests(unittest.TestCase):
    def classify(self, expectation, code=0, stdout=b"", stderr=b""):
        return core.classify(expectation, core.CompletedRun(
            returncode=code, stdout=stdout, stderr=stderr))

    def test_exit_expectation_matrix_keeps_silence_independent(self):
        for expectation, code, mismatch in (
            ("reject", 0, "unexpected-success"), ("reject", 2, None),
            ("accept", 0, None), ("accept", 2, "unexpected-failure"),
            ("observe", 0, None), ("observe", 2, None),
        ):
            for stdout, stderr in ((b"", b""), (b"diagnostic\n", b""),
                                   (b"", b"diagnostic\n")):
                with self.subTest(expectation=expectation, code=code,
                                  stdout=stdout, stderr=stderr):
                    result = self.classify(expectation, code, stdout, stderr)
                    self.assertEqual(result.mismatch, mismatch)
                    self.assertEqual(result.returncode, code)
                    self.assertEqual(result.exit_outcome, "zero" if code == 0 else "nonzero")
                    self.assertEqual(result.stdout_present, bool(stdout))
                    self.assertEqual(result.stderr_present, bool(stderr))
                    self.assertEqual(result.silent, not (stdout or stderr))
                    self.assertEqual(result.stacks, ())

    def test_empty_stdin_can_legitimately_succeed_silently(self):
        case = core.make_case("empty-stdin", expectation="accept")
        result = self.classify(case.expectation)
        self.assertIsNone(result.mismatch)
        self.assertTrue(result.silent)

    def test_stdout_only_rejection_is_normal(self):
        result = self.classify("reject", 2, b"file not found\n")
        self.assertIsNone(result.mismatch)
        self.assertFalse(result.silent)
        self.assertTrue(result.stdout_present)
        self.assertFalse(result.stderr_present)

    def test_signals_preserve_status_and_expectation(self):
        for expectation, mismatch in (("accept", "unexpected-failure"),
                                      ("reject", None), ("observe", None)):
            result = self.classify(expectation, -9)
            self.assertEqual(result.exit_outcome, "signal")
            self.assertEqual(result.returncode, -9)
            self.assertEqual(result.mismatch, mismatch)

    def test_whitespace_and_invalid_bytes(self):
        for blank in (b"", b" \t\r\n\v\f", "\u2003\u00a0\n".encode("utf-8")):
            result = self.classify("observe", stdout=blank, stderr=blank)
            self.assertTrue(result.silent)
        result = self.classify("observe", stdout=b"\xff", stderr=b" \xfe\n")
        self.assertTrue(result.stdout_present)
        self.assertTrue(result.stderr_present)
        self.assertEqual(result.stacks, ())

    def test_stacks_on_either_stream_regardless_of_exit_or_expectation(self):
        for signature, output in STACKS:
            for stream in ("stdout", "stderr"):
                for code in (0, 1, -6):
                    for expectation in ("accept", "reject", "observe"):
                        with self.subTest(signature=signature, stream=stream,
                                          code=code, expectation=expectation):
                            result = self.classify(expectation, code, **{stream: output})
                            self.assertEqual(len(result.stacks), 1)
                            evidence = result.stacks[0]
                            self.assertEqual((evidence.signature, evidence.stream),
                                             (signature, stream))
                            self.assertEqual(evidence.excerpt, output.decode("utf-8").rstrip("\n"))
                            self.assertFalse(evidence.truncated)

    def test_prose_and_incomplete_signatures_are_not_stacks(self):
        controls = (
            b"Error: missing file\n", b"Do not panic.\n", b"Traceback is a Python word.\n",
            b"Traceback (most recent call last):\nThis is documentation.\n",
            b'Traceback (most recent call last):\n  File "x", line 1\n',
            b"Error: a tutorial\n    at home we print this\n",
            b"Error: bad input\nnot a stack\n    at main (/x.js:1:2)\n",
            b"    at main (/x.js:1:2)\n",
            b"panic: this is a word in prose\n",
            b"panic: tutorial\n\ngoroutine 1 [running]:\nnot a frame\n",
            b"thread 'main' panicked at the disco:\nordinary prose\n",
            b"thread 'main' panicked at src/main.rs:4:12:\n",
            b"thread 'main' panicked at 'example', src/main.rs:4:12\n",
        )
        for output in controls:
            with self.subTest(output=output):
                self.assertEqual(self.classify("observe", stderr=output).stacks, ())

    def test_do_not_join_streams_to_manufacture_a_signature(self):
        result = self.classify("observe", stdout=b"Error: message\n",
                               stderr=b"    at main (/x.js:1:2)\n")
        self.assertEqual(result.stacks, ())

    def test_crlf_no_final_newline_and_invalid_bytes_in_stacks(self):
        for signature, output in STACKS:
            for variant in (output.rstrip(b"\n"), output.replace(b"\n", b"\r\n"),
                            output.replace(b"bad input", b"bad \xff input")):
                with self.subTest(signature=signature, variant=variant):
                    result = self.classify("observe", stderr=variant)
                    self.assertEqual(result.stacks[0].signature, signature)

    def test_old_rust_format(self):
        output = (b"thread 'main' panicked at 'bad input', src/main.rs:4:12\n"
                  b"note: run with `RUST_BACKTRACE=1` to display a backtrace\n")
        self.assertEqual(self.classify("observe", stderr=output).stacks[0].signature,
                         "rust-panic")

    def test_indented_prose_does_not_complete_a_python_traceback(self):
        output = (b'Traceback (most recent call last):\n'
                  b'  File "tool.py", line 1\n' + b'        example\n' * 12
                  + b'ordinary prose with spaces\n')
        self.assertEqual(self.classify("observe", stderr=output).stacks, ())

    def test_bounded_evidence_starts_at_match_and_keeps_streams(self):
        output = b"banner\n" + NODE.replace(b"bad input", "\u732b".encode("utf-8") * 2000)
        result = self.classify("observe", stdout=output * 3, stderr=PYTHON + GO)
        self.assertEqual([(e.signature, e.stream) for e in result.stacks],
                         [("node-stack", "stdout"), ("python-traceback", "stderr"),
                          ("go-panic", "stderr")])
        evidence = result.stacks[0]
        self.assertEqual(core.EXCERPT_LIMIT, 512)
        self.assertEqual(len(evidence.excerpt), 512)
        self.assertTrue(evidence.excerpt.startswith("TypeError: \u732b"))
        self.assertNotIn("\ufffd", evidence.excerpt)
        self.assertTrue(evidence.truncated)

    def test_incomplete_runs_keep_partial_output_without_target_verdict(self):
        for reason in ("setup-failure", "timeout"):
            run = core.IncompleteRun(reason=reason, detail="runner context",
                                     stdout=b"partial", stderr=PYTHON)
            for expectation in ("reject", "accept", "observe"):
                self.assertIs(core.classify(expectation, run), run)
            self.assertFalse(hasattr(run, "returncode"))
            self.assertFalse(hasattr(run, "mismatch"))
            self.assertEqual(run.stderr, PYTHON)
        with self.assertRaises(ValueError):
            core.IncompleteRun(reason="oops", detail="context")

    def test_invalid_contract_inputs_do_not_become_completed_results(self):
        for code in (None, True, "0", 1.5):
            with self.subTest(code=code):
                with self.assertRaises(TypeError):
                    core.CompletedRun(returncode=code, stdout=b"", stderr=b"")
        for run_type, extra in ((core.CompletedRun, {"returncode": 0}),
                                (core.IncompleteRun, {"reason": "timeout", "detail": "x"})):
            with self.assertRaises(TypeError):
                run_type(stdout="text", stderr=b"", **extra)
        with self.assertRaises(ValueError):
            self.classify("typo")
        with self.assertRaises(TypeError):
            core.classify("observe", None)

    def test_repeat_and_overlap_share_no_result_state(self):
        run = core.CompletedRun(returncode=0, stdout=NODE, stderr=GO)
        expected = core.classify("reject", run)
        self.assertEqual(core.classify("reject", run), expected)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: core.classify("reject", run), range(20)))
        self.assertEqual(results, [expected] * 20)
        self.assertEqual(run.stdout, NODE)
        with self.assertRaises(FrozenInstanceError):
            expected.mismatch = None


if __name__ == "__main__":
    unittest.main()
