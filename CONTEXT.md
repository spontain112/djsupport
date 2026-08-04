# DJ Library Synchronization

This context describes how curated music selections are transferred from DJ-oriented sources into Spotify playlists.

## Language

**Transfer**:
A complete attempt to move selections from one source into Spotify, including source intake, track matching, playlist publication, retained matching knowledge, playlist state when applicable, and an outcome report. A Transfer publishes either a Mirror or a Snapshot.
_Avoid_: Sync, import, job, matching run

**Mirror**:
An ongoing relationship in which a managed Spotify playlist is updated on later Transfers to match the successfully matched selections currently present in its source. Rekordbox selections are Mirrors by default.
_Avoid_: Managed sync, live playlist

**Snapshot**:
A one-time Spotify playlist representing the successfully matched selections present in a source at the time of a Transfer. Beatport charts and labels are Snapshots by default.
_Avoid_: Import, unmanaged sync

**Provisional Playlist**:
A Spotify playlist published for review whose source-to-Spotify matches have not yet been approved. Removing a track from this playlist before approval rejects the corresponding proposed match.
_Avoid_: Draft playlist, temporary playlist

**Approved Match**:
A source-to-Spotify match explicitly accepted after review of a Provisional Playlist. An Approved Match is authoritative matching knowledge and is reused across source types by later Transfers when the source-track identity is sufficiently specific.
_Avoid_: Cached match, automatic match

**Rejected Match**:
A proposed source-to-Spotify match removed from its Provisional Playlist before approval. A Rejected Match is never reused as authoritative matching knowledge.
_Avoid_: Missing track, unmatched track

**Correction**:
An explicit source-track-to-Spotify-track mapping supplied by a user as a Spotify URL or URI when a proposed match is wrong or absent. A Correction becomes an Approved Match and a matching regression case.
_Avoid_: Manual match, cache override

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

**Agent Client**:
An AI harness or automation client that uses the same public Transfer policy as CLI and web through capability, bounded plan, explicit authorization, execute or resume, and structured outcome phases. Conversation is never authorization.
_Avoid_: Autonomous authority, agent workflow engine
