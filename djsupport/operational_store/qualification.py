"""Classify exact SQLite binding and runtime evidence before store access."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from importlib import resources
import json
import re
from typing import Callable, Mapping, TypeVar

from jsonschema import Draft202012Validator, FormatChecker


_MANIFEST_SCHEMA = "sqlite-runtime-qualification.v1.schema.json"
_PACKAGED_MANIFEST = "sqlite-runtime-qualification.v1.json"
_T = TypeVar("_T")
_NEAR_MISS_RULES = (
    ("binding_artifact_unapproved", "binding", "extension_sha256"),
    ("sqlite_source_unapproved", "sqlite", "source_id"),
    ("compile_options_unapproved", "sqlite", "compile_options_sha256"),
    ("wrapper_version_unapproved", "binding", "wrapper_version"),
    ("platform_unapproved", "platform", None),
    ("python_runtime_unapproved", "python", None),
    ("sqlite_build_unapproved", "sqlite", "using_amalgamation"),
    ("sqlite_version_number_unapproved", "sqlite", "version_number"),
)


class QualificationManifestError(ValueError):
    """The repository-owned runtime policy document is not trustworthy."""


class SQLiteRuntimeUnavailable(RuntimeError):
    """The production store must stop before resolving any private path."""

    def __init__(self, result: QualificationResult) -> None:
        self.result = result
        super().__init__(f"sqlite_runtime_unavailable:{result.reason_code}")


class QualificationState(str, Enum):
    """The complete fail-closed SQLite runtime policy result."""

    QUALIFIED_UPSTREAM = "qualified_upstream"
    QUALIFIED_DOWNSTREAM_ATTESTATION = "qualified_downstream_attestation"
    UNQUALIFIED_AFFECTED = "unqualified_affected"
    UNQUALIFIED_WITHDRAWN = "unqualified_withdrawn"
    UNQUALIFIED_UNKNOWN = "unqualified_unknown"


@dataclass(frozen=True)
class RuntimeFacts:
    """Path-free public facts from the binding that would open the store."""

    binding_distribution: str
    binding_distribution_version: str
    binding_wrapper_version: str
    binding_extension_sha256: str
    sqlite_version: str
    sqlite_version_number: int
    sqlite_source_id: str
    sqlite_compile_options_sha256: str
    using_amalgamation: bool
    python_implementation: str
    python_version: str
    python_abi: str
    python_gil_mode: str
    os_name: str
    os_version: str
    os_kernel_release: str
    os_product_type: str
    architecture: str

    def _selectors(self) -> dict[str, object]:
        return {
            "binding": {
                "distribution": self.binding_distribution,
                "distribution_version": self.binding_distribution_version,
                "wrapper_version": self.binding_wrapper_version,
                "extension_sha256": self.binding_extension_sha256,
            },
            "sqlite": {
                "version": self.sqlite_version,
                "version_number": self.sqlite_version_number,
                "source_id": self.sqlite_source_id,
                "compile_options_sha256": self.sqlite_compile_options_sha256,
                "using_amalgamation": self.using_amalgamation,
            },
            "python": {
                "implementation": self.python_implementation,
                "version": self.python_version,
                "abi": self.python_abi,
                "gil_mode": self.python_gil_mode,
            },
            "platform": {
                "os": self.os_name,
                "version": self.os_version,
                "kernel_release": self.os_kernel_release,
                "product_type": self.os_product_type,
                "architecture": self.architecture,
            },
        }


@dataclass(frozen=True)
class QualificationResult:
    """Typed classification plus the reviewed evidence identity, if any."""

    state: QualificationState
    reason_code: str
    evidence_id: str | None = None

    @property
    def qualified(self) -> bool:
        return self.state in {
            QualificationState.QUALIFIED_UPSTREAM,
            QualificationState.QUALIFIED_DOWNSTREAM_ATTESTATION,
        }

    @property
    def diagnostic(self) -> dict[str, str | None]:
        """Return only stable, path-free facts safe for diagnostics."""
        return {
            "state": self.state.value,
            "reason_code": self.reason_code,
            "evidence_id": self.evidence_id,
        }


@dataclass(frozen=True)
class QualifiedRuntime:
    """Proof that one reviewed evidence entry admitted this process."""

    state: QualificationState
    evidence_id: str


class SQLiteRuntimeQualification:
    """Apply one immutable repository-owned qualification manifest."""

    def __init__(self, manifest: Mapping[str, object]) -> None:
        manifest_document = deepcopy(dict(manifest))
        _validate_manifest(manifest_document)
        self._manifest = manifest_document

    @classmethod
    def packaged(cls) -> SQLiteRuntimeQualification:
        """Load the immutable policy shipped with this DJ Support build."""
        manifest_text = (
            resources.files("djsupport")
            .joinpath("contracts", _PACKAGED_MANIFEST)
            .read_text(encoding="utf-8")
        )
        manifest = json.loads(manifest_text)
        if not isinstance(manifest, dict):
            raise QualificationManifestError(
                "sqlite_runtime_manifest_invalid:type:root"
            )
        return cls(manifest)

    def classify(self, facts: RuntimeFacts) -> QualificationResult:
        withdrawn = self._manifest.get("withdrawn_sqlite_versions", [])
        if isinstance(withdrawn, list) and facts.sqlite_version in withdrawn:
            return QualificationResult(
                QualificationState.UNQUALIFIED_WITHDRAWN,
                "sqlite_release_withdrawn",
            )
        if not _runtime_facts_are_well_formed(facts):
            return QualificationResult(
                QualificationState.UNQUALIFIED_UNKNOWN,
                "runtime_facts_malformed",
            )
        if _is_affected_release(
            facts.sqlite_version,
            self._manifest.get("affected_sqlite_ranges", []),
        ):
            return QualificationResult(
                QualificationState.UNQUALIFIED_AFFECTED,
                "sqlite_release_affected",
            )
        selected_binding = self._manifest.get("selected_binding")
        if not isinstance(selected_binding, dict) or (
            selected_binding.get("distribution")
            != facts.binding_distribution
            or selected_binding.get("version")
            != facts.binding_distribution_version
        ):
            return QualificationResult(
                QualificationState.UNQUALIFIED_UNKNOWN,
                "binding_unapproved",
            )
        selectors = facts._selectors()
        entries = self._manifest.get("entries", [])
        near_miss_reason = None
        if isinstance(entries, list):
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                entry_selectors = entry.get("selectors")
                if entry_selectors == selectors:
                    status = entry.get("status")
                    if status in {"revoked", "superseded"}:
                        return QualificationResult(
                            QualificationState.UNQUALIFIED_UNKNOWN,
                            f"evidence_{status}",
                            str(entry["evidence_id"]),
                        )
                    if status != "active":
                        continue
                    state = QualificationState(str(entry["classification"]))
                    reason_code = (
                        "downstream_attestation_exact_match"
                        if state
                        is QualificationState.QUALIFIED_DOWNSTREAM_ATTESTATION
                        else "upstream_exact_match"
                    )
                    return QualificationResult(
                        state,
                        reason_code,
                        str(entry["evidence_id"]),
                    )
                if (
                    entry.get("status") == "active"
                    and near_miss_reason is None
                ):
                    for reason_code, section, field in _NEAR_MISS_RULES:
                        if _matches_except_selector(
                            entry_selectors,
                            selectors,
                            section,
                            field,
                        ):
                            near_miss_reason = reason_code
                            break
        if near_miss_reason is not None:
            return QualificationResult(
                QualificationState.UNQUALIFIED_UNKNOWN,
                near_miss_reason,
            )
        return QualificationResult(
            QualificationState.UNQUALIFIED_UNKNOWN,
            "evidence_unlisted",
        )

    def classify_installed(self) -> QualificationResult:
        """Probe APSW and fail closed before any Operational Store path."""
        from djsupport.operational_store.apsw import (
            RuntimeProbeError,
            probe_apsw_runtime,
        )

        try:
            facts = probe_apsw_runtime()
        except RuntimeProbeError as exc:
            return QualificationResult(
                QualificationState.UNQUALIFIED_UNKNOWN,
                exc.reason_code,
            )
        return self.classify(facts)

    def run_qualified(
        self,
        operation: Callable[[QualifiedRuntime], _T],
    ) -> _T:
        """Run an Operational Store operation only after exact qualification."""
        result = self.classify_installed()
        if not result.qualified or result.evidence_id is None:
            raise SQLiteRuntimeUnavailable(result)
        return operation(QualifiedRuntime(result.state, result.evidence_id))


def _matches_except_selector(
    expected: object,
    actual: Mapping[str, object],
    target_section: str,
    target_field: str | None,
) -> bool:
    if not isinstance(expected, dict):
        return False
    sections = ("binding", "sqlite", "python", "platform")
    for section in sections:
        if section == target_section:
            continue
        if expected.get(section) != actual.get(section):
            return False
    expected_target = expected.get(target_section)
    actual_target = actual.get(target_section)
    if target_field is None:
        return expected_target != actual_target
    if not isinstance(expected_target, dict):
        return False
    if not isinstance(actual_target, dict):
        return False
    expected_without_field = {
        key: value
        for key, value in expected_target.items()
        if key != target_field
    }
    actual_without_field = {
        key: value
        for key, value in actual_target.items()
        if key != target_field
    }
    return (
        expected_without_field == actual_without_field
        and expected_target.get(target_field)
        != actual_target.get(target_field)
    )


def _is_affected_release(version: str, ranges: object) -> bool:
    parsed = _parse_sqlite_version(version)
    if parsed is None or not isinstance(ranges, list):
        return False
    for item in ranges:
        if not isinstance(item, dict):
            continue
        minimum = _parse_sqlite_version(item.get("minimum"))
        maximum = _parse_sqlite_version(item.get("maximum"))
        exceptions = item.get("exceptions", [])
        if minimum is None or maximum is None:
            continue
        if version in exceptions:
            continue
        if minimum <= parsed <= maximum:
            return True
    return False


def _parse_sqlite_version(value: object) -> tuple[int, int, int] | None:
    if not isinstance(value, str):
        return None
    parts = value.split(".")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        return None
    parsed = int(parts[0]), int(parts[1]), int(parts[2])
    if value != ".".join(str(part) for part in parsed):
        return None
    if parsed[1] >= 1000 or parsed[2] >= 1000:
        return None
    return parsed


def _runtime_facts_are_well_formed(facts: RuntimeFacts) -> bool:
    text_values = (
        facts.binding_distribution,
        facts.binding_distribution_version,
        facts.binding_wrapper_version,
        facts.binding_extension_sha256,
        facts.sqlite_version,
        facts.sqlite_source_id,
        facts.sqlite_compile_options_sha256,
        facts.python_implementation,
        facts.python_version,
        facts.python_abi,
        facts.python_gil_mode,
        facts.os_name,
        facts.os_version,
        facts.os_kernel_release,
        facts.os_product_type,
        facts.architecture,
    )
    if any(not isinstance(value, str) for value in text_values):
        return False
    if any(
        re.fullmatch(r"[A-Za-z0-9_.+\-]+", value) is None
        for value in (facts.binding_distribution, facts.os_kernel_release)
    ):
        return False
    if (
        re.fullmatch(
            r"[0-9]+(?:\.[0-9]+){3}",
            facts.binding_distribution_version,
        )
        is None
        or re.fullmatch(
            r"[0-9]+(?:\.[0-9]+){3}",
            facts.binding_wrapper_version,
        )
        is None
    ):
        return False
    python_version = _parse_python_version(facts.python_version)
    if facts.python_implementation != "CPython" or python_version is None:
        return False
    python_abi_match = re.fullmatch(
        rf"(?:cpython-{python_version[0]}{python_version[1]}|"
        rf"cp{python_version[0]}{python_version[1]})(t)?"
        r"(?:[-_][A-Za-z0-9_.+-]+)?",
        facts.python_abi,
    )
    if python_abi_match is None:
        return False
    if facts.python_gil_mode not in {"gil", "free-threaded"}:
        return False
    is_free_threaded_abi = python_abi_match.group(1) == "t"
    if is_free_threaded_abi != (
        facts.python_gil_mode == "free-threaded"
    ):
        return False
    if not _platform_facts_are_well_formed(facts):
        return False
    parsed_sqlite_version = _parse_sqlite_version(facts.sqlite_version)
    if parsed_sqlite_version is None:
        return False
    if (
        not isinstance(facts.sqlite_version_number, int)
        or isinstance(facts.sqlite_version_number, bool)
        or facts.sqlite_version_number <= 0
    ):
        return False
    expected_version_number = (
        parsed_sqlite_version[0] * 1_000_000
        + parsed_sqlite_version[1] * 1_000
        + parsed_sqlite_version[2]
    )
    if facts.sqlite_version_number != expected_version_number:
        return False
    if re.fullmatch(r"[0-9a-f]{64}", facts.binding_extension_sha256) is None:
        return False
    if re.fullmatch(
        r"[0-9a-f]{64}",
        facts.sqlite_compile_options_sha256,
    ) is None:
        return False
    if re.fullmatch(
        r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} [0-9a-f]{64}",
        facts.sqlite_source_id,
    ) is None:
        return False
    return isinstance(facts.using_amalgamation, bool)


def _parse_python_version(value: object) -> tuple[int, int, int] | None:
    parsed = _parse_sqlite_version(value)
    if parsed is None or parsed[0] != 3 or parsed[1] not in range(10, 15):
        return None
    return parsed


def _platform_facts_are_well_formed(facts: RuntimeFacts) -> bool:
    if facts.os_name not in {"Ubuntu", "macOS", "Windows"}:
        return False
    version_pattern = r"[0-9]+(?:\.[0-9]+){1,3}"
    if re.fullmatch(version_pattern, facts.os_version) is None:
        return False
    if facts.os_name == "Windows":
        if facts.os_product_type not in {
            "domain_controller",
            "server",
            "workstation",
        }:
            return False
    elif facts.os_product_type != "not_applicable":
        return False
    return facts.architecture in {
        "AMD64",
        "aarch64",
        "amd64",
        "arm64",
        "x86_64",
    }


def _validate_manifest(manifest: Mapping[str, object]) -> None:
    schema_text = (
        resources.files("djsupport")
        .joinpath("contracts", _MANIFEST_SCHEMA)
        .read_text(encoding="utf-8")
    )
    schema = json.loads(schema_text)
    errors = sorted(
        Draft202012Validator(
            schema,
            format_checker=FormatChecker(),
        ).iter_errors(manifest),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = ".".join(
            str(part) for part in error.absolute_path
        ) or "root"
        raise QualificationManifestError(
            f"sqlite_runtime_manifest_invalid:{error.validator}:{location}"
        )
    entries = manifest.get("entries", [])
    if isinstance(entries, list):
        evidence_ids = [
            entry["evidence_id"]
            for entry in entries
            if isinstance(entry, dict)
        ]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise QualificationManifestError(
                "sqlite_runtime_manifest_invalid:unique:evidence_id"
            )
        selector_identities = [
            json.dumps(
                entry["selectors"],
                sort_keys=True,
                separators=(",", ":"),
            )
            for entry in entries
            if isinstance(entry, dict)
        ]
        if len(selector_identities) != len(set(selector_identities)):
            raise QualificationManifestError(
                "sqlite_runtime_manifest_invalid:unique:selectors"
            )
