"""Canonical private application-data paths."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _absolute_environment_path(name: str, fallback: Path) -> Path:
    """Return an absolute configured root, or a known private fallback."""
    value = os.environ.get(name)
    if value:
        candidate = Path(value)
        if candidate.is_absolute():
            return candidate
    return fallback


def default_app_data_path() -> Path:
    """Return the private, user-local application-data directory."""
    if sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    elif sys.platform == "win32":
        root = _absolute_environment_path(
            "LOCALAPPDATA", Path.home() / "AppData" / "Local",
        )
    else:
        root = _absolute_environment_path(
            "XDG_DATA_HOME", Path.home() / ".local" / "share",
        )
    return root / "djsupport"
