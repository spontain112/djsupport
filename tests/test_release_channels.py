"""Repository behavior tests for development and release channels."""

import re
from pathlib import Path

import yaml

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10
    import tomli as tomllib


REPOSITORY_ROOT = Path(__file__).parents[1]


def test_source_checkout_uses_0_6_development_version():
    with (REPOSITORY_ROOT / "pyproject.toml").open("rb") as pyproject_file:
        project = tomllib.load(pyproject_file)["project"]

    assert project["version"] == "0.6.0.dev0"


def test_documented_latest_stable_release_differs_from_development():
    readme = (REPOSITORY_ROOT / "README.md").read_text()
    with (REPOSITORY_ROOT / "pyproject.toml").open("rb") as pyproject_file:
        development_version = tomllib.load(pyproject_file)["project"]["version"]

    assert "v0.5.0" in readme and development_version != "0.5.0"


def test_manual_release_checklist_separates_validation_from_publication():
    checklist = (REPOSITORY_ROOT / "docs" / "releasing.md").read_text()
    normalized_checklist = " ".join(checklist.split())
    required_policy = (
        "exact commit",
        "release-preparation PR",
        "migration and backup",
        "green CI",
        "annotated `vX.Y.ZrcN` tag",
        "GitHub pre-release",
        "disposable environment",
        "final GitHub Release as Latest",
        "next `.dev0` version",
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
    if set(triggers) != {"push", "pull_request"}:
        errors.append("CI must run only for pushes and pull requests")
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
