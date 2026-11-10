"""Run every check CI runs, on any platform: ``uv run python scripts/check.py``."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHECKS = (
    ("ruff", "check", "."),
    ("ruff", "format", "--check", "."),
    ("mypy",),
    ("pytest", "-q"),
)


def main() -> int:
    for command in CHECKS:
        print(f"$ {' '.join(command)}", flush=True)
        if subprocess.run([sys.executable, "-m", *command], cwd=ROOT, check=False).returncode:
            return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
