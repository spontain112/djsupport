"""Contract tests for the canonical documentation architecture."""

import re
from pathlib import Path

from djsupport.backup import BACKUP_VERSION, SUPPORTED_SCHEMAS
from djsupport.cache import CACHE_VERSION
from djsupport.config import CONFIG_FILENAME, CONFIG_VERSION
from djsupport.transfer import (
    PUBLICATION_MANIFEST_VERSION,
    TRANSFER_STATE_VERSION,
    default_publication_manifest_path,
)


ROOT = Path(__file__).parents[1]
DOCS = ROOT / "docs"


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _mermaid_blocks(document: str) -> list[tuple[str, str]]:
    matches = list(re.finditer(r"```mermaid\n(.*?)\n```", document, re.DOTALL))
    blocks = []
    for index, match in enumerate(matches):
        next_start = matches[index + 1].start() if index + 1 < len(matches) else None
        blocks.append((match.group(1), document[match.end():next_start]))
    return blocks


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

    portrait = DOCS / "assets" / "djsupport-architecture-mobile.svg"
    assert "(assets/djsupport-architecture-mobile.svg)" in architecture
    assert portrait.read_text(encoding="utf-8").startswith("<svg ")


def test_storage_document_follows_executable_schema_versions() -> None:
    storage = _read("docs/storage.md")
    transfer_state_name = default_publication_manifest_path().with_suffix(
        ".transfers.json"
    ).name

    expected_lines = {
        f"| Configuration | `{CONFIG_FILENAME}` | `{CONFIG_VERSION}` |",
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


def test_batch_docs_separate_reported_partial_success_from_durable_pause() -> None:
    lifecycles = _read("docs/lifecycles.md")
    normalized = " ".join(lifecycles.split())

    assert "reported as `Partial success`" in normalized
    assert "durable Batch remains `Paused`" in normalized
    assert "PartialSuccess --> BatchPaused" in lifecycles
    assert "BatchPaused --> BatchMatching: explicit resume" in lifecycles


def test_domain_model_relates_every_required_concept() -> None:
    domain_model = _read("docs/domain-model.md")

    for entity in (
        "PROVISIONAL_PLAYLIST",
        "SNAPSHOT",
        "PLAYLIST_DRIFT",
        "LOCAL_AUDIO_IDENTITY",
    ):
        assert entity in domain_model
    for relationship_row in (
        "| Provisional Playlist |",
        "| Snapshot |",
        "| Playlist Drift |",
        "| Local Audio Identity |",
    ):
        assert relationship_row in domain_model


def test_every_mermaid_block_is_extracted_and_has_local_omission_context() -> None:
    documents = (
        "README.md",
        "docs/architecture.md",
        "docs/domain-model.md",
        "docs/lifecycles.md",
        "docs/storage.md",
    )
    allowed_headers = ("flowchart ", "stateDiagram-v2", "erDiagram")
    block_count = 0

    for relative_path in documents:
        document = _read(relative_path)
        assert document.count("```mermaid") == len(_mermaid_blocks(document))
        for block, following_text in _mermaid_blocks(document):
            block_count += 1
            assert block.startswith(allowed_headers)
            if block.startswith("flowchart "):
                without_labels = re.sub(r'"[^"]*"', "", block)
                for opening, closing in (("[", "]"), ("{", "}"), ("(", ")")):
                    assert without_labels.count(opening) == without_labels.count(closing)
            elif block.startswith("erDiagram"):
                for relationship in block.splitlines()[1:]:
                    assert re.match(
                        r"\s+[A-Z_]+ [|o}{]+--[|o}{]+ [A-Z_]+ : [a-z_]+$",
                        relationship,
                    )
            else:
                for transition in block.splitlines()[1:]:
                    assert "-->" in transition
            nearby = following_text[:700].casefold()
            assert "omit" in nearby

    assert block_count >= 10


def test_documentation_index_routes_agent_and_release_audiences() -> None:
    index = _read("docs/index.md")

    assert "Agent Clients" in index
    assert "Release maintainers" in index


def test_data_model_terms_live_in_the_canonical_glossary() -> None:
    context = _read("CONTEXT.md")

    for term in (
        "Spotify Account",
        "Source Selection",
        "Source Occurrence",
        "Publication Manifest",
        "Publication Item",
    ):
        assert f"**{term}**:" in context


def test_client_and_abandonment_docs_follow_canonical_behavior() -> None:
    readme = _read("README.md")
    architecture = _read("docs/architecture.md")
    lifecycles = _read("docs/lifecycles.md")

    assert 'A["Agent Client"]' in readme
    assert "AI agent" not in architecture
    assert "RetainingPublication --> Abandoned" in lifecycles
    assert "does not infer playlist deletion or Approval" in " ".join(
        lifecycles.split()
    )


def test_domain_relationships_preserve_mode_and_identity_direction() -> None:
    domain_model = _read("docs/domain-model.md")

    assert "TRANSFER ||--o| SNAPSHOT : may_publish" in domain_model
    assert "APPROVAL ||--o| MIRROR : establishes" in domain_model
    assert "SNAPSHOT ||--|| PROVISIONAL_PLAYLIST" not in domain_model
    assert (
        "LOCAL_AUDIO_IDENTITY }o--|| APPROVED_MATCH : recovers"
        in domain_model
    )


def test_architecture_links_every_named_production_adapter() -> None:
    architecture = _read("docs/architecture.md")

    for source_path in (
        "../djsupport/cli.py",
        "../djsupport/web.py",
        "../djsupport/agent.py",
        "../djsupport/rekordbox.py",
        "../djsupport/beatport.py",
        "../djsupport/label.py",
        "../djsupport/spotify.py",
        "../djsupport/cache.py",
        "../djsupport/local_audio.py",
        "../djsupport/local_audition.py",
    ):
        assert f"]({source_path})" in architecture


def test_glossary_matches_batch_and_account_scoping_in_code() -> None:
    context = _read("CONTEXT.md")
    domain_model = _read("docs/domain-model.md")
    normalized_context = " ".join(context.split())

    assert "one durable Transfer per selected playlist" in normalized_context
    assert "does not scope ordinary metadata-based Approved Matches" in normalized_context
    assert "SPOTIFY_ACCOUNT ||--o{ APPROVED_MATCH : owns" not in domain_model


def test_architecture_distinguishes_spotify_adapter_from_client_helpers() -> None:
    architecture = _read("docs/architecture.md")

    assert (
        "| Spotify adapter and effects | "
        "[`SpotifyMatcher`](../djsupport/transfer.py) |"
    ) in architecture
    assert (
        "| Spotify client, search, and rate-limit helpers | "
        "[`spotify.py`](../djsupport/spotify.py) |"
    ) in architecture
