"""Canonical private application-data paths."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def default_app_data_path() -> Path:
    """Return the private, user-local application-data directory."""
    if sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    elif os.name == "nt":
        root = Path(
            os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
        )
    else:
        root = Path(
            os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
        )
    return root / "djsupport"
