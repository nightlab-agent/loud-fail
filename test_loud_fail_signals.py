"""Real runner signals, synchronized with a live probe over a local socket."""

import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import unittest

import loud_fail


@unittest.skipUnless(os.name == "posix", "POSIX runner signal behavior")
class SignalTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name).resolve()
        self.env = dict(os.environ, TMPDIR=str(self.root))
        self.valid = self.root / "valid.txt"
        self.valid.write_bytes(b"valid bytes")

    def start_probe(self, expectation="observe", timeout="30"):
        listener = socket.socket()
        self.addCleanup(listener.close)
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(5)
        code = (
            "import json,os,pathlib,signal,socket,sys\n"
            "if len(sys.argv) > 1 and pathlib.Path(sys.argv[1]).name == 'missing.txt':\n"
            "    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "    signal.signal(signal.SIGINT, signal.SIG_IGN)\n"
            f"    with socket.create_connection({listener.getsockname()!r}) as channel:\n"
            "        channel.sendall((json.dumps([os.getpid(), str(pathlib.Path(sys.argv[1]).parent)]) + '\\n').encode())\n"
            "        if channel.recv(1) != b'x': sys.exit('probe channel closed')\n"
            "print('done')\n"
        )
        process = subprocess.Popen(
            [sys.executable, str(Path(loud_fail.__file__).resolve()),
             "--timeout", timeout, "--expect", "missing-file=" + expectation,
             "--valid", str(self.valid),
             "--", sys.executable, "-c", code, "{}"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env)
        child_pid = None

        def cleanup():
            if process.poll() is None:
                process.kill()
            if child_pid is not None:
                try:
                    os.kill(child_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.communicate(timeout=5)

        self.addCleanup(cleanup)
        channel, _ = listener.accept()
        self.addCleanup(channel.close)
        channel.settimeout(5)
        with channel.makefile("rb") as ready:
            child_pid, root = json.loads(ready.readline())
        os.kill(child_pid, 0)  # The sender is alive, not merely a stale readiness file.
        self.assertIsNone(process.poll())
        fixture = Path(root)
        self.assertTrue(fixture.is_dir())
        self.assertEqual((fixture / "good-input.txt").read_bytes(), b"valid bytes")
        return process, channel, child_pid, fixture

    def assert_stopped(self, process, child_pid, fixture):
        # Wait on the runner itself before draining inherited capture pipes.
        process.wait(timeout=5)
        with self.subTest(resource="direct child"):
            with self.assertRaises(ProcessLookupError):
                os.kill(child_pid, 0)
        with self.subTest(resource="fixture"):
            self.assertFalse(fixture.exists(), str(fixture))
        stdout, stderr = process.communicate(timeout=5)
        self.assertNotEqual(process.returncode, 0, (stdout, stderr))
        self.assertEqual(stdout, b"", "interrupted case must not get a policy row")
        return stderr

    def test_sigterm_cleans_child_and_fixtures_under_every_policy_on_repeat(self):
        roots = []
        for expectation in ("observe", "accept", "reject"):
            with self.subTest(expectation=expectation):
                process, _, child_pid, fixture = self.start_probe(expectation)
                roots.append(fixture)
                process.send_signal(signal.SIGTERM)
                stderr = self.assert_stopped(process, child_pid, fixture)
                self.assertEqual((process.returncode, stderr), (143, b""))
        self.assertEqual(len(set(roots)), 3)

    def test_sigint_still_cleans_child_and_fixtures(self):
        process, _, child_pid, fixture = self.start_probe()
        process.send_signal(signal.SIGINT)
        self.assert_stopped(process, child_pid, fixture)
        self.assertEqual(process.returncode, -signal.SIGINT)

    def test_timeout_still_kills_ready_child_and_removes_fixtures(self):
        process, _, child_pid, fixture = self.start_probe("reject", timeout="2")
        stdout, stderr = process.communicate(timeout=10)
        self.assertEqual((process.returncode, stderr), (1, b""), stdout)
        with self.assertRaises(ProcessLookupError):
            os.kill(child_pid, 0)
        self.assertFalse(fixture.exists())
        row = stdout.decode("utf-8").splitlines()[0]
        self.assertTrue(row.startswith("HANG"), row)
        self.assertIn("missing-file", row)
        self.assertNotRegex(row, r"\bexit -?\d+")

    def test_sigterm_leaves_concurrent_peer_fixtures_and_normal_exit_intact(self):
        first, _, first_pid, first_root = self.start_probe()
        peer, release, peer_pid, peer_root = self.start_probe()
        self.assertNotEqual(first_root, peer_root)
        first.send_signal(signal.SIGTERM)
        self.assert_stopped(first, first_pid, first_root)
        self.assertIsNone(peer.poll())
        os.kill(peer_pid, 0)
        self.assertTrue(peer_root.is_dir())
        release.sendall(b"x")
        stdout, stderr = peer.communicate(timeout=5)
        self.assertEqual((peer.returncode, stderr), (0, b""), stdout)
        self.assertIn(b"missing-file", stdout)
        self.assertFalse(peer_root.exists())


if __name__ == "__main__":
    unittest.main()
