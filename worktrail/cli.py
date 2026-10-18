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


def run_doctor(root):
    """Check common Worktrail setup issues without changing files."""
    checks = []

    git = snapshot(root)
    git_available = git["branch"] is not None

    checks.append(
        (
            "Git repository",
            git_available,
            "Git context available"
            if git_available
            else "Not inside a Git repository",
        )
    )

    try:
        data = load(root)

        if data is None:
            checks.append(
                (
                    "Session",
                    True,
                    "No session yet. Run 'worktrail start --task \"...\"'.",
                )
            )
        else:
            checks.append(
                ("Session", True, f"Session found: {data['task']}")
            )

    except (ValueError, OSError) as exc:
        checks.append(("Session", False, str(exc)))

    try:
        proc = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "check-ignore",
                "--quiet",
                "--",
                ".worktrail/session.json",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

        if proc.returncode == 0:
            ignored = True
            message = "Git rules ignore .worktrail/session.json"
        elif proc.returncode == 1:
            ignored = False
            message = (
                "Git does not ignore .worktrail/session.json; "
                "add .worktrail/ to an applicable ignore file"
            )
        else:
            ignored = False
            detail = proc.stderr.strip() or "Git could not evaluate ignore rules"
            message = detail

        checks.append((".worktrail ignored", ignored, message))

    except (OSError, subprocess.TimeoutExpired) as exc:
        checks.append((".worktrail ignored", False, str(exc)))

    for name, passed, message in checks:
        marker = "OK" if passed else "WARN"
        print(f"[{marker}] {name}: {message}")

    return 0 if all(passed for _, passed, _ in checks) else 1



def render_handoff(data, current, next_step=None):
    """Build a portable Markdown summary of the current work session."""
    lines = [
        f"# Work handoff: {data['task']}",
        "",
        "## Current task",
        data["task"],
        "",
        "## Session",
        f"- Started: {data['started_at']}",
        f"- Last checkpoint: {data['checkpoint_at']}",
        f"- Current branch: {current.get('branch') or 'unavailable'}",
        "",
        "## Git working tree",
    ]

    status = current.get("git_status")
    if current.get("branch") is None:
        lines.append("Git context is unavailable or this is not a repository.")
    elif status:
        lines.extend(["```text", status, "```"])
    else:
        lines.append("Working tree is clean.")

    lines.extend(["", "## Notes"])
    if data["notes"]:
        for note in data["notes"]:
            lines.append(f"- [{note['at']}] {note['text']}")
    else:
        lines.append("- No notes recorded yet.")

    lines.extend(["", "## Next step"])
    lines.append(next_step if next_step else "Not recorded yet.")
    lines.extend([
        "",
        "## Instructions for the next session",
        "Continue from the context above. Inspect the current code before editing,",
        "preserve existing work, and run focused tests before reporting completion.",
        "",
    ])
    return "\n".join(lines)


def write_handoff(path, content):
    """Create a handoff file without overwriting an existing file."""
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(content)

def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="worktrail",
        description="Leave a trail for the next time you open your project.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    commands = parser.add_subparsers(dest="command", required=True)

    start = commands.add_parser("start", help="Start a session")
    start.add_argument("--task", required=True, help="What you're working on")

    checkpoint = commands.add_parser(
        "checkpoint",
        help="Save your progress",
    )
    checkpoint.add_argument("--note", help="Leave a note for future-you")

    commands.add_parser("resume", help="Show the saved session context")
    commands.add_parser(
        "status",
        help="Compare Git state with your checkpoint",
    )
    commands.add_parser(
        "doctor",
        help="Check this project's Worktrail setup",
    )

    handoff = commands.add_parser(
        "handoff",
        help="Prepare a Markdown handoff for your next coding session",
    )
    handoff.add_argument(
        "--next",
        dest="next_step",
        help="Record the next step without making Worktrail guess",
    )
    handoff.add_argument(
        "--output",
        type=Path,
        help="Save the handoff to a new file instead of printing it",
    )

    args = parser.parse_args(argv)
    root = Path.cwd()

    try:
        if args.command == "doctor":
            return run_doctor(root)

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
            print(
                "Leave a note any time with "
                "'worktrail checkpoint --note \"...\"'."
            )
            return 0

        if args.command == "checkpoint":
            data = require_session(root)

            if args.note is not None:
                note = args.note.strip()

                if not note:
                    raise ValueError("Note cannot be empty.")

                data["notes"].append(
                    {"at": timestamp(), "text": note}
                )

            data.update(snapshot(root))
            data["checkpoint_at"] = timestamp()
            save(root, data)

            print("Checkpoint saved.")

            if args.note is not None:
                print("Future-you will thank you.")

            return 0

        data = require_session(root)

        if args.command == "handoff":
            next_step = args.next_step
            if next_step is not None and not next_step.strip():
                raise ValueError("Next step cannot be empty.")

            content = render_handoff(
                data,
                snapshot(root),
                next_step=next_step.strip() if next_step is not None else None,
            )

            if args.output is not None:
                write_handoff(args.output, content)
                print(f"Handoff saved: {args.output}")
            else:
                print(content, end="")
            return 0

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