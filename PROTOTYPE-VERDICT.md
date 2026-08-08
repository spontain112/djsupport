# Integrated Review Prototype Verdict

## Question

Should DJ Support replace the current review workflow with one integrated
Correction Search surface, and what should that surface look like?

## Verdict

Do not build one universal review surface.

- **Browser-origin selections** such as Beatport charts already have a useful
  source interface. Publish a Provisional Spotify Snapshot, let the user review
  it in Spotify, and interpret removals only through the existing explicit
  Approval workflow. Correction Search remains subordinate and user-requested.
- **Rekordbox XML selections** need a DJ Support qualification workspace because
  Spotify cannot expose the local source evidence. Prototype C's queue,
  evidence workspace, listening area, and single decision rail is the preferred
  desktop information architecture.
- **Large Rekordbox libraries** must be playlist-scoped and attention-led.
  Reuse Approved Matches and focus qualification on new proposals, meaningful
  duration or version conflicts, Match Collisions, and unresolved tracks rather
  than requiring review of every track.

The governing product principle is:

> Review in the destination when the source is already understandable; use DJ
> Support as the comparison surface when the destination cannot reveal the
> source evidence.

## Rekordbox qualification behavior

The workspace should determine the source capability automatically. The user
must never configure source types or playback states.

When a selected Rekordbox file is available and the user explicitly authorizes
that source audio, present local source playback beside the Spotify proposal.
Show duration, version, and release evidence, then offer only the human outcomes
needed to continue: Correct, Wrong — find another, Cannot verify, or Not my
source. Advance automatically after a decision.

If the referenced local file is unavailable, say so. Never treat metadata as
listening evidence or infer a decision. The user may locate the source
externally or defer.

## Prototype findings

- Ten owner-test Beatport proposals were human-decidable and all ten were judged
  correct.
- Browser search mostly surfaced alternate Spotify release representations,
  not better recordings.
- Duration was the first useful discriminator, artwork and release context
  explained alternate representations, and listening was the final check.
- The conversational Correction Search workflow failed the owner's preference
  gate despite satisfying its bounded-search safety constraints.
- UI variant C won for desktop, but needed earlier responsive breakpoints for a
  narrow Codex browser window.
- The source-audition state console was rejected because it exposed internal
  capability and authorization mechanics as a large set of user controls.

## Safety and authority

Playback, browser search, and conversation never create Approval, Correction,
Rejected Match, source relinking, or playlist mutation. Local audio remains
explicitly selected, local-only, and separately authorized. The private owner
test data and generated real-data HTML remain outside Git.

## Captured prototype files

- `djsupport/static/integrated-review-prototype.html` — three synthetic UI
  variants; C is the preferred Rekordbox desktop structure.
- `djsupport/static/source-audition-logic-prototype.html` — rejected synthetic
  state-console exploration retained as evidence of what not to expose.
- `djsupport/static/generate-integrated-review-prototype.py` — throwaway private
  instance generator with an output guard preventing real-data artifacts from
  being written into the repository.

These files are primary-source prototype evidence on this throwaway branch.
They are not production implementation and must not be merged into `main`.
