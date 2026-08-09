"""Local app configuration for djsupport."""

from __future__ import annotations

import json
import os
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from djsupport.paths import default_app_data_path

CONFIG_VERSION = 1
CONFIG_FILENAME = "config.json"
LEGACY_CONFIG_FILENAME = ".djsupport_config.json"


def default_config_path() -> Path:
    """Return the canonical private application-data configuration path."""
    return default_app_data_path() / CONFIG_FILENAME


DEFAULT_CONFIG_PATH = str(default_config_path())


@dataclass
class AppConfig:
    rekordbox_xml_path: str | None = None
    last_set_at: str | None = None


@dataclass(frozen=True)
class ConfigMigrationResult:
    status: str
    applied: bool = False


class ConfigManager:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else default_config_path()
        self.config = AppConfig()

    def load(self) -> None:
        """Load config from disk. No-op if file doesn't exist or is invalid."""
        if not self.path.exists():
            return
        loaded = self._read_valid(self.path)
        if loaded is not None:
            self.config = loaded

    @staticmethod
    def _read_valid(path: Path) -> AppConfig | None:
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None
        if not isinstance(data, dict):
            return None
        if data.get("version") != CONFIG_VERSION:
            return None
        for field in ("rekordbox_xml_path", "last_set_at"):
            if data.get(field) is not None and not isinstance(
                data.get(field), str
            ):
                return None
        return AppConfig(
            rekordbox_xml_path=data.get("rekordbox_xml_path"),
            last_set_at=data.get("last_set_at"),
        )

    def migrate_legacy(self, *, apply: bool = False) -> ConfigMigrationResult:
        """Preview or apply migration from the exact current-directory file."""
        legacy_path = Path.cwd() / LEGACY_CONFIG_FILENAME
        if legacy_path.is_symlink():
            return ConfigMigrationResult("invalid")
        if not legacy_path.exists():
            return ConfigMigrationResult("not_found")
        legacy_config = self._read_valid(legacy_path)
        if legacy_config is None:
            return ConfigMigrationResult("invalid")
        if self.path.exists():
            current_config = self._read_valid(self.path)
            status = (
                "already_current"
                if current_config == legacy_config
                else "conflict"
            )
            return ConfigMigrationResult(status)
        if apply:
            self.config = legacy_config
            self.save()
            return ConfigMigrationResult("migrated", applied=True)
        return ConfigMigrationResult("ready")

    def save(self) -> None:
        """Write config to disk."""
        data = {"version": CONFIG_VERSION, **asdict(self.config)}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent,
                prefix=f".{self.path.name}.", delete=False,
            ) as temporary:
                json.dump(data, temporary, indent=2)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

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
