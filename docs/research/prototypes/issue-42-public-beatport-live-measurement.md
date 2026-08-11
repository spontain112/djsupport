# Issue #42: bounded public Beatport ISRC measurement

Date: 2026-08-11

## Decision question

Does ISRC provide enough real candidate-retrieval coverage on a small public
club-music sample to justify a human-reviewed comparison with DJ Support's
current fuzzy matcher?

This measurement evaluates retrieval evidence and request cost. It does not
measure audio identity, human-confirmed correctness, Approval safety, or
production savings.

## Authorization and bounds

The owner explicitly authorized transmission of 20 ISRC values from a named
public Beatport chart to Spotify's read-only Search API using locally configured
credentials.

- Sample: 20 ordered public chart occurrences.
- Beatport: one extraction request.
- Spotify: one Search request per distinct valid normalized ISRC, capped at 25.
- Authentication: one OAuth token request, counted separately.
- Retries: disabled.
- Forbidden: fuzzy search, playlist access or mutation, Transfer execution,
  Approval, Corrections, cache/state writes, and publication.
- Spotify observations: evaluated in memory and not persisted.

## Aggregate result

| Measure | Count |
| --- | ---: |
| Sample occurrences | 20 |
| Occurrences with format-valid ISRC evidence | 20 |
| Distinct valid ISRC values | 20 |
| Duplicate-code occurrences | 0 |
| Beatport extraction requests | 1 |
| Spotify Search requests / HTTP attempts | 20 / 20 |
| Spotify OAuth HTTP attempts | 1 |
| Automatic retries | 0 |
| Fuzzy searches | 0 |
| Playlist or Transfer calls | 0 |
| Raw Spotify observations persisted | 0 |

Every Search request landed in exactly one aggregate outcome:

| Outcome | Count |
| --- | ---: |
| One metadata-concordant representation | 11 |
| Multiple metadata-equivalent representations | 5 |
| No result within the bounded search | 2 |
| Metadata conflict requiring review or fallback | 1 |
| Version/duration conflict requiring review or fallback | 1 |
| Returned ISRC missing or mismatched | 0 |
| Explicit availability/relink review outcome | 0 |

The duration-evidence marginal was 17 occurrences at 0–2 seconds, one above
30 seconds, and two unknown. Availability evidence was present for 16 and
unknown for four. These are marginal totals: the intentionally non-persistent
measurement did not retain the cross-tab needed to prove that every
metadata-concordant outcome also had complete availability evidence.

## Safe interpretation

- ISRC coverage was 20/20 in this selected chart. That is evidence for this
  chart only, not a Beatport-wide coverage estimate.
- Spotify returned some candidate evidence for 18/20 occurrences (90%).
- Sixteen of 20 occurrences (80%) had metadata-concordant evidence: 11 single
  representations and five equivalent-representation groups.
- Four of 20 occurrences (20%) require fallback or review: two no-results, one
  metadata conflict, and one version/duration conflict.
- All ISRC values were distinct, so query deduplication saved zero Search calls
  in this sample.
- Equivalent metadata does not prove identical audio, human correctness,
  Approval, or which Spotify representation should become durable identity.

No accuracy claim is justified because there was no independent truth set or
human audition. No measured API-saving claim is justified because no fuzzy
baseline was run. A simple one-search-per-track comparison would be 20 fuzzy
searches versus 20 ISRC searches plus at least four fallbacks, a projected
increase of four; the real matcher can issue multiple searches, so this is not
a production cost comparison.

## Governance and containment

Request accounting, mutation boundaries, and Spotify observation retention
passed. Repository state contains aggregate counters only.

Strict transcript containment did not fully pass: the Beatport CLI emitted its
public source payload to the private execution log even though an output file
was supplied. No Spotify response payload, credentials, user playlist data, or
local music-library data was printed or retained. This CLI behavior should be
corrected before a future privacy-sensitive measurement.

## Verdict

**Proceed to one bounded human-reviewed and offline request-count comparison;
do not create the production implementation ticket yet.**

The next comparison should:

1. Replay the same aggregate cases through current matcher request-count logic
   without additional live calls where possible.
2. Human-check at least 10 nominally concordant candidates, including
   equivalent-release groups, with zero wrong recording/version outcomes.
3. Record an aggregate cross-tab for metadata, duration, availability, and
   relink evidence without retaining track-level observations.
4. Demonstrate at least 20% fewer total searches after Approved Match and cache
   reuse, including required fuzzy fallbacks, before an ISRC-first ticket is
   proposed.

The likely safe product order remains: Approved Match → retained knowledge →
ISRC candidate retrieval → metadata/human review → fuzzy fallback. ISRC is
candidate evidence, never Approval and never destructive intent.
