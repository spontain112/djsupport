# Make Transfer agent-native without creating agent authority

AI coding harnesses such as Codex are a primary operating surface for DJ
Support. They need a stable way to inspect the installation, plan bounded work,
execute or resume it, and explain the result. Treating a harness as an
incidental shell wrapper would encourage prompt scraping, hidden interactive
questions, duplicated policy, and accidental expansion of private-file or
Spotify authority.

DJ Support therefore treats AI harnesses as first-class clients of the public
Transfer contract. Every agent flow follows five explicit phases: capability
inspection, bounded Batch planning, authorization, execute or resume, and a
structured outcome. Transfer remains the only policy authority. CLI, web, and
future harness adapters may render its behavior but may not create separate
matching, Approval, persistence, or publication rules.

Capability inspection is side-effect free and does not read a Rekordbox XML
file, audio, matching knowledge, or Spotify account. Planning requires explicit
private-source authorization and cannot broaden an explicitly selected Batch.
Spotify mutation requires a separate explicit authorization. Conversation,
ambient browser state, previous sessions, or an agent's judgment are never
authority. Missing authorization produces a versioned
`authorization_required` outcome before the gated effect; once all required
inputs are present, execution is non-interactive.

Machine-readable capability, plan, progress, and outcome records are versioned,
idempotent, and privacy-redacted by construction. They may expose aggregate
counts, lifecycle states, stable Transfer or Batch identifiers, reason codes,
and permitted next actions. They do not expose source paths, playlist or track
contents, raw XML metadata, fingerprints, subprocess output, credentials, or
Spotify account identifiers.

Transfer derives the Batch identifier from the exact selected source content
and requested effect scope, then hashes that private material before returning
the identifier. Confirmation does not alter identity. A changed source,
Preview/publication mode, matching policy, or local-audio opt-in cannot resume
an earlier Batch. Legacy checkpoints without this bounded identity remain
readable for inspection but must be restarted rather than resumed ambiguously.

Opt-in local audio identity is the first end-to-end proof of this decision. An
agent can detect Chromaprint support, plan one selected Rekordbox Batch, obtain
separate authority, and run or resume the Transfer through the same policy used
by human-facing clients. The fingerprint remains private evidence and cannot
create Approval. An exact account-scoped fingerprint may reuse an already
Approved Match; similar evidence remains non-authoritative.

This decision does not require a proprietary harness, an MCP server, a hosted
agent service, conversational authorization inference, or an agent-specific
policy engine. Those may be evaluated later as adapters over the same contract.
