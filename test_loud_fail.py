"""Runner tests: fake tools that fail loudly, quietly, with a traceback, or hang."""

import contextlib, io, sys, unittest
import os
from pathlib import Path
import subprocess
import tempfile
import time
import socket

import loud_fail

LOUD = ("import sys,os\np=[a for a in sys.argv[1:] if not a.startswith('--')]\n"
        "if any(a.startswith('--') for a in sys.argv[1:]): sys.exit('unknown option')\n"
        "if not p: sys.exit('no input')\n"
        "if not os.path.isfile(p[0]): sys.exit('not a file: '+p[0])\n"
        "print('read', len(open(p[0],'rb').read()))\n")
SAYS_OK = "print('done')\n"
SILENT = "import sys\nsys.exit(3)\n"
CRASH = "import sys\nopen(sys.argv[1]).read()\n"
HANG = "import time\ntime.sleep(5)\n"
OPERANDS = (
    "import pathlib,sys\n"
    "for arg in sys.argv[1:]:\n"
    "    if arg == '--loud-fail-unknown-option': print('accepted operand')\n"
    "    elif pathlib.Path(arg).name == 'missing.txt':\n"
    "        with pathlib.Path(arg).open('xb') as out: out.write(b'created')\n"
    "        print('created missing path')\n"
    "    elif pathlib.Path(arg).name == 'valid input.txt':\n"
    "        if len(sys.argv) != 2 or pathlib.Path(arg).read_bytes() != b'valid bytes':\n"
    "            sys.exit('bad argv or contents')\n"
    "        print('one argument with valid bytes')\n"
    "print('done')\n"
)
DIRECTORY_READER = (
    "import pathlib,sys\n"
    "args = [a for a in sys.argv[1:] if not a.startswith('--')]\n"
    "if len(args) != 1: sys.exit('need one directory')\n"
    "p = pathlib.Path(args[0])\n"
    "try:\n"
    "    if (p / 'nested' / 'data.bin').read_bytes() != b'\\x00\\xffvalid':\n"
    "        sys.exit('wrong contents')\n"
    "    if not (p / 'nested' / 'empty').is_dir(): sys.exit('missing empty directory')\n"
    "    if (p / '.hidden').read_bytes() != b'hidden': sys.exit('missing hidden file')\n"
    "except OSError: sys.exit('not a valid directory')\n"
    "(p / 'nested' / 'data.bin').write_bytes(b'changed in copy')\n"
    "if '--loud-fail-unknown-option' in sys.argv: sys.exit('unknown option with valid directory')\n"
    "print('directory read as one argument')\n"
)


def run(code, *opts):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        rc = loud_fail.main([*opts, "--", sys.executable, "-c", code, "{}"])
    return rc, {line[11:].split()[0]: line[:10].strip() for line in out.getvalue().splitlines()}


class RunnerTests(unittest.TestCase):
    def test_a_tool_that_refuses_everything_bad_has_no_finding(self):
        rc, rows = run(LOUD, "--valid", __file__)
        self.assertEqual(rc, 0, rows)
        self.assertEqual(rows["missing-file"], "LOUD")
        self.assertEqual(rows["unknown-flag"], "LOUD")
        self.assertEqual(rows["path-with-spaces"], "OK")

    def test_exit_0_on_a_missing_file_is_a_finding(self):
        rc, rows = run(SAYS_OK, "--expect", "missing-file=reject")
        self.assertEqual(rc, 1)
        self.assertEqual(rows["missing-file"], "SAYS OK")
        self.assertEqual(rows["empty-file"], "OK")           # observe: not a finding
        self.assertEqual(rows["unknown-flag"], "SKIPPED")    # needs --valid

    def test_silent_nonzero_and_traceback_are_findings(self):
        self.assertEqual(run(SILENT)[1]["empty-file"], "SILENT")
        rc, rows = run(CRASH)
        self.assertEqual(rc, 1)
        self.assertEqual(rows["missing-file"], "TRACEBACK")
        self.assertEqual(rows["non-utf8-file"], "TRACEBACK")

    def test_explicit_observe_overrides_reject(self):
        rc, rows = run(SAYS_OK, "--expect", "missing-file=reject",
                       "--expect", "missing-file=observe")
        self.assertEqual(rows["missing-file"], "OK")
        self.assertEqual(rc, 0)

    def test_usage_errors_exit_2(self):
        for opts in (["--expect", "nope=reject"], ["--bogus", "x"], ["--valid", "/no/such/file"],
                     *(["--timeout", t] for t in ("nan", "inf", "-1", "0", "abc", "1e100", "86401"))):
            with self.subTest(opts=opts), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(loud_fail.main([*opts, "--", "true"]), 2)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(loud_fail.main(["--"]), 2)

    def test_help_prints_usage_and_exits_0(self):
        for flag in ("-h", "--help"):
            out = io.StringIO()
            with self.subTest(flag=flag), contextlib.redirect_stdout(out):
                self.assertEqual(loud_fail.main([flag]), 0)
            self.assertIn("missing-file empty-file", out.getvalue())

    def test_rows_have_no_trailing_spaces(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            loud_fail.main(["--", sys.executable, "-c", "pass", "{}"])
        rows = out.getvalue().splitlines()
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(row, row.rstrip())

    def test_empty_stdin_drops_the_input_argument(self):
        case = loud_fail.make_case("empty-stdin", expectation="observe")
        self.assertEqual(loud_fail.argv_for(["t", "--in", "{}", "-v"], case, "/r", None),
                         ["t", "--in", "-v"])

    def test_unknown_flag_goes_before_a_double_dash(self):
        case = loud_fail.make_case("unknown-flag", expectation="reject")
        self.assertEqual(loud_fail.argv_for(["t", "--", "{}"], case, "/r", "/r/good"),
                         ["t", "--loud-fail-unknown-option", "--", "/r/good"])


class CliTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.valid = self.root / "valid.txt"
        self.valid.write_bytes(b"valid bytes")
        self.valid_dir = self.root / "source directory"
        (self.valid_dir / "nested" / "empty").mkdir(parents=True)
        (self.valid_dir / "nested" / "data.bin").write_bytes(b"\x00\xffvalid")
        (self.valid_dir / ".hidden").write_bytes(b"hidden")
        self.env = dict(os.environ, TMPDIR=str(self.root))

    def argv(self, code, *opts):
        return [sys.executable, str(Path(loud_fail.__file__).resolve()),
                *opts, "--", sys.executable, "-c", code, "{}"]

    def invoke(self, code, *opts):
        return subprocess.run(self.argv(code, *opts), capture_output=True,
                              env=self.env, timeout=15)

    def rows(self, result):
        self.assertEqual(result.stderr, b"")
        return {line[11:].split()[0]: (line[:10].strip(), line[30:].split()[0], line)
                for line in result.stdout.decode("utf-8").splitlines()}

    def test_legitimate_creation_and_flag_operand_default_to_observe(self):
        result = self.invoke(OPERANDS, "--valid", str(self.valid))
        rows = self.rows(result)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(len(rows), 7)
        self.assertTrue(all(row[1] == "observe" for row in rows.values()), rows)
        self.assertEqual(rows["missing-file"][0], "OK")
        self.assertIn("created missing path", rows["missing-file"][2])
        self.assertEqual(rows["unknown-flag"][0], "OK")
        self.assertIn("accepted operand", rows["unknown-flag"][2])
        self.assertEqual(list(self.root.glob("loud-fail-*")), [])

    def test_explicit_reject_has_success_and_diagnostic_rejection_controls(self):
        opts = ("--valid", str(self.valid), "--expect", "missing-file=reject",
                "--expect", "unknown-flag=reject")
        for code, status, word in ((OPERANDS, 1, "SAYS OK"),
                                   ("import sys; sys.exit('refused input')", 0, "LOUD")):
            with self.subTest(status=status):
                result = self.invoke(code, *opts)
                rows = self.rows(result)
                self.assertEqual(result.returncode, status, result.stdout)
                for cid in ("missing-file", "unknown-flag"):
                    self.assertEqual(rows[cid][:2], (word, "reject"))
                    if status == 0:
                        self.assertIn("refused input", rows[cid][2])

    def test_spaces_preserve_one_argument_and_honor_each_explicit_expectation(self):
        for expectation, status, word in (("observe", 0, "OK"),
                                          ("accept", 0, "OK"),
                                          ("reject", 1, "SAYS OK")):
            with self.subTest(expectation=expectation):
                result = self.invoke(OPERANDS, "--valid", str(self.valid),
                                     "--expect", "missing-file=observe",
                                     "--expect", "unknown-flag=observe",
                                     "--expect", "path-with-spaces=" + expectation)
                row = self.rows(result)["path-with-spaces"]
                self.assertEqual(result.returncode, status, result.stdout)
                self.assertEqual(row[:2], (word, expectation))
                self.assertIn("one argument with valid bytes", row[2])
        result = self.invoke("import sys; sys.exit('refused input')", "--valid", str(self.valid),
                             "--expect", "path-with-spaces=accept")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.rows(result)["path-with-spaces"][:2], ("REFUSED", "accept"))

    def test_timeout_and_launch_failure_are_incomplete_under_every_policy(self):
        for expectation in ("observe", "accept", "reject"):
            for launch in (False, True):
                with self.subTest(expectation=expectation, launch=launch):
                    argv = self.argv(HANG, "--timeout", "0.2", "--expect",
                                     "missing-file=" + expectation)
                    if launch:
                        argv[argv.index("--") + 1:] = [str(self.root / "no-command"), "{}"]
                    result = subprocess.run(argv, capture_output=True, env=self.env, timeout=10)
                    row = self.rows(result)["missing-file"]
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(row[:2], ("NO RUN" if launch else "HANG", expectation))
                    self.assertNotRegex(row[2], r"\bexit -?\d+")
        self.assertEqual(list(self.root.glob("loud-fail-*")), [])

    def test_directory_controls_read_nested_bytes_and_empty_directories(self):
        result = self.invoke(DIRECTORY_READER, "--valid-dir", str(self.valid_dir),
                             "--expect", "path-with-spaces=accept",
                             "--expect", "unknown-flag=reject")
        rows = self.rows(result)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(rows["path-with-spaces"][:2], ("OK", "accept"))
        self.assertIn("directory read as one argument", rows["path-with-spaces"][2])
        self.assertEqual(rows["unknown-flag"][:2], ("LOUD", "reject"))
        self.assertIn("unknown option with valid directory", rows["unknown-flag"][2])
        self.assertEqual((self.valid_dir / "nested" / "data.bin").read_bytes(), b"\x00\xffvalid")
        self.assertEqual(list(self.root.glob("loud-fail-*")), [])

    def test_directory_controls_default_to_observe_and_honor_policy(self):
        for expectation, status, word in ((None, 0, "OK"), ("observe", 0, "OK"),
                                          ("reject", 1, "SAYS OK")):
            opts = [] if expectation is None else ["--expect", "path-with-spaces=" + expectation]
            with self.subTest(expectation=expectation):
                result = self.invoke(DIRECTORY_READER, "--valid-dir", str(self.valid_dir), *opts)
                rows = self.rows(result)
                self.assertEqual(result.returncode, status, result.stdout)
                self.assertEqual(rows["path-with-spaces"][:2], (word, expectation or "observe"))
                if expectation is None:
                    self.assertTrue(all(row[1] == "observe" for row in rows.values()), rows)
        empty = self.root / "empty-source"
        empty.mkdir()
        code = ("import pathlib,sys; p=pathlib.Path(sys.argv[1]) if len(sys.argv)>1 else None; "
                "sys.exit(0 if p is not None and p.is_dir() and not list(p.iterdir()) else 'not empty')")
        result = self.invoke(code, "--valid-dir", str(empty),
                             "--expect", "path-with-spaces=accept")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.rows(result)["path-with-spaces"][:2], ("QUIET OK", "accept"))

    def test_invalid_directory_controls_are_usage_errors_before_target_runs(self):
        marker = self.root / "target-ran"
        code = f"from pathlib import Path; Path({str(marker)!r}).touch()"
        for opts in (("--valid-dir",), ("--valid-dir", ""),
                     ("--valid-dir", str(self.root / "missing")),
                     ("--valid-dir", str(self.valid)),
                     ("--valid", str(self.valid), "--valid-dir", str(self.valid_dir)),
                     ("--valid-dir", str(self.valid_dir), "--valid", str(self.valid))):
            with self.subTest(opts=opts):
                result = self.invoke(code, *opts)
                self.assertEqual(result.returncode, 2, result)
                self.assertEqual(result.stdout, b"")
                self.assertIn(b"--valid-dir", result.stderr)
                if opts == ("--valid-dir", ""):
                    self.assertIn(b"empty directory path", result.stderr)
                self.assertNotIn(b"Traceback", result.stderr)
                self.assertFalse(marker.exists())
        self.assertEqual(list(self.root.glob("loud-fail-*")), [])

    def test_directory_links_and_special_entries_are_refused_without_launch(self):
        marker = self.root / "target-ran"
        code = f"from pathlib import Path; Path({str(marker)!r}).touch()"
        root_link = self.root / "root-link"
        root_link.symlink_to(self.valid_dir, target_is_directory=True)
        for source in (str(root_link), str(root_link) + "/"):
            result = self.invoke(code, "--valid-dir", source)
            self.assertEqual(result.returncode, 2, result)
            self.assertIn(b"symlink", result.stderr)
        entry = self.valid_dir / "nested" / "bad-entry"
        for target in (self.valid, self.valid_dir, self.root / "dangling"):
            with self.subTest(target=target):
                entry.symlink_to(target)
                try:
                    result = self.invoke(code, "--valid-dir", str(self.valid_dir))
                    self.assertEqual(result.returncode, 2, result)
                    self.assertIn(b"symlink", result.stderr)
                    self.assertIn(b"bad-entry", result.stderr)
                finally:
                    entry.unlink()
        os.mkfifo(entry)
        try:
            result = self.invoke(code, "--valid-dir", str(self.valid_dir))
            self.assertEqual(result.returncode, 2, result)
            self.assertIn(b"special", result.stderr)
        finally:
            entry.unlink()
        with socket.socket(socket.AF_UNIX) as sock:
            # Relative spelling avoids AF_UNIX path limits in deep checkouts.
            sock.bind(os.path.relpath(entry))
            result = self.invoke(code, "--valid-dir", str(self.valid_dir))
            self.assertEqual(result.returncode, 2, result)
            self.assertIn(b"special", result.stderr)
        self.assertFalse(marker.exists())
        self.assertEqual(list(self.root.glob("loud-fail-*")), [])

    def test_directory_controls_clean_up_after_timeout_and_launch_failure(self):
        for launch in (False, True):
            with self.subTest(launch=launch):
                argv = self.argv(HANG, "--valid-dir", str(self.valid_dir), "--timeout", "0.05")
                if launch:
                    argv[argv.index("--") + 1:] = [str(self.root / "no-command"), "{}"]
                result = subprocess.run(argv, capture_output=True, env=self.env, timeout=10)
                rows = self.rows(result)
                self.assertEqual(result.returncode, 1, result.stdout)
                for cid in ("unknown-flag", "path-with-spaces"):
                    self.assertEqual(rows[cid][0], "NO RUN" if launch else "HANG")
                self.assertEqual(list(self.root.glob("loud-fail-*")), [])

    def test_repeat_and_overlap_use_distinct_fixtures_and_clean_up(self):
        self.check_repeat_and_overlap(OPERANDS, "--valid", self.valid)

    def test_directory_repeat_and_overlap_use_isolated_copies_and_clean_up(self):
        self.check_repeat_and_overlap(DIRECTORY_READER, "--valid-dir", self.valid_dir)
        self.assertEqual((self.valid_dir / "nested" / "data.bin").read_bytes(), b"\x00\xffvalid")

    def check_repeat_and_overlap(self, reader, option, source):
        release = self.root / "release"

        def start(index):
            log = self.root / f"roots-{index}.txt"
            code = (
                "import pathlib,sys,time\n"
                "if len(sys.argv) > 1:\n"
                f"    with open({str(log)!r}, 'a', encoding='utf-8') as out:\n"
                "        out.write(str(pathlib.Path(sys.argv[1]).parent) + '\\n')\n"
                f"while not pathlib.Path({str(release)!r}).exists(): time.sleep(0.01)\n"
            ) + reader
            return subprocess.Popen(self.argv(code, option, str(source)),
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    env=self.env), log

        roots = []
        release.touch()
        for index in range(2):
            process, log = start(index)
            with process:
                stdout, stderr = process.communicate(timeout=15)
            self.assertEqual((process.returncode, stderr), (0, b""), stdout)
            roots.append(set(log.read_text(encoding="utf-8").splitlines()))
        release.unlink()
        with contextlib.ExitStack() as stack:
            peers = [start(index) for index in (2, 3)]
            for process, _ in peers:
                stack.enter_context(process)
            try:
                deadline = time.monotonic() + 5
                while not all(log.exists() for _, log in peers) and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(all(log.exists() for _, log in peers), "both children must start")
            finally:
                release.touch()
            for process, log in peers:
                stdout, stderr = process.communicate(timeout=15)
                self.assertEqual((process.returncode, stderr), (0, b""), stdout)
                roots.append(set(log.read_text(encoding="utf-8").splitlines()))
        self.assertEqual([len(paths) for paths in roots], [1] * 4)
        self.assertEqual(len(set.union(*roots)), 4)
        self.assertTrue(all(not Path(path).exists() for paths in roots for path in paths))


if __name__ == "__main__":
    unittest.main()
