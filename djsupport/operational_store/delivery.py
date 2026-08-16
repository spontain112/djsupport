"""Verify one official APSW wheel and its loaded runtime evidence."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from importlib import resources
import json
from pathlib import Path
import re
from typing import Mapping

from jsonschema import Draft202012Validator, FormatChecker

from djsupport.operational_store.apsw import probe_apsw_runtime
from djsupport.operational_store.qualification import (
    QualificationState,
    RuntimeFacts,
    SQLiteRuntimeQualification,
)


_CATALOG = "apsw-runtime-artifacts.v1.json"
_CATALOG_SCHEMA = "apsw-runtime-artifacts.v1.schema.json"
_QUALIFICATION = "sqlite-runtime-qualification.v1.json"
_SAFE_IDENTITY = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._+-]*(/[A-Za-z0-9][A-Za-z0-9._+-]*)*"
)


class RuntimeDeliveryError(RuntimeError):
    """One public delivery fact failed the reviewed contract."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"sqlite_runtime_delivery_failed:{reason_code}")


def load_artifact_catalog() -> dict[str, object]:
    """Load and strictly validate the packaged binary artifact catalog."""
    catalog = _load_packaged_json(_CATALOG)
    schema = _load_packaged_json(_CATALOG_SCHEMA)
    errors = sorted(
        Draft202012Validator(
            schema,
            format_checker=FormatChecker(),
        ).iter_errors(catalog),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        raise RuntimeDeliveryError("artifact_catalog_invalid")
    artifacts = catalog.get("artifacts")
    if not isinstance(artifacts, list):
        raise RuntimeDeliveryError("artifact_catalog_invalid")
    artifact_ids = [
        artifact.get("artifact_id")
        for artifact in artifacts
        if isinstance(artifact, dict)
    ]
    filenames = [
        artifact.get("filename")
        for artifact in artifacts
        if isinstance(artifact, dict)
    ]
    cells = [
        (
            artifact.get("runner_label"),
            artifact.get("python_version"),
            artifact.get("architecture"),
        )
        for artifact in artifacts
        if isinstance(artifact, dict)
    ]
    if not (
        len(artifacts)
        == len(set(artifact_ids))
        == len(set(filenames))
        == len(set(cells))
    ):
        raise RuntimeDeliveryError("artifact_catalog_duplicate")
    return catalog


def artifact_for_cell(
    catalog: Mapping[str, object],
    *,
    runner_label: str,
    python_version: str,
    architecture: str,
) -> dict[str, object]:
    """Select exactly one reviewed wheel for one claimed native cell."""
    artifacts = catalog.get("artifacts")
    if not isinstance(artifacts, list):
        raise RuntimeDeliveryError("artifact_catalog_invalid")
    matches = [
        artifact
        for artifact in artifacts
        if isinstance(artifact, dict)
        and artifact.get("runner_label") == runner_label
        and artifact.get("python_version") == python_version
        and artifact.get("architecture") == architecture
    ]
    if len(matches) != 1:
        raise RuntimeDeliveryError("native_cell_unapproved")
    return deepcopy(matches[0])


def verify_downloaded_wheel(
    wheel_path: Path,
    artifact: Mapping[str, object],
) -> None:
    """Match the resolved wheel to its reviewed name, size, and digest."""
    if wheel_path.name != artifact.get("filename"):
        raise RuntimeDeliveryError("artifact_filename_unapproved")
    try:
        size_bytes = wheel_path.stat().st_size
    except OSError:
        raise RuntimeDeliveryError("artifact_unavailable") from None
    if size_bytes != artifact.get("size_bytes"):
        raise RuntimeDeliveryError("artifact_size_unapproved")
    digest = sha256()
    try:
        with wheel_path.open("rb") as wheel:
            for chunk in iter(lambda: wheel.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        raise RuntimeDeliveryError("artifact_unavailable") from None
    if digest.hexdigest() != artifact.get("sha256"):
        raise RuntimeDeliveryError("artifact_digest_unapproved")


def collect_candidate_entry(
    *,
    artifact: Mapping[str, object],
    catalog: Mapping[str, object],
    runner_label: str,
    runner_version: str,
    runner_manifest_url: str,
    activated_at_utc: str | None = None,
    facts: RuntimeFacts | None = None,
) -> dict[str, object]:
    """Create a path-free candidate entry from the loaded APSW runtime."""
    runtime_facts = facts if facts is not None else probe_apsw_runtime()
    _require_cell_facts(runtime_facts, artifact, runner_label)
    if _SAFE_IDENTITY.fullmatch(runner_version) is None:
        raise RuntimeDeliveryError("runner_image_version_malformed")
    if not runner_manifest_url.startswith("https://"):
        raise RuntimeDeliveryError("runner_manifest_url_malformed")
    publisher = catalog.get("publisher")
    if not isinstance(publisher, dict):
        raise RuntimeDeliveryError("artifact_catalog_invalid")
    artifact_id = artifact.get("artifact_id")
    if not isinstance(artifact_id, str):
        raise RuntimeDeliveryError("artifact_catalog_invalid")
    activation = activated_at_utc or (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    evidence_id = f"{artifact_id}/{runner_version}"
    return {
        "evidence_id": evidence_id,
        "artifact_id": artifact_id,
        "classification": "qualified_upstream",
        "status": "active",
        "selectors": runtime_facts.selectors(),
        "artifact": {
            "vendor": "PyPI",
            "filename": artifact["filename"],
            "download_url": artifact["download_url"],
            "size_bytes": artifact["size_bytes"],
            "sha256": artifact["sha256"],
            "platform_tag": artifact["platform_tag"],
            "publisher": {
                "identity": "github/rogerbinns/apsw/build-pypi.yml",
                "provenance_url": artifact["provenance_url"],
            },
            "build": {
                "source_repository_url": publisher[
                    "source_repository_url"
                ],
                "source_commit": publisher["source_commit"],
                "workflow_url": publisher["workflow_url"],
                "runner_image": {
                    "label": runner_label,
                    "version": runner_version,
                    "manifest_url": runner_manifest_url,
                },
            },
        },
        "activated_at_utc": activation,
        "revoked_at_utc": None,
        "supersedes_evidence_id": None,
        "status_evidence_id": None,
    }


def verify_installed_delivery(
    *,
    artifact: Mapping[str, object],
    catalog: Mapping[str, object],
    runner_label: str,
    runner_version: str,
    runner_manifest_url: str,
) -> dict[str, object]:
    """Require the exact loaded runtime and its active manifest entry."""
    facts = probe_apsw_runtime()
    candidate = collect_candidate_entry(
        artifact=artifact,
        catalog=catalog,
        runner_label=runner_label,
        runner_version=runner_version,
        runner_manifest_url=runner_manifest_url,
        facts=facts,
    )
    qualification = SQLiteRuntimeQualification.packaged()
    result = qualification.classify(facts)
    if (
        not result.qualified
        or result.state is not QualificationState.QUALIFIED_UPSTREAM
        or result.evidence_id != candidate["evidence_id"]
    ):
        raise RuntimeDeliveryError("runtime_not_qualified")
    manifest = _load_packaged_json(_QUALIFICATION)
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise RuntimeDeliveryError("runtime_manifest_invalid")
    matched = [
        entry
        for entry in entries
        if isinstance(entry, dict)
        and entry.get("evidence_id") == result.evidence_id
    ]
    if len(matched) != 1:
        raise RuntimeDeliveryError("runtime_manifest_entry_unavailable")
    entry = matched[0]
    for field in ("artifact_id", "selectors", "artifact"):
        if entry.get(field) != candidate.get(field):
            raise RuntimeDeliveryError("runtime_manifest_entry_mismatch")
    return {
        "schema_version": 1,
        "qualification_state": result.state.value,
        "evidence_id": result.evidence_id,
        "artifact_id": entry["artifact_id"],
        "selectors": entry["selectors"],
        "artifact": entry["artifact"],
        "activated_at_utc": entry["activated_at_utc"],
    }


def _require_cell_facts(
    facts: RuntimeFacts,
    artifact: Mapping[str, object],
    runner_label: str,
) -> None:
    expected = (
        artifact.get("runner_label"),
        artifact.get("python_version"),
        artifact.get("architecture"),
        artifact.get("os"),
        artifact.get("product_type"),
    )
    actual = (
        runner_label,
        facts.python_version,
        facts.architecture,
        facts.os_name,
        facts.os_product_type,
    )
    if actual != expected:
        raise RuntimeDeliveryError("native_cell_mismatch")
    version_family = artifact.get("os_version_family")
    if not isinstance(version_family, str) or not (
        facts.os_version == version_family
        or facts.os_version.startswith(f"{version_family}.")
    ):
        raise RuntimeDeliveryError("native_os_version_mismatch")


def _load_packaged_json(filename: str) -> dict[str, object]:
    try:
        document = json.loads(
            resources.files("djsupport")
            .joinpath("contracts", filename)
            .read_text(encoding="utf-8")
        )
    except (OSError, TypeError, ValueError):
        raise RuntimeDeliveryError("packaged_contract_unavailable") from None
    if not isinstance(document, dict):
        raise RuntimeDeliveryError("packaged_contract_invalid")
    return document
