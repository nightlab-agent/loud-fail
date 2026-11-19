"""empty-stdin finds the program from the caller's folder before it starts in an empty one."""
import os, subprocess, sys, tempfile, unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
