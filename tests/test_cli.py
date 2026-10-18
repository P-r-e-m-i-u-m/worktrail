"""Tests for Worktrail's command-line interface."""

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
            return_value={"branch": "main", "git_status": ""},
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

    def test_handoff_includes_notes_git_context_and_next_step(self):
        self.run_cli("start", "--task", "Fix login")
        self.run_cli("checkpoint", "--note", "Token refresh still fails")
        with patch(
            "worktrail.cli.snapshot",
            return_value={"branch": "feature/login", "git_status": " M app.py"},
        ):
            code, output, error = self.run_cli(
                "handoff", "--next", "Add expired-token tests"
            )

        self.assertEqual(code, 0, error)
        self.assertIn("# Work handoff: Fix login", output)
        self.assertIn("Token refresh still fails", output)
        self.assertIn("feature/login", output)
        self.assertIn(" M app.py", output)
        self.assertIn("Add expired-token tests", output)

    def test_handoff_output_does_not_overwrite(self):
        self.run_cli("start", "--task", "Fix login")
        target = self.root / "handoff.md"
        target.write_text("keep this file", encoding="utf-8")

        code, _, error = self.run_cli("handoff", "--output", str(target))

        self.assertEqual(code, 1)
        self.assertIn("File exists", error)
        self.assertEqual(target.read_text(encoding="utf-8"), "keep this file")

    def test_handoff_rejects_blank_next_step(self):
        self.run_cli("start", "--task", "Fix login")
        code, _, error = self.run_cli("handoff", "--next", "   ")
        self.assertEqual(code, 1)
        self.assertIn("Next step cannot be empty", error)

    def test_doctor_passes_when_git_ignores_session_file(self):
        from unittest.mock import Mock

        with patch(
            "worktrail.cli.subprocess.run",
            return_value=Mock(returncode=0, stdout="", stderr=""),
        ) as run:
            code, output, error = self.run_cli("doctor")

        self.assertEqual(code, 0, error)
        self.assertIn(
            "[OK] .worktrail ignored: Git rules ignore .worktrail/session.json",
            output,
        )
        self.assertIn("check-ignore", run.call_args.args[0])

    def test_doctor_warns_when_git_does_not_ignore_session_file(self):
        from unittest.mock import Mock

        with patch(
            "worktrail.cli.subprocess.run",
            return_value=Mock(returncode=1, stdout="", stderr=""),
        ):
            code, output, error = self.run_cli("doctor")

        self.assertEqual(code, 1, error)
        self.assertIn("[WARN] .worktrail ignored:", output)
        self.assertIn(
            "Git does not ignore .worktrail/session.json",
            output,
        )

    def test_doctor_warns_when_git_ignore_check_fails(self):
        from unittest.mock import Mock

        with patch(
            "worktrail.cli.subprocess.run",
            return_value=Mock(returncode=128, stdout="", stderr="fatal: not a git repository"),
        ):
            code, output, error = self.run_cli("doctor")

        self.assertEqual(code, 1, error)
        self.assertIn("[WARN] .worktrail ignored: fatal: not a git repository", output)

    def test_recover_restores_last_saved_session_when_current_is_missing(self):
        self.run_cli("start", "--task", "Fix login")
        self.run_cli("checkpoint", "--note", "Newer progress")
        current = self.root / ".worktrail" / "session.json"
        backup = self.root / ".worktrail" / "session.json.bak"

        self.assertTrue(backup.exists())
        current.unlink()

        code, output, error = self.run_cli("recover")

        self.assertEqual(code, 0, error)
        self.assertIn("Session recovered: Fix login", output)
        self.assertTrue(backup.exists())
        _, resumed, _ = self.run_cli("resume")
        self.assertNotIn("Newer progress", resumed)

    def test_recover_never_overwrites_existing_session(self):
        self.run_cli("start", "--task", "Original task")
        self.run_cli("checkpoint", "--note", "Backup note")
        current = self.root / ".worktrail" / "session.json"
        before = current.read_text(encoding="utf-8")

        code, _, error = self.run_cli("recover")

        self.assertEqual(code, 1)
        self.assertIn("will not overwrite it", error)
        self.assertEqual(current.read_text(encoding="utf-8"), before)

    def test_recover_fails_cleanly_without_backup(self):
        code, _, error = self.run_cli("recover")

        self.assertEqual(code, 1)
        self.assertIn("No recovery backup found", error)

    def test_recover_rejects_malformed_backup_without_creating_session(self):
        folder = self.root / ".worktrail"
        folder.mkdir()
        (folder / "session.json.bak").write_text("{broken", encoding="utf-8")

        code, _, error = self.run_cli("recover")

        self.assertEqual(code, 1)
        self.assertIn("Cannot read session", error)
        self.assertFalse((folder / "session.json").exists())

    def test_version(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as exit_info:
            cli.main(["--version"])
        self.assertEqual(exit_info.exception.code, 0)
        self.assertIn("worktrail 0.1.0", out.getvalue())

    def test_start_and_resume(self):
        code, _, _ = self.run_cli("start", "--task", "Fix login")
        self.assertEqual(code, 0)
        code, output, _ = self.run_cli("resume")
        self.assertEqual(code, 0)
        self.assertIn("Fix login", output)
        self.assertIn("Branch:     main", output)

    def test_checkpoint_saves_note(self):
        self.run_cli("start", "--task", "Fix login")
        code, output, _ = self.run_cli("checkpoint", "--note", "Tests pending")
        self.assertEqual(code, 0)
        self.assertIn("Future-you", output)
        _, output, _ = self.run_cli("resume")
        self.assertIn("Tests pending", output)

    def test_checkpoint_without_note_updates_snapshot(self):
        self.run_cli("start", "--task", "Fix login")
        code, output, _ = self.run_cli("checkpoint")
        self.assertEqual(code, 0)
        self.assertIn("Checkpoint saved", output)

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
            '{"task": "Broken", "notes": null}', encoding="utf-8"
        )
        code, _, error = self.run_cli("resume")
        self.assertEqual(code, 1)
        self.assertIn("invalid format", error)

    def test_empty_task_is_rejected(self):
        code, _, error = self.run_cli("start", "--task", "  ")
        self.assertEqual(code, 1)
        self.assertIn("Task cannot be empty", error)

    def test_status_reports_changes(self):
        self.run_cli("start", "--task", "Fix login")
        with patch(
            "worktrail.cli.snapshot",
            return_value={"branch": "feature/login", "git_status": " M app.py"},
        ):
            code, output, _ = self.run_cli("status")
        self.assertEqual(code, 0)
        self.assertIn("Branch has changed", output)
        self.assertIn("Working tree has changed", output)

    def test_unicode_notes_round_trip(self):
        self.run_cli("start", "--task", "Fix login")
        self.run_cli("checkpoint", "--note", "Café ☕")
        _, output, _ = self.run_cli("resume")
        self.assertIn("Café ☕", output)


if __name__ == "__main__":
    unittest.main()
