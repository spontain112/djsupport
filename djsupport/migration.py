"""Explicit, privacy-safe migration of DJ Support 0.3.0 local data."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from djsupport.backup import LocalDataBackup


LEGACY_CACHE_FILES = (
    ".djsupport_cache.json",
    ".djsupport_beatport_cache.json",
)
LEGACY_STATE_FILES = (
    ".djsupport_playlists.json",
    ".djsupport_beatport_playlists.json",
)
CACHE_FIELDS = {
    "spotify_uri", "spotify_name", "spotify_artist", "score", "matched",
    "timestamp", "threshold", "match_type",
}
STATE_FIELDS = {
    "spotify_id", "spotify_name", "source_path", "last_synced",
    "prefix_used", "source_type",
}


@dataclass(frozen=True)
class MigrationReport:
    valid: bool
    detected_files: int = 0
    cache_records: int = 0
    proposed_cache_imports: int = 0
    conflicts: int = 0
    skipped: int = 0
    relink_required: int = 0
    historical_snapshots: int = 0
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class MigrationResult:
    applied: bool
    report: MigrationReport
    errors: tuple[str, ...] = ()


class LegacyMigration:
    """Inspect and apply one explicitly selected legacy directory."""

    def __init__(
        self, app_data: str | Path, *,
        replace_file: Callable[[Path, Path], None] | None = None,
    ) -> None:
        self.app_data = Path(app_data)
        self._replace_file = replace_file or self._replace

    @staticmethod
    def _replace(source: Path, target: Path) -> None:
        os.replace(source, target)

    def preview(self, legacy_directory: str | Path) -> MigrationReport:
        try:
            report, _ = self._plan(Path(legacy_directory))
            return report
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            return MigrationReport(False, errors=(str(exc),))

    def apply(self, legacy_directory: str | Path) -> MigrationResult:
        archive: Path | None = None
        try:
            report, writes = self._plan(Path(legacy_directory))
            if not report.valid:
                return MigrationResult(False, report, report.errors)
            archive = self._create_backup()
            verification = LocalDataBackup(self.app_data).preview(archive)
            if not verification.valid:
                raise ValueError("current-format backup verification failed")
            self._commit(writes)
            return MigrationResult(True, report)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            if archive is not None:
                archive.unlink(missing_ok=True)
            report = locals().get("report", MigrationReport(False))
            return MigrationResult(False, report, (self._safe_error(exc),))

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        if isinstance(exc, OSError):
            return "Migration storage operation failed; current data was unchanged"
        return str(exc)

    def _create_backup(self) -> Path:
        backup = LocalDataBackup(self.app_data)
        now = datetime.now()
        for offset in range(60):
            try:
                return backup.create(
                    self.app_data / "backups", now=now + timedelta(seconds=offset),
                )
            except FileExistsError:
                continue
        raise OSError("could not allocate backup name")

    def _plan(self, legacy: Path) -> tuple[MigrationReport, dict[str, bytes]]:
        detected = cache_records = conflicts = skipped = relinks = snapshots = 0
        errors: list[str] = []
        incoming_cache: dict[str, dict] = {}
        relink_candidates: list[dict] = []
        historical_snapshots: list[dict] = []

        for name in LEGACY_CACHE_FILES:
            path = legacy / name
            if not path.is_file() or path.is_symlink():
                continue
            detected += 1
            try:
                entries = self._read_cache(path)
                cache_records += len(entries)
                for key, entry in entries.items():
                    previous = incoming_cache.get(key)
                    if previous is None:
                        incoming_cache[key] = entry
                    elif previous != entry:
                        conflicts += 1
                        skipped += 1
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                errors.append(f"{name}: malformed or unsupported")

        for name in LEGACY_STATE_FILES:
            path = legacy / name
            if not path.is_file() or path.is_symlink():
                continue
            detected += 1
            try:
                entries = self._read_state(path)
                for key, entry in entries.items():
                    record = {
                        "legacy_key": key,
                        "account_id": None,
                        "spotify_playlist_id": entry["spotify_id"],
                        "spotify_name": entry["spotify_name"],
                        "source_reference": entry["source_path"],
                        "last_transferred_at": entry["last_synced"],
                    }
                    if name == ".djsupport_playlists.json":
                        relink_candidates.append({
                            **record, "source_label": "Rekordbox",
                            "status": "relink_required",
                        })
                        relinks += 1
                    else:
                        historical_snapshots.append({
                            **record, "source_label": "Beatport",
                            "mode": "snapshot", "managed": False,
                        })
                        snapshots += 1
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                errors.append(f"{name}: malformed or unsupported")

        current = self._read_current_matching()
        proposed = 0
        for key, entry in incoming_cache.items():
            legacy_entry = {**entry, "approval_status": None, "source_duration": 0}
            existing = current["entries"].get(key)
            if existing is None:
                current["entries"][key] = legacy_entry
                proposed += 1
            elif existing != legacy_entry:
                conflicts += 1
                skipped += 1

        migration_records = self._read_migration_records()
        for field, values in (
            ("relink_candidates", relink_candidates),
            ("historical_snapshots", historical_snapshots),
        ):
            for value in values:
                identity = self._migration_identity(value)
                existing = next((
                    item for item in migration_records[field]
                    if self._migration_identity(item) == identity
                ), None)
                if existing is None:
                    migration_records[field].append(value)
                elif existing != value:
                    conflicts += 1
                    skipped += 1

        report = MigrationReport(
            not errors, detected, cache_records, proposed, conflicts, skipped,
            relinks, snapshots, tuple(errors),
        )
        writes = {}
        if incoming_cache:
            writes["matching-knowledge.json"] = self._json_bytes(current)
        if relink_candidates or historical_snapshots:
            writes["legacy-migration.json"] = self._json_bytes(migration_records)
        return report, writes

    @staticmethod
    def _json_bytes(value: dict) -> bytes:
        return json.dumps(value, indent=2).encode()

    @staticmethod
    def _migration_identity(value: dict) -> tuple:
        return (
            value.get("legacy_key"), value.get("source_label"),
            value.get("spotify_playlist_id"),
        )

    @staticmethod
    def _read_cache(path: Path) -> dict[str, dict]:
        data = json.loads(path.read_text())
        if (
            not isinstance(data, dict) or set(data) != {"version", "entries"}
            or data.get("version") != 1
            or not isinstance(data.get("entries"), dict)
        ):
            raise ValueError("unsupported cache schema")
        for key, entry in data["entries"].items():
            if not isinstance(key, str) or not isinstance(entry, dict):
                raise ValueError("invalid cache entry")
            if set(entry) not in (CACHE_FIELDS, CACHE_FIELDS - {"match_type"}):
                raise ValueError("invalid cache entry shape")
            if not isinstance(entry["matched"], bool):
                raise ValueError("invalid cache entry")
            entry.setdefault("match_type", None)
        return data["entries"]

    @staticmethod
    def _read_state(path: Path) -> dict[str, dict]:
        data = json.loads(path.read_text())
        if (
            not isinstance(data, dict) or set(data) != {"version", "entries"}
            or data.get("version") not in (1, 2)
            or not isinstance(data.get("entries"), dict)
        ):
            raise ValueError("unsupported playlist-state schema")
        for key, entry in data["entries"].items():
            if data["version"] == 1 and "rekordbox_path" in entry:
                entry["source_path"] = entry.pop("rekordbox_path")
                entry.setdefault("source_type", "rekordbox")
            if (
                not isinstance(key, str) or not isinstance(entry, dict)
                or set(entry) != STATE_FIELDS
            ):
                raise ValueError("invalid playlist-state entry shape")
            if not all(isinstance(entry[field], str) for field in (
                "spotify_id", "spotify_name", "source_path", "last_synced",
                "source_type",
            )):
                raise ValueError("invalid playlist-state entry")
        return data["entries"]

    def _read_current_matching(self) -> dict:
        path = self.app_data / "matching-knowledge.json"
        if not path.exists():
            return {
                "version": 1, "entries": {}, "local_regressions": [],
                "approval_conflicts": [],
            }
        data = json.loads(path.read_text())
        if data.get("version") != 1 or not isinstance(data.get("entries"), dict):
            raise ValueError("Current matching knowledge is unsupported or malformed")
        return data

    def _read_migration_records(self) -> dict:
        path = self.app_data / "legacy-migration.json"
        if not path.exists():
            return {
                "version": 1, "relink_candidates": [],
                "historical_snapshots": [],
            }
        data = json.loads(path.read_text())
        if data.get("version") != 1:
            raise ValueError("Current migration records are unsupported")
        return data

    def _commit(self, writes: dict[str, bytes]) -> None:
        self.app_data.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="djsupport-migration-", dir=self.app_data.parent,
        ) as temporary_name:
            temporary = Path(temporary_name)
            staged = temporary / "staged"
            originals = temporary / "originals"
            existed = {}
            for name, content in writes.items():
                (staged / name).parent.mkdir(parents=True, exist_ok=True)
                (staged / name).write_bytes(content)
                target = self.app_data / name
                existed[name] = target.exists()
                if target.exists():
                    originals.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target, originals / name)
            committed = []
            try:
                for name in sorted(writes):
                    self._replace_file(staged / name, self.app_data / name)
                    committed.append(name)
            except Exception:
                for name in reversed(committed):
                    target = self.app_data / name
                    if existed[name]:
                        shutil.copy2(originals / name, target)
                    else:
                        target.unlink(missing_ok=True)
                raise
