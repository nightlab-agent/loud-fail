"""empty-stdin: the program is found from the caller's folder, then runs in an empty one."""
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

from test_loud_fail import CliBase

LOUD_FAIL = str(Path(__file__).resolve().parent / "loud_fail.py")


class ProgramLookupTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.caller = self.root / "caller"
        self.caller.mkdir()
        self.tool = self.caller / "tool"
        self.tool.write_text("#!/bin/sh\necho ran\n", encoding="utf-8")
        self.tool.chmod(0o755)

    def row(self, argv0, path):
        p = subprocess.run([sys.executable, LOUD_FAIL, "--timeout", "5", "--", argv0, "{}"],
                           cwd=self.caller, capture_output=True, timeout=60,
                           env=dict(os.environ, TMPDIR=str(self.root), PATH=path))
        return next(l for l in p.stdout.decode().splitlines() if " empty-stdin " in l)

    def assertRuns(self, argv0, path):
        line = self.row(argv0, path)
        self.assertEqual(line.split()[0], "OK", line)

    def test_dot_entry_in_path(self):
        self.assertRuns("tool", ".:/usr/bin:/bin")

    def test_empty_entry_in_path_means_the_callers_folder(self):
        for path in (":/usr/bin:/bin", "/usr/bin:/bin:", "/usr/bin::/bin"):
            with self.subTest(path=path):
                self.assertRuns("tool", path)

    def test_dot_slash_program(self):
        self.assertRuns("./tool", "/usr/bin:/bin")

    def test_symlink_then_dotdot_resolves_as_the_kernel_does(self):
        far = self.root / "far" / "deep"
        far.mkdir(parents=True)
        (self.root / "far" / "tool").write_text("#!/bin/sh\necho far\n", encoding="utf-8")
        (self.root / "far" / "tool").chmod(0o755)
        (self.caller / "link").symlink_to(far)
        self.tool.unlink()
        self.assertRuns("link/../tool", "/usr/bin:/bin")


class EmptyFolderTests(CliBase):
    def invoke_directory_walker(self, caller, executable=sys.executable, env=None):
        record = self.root / "walk.json"
        record.unlink(missing_ok=True)
        script = self.root / "walk.py"
        literals = ["--config=relative/config.json", "two words", ".."]
        script.write_text(
            "import json,pathlib,sys,time\n"
            f"if sys.argv[1:4] != {literals!r}: sys.exit('changed literal arguments')\n"
            "if len(sys.argv) == 4:\n"
            "    entries = sorted(str(p) for p in pathlib.Path('.').rglob('*'))\n"
            "    observed = dict(cwd=str(pathlib.Path.cwd()), entries=entries,\n"
            "                    stdin=sys.stdin.buffer.read().decode('utf-8'))\n"
            f"    pathlib.Path({str(record.resolve())!r}).write_text(json.dumps(observed), encoding='utf-8')\n"
            "    for entry in entries: time.sleep(0.05)\n"
            "print('done')\n", encoding="utf-8")
        argv = self.argv("", "--timeout", "1")
        argv[argv.index("--") + 1:] = [executable, str(script.resolve()), *literals, "{}"]
        result = subprocess.run(argv, cwd=caller, capture_output=True,
                                env=self.env if env is None else env, timeout=15)
        self.assertTrue(record.is_file(), (result.returncode, result.stdout, result.stderr))
        return result, json.loads(record.read_text(encoding="utf-8"))

    def test_empty_stdin_walker_has_no_finding_from_an_empty_caller_directory(self):
        caller = self.root / "launcher" / "empty caller"
        caller.mkdir(parents=True)
        bin_dir = caller.parent / "bin"
        bin_dir.mkdir()
        (bin_dir / "walk-python").symlink_to(sys.executable)
        # A relative PATH entry must be resolved before the child's cwd changes.
        lookup_env = dict(self.env, PATH=os.path.relpath(bin_dir, caller))
        for executable, env in ((sys.executable, self.env), ("walk-python", lookup_env)):
            with self.subTest(executable=executable):
                result, observed = self.invoke_directory_walker(caller, executable, env)
                self.assertEqual(observed["entries"], [])
                self.assertEqual(observed["stdin"], "")
                self.assertEqual(self.rows(result)["empty-stdin"][:2], ("OK", "observe"))
                self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(list(caller.iterdir()), [])
        self.assertEqual(list(self.root.glob("loud-fail-*")), [])

    def test_empty_stdin_uses_a_fresh_empty_directory_and_removes_it_on_repeat(self):
        caller = self.root / "populated caller"
        caller.mkdir()
        sentinel = caller / "sentinel.txt"
        sentinel.write_bytes(b"caller-owned bytes")
        # 65 entries at 0.05 s each exceed the 1 s probe deadline in the caller.
        for index in range(64):
            (caller / f"entry-{index}").touch()
        roots = []
        for index in range(2):
            result, observed = self.invoke_directory_walker(caller)
            case_dir = Path(observed["cwd"])
            roots.append(case_dir)
            with self.subTest(run=index, contract="own working directory"):
                self.assertNotEqual(case_dir, caller.resolve())
            with self.subTest(run=index, contract="initially empty"):
                self.assertEqual(observed["entries"], [])
                self.assertEqual(observed["stdin"], "")
            with self.subTest(run=index, contract="caller sentinel untouched"):
                self.assertEqual(sentinel.read_bytes(), b"caller-owned bytes")
                self.assertEqual(len(list(caller.iterdir())), 65)
            with self.subTest(run=index, contract="case directory removed"):
                self.assertFalse(case_dir.exists(), str(case_dir))
            with self.subTest(run=index, contract="no false timeout"):
                self.assertEqual(self.rows(result)["empty-stdin"][:2], ("OK", "observe"))
                self.assertEqual(result.returncode, 0, result.stdout)
            self.assertEqual(list(self.root.glob("loud-fail-*")), [])
        self.assertEqual(len(set(roots)), 2, "each invocation needs a fresh case directory")


if __name__ == "__main__":
    unittest.main()
