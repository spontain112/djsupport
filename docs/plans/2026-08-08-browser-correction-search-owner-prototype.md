# Browser Correction Search owner prototype

**Date:** 2026-08-08

**Status:** ready for an owner-operated prototype; no production commitment

**Decision:** Determine whether a bounded, agent-operated Correction Search
finds usable Spotify links faster and with less open-ended browser work than the
owner's current manual recovery workflow.

## Product boundary

Correction Search is retrieval assistance, not matching authority. It operates
under [ADR-0003](../adr/0003-keep-correction-search-subordinate-to-approval.md)
and uses the terms defined in [`CONTEXT.md`](../../CONTEXT.md).

- It starts only for explicitly selected Unresolved Source Tracks or explicitly
  challenged proposals.
- One user-confirmed Correction Search Plan binds the selected tracks, external
  provider, disclosed metadata, and query/candidate limits.
- The agent returns Correction Candidates and never labels one correct.
- Merely challenging a proposal or searching does not change playlist or match
  state.
- Only the user's chosen link may enter the existing Correction and
  playlist-scoped Approval workflow.
- Failure within the plan does not prove that a track is absent from Spotify.

## Why test without new code

The owner already recovers difficult tracks by trying Spotify search and then
ordinary web search. A harness can enact that workflow directly. Building a
service, persistence model, CLI command, or GUI before measuring the bounded
workflow would answer implementation questions before establishing that the
extended search has useful payoff.

This prototype can establish owner usefulness only. The only known secondary
user cloned an older version, so the result cannot establish broader demand.

## Human-gated input

The prototype must not read private data until the owner supplies and confirms:

1. one exact private Markdown report or Correction CSV path;
2. exactly ten source row identifiers from that file;
3. the proposed external search provider;
4. the metadata fields that will be included in external queries; and
5. the fixed query and candidate limits below.

The agent reads only the selected rows. It must not inspect the rest of the
playlist, report, library, matching knowledge, or application-data directory.
The selected metadata remains private working data and never enters Git.

## Confirmed limits

- At most three external web queries per selected track.
- Search results must be restricted to Spotify track pages under
  `open.spotify.com/track`.
- At most three distinct Correction Candidates per selected track.
- General web search is the capability; record the provider actually used
  without making that provider part of product architecture.
- Do not open or summarize full pages when the search result contains enough
  metadata to construct the candidate card.
- The agent stops at the bound. Continuing requires a new explicit plan.

## Search ladder

Record each stage separately:

1. **Baseline:** existing DJ Support/Spotify result and whether the owner
   remembers already trying Spotify application search. Do not require repeated
   manual work.
2. **Exact:** site-restricted search using the original artist, title, and
   meaningful version facts.
3. **Relaxed:** remove or reorder one explained non-version element while
   preserving remix, edit, live, remaster, instrumental, acapella, and other
   meaningful version intent.
4. **Final bounded variant:** one explicitly explained, conservative
   noise-cleaned or reordered query. Never use broad “clean everything” rules.

Issue #32 found that joined-field and broad operational-noise normalization can
add requests or create wrong-confident matches. Correction Search remains safer
because its links are non-authoritative, but the agent must still expose every
query transformation and preserve meaningful version information.

## Candidate card

Return compact, unranked cards in discovery order. Each card contains only:

- canonical Spotify track link;
- artist, title, and version shown by the search result;
- duration when readily available;
- metadata agreements or conflicts;
- the query stage that surfaced it; and
- **Open in Spotify**.

The agent may explain why a result was included but must not call it correct,
best, approved, or a match. The owner listens and decides.

For a future GUI, Spotify's
[Embed/iFrame API](https://developer.spotify.com/documentation/embeds/references/iframe-api)
can provide human-initiated listening without additional OAuth scopes, but
playback or a full track is not guaranteed. Always retain Open in Spotify as
the fallback. Do not use the Premium/OAuth-heavy
[Web Playback SDK](https://developer.spotify.com/documentation/web-playback-sdk/howtos/web-app-player/)
for this workflow.

## User decision and existing workflow

For each source row, the owner chooses one outcome:

1. select a Correction Candidate;
2. decline all returned candidates;
3. accept that no candidate was found inside this plan; or
4. leave it unresolved with a private reason: DJ mix/bootleg,
   promotional/unreleased, unavailable, unknown, or deferred.

When a candidate is selected, the agent returns the chosen Spotify URL and the
exact proposed Correction CSV row but writes nothing. The owner uses the
existing review and playlist-scoped Approval workflow. A selected URL counts as
successful only after current Correction validation and Approval accept it.

The other outcomes are not negative matching truth. They do not infer a
Rejected Match or permanent catalog absence and are retried only when the owner
explicitly requests another search.

## Measurements

Retain a private working register and publish aggregate counts only:

- selected tracks;
- queries attempted by search stage;
- Correction Candidates returned;
- candidates selected and declined;
- no-candidate outcomes;
- private reason-category counts;
- Correction rows accepted by validation;
- Corrections surviving playlist-scoped Approval;
- cases requiring another open-ended manual browser search; and
- the owner's preference between Correction Search and the prior workflow.

Do not retain browser pages, snippets, query transcripts, source metadata,
Spotify URLs/IDs, track or playlist names, reports, or per-track evidence in the
repository. Successful Corrections and a minimal private strategy/outcome
reason may remain in local application data. Repository regression tests use
invented generalizations only unless the owner explicitly exports and consents
to a privacy-reviewed contribution.

## Proceed gate

Proceed to product specification only when all are true:

- useful Correction Candidates are found for at least eight of ten tracks;
- the agent stays within three queries and three candidates per track;
- no candidate is presented as automatically correct;
- at least eight tracks can be decided without another open-ended browser
  search;
- every accepted URL passes current Correction validation and playlist-scoped
  Approval; and
- the owner would choose this workflow over the current browser loop.

Otherwise revise the search ladder once or stop. The first ten tracks may guide
the next owner prototype but must not silently personalize future query order.

## Fresh-session handoff

Start a fresh session in the DJ Support repository with this instruction:

> Run the owner prototype in
> `docs/plans/2026-08-08-browser-correction-search-owner-prototype.md`. Do not
> read private data or search externally until I provide one exact report/CSV
> path, ten row IDs, and confirm the complete Correction Search Plan. Enact the
> protocol through the agent harness without adding product code. Keep all
> source facts and per-track results private, return Correction Candidates for
> my decisions, and finish with aggregate-only findings against the proceed
> gate.
