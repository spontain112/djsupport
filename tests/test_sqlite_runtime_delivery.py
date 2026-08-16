"""Release-contract tests for the one qualified APSW delivery route."""

from __future__ import annotations

import json
import re
import tarfile
from io import BytesIO
from pathlib import Path
import zipfile

from jsonschema import Draft202012Validator, FormatChecker
import pytest
import yaml

from djsupport.operational_store.delivery import (
    RuntimeDeliveryError,
    artifact_for_cell,
    load_artifact_catalog,
    verify_downloaded_wheel,
)
from scripts.sqlite_runtime_delivery import _inspect_source, _inspect_wheel

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10
    import tomli as tomllib


REPOSITORY_ROOT = Path(__file__).parents[1]
CONTRACTS = REPOSITORY_ROOT / "djsupport" / "contracts"
CATALOG_PATH = CONTRACTS / "apsw-runtime-artifacts.v1.json"
CATALOG_SCHEMA_PATH = CONTRACTS / "apsw-runtime-artifacts.v1.schema.json"
QUALIFICATION_PATH = CONTRACTS / "sqlite-runtime-qualification.v1.json"
WORKFLOW_PATH = (
    REPOSITORY_ROOT / ".github" / "workflows" / "sqlite-runtime.yml"
)

EXPECTED_CELLS = {
    ("ubuntu-24.04", "3.10.21", "x86_64"),
    ("ubuntu-24.04", "3.11.16", "x86_64"),
    ("ubuntu-24.04", "3.12.14", "x86_64"),
    ("ubuntu-24.04", "3.13.15", "x86_64"),
    ("ubuntu-24.04", "3.14.7", "x86_64"),
    ("ubuntu-24.04-arm", "3.10.21", "aarch64"),
    ("ubuntu-24.04-arm", "3.11.16", "aarch64"),
    ("ubuntu-24.04-arm", "3.12.14", "aarch64"),
    ("ubuntu-24.04-arm", "3.13.15", "aarch64"),
    ("ubuntu-24.04-arm", "3.14.7", "aarch64"),
    ("macos-15-intel", "3.10.21", "x86_64"),
    ("macos-15-intel", "3.11.9", "x86_64"),
    ("macos-15-intel", "3.12.10", "x86_64"),
    ("macos-15-intel", "3.13.15", "x86_64"),
    ("macos-15-intel", "3.14.7", "x86_64"),
    ("macos-15", "3.10.11", "arm64"),
    ("macos-15", "3.11.9", "arm64"),
    ("macos-15", "3.12.10", "arm64"),
    ("macos-15", "3.13.15", "arm64"),
    ("macos-15", "3.14.7", "arm64"),
    ("windows-2025", "3.10.11", "AMD64"),
    ("windows-2025", "3.11.9", "AMD64"),
    ("windows-2025", "3.12.10", "AMD64"),
    ("windows-2025", "3.13.15", "AMD64"),
    ("windows-2025", "3.14.7", "AMD64"),
}


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_package_pins_the_only_production_binding_and_python_surface():
    with (REPOSITORY_ROOT / "pyproject.toml").open("rb") as source:
        project = tomllib.load(source)["project"]

    assert project["requires-python"] == ">=3.10,<3.15"
    assert [
        dependency
        for dependency in project["dependencies"]
        if dependency.lower().startswith("apsw")
    ] == ["apsw==3.53.4.0"]


def test_versioned_artifact_catalog_is_strict_and_claims_only_proved_cells():
    catalog = _load_json(CATALOG_PATH)
    schema = _load_json(CATALOG_SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(
        schema,
        format_checker=FormatChecker(),
    ).validate(catalog)

    assert catalog["selected_binding"] == {
        "distribution": "apsw",
        "version": "3.53.4.0",
    }
    assert catalog["publisher"] == {
        "kind": "GitHub",
        "repository": "rogerbinns/apsw",
        "workflow": "build-pypi.yml",
        "source_repository_url": "https://github.com/rogerbinns/apsw",
        "source_commit": "09b6a89e13e1c49f13bfb92fdb8725d1a0f03b5a",
        "workflow_url": (
            "https://github.com/rogerbinns/apsw/actions/workflows/"
            "build-pypi.yml"
        ),
    }

    artifacts = catalog["artifacts"]
    cells = {
        (
            artifact["runner_label"],
            artifact["python_version"],
            artifact["architecture"],
        )
        for artifact in artifacts
    }
    assert cells == EXPECTED_CELLS
    assert len(artifacts) == len(EXPECTED_CELLS)
    assert len({artifact["artifact_id"] for artifact in artifacts}) == len(
        artifacts
    )
    assert len({artifact["filename"] for artifact in artifacts}) == len(
        artifacts
    )
    for artifact in artifacts:
        assert artifact["filename"].endswith(".whl")
        assert "sdist" not in artifact["artifact_id"]
        assert artifact["download_url"].startswith(
            "https://files.pythonhosted.org/"
        )
        assert artifact["provenance_url"] == (
            "https://pypi.org/integrity/apsw/3.53.4.0/"
            f"{artifact['filename']}/provenance"
        )


def test_every_claimed_artifact_has_one_active_runtime_admission():
    catalog = _load_json(CATALOG_PATH)
    qualification = _load_json(QUALIFICATION_PATH)
    artifacts = {
        artifact["artifact_id"]: artifact
        for artifact in catalog["artifacts"]
    }
    entries = qualification["entries"]

    assert len(entries) == len(artifacts)
    assert {entry["artifact_id"] for entry in entries} == set(artifacts)
    for entry in entries:
        artifact = artifacts[entry["artifact_id"]]
        assert entry["status"] == "active"
        assert entry["classification"] == "qualified_upstream"
        assert entry["artifact"]["filename"] == artifact["filename"]
        assert entry["artifact"]["download_url"] == artifact["download_url"]
        assert entry["artifact"]["size_bytes"] == artifact["size_bytes"]
        assert entry["artifact"]["sha256"] == artifact["sha256"]
        assert entry["artifact"]["publisher"]["provenance_url"] == (
            artifact["provenance_url"]
        )


def test_native_matrix_uses_clean_binary_installs_and_no_publish_authority():
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    workflow = yaml.safe_load(workflow_text)
    jobs = workflow["jobs"]

    assert workflow["permissions"] == {"contents": "read"}
    assert set(workflow["on"]) == {"pull_request", "push", "workflow_dispatch"}
    assert workflow["on"]["push"]["branches"] == ["main"]
    assert set(jobs) == {"qualify"}
    job = jobs["qualify"]
    assert "permissions" not in job
    assert job["runs-on"] == "${{ matrix.runner }}"
    assert job["timeout-minutes"] == 30
    assert job["strategy"]["fail-fast"] is False

    matrix = job["strategy"]["matrix"]["include"]
    workflow_cells = {
        (
            cell["runner"],
            cell["python-version"],
            cell["architecture"],
        )
        for cell in matrix
    }
    assert workflow_cells == EXPECTED_CELLS
    assert len(matrix) == len(EXPECTED_CELLS)

    steps = job["steps"]
    uses = [step["uses"] for step in steps if "uses" in step]
    assert uses
    assert all(
        re.fullmatch(
            r"actions/(?:checkout|setup-python)@[0-9a-f]{40}",
            action,
        )
        for action in uses
    )
    checkout = next(
        step for step in steps if step.get("uses", "").startswith(
            "actions/checkout@"
        )
    )
    assert checkout["with"]["persist-credentials"] is False

    commands = "\n".join(step.get("run", "") for step in steps)
    for tool in (
        '"build==1.3.0"',
        '"jsonschema==4.26.0"',
        '"pypi-attestations==0.0.30"',
    ):
        assert tool in commands
    assert "python scripts/sqlite_runtime_delivery.py verify" in commands
    script = (
        REPOSITORY_ROOT / "scripts" / "sqlite_runtime_delivery.py"
    ).read_text(encoding="utf-8")
    assert "--only-binary=:all:" in script
    assert "pypi_attestations" in script
    assert '"-m",\n            "build",' in script
    assert "_inspect_wheel" in script and "_inspect_source" in script

    forbidden = (
        "pull_request_target",
        "secrets.",
        "permissions: write",
        "id-token: write",
        "continue-on-error",
        "upload-artifact",
        "twine",
        "git tag",
        "gh release",
        "spotify",
        "beatport",
    )
    normalized = workflow_text.casefold()
    assert not [marker for marker in forbidden if marker in normalized]


def test_runtime_delivery_is_credited_and_monitoring_has_an_owner():
    credits = (REPOSITORY_ROOT / "THIRD_PARTY.md").read_text(encoding="utf-8")
    delivery = (
        REPOSITORY_ROOT / "docs" / "sqlite-runtime-delivery.md"
    ).read_text(encoding="utf-8")
    normalized = " ".join(delivery.split()).casefold()

    assert "[APSW](https://github.com/rogerbinns/apsw)" in credits
    assert "[SQLite](https://sqlite.org/)" in credits
    assert "public domain" in credits.casefold()
    for phrase in (
        "official sqlite news",
        "apsw release feed",
        "withdrawal",
        "revocation",
        "security policy",
        "maintainer",
        "binary-only",
        "json remains the production authority",
    ):
        assert phrase in normalized


def test_an_unclaimed_native_cell_has_no_artifact_fallback():
    catalog = load_artifact_catalog()

    with pytest.raises(RuntimeDeliveryError) as caught:
        artifact_for_cell(
            catalog,
            runner_label="windows-2025",
            python_version="3.14.7",
            architecture="ARM64",
        )

    assert caught.value.reason_code == "native_cell_unapproved"


def test_downloaded_wheel_digest_near_miss_fails_closed(tmp_path):
    wheel = tmp_path / "apsw-test.whl"
    wheel.write_bytes(b"synthetic wheel")
    artifact = {
        "filename": wheel.name,
        "size_bytes": wheel.stat().st_size,
        "sha256": "0" * 64,
    }

    with pytest.raises(RuntimeDeliveryError) as caught:
        verify_downloaded_wheel(wheel, artifact)

    assert caught.value.reason_code == "artifact_digest_unapproved"


def _write_test_wheel(path: Path, member: str, payload: bytes = b"safe\n"):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(member, payload)


def _write_test_source(path: Path, member: str, payload: bytes = b"safe\n"):
    with tarfile.open(path, "w:gz") as archive:
        info = tarfile.TarInfo(f"djsupport-0.6.0/{member}")
        info.size = len(payload)
        archive.addfile(info, BytesIO(payload))


@pytest.mark.parametrize(
    "member",
    [
        "djsupport/spotify-credentials.json",
        "djsupport/operational-store.sqlite3-wal",
        "djsupport/djsupport-backup-2026-08-16.zip",
        "djsupport/djsupport-migration-staging/candidate.json",
        "djsupport/djsupport-diagnostics.json",
        "djsupport/matching-knowledge.json",
    ],
)
@pytest.mark.parametrize("archive_kind", ["wheel", "source"])
def test_package_inspection_rejects_private_state_members(
    tmp_path,
    member,
    archive_kind,
):
    if archive_kind == "wheel":
        archive_path = tmp_path / "djsupport.whl"
        _write_test_wheel(archive_path, member)
        inspector = _inspect_wheel
    else:
        archive_path = tmp_path / "djsupport.tar.gz"
        _write_test_source(archive_path, member)
        inspector = _inspect_source

    with pytest.raises(SystemExit, match="private_package_member"):
        inspector(archive_path)


@pytest.mark.parametrize("archive_kind", ["wheel", "source"])
def test_package_inspection_rejects_untracked_members(
    tmp_path,
    archive_kind,
):
    member = "djsupport/unreviewed-generated-state.json"
    if archive_kind == "wheel":
        archive_path = tmp_path / "djsupport.whl"
        _write_test_wheel(archive_path, member)
        inspector = _inspect_wheel
    else:
        archive_path = tmp_path / "djsupport.tar.gz"
        _write_test_source(archive_path, member)
        inspector = _inspect_source

    with pytest.raises(SystemExit, match="unexpected_package_member"):
        inspector(archive_path)


@pytest.mark.parametrize("archive_kind", ["wheel", "source"])
def test_package_inspection_rejects_build_root_leaks(
    tmp_path,
    archive_kind,
):
    member = "djsupport/__init__.py"
    payload = str(REPOSITORY_ROOT).encode("utf-8")
    if archive_kind == "wheel":
        archive_path = tmp_path / "djsupport.whl"
        _write_test_wheel(archive_path, member, payload)
        inspector = _inspect_wheel
    else:
        archive_path = tmp_path / "djsupport.tar.gz"
        _write_test_source(archive_path, member, payload)
        inspector = _inspect_source

    with pytest.raises(SystemExit, match="local_path_in_package"):
        inspector(archive_path)


@pytest.mark.parametrize(
    "member",
    [
        "../private.txt",
        "/private/local.txt",
        "C:\\Users\\owner\\private.txt",
    ],
)
def test_wheel_inspection_rejects_cross_platform_unsafe_paths(
    tmp_path,
    member,
):
    archive_path = tmp_path / "djsupport.whl"
    _write_test_wheel(archive_path, member)

    with pytest.raises(SystemExit, match="unsafe_package_path"):
        _inspect_wheel(archive_path)
