# DJ Library Synchronization

This context describes how curated music selections are transferred from DJ-oriented sources into Spotify playlists.

## Language

**Spotify Account**:
The stable Spotify profile identity that scopes publication state, Mirrors, Approved Matches, Corrections, and Local Audio Identity reuse. A login or token change does not transfer authority to another Spotify Account.
_Avoid_: Current login, OAuth account

**Transfer**:
A complete attempt to move selections from one source into Spotify, including source intake, track matching, playlist publication, retained matching knowledge, playlist state when applicable, and an outcome report. A Transfer publishes either a Mirror or a Snapshot.
_Avoid_: Sync, import, job, matching run

**Source Selection**:
The explicitly chosen, ordered source content consumed by one Transfer, such as one Rekordbox playlist, Beatport chart, or Beatport label selection. Its reference and content participate in the identity of the bounded work.
_Avoid_: Import source, inferred selection

**Source Occurrence**:
One ordered appearance of a source track within a Source Selection. Repeated appearances remain distinct Source Occurrences even when their metadata or recording identity is equal.
_Avoid_: Deduplicated track, unique recording

**Mirror**:
An ongoing relationship in which a managed Spotify playlist is updated on later Transfers to match the successfully matched selections currently present in its source. Rekordbox selections are Mirrors by default.
_Avoid_: Managed sync, live playlist

**Snapshot**:
A one-time Spotify playlist representing the successfully matched selections present in a source at the time of a Transfer. Beatport charts and labels are Snapshots by default.
_Avoid_: Import, unmanaged sync

**Provisional Playlist**:
A Spotify playlist published for review whose source-to-Spotify matches have not yet been approved. Removing a track from this playlist before approval rejects the corresponding proposed match.
_Avoid_: Draft playlist, temporary playlist

**Publication Manifest**:
The durable, ordered record of the exact source-to-Spotify proposals and source facts needed to review one Provisional Playlist later. It records what was proposed but carries no matching authority.
_Avoid_: Approval record, review CSV, playlist state

**Publication Item**:
One ordered Source Occurrence and its proposed Spotify representation or unresolved outcome inside a Publication Manifest.
_Avoid_: Cache entry, Approved Match

**Approved Match**:
A source-to-Spotify match explicitly accepted after review of a Provisional Playlist. An Approved Match is authoritative matching knowledge and is reused across source types by later Transfers when the source-track identity is sufficiently specific.
_Avoid_: Cached match, automatic match

**Rejected Match**:
A proposed source-to-Spotify match removed from its Provisional Playlist before approval. A Rejected Match is never reused as authoritative matching knowledge.
_Avoid_: Missing track, unmatched track

**Unresolved Source Track**:
A source track for which the current bounded work produced no user-accepted Spotify representation. It may retain a private user-supplied reason but does not prove permanent catalog absence; searching it again requires explicit retry.
_Avoid_: Missing track, not on Spotify

**Correction**:
An explicit source-track-to-Spotify-track mapping supplied by a user as a Spotify URL or URI when a proposed match is wrong or absent. A Correction becomes an Approved Match and a matching regression case.
_Avoid_: Manual match, cache override

**Correction Search**:
An explicitly requested, user-bounded search for candidate Spotify links when a source track is unmatched or its proposal is challenged. It does not change proposal state or create a Correction or Approval; a user-chosen link enters the existing Correction and playlist-scoped Approval workflow.
_Avoid_: Browser matching, automatic correction

**Correction Search Plan**:
A user-confirmed envelope naming the selected source tracks, external search provider, metadata disclosure, query limit, and Correction Candidate limit for one Correction Search. An Agent Client may execute inside that envelope without further prompts but may not broaden it.
_Avoid_: Browser permission, open-ended search

**Correction Candidate**:
A Spotify track reference surfaced by Correction Search for user audition. It carries no matching or playlist authority until the user selects it as a Correction and completes playlist-scoped Approval.
_Avoid_: Browser match, automatic correction

**Correction Search Outcome**:
The terminal record of a Correction Search: a selected Correction Candidate, declined candidates, no candidate within the plan, or an unresolved track with a private user-supplied reason. Only a selected candidate may proceed to Correction, and no outcome proves permanent Spotify catalog absence.
_Avoid_: Browser verdict, automatic rejection

**Approval**:
The playlist-scoped act that compares a Provisional Playlist with its publication manifest, records surviving and corrected mappings as Approved Matches, and records removed proposals as Rejected Matches.
_Avoid_: Transfer approval, cache confirmation

**Batch**:
An explicitly selected, bounded set of source playlists processed by one Transfer. Processing every playlist in a Rekordbox library is an opt-in Batch rather than the default.
_Avoid_: Whole library, run

**Playlist Drift**:
A difference between a Mirror and its retained state that was not caused by a source change, such as a previously Approved Match being manually removed in Spotify. Playlist Drift requires an explicit choice to restore the playlist or revoke the Approved Match.
_Avoid_: Sync conflict, mismatch

**Match Collision**:
A review-required condition in which distinct source tracks resolve to the same Spotify track. A Match Collision is not counted as successful representation until each source track is explicitly corrected or rejected.
_Avoid_: Duplicate match, deduplication

**Approval Conflict**:
A review-required condition in which matching knowledge for an apparently identical source track points to different Spotify tracks. An Approval Conflict requires sharpening the source identity or explicitly replacing an earlier Approved Match.
_Avoid_: Latest correction, cache overwrite

**Abandoned**:
The terminal state of a Provisional Playlist that the user deleted instead of approving. Its publication history is retained, but none of its pending match proposals become authoritative matching knowledge.
_Avoid_: Rejected playlist, expired review

**Orphaned Mirror**:
A Mirror whose linked source playlist can no longer be found. It remains untouched in Spotify until the user explicitly keeps it as an ordinary playlist, relinks it, or deletes it.
_Avoid_: Deleted source, stale playlist

**Preview**:
A complete matching and reporting attempt for a Transfer that may retain matching knowledge but never modifies Spotify playlists or playlist state.
_Avoid_: Dry run, test run

**Local Audio Identity**:
Opt-in, local-only Chromaprint evidence calculated for audio referenced by an explicitly selected Rekordbox Batch. It can recover an existing account-scoped Approved Match by exact equality but can never create Approval or identify an unknown recording from a catalog.
_Avoid_: Automatic identification, fingerprint approval, library scan

**Qualification Workspace**:
The Rekordbox-only, attention-led comparison surface for one selected playlist. It presents retained source and Spotify proposal facts, optionally auditions the exact authorized local source, and collects one explicit Qualification Draft outcome at a time. Browser-origin selections remain reviewed in Spotify.
_Avoid_: Approval screen, generic review UI, match confirmation

**Qualification Draft**:
Private, versioned, resumable working state bound to one Rekordbox playlist Transfer, publication manifest, Spotify account, and playlist head. Its keep, Correction, deferred, exclusion, and rejection choices carry no matching or playlist authority; applying it and approving the resulting playlist remain separate explicit operations.
_Avoid_: Approval, matching knowledge, draft playlist

**Local Audition**:
Opt-in playback of one exact local source occurrence from an explicitly authorized Rekordbox Batch through a short-lived, process-local handle. It does not calculate a fingerprint, require retained matching knowledge, expose a path, or authorize Spotify writes.
_Avoid_: Local audio identity, directory playback, file server

**Agent Client**:
An AI harness or automation client that uses the same public Transfer policy as CLI and web through capability, bounded plan, explicit authorization, execute or resume, and structured outcome phases. Conversation is never authorization.
_Avoid_: Autonomous authority, agent workflow engine
