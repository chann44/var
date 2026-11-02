import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import engine


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.hostfile = Path(self.directory.name) / "hosts.json"
        self.hostfile.write_text(json.dumps([
            ["127.0.0.1:5500"], ["127.0.0.1:5501"], ["127.0.0.1:5502"],
        ]))

    def assert_invalid(self, argv):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            engine.parse_args(argv)
        self.assertEqual(error.exception.code, 2)

    def test_baseline_and_workers(self):
        self.assertIsNone(engine.parse_args(["--prompt", "hello"]).hosts)
        args = engine.parse_args(["--hosts", str(self.hostfile), "--rank", "2"])
        self.assertEqual(args.rank, 2)
        self.assertIsNone(args.prompt)

    def test_invalid_requests(self):
        for argv in (
            [], ["--prompt", " "], ["--prompt", "🐍" * 4097],
            ["--prompt", "hi", "--max-tokens", "0"],
            ["--prompt", "hi", "--max-tokens", "1025"],
            ["--prompt", "hi", "--timeout", "0"],
            ["--prompt", "hi", "--timeout", "nan"],
            ["--prompt", "hi", "--timeout", "inf"],
            ["--prompt", "hi", "--rank", "0"],
            ["--hosts", str(self.hostfile)],
            ["--hosts", str(self.hostfile), "--rank", "-1"],
            ["--hosts", str(self.hostfile), "--rank", "3"],
            ["--hosts", str(self.hostfile), "--rank", "0"],
            ["--hosts", str(self.hostfile), "--rank", "1", "--prompt", "hi"],
        ):
            with self.subTest(argv=argv):
                self.assert_invalid(argv)

    def test_invalid_hostfiles(self):
        for hosts in (
            {}, [], [["127.0.0.1:5500"]],
            [["127.0.0.1:5500"]] * 2,
            [["not-an-ip:5500"], ["127.0.0.1:5501"]],
            [["0.0.0.0:5500"], ["127.0.0.1:5501"]],
            [["127.0.0.1:99999"], ["127.0.0.1:5501"]],
            [["127.0.0.1:nope"], ["127.0.0.1:5501"]],
            [["127.0.0.1"], ["127.0.0.1:5501"]],
            ["127.0.0.1:5500", "127.0.0.1:5501"],
        ):
            with self.subTest(hosts=hosts):
                self.hostfile.write_text(json.dumps(hosts))
                with self.assertRaises(ValueError):
                    engine.read_hosts(self.hostfile)

    def test_deadline_kills_a_stuck_worker(self):
        worker = Path(self.directory.name) / "stuck.py"
        worker.write_text("import time\ntime.sleep(30)\n")
        with patch.object(engine, "__file__", str(worker)), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(engine.main(["--prompt", "hi", "--timeout", "0.1"]), 124)


if __name__ == "__main__":
    unittest.main()
