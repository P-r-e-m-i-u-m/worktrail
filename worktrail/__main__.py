"""Allow running Worktrail with python -m worktrail."""
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
