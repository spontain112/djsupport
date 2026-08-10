# Issue #42 Phase A verdict: ISRC feasibility measurement

## Decision question

Can an aggregate-only measurement correctly represent source ISRC availability,
the required Approved Match → retained cache → ISRC → fuzzy evaluation order,
Spotify safety classifications, and request cost before any private local-file
or live-service measurement is authorized?

## Authorization and bounds

- Authorized and run: Phase A, synthetic data only.
- Not authorized or run: Phase B local Rekordbox/audio measurement.
- Not authorized or run: Phase C live Spotify measurement.
- Inputs: deliberately invented cases in the self-contained logic prototype.
- Effects: no file reads, credentials, live requests, persistence, or playlist
  mutation.

The primary source is
[`issue-42-isrc-feasibility.html`](issue-42-isrc-feasibility.html) on the
throwaway `prototype/42-isrc-feasibility-synthetic` branch. Open it directly in
a browser; no server or installation is required.

## Reference synthetic aggregate

- Bounds: 26 invented source records; request budget 30.
- Exclusions before comparison: 2 contract-rejected, 1 Approved Match hit, and
  1 retained-cache hit. Eligible after reuse: 22.
- ISRC coverage: 12 valid normalized, 8 absent, 1 invalid, and 1 conflicting.
- Beatport V2 cases: 12 present, 1 null-rejected, 1 missing, 1 malformed, and
  1 schema-moved-rejected.
- Local boundary cases: 10 locations, 8 decodable local file URIs, 7
  existing/readable files, 6 supported formats, 1 non-file scheme, 1 non-local
  host, 1 missing file, 1 unsupported format, and 2 corrupt/no-tag outcomes.
- Local tag shapes: 1 MP3/AIFF TSRC, 1 FLAC/Vorbis ISRC, 1 MP4 freeform ISRC,
  and 1 unsupported tag shape.
- Spotify classifications: 1 no hit, 5 one verified hit, 2 multiple equivalent
  release instances, 1 ambiguous version, 1 market-unplayable/relinked result,
  and 1 returned-ISRC mismatch.
- Requests after Approved Match/cache reuse: baseline 22 fuzzy; candidate 11
  ISRC plus 14 fuzzy fallback; net **+3** requests. Eight fuzzy requests were
  skipped after safe ISRC results.
- Baseline outcomes: 13 correct, 1 wrong, 8 review-required (36.4%). Candidate
  outcomes: 16 correct, 1 wrong, 5 review-required (22.7%). These outcomes are
  fixture expectations, not measured product accuracy.
- Privacy output: 0 raw paths, 0 titles/artists, 0 raw tags/ISRCs, and 0 Spotify
  identifiers retained or rendered.

Observed synthetic failures were handled without widening access: V2 null and
schema-moved fields failed contract intake; malformed and conflicting ISRCs
fell back; unsafe URI/file/tag outcomes produced only counters; ambiguous,
unplayable/relinked, mismatched, and absent Spotify results never became safe
automatic matches. The edge-weighted reference sample produced a request
increase, which correctly prevents Phase A from claiming savings.

## What Phase A proved

1. An aggregate-only model can preserve the required evaluation order. Approved
   Match and retained-cache hits generate zero requests in both strategies and
   therefore generate no claimed ISRC saving.
2. One lookup per distinct normalized ISRC can be accounted for separately from
   per-occurrence fuzzy fallback. Case, spacing, and punctuation variants can be
   normalized without retaining the normalized value in the report.
3. Every attempted synthetic lookup can land in exactly one required class.
   Only a verified, version-safe, duration-safe, market-safe result can skip
   fuzzy fallback; list position alone carries no authority.
4. The Beatport V2 contract is the lower-risk first source path because it
   carries public typed `track.isrc` evidence without local-file access. Under
   the current normative schema, missing `isrc` is accepted as absence, a
   malformed string passes structural validation but fails normalization, and
   `null` or a moved field is rejected by the contract.
5. Local URI, file, format, and tag outcomes can be represented as aggregate
   counters without paths or metadata. This is a model of the boundary only;
   it does not prove Mutagen parsing, filesystem behavior, or platform-specific
   URI decoding.
6. A request budget and missing Phase B/C authorization can stop the model
   before the gated boundary. The rendered state and report retain zero paths,
   titles, artists, raw tags, ISRC values, or Spotify identifiers.

## What remains unproved

- Real Beatport ISRC availability and correctness across representative exports.
- Real local audio URI decoding, filesystem containment, format support, tag
  parsing, and ISRC coverage.
- Live Spotify result distributions, relinking and market behavior, accepted
  match correctness, review-required rate, and actual request savings.
- Whether material net savings remain after existing Approved Match and retained
  cache reuse on a representative user-selected sample.

Synthetic counts are conformance evidence for the method, not product evidence.
They must not be used to claim real accuracy, coverage, or savings.

## Recommendation

**Proceed only to a separately authorized Phase B, starting with a small named
Batch and aggregate-only output. Do not create an implementation ticket yet.**

Phase B should validate the highest-risk unproved boundary: exact selected-file
URI handling and representative local tag extraction. If its coverage is too
low, paths cannot remain private, or the boundary cannot be kept selection-only,
stop ISRC-first local-file work. Phase C should remain separately locked until
Phase B is accepted and a human approves an explicit sample size and maximum
Spotify request count.
