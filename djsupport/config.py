"""Local app configuration for djsupport."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

CONFIG_VERSION = 1
DEFAULT_CONFIG_PATH = ".djsupport_config.json"


@dataclass
class AppConfig:
    rekordbox_xml_path: str | None = None
    last_set_at: str | None = None


class ConfigManager:
    def __init__(self, path: str = DEFAULT_CONFIG_PATH):
        self.path = Path(path)
        self.config = AppConfig()

    def load(self) -> None:
        """Load config from disk. No-op if file doesn't exist or is invalid."""
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError):
            return
        if data.get("version") != CONFIG_VERSION:
            return
        self.config = AppConfig(
            rekordbox_xml_path=data.get("rekordbox_xml_path"),
            last_set_at=data.get("last_set_at"),
        )

    def save(self) -> None:
        """Write config to disk."""
        data = {"version": CONFIG_VERSION, **asdict(self.config)}
        self.path.write_text(json.dumps(data, indent=2))

    def get_rekordbox_xml_path(self) -> str | None:
        return self.config.rekordbox_xml_path

    def set_rekordbox_xml_path(self, path: str) -> None:
        self.config.rekordbox_xml_path = str(Path(path).expanduser())
        self.config.last_set_at = datetime.now().isoformat()


def validate_rekordbox_xml(path: str | Path) -> tuple[bool, str | None]:
    """Validate a Rekordbox XML file path and basic structure."""
    p = Path(path).expanduser()
    if not p.exists():
        return False, f"File not found: {p}"
    if not p.is_file():
        return False, f"Not a file: {p}"

    try:
        tree = ET.parse(p)
    except ET.ParseError as exc:
        return False, f"Invalid XML: {exc}"
    except OSError as exc:
        return False, f"Unable to read file: {exc}"

    root = tree.getroot()
    if root.find("COLLECTION") is None and root.find("PLAYLISTS") is None:
        return False, "XML parsed, but missing Rekordbox COLLECTION/PLAYLISTS nodes"
    return True, None
