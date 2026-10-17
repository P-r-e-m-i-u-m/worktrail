# Worktrail

**Pick up where your last coding session left off.**

Worktrail is a small, local-first CLI for keeping track of what you're working on, what you last saved, and whether your Git working tree has changed since then.

No account. No hosted service. No extra runtime dependencies.

## What it does

- **Start a session** with a task description.
- **Save a checkpoint** with an optional progress note.
- **Resume your context** when you return to the project.
- **Compare Git state** with the last checkpoint.

Session data lives in `.worktrail/session.json` inside the current working directory.

## Quick start

Python 3.10 or newer is required.

Install from a local clone:

```powershell
python -m pip install .
```

Start a session from the root of your project:

```powershell
worktrail start --task "Fix login flow"
```

Save your progress:

```powershell
worktrail checkpoint --note "Login tests still failing"
```

Return to your saved context:

```powershell
worktrail resume
```

Check whether your Git state has changed:

```powershell
worktrail status
```

You can also run Worktrail without installing its command:

```powershell
python -m worktrail start --task "Fix login flow"
```

## A note on Git

Worktrail records the current branch and short Git status when a session starts or a checkpoint is saved. `worktrail status` compares that snapshot with the current Git state.

It reports changes in the working tree; it does not save your code, create commits, or restore files.

## Development

Run the test suite:

```powershell
python -m unittest discover -s tests -v
```

Build a package:

```powershell
python -m build
```

## Project status

Worktrail is an early project. Its interface and saved session format may change as it develops.

## License

MIT
