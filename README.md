<div align="center">

# Worktrail

**Close the laptop. Keep the thread.**

A tiny, local-first CLI for remembering what you were doing, what changed, and where to pick up next.

No account. No cloud sync. No project management ceremony.

</div>

---

You know the moment: you open a project, stare at the files, and spend the first 20 minutes trying to remember what you were doing.

Worktrail gives that context a home. Start a session, leave yourself a note, and come back to a useful snapshot instead of a blank stare.

## A small tool for the gap between sessions

```text
$ worktrail start --task "Untangle the login flow"
Session started: Untangle the login flow

$ worktrail checkpoint --note "API works; still need to cover expired tokens"
Checkpoint saved.

# Tomorrow, from the same project directory:
$ worktrail resume
Task: Untangle the login flow
Started: 2026-10-17T12:10:00+00:00
Checkpoint: 2026-10-17T12:42:00+00:00
Branch: feature/login

Notes:
  [2026-10-17T12:42:00+00:00] API works; still need to cover expired tokens
```

*Example output for illustration.*

## What it remembers

- **The task** you're working on
- **The last checkpoint** and when you saved it
- **Notes to future-you**, in your own words
- **A Git snapshot** of the branch and working-tree status

Worktrail stores this in `.worktrail/session.json` inside the current directory. Your session stays with the project on your machine. Worktrail does not commit, edit, or restore your source files.

## Get going

**You need Python 3.10 or newer.**

Clone the repository, open its folder, then install it:

```powershell
python -m pip install .
```

Start a session from the project you want to track:

```powershell
worktrail start --task "Build the settings page"
```

Leave a breadcrumb before you stop:

```powershell
worktrail checkpoint --note "Layout is done; wire up save state next"
```

When you come back:

```powershell
worktrail resume
worktrail status
```

Prefer not to install the command? Run it as a module from the repository:

```powershell
python -m worktrail start --task "Build the settings page"
```

## Commands

| Command | What it does |
| --- | --- |
| `worktrail start --task "..."` | Start a session in the current directory |
| `worktrail checkpoint` | Save a fresh Git snapshot |
| `worktrail checkpoint --note "..."` | Save a snapshot and a note |
| `worktrail resume` | Print the saved context and notes |
| `worktrail status` | Compare current Git state with the last checkpoint |

A session is not silently overwritten. If one already exists, resume it first. Session data is local and can be removed by deleting the project's `.worktrail` directory.

## Under the hood

Worktrail is intentionally boring in the right places:

- Python standard library at runtime
- Plain JSON you can inspect or back up
- No account, daemon, database, or network calls
- Git is queried for context, never used to change your repository

The Git snapshot is a point-in-time comparison, not a full history or a backup. Commit your code and back up your work separately.

## Hacking on Worktrail

Run the tests:

```powershell
python -m unittest discover -s tests -v
```

Build the distributable package:

```powershell
python -m pip install build
python -m build
```

## Where it is right now

Worktrail is an early, actively evolving project. The goal is to keep it useful, understandable, and small. If something feels clunky or missing, an issue with a concrete example is a great place to start.

## License

MIT. See [LICENSE](LICENSE).
