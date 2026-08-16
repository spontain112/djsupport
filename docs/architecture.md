# Architecture

DJ Support is a local Python application whose deep module is
[`Transfer`](../djsupport/transfer.py). CLI, local web, and Agent Clients all
cross its public interface. Transfer owns matching, Preview, persistence
ordering, publication, Qualification, Approval, recovery, and Mirror policy;
the clients render facts and collect explicit decisions.

This document is the canonical conceptual module and adapter map. The
[domain model](domain-model.md) explains product entities, the
[lifecycles](lifecycles.md) explain state and authority transitions, and
[private storage](storage.md) explains serialized local data. The
[glossary](../CONTEXT.md) remains the source for canonical terms.

## Authority overview

This mobile-friendly portrait summarizes the authority path. It is a reading
aid derived from the canonical model documented on this page; the Mermaid
diagrams below remain the editable architecture views.

![DJ Support authority architecture: sources and clients enter Transfer, effects remain reviewable, and only human review creates playlist-scoped Approval](assets/djsupport-architecture-mobile.svg)

## System context

```mermaid
flowchart TB
    subgraph Sources["Selected sources"]
        RB["Rekordbox XML<br/>and optional selected audio"]
        BP["Beatport chart or label"]
    end

    subgraph Clients["Thin clients"]
        CLI["Click CLI"]
        WEB["Local FastAPI web interface"]
        AGENT["Harness-neutral Agent Client"]
    end

    T["Public Transfer interface<br/><b>policy authority</b>"]

    subgraph Private["Private local application data"]
        MK["Matching knowledge"]
        TS["Transfer checkpoints<br/>and Qualification Drafts"]
        PS["Publication manifests<br/>Approvals and Mirrors"]
    end

    SP["Spotify adapter"]
    PLAYLIST["Spotify playlists"]

    RB --> T
    BP --> T
    CLI --> T
    WEB --> T
    AGENT --> T
    T --> MK
    T --> TS
    T --> PS
    T --> SP
    SP --> PLAYLIST
```

The diagram shows information and control relationships, not automatic
authority. It intentionally omits lifecycle states and method-level calls. A
line to Spotify does not imply permission to write: Preview and capability
inspection make no playlist or playlist-state mutation, and an Agent Client
cannot turn conversation into authorization.

## Module architecture

```mermaid
flowchart TB
    subgraph ClientAdapters["Client adapters"]
        CLI["cli.py"]
        WEB["web.py + static web"]
        AGENT["agent.py"]
    end

    RUNTIME["Private Runtime Assembly<br/>production construction"]
    INTERFACE["Transfer public interface"]

    subgraph TransferModule["transfer.py implementation"]
        PLAN["Source selection<br/>Batch planning and Preview"]
        MATCH["Matching and retained-knowledge policy"]
        PUBLISH["Publication and recovery ordering"]
        QUALIFY["Qualification and Approval"]
        MIRROR["Mirror, Drift and orphan policy"]
    end

    subgraph SourceAdapters["Source adapters"]
        REKORDBOX["RekordboxPlaylistSource"]
        CHART["BeatportChartSource"]
        LABEL["BeatportLabelSource"]
    end

    subgraph EffectAdapters["Effect and persistence adapters"]
        SPOTIFY["SpotifyAdapter"]
        KNOWLEDGE["MatchingKnowledge"]
        TRANSFERSTORE["TransferStorage"]
        PUBLICATIONSTORE["PublicationStorage"]
        IDENTITY["Local Audio Identity"]
        AUDITION["Local Audition"]
    end

    CLI --> INTERFACE
    WEB --> INTERFACE
    AGENT --> INTERFACE
    CLI -. phase facts .-> RUNTIME
    WEB -. phase facts .-> RUNTIME
    AGENT -. phase facts .-> RUNTIME
    RUNTIME -. assembles .-> INTERFACE
    INTERFACE --> PLAN
    INTERFACE --> MATCH
    INTERFACE --> PUBLISH
    INTERFACE --> QUALIFY
    INTERFACE --> MIRROR
    PLAN --> REKORDBOX
    PLAN --> CHART
    PLAN --> LABEL
    MATCH --> SPOTIFY
    MATCH --> KNOWLEDGE
    MATCH --> IDENTITY
    PUBLISH --> SPOTIFY
    PUBLISH --> TRANSFERSTORE
    PUBLISH --> PUBLICATIONSTORE
    QUALIFY --> SPOTIFY
    QUALIFY --> KNOWLEDGE
    QUALIFY --> TRANSFERSTORE
    QUALIFY --> PUBLICATIONSTORE
    QUALIFY --> AUDITION
    MIRROR --> SPOTIFY
    MIRROR --> KNOWLEDGE
    MIRROR --> PUBLICATIONSTORE
```

The boxes inside `transfer.py` are responsibilities hidden behind one public
interface, not new public modules. They illustrate why Transfer is deep: the
same policy pays back across three clients and synthetic high-level tests.
This diagram intentionally omits individual methods, state fields, and report
rendering. Runtime Assembly is a separate private construction seam: CLI, web,
and Agent Client paths provide explicit phase facts, while Transfer remains
their only public policy interface.

### Production source map

| Role | Owning source |
| --- | --- |
| Client adapters | [`cli.py`](../djsupport/cli.py), [`web.py`](../djsupport/web.py), and [`agent.py`](../djsupport/agent.py) |
| Client production assembly | [`runtime.py`](../djsupport/runtime.py) |
| Rekordbox intake | [`rekordbox.py`](../djsupport/rekordbox.py) |
| Beatport intake | [`beatport.py`](../djsupport/beatport.py) and [`label.py`](../djsupport/label.py) |
| Spotify adapter and effects | [`SpotifyMatcher`](../djsupport/transfer.py) |
| Spotify client, search, and rate-limit helpers | [`spotify.py`](../djsupport/spotify.py) |
| Candidate matching and knowledge | [`matcher.py`](../djsupport/matcher.py) and [`cache.py`](../djsupport/cache.py) |
| Local Audio Identity and Local Audition | [`local_audio.py`](../djsupport/local_audio.py) and [`local_audition.py`](../djsupport/local_audition.py) |
| Transfer and file-backed persistence adapters | [`transfer.py`](../djsupport/transfer.py) |
| Private application-data paths, configuration, backup, and migration | [`paths.py`](../djsupport/paths.py), [`config.py`](../djsupport/config.py), [`backup.py`](../djsupport/backup.py), and [`migration.py`](../djsupport/migration.py) |

### Plain-text module map

```text
                              DJ Support
                                  │
               ┌──────────────────┼──────────────────┐
               │                  │                  │
             CLI              Local web       Agent Client
               │                  │                  │
               └──────────────────┼──────────────────┘
                                  ▼
                    ┌─────────────────────────┐
                    │ Transfer public interface│
                    │                         │
                    │ planning + Preview      │
                    │ matching + publication │
                    │ Qualification + Approval│
                    │ recovery + Mirror policy│
                    └─────────────┬───────────┘
                                  │
          ┌───────────────────────┼────────────────────────┐
          ▼                       ▼                        ▼
   Source adapters          Private local state       Spotify adapter
   ┌───────────────┐        ┌───────────────────┐      ┌──────────────┐
   │ Rekordbox XML │        │ matching knowledge│      │ search       │
   │ Beatport chart│        │ checkpoints/drafts│      │ playlists    │
   │ Beatport label│        │ manifests/Mirrors │      │ review facts │
   └───────────────┘        └───────────────────┘      └──────────────┘
                                  ▲
                    ┌─────────────┴─────────────┐
                    │                           │
             Local Audio Identity       Local Audition
             exact reuse evidence       selected playback
```

The ASCII view is deliberately less detailed than the rendered module diagram.
It is the terminal-readable fallback, not a second architecture.

## Interfaces and adapters

| Seam | Interface owner | Production adapter | Why it varies |
| --- | --- | --- | --- |
| Client to policy | `Transfer` methods and structured results | CLI, local web, Agent Client | Humans and harnesses need different renderings of the same policy |
| Source intake | `SourceAdapter` | Rekordbox playlist, Beatport chart, Beatport label | Each source supplies selections differently |
| Spotify effects | `SpotifyAdapter` | Spotipy-backed adapter | Offline tests use stateful synthetic Spotify behavior |
| Matching authority | `MatchingKnowledge` | Versioned local matching knowledge | Tests use ephemeral or authority-recording adapters |
| Durable work | `TransferStorage` | Atomic file storage | Tests resume from in-memory or temporary storage |
| Publication history | `PublicationStorage` | Versioned local publication storage | Review, Approval, and Mirror facts outlive a process |

High-level tests and callers cross these interfaces rather than reaching into
the implementation. See [`CONTRIBUTING.md`](../CONTRIBUTING.md) for the file map
and engineering conventions.

## Accepted production hardening direction

[ADR-0005](adr/0005-use-one-local-transactional-operational-store.md) accepts
one local transactional Operational Store for the 0.7 development line. It
will replace the three current production persistence adapters with one deep
internal interface implemented by SQLite in production and an in-memory
adapter in behavior tests. Transfer remains the sole public policy authority;
the Operational Store concentrates transactions, integrity, recovery, and
derived diagnostics without creating a second policy interface.

[Runtime Assembly](../djsupport/runtime.py) already concentrates production
adapter selection for CLI, web, and Agent Clients. Delivery follows the
[#138–#147 dependency map](research/2026-08-16-operational-store-issue-frontier.md#dependency-order-and-parallel-safe-lanes):
JSON remains the sole production authority before the verified activation
point, and every client resolves the selected SQLite generation afterward.
There is no runtime dual-write, partial-client cutover, or silent JSON
fallback. Retained JSON is inert input to explicit migration or rollback only.

SQLite transactions do not include Spotify. Transfer retains explicit effect
ordering and Spotify Account publishing guards, while the Effect Journal makes
incomplete external work durable and reconcilable. The implementation details
for connection behavior, runtime qualification, migration, backup, restore,
and atomic activation live in the linked
[concurrency](research/2026-08-16-sqlite-concurrency-durability-contract.md)
and
[cutover](research/2026-08-16-sqlite-migration-backup-cutover-contract.md)
contracts rather than in this stable architecture overview.

## Audio capabilities are separate

**Local Audio Identity** calculates an opt-in Chromaprint observation for audio
referenced by an explicitly selected Rekordbox Batch. Exact evidence can reuse
only an Approved Match already associated with the same Spotify account. It
does not identify unknown music, scan directories, upload audio, or grant
Approval.

**Local Audition** opens only the exact selected occurrence through a temporary,
path-redacted local handle so the user can listen during Qualification. It does
not calculate a fingerprint or create retained matching knowledge. Enabling one
capability never enables the other.

## Authority and privacy seams

- Capability inspection reads neither a private source nor Spotify state.
- A bounded plan names the selected source work and anticipated effects.
- Private-source authorization permits only the selected XML/audio reads.
- Spotify-write authorization is separate and scoped to the planned effect.
- Preview can retain permitted local knowledge and checkpoints but cannot
  mutate Spotify playlists or playlist state.
- Qualification decisions remain private, revisable draft state.
- Playlist-scoped Approval is the only transition that creates Approved
  Matches, Corrections, Rejected Matches, or fingerprint associations.
- Credentials and all user-derived operational data remain outside Git and the
  package under [ADR-0001](adr/0001-keep-user-data-out-of-the-repository.md).
- Agent execution follows the versioned contract in
  [ADR-0002](adr/0002-make-transfer-agent-native.md); conversation is never
  authority.

## Intentionally omitted

This architecture does not reproduce every function, dataclass, HTTP route,
CLI flag, JSON field, or historical implementation plan. Those details change
more frequently than the stable module seams. Use the linked source files for
implementation details and the [storage model](storage.md) for versioned local
files.
