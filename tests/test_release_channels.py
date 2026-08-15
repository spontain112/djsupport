"""Repository behavior tests for development and release channels."""

import re
from pathlib import Path

import yaml

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10
    import tomli as tomllib


REPOSITORY_ROOT = Path(__file__).parents[1]


def test_source_checkout_uses_a_supported_release_version():
    with (REPOSITORY_ROOT / "pyproject.toml").open("rb") as pyproject_file:
        project = tomllib.load(pyproject_file)["project"]

    assert re.fullmatch(r"\d+\.\d+\.\d+(?:(?:\.dev|rc)\d+)?", project["version"])


def test_documented_latest_stable_release_differs_from_source_version():
    readme = (REPOSITORY_ROOT / "README.md").read_text()
    with (REPOSITORY_ROOT / "pyproject.toml").open("rb") as pyproject_file:
        source_version = tomllib.load(pyproject_file)["project"]["version"]

    assert "v0.5.0" in readme and source_version != "0.5.0"


def test_manual_release_checklist_separates_validation_from_publication():
    checklist = (REPOSITORY_ROOT / "docs" / "releasing.md").read_text()
    normalized_checklist = " ".join(checklist.split())
    required_policy = (
        "exact commit",
        "release-preparation PR",
        ".release-notes/*.md",
        "release/version",
        "migration and backup",
        "green CI",
        "annotated `vX.Y.ZrcN` tag",
        "GitHub pre-release",
        "disposable environment",
        "final GitHub Release as Latest",
        "authorization to create and push the annotated final tag",
        (
            "Separately obtain authorization to publish the final GitHub Release "
            "as Latest"
        ),
        "green CI on the exact final commit",
        "version PR does not authorize tagging or publication",
        "separate gated operations",
    )

    assert not [
        phrase for phrase in required_policy if phrase not in normalized_checklist
    ]


def test_ci_is_a_least_privilege_offline_release_gate():
    workflow_path = REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml"
    workflow_text = workflow_path.read_text()
    workflow = yaml.safe_load(workflow_text)
    errors = []

    triggers = workflow.get("on", {})
    if set(triggers) != {"push", "pull_request", "workflow_dispatch"}:
        errors.append(
            "CI must run only for pushes, pull requests, and explicit dispatches"
        )
    if triggers.get("push", {}).get("branches") != ["main"]:
        errors.append("push CI must be limited to main")
    if workflow.get("permissions") != {"contents": "read"}:
        errors.append("workflow permissions must be contents: read only")

    concurrency = workflow.get("concurrency", {})
    if concurrency.get("cancel-in-progress") is not True:
        errors.append("superseded runs must be cancelled")
    if "github.ref" not in concurrency.get("group", ""):
        errors.append("concurrency must be scoped to the ref")

    jobs = workflow.get("jobs", {})
    if any("permissions" in job for job in jobs.values()):
        errors.append("jobs must not override the read-only workflow permissions")
    test_job = jobs.get("test", {})
    versions = test_job.get("strategy", {}).get("matrix", {}).get("python-version")
    if versions != ["3.10", "3.14"]:
        errors.append("the complete suite must run on Python 3.10 and 3.14")

    test_commands = "\n".join(
        step.get("run", "") for step in test_job.get("steps", [])
    )
    for command in (
        'python -m pip install ".[dev,web]"',
        "python -m pytest",
        "python -m compileall -q djsupport tests",
    ):
        if command not in test_commands:
            errors.append(f"test matrix is missing: {command}")

    package_commands = "\n".join(
        step.get("run", "") for step in jobs.get("package", {}).get("steps", [])
    )
    for command in (
        "python -m build",
        "python -m tarfile -l",
        "python -m zipfile -l",
        "python -m venv",
        "import djsupport",
        "djsupport --help",
    ):
        if command not in package_commands:
            errors.append(f"package validation is missing: {command}")
    if workflow_text.count("python -m build") != 1:
        errors.append("source and wheel distributions must be built exactly once")
    if "0.6.0.dev0" in workflow_text:
        errors.append("CI must read version truth from pyproject.toml")
    if "pyproject.toml" not in package_commands:
        errors.append("package validation must read the canonical project version")

    steps = [step for job in jobs.values() for step in job.get("steps", [])]
    uses = [step["uses"] for step in steps if "uses" in step]
    action_pin = re.compile(r"^actions/(checkout|setup-python)@[0-9a-f]{40}$")
    if not uses or any(action_pin.fullmatch(action) is None for action in uses):
        errors.append("only checkout/setup-python pinned to full SHAs may be used")
    for step in steps:
        if step.get("uses", "").startswith("actions/checkout@"):
            if step.get("with", {}).get("persist-credentials") is not False:
                errors.append("checkout credentials must not persist")

    forbidden = (
        "secrets.",
        "permissions: write",
        "continue-on-error",
        "spotify",
        "beatport",
        "git tag",
        "gh release",
        "twine",
        "pypi",
        "upload-artifact",
    )
    lowered_workflow = workflow_text.lower()
    for marker in forbidden:
        if marker in lowered_workflow:
            errors.append(f"forbidden workflow capability: {marker}")

    assert not errors, "\n".join(errors)


def test_version_pr_automation_cannot_publish_a_release():
    version_workflow = (
        REPOSITORY_ROOT / ".github" / "workflows" / "version-pr.yml"
    ).read_text()
    ci_workflow = (
        REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml"
    ).read_text()
    normalized = version_workflow.casefold()

    assert "scripts/release_records.py prepare" in version_workflow
    assert "release/version" in version_workflow
    assert "pull-requests: write" in version_workflow
    assert "actions: write" in version_workflow
    assert "gh workflow run ci.yml --ref release/version" in version_workflow
    assert "workflow_dispatch:" in ci_workflow
    assert "github.event_name == 'workflow_dispatch'" in ci_workflow
    assert "RELEASE_RECORD_BASE" in ci_workflow
    for forbidden in ("git tag", "gh release create", "twine", "pypi", "spotify", "beatport"):
        assert forbidden not in normalized


def test_version_pr_automation_ignores_prior_merged_pull_requests():
    version_workflow = (
        REPOSITORY_ROOT / ".github" / "workflows" / "version-pr.yml"
    ).read_text()

    assert "gh pr list" in version_workflow
    assert "--base main" in version_workflow
    assert "--head release/version" in version_workflow
    assert "--state open" in version_workflow
    assert 'gh pr edit "$open_pr"' in version_workflow
    assert "gh pr view release/version" not in version_workflow
