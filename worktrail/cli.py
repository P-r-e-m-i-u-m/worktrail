"""Local-first development session tracker."""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import __version__


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def snapshot(root):
    """Capture Git context without changing the repository."""
    result = {"branch": None, "git_status": None}
    for key, args in (
        ("branch", ["branch", "--show-current"]),
        ("git_status", ["status", "--short", "--untracked-files=all"]),
    ):
        try:
            proc = subprocess.run(
                ["git", "-C", str(root), *args],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if proc.returncode == 0:
                result[key] = proc.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
    return result


def session_file(root):
    return root / ".worktrail" / "session.json"


def load(root):
    """Load a session, rejecting malformed data instead of guessing."""
    path = session_file(root)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read session: {exc}") from exc

    if (
        not isinstance(data, dict)
        or not isinstance(data.get("task"), str)
        or not data["task"].strip()
        or not isinstance(data.get("started_at"), str)
        or not isinstance(data.get("checkpoint_at"), str)
        or not isinstance(data.get("notes"), list)
        or any(
            not isinstance(note, dict)
            or not isinstance(note.get("at"), str)
            or not isinstance(note.get("text"), str)
            for note in data["notes"]
        )
    ):
        raise ValueError("Session file has an invalid format.")
    return data


def save(root, data):
    """Replace the session file only after the complete JSON is written."""
    path = session_file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def require_session(root):
    data = load(root)
    if data is None:
        raise ValueError("No session found. Run 'worktrail start' first.")
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="worktrail",
        description="Leave a trail for the next time you open your project.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    start = commands.add_parser("start", help="Start a session")
    start.add_argument("--task", required=True, help="What you're working on")

    checkpoint = commands.add_parser("checkpoint", help="Save your progress")
    checkpoint.add_argument("--note", help="Leave a note for future-you")

    commands.add_parser("resume", help="Show the saved session context")
    commands.add_parser("status", help="Compare Git state with your checkpoint")
    args = parser.parse_args(argv)
    root = Path.cwd()

    try:
        if args.command == "start":
            task = args.task.strip()
            if not task:
                raise ValueError("Task cannot be empty.")
            if load(root) is not None:
                raise ValueError(
                    "A session already exists. Run 'worktrail resume' to see it."
                )
            now = timestamp()
            data = {
                "task": task,
                "started_at": now,
                "checkpoint_at": now,
                "notes": [],
                **snapshot(root),
            }
            save(root, data)
            print(f"Session started: {task}")
            print("Leave a note any time with 'worktrail checkpoint --note \"...\"'.")
            return 0

        if args.command == "checkpoint":
            data = require_session(root)
            if args.note is not None:
                note = args.note.strip()
                if not note:
                    raise ValueError("Note cannot be empty.")
                data["notes"].append({"at": timestamp(), "text": note})
            data.update(snapshot(root))
            data["checkpoint_at"] = timestamp()
            save(root, data)
            print("Checkpoint saved.")
            if args.note is not None:
                print("Future-you will thank you.")
            return 0

        data = require_session(root)

        if args.command == "resume":
            print(f"Task:       {data['task']}")
            print(f"Started:    {data['started_at']}")
            print(f"Checkpoint: {data['checkpoint_at']}")
            print(f"Branch:     {data.get('branch') or 'unavailable'}")
            print("\nNotes:")
            if not data["notes"]:
                print("  Nothing written down yet.")
            for note in data["notes"]:
                print(f"  [{note['at']}] {note['text']}")
            return 0

        if args.command == "status":
            current = snapshot(root)
            print(f"Task:       {data['task']}")
            print(f"Checkpoint: {data['checkpoint_at']}")
            if current["branch"] is None:
                print("Git:        unavailable or not a repository")
                return 0

            print(f"Branch:     {current['branch']}")
            branch_changed = current["branch"] != data.get("branch")
            tree_changed = current["git_status"] != data.get("git_status")

            if branch_changed:
                print("Branch has changed since the last checkpoint.")
            else:
                print("Branch matches the last checkpoint.")

            if tree_changed:
                print("Working tree has changed since the last checkpoint.")
            else:
                print("Working tree matches the last checkpoint.")
            return 0

    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
