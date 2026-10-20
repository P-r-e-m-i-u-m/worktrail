"""Local-first development session tracker."""
import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from . import __version__


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")



def _decode_git_path(path):
    """Decode a path quoted by Git's short status output."""
    if not (path.startswith('"') and path.endswith('"')):
        return path

    value = path[1:-1]
    decoded = bytearray()
    i = 0

    escapes = {
        '"': 34,
        "\\": 92,
        "a": 7,
        "b": 8,
        "t": 9,
        "n": 10,
        "v": 11,
        "f": 12,
        "r": 13,
    }

    while i < len(value):
        if value[i] != "\\":
            decoded.extend(value[i].encode("utf-8"))
            i += 1
            continue

        i += 1
        if i >= len(value):
            decoded.append(92)
            break

        char = value[i]

        if char in "01234567":
            digits = char
            i += 1

            while (
                i < len(value)
                and len(digits) < 3
                and value[i] in "01234567"
            ):
                digits += value[i]
                i += 1

            decoded.append(int(digits, 8))
        else:
            decoded.append(escapes.get(char, ord(char)))
            i += 1

    return decoded.decode("utf-8", errors="surrogateescape")


def _split_rename_path(path):
    """Split a rename entry at the separator outside quoted paths."""
    quoted = False
    escaped = False

    for i, char in enumerate(path):
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif path.startswith(" -> ", i):
            return path[:i], path[i + 4:]

    return None

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


def load_path(path):
    """Load and validate a session file without guessing at malformed data."""
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


def load(root):
    """Load the current session, if one exists."""
    return load_path(session_file(root))


def backup_file(root):
    return session_file(root).with_suffix(".json.bak")


def save(root, data):
    """Atomically save a session and preserve the previous valid version."""
    path = session_file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    backup = backup_file(root)
    backup_temporary = backup.with_suffix(".tmp")

    if path.exists():
        # Preserve the previous session before replacing it. Never overwrite
        # a backup until its complete contents have been written.
        backup_temporary.write_bytes(path.read_bytes())
        backup_temporary.replace(backup)

    temporary.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def recover(root):
    """Restore a valid backup only when the current session is absent."""
    current = session_file(root)
    backup = backup_file(root)

    if current.exists():
        raise ValueError(
            "A session already exists. Recovery will not overwrite it; "
            "move the current session aside yourself if you need the backup."
        )

    data = load_path(backup)
    if data is None:
        raise ValueError("No recovery backup found.")

    # Revalidate and write a new current session without touching the backup.
    current.parent.mkdir(parents=True, exist_ok=True)
    temporary = current.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(current)
    return data


def require_session(root):
    data = load(root)

    if data is None:
        raise ValueError("No session found. Run 'worktrail start' first.")

    return data


def run_doctor(root):
    """Check common Worktrail setup issues without changing files."""
    checks = []

    git_executable = shutil.which("git")

    if git_executable is None:
        checks.append(
            (
                "Git repository",
                False,
                "Git was not found on PATH. Install Git and ensure it is available on PATH.",
            )
        )
        checks.append(
            (
                ".worktrail ignored",
                False,
                "Cannot check ignore rules because Git is not available on PATH",
            )
        )
    else:
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

    if git_executable is not None:
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


def archive_session(root):
    """Save the active session to the archive, then close it."""
    current = session_file(root)
    data = load_path(current)
    if data is None:
        raise ValueError("No active session to archive. Run 'worktrail start' first.")

    archive_dir = root / ".worktrail" / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slug = "-".join(data["task"].lower().split())
    slug = "".join(c for c in slug if c.isalnum() or c == "-")[:48].strip("-")
    slug = slug or "session"
    target = archive_dir / f"{stamp}-{slug}.json"
    counter = 2
    while target.exists():
        target = archive_dir / f"{stamp}-{slug}-{counter}.json"
        counter += 1

    temporary = target.with_suffix(".tmp")
    try:
        temporary.write_text(
            json.dumps(data, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.rename(target)
        current.unlink()
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise

    return target


def search_sessions(root, query):
    """Search tasks and notes in the current session, backup, and archives."""
    query = query.strip()
    if not query:
        print("Search query cannot be empty.", file=sys.stderr)
        return 2

    worktrail_dir = root / ".worktrail"
    sources = [
        ("current session", session_file(root)),
        ("previous backup", backup_file(root)),
    ]
    archive_dir = worktrail_dir / "archive"
    if archive_dir.is_dir():
        sources.extend(
            (f"archive: {path.name}", path)
            for path in sorted(archive_dir.glob("*.json"))
        )

    needle = query.casefold()
    count = 0
    for label, path in sources:
        if not path.is_file():
            continue
        try:
            data = load_path(path)
        except (ValueError, OSError) as exc:
            if label.startswith("archive:"):
                print(f"Warning: skipped {label}: {exc}", file=sys.stderr)
                continue
            raise
        if data is None:
            continue

        task_hit = needle in data["task"].casefold()
        note_hits = [
            note for note in data["notes"]
            if needle in note["text"].casefold()
        ]
        if not task_hit and not note_hits:
            continue

        count += 1
        print(f"Session: {label}")
        print(f"Task: {data['task']}")
        print(f"Started: {data['started_at']}")
        if task_hit:
            print("Match: task")
        for note in note_hits:
            print(f"Match: note [{note['at']}]: {note['text']}")
        print()

    if not count:
        print(f"No matches for '{query}'.")
    return 0


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
    commands.add_parser("summary", help="Show a compact session overview")
    commands.add_parser("archive", help="Archive and close the active session")
    search = commands.add_parser("search", help="Search tasks and notes across sessions")
    search.add_argument("query", help="Text to search in tasks and notes")
    commands.add_parser(
        "history",
        help="Show the current session and its previous saved version",
    )
    commands.add_parser(
        "diff",
        help="Compare the current session with its previous saved version",
    )
    commands.add_parser(
        "recover",
        help="Restore a missing session from its last saved backup",
    )
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
        if args.command == "archive":
            archived = archive_session(root)
            print(f"Session archived: {archived.name}")
            print("Active session closed.")
            return 0

        if args.command == "search":
            return search_sessions(root, args.query)

        if args.command == "doctor":
            return run_doctor(root)

        if args.command == "recover":
            data = recover(root)
            print(f"Session recovered: {data['task']}")
            print("Recovery backup was kept unchanged.")
            return 0

        if args.command in ("history", "diff"):
            current_path = session_file(root)
            backup_path = backup_file(root)
            current = load_path(current_path)
            previous = load_path(backup_path)

            if args.command == "diff":
                if current is None or previous is None:
                    raise ValueError(
                        "Session comparison needs both a current session and a valid backup. "
                        "Create another checkpoint first."
                    )

                previous_notes = {
                    (note["at"], note["text"]) for note in previous["notes"]
                }
                current_notes = {
                    (note["at"], note["text"]) for note in current["notes"]
                }
                added = [
                    note for note in current["notes"]
                    if (note["at"], note["text"]) not in previous_notes
                ]
                removed = [
                    note for note in previous["notes"]
                    if (note["at"], note["text"]) not in current_notes
                ]
                changed = False

                if current["task"] != previous["task"]:
                    print("Task changed:")
                    print(f"  Previous: {previous['task']}")
                    print(f"  Current:  {current['task']}")
                    changed = True
                if added:
                    print("Notes added:")
                    for note in added:
                        print(f"  + [{note['at']}] {note['text']}")
                    changed = True
                if removed:
                    print("Notes missing from current session:")
                    for note in removed:
                        print(f"  - [{note['at']}] {note['text']}")
                    changed = True
                if not changed:
                    print("No task or note changes from the previous saved version.")
                return 0

            if current is None and previous is None:
                raise ValueError("No current session or recovery backup found.")

            if current is not None:
                print("Current session")
                print(f"  Task:       {current['task']}")
                print(f"  Checkpoint: {current['checkpoint_at']}")
                print(f"  Notes:      {len(current['notes'])}")
            else:
                print("Current session: missing")

            if previous is not None:
                print("\nPrevious saved version (session.json.bak)")
                print(f"  Task:       {previous['task']}")
                print(f"  Checkpoint: {previous['checkpoint_at']}")
                print(f"  Notes:      {len(previous['notes'])}")
            elif backup_path.exists():
                print("\nPrevious saved version: backup exists but is invalid")
            else:
                print("\nPrevious saved version: no backup yet")
            return 0

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

        if args.command == "summary":
            print("Task:       {}".format(data["task"]))
            print("Started:    {}".format(data["started_at"]))
            print("Checkpoint: {}".format(data["checkpoint_at"]))
            print("Notes:      {}".format(len(data["notes"])))
            print("Branch:     {}".format(data.get("branch") or "unavailable"))
            if data["notes"]:
                print("Latest note: {}".format(data["notes"][-1]["text"]))
            else:
                print("Latest note: none yet")
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

                git_status = current.get("git_status") or ""
                changed_paths = []

                for line in git_status.splitlines():
                    if len(line) < 4:
                        continue

                    status = line[:2]
                    path = line[3:]

                    if "R" in status or "C" in status:
                        rename_paths = _split_rename_path(path)
                        if rename_paths is not None:
                            _, path = rename_paths

                    path = _decode_git_path(path)

                    if path:
                        changed_paths.append(path)

                if changed_paths:
                    print("Changed files:")
                    for path in changed_paths:
                        print(f"  - {path}")

            else:
                print("Working tree matches the last checkpoint.")

            return 0

    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
