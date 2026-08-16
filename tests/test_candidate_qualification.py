"""Publication-free release-candidate qualification contract."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import zipfile

from jsonschema import Draft202012Validator
import pytest
import yaml

from scripts.candidate_qualification import (
    CandidateQualificationError,
    candidate_matrix,
    fetch_public_run_jobs,
    finalize_qualification,
    inspect_distribution,
    observe_source,
    qualify_candidate,
    verify_build_tools,
)


ROOT = Path(__file__).parents[1]
CONTRACTS = ROOT / "djsupport" / "contracts"
QUALIFICATION_CONTRACTS = ROOT / "scripts" / "contracts"
INPUT_SCHEMA = (
    QUALIFICATION_CONTRACTS / "candidate-qualification-input.v1.schema.json"
)
EVIDENCE_SCHEMA = (
    QUALIFICATION_CONTRACTS / "candidate-qualification-evidence.v1.schema.json"
)
RUNTIME_CATALOG = CONTRACTS / "apsw-runtime-artifacts.v1.json"
RUNTIME_POLICY = CONTRACTS / "sqlite-runtime-qualification.v1.json"
CANDIDATE_WORKFLOW = ROOT / ".github" / "workflows" / "candidate-qualification.yml"


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def synthetic_qualification_input() -> dict[str, object]:
    catalog = _load_json(RUNTIME_CATALOG)
    policy = _load_json(RUNTIME_POLICY)
    policy_entries = {
        entry["artifact_id"]: entry for entry in policy["entries"]
    }
    runtime_cells = []
    wheel_rebuilds = []
    wheel_sha256 = "a" * 64
    for artifact in catalog["artifacts"]:
        entry = policy_entries[artifact["artifact_id"]]
        runner_image = entry["artifact"]["build"]["runner_image"]
        cell = {
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
        runtime_cells.append(cell)
        wheel_rebuilds.append(
            {
                "runner_label": artifact["runner_label"],
                "python_version": artifact["python_version"],
                "architecture": artifact["architecture"],
                "wheel_sha256": wheel_sha256,
                "conclusion": "passed",
            }
        )

    scenarios = [
        "preview",
        "apply_cutover",
        "resume",
        "backup",
        "restore",
        "rollback",
        "diagnostics",
    ]
    return {
        "contract_id": "djsupport/candidate-qualification-input/1",
        "contract_version": 1,
        "qualification_kind": "synthetic_non_release",
        "run": {
            "repository": "spontain112/djsupport",
            "run_id": "synthetic-181",
            "run_url": "https://github.com/spontain112/djsupport/actions/runs/181",
        },
        "candidate": {
            "product_commit": "1" * 40,
            "observed_product_commit": "1" * 40,
            "documentation_commit": "2" * 40,
            "observed_documentation_commit": "2" * 40,
            "expected_version": "0.0.0.dev181",
            "observed_version": "0.0.0.dev181",
            "changelog_identity": "[Synthetic 0.0.0.dev181]",
            "observed_changelog_identity": "[Synthetic 0.0.0.dev181]",
            "source_date_epoch": 1_786_867_310,
        },
        "build": {
            "tools": {
                "build": "1.3.0",
                "setuptools": "80.9.0",
                "wheel": "0.45.1",
            },
            "build_isolation": False,
            "source_date_epoch": 1_786_867_310,
            "archives": {
                "source": {
                    "filename": "djsupport-0.0.0.dev181.tar.gz",
                    "size_bytes": 1000,
                    "sha256": "b" * 64,
                    "member_count": 100,
                    "inspection": "passed",
                },
                "wheel": {
                    "filename": "djsupport-0.0.0.dev181-py3-none-any.whl",
                    "size_bytes": 900,
                    "sha256": wheel_sha256,
                    "member_count": 80,
                    "inspection": "passed",
                },
            },
            "wheel_rebuilds": wheel_rebuilds,
        },
        "runtime": {
            "artifact_catalog_id": catalog["catalog_id"],
            "artifact_catalog_sha256": _sha256(RUNTIME_CATALOG),
            "qualification_policy_id": policy["policy_id"],
            "qualification_policy_sha256": _sha256(RUNTIME_POLICY),
            "cells": runtime_cells,
        },
        "installed_scenarios": {
            "evidence_kind": "synthetic_contract",
            "required": scenarios,
            "observations": [
                {
                    "platform": platform,
                    "python_version": python_version,
                    "synthetic_data": True,
                    "live_provider_capability": False,
                    "scenarios": scenarios,
                    "conclusion": "passed",
                }
                for platform, python_version in (
                    ("Linux", "3.10.21"),
                    ("macOS", "3.14.7"),
                    ("Windows", "3.14.7"),
                )
            ],
        },
        "documentation": {
            "product_commit": "1" * 40,
            "documentation_commit": "2" * 40,
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
                "offline_suite": "passed",
                "compilation": "passed",
                "repository_privacy": "passed",
                "archive_inspection": "passed",
                "clean_install": "passed",
            },
        },
        "workflow": {
            "permissions": {"contents": "read"},
            "persist_credentials": False,
            "actions": [
                "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd",
                "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97",
            ],
            "secrets": False,
            "continue_on_error": False,
            "artifact_upload": False,
            "publication_capability": False,
        },
    }


def synthetic_workflow_run_observation() -> dict[str, object]:
    def successful_job(name: str, steps: tuple[str, ...]) -> dict[str, object]:
        return {
            "name": name,
            "head_sha": "1" * 40,
            "workflow_name": "Candidate qualification",
            "status": "completed",
            "conclusion": "success",
            "steps": [
                {"name": step, "status": "completed", "conclusion": "success"}
                for step in steps
            ],
        }

    jobs = [
        successful_job(
            "Contract",
            (
                "Check out qualification source",
                "Set up contract Python",
                "Install pinned contract tools",
                "Prove the synthetic non-release contract",
            ),
        ),
        successful_job(
            "Plan",
            (
                "Check out the exact candidate source",
                "Set up canonical build Python",
                "Install pinned build and verification tools",
                "Install the exact checkout for offline validation",
                "Run complete offline and privacy checks",
                "Build, inspect, and bind the exact source",
            ),
        ),
        successful_job(
            "Documentation",
            (
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
            ),
        ),
    ]
    qualification_steps = (
        "Check out the exact candidate source",
        "Set up exact native Python",
        "Install pinned native qualification tools",
        "Require the canonical pure-Python wheel digest",
        "Reuse exact APSW artifact and loaded-runtime qualification",
        "Exercise the installed synthetic scenario seam",
    )
    jobs.extend(
        successful_job(
            (
                f"Qualify {cell['runner']} / Python "
                f"{cell['python-version']} / {cell['architecture']}"
            ),
            qualification_steps,
        )
        for cell in candidate_matrix()
    )
    return {
        "repository": "spontain112/djsupport",
        "run_id": "synthetic-181",
        "total_count": len(jobs),
        "jobs": jobs,
    }


class TestCandidateQualificationContract:
    def test_wrong_product_commit_fails_closed(self) -> None:
        document = deepcopy(synthetic_qualification_input())
        document["candidate"]["observed_product_commit"] = "3" * 40

        with pytest.raises(
            CandidateQualificationError,
            match="candidate_qualification_failed:product_commit_mismatch",
        ):
            qualify_candidate(document)

    def test_complete_synthetic_contract_returns_schema_valid_path_free_evidence(
        self,
    ) -> None:
        input_schema = _load_json(INPUT_SCHEMA)
        evidence_schema = _load_json(EVIDENCE_SCHEMA)
        Draft202012Validator.check_schema(input_schema)
        Draft202012Validator.check_schema(evidence_schema)
        document = synthetic_qualification_input()
        Draft202012Validator(input_schema).validate(document)

        evidence = qualify_candidate(document)

        Draft202012Validator(evidence_schema).validate(evidence)
        assert evidence == {
            "schema_id": "djsupport/candidate-qualification-evidence/1",
            "schema_version": 1,
            "conclusion": "passed",
            "qualification_kind": "synthetic_non_release",
            "run": {
                "repository": "spontain112/djsupport",
                "run_id": "synthetic-181",
                "run_url": "https://github.com/spontain112/djsupport/actions/runs/181",
            },
            "candidate": {
                "product_commit": "1" * 40,
                "documentation_commit": "2" * 40,
                "package_version": "0.0.0.dev181",
                "changelog_identity": "[Synthetic 0.0.0.dev181]",
            },
            "build": {
                "source": {
                    "filename": "djsupport-0.0.0.dev181.tar.gz",
                    "size_bytes": 1000,
                    "sha256": "b" * 64,
                    "member_count": 100,
                },
                "wheel": {
                    "filename": "djsupport-0.0.0.dev181-py3-none-any.whl",
                    "size_bytes": 900,
                    "sha256": "a" * 64,
                    "member_count": 80,
                },
                "reproducible_cells": 25,
            },
            "runtime": {
                "artifact_catalog_id": "djsupport/apsw-runtime-artifacts/1",
                "qualification_policy_id": (
                    "djsupport/sqlite-runtime-qualification/1"
                ),
                "qualified_cells": 25,
                "binding_resolution": "binary_only",
            },
            "installed_scenarios": {
                "evidence_kind": "synthetic_contract",
                "required": [
                    "preview",
                    "apply_cutover",
                    "resume",
                    "backup",
                    "restore",
                    "rollback",
                    "diagnostics",
                ],
                "platforms": ["Linux", "macOS", "Windows"],
                "conclusion": "passed",
            },
            "documentation": {
                "product_commit": "1" * 40,
                "documentation_commit": "2" * 40,
                "product_contract": "passed",
                "site_checks": {
                    "validate": "passed",
                    "broken_links": "passed",
                    "accessibility": "passed",
                },
            },
            "checks": {
                "archive_inspection": "passed",
                "clean_install": "passed",
                "compilation": "passed",
                "offline_suite": "passed",
                "repository_privacy": "passed",
            },
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
        serialized = json.dumps(evidence, sort_keys=True)
        assert "/private/" not in serialized
        assert "\\Users\\" not in serialized

    def test_release_candidate_cannot_claim_synthetic_scenarios_as_product_proof(
        self,
    ) -> None:
        document = synthetic_qualification_input()
        document["qualification_kind"] = "release_candidate"
        candidate = document["candidate"]
        candidate["expected_version"] = "0.7.0rc1"
        candidate["observed_version"] = "0.7.0rc1"
        candidate["changelog_identity"] = "[0.7.0rc1] - 2026-08-16"
        candidate["observed_changelog_identity"] = "[0.7.0rc1] - 2026-08-16"
        document["build"]["archives"]["source"]["filename"] = (
            "djsupport-0.7.0rc1.tar.gz"
        )
        document["build"]["archives"]["wheel"]["filename"] = (
            "djsupport-0.7.0rc1-py3-none-any.whl"
        )

        with pytest.raises(
            CandidateQualificationError,
            match="candidate_qualification_failed:installed_scenarios_required",
        ):
            qualify_candidate(document)


class TestCandidateArchiveAndCliAdapters:
    def test_archive_inspection_rejects_private_members_without_echoing_the_path(
        self,
        tmp_path: Path,
    ) -> None:
        wheel = tmp_path / "djsupport-0.0.0.dev181-py3-none-any.whl"
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr("djsupport/operational-store.sqlite3", b"private")

        with pytest.raises(
            CandidateQualificationError,
            match="candidate_qualification_failed:private_archive_member",
        ) as exc_info:
            inspect_distribution(wheel, "wheel")

        assert str(tmp_path) not in str(exc_info.value)

    def test_cli_emits_only_the_schema_validated_evidence_document(
        self,
        tmp_path: Path,
    ) -> None:
        input_path = tmp_path / "qualification.json"
        input_path.write_text(
            json.dumps(synthetic_qualification_input()),
            encoding="utf-8",
        )

        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "candidate_qualification.py"),
                "qualify",
                "--input",
                str(input_path),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr
        evidence = json.loads(result.stdout)
        Draft202012Validator(_load_json(EVIDENCE_SCHEMA)).validate(evidence)
        assert str(tmp_path) not in result.stdout
        assert result.stderr == ""

    def test_public_run_adapter_returns_only_bounded_job_observations(self) -> None:
        raw = {
            "jobs": [
                {
                    "name": "Plan",
                    "head_sha": "1" * 40,
                    "workflow_name": "Candidate qualification",
                    "status": "completed",
                    "conclusion": "success",
                    "runner_name": "/private/runner-name",
                    "steps": [
                        {
                            "name": "Build, inspect, and bind the exact source",
                            "status": "completed",
                            "conclusion": "success",
                            "number": 7,
                        }
                    ],
                }
            ]
        }

        expected_context = object()

        def opener(request, *, timeout, context):
            assert request.full_url == (
                "https://api.github.com/repos/spontain112/djsupport/actions/"
                "runs/181/jobs?filter=latest&per_page=100"
            )
            assert timeout == 30
            assert context is expected_context
            return BytesIO(json.dumps(raw).encode())

        observed = fetch_public_run_jobs(
            repository="spontain112/djsupport",
            run_id="181",
            opener=opener,
            ssl_context=expected_context,
        )

        assert observed == {
            "repository": "spontain112/djsupport",
            "run_id": "181",
            "total_count": 1,
            "jobs": [
                {
                    "name": "Plan",
                    "head_sha": "1" * 40,
                    "workflow_name": "Candidate qualification",
                    "status": "completed",
                    "conclusion": "success",
                    "steps": [
                        {
                            "name": "Build, inspect, and bind the exact source",
                            "status": "completed",
                            "conclusion": "success",
                        }
                    ],
                }
            ],
        }
        assert "/private/" not in json.dumps(observed)


class TestCandidateInputRejection:
    @pytest.mark.parametrize(
        ("mutation", "reason"),
        [
            (
                lambda document: document["candidate"].__setitem__(
                    "observed_documentation_commit", "4" * 40
                ),
                "documentation_commit_mismatch",
            ),
            (
                lambda document: document["candidate"].__setitem__(
                    "observed_version", "0.0.0.dev182"
                ),
                "package_version_mismatch",
            ),
            (
                lambda document: document["candidate"].__setitem__(
                    "observed_changelog_identity", "[Synthetic mismatch]"
                ),
                "changelog_identity_mismatch",
            ),
            (
                lambda document: document["build"]["wheel_rebuilds"][0].__setitem__(
                    "wheel_sha256", "c" * 64
                ),
                "wheel_digest_mismatch",
            ),
            (
                lambda document: document["build"]["tools"].__setitem__(
                    "build", "1.4.0"
                ),
                "build_tool_mismatch",
            ),
            (
                lambda document: document["runtime"]["cells"].pop(),
                "runtime_cell_missing",
            ),
            (
                lambda document: document["documentation"].__setitem__(
                    "documentation_commit", "5" * 40
                ),
                "documentation_evidence_mismatch",
            ),
        ],
    )
    def test_identity_and_completeness_mismatches_fail_closed(
        self,
        mutation,
        reason: str,
    ) -> None:
        document = deepcopy(synthetic_qualification_input())
        mutation(document)

        with pytest.raises(
            CandidateQualificationError,
            match=f"candidate_qualification_failed:{reason}",
        ):
            qualify_candidate(document)

    @pytest.mark.parametrize(
        "mutation",
        [
            lambda document: document["runtime"]["cells"][0].__setitem__(
                "source_build", True
            ),
            lambda document: document["installed_scenarios"]["observations"][
                0
            ].__setitem__("live_provider_capability", True),
            lambda document: document["workflow"].__setitem__(
                "artifact_upload", True
            ),
            lambda document: document["checks"]["conclusions"].pop(
                "repository_privacy"
            ),
            lambda document: document.__setitem__(
                "raw_log", "/private/example/qualification.log"
            ),
        ],
    )
    def test_malformed_private_or_capability_broadening_input_fails_closed(
        self,
        mutation,
    ) -> None:
        document = deepcopy(synthetic_qualification_input())
        mutation(document)

        with pytest.raises(
            CandidateQualificationError,
            match="^candidate_qualification_failed:",
        ) as exc_info:
            qualify_candidate(document)

        assert "/private/" not in str(exc_info.value)


class TestCandidateWorkflowAssembly:
    def test_candidate_matrix_is_derived_from_every_qualified_runtime_cell(
        self,
    ) -> None:
        matrix = candidate_matrix()

        assert len(matrix) == 25
        assert len(
            {
                (
                    cell["runner"],
                    cell["python-version"],
                    cell["architecture"],
                )
                for cell in matrix
            }
        ) == 25
        assert {cell["setup-architecture"] for cell in matrix} == {"x64", "arm64"}
        assert {
            (cell["runner"], cell["python-version"], cell["architecture"])
            for cell in matrix
            if cell["runner"] == "windows-2025"
        } == {
            ("windows-2025", "3.10.11", "AMD64"),
            ("windows-2025", "3.11.9", "AMD64"),
            ("windows-2025", "3.12.10", "AMD64"),
            ("windows-2025", "3.13.15", "AMD64"),
            ("windows-2025", "3.14.7", "AMD64"),
        }

    def test_finalizer_concentrates_job_facts_into_one_evidence_document(self) -> None:
        complete = synthetic_qualification_input()
        preparation = {
            "candidate": {
                key: complete["candidate"][key]
                for key in (
                    "product_commit",
                    "observed_product_commit",
                    "expected_version",
                    "observed_version",
                    "changelog_identity",
                    "observed_changelog_identity",
                    "source_date_epoch",
                )
            },
            "archives": complete["build"]["archives"],
        }

        evidence = finalize_qualification(
            preparation=preparation,
            qualification_kind="synthetic_non_release",
            documentation_commit="2" * 40,
            run=complete["run"],
            run_jobs=synthetic_workflow_run_observation(),
            actions=complete["workflow"]["actions"],
        )

        assert evidence == qualify_candidate(complete)

    @pytest.mark.parametrize(
        "mutation",
        [
            lambda observation: observation["jobs"].pop(),
            lambda observation: observation.__setitem__(
                "run_id", "synthetic-elsewhere"
            ),
            lambda observation: observation["jobs"][0].__setitem__(
                "head_sha", "9" * 40
            ),
            lambda observation: observation["jobs"][0].__setitem__(
                "workflow_name", "Different workflow"
            ),
            lambda observation: observation["jobs"][1]["steps"][4].__setitem__(
                "conclusion", "failure"
            ),
            lambda observation: observation["jobs"].append(
                deepcopy(observation["jobs"][0])
            ),
        ],
    )
    def test_finalizer_rejects_missing_failed_or_duplicate_job_observations(
        self,
        mutation,
    ) -> None:
        complete = synthetic_qualification_input()
        observation = synthetic_workflow_run_observation()
        mutation(observation)
        preparation = {
            "candidate": {
                key: complete["candidate"][key]
                for key in (
                    "product_commit",
                    "observed_product_commit",
                    "expected_version",
                    "observed_version",
                    "changelog_identity",
                    "observed_changelog_identity",
                    "source_date_epoch",
                )
            },
            "archives": complete["build"]["archives"],
        }

        with pytest.raises(
            CandidateQualificationError,
            match="candidate_qualification_failed:workflow_observation",
        ):
            finalize_qualification(
                preparation=preparation,
                qualification_kind="synthetic_non_release",
                documentation_commit="2" * 40,
                run=complete["run"],
                run_jobs=observation,
                actions=complete["workflow"]["actions"],
            )

    def test_candidate_workflow_is_read_only_exact_and_publication_free(self) -> None:
        workflow_text = CANDIDATE_WORKFLOW.read_text(encoding="utf-8")
        workflow = yaml.safe_load(workflow_text)

        assert workflow["permissions"] == {"contents": "read"}
        assert set(workflow["on"]) == {"pull_request", "workflow_dispatch"}
        dispatch_inputs = workflow["on"]["workflow_dispatch"]["inputs"]
        assert set(dispatch_inputs) == {
            "expected_product_commit",
            "documentation_commit",
            "expected_version",
            "changelog_identity",
        }
        assert all(
            input_contract["required"] is True
            for input_contract in dispatch_inputs.values()
        )

        jobs = workflow["jobs"]
        assert set(jobs) == {"contract", "plan", "qualify", "documentation", "finalize"}
        assert all("permissions" not in job for job in jobs.values())
        assert jobs["plan"]["if"] == "github.event_name == 'workflow_dispatch'"
        assert jobs["qualify"]["strategy"]["fail-fast"] is False
        assert jobs["qualify"]["name"] == (
            "Qualify ${{ matrix.runner }} / Python "
            "${{ matrix.python-version }} / ${{ matrix.architecture }}"
        )
        assert jobs["qualify"]["strategy"]["matrix"] == (
            "${{ fromJSON(needs.plan.outputs.matrix) }}"
        )
        assert set(jobs["finalize"]["needs"]) == {
            "contract",
            "plan",
            "qualify",
            "documentation",
        }

        steps = [step for job in jobs.values() for step in job.get("steps", [])]
        uses = [step["uses"] for step in steps if "uses" in step]
        assert uses
        assert all(
            re.fullmatch(
                r"actions/(?:checkout|setup-python|setup-node)@[0-9a-f]{40}",
                action,
            )
            for action in uses
        )
        checkouts = [
            step
            for step in steps
            if step.get("uses", "").startswith("actions/checkout@")
        ]
        assert checkouts
        assert all(step["with"]["persist-credentials"] is False for step in checkouts)
        setup_node = next(
            step
            for step in steps
            if step.get("uses", "").startswith("actions/setup-node@")
        )
        assert setup_node["with"]["node-version"] == "22.23.1"

        commands = "\n".join(step.get("run", "") for step in steps)
        for command in (
            "candidate_qualification.py matrix",
            "candidate_qualification.py prepare",
            "candidate_qualification.py rebuild-wheel",
            "sqlite_runtime_delivery.py verify",
            "candidate_qualification.py synthetic-scenarios",
            "check_product_contract.py",
            "mint validate",
            "mint broken-links --check-anchors --check-redirects",
            "mint a11y",
            "candidate_qualification.py observe-run",
            "candidate_qualification.py finalize",
        ):
            assert command in commands
        assert "--run-jobs" in commands
        assert "--qualification-kind synthetic_non_release" in commands
        assert "--scenario-evidence-kind synthetic_contract" in commands
        assert "--qualification-kind release_candidate" not in commands

        normalized = workflow_text.casefold()
        forbidden = (
            "pull_request_target",
            "secrets.",
            "permissions: write",
            "continue-on-error",
            "upload-artifact",
            "git tag",
            "gh release",
            "twine",
            ".release-notes/next-version",
            "spotify",
            "beatport",
        )
        assert not [marker for marker in forbidden if marker in normalized]

        contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
        assert "scripts/candidate_qualification.py" in contributing
        assert "scripts/contracts/" in contributing


class TestCandidateSourceAndBuildAdapters:
    def test_source_observation_requires_the_exact_clean_commit(
        self,
        tmp_path: Path,
    ) -> None:
        repository = tmp_path / "source"
        repository.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
        subprocess.run(
            ["git", "config", "user.name", "Synthetic Test"],
            cwd=repository,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "synthetic@example.invalid"],
            cwd=repository,
            check=True,
        )
        (repository / "pyproject.toml").write_text(
            '[project]\nname = "synthetic"\nversion = "0.0.0.dev181"\n',
            encoding="utf-8",
        )
        (repository / "CHANGELOG.md").write_text(
            "# Changelog\n\n## [Synthetic 0.0.0.dev181]\n",
            encoding="utf-8",
        )
        subprocess.run(
            ["git", "add", "pyproject.toml", "CHANGELOG.md"],
            cwd=repository,
            check=True,
        )
        environment = dict(os.environ)
        environment.update(
            {
                "GIT_AUTHOR_DATE": "2026-08-16T08:00:00Z",
                "GIT_COMMITTER_DATE": "2026-08-16T08:00:00Z",
            }
        )
        subprocess.run(
            ["git", "commit", "-q", "-m", "synthetic"],
            cwd=repository,
            env=environment,
            check=True,
        )
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        epoch = int(
            subprocess.run(
                ["git", "show", "-s", "--format=%ct", "HEAD"],
                cwd=repository,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )

        observed = observe_source(
            expected_commit=commit,
            expected_version="0.0.0.dev181",
            changelog_identity="[Synthetic 0.0.0.dev181]",
            source_date_epoch=epoch,
            repository_root=repository,
        )
        assert observed["product_commit"] == commit

        with pytest.raises(
            CandidateQualificationError,
            match="candidate_qualification_failed:changelog_identity_mismatch",
        ):
            observe_source(
                expected_commit=commit,
                expected_version="0.0.0.dev181",
                changelog_identity="Synthetic",
                source_date_epoch=epoch,
                repository_root=repository,
            )

        (repository / "untracked-private.txt").write_text(
            "must not enter an exact build",
            encoding="utf-8",
        )
        with pytest.raises(
            CandidateQualificationError,
            match="candidate_qualification_failed:source_checkout_dirty",
        ):
            observe_source(
                expected_commit=commit,
                expected_version="0.0.0.dev181",
                changelog_identity="[Synthetic 0.0.0.dev181]",
                source_date_epoch=epoch,
                repository_root=repository,
            )

    def test_build_adapter_rejects_an_unpinned_installed_tool(self) -> None:
        with pytest.raises(
            CandidateQualificationError,
            match="candidate_qualification_failed:build_tool_mismatch",
        ):
            verify_build_tools(
                {
                    "build": "1.3.0",
                    "setuptools": "81.0.0",
                    "wheel": "0.45.1",
                }
            )
