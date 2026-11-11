"""Tests for Worktrail's command-line interface."""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from worktrail import cli


class SnapshotTests(unittest.TestCase):
    def test_snapshot_keeps_status_unavailable_when_git_status_fails(self):
        from unittest.mock import Mock, patch
        from worktrail.cli import snapshot

        branch_result = Mock(returncode=0, stdout="main", stderr="")
        status_result = Mock(returncode=1, stdout="", stderr="fatal: unavailable")
        with patch("worktrail.cli.subprocess.run", side_effect=[branch_result, status_result]):
            result = snapshot(Path.cwd())

        self.assertEqual(result, {"branch": "main", "git_status": None})

    def test_snapshot_keeps_status_unavailable_when_git_status_times_out(self):
        import subprocess
        from unittest.mock import Mock, patch
        from worktrail.cli import snapshot

        branch_result = Mock(returncode=0, stdout="main", stderr="")
        with patch(
            "worktrail.cli.subprocess.run",
            side_effect=[branch_result, subprocess.TimeoutExpired("git", 5)],
        ):
            result = snapshot(Path.cwd())

        self.assertEqual(result, {"branch": "main", "git_status": None})


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

    def test_handoff_output_is_published_only_after_complete_write(self):
        self.run_cli("start", "--task", "Fix login")
        target = self.root / "handoff.md"

        code, output, error = self.run_cli(
            "handoff", "--output", str(target)
        )

        self.assertEqual(code, 0, error)
        self.assertIn("Handoff saved:", output)
        self.assertTrue(target.is_file())
        self.assertIn("# Work handoff: Fix login", target.read_text(encoding="utf-8"))
        self.assertEqual(list(self.root.glob(".worktrail-handoff-*.tmp")), [])

    def test_handoff_output_cleans_temporary_file_when_publish_fails(self):
        self.run_cli("start", "--task", "Fix login")
        target = self.root / "handoff.md"

        with patch("worktrail.cli.os.link", side_effect=OSError("simulated publish failure")):
            code, _, error = self.run_cli("handoff", "--output", str(target))

        self.assertEqual(code, 1)
        self.assertIn("simulated publish failure", error)
        self.assertFalse(target.exists())
        self.assertEqual(list(self.root.glob(".worktrail-handoff-*.tmp")), [])

    def test_handoff_rejects_blank_next_step(self):
        self.run_cli("start", "--task", "Fix login")
        code, _, error = self.run_cli("handoff", "--next", "   ")
        self.assertEqual(code, 1)
        self.assertIn("Next step cannot be empty", error)

    def test_doctor_distinguishes_missing_git_executable(self):
        with patch("worktrail.cli.shutil.which", return_value=None):
            with patch("worktrail.cli.subprocess.run") as run:
                code, output, error = self.run_cli("doctor")

        self.assertEqual(code, 1, error)
        self.assertIn("Git was not found on PATH", output)
        self.assertIn("Install Git", output)
        self.assertNotIn("Not inside a Git repository", output)
        self.assertIn(
            "Cannot check ignore rules because Git is not available on PATH",
            output,
        )
        run.assert_not_called()

    def test_doctor_warns_when_git_is_installed_outside_repository(self):
        from unittest.mock import Mock

        with patch("worktrail.cli.shutil.which", return_value="/usr/bin/git"):
            with patch(
                "worktrail.cli.snapshot",
                return_value={"branch": None, "git_status": None},
            ):
                with patch(
                    "worktrail.cli.subprocess.run",
                    return_value=Mock(returncode=1, stdout="", stderr=""),
                ):
                    code, output, error = self.run_cli("doctor")

        self.assertEqual(code, 1, error)
        self.assertIn("[WARN] Git repository: Not inside a Git repository", output)
        self.assertNotIn("Git was not found on PATH", output)

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

    def test_doctor_accepts_root_anchored_worktrail_ignore_rule(self):
        import subprocess

        subprocess.run(
            ["git", "-C", str(self.root), "init"],
            capture_output=True,
            text=True,
            check=True,
        )
        (self.root / ".gitignore").write_text("/.worktrail/\n", encoding="utf-8")

        code, output, error = self.run_cli("doctor")

        self.assertEqual(code, 0, error)
        self.assertIn(
            "[OK] .worktrail ignored: Git rules ignore .worktrail/session.json",
            output,
        )

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

    def test_recover_does_not_overwrite_session_created_during_publish(self):
        self.run_cli("start", "--task", "Original task")
        self.run_cli("checkpoint", "--note", "Backup note")
        current = self.root / ".worktrail" / "session.json"
        current.unlink()
        competing = b'{"task":"Concurrent session"}\\n'
        real_link = __import__("os").link

        def create_competing_session(source, destination):
            Path(destination).write_bytes(competing)
            return real_link(source, destination)

        with patch("worktrail.cli.os.link", side_effect=create_competing_session):
            code, _, error = self.run_cli("recover")

        self.assertEqual(code, 1)
        self.assertIn("will not overwrite it", error)
        self.assertEqual(current.read_bytes(), competing)
        self.assertTrue((self.root / ".worktrail" / "session.json.bak").exists())
        self.assertEqual(
            list(current.parent.glob(".session.json.*.tmp")),
            [],
        )

    def test_recover_fails_cleanly_without_backup(self):
        code, _, error = self.run_cli("recover")

        self.assertEqual(code, 1)
        self.assertIn("No recovery backup found", error)

    def test_commands_fail_cleanly_when_session_is_not_utf8(self):
        folder = self.root / ".worktrail"
        folder.mkdir()
        session = folder / "session.json"
        session.write_bytes(b"\xff\xfe{\"task\": \"\xffencoding\"}")

        code, _, error = self.run_cli("summary")

        self.assertEqual(code, 1)
        self.assertIn("not valid UTF-8", error)
        self.assertNotIn("Traceback", error)
        # the file is left untouched
        self.assertEqual(
            session.read_bytes(), b"\xff\xfe{\"task\": \"\xffencoding\"}"
        )

    def test_recover_rejects_malformed_backup_without_creating_session(self):
        folder = self.root / ".worktrail"
        folder.mkdir()
        (folder / "session.json.bak").write_text("{broken", encoding="utf-8")

        code, _, error = self.run_cli("recover")

        self.assertEqual(code, 1)
        self.assertIn("Cannot read session", error)
        self.assertFalse((folder / "session.json").exists())

    def test_diff_reports_notes_added_since_checkpoint(self):
        self.run_cli("start", "--task", "Fix login")
        self.run_cli("checkpoint", "--note", "Initial state")
        self.run_cli("checkpoint", "--note", "Token refresh still fails")

        code, output, error = self.run_cli("diff")

        self.assertEqual(code, 0, error)
        self.assertIn("Notes added:", output)
        self.assertIn("Token refresh still fails", output)
    def test_history_shows_current_and_previous_saved_session(self):
        self.run_cli("start", "--task", "Fix login")
        self.run_cli("checkpoint", "--note", "First saved note")
        self.run_cli("checkpoint", "--note", "Second saved note")

        code, output, error = self.run_cli("history")

        self.assertEqual(code, 0, error)
        self.assertIn("Current session", output)
        self.assertIn("Previous saved version (session.json.bak)", output)
        self.assertNotIn("\\nPrevious saved version", output)
        self.assertIn("\nPrevious saved version", output)
        self.assertIn("Fix login", output)
        self.assertIn("Notes:      2", output)
        self.assertIn("Notes:      1", output)

    def test_history_explains_when_no_backup_exists(self):
        self.run_cli("start", "--task", "Fix login")

        code, output, error = self.run_cli("history")

        self.assertEqual(code, 0, error)
        self.assertIn("no backup yet", output)
        self.assertNotIn("\\nPrevious saved version", output)

    def test_history_fails_when_no_session_or_backup_exists(self):
        code, _, error = self.run_cli("history")

        self.assertEqual(code, 1)
        self.assertIn("No current session or recovery backup found", error)

    def test_summary_shows_compact_session_overview(self):
        self.run_cli("start", "--task", "Fix login")
        self.run_cli("checkpoint", "--note", "First note")
        self.run_cli("checkpoint", "--note", "Latest note")
        code, output, error = self.run_cli("summary")
        self.assertEqual(code, 0, error)
        self.assertIn("Task:       Fix login", output)
        self.assertIn("Notes:      2", output)
        self.assertIn("Latest note: Latest note", output)
        self.assertIn("Branch:     main", output)

    def test_summary_reports_no_notes(self):
        self.run_cli("start", "--task", "Fix login")
        code, output, error = self.run_cli("summary")
        self.assertEqual(code, 0, error)
        self.assertIn("Notes:      0", output)
        self.assertIn("Latest note: none yet", output)

    def test_summary_requires_session(self):
        code, _, error = self.run_cli("summary")
        self.assertEqual(code, 1)
        self.assertIn("No session found", error)
    def test_version(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as exit_info:
            cli.main(["--version"])
        self.assertEqual(exit_info.exception.code, 0)
        self.assertIn("worktrail 0.1.0", out.getvalue())

    def test_save_uses_unique_temporary_files_and_leaves_no_staging_files(self):
        from concurrent.futures import ThreadPoolExecutor
        import json

        self.run_cli("start", "--task", "Initial session")
        root = self.root

        def save_task(number):
            cli.save(root, {
                "task": f"Concurrent task {number}",
                "started_at": f"2026-11-10T10:00:0{number}+00:00",
                "checkpoint_at": f"2026-11-10T10:00:0{number}+00:00",
                "notes": [{"at": "2026-11-10T10:00:00+00:00", "text": str(number)}],
                "branch": "main",
                "git_status": "",
            })

        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(save_task, range(4)))

        current = json.loads((root / ".worktrail" / "session.json").read_text(encoding="utf-8"))
        self.assertTrue(current["task"].startswith("Concurrent task "))
        self.assertEqual(
            list((root / ".worktrail").glob(".session.json.*.tmp")),
            [],
        )
        self.assertEqual(
            list((root / ".worktrail").glob(".session.json.bak.*.tmp")),
            [],
        )
        backup = json.loads((root / ".worktrail" / "session.json.bak").read_text(encoding="utf-8"))
        self.assertIsInstance(backup["task"], str)

    def test_session_replace_retries_transient_permission_error(self):
        with patch(
            "worktrail.cli.os.replace",
            side_effect=[PermissionError("sharing violation"), None],
        ) as replace:
            cli._replace_with_retry(Path("staged.tmp"), Path("session.json"))

        self.assertEqual(replace.call_count, 2)

    def test_save_failure_keeps_current_session_and_cleans_temporary_file(self):
        import json

        self.run_cli("start", "--task", "Keep current session")
        current_path = self.root / ".worktrail" / "session.json"
        before = current_path.read_bytes()

        with patch("worktrail.cli.os.replace", side_effect=OSError("simulated replace failure")):
            with self.assertRaises(OSError):
                cli.save(self.root, {
                    "task": "Must not replace current",
                    "started_at": "2026-11-10T10:00:00+00:00",
                    "checkpoint_at": "2026-11-10T10:00:00+00:00",
                    "notes": [],
                    "branch": "main",
                    "git_status": "",
                })

        self.assertEqual(current_path.read_bytes(), before)
        self.assertEqual(
            list((self.root / ".worktrail").glob(".session.json.*.tmp")),
            [],
        )
        self.assertEqual(
            list((self.root / ".worktrail").glob(".session.json.bak.*.tmp")),
            [],
        )
        self.assertEqual(json.loads(before)["task"], "Keep current session")

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

    def test_status_reports_unavailable_git_status_without_clean_claim(self):
        self.run_cli("start", "--task", "Fix login")
        with patch(
            "worktrail.cli.snapshot",
            return_value={"branch": "main", "git_status": None},
        ):
            code, output, _ = self.run_cli("status")

        self.assertEqual(code, 0)
        self.assertIn("Branch matches the last checkpoint.", output)
        self.assertIn("Working tree comparison is unavailable", output)
        self.assertNotIn("Working tree matches", output)
        self.assertNotIn("Working tree is clean", output)

    def test_status_distinguishes_successful_empty_git_status(self):
        self.run_cli("start", "--task", "Fix login")
        with patch(
            "worktrail.cli.snapshot",
            return_value={"branch": "main", "git_status": ""},
        ):
            code, output, _ = self.run_cli("status")

        self.assertEqual(code, 0)
        self.assertIn("Working tree matches the last checkpoint.", output)
        self.assertNotIn("comparison is unavailable", output)

    def test_status_lists_changed_files(self):
        self.run_cli("start", "--task", "Fix login")
        with patch(
            "worktrail.cli.snapshot",
            return_value={
                "branch": "main",
                "git_status": " M app.py\n?? new_file.py",
            },
        ):
            code, output, _ = self.run_cli("status")

        self.assertEqual(code, 0)
        self.assertIn("Changed files:", output)
        self.assertIn("  - app.py", output)
        self.assertIn("  - new_file.py", output)

    def test_status_lists_renamed_file_destination(self):
        self.run_cli("start", "--task", "Fix login")
        with patch(
            "worktrail.cli.snapshot",
            return_value={
                "branch": "main",
                "git_status": "R  old_name.py -> new_name.py",
            },
        ):
            code, output, _ = self.run_cli("status")

        self.assertEqual(code, 0)
        self.assertIn("  - new_name.py", output)

    def test_status_lists_renamed_file_with_arrow_in_name(self):
        self.run_cli("start", "--task", "Fix login")
        with patch(
            "worktrail.cli.snapshot",
            return_value={
                "branch": "main",
                "git_status": 'R  "old -> name.py" -> "new -> name.py"',
            },
        ):
            code, output, _ = self.run_cli("status")

        self.assertEqual(code, 0)
        self.assertIn("  - new -> name.py", output)
        self.assertNotIn("  - old -> name.py", output)

    def test_status_decodes_quoted_changed_file_path(self):
        self.run_cli("start", "--task", "Fix login")
        with patch(
            "worktrail.cli.snapshot",
            return_value={
                "branch": "main",
                "git_status": r'?? "file with spaces.py"',
            },
        ):
            code, output, _ = self.run_cli("status")

        self.assertEqual(code, 0)
        self.assertIn("  - file with spaces.py", output)

    def test_status_decodes_octal_escaped_file_path(self):
        self.run_cli("start", "--task", "Fix login")
        with patch(
            "worktrail.cli.snapshot",
            return_value={
                "branch": "main",
                "git_status": r'?? "caf\303\251.py"',
            },
        ):
            code, output, _ = self.run_cli("status")

        self.assertEqual(code, 0)
        self.assertIn("  - café.py", output)

    def test_status_clean_tree_does_not_list_changed_files(self):
        self.run_cli("start", "--task", "Fix login")

        code, output, _ = self.run_cli("status")

        self.assertEqual(code, 0)
        self.assertIn(
            "Working tree matches the last checkpoint.",
            output,
        )
        self.assertNotIn("Changed files:", output)

    def test_unicode_notes_round_trip(self):
        self.run_cli("start", "--task", "Fix login")
        self.run_cli("checkpoint", "--note", "Café ☕")
        _, output, _ = self.run_cli("resume")
        self.assertIn("Café ☕", output)




class ArchiveAndSearchFeatureTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def run_cli(self, *args):
        from unittest.mock import patch
        from io import StringIO
        from contextlib import redirect_stdout, redirect_stderr
        from worktrail.cli import main

        out, err = StringIO(), StringIO()
        with patch("pathlib.Path.cwd", return_value=self.root):
            with redirect_stdout(out), redirect_stderr(err):
                code = main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_archive_saves_session_then_closes_it(self):
        self.assertEqual(self.run_cli("start", "--task", "Fix authentication")[0], 0)
        self.assertEqual(
            self.run_cli("checkpoint", "--note", "Token refresh is broken")[0], 0
        )
        code, output, _ = self.run_cli("archive")
        self.assertEqual(code, 0)
        self.assertIn("Active session closed.", output)
        self.assertFalse((self.root / ".worktrail" / "session.json").exists())
        self.assertEqual(
            len(list((self.root / ".worktrail" / "archive").glob("*.json"))), 1
        )

    def test_archive_does_not_replace_concurrent_archive_entry(self):
        import os

        self.run_cli("start", "--task", "Concurrent archive")
        archive_dir = self.root / ".worktrail" / "archive"
        real_link = os.link
        created = []

        def create_competing_entry(source, destination):
            destination = Path(destination)
            if not created:
                destination.write_bytes(b"existing archive entry")
                created.append(destination)
            return real_link(source, destination)

        with patch("worktrail.cli.os.link", side_effect=create_competing_entry):
            code, _, error = self.run_cli("archive")

        self.assertEqual(code, 0, error)
        self.assertTrue((self.root / ".worktrail" / "session.json").exists() is False)
        self.assertEqual(created[0].read_bytes(), b"existing archive entry")
        archived = [path for path in archive_dir.glob("*.json") if path != created[0]]
        self.assertEqual(len(archived), 1)
        self.assertEqual(json.loads(archived[0].read_text(encoding="utf-8"))["task"], "Concurrent archive")
        self.assertEqual(list(archive_dir.glob(".worktrail-archive-*.tmp")), [])

    def test_archive_publish_failure_keeps_active_session(self):
        self.run_cli("start", "--task", "Keep this session")
        current = self.root / ".worktrail" / "session.json"

        with patch("worktrail.cli.os.link", side_effect=OSError("disk unavailable")):
            code, _, error = self.run_cli("archive")

        self.assertEqual(code, 1)
        self.assertIn("disk unavailable", error)
        self.assertTrue(current.exists())
        self.assertEqual(json.loads(current.read_text(encoding="utf-8"))["task"], "Keep this session")
        archive_dir = self.root / ".worktrail" / "archive"
        self.assertEqual(list(archive_dir.glob("*.json")), [])
        self.assertEqual(list(archive_dir.glob(".worktrail-archive-*.tmp")), [])

    def test_archive_requires_active_session(self):
        code, _, error = self.run_cli("archive")
        self.assertEqual(code, 1)
        self.assertIn("No active session", error)

    def test_search_finds_archived_task_and_note_case_insensitively(self):
        self.assertEqual(self.run_cli("start", "--task", "Fix Authentication")[0], 0)
        self.assertEqual(
            self.run_cli("checkpoint", "--note", "Token refresh is broken")[0], 0
        )
        self.assertEqual(self.run_cli("archive")[0], 0)

        code, output, _ = self.run_cli("search", "authentication")
        self.assertEqual(code, 0)
        self.assertIn("Fix Authentication", output)
        self.assertIn("archive:", output)

        code, output, _ = self.run_cli("search", "TOKEN REFRESH")
        self.assertEqual(code, 0)
        self.assertIn("Token refresh is broken", output)

    def test_search_reports_no_matches(self):
        self.assertEqual(self.run_cli("start", "--task", "Write documentation")[0], 0)
        code, output, _ = self.run_cli("search", "nothing-like-this")
        self.assertEqual(code, 0)
        self.assertIn("No matches", output)

    def test_search_rejects_blank_query(self):
        code, _, error = self.run_cli("search", "   ")
        self.assertEqual(code, 2)
        self.assertIn("cannot be empty", error)


    def test_context_command_prints_agent_ready_handoff(self):
        self.assertEqual(self.run_cli("start", "--task", "Fix login")[0], 0)
        self.assertEqual(
            self.run_cli("checkpoint", "--note", "Refresh token expires")[0], 0
        )
        code, output, error = self.run_cli(
            "context", "--next", "Add expired-token tests"
        )
        self.assertEqual(code, 0, error)
        self.assertIn("# Work handoff: Fix login", output)
        self.assertIn("Refresh token expires", output)
        self.assertIn("Add expired-token tests", output)

    def test_timeline_includes_current_and_archived_sessions(self):
        self.assertEqual(self.run_cli("start", "--task", "Fix login")[0], 0)
        self.assertEqual(self.run_cli("archive")[0], 0)
        self.assertEqual(self.run_cli("start", "--task", "Write docs")[0], 0)
        code, output, error = self.run_cli("timeline")
        self.assertEqual(code, 0, error)
        self.assertIn("Fix login", output)
        self.assertIn("Write docs", output)
        self.assertIn("archive:", output)
        self.assertIn("current", output)

    def test_timeline_skips_malformed_and_non_utf8_archive_records(self):
        self.assertEqual(self.run_cli("start", "--task", "Healthy session")[0], 0)
        archive = self.root / ".worktrail" / "archive"
        archive.mkdir(parents=True)
        (archive / "broken-json.json").write_text("{broken", encoding="utf-8")
        (archive / "broken-encoding.json").write_bytes(b"\\xff\\xfe")

        code, output, error = self.run_cli("timeline")

        self.assertEqual(code, 0, error)
        self.assertIn("Healthy session", output)
        self.assertIn("Warning: skipped archive:broken-json.json", error)
        self.assertIn("Warning: skipped archive:broken-encoding.json", error)

    def test_export_skips_bad_archive_and_keeps_valid_records(self):
        self.assertEqual(self.run_cli("start", "--task", "Healthy session")[0], 0)
        archive = self.root / ".worktrail" / "archive"
        archive.mkdir(parents=True)
        (archive / "broken.json").write_text("{broken", encoding="utf-8")
        valid = {
            "task": "Archived session",
            "started_at": "2026-11-06T10:00:00+00:00",
            "checkpoint_at": "2026-11-06T11:00:00+00:00",
            "notes": [],
            "branch": "main",
            "git_status": "",
        }
        (archive / "valid.json").write_text(
            __import__("json").dumps(valid), encoding="utf-8"
        )
        destination = self.root / "export.json"

        code, output, error = self.run_cli("export", str(destination))

        self.assertEqual(code, 0, error)
        self.assertIn("Exported 2 session record(s)", output)
        self.assertIn("Warning: skipped archive:broken.json", error)
        exported = __import__("json").loads(destination.read_text(encoding="utf-8"))
        self.assertEqual(
            [record["session"]["task"] for record in exported["sessions"]],
            ["Healthy session", "Archived session"],
        )

    def test_timeline_still_reports_corrupt_current_session_and_backup(self):
        worktrail = self.root / ".worktrail"
        worktrail.mkdir()
        current = worktrail / "session.json"
        backup = worktrail / "session.json.bak"

        current.write_text("{broken", encoding="utf-8")
        code, _, error = self.run_cli("timeline")
        self.assertEqual(code, 1)
        self.assertIn("Cannot read session", error)

        current.unlink()
        backup.write_bytes(bytes((0xff, 0xfe)))
        code, _, error = self.run_cli("timeline")
        self.assertEqual(code, 1)
        self.assertIn("not valid UTF-8", error)

    def test_export_and_import_round_trip_without_overwriting(self):
        self.assertEqual(self.run_cli("start", "--task", "Fix login")[0], 0)
        self.assertEqual(
            self.run_cli("checkpoint", "--note", "Add token tests")[0], 0
        )
        bundle = self.root / "worktrail-export.json"
        code, output, error = self.run_cli("export", str(bundle))
        self.assertEqual(code, 0, error)
        self.assertIn("Exported 2 session record(s)", output)
        self.assertTrue(bundle.is_file())

        code, output, error = self.run_cli("import", str(bundle))
        self.assertEqual(code, 0, error)
        self.assertIn("Imported 2 session record(s)", output)
        archived = list((self.root / ".worktrail" / "archive").glob("*.json"))
        self.assertEqual(len(archived), 2)
        self.assertTrue(any("Fix login" in path.read_text(encoding="utf-8") for path in archived))

    def test_export_refuses_to_overwrite_existing_file(self):
        self.assertEqual(self.run_cli("start", "--task", "Fix login")[0], 0)
        target = self.root / "existing.json"
        target.write_text("keep me", encoding="utf-8")
        code, _, error = self.run_cli("export", str(target))
        self.assertEqual(code, 1)
        self.assertIn("File exists", error)
        self.assertEqual(target.read_text(encoding="utf-8"), "keep me")

    def test_export_cleans_temporary_file_when_atomic_publish_fails(self):
        from unittest.mock import patch

        self.assertEqual(self.run_cli("start", "--task", "Export safely")[0], 0)
        target = self.root / "nested" / "worktrail-export.json"

        with patch("worktrail.cli.os.link", side_effect=OSError("simulated publish failure")):
            code, _, error = self.run_cli("export", str(target))

        self.assertEqual(code, 1)
        self.assertIn("simulated publish failure", error)
        self.assertFalse(target.exists())
        self.assertEqual(list(target.parent.glob(".worktrail-export-*.tmp")), [])

    def test_export_does_not_replace_destination_created_before_publish(self):
        from unittest.mock import patch

        self.assertEqual(self.run_cli("start", "--task", "Export safely")[0], 0)
        target = self.root / "racing-export.json"
        real_link = __import__("os").link

        def create_destination_then_link(source, destination):
            target.write_text("keep this exact content", encoding="utf-8")
            return real_link(source, destination)

        with patch("worktrail.cli.os.link", side_effect=create_destination_then_link):
            code, _, error = self.run_cli("export", str(target))

        self.assertEqual(code, 1)
        self.assertIn("File exists", error)
        self.assertEqual(target.read_text(encoding="utf-8"), "keep this exact content")
        self.assertEqual(list(self.root.glob(".worktrail-export-*.tmp")), [])

    def test_import_cleans_temporary_file_when_atomic_publish_fails(self):
        import json

        source = self.root / "bundle.json"
        source.write_text(
            json.dumps({
                "format": "worktrail-session-bundle",
                "version": 1,
                "sessions": [{
                    "source": "current",
                    "session": {
                        "task": "Keep existing archive",
                        "started_at": "2026-11-05T10:00:00+00:00",
                        "checkpoint_at": "2026-11-05T11:00:00+00:00",
                        "notes": [],
                        "branch": "main",
                        "git_status": ""
                    }
                }]
            }),
            encoding="utf-8",
        )
        archive = self.root / ".worktrail" / "archive"
        archive.mkdir(parents=True)
        existing = archive / "import-20261105T1100000000-keep-existing-archive.json"
        existing.write_text("keep this exact content", encoding="utf-8")

        with patch("worktrail.cli.os.link", side_effect=OSError("simulated publish failure")):
            code, _, error = self.run_cli("import", str(source))

        self.assertEqual(code, 1)
        self.assertIn("simulated publish failure", error)
        self.assertEqual(existing.read_text(encoding="utf-8"), "keep this exact content")
        self.assertEqual(list(archive.glob("*.tmp")), [])
        self.assertEqual(list(archive.glob("*.json")), [existing])

    def test_import_publishes_complete_file_and_preserves_colliding_archive_entry(self):
        import json

        source = self.root / "bundle.json"
        session = {
            "task": "Keep existing archive",
            "started_at": "2026-11-05T10:00:00+00:00",
            "checkpoint_at": "2026-11-05T11:00:00+00:00",
            "notes": [],
            "branch": "main",
            "git_status": ""
        }
        source.write_text(json.dumps({
            "format": "worktrail-session-bundle",
            "version": 1,
            "sessions": [{"source": "current", "session": session}]
        }), encoding="utf-8")
        archive = self.root / ".worktrail" / "archive"
        archive.mkdir(parents=True)
        existing = archive / "import-20261105T1100000000-keep-existing-archive.json"
        existing.write_text("keep this exact content", encoding="utf-8")

        code, _, error = self.run_cli("import", str(source))

        self.assertEqual(code, 0, error)
        self.assertEqual(existing.read_text(encoding="utf-8"), "keep this exact content")
        imported = archive / "import-20261105T1100000000-keep-existing-archive-2.json"
        self.assertEqual(json.loads(imported.read_text(encoding="utf-8")), session)
        self.assertEqual(list(archive.glob("*.tmp")), [])

    def test_import_rejects_unknown_format_without_writing_archive(self):
        source = self.root / "bad.json"
        source.write_text('{"format":"other","version":1,"sessions":[]}', encoding="utf-8")
        code, _, error = self.run_cli("import", str(source))
        self.assertEqual(code, 1)
        self.assertIn("Unsupported Worktrail export format", error)
        self.assertFalse((self.root / ".worktrail" / "archive").exists())


    def test_doctor_json_emits_structured_success_report(self):
        import json
        from unittest.mock import Mock

        with patch(
            "worktrail.cli.subprocess.run",
            return_value=Mock(returncode=0, stdout="", stderr=""),
        ):
            code, output, error = self.run_cli("doctor", "--json")

        self.assertEqual(code, 0, error)
        report = json.loads(output)
        self.assertTrue(report["ok"])
        self.assertEqual(
            {item["name"] for item in report["checks"]},
            {"Git repository", "Session", ".worktrail ignored"},
        )
        for item in report["checks"]:
            self.assertEqual(set(item), {"name", "ok", "message"})
            self.assertIsInstance(item["ok"], bool)
            self.assertIsInstance(item["message"], str)
        self.assertNotIn("[OK]", output)

    def test_doctor_json_preserves_failure_exit_code(self):
        import json

        with patch("worktrail.cli.shutil.which", return_value=None):
            code, output, error = self.run_cli("doctor", "--json")

        self.assertEqual(code, 1, error)
        report = json.loads(output)
        self.assertFalse(report["ok"])
        self.assertTrue(any(not item["ok"] for item in report["checks"]))

    def test_doctor_default_output_remains_human_readable(self):
        from unittest.mock import Mock

        with patch(
            "worktrail.cli.subprocess.run",
            return_value=Mock(returncode=0, stdout="", stderr=""),
        ):
            code, output, error = self.run_cli("doctor")

        self.assertEqual(code, 0, error)
        self.assertIn("[OK] Git repository:", output)
        self.assertNotIn('"checks"', output)


if __name__ == "__main__":
    unittest.main()
