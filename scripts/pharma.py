#!/usr/bin/env python3
"""PharmaScount commands without changing the existing root setup/dev workflow."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
PYTHON = BACKEND / (
    ".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python"
)


def main():
    if not PYTHON.exists():
        raise SystemExit("Backend environment missing; run make install first.")
    env = {**os.environ, "PYTHONPATH": str(BACKEND)}
    action = sys.argv[1] if len(sys.argv) > 1 else "help"
    if action in {"migrate", "seed-demo", "create-user"}:
        command = [str(PYTHON), "-m", "app.pharma.cli", action, *sys.argv[2:]]
    elif action == "worker":
        command = [str(PYTHON), "-m", "app.pharma.worker"]
    elif action == "test":
        # Load private integration URL without placing it in argv or output.
        from dotenv import dotenv_values

        values = dotenv_values(ROOT / ".deer-flow/pharma/private.env")
        if values.get("PHARMA_TEST_DATABASE_URL"):
            env["PHARMA_TEST_DATABASE_URL"] = values["PHARMA_TEST_DATABASE_URL"]
        files = sorted(
            str(p.relative_to(BACKEND))
            for p in (BACKEND / "tests").glob("test_pharma*.py")
        )
        command = [
            str(PYTHON),
            "-m",
            "pytest",
            *files,
            "-m",
            "not live",
            "-q",
            *sys.argv[2:],
        ]
    elif action == "verify-docs":
        command = [
            str(PYTHON),
            str(ROOT / "docs/reference/pharma-intelligence/scripts/verify_context.py"),
        ]
    else:
        raise SystemExit(
            "Usage: pharma.py migrate|seed-demo|create-user|worker|test|verify-docs"
        )
    return subprocess.call(command, cwd=BACKEND, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
