"""Versioned backup and conflict-aware restore for local application data."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable


BACKUP_VERSION = 1
SUPPORTED_SCHEMAS = {
    "matching-knowledge.json": (1, 2),
    "transfers.json": (1, 2, 3),
    "publication-manifests.transfers.json": (1, 2, 3),
    "publication-manifests.json": (1, 2, 3, 4, 5),
    "playlist-state.json": (1, 2),
    "legacy-migration.json": (1,),
    "foundation-migration.json": (1,),
}
DATA_FILES = tuple(SUPPORTED_SCHEMAS)
SECRET_KEYS = {
    "access_token", "refresh_token", "client_secret", "client_id",
    "authorization", "password",
}


@dataclass(frozen=True)
class RestoreConflict:
    conflict_id: str
    kind: str
    path: str
    choices: tuple[str, str] = ("current", "archive")


@dataclass(frozen=True)
class RestorePreview:
    valid: bool
    contents: tuple[str, ...] = ()
    changes: tuple[str, ...] = ()
    conflicts: tuple[RestoreConflict, ...] = ()
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class RestoreResult:
    restored: bool
    changes: tuple[str, ...] = ()
    conflicts: tuple[RestoreConflict, ...] = ()
    errors: tuple[str, ...] = ()


class LocalDataBackup:
    """Create and restore portable archives at the local-data boundary."""

    def __init__(
        self, app_data: str | Path, *,
        replace_file: Callable[[Path, Path], None] | None = None,
    ) -> None:
        self.app_data = Path(app_data)
        self._replace_file = replace_file or self._replace

    @staticmethod
    def _replace(source: Path, target: Path) -> None:
        os.replace(source, target)

    def create(
        self, destination: str | Path, *, now: datetime | None = None,
    ) -> Path:
        created_at = now or datetime.now()
        destination = Path(destination)
        archive = destination / (
            f"djsupport-backup-{created_at:%Y%m%dT%H%M%S}.zip"
        )
        members = [
            self.app_data / name for name in DATA_FILES
            if (self.app_data / name).is_file()
        ]
        reports = self.app_data / "reports"
        if reports.is_dir():
            members.extend(
                path for path in reports.rglob("*")
                if path.is_file() and not path.is_symlink()
                and path.suffix.casefold() in (".md", ".csv")
                and not self._report_contains_secret(path)
            )
        entries = []
        for path in members:
            content = path.read_bytes()
            relative = path.relative_to(self.app_data).as_posix()
            schema_version = None
            if relative in SUPPORTED_SCHEMAS:
                data = json.loads(content)
                if self._contains_secret_key(data):
                    raise ValueError(
                        f"Credential fields found in application data: {relative}"
                    )
                schema_version = data["version"]
            entries.append({
                "path": relative,
                "sha256": hashlib.sha256(content).hexdigest(),
                "schema_version": schema_version,
            })
        manifest = {
            "version": BACKUP_VERSION,
            "created_at": created_at.isoformat(),
            "entries": entries,
        }
        destination.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("backup-manifest.json", json.dumps(manifest, indent=2))
            for path in members:
                bundle.write(path, path.relative_to(self.app_data).as_posix())
        return archive

    @classmethod
    def _contains_secret_key(cls, value) -> bool:
        if isinstance(value, dict):
            return any(
                cls._is_secret_key(str(key))
                or cls._contains_secret_key(item)
                for key, item in value.items()
            )
        if isinstance(value, list):
            return any(cls._contains_secret_key(item) for item in value)
        return False

    @staticmethod
    def _is_secret_key(key: str) -> bool:
        normalized = re.sub(r"[^a-z0-9]+", "_", key.casefold()).strip("_")
        return any(
            normalized == secret or normalized.endswith(f"_{secret}")
            for secret in SECRET_KEYS
        )

    @staticmethod
    def _report_contains_secret(path: Path) -> bool:
        text = path.read_text(errors="replace").casefold()
        key_pattern = "|".join(
            re.escape(key).replace(r"\_", r"[ _-]?") for key in SECRET_KEYS
        )
        return bool(re.search(
            rf"(?:spotipy[ _-])?(?:{key_pattern})\s*[:=]"
            rf"|authorization\s*:\s*(?:bearer|basic)\s+",
            text,
        ))

    def preview(self, archive: str | Path) -> RestorePreview:
        try:
            incoming = self._read_archive(Path(archive))
            merged, changes, conflicts = self._plan(incoming, {})
            del merged
            return RestorePreview(
                True, tuple(sorted(incoming)), tuple(changes), tuple(conflicts),
            )
        except (
            OSError, ValueError, KeyError, json.JSONDecodeError,
            zipfile.BadZipFile,
        ) as exc:
            return RestorePreview(False, errors=(str(exc),))

    def restore(
        self, archive: str | Path, *, resolutions: dict[str, str] | None = None,
    ) -> RestoreResult:
        preview = self.preview(archive)
        if not preview.valid:
            return RestoreResult(False, errors=preview.errors)
        incoming = self._read_archive(Path(archive))
        merged, changes, conflicts = self._plan(incoming, resolutions or {})
        unresolved = [
            conflict for conflict in conflicts
            if conflict.conflict_id not in (resolutions or {})
        ]
        if unresolved:
            return RestoreResult(False, conflicts=tuple(unresolved))
        self._commit(merged)
        return RestoreResult(True, tuple(changes), tuple(conflicts))

    def _read_archive(self, archive: Path) -> dict[str, bytes]:
        with zipfile.ZipFile(archive) as bundle:
            names = bundle.namelist()
            if len(names) != len(set(names)):
                raise ValueError("Archive contains duplicate entries")
            if "backup-manifest.json" not in names:
                raise ValueError("Archive has no backup manifest")
            manifest = json.loads(bundle.read("backup-manifest.json"))
            if manifest.get("version") != BACKUP_VERSION:
                raise ValueError("Unsupported backup schema version")
            declared = {entry["path"]: entry for entry in manifest["entries"]}
            if set(names) != {"backup-manifest.json", *declared}:
                raise ValueError("Archive contents do not match its manifest")
            incoming = {}
            for path, entry in declared.items():
                candidate = Path(path)
                if candidate.is_absolute() or ".." in candidate.parts:
                    raise ValueError("Archive contains an unsafe path")
                if path not in DATA_FILES and not path.startswith("reports/"):
                    raise ValueError("Archive contains unrelated application data")
                content = bundle.read(path)
                if hashlib.sha256(content).hexdigest() != entry["sha256"]:
                    raise ValueError(f"Integrity check failed for {path}")
                if path in SUPPORTED_SCHEMAS:
                    data = json.loads(content)
                    version = data.get("version")
                    if version not in SUPPORTED_SCHEMAS[path]:
                        raise ValueError(f"Unsupported schema version for {path}")
                    if entry.get("schema_version") != version:
                        raise ValueError(f"Schema metadata mismatch for {path}")
                incoming[path] = content
            return incoming

    def _plan(
        self, incoming: dict[str, bytes], resolutions: dict[str, str],
    ) -> tuple[dict[str, bytes], list[str], list[RestoreConflict]]:
        merged: dict[str, bytes] = {}
        changes: list[str] = []
        conflicts: list[RestoreConflict] = []
        for path, content in incoming.items():
            current_path = self.app_data / path
            if path.startswith("reports/"):
                if not current_path.exists():
                    merged[path] = content
                    changes.append(f"add report: {path.removeprefix('reports/')}")
                elif current_path.read_bytes() == content:
                    merged[path] = content
                else:
                    holder = {"content": current_path.read_bytes()}
                    self._resolve_conflict(
                        holder, "content", content, "report", path,
                        conflicts, resolutions,
                    )
                    merged[path] = holder["content"]
                    if resolutions.get(f"report:{path}:content") == "archive":
                        changes.append(f"replace report: {path.removeprefix('reports/')}")
                continue
            incoming_data = json.loads(content)
            if not current_path.exists():
                merged[path] = content
                changes.append(f"add {path}")
                continue
            current_data = json.loads(current_path.read_bytes())
            combined = self._merge_json(
                path, current_data, incoming_data, changes, conflicts, resolutions,
            )
            merged[path] = json.dumps(combined, indent=2).encode()
        return merged, changes, conflicts

    def _merge_json(self, path, current, incoming, changes, conflicts, resolutions):
        combined = json.loads(json.dumps(current))
        if path == "matching-knowledge.json":
            combined["version"] = max(
                current.get("version", 1), incoming.get("version", 1),
            )
            combined.setdefault("entries", {})
            for key, value in incoming.get("entries", {}).items():
                existing = combined["entries"].get(key)
                if existing is None:
                    combined["entries"][key] = value
                    changes.append(f"add matching knowledge: {key}")
                elif existing != value and (
                    existing.get("approval_status") == "approved"
                    or value.get("approval_status") == "approved"
                ):
                    self._resolve_conflict(
                        combined["entries"], key, value, "approval", path,
                        conflicts, resolutions,
                    )
            for field in ("local_regressions", "approval_conflicts"):
                combined.setdefault(field, [])
                for item in incoming.get(field, []):
                    if item not in combined[field]:
                        combined[field].append(item)
            combined.setdefault("fingerprint_observations", {})
            for evidence_id, item in incoming.get(
                "fingerprint_observations", {}
            ).items():
                existing = combined["fingerprint_observations"].get(evidence_id)
                if existing is None:
                    combined["fingerprint_observations"][evidence_id] = item
                    changes.append("add local audio observation")
                elif existing != item:
                    safe_identity = hashlib.sha256(
                        evidence_id.encode()
                    ).hexdigest()[:12]
                    self._resolve_conflict(
                        combined["fingerprint_observations"], evidence_id, item,
                        "identity", path, conflicts, resolutions,
                        label=f"local-audio:{safe_identity}",
                    )
            combined.setdefault("fingerprint_associations", [])
            for item in incoming.get("fingerprint_associations", []):
                identity = (
                    item.get("algorithm"), item.get("algorithm_version"),
                    item.get("fingerprint"), item.get("account_id"),
                )
                existing = next((
                    value for value in combined["fingerprint_associations"]
                    if (
                        value.get("algorithm"),
                        value.get("algorithm_version"),
                        value.get("fingerprint"),
                        value.get("account_id"),
                    ) == identity
                ), None)
                if existing is None:
                    combined["fingerprint_associations"].append(item)
                    changes.append("add local audio Approved Match")
                elif existing != item:
                    safe_identity = hashlib.sha256(
                        repr(identity).encode()
                    ).hexdigest()[:12]
                    self._resolve_conflict(
                        combined["fingerprint_associations"],
                        combined["fingerprint_associations"].index(existing),
                        item, "approval", path, conflicts, resolutions,
                        label=f"local-audio:{safe_identity}",
                    )
        elif path in ("transfers.json", "publication-manifests.transfers.json"):
            for field in ("transfers", "batches"):
                combined.setdefault(field, {})
                for key, value in incoming.get(field, {}).items():
                    if key not in combined[field]:
                        combined[field][key] = value
                        changes.append(f"add {field[:-1]}: {key}")
        elif path == "playlist-state.json":
            combined.setdefault("entries", {})
            for key, value in incoming.get("entries", {}).items():
                if key not in combined["entries"]:
                    combined["entries"][key] = value
                    changes.append(f"add playlist state: {key}")
                elif combined["entries"][key] != value:
                    self._resolve_conflict(
                        combined["entries"], key, value, "playlist-state", path,
                        conflicts, resolutions,
                    )
        elif path == "publication-manifests.json":
            for field in ("manifests", "mirrors"):
                combined.setdefault(field, [])
                for item in incoming.get(field, []):
                    identity = self._publication_identity(field, item)
                    existing = next((
                        value for value in combined[field]
                        if self._publication_identity(field, value) == identity
                    ), None)
                    if existing is None:
                        combined[field].append(item)
                        changes.append(f"add playlist state: {identity}")
                    elif existing != item:
                        index = combined[field].index(existing)
                        self._resolve_conflict(
                            combined[field], index, item, "playlist-state", path,
                            conflicts, resolutions, label=str(identity),
                        )
            combined.setdefault("approvals", [])
            for item in incoming.get("approvals", incoming.get("reviews", [])):
                if item not in combined["approvals"]:
                    combined["approvals"].append(item)
        elif path == "legacy-migration.json":
            for field in ("relink_candidates", "historical_snapshots"):
                combined.setdefault(field, [])
                for item in incoming.get(field, []):
                    identity = (
                        item.get("legacy_key"), item.get("source_label"),
                        item.get("spotify_playlist_id"),
                    )
                    existing = next((
                        value for value in combined[field]
                        if (
                            value.get("legacy_key"), value.get("source_label"),
                            value.get("spotify_playlist_id"),
                        ) == identity
                    ), None)
                    if existing is None:
                        combined[field].append(item)
                        changes.append(f"add legacy migration record: {field}")
                    elif existing != item:
                        safe_identity = hashlib.sha256(
                            repr(identity).encode()
                        ).hexdigest()[:12]
                        self._resolve_conflict(
                            combined[field], combined[field].index(existing), item,
                            "migration", path, conflicts, resolutions,
                            label=f"{field}:{safe_identity}",
                        )
        return combined

    @staticmethod
    def _publication_identity(field: str, item: dict) -> tuple:
        if field == "manifests":
            return item.get("account_id"), item.get("spotify_playlist_id")
        return (
            item.get("account_id"), item.get("source_label"),
            item.get("source_reference"),
        )

    @staticmethod
    def _resolve_conflict(
        container, key, incoming, kind, path, conflicts, resolutions, *, label=None,
    ):
        conflict_id = f"{kind}:{path}:{label if label is not None else key}"
        conflict = RestoreConflict(conflict_id, kind, path)
        conflicts.append(conflict)
        choice = resolutions.get(conflict_id)
        if choice not in (None, *conflict.choices):
            raise ValueError(f"Invalid resolution for {conflict_id}")
        if choice == "archive":
            container[key] = incoming

    def _commit(self, merged: dict[str, bytes]) -> None:
        self.app_data.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="djsupport-restore-", dir=self.app_data.parent,
        ) as temporary_name:
            temporary = Path(temporary_name)
            staged = temporary / "staged"
            originals = temporary / "originals"
            existed: dict[str, bool] = {}
            for path, content in merged.items():
                stage_path = staged / path
                stage_path.parent.mkdir(parents=True, exist_ok=True)
                stage_path.write_bytes(content)
                target = self.app_data / path
                existed[path] = target.exists()
                if target.exists():
                    original = originals / path
                    original.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target, original)
            committed: list[str] = []
            try:
                for path in sorted(merged):
                    target = self.app_data / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    self._replace_file(staged / path, target)
                    committed.append(path)
            except Exception:
                for path in reversed(committed):
                    target = self.app_data / path
                    if existed[path]:
                        shutil.copy2(originals / path, target)
                    else:
                        target.unlink(missing_ok=True)
                raise


def default_app_data_path() -> Path:
    """Return the ADR-0001 application-data directory."""
    from djsupport.transfer import default_matching_knowledge_path

    return default_matching_knowledge_path().parent
