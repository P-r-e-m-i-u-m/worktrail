# Contributing to Worktrail

Thanks for giving Worktrail some of your time. The goal is to make useful contributions straightforward, whether this is your first pull request or your hundredth.

## Before you start

- Read the README and understand the behavior related to your change.
- Check existing issues and pull requests to avoid duplicate work.
- For a substantial change, open or comment on an issue before investing time in it.
- Keep the change focused. A small, complete fix is better than a broad rewrite.

## Development setup

Requirements: Python 3.10 or newer and Git.

From the repository root, create and activate a virtual environment:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

If PowerShell blocks environment activation, run the commands below without activating it, using `.venv\Scripts\python.exe` in place of `python`.

## Run the tests

```powershell
python -m unittest discover -s tests -v
```

Run this from the repository root. If a test fails, include the relevant failure output in your pull request and do not describe the test suite as passing.

## Making a change

1. Identify the behavior that needs to change and inspect the relevant code and tests.
2. Reproduce the issue or add a focused test when practical.
3. Make the smallest change that correctly addresses the problem.
4. Add or update tests for changed behavior, including meaningful edge cases.
5. Run the relevant tests, then the full test suite.
6. Review `git diff` and `git diff --check`.
7. Confirm that only intended files are staged and included.

Do not remove, reset, overwrite, or stage another contributor's unrelated work.

## Code expectations

- Keep changes consistent with the existing project structure and style.
- Prefer readable, straightforward Python over clever abstractions.
- Avoid adding dependencies unless they are necessary and justified.
- Preserve existing CLI behavior unless the change explicitly calls for a behavior change.
- Handle invalid input and expected failures with useful, understandable messages.
- Never claim that behavior or tests were verified unless you actually verified them.

## Pull requests

A good pull request explains the problem, the solution, and how the change was tested. Link the related issue when one exists. Include relevant command output or reproduction steps for fixes. Mention limitations or tests you could not run.

Keep unrelated formatting changes and drive-by refactors out of the patch.

## Questions and problems

If you are unsure about expected behavior, ask in the related issue before guessing. If you get stuck, share what you tried, what happened, and the smallest useful error output. A clear question is welcome here.