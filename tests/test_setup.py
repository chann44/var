import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        self.project = self.path / "project with spaces"
        self.project.mkdir()
        self.bin = self.path / "bin"
        self.bin.mkdir()
        self.log = self.path / "commands.log"
        shutil.copy(ROOT / "setup.sh", self.project)
        (self.project / "hosts.example.json").write_text('[["192.168.1.10:5500"], ["192.168.1.11:5500"]]\n')
        self.command("uname", 'if [[ "$1" == -s ]]; then echo Darwin; else echo arm64; fi')
        self.command("git", 'exit 0')
        self.command("uv", '''
printf 'uv %s\\n' "$*" >> "$SETUP_TEST_LOG"
if [[ "$1" == venv ]]; then
    mkdir -p .venv/bin
    cp "$SETUP_TEST_PYTHON" .venv/bin/python
elif [[ "${SETUP_TEST_INSTALL_FAIL:-0}" == 1 ]]; then
    exit 42
fi
''')
        self.python = self.command("fake-python", 'printf "python %s\\n" "$*" >> "$SETUP_TEST_LOG"')
        self.env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}",
                        SETUP_TEST_LOG=str(self.log), SETUP_TEST_PYTHON=str(self.python))

    def command(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/bash\nset -eu\n" + body + "\n")
        path.chmod(0o755)
        return path

    def run_setup(self):
        return subprocess.run(["/bin/bash", str(self.project / "setup.sh")],
                              cwd=self.path, env=self.env, capture_output=True, text=True, timeout=10)

    def test_setup_from_another_directory_and_rerun_preserves_files(self):
        result = self.run_setup()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.project / "hosts.json").read_text(),
                         (self.project / "hosts.example.json").read_text())
        commands = self.log.read_text()
        self.assertIn("uv venv --python 3.12 .venv", commands)
        self.assertIn("uv pip install --python .venv/bin/python -r requirements.txt", commands)
        self.assertIn("python -m unittest discover -s tests -v", commands)
        self.assertIn("python engine.py --prompt Say hello in one sentence. --max-tokens 16", commands)
        (self.project / "hosts.json").write_text("my existing configuration\n")
        self.log.write_text("")
        result = self.run_setup()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("uv venv", self.log.read_text())
        self.assertEqual((self.project / "hosts.json").read_text(), "my existing configuration\n")

    def test_dependency_failure_stops_tests_and_download(self):
        self.env["SETUP_TEST_INSTALL_FAIL"] = "1"
        result = self.run_setup()
        self.assertEqual(result.returncode, 42)
        self.assertNotIn("unittest", self.log.read_text())
        self.assertNotIn("engine.py", self.log.read_text())
        self.assertNotIn("Setup complete", result.stdout)

    def test_missing_git_launches_installer_and_requests_rerun(self):
        self.command("git", "exit 1")
        self.command("xcode-select", 'printf "xcode-select %s\\n" "$*" >> "$SETUP_TEST_LOG"')
        result = self.run_setup()
        self.assertEqual(result.returncode, 1)
        self.assertIn("xcode-select --install", self.log.read_text())
        self.assertIn("rerun ./setup.sh", result.stderr)
        self.assertNotIn("uv ", self.log.read_text())

    def test_rejects_unsupported_platform(self):
        self.command("uname", "echo Linux")
        result = self.run_setup()
        self.assertEqual(result.returncode, 1)
        self.assertIn("Apple silicon", result.stderr)
        self.assertFalse(self.log.exists())


if __name__ == "__main__":
    unittest.main()
