"""Worktrail tests."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from worktrail import cli


class WorktrailTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cwd = patch("worktrail.cli.Path.cwd", return_value=self.root)
        self.cwd.start()
        self.git_snapshot = patch(
            "worktrail.cli.snapshot",
            return_value={"branch": None, "git_status": None},
        )
        self.git_snapshot.start()

    def tearDown(self):
        self.git_snapshot.stop()
        self.cwd.stop()
        self.temp.cleanup()

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_start_and_resume(self):
        code, _, _ = self.run_cli("start", "--task", "Fix login")
        self.assertEqual(code, 0)
        code, output, _ = self.run_cli("resume")
        self.assertEqual(code, 0)
        self.assertIn("Fix login", output)

    def test_checkpoint_saves_note(self):
        self.run_cli("start", "--task", "Fix login")
        code, _, _ = self.run_cli("checkpoint", "--note", "Tests pending")
        self.assertEqual(code, 0)
        _, output, _ = self.run_cli("resume")
        self.assertIn("Tests pending", output)

    def test_existing_session_is_not_overwritten(self):
        self.run_cli("start", "--task", "First task")
        code, _, error = self.run_cli("start", "--task", "Second task")
        self.assertEqual(code, 1)
        self.assertIn("already exists", error)
        _, output, _ = self.run_cli("resume")
        self.assertIn("First task", output)

    def test_checkpoint_requires_session(self):
        code, _, error = self.run_cli("checkpoint", "--note", "Progress")
        self.assertEqual(code, 1)
        self.assertIn("No session found", error)

    def test_malformed_session_is_rejected(self):
        session_dir = self.root / ".worktrail"
        session_dir.mkdir()
        (session_dir / "session.json").write_text(
            '{"task": "Broken", "notes": null}',
            encoding="utf-8",
        )
        code, _, error = self.run_cli("resume")
        self.assertEqual(code, 1)
        self.assertIn("invalid format", error)

    def test_empty_task_is_rejected(self):
        code, _, error = self.run_cli("start", "--task", "  ")
        self.assertEqual(code, 1)
        self.assertIn("Task cannot be empty", error)


if __name__ == "__main__":
    unittest.main()
