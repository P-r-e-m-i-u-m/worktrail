"""Local-first development session tracker."""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def snapshot(root):
    result = {"branch": None, "git_status": None}
    for key, args in (
        ("branch", ["branch", "--show-current"]),
        ("git_status", ["status", "--short", "--untracked-files=all"]),
    ):
        try:
            proc = subprocess.run(
                ["git", "-C", str(root), *args],
                capture_output=True, text=True, timeout=5, check=False,
            )
            if proc.returncode == 0:
                result[key] = proc.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
    return result


def session_file(root):
    return root / ".worktrail" / "session.json"


def load(root):
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
    path = session_file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def require_session(root):
    data = load(root)
    if data is None:
        raise ValueError("No session found. Run 'worktrail start' first.")
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="worktrail", description="Keep track of development sessions."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    start = commands.add_parser("start", help="Start a session")
    start.add_argument("--task", required=True)

    checkpoint = commands.add_parser("checkpoint", help="Save progress")
    checkpoint.add_argument("--note", help="Add a progress note")

    commands.add_parser("resume", help="Show saved session context")
    commands.add_parser("status", help="Compare Git state with checkpoint")
    args = parser.parse_args(argv)
    root = Path.cwd()

    try:
        if args.command == "start":
            task = args.task.strip()
            if not task:
                raise ValueError("Task cannot be empty.")
            if load(root) is not None:
                raise ValueError(
                    "A session already exists. Resume it before starting another."
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
            return 0

        if args.command == "checkpoint":
            data = require_session(root)
            if args.note is not None:
                if not args.note.strip():
                    raise ValueError("Note cannot be empty.")
                data["notes"].append({
                    "at": timestamp(), "text": args.note.strip()
                })
            data.update(snapshot(root))
            data["checkpoint_at"] = timestamp()
            save(root, data)
            print("Checkpoint saved.")
            return 0

        data = require_session(root)

        if args.command == "resume":
            print(f"Task: {data['task']}")
            print(f"Started: {data['started_at']}")
            print(f"Checkpoint: {data['checkpoint_at']}")
            print(f"Branch: {data.get('branch') or 'unavailable'}")
            print("\nNotes:")
            if not data["notes"]:
                print("  No notes yet.")
            for note in data["notes"]:
                print(f"  [{note['at']}] {note['text']}")
            return 0

        if args.command == "status":
            current = snapshot(root)
            print(f"Task: {data['task']}")
            print(f"Checkpoint: {data['checkpoint_at']}")
            if current["branch"] is None:
                print("Git: unavailable or not a repository")
            else:
                print(f"Branch: {current['branch']}")
                if current["branch"] != data.get("branch"):
                    print("Branch changed since checkpoint.")
                if current["git_status"] != data.get("git_status"):
                    print("Working tree changed since checkpoint.")
                else:
                    print("Working tree matches checkpoint.")
            return 0

    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
