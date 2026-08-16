#!/usr/bin/env python3
"""Qualify an exact DJ Support candidate without publishing artifacts."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import hashlib
from importlib.metadata import PackageNotFoundError, version as distribution_version
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import sys
import tarfile
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import zipfile

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))
QUALIFICATION_CONTRACTS = REPOSITORY_ROOT / "scripts" / "contracts"
INPUT_SCHEMA_PATH = (
    QUALIFICATION_CONTRACTS / "candidate-qualification-input.v1.schema.json"
)
EVIDENCE_SCHEMA_PATH = (
    QUALIFICATION_CONTRACTS
    / "candidate-qualification-evidence.v1.schema.json"
)
RUNTIME_CATALOG_PATH = (
    REPOSITORY_ROOT
    / "djsupport"
    / "contracts"
    / "apsw-runtime-artifacts.v1.json"
)
RUNTIME_POLICY_PATH = (
    REPOSITORY_ROOT
    / "djsupport"
    / "contracts"
    / "sqlite-runtime-qualification.v1.json"
)
SCENARIO_ORDER = (
    "preview",
    "apply_cutover",
    "resume",
    "backup",
    "restore",
    "rollback",
    "diagnostics",
)
REQUIRED_SCENARIOS = frozenset(SCENARIO_ORDER)
REQUIRED_PLATFORMS = frozenset({"Linux", "macOS", "Windows"})
REQUIRED_CHECKS = frozenset(
    {
        "offline_suite",
        "compilation",
        "repository_privacy",
        "archive_inspection",
        "clean_install",
    }
)
QUALIFICATION_WORKFLOW_NAME = "Candidate qualification"
PINNED_BUILD_TOOLS = {
    "build": "1.3.0",
    "setuptools": "80.9.0",
    "wheel": "0.45.1",
}
CONTRACT_JOB_STEPS = (
    "Check out qualification source",
    "Set up contract Python",
    "Install pinned contract tools",
    "Prove the synthetic non-release contract",
)
PLAN_JOB_STEPS = (
    "Check out the exact candidate source",
    "Set up canonical build Python",
    "Install pinned build and verification tools",
    "Install the exact checkout for offline validation",
    "Run complete offline and privacy checks",
    "Build, inspect, and bind the exact source",
)
QUALIFICATION_JOB_STEPS = (
    "Check out the exact candidate source",
    "Set up exact native Python",
    "Install pinned native qualification tools",
    "Require the canonical pure-Python wheel digest",
    "Reuse exact APSW artifact and loaded-runtime qualification",
    "Exercise the installed synthetic scenario seam",
)
DOCUMENTATION_JOB_STEPS = (
    "Check out exact product source",
    "Check out exact documentation source",
    "Set up documentation Node",
    "Set up documentation Python",
    "Install pinned documentation tools",
    "Test documentation contract",
    "Check exact product contract",
    "Validate documentation site",
    "Check documentation links and redirects",
    "Check documentation accessibility",
)
WINDOWS_PATH = re.compile(r"^[A-Za-z]:[\\/]")

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10
    import tomli as tomllib


class CandidateQualificationError(ValueError):
    """A stable, path-free qualification failure."""


def candidate_matrix() -> list[dict[str, str]]:
    """Return the exact qualified native matrix from the reviewed catalogs."""

    catalog = _load_json(RUNTIME_CATALOG_PATH)
    policy = _load_json(RUNTIME_POLICY_PATH)
    artifacts = catalog.get("artifacts")
    entries = policy.get("entries")
    if not isinstance(artifacts, list) or not isinstance(entries, list):
        _fail("runtime_contract_mismatch")
    active_ids = {
        entry.get("artifact_id")
        for entry in entries
        if isinstance(entry, Mapping) and entry.get("status") == "active"
    }
    artifact_ids = {
        artifact.get("artifact_id")
        for artifact in artifacts
        if isinstance(artifact, Mapping)
    }
    if len(artifact_ids) != len(artifacts) or artifact_ids != active_ids:
        _fail("runtime_contract_mismatch")

    matrix = []
    for artifact in artifacts:
        architecture = artifact.get("architecture")
        if architecture in {"arm64", "aarch64"}:
            setup_architecture = "arm64"
        elif architecture in {"x86_64", "AMD64"}:
            setup_architecture = "x64"
        else:
            _fail("runtime_contract_mismatch")
        matrix.append(
            {
                "runner": artifact["runner_label"],
                "python-version": artifact["python_version"],
                "architecture": architecture,
                "setup-architecture": setup_architecture,
                "platform": _platform_name(artifact.get("os")),
            }
        )
    return matrix


def inspect_distribution(path: Path, kind: str) -> dict[str, object]:
    """Inspect one built distribution and return public archive facts."""

    from scripts.sqlite_runtime_delivery import _inspect_source, _inspect_wheel

    try:
        if kind == "wheel":
            _inspect_wheel(path)
            with zipfile.ZipFile(path) as archive:
                member_count = len(archive.infolist())
        elif kind == "source":
            _inspect_source(path)
            with tarfile.open(path, "r:gz") as archive:
                member_count = len(archive.getmembers())
        else:
            _fail("archive_kind")
    except (OSError, tarfile.TarError, zipfile.BadZipFile):
        _fail("archive_inspection")
    except SystemExit as exc:
        reason = str(exc)
        if "private_package_member" in reason:
            _fail("private_archive_member")
        _fail("archive_inspection")
    try:
        size_bytes = path.stat().st_size
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        _fail("archive_inspection")
    if size_bytes < 1 or member_count < 1:
        _fail("archive_inspection")
    return {
        "filename": path.name,
        "size_bytes": size_bytes,
        "sha256": digest,
        "member_count": member_count,
        "inspection": "passed",
    }


def observe_source(
    *,
    expected_commit: str,
    expected_version: str,
    changelog_identity: str,
    source_date_epoch: int,
    repository_root: Path = REPOSITORY_ROOT,
) -> dict[str, object]:
    """Bind qualification to the exact checkout and its source-derived epoch."""

    status = _git_output(
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        repository_root=repository_root,
    )
    if status:
        _fail("source_checkout_dirty")
    observed_commit = _git_output(
        "rev-parse",
        "HEAD",
        repository_root=repository_root,
    )
    if observed_commit != expected_commit:
        _fail("product_commit_mismatch")
    try:
        with (repository_root / "pyproject.toml").open("rb") as source:
            observed_version = tomllib.load(source)["project"]["version"]
        changelog = (repository_root / "CHANGELOG.md").read_text(
            encoding="utf-8"
        )
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError):
        _fail("source_contract_unavailable")
    if observed_version != expected_version:
        _fail("package_version_mismatch")
    observed_changelog_headings = [
        line.removeprefix("## ")
        for line in changelog.splitlines()
        if line.startswith("## ")
    ]
    if observed_changelog_headings.count(changelog_identity) != 1:
        _fail("changelog_identity_mismatch")
    observed_epoch = _git_output(
        "show",
        "-s",
        "--format=%ct",
        "HEAD",
        repository_root=repository_root,
    )
    if not observed_epoch.isdigit() or int(observed_epoch) != source_date_epoch:
        _fail("source_date_epoch_mismatch")
    return {
        "product_commit": expected_commit,
        "observed_product_commit": observed_commit,
        "expected_version": expected_version,
        "observed_version": observed_version,
        "changelog_identity": changelog_identity,
        "observed_changelog_identity": changelog_identity,
        "source_date_epoch": source_date_epoch,
    }


def collect_candidate_archives(
    destination: Path,
    *,
    expected_version: str,
) -> dict[str, dict[str, object]]:
    """Build once with the reviewed adapter and inspect both distributions."""

    from scripts.sqlite_runtime_delivery import _build_and_inspect

    verify_build_tools()
    try:
        destination.mkdir(parents=True, exist_ok=False)
    except OSError:
        _fail("build_destination")
    try:
        wheel = _build_and_inspect(destination, quiet=True)
    except (OSError, subprocess.CalledProcessError, SystemExit):
        _fail("package_build")
    sources = list(destination.glob("djsupport-*.tar.gz"))
    if len(sources) != 1:
        _fail("package_build_shape")
    source = sources[0]
    expected_stem = f"djsupport-{expected_version}"
    if source.name != f"{expected_stem}.tar.gz":
        _fail("archive_identity_mismatch")
    if wheel.name != f"{expected_stem}-py3-none-any.whl":
        _fail("archive_identity_mismatch")
    return {
        "source": inspect_distribution(source, "source"),
        "wheel": inspect_distribution(wheel, "wheel"),
    }


def verify_build_tools(
    installed_versions: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Require the actual build frontend and backends to equal their pins."""

    if installed_versions is None:
        try:
            installed_versions = {
                name: distribution_version(name) for name in PINNED_BUILD_TOOLS
            }
        except PackageNotFoundError:
            _fail("build_tool_mismatch")
    observed = dict(installed_versions)
    if observed != PINNED_BUILD_TOOLS:
        _fail("build_tool_mismatch")
    return observed


def verify_wheel_rebuild(
    destination: Path,
    *,
    expected_commit: str,
    expected_version: str,
    changelog_identity: str,
    source_date_epoch: int,
    expected_sha256: str,
) -> dict[str, object]:
    """Require an independently rebuilt wheel to equal the canonical digest."""

    observe_source(
        expected_commit=expected_commit,
        expected_version=expected_version,
        changelog_identity=changelog_identity,
        source_date_epoch=source_date_epoch,
    )
    archives = collect_candidate_archives(
        destination,
        expected_version=expected_version,
    )
    wheel = archives["wheel"]
    if wheel["sha256"] != expected_sha256:
        _fail("wheel_digest_mismatch")
    return wheel


def synthetic_scenario_observation(
    *, platform_name: str,
    python_version: str,
) -> dict[str, object]:
    """Prove the installed-scenario seam without claiming product scenarios."""

    provider_markers = (
        "SPOTIPY_CLIENT_ID",
        "SPOTIPY_CLIENT_SECRET",
        "SPOTIPY_REDIRECT_URI",
        "BEATPORT_ACCESS_TOKEN",
    )
    if any(os.environ.get(name) for name in provider_markers):
        _fail("live_provider_capability")
    if platform_name not in REQUIRED_PLATFORMS:
        _fail("scenario_platform_missing")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", python_version):
        _fail("scenario_python_version")
    return {
        "platform": platform_name,
        "python_version": python_version,
        "synthetic_data": True,
        "live_provider_capability": False,
        "scenarios": list(SCENARIO_ORDER),
        "conclusion": "passed",
    }


def fetch_public_run_jobs(
    *,
    repository: str,
    run_id: str,
    opener=urlopen,
    ssl_context: ssl.SSLContext | None = None,
) -> dict[str, object]:
    """Read and bound public GitHub job observations without credentials."""

    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        _fail("workflow_observation")
    if not run_id.isdigit():
        _fail("workflow_observation")
    request = Request(
        (
            f"https://api.github.com/repos/{repository}/actions/runs/"
            f"{run_id}/jobs?filter=latest&per_page=100"
        ),
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "djsupport-candidate-qualification",
        },
    )
    if ssl_context is None:
        try:
            import certifi
        except ModuleNotFoundError:
            _fail("workflow_observation")
        ssl_context = ssl.create_default_context(cafile=certifi.where())
    try:
        with opener(request, timeout=30, context=ssl_context) as response:
            document = json.load(response)
    except (
        HTTPError,
        URLError,
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ):
        _fail("workflow_observation")
    if not isinstance(document, Mapping) or not isinstance(
        document.get("jobs"), list
    ):
        _fail("workflow_observation")

    jobs = []
    for job in document["jobs"]:
        if not isinstance(job, Mapping) or not isinstance(
            job.get("steps"), list
        ):
            _fail("workflow_observation")
        steps = []
        for step in job["steps"]:
            if not isinstance(step, Mapping):
                _fail("workflow_observation")
            steps.append(
                {
                    "name": step.get("name"),
                    "status": step.get("status"),
                    "conclusion": step.get("conclusion"),
                }
            )
        jobs.append(
            {
                "name": job.get("name"),
                "status": job.get("status"),
                "conclusion": job.get("conclusion"),
                "head_sha": job.get("head_sha"),
                "workflow_name": job.get("workflow_name"),
                "steps": steps,
            }
        )
    return {
        "repository": repository,
        "run_id": run_id,
        "total_count": len(jobs),
        "jobs": jobs,
    }


def finalize_qualification(
    *,
    preparation: Mapping[str, object],
    qualification_kind: str,
    documentation_commit: str,
    run: Mapping[str, object],
    run_jobs: Mapping[str, object],
    actions: list[str],
    scenario_evidence_kind: str = "synthetic_contract",
) -> dict[str, object]:
    """Concentrate successful job facts into the one validated evidence record."""

    try:
        prepared_candidate = preparation["candidate"]
        archives = preparation["archives"]
        product_commit = prepared_candidate["product_commit"]
        wheel_sha256 = archives["wheel"]["sha256"]
    except (KeyError, TypeError):
        _fail("input_contract")
    if (
        qualification_kind != "synthetic_non_release"
        or scenario_evidence_kind != "synthetic_contract"
    ):
        _fail("installed_scenarios_required")

    jobs = _successful_job_observations(
        run_jobs,
        expected_run=run,
        expected_product_commit=product_commit,
    )
    _require_successful_job(jobs, "Contract", CONTRACT_JOB_STEPS)
    _require_successful_job(jobs, "Plan", PLAN_JOB_STEPS)
    _require_successful_job(
        jobs,
        "Documentation",
        DOCUMENTATION_JOB_STEPS,
    )

    catalog = _load_json(RUNTIME_CATALOG_PATH)
    policy = _load_json(RUNTIME_POLICY_PATH)
    policy_entries = {
        entry["artifact_id"]: entry for entry in policy["entries"]
    }
    runtime_cells = []
    wheel_rebuilds = []
    scenario_observations = []
    for artifact in catalog["artifacts"]:
        entry = policy_entries.get(artifact["artifact_id"])
        if entry is None:
            _fail("runtime_contract_mismatch")
        _require_successful_job(
            jobs,
            (
                f"Qualify {artifact['runner_label']} / Python "
                f"{artifact['python_version']} / {artifact['architecture']}"
            ),
            QUALIFICATION_JOB_STEPS,
        )
        runner_image = entry["artifact"]["build"]["runner_image"]
        runtime_cells.append(
            {
                "artifact_id": artifact["artifact_id"],
                "runner_label": artifact["runner_label"],
                "runner_image_version": runner_image["version"],
                "runner_manifest_url": runner_image["manifest_url"],
                "python_version": artifact["python_version"],
                "architecture": artifact["architecture"],
                "apsw_filename": artifact["filename"],
                "apsw_sha256": artifact["sha256"],
                "runtime_evidence_id": entry["evidence_id"],
                "binding_resolution": "binary_only",
                "source_build": False,
                "conclusion": "passed",
            }
        )
        scenario_observations.append(
            synthetic_scenario_observation(
                platform_name=_platform_name(artifact["os"]),
                python_version=artifact["python_version"],
            )
        )
        wheel_rebuilds.append(
            {
                "runner_label": artifact["runner_label"],
                "python_version": artifact["python_version"],
                "architecture": artifact["architecture"],
                "wheel_sha256": wheel_sha256,
                "conclusion": "passed",
            }
        )

    source_epoch = prepared_candidate.get("source_date_epoch")
    candidate = dict(prepared_candidate)
    candidate.update(
        {
            "documentation_commit": documentation_commit,
            "observed_documentation_commit": documentation_commit,
        }
    )
    document = {
        "contract_id": "djsupport/candidate-qualification-input/1",
        "contract_version": 1,
        "qualification_kind": qualification_kind,
        "run": dict(run),
        "candidate": candidate,
        "build": {
            "tools": dict(PINNED_BUILD_TOOLS),
            "build_isolation": False,
            "source_date_epoch": source_epoch,
            "archives": archives,
            "wheel_rebuilds": wheel_rebuilds,
        },
        "runtime": {
            "artifact_catalog_id": catalog["catalog_id"],
            "artifact_catalog_sha256": _sha256(RUNTIME_CATALOG_PATH),
            "qualification_policy_id": policy["policy_id"],
            "qualification_policy_sha256": _sha256(RUNTIME_POLICY_PATH),
            "cells": runtime_cells,
        },
        "installed_scenarios": {
            "evidence_kind": scenario_evidence_kind,
            "required": list(SCENARIO_ORDER),
            "observations": scenario_observations,
        },
        "documentation": {
            "product_commit": product_commit,
            "documentation_commit": documentation_commit,
            "checkout": "exact_commit",
            "product_contract": "passed",
            "site_checks": {
                "validate": "passed",
                "broken_links": "passed",
                "accessibility": "passed",
            },
        },
        "checks": {
            "required": [
                "offline_suite",
                "compilation",
                "repository_privacy",
                "archive_inspection",
                "clean_install",
            ],
            "conclusions": {
                check: "passed" for check in REQUIRED_CHECKS
            },
        },
        "workflow": {
            "permissions": {"contents": "read"},
            "persist_credentials": False,
            "actions": list(actions),
            "secrets": False,
            "continue_on_error": False,
            "artifact_upload": False,
            "publication_capability": False,
        },
    }
    return qualify_candidate(document)


def _successful_job_observations(
    run_jobs: Mapping[str, object],
    *,
    expected_run: Mapping[str, object],
    expected_product_commit: object,
) -> dict[str, Mapping[str, object]]:
    if (
        run_jobs.get("repository") != expected_run.get("repository")
        or run_jobs.get("run_id") != expected_run.get("run_id")
    ):
        _fail("workflow_observation")
    raw_jobs = run_jobs.get("jobs")
    if not isinstance(raw_jobs, list):
        _fail("workflow_observation")
    jobs: dict[str, Mapping[str, object]] = {}
    for job in raw_jobs:
        if (
            not isinstance(job, Mapping)
            or not isinstance(job.get("name"), str)
            or job.get("head_sha") != expected_product_commit
            or job.get("workflow_name") != QUALIFICATION_WORKFLOW_NAME
        ):
            _fail("workflow_observation")
        name = job["name"]
        if name in jobs:
            _fail("workflow_observation")
        jobs[name] = job
    return jobs


def _platform_name(os_name: object) -> str:
    platform_name = {
        "Ubuntu": "Linux",
        "macOS": "macOS",
        "Windows": "Windows",
    }.get(os_name)
    if platform_name is None:
        _fail("runtime_contract_mismatch")
    return platform_name


def _require_successful_job(
    jobs: Mapping[str, Mapping[str, object]],
    name: str,
    required_steps: tuple[str, ...],
) -> None:
    job = jobs.get(name)
    if (
        job is None
        or job.get("status") != "completed"
        or job.get("conclusion") != "success"
        or not isinstance(job.get("steps"), list)
    ):
        _fail("workflow_observation")
    steps: dict[str, Mapping[str, object]] = {}
    for step in job["steps"]:
        if not isinstance(step, Mapping) or not isinstance(
            step.get("name"), str
        ):
            _fail("workflow_observation")
        step_name = step["name"]
        if step_name in steps:
            _fail("workflow_observation")
        steps[step_name] = step
    for required_step in required_steps:
        step = steps.get(required_step)
        if (
            step is None
            or step.get("status") != "completed"
            or step.get("conclusion") != "success"
        ):
            _fail("workflow_observation")


def qualify_candidate(document: Mapping[str, object]) -> dict[str, object]:
    """Return public evidence only when every candidate identity agrees."""

    candidate = document.get("candidate")
    if not isinstance(candidate, Mapping):
        raise CandidateQualificationError(
            "candidate_qualification_failed:input_contract"
        )
    if candidate.get("product_commit") != candidate.get(
        "observed_product_commit"
    ):
        raise CandidateQualificationError(
            "candidate_qualification_failed:product_commit_mismatch"
        )
    _validate(document, INPUT_SCHEMA_PATH, "input_contract")
    _reject_private_values(document)

    if candidate["documentation_commit"] != candidate[
        "observed_documentation_commit"
    ]:
        _fail("documentation_commit_mismatch")
    if candidate["expected_version"] != candidate["observed_version"]:
        _fail("package_version_mismatch")
    if candidate["changelog_identity"] != candidate[
        "observed_changelog_identity"
    ]:
        _fail("changelog_identity_mismatch")

    kind = document["qualification_kind"]
    expected_version = candidate["expected_version"]
    if kind == "release_candidate" and not re.fullmatch(
        r"[0-9]+\.[0-9]+\.[0-9]+rc[1-9][0-9]*",
        expected_version,
    ):
        _fail("release_version_required")

    build = document["build"]
    if build["tools"] != PINNED_BUILD_TOOLS:
        _fail("build_tool_mismatch")
    if build["source_date_epoch"] != candidate["source_date_epoch"]:
        _fail("source_date_epoch_mismatch")
    archives = build["archives"]
    expected_stem = f"djsupport-{expected_version}"
    if archives["source"]["filename"] != f"{expected_stem}.tar.gz":
        _fail("archive_identity_mismatch")
    if archives["wheel"]["filename"] != f"{expected_stem}-py3-none-any.whl":
        _fail("archive_identity_mismatch")

    catalog = _load_json(RUNTIME_CATALOG_PATH)
    policy = _load_json(RUNTIME_POLICY_PATH)
    runtime = document["runtime"]
    if (
        runtime["artifact_catalog_id"] != catalog["catalog_id"]
        or runtime["artifact_catalog_sha256"]
        != _sha256(RUNTIME_CATALOG_PATH)
        or runtime["qualification_policy_id"] != policy["policy_id"]
        or runtime["qualification_policy_sha256"]
        != _sha256(RUNTIME_POLICY_PATH)
    ):
        _fail("runtime_contract_mismatch")

    artifacts = {
        artifact["artifact_id"]: artifact for artifact in catalog["artifacts"]
    }
    policy_entries = {
        entry["artifact_id"]: entry for entry in policy["entries"]
    }
    runtime_cells = runtime["cells"]
    runtime_by_id = {cell["artifact_id"]: cell for cell in runtime_cells}
    if len(runtime_by_id) != len(runtime_cells):
        _fail("runtime_cell_duplicate")
    if set(runtime_by_id) != set(artifacts):
        _fail("runtime_cell_missing")
    for artifact_id, artifact in artifacts.items():
        cell = runtime_by_id[artifact_id]
        entry = policy_entries.get(artifact_id)
        if entry is None or entry.get("status") != "active":
            _fail("runtime_cell_unqualified")
        runner_image = entry["artifact"]["build"]["runner_image"]
        exact_facts = {
            "runner_label": artifact["runner_label"],
            "runner_image_version": runner_image["version"],
            "runner_manifest_url": runner_image["manifest_url"],
            "python_version": artifact["python_version"],
            "architecture": artifact["architecture"],
            "apsw_filename": artifact["filename"],
            "apsw_sha256": artifact["sha256"],
            "runtime_evidence_id": entry["evidence_id"],
        }
        if any(cell[name] != value for name, value in exact_facts.items()):
            _fail("runtime_cell_unqualified")
        if cell["source_build"] or cell["binding_resolution"] != "binary_only":
            _fail("runtime_source_build")

    wheel_sha256 = archives["wheel"]["sha256"]
    rebuilds = build["wheel_rebuilds"]
    rebuild_by_cell = {
        (
            rebuild["runner_label"],
            rebuild["python_version"],
            rebuild["architecture"],
        ): rebuild
        for rebuild in rebuilds
    }
    expected_cells = {
        (
            artifact["runner_label"],
            artifact["python_version"],
            artifact["architecture"],
        )
        for artifact in artifacts.values()
    }
    if len(rebuild_by_cell) != len(rebuilds):
        _fail("wheel_rebuild_duplicate")
    if set(rebuild_by_cell) != expected_cells:
        _fail("wheel_rebuild_missing")
    if any(
        rebuild["wheel_sha256"] != wheel_sha256
        for rebuild in rebuilds
    ):
        _fail("wheel_digest_mismatch")

    scenarios = document["installed_scenarios"]
    if (
        kind == "release_candidate"
        and scenarios["evidence_kind"] != "installed_product"
    ):
        _fail("installed_scenarios_required")
    if set(scenarios["required"]) != REQUIRED_SCENARIOS:
        _fail("scenario_contract_mismatch")
    observed_platforms = {
        observation["platform"] for observation in scenarios["observations"]
    }
    if observed_platforms != REQUIRED_PLATFORMS:
        _fail("scenario_platform_missing")
    for observation in scenarios["observations"]:
        if observation["live_provider_capability"]:
            _fail("live_provider_capability")
        if not observation["synthetic_data"]:
            _fail("owner_data_forbidden")
        if set(observation["scenarios"]) != REQUIRED_SCENARIOS:
            _fail("scenario_missing")

    documentation = document["documentation"]
    if (
        documentation["product_commit"] != candidate["product_commit"]
        or documentation["documentation_commit"]
        != candidate["documentation_commit"]
    ):
        _fail("documentation_evidence_mismatch")

    checks = document["checks"]
    if set(checks["required"]) != REQUIRED_CHECKS:
        _fail("check_contract_mismatch")
    if set(checks["conclusions"]) != REQUIRED_CHECKS:
        _fail("check_missing")

    workflow = document["workflow"]
    if workflow != {
        "permissions": {"contents": "read"},
        "persist_credentials": False,
        "actions": workflow["actions"],
        "secrets": False,
        "continue_on_error": False,
        "artifact_upload": False,
        "publication_capability": False,
    }:
        _fail("workflow_capability")

    evidence = {
        "schema_id": "djsupport/candidate-qualification-evidence/1",
        "schema_version": 1,
        "conclusion": "passed",
        "qualification_kind": kind,
        "run": dict(document["run"]),
        "candidate": {
            "product_commit": candidate["product_commit"],
            "documentation_commit": candidate["documentation_commit"],
            "package_version": expected_version,
            "changelog_identity": candidate["changelog_identity"],
        },
        "build": {
            "source": _public_archive(archives["source"]),
            "wheel": _public_archive(archives["wheel"]),
            "reproducible_cells": len(rebuilds),
        },
        "runtime": {
            "artifact_catalog_id": runtime["artifact_catalog_id"],
            "qualification_policy_id": runtime["qualification_policy_id"],
            "qualified_cells": len(runtime_cells),
            "binding_resolution": "binary_only",
        },
        "installed_scenarios": {
            "evidence_kind": scenarios["evidence_kind"],
            "required": list(scenarios["required"]),
            "platforms": sorted(
                observed_platforms,
                key=("Linux", "macOS", "Windows").index,
            ),
            "conclusion": "passed",
        },
        "documentation": {
            "product_commit": documentation["product_commit"],
            "documentation_commit": documentation["documentation_commit"],
            "product_contract": "passed",
            "site_checks": dict(documentation["site_checks"]),
        },
        "checks": dict(sorted(checks["conclusions"].items())),
        "publication": {
            "tag": False,
            "github_release": False,
            "artifact_upload": False,
            "package_upload": False,
            "advisory_publication": False,
        },
        "data_provider_state": {
            "synthetic_only": True,
            "live_provider_call": False,
            "owner_data": False,
        },
    }
    _validate(evidence, EVIDENCE_SCHEMA_PATH, "evidence_contract")
    _reject_private_values(evidence)
    return evidence


def _public_archive(archive: Mapping[str, object]) -> dict[str, object]:
    return {
        "filename": archive["filename"],
        "size_bytes": archive["size_bytes"],
        "sha256": archive["sha256"],
        "member_count": archive["member_count"],
    }


def _load_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _fail("contract_unavailable")
    if not isinstance(value, dict):
        _fail("contract_unavailable")
    return value


def _sha256(path: Path) -> str:
    try:
        payload = path.read_bytes()
    except OSError:
        _fail("contract_unavailable")
    return hashlib.sha256(payload).hexdigest()


def _git_output(
    *arguments: str,
    repository_root: Path = REPOSITORY_ROOT,
) -> str:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        _fail("source_contract_unavailable")
    return result.stdout.strip()


def _validate(
    document: Mapping[str, object],
    schema_path: Path,
    reason: str,
) -> None:
    schema = _load_json(schema_path)
    try:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(
            schema,
            format_checker=FormatChecker(),
        ).validate(document)
    except (SchemaError, ValidationError):
        _fail(reason)


def _reject_private_values(value: object) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).casefold()
            if normalized in {
                "path",
                "local_path",
                "raw_exception",
                "raw_log",
                "raw_sql",
                "credentials",
                "owner_facts",
            }:
                _fail("private_evidence")
            _reject_private_values(child)
        return
    if isinstance(value, list):
        for child in value:
            _reject_private_values(child)
        return
    if isinstance(value, str):
        normalized = value.casefold()
        if (
            value.startswith(("/", "~/"))
            or WINDOWS_PATH.match(value)
            or normalized.startswith("file://")
            or "\\users\\" in normalized
        ):
            _fail("private_evidence")


def _fail(reason: str) -> None:
    raise CandidateQualificationError(
        f"candidate_qualification_failed:{reason}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    qualify_parser = subparsers.add_parser("qualify")
    qualify_parser.add_argument("--input", required=True)
    subparsers.add_parser("matrix")
    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--expected-commit", required=True)
    prepare_parser.add_argument("--expected-version", required=True)
    prepare_parser.add_argument("--changelog-identity", required=True)
    prepare_parser.add_argument("--source-date-epoch", required=True, type=int)
    prepare_parser.add_argument("--output-dir", required=True)
    rebuild_parser = subparsers.add_parser("rebuild-wheel")
    rebuild_parser.add_argument("--expected-commit", required=True)
    rebuild_parser.add_argument("--expected-version", required=True)
    rebuild_parser.add_argument("--changelog-identity", required=True)
    rebuild_parser.add_argument(
        "--source-date-epoch",
        required=True,
        type=int,
    )
    rebuild_parser.add_argument("--expected-sha256", required=True)
    rebuild_parser.add_argument("--output-dir", required=True)
    scenario_parser = subparsers.add_parser("synthetic-scenarios")
    scenario_parser.add_argument("--platform", required=True)
    scenario_parser.add_argument("--python-version", required=True)
    observe_run_parser = subparsers.add_parser("observe-run")
    observe_run_parser.add_argument("--repository", required=True)
    observe_run_parser.add_argument("--run-id", required=True)
    finalize_parser = subparsers.add_parser("finalize")
    finalize_parser.add_argument("--preparation", required=True)
    finalize_parser.add_argument("--run-jobs", required=True)
    finalize_parser.add_argument(
        "--qualification-kind",
        choices=("synthetic_non_release", "release_candidate"),
        required=True,
    )
    finalize_parser.add_argument("--documentation-commit", required=True)
    finalize_parser.add_argument("--repository", required=True)
    finalize_parser.add_argument("--run-id", required=True)
    finalize_parser.add_argument("--run-url", required=True)
    finalize_parser.add_argument("--action", action="append", required=True)
    finalize_parser.add_argument(
        "--scenario-evidence-kind",
        choices=("synthetic_contract", "installed_product"),
        default="synthetic_contract",
    )
    args = parser.parse_args()

    try:
        if args.command == "matrix":
            result: object = {"include": candidate_matrix()}
        elif args.command == "prepare":
            source = observe_source(
                expected_commit=args.expected_commit,
                expected_version=args.expected_version,
                changelog_identity=args.changelog_identity,
                source_date_epoch=args.source_date_epoch,
            )
            result = {
                "candidate": source,
                "archives": collect_candidate_archives(
                    Path(args.output_dir),
                    expected_version=args.expected_version,
                ),
            }
        elif args.command == "rebuild-wheel":
            result = verify_wheel_rebuild(
                Path(args.output_dir),
                expected_commit=args.expected_commit,
                expected_version=args.expected_version,
                changelog_identity=args.changelog_identity,
                source_date_epoch=args.source_date_epoch,
                expected_sha256=args.expected_sha256,
            )
        elif args.command == "synthetic-scenarios":
            result = synthetic_scenario_observation(
                platform_name=args.platform,
                python_version=args.python_version,
            )
        elif args.command == "observe-run":
            result = fetch_public_run_jobs(
                repository=args.repository,
                run_id=args.run_id,
            )
        elif args.command == "finalize":
            try:
                preparation = json.loads(
                    Path(args.preparation).read_text(encoding="utf-8")
                )
                run_jobs = json.loads(
                    Path(args.run_jobs).read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError):
                _fail("input_contract")
            if not isinstance(preparation, dict) or not isinstance(
                run_jobs, dict
            ):
                _fail("input_contract")
            result = finalize_qualification(
                preparation=preparation,
                qualification_kind=args.qualification_kind,
                documentation_commit=args.documentation_commit,
                run={
                    "repository": args.repository,
                    "run_id": args.run_id,
                    "run_url": args.run_url,
                },
                run_jobs=run_jobs,
                actions=args.action,
                scenario_evidence_kind=args.scenario_evidence_kind,
            )
        else:
            try:
                document = json.loads(
                    Path(args.input).read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError):
                _fail("input_contract")
            if not isinstance(document, dict):
                _fail("input_contract")
            result = qualify_candidate(document)
    except CandidateQualificationError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
