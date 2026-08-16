"""Repository behavior tests for development and release channels."""

import re
from pathlib import Path

import yaml

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10
    import tomli as tomllib


REPOSITORY_ROOT = Path(__file__).parents[1]


def test_direct_tools_are_credited_and_source_archive_includes_acknowledgements():
    with (REPOSITORY_ROOT / "pyproject.toml").open("rb") as pyproject_file:
        metadata = tomllib.load(pyproject_file)
    project = metadata["project"]

    credits = (REPOSITORY_ROOT / "THIRD_PARTY.md").read_text()
    declared = [
        *project["dependencies"],
        *project["optional-dependencies"]["web"],
        *project["optional-dependencies"]["dev"],
        *metadata["build-system"]["requires"],
    ]
    package_names = {
        re.split(r"[<>=!~;\[]", requirement, maxsplit=1)[0].strip().lower()
        for requirement in declared
    }

    assert not [name for name in package_names if name not in credits.lower()]
    assert "Chromaprint" in credits and "beatport-pp-cli" in credits
    assert "[CodeQL](https://github.com/github/codeql-action)" in credits
    assert "issue #133" in credits and "Unverified" in credits
    assert "include THIRD_PARTY.md" in (REPOSITORY_ROOT / "MANIFEST.in").read_text()
    assert (REPOSITORY_ROOT / "THIRD_PARTY.md").is_file()


def test_security_policy_uses_private_reporting_and_is_in_source_archive():
    policy = (REPOSITORY_ROOT / "SECURITY.md").read_text()
    normalized_policy = " ".join(policy.split())
    manifest = (REPOSITORY_ROOT / "MANIFEST.in").read_text()

    assert "security/advisories/new" in policy
    assert "Do not describe the vulnerability" in normalized_policy
    assert "synthetic data" in normalized_policy
    assert "no response deadline" in normalized_policy
    assert "include SECURITY.md" in manifest


def test_source_checkout_uses_the_next_development_version():
    with (REPOSITORY_ROOT / "pyproject.toml").open("rb") as pyproject_file:
        project = tomllib.load(pyproject_file)["project"]

    assert project["version"] == "0.7.0.dev0"


def test_documented_latest_stable_release_differs_from_source_version():
    readme = (REPOSITORY_ROOT / "README.md").read_text()
    with (REPOSITORY_ROOT / "pyproject.toml").open("rb") as pyproject_file:
        source_version = tomllib.load(pyproject_file)["project"]["version"]

    assert "v0.6.0" in readme and source_version != "0.6.0"


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


def test_codeql_scans_python_and_workflows_with_least_privilege():
    workflow_path = REPOSITORY_ROOT / ".github" / "workflows" / "codeql.yml"
    workflow_text = workflow_path.read_text()
    workflow = yaml.safe_load(workflow_text)
    errors = []

    triggers = workflow.get("on", {})
    if set(triggers) != {"push", "pull_request", "schedule"}:
        errors.append("CodeQL must run only for main changes and its schedule")
    if triggers.get("push", {}).get("branches") != ["main"]:
        errors.append("CodeQL push scans must be limited to main")
    if triggers.get("pull_request", {}).get("branches") != ["main"]:
        errors.append("CodeQL pull-request scans must target main")
    if triggers.get("schedule") != [{"cron": "17 3 * * 1"}]:
        errors.append("CodeQL must define the reviewed weekly UTC schedule")

    if workflow.get("permissions") != {"contents": "read"}:
        errors.append("CodeQL workflow permissions must default to contents: read")
    concurrency = workflow.get("concurrency", {})
    if concurrency.get("cancel-in-progress") is not True:
        errors.append("superseded CodeQL runs must be cancelled")
    if "github.ref" not in concurrency.get("group", ""):
        errors.append("CodeQL concurrency must be scoped to the ref")

    jobs = workflow.get("jobs", {})
    if set(jobs) != {"analyze"}:
        errors.append("CodeQL must expose one analysis job")
    analyze = jobs.get("analyze", {})
    if analyze.get("permissions") != {
        "actions": "read",
        "contents": "read",
        "packages": "read",
        "security-events": "write",
    }:
        errors.append("CodeQL analysis permissions must be the reviewed minimum")
    if analyze.get("timeout-minutes") != 30:
        errors.append("CodeQL analysis must have a bounded timeout")

    expected_matrix = [
        {"language": "python", "build-mode": "none"},
        {"language": "actions", "build-mode": "none"},
    ]
    strategy = analyze.get("strategy", {})
    if strategy.get("fail-fast") is not False:
        errors.append("one failed language must not hide the other analysis")
    if strategy.get("matrix", {}).get("include") != expected_matrix:
        errors.append("CodeQL must explicitly analyze Python and Actions")

    steps = analyze.get("steps", [])
    uses = [step.get("uses", "") for step in steps]
    action_roles = [action.rsplit("@", maxsplit=1)[0] for action in uses]
    expected_action_roles = [
        "actions/checkout",
        "github/codeql-action/init",
        "github/codeql-action/analyze",
    ]
    action_pin = re.compile(
        r"^(?:actions/checkout|github/codeql-action/(?:init|analyze))@[0-9a-f]{40}$"
    )
    if action_roles != expected_action_roles:
        errors.append("CodeQL must check out, initialize, and analyze in that order")
    if any(action_pin.fullmatch(action) is None for action in uses):
        errors.append("CodeQL actions must be canonical and pinned to full SHAs")
    codeql_pins = {
        action.rsplit("@", maxsplit=1)[1]
        for action in uses
        if action.startswith("github/codeql-action/")
    }
    if len(codeql_pins) != 1:
        errors.append("CodeQL initialization and analysis must use one reviewed pin")
    checkout = next(
        (step for step in steps if step.get("uses", "").startswith("actions/checkout@")),
        {},
    )
    if checkout.get("with", {}).get("persist-credentials") is not False:
        errors.append("CodeQL checkout credentials must not persist")
    initialize = next(
        (
            step
            for step in steps
            if step.get("uses", "").startswith("github/codeql-action/init@")
        ),
        {},
    )
    if initialize.get("with") != {
        "languages": "${{ matrix.language }}",
        "build-mode": "${{ matrix.build-mode }}",
    }:
        errors.append("CodeQL must initialize only the explicit matrix language")

    forbidden = (
        "pull_request_target",
        "workflow_dispatch",
        "continue-on-error",
        "permissions: write",
        "spotify",
        "beatport",
        "git tag",
        "gh release",
        "twine",
        "pypi",
        "upload-sarif",
    )
    normalized = workflow_text.casefold()
    for marker in forbidden:
        if marker in normalized:
            errors.append(f"forbidden CodeQL capability: {marker}")
    if re.search(r"\bsecrets\s*(?:\.|\[)", normalized):
        errors.append("forbidden CodeQL capability: repository secrets")
    if any("run" in step for step in steps):
        errors.append("CodeQL setup must not execute arbitrary repository commands")

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
