"""Contract tests for the canonical documentation architecture."""

from pathlib import Path

from djsupport.backup import BACKUP_VERSION, SUPPORTED_SCHEMAS
from djsupport.cache import CACHE_VERSION
from djsupport.config import CONFIG_VERSION, DEFAULT_CONFIG_PATH
from djsupport.transfer import (
    PUBLICATION_MANIFEST_VERSION,
    TRANSFER_STATE_VERSION,
    default_publication_manifest_path,
)


ROOT = Path(__file__).parents[1]
DOCS = ROOT / "docs"


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_canonical_documentation_surfaces_are_navigable() -> None:
    expected = {
        "docs/index.md": "# DJ Support documentation",
        "docs/architecture.md": "# Architecture",
        "docs/domain-model.md": "# Domain model",
        "docs/lifecycles.md": "# Lifecycles",
        "docs/storage.md": "# Private storage",
    }

    for relative_path, title in expected.items():
        document = _read(relative_path)
        assert document.startswith(title)

    readme = _read("README.md")
    contributing = _read("CONTRIBUTING.md")
    index = _read("docs/index.md")
    assert "[Documentation map](docs/index.md)" in readme
    assert "[architecture documentation](docs/architecture.md)" in readme
    assert "[Architecture](docs/architecture.md)" in contributing
    for filename in expected:
        if filename == "docs/index.md":
            continue
        assert f"({Path(filename).name})" in index


def test_documentation_has_rendered_and_plain_text_architecture_views() -> None:
    readme = _read("README.md")
    architecture = _read("docs/architecture.md")
    domain_model = _read("docs/domain-model.md")
    lifecycles = _read("docs/lifecycles.md")

    assert "```mermaid\nflowchart" in readme
    assert "```mermaid\nflowchart" in architecture
    assert "```text" in architecture
    assert "```mermaid\nerDiagram" in domain_model
    assert "## Relationship summary" in domain_model
    assert lifecycles.count("```mermaid") >= 4
    assert "## Transition tables" in lifecycles


def test_storage_document_follows_executable_schema_versions() -> None:
    storage = _read("docs/storage.md")
    transfer_state_name = default_publication_manifest_path().with_suffix(
        ".transfers.json"
    ).name

    expected_lines = {
        f"| Configuration | `{DEFAULT_CONFIG_PATH}` | `{CONFIG_VERSION}` |",
        f"| Matching knowledge | `matching-knowledge.json` | `{CACHE_VERSION}` |",
        (
            "| Publication state | `publication-manifests.json` | "
            f"`{PUBLICATION_MANIFEST_VERSION}` |"
        ),
        f"| Transfer state | `{transfer_state_name}` | `{TRANSFER_STATE_VERSION}` |",
        f"| Backup manifest | `backup-manifest.json` | `{BACKUP_VERSION}` |",
    }
    for line in expected_lines:
        assert line in storage

    for filename, versions in SUPPORTED_SCHEMAS.items():
        rendered_versions = ", ".join(f"`{version}`" for version in versions)
        assert f"| `{filename}` | {rendered_versions} |" in storage


def test_docs_keep_domain_concepts_separate_from_serialized_schemas() -> None:
    domain_model = _read("docs/domain-model.md")
    storage = _read("docs/storage.md")

    assert "[canonical glossary](../CONTEXT.md)" in domain_model
    assert "does not describe JSON fields" in domain_model
    assert "conceptual domain model" in storage
    assert "serialized storage model" in storage
    assert "Never copy private application data" in storage


def test_lifecycle_document_covers_cancellation_and_bounded_retry() -> None:
    lifecycles = _read("docs/lifecycles.md")

    assert "User cancellation is persisted as `Paused`" in lifecycles
    assert "## Retry policy" in lifecycles
    assert "previously unsuccessful match" in lifecycles
    assert "transient Spotify operation" in lifecycles
