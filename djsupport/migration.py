"""Explicit, privacy-safe migration of DJ Support 0.3.0 local data."""

from __future__ import annotations

import json
import os
import re
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
MIGRATION_VERSION = 1
MATCHING_KNOWLEDGE_VERSION = 2
SUPPORTED_PUBLICATION_VERSIONS = (1, 2, 3, 4, 5)
SPOTIFY_TRACK_URI = re.compile(r"^spotify:track:[A-Za-z0-9]{22}$")
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
        if not legacy.is_dir():
            raise ValueError("Selected legacy directory is unavailable")
        detected = cache_records = conflicts = skipped = relinks = snapshots = 0
        errors: list[str] = []
        incoming_cache: dict[str, dict] = {}
        ambiguous_cache_keys: set[str] = set()
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
                        ambiguous_cache_keys.add(key)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                errors.append(f"{name}: malformed or unsupported")

        publication_accounts = self._read_publication_accounts()
        for name in LEGACY_STATE_FILES:
            path = legacy / name
            if not path.is_file() or path.is_symlink():
                continue
            detected += 1
            try:
                expected_source = (
                    "rekordbox" if name == ".djsupport_playlists.json"
                    else "beatport"
                )
                entries = self._read_state(path, expected_source)
                for key, entry in entries.items():
                    account_id = None
                    if expected_source == "rekordbox":
                        accounts = publication_accounts.get((
                            entry["spotify_id"], entry["source_path"],
                        ), set())
                        if len(accounts) == 1:
                            account_id = next(iter(accounts))
                        elif len(accounts) > 1:
                            conflicts += 1
                    record = {
                        "legacy_key": key,
                        "account_id": account_id,
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
            if key in ambiguous_cache_keys:
                continue
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
            if (
                not isinstance(entry["matched"], bool)
                or not isinstance(entry["timestamp"], str)
                or not isinstance(entry["threshold"], int)
                or isinstance(entry["threshold"], bool)
                or not 0 <= entry["threshold"] <= 100
                or entry.get("match_type") not in (
                    None, "exact", "fallback_version",
                )
            ):
                raise ValueError("invalid cache entry")
            datetime.fromisoformat(entry["timestamp"])
            if entry["matched"]:
                if (
                    not isinstance(entry["spotify_uri"], str)
                    or not SPOTIFY_TRACK_URI.fullmatch(entry["spotify_uri"])
                    or not isinstance(entry["spotify_name"], str)
                    or not isinstance(entry["spotify_artist"], str)
                    or not isinstance(entry["score"], (int, float))
                    or isinstance(entry["score"], bool)
                    or not 0 <= entry["score"] <= 100
                ):
                    raise ValueError("invalid matched cache entry")
            elif any(entry[field] is not None for field in (
                "spotify_uri", "spotify_name", "spotify_artist", "score",
            )):
                raise ValueError("invalid unmatched cache entry")
            entry.setdefault("match_type", None)
        return data["entries"]

    @staticmethod
    def _read_state(path: Path, expected_source: str) -> dict[str, dict]:
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
            if entry["source_type"] != expected_source:
                raise ValueError("playlist-state source type is ambiguous")
            if not (
                entry["prefix_used"] is None
                or isinstance(entry["prefix_used"], str)
            ):
                raise ValueError("invalid playlist-state prefix")
            datetime.fromisoformat(entry["last_synced"])
        return data["entries"]

    def _read_current_matching(self) -> dict:
        path = self.app_data / "matching-knowledge.json"
        if not path.exists():
            return {
                "version": MATCHING_KNOWLEDGE_VERSION, "entries": {},
                "local_regressions": [],
                "approval_conflicts": [],
                "fingerprint_observations": {},
                "fingerprint_associations": [],
            }
        data = json.loads(path.read_text())
        if (
            data.get("version") not in (1, MATCHING_KNOWLEDGE_VERSION)
            or not isinstance(data.get("entries"), dict)
        ):
            raise ValueError("Current matching knowledge is unsupported or malformed")
        data["version"] = MATCHING_KNOWLEDGE_VERSION
        data.setdefault("local_regressions", [])
        data.setdefault("approval_conflicts", [])
        data.setdefault("fingerprint_observations", {})
        data.setdefault("fingerprint_associations", [])
        return data

    def _read_migration_records(self) -> dict:
        path = self.app_data / "legacy-migration.json"
        if not path.exists():
            return {
                "version": MIGRATION_VERSION, "relink_candidates": [],
                "historical_snapshots": [],
            }
        data = json.loads(path.read_text())
        if (
            not isinstance(data, dict)
            or set(data) != {
                "version", "relink_candidates", "historical_snapshots",
            }
            or data.get("version") != MIGRATION_VERSION
            or not isinstance(data["relink_candidates"], list)
            or not isinstance(data["historical_snapshots"], list)
        ):
            raise ValueError("Current migration records are unsupported")
        return data

    def _read_publication_accounts(self) -> dict[tuple[str, str], set[str]]:
        path = self.app_data / "publication-manifests.json"
        if not path.exists():
            return {}
        data = json.loads(path.read_text())
        if (
            data.get("version") not in SUPPORTED_PUBLICATION_VERSIONS
            or not isinstance(data.get("manifests", []), list)
            or not isinstance(data.get("mirrors", []), list)
        ):
            raise ValueError("Current publication state is unsupported or malformed")
        accounts: dict[tuple[str, str], set[str]] = {}
        for item in [*data.get("manifests", []), *data.get("mirrors", [])]:
            account = item.get("account_id")
            playlist = item.get("spotify_playlist_id")
            reference = item.get("source_reference")
            if all(isinstance(value, str) and value for value in (
                account, playlist, reference,
            )):
                accounts.setdefault((playlist, reference), set()).add(account)
        return accounts

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
                        rollback = staged / f"{name}.rollback"
                        shutil.copy2(originals / name, rollback)
                        os.replace(rollback, target)
                    else:
                        target.unlink(missing_ok=True)
                raise


@dataclass(frozen=True)
class FoundationMigrationResult:
    applied: bool
    changed_records: int
    backup_created: bool


class FoundationMigration:
    """Backup-first, repeatable migration to stable Spotify account identity."""

    FILES = ("publication-manifests.json", "transfers.json",
             "publication-manifests.transfers.json")

    def __init__(self, app_data: str | Path) -> None:
        self.app_data = Path(app_data)

    def apply(
        self, legacy_account_id: str, account_id: str,
    ) -> FoundationMigrationResult:
        if not legacy_account_id or not account_id:
            raise ValueError("Both legacy and stable account identities are required")
        marker = self.app_data / "foundation-migration.json"
        if marker.exists():
            value = json.loads(marker.read_text())
            if value == {"version": 1, "account_id": account_id}:
                return FoundationMigrationResult(False, 0, False)
            raise ValueError("A different Spotify account migration is already retained")

        planned: dict[Path, bytes] = {}
        changed = 0
        for name in self.FILES:
            path = self.app_data / name
            if not path.exists():
                continue
            value = json.loads(path.read_text())
            migrated, count = self._replace_account_ids(
                value, legacy_account_id, account_id,
            )
            changed += count
            if count:
                planned[path] = json.dumps(migrated, indent=2).encode()

        self.app_data.mkdir(parents=True, exist_ok=True)
        backup_dir = self.app_data / "backups"
        archive = LocalDataBackup(self.app_data).create(backup_dir)
        if not LocalDataBackup(self.app_data).preview(archive).valid:
            raise ValueError("Foundation migration backup verification failed")
        planned[marker] = json.dumps(
            {"version": 1, "account_id": account_id}, indent=2,
        ).encode()
        self._atomic_commit(planned)
        return FoundationMigrationResult(True, changed, True)

    @classmethod
    def _replace_account_ids(
        cls, value, legacy_account_id: str, account_id: str,
    ):
        changed = 0
        if isinstance(value, list):
            result = []
            for item in value:
                migrated, count = cls._replace_account_ids(
                    item, legacy_account_id, account_id,
                )
                result.append(migrated)
                changed += count
            return result, changed
        if not isinstance(value, dict):
            return value, 0
        result = dict(value)
        retained = result.get("account_id")
        legacy = result.get("spotify_user_id")
        if retained not in (None, legacy_account_id, account_id):
            raise ValueError("Current account ownership conflicts with migration")
        if legacy not in (None, legacy_account_id, account_id):
            raise ValueError("Legacy account ownership conflicts with migration")
        result.pop("spotify_user_id", None)
        if retained == legacy_account_id or legacy == legacy_account_id:
            result["account_id"] = account_id
            changed += 1
        for key, item in list(result.items()):
            migrated, count = cls._replace_account_ids(
                item, legacy_account_id, account_id,
            )
            result[key] = migrated
            changed += count
        return result, changed

    def _atomic_commit(self, writes: dict[Path, bytes]) -> None:
        staged: list[tuple[Path, Path]] = []
        try:
            for target, content in writes.items():
                temporary = target.with_suffix(f"{target.suffix}.migration.tmp")
                temporary.write_bytes(content)
                staged.append((temporary, target))
            for temporary, target in staged:
                os.replace(temporary, target)
        finally:
            for temporary, _ in staged:
                temporary.unlink(missing_ok=True)
