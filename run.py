#!/usr/bin/env python3
import os
import sys
from pathlib import Path


def _restart_in_project_venv():
    """Use the project environment automatically when launched from a shortcut."""
    root = Path(__file__).resolve().parent
    project_venv = (root / ".venv").resolve()
    if Path(sys.prefix).resolve() == project_venv:
        return
    candidates = (
        root / ".venv" / "bin" / "python",
        root / ".venv" / "Scripts" / "python.exe",
    )
    for python in candidates:
        if python.exists():
            os.execv(str(python), [str(python), *sys.argv])


_restart_in_project_venv()

from src.codex_monitor.main import main

if __name__ == "__main__":
    main()
