# AI-assisted UX and user-research tools for roadmap validation

**Date:** 2026-08-01

**Status:** Public-source research; no vendor account was created, no vendor was
contacted, and no repository or user data was uploaded.

**Roadmap:** [playlist management after 0.4.0](../plans/2026-08-01-playlist-management-roadmap.md)

## Executive recommendation

DJ Support does not need a large “synthetic customer” platform. It needs a
small continuous-discovery system that connects each roadmap claim to the
least expensive credible evidence and refuses to treat generated opinions as
user validation.

Use three layers:

1. **Local, synthetic critique** to find missing states, rehearse an interview
   guide, and generate counterexamples. This can use generic local or
   organization-approved models with invented playlists and personas. It is a
   design-review aid, not research evidence.
2. **Five to eight real DJs per distinct workflow** for moderated or
   unmoderated prototype tasks, recruited from the intended audience. Maze is
   the most accessible packaged prototype-testing option because it advertises
   a free plan with one study per month; Prolific is a transparent pay-as-you-go
   alternative for recruitment, although screening for actual Rekordbox,
   Beatport, and Spotify experience remains the researcher's job
   ([Maze pricing](https://maze.co/pricing/),
   [Prolific pricing](https://www.prolific.com/pricing)).
3. **A local evidence register** in redacted Markdown, linked to roadmap
   decisions. Dovetail becomes reasonable only when volume and collaboration
   make a repository worth sending research data to a processor; its current
   free tier is one project and its Enterprise tier is custom-priced
   ([Dovetail pricing](https://dovetail.com/pricing/)).

For a first study, test the 0.5/0.6 read-only path with five real DJs: “Is this
Mirror unchanged; if not, what do you think happened and what would you do
next?” Use a clickable prototype containing only invented track and playlist
data. Measure task interpretation, confidence, and unsafe-action attempts.
Do not test a live Spotify account and do not ask participants to expose their
libraries.

## Evidence hierarchy and non-substitution rule

**Synthetic users cannot replace real users.** An LLM has no DJ library,
embodied workflow, financial stake, playlist history, privacy concern, or
consequence if a restore destroys order. It predicts plausible text from its
training and prompts. Plausibility is useful for brainstorming and dangerously
easy to mistake for observed behavior.

Use this hierarchy, highest confidence first:

| Level | Evidence | Permitted roadmap use |
| --- | --- | --- |
| 1 | Observed behavior by correctly screened real target users in the relevant workflow, repeated after design changes | Release gate or priority change when the study matches the decision |
| 2 | Real-user interview, diary, support, or field evidence with traceable quotes/context | Problem framing and hypothesis formation; behavioral claims need observation |
| 3 | Product telemetry or aggregate operational evidence, collected with consent and interpreted with qualitative context | Frequency and funnel evidence; not motivation by itself |
| 4 | Independent HCI research, standards, and established usability principles | Design constraints and research-method choice; transferability must be argued |
| 5 | Expert review, cognitive walkthrough, heuristic evaluation, and adversarial scenario analysis | Find likely defects and prepare real-user studies |
| 6 | Synthetic personas, simulated interviews, generated journeys, or multi-agent worlds | Generate hypotheses, missing states, scripts, and test cases only |
| 7 | Vendor case studies, testimonials, and unreplicated vendor benchmarks | Product discovery only; never validation of DJ Support or of the vendor's accuracy |

Nielsen Norman Group's public guidance is blunt that synthetic “participants”
are fake users and that user research needs real users
([NN/g overview](https://www.youtube.com/watch?v=q_fdcbwHJKQ)). Academic work
shows that generative agents can produce *believable* behavior, which is not
the same as predicting a target population
([Generative Agents paper](https://arxiv.org/abs/2304.03442)). A recent critical
HCI analysis identifies proprietary validation and independent-verification
gaps as core problems for synthetic-user systems
([Jansen, Jung and Salminen](https://www.bernardjjansen.com/uploads/2/4/1/8/24188166/3745900.3746108.pdf)).

## Tool landscape

Pricing and capabilities below are what vendors publicly stated on 2026-08-01.
“Popular” has no single auditable definition: vendors rarely publish active
paid-customer counts, independent market share, completion quality, or
retention. Panel size, named customers, interview counts, and “trusted by”
figures are therefore labeled as vendor claims, not adoption proof. Absence of
a public price is itself material for a solo project.

### Comparison

| Tool | Actual capability and inputs | Data, access, and integrations | Evidence and failure modes | DJ Support fit |
| --- | --- | --- | --- | --- |
| **Synthetic Users** | Generates audience-defined synthetic participants for interviews, surveys, concept tests, images/video/live-site stimuli, and RAG grounding from uploaded customer data ([core concepts](https://docs.syntheticusers.com/guides/core-concepts), [pricing](https://www.syntheticusers.com/pricing)). | Annual plans start at **US$12,500**; user inputs may be sent to AI subprocessors including OpenAI, Anthropic, Google, Meta, and Mistral in the US. The company says customer data is not used to train shared models ([privacy](https://legal.syntheticusers.com/privacy-policy), [terms](https://legal.syntheticusers.com/terms-of-service)). | The vendor claims 85–92% “synthetic-organic parity” and cites supporting papers, but the metric and selection are vendor-framed. Encouragingly, its current FAQ says real research remains essential. Failure modes: stereotype amplification, homogeneous answers, circular RAG, invented needs, no consequential behavior, prompt sensitivity. | **Do not buy.** The price exceeds likely value. If ever trialed, use only invented data to rehearse questions; require a paired real-user study before any decision. |
| **Outset** | AI-moderated text, voice, and video interviews; dynamic follow-ups; diary studies; guide generation; participant recruitment; automated themes, transcripts, highlight reels, and exports ([product overview](https://outset.ai/official-outset-company-information), [pricing](https://outset.ai/pricing)). | Custom subscription pricing. Vendor states SOC 2 Type II, GDPR and HIPAA compliance, encryption at rest/TLS 1.3, segregated workspaces, SSO, and no training on customer data. Supports bring-your-own or recruited panels and survey integrations. | Claims 40+ languages and reach to a billion potential participants are vendor marketing, not evidence that niche DJs are available or well screened. AI probing can lead participants, miss hesitation/context, flatten minority views, and turn model-generated themes into false certainty. | **Later/conditional.** Useful if dozens of real participants must be interviewed asynchronously; likely excessive for a solo allowlisted product. Obtain DPA/retention/subprocessor details before any private study. |
| **Askable** | Recruits real participants and supports moderated, unmoderated, prototype, card-sort, tree, diary, survey, A/B, first-click, AI-moderated interviews, and evidence-linked synthesis ([methods](https://www.askable.com/methods/ai-moderated-interviews), [pricing](https://www.askable.com/pricing)). | Pro and Enterprise are quote-based; incentives are bundled into study credits. Vendor states SOC 2 Type II, ISO 27001, GDPR, custom retention and SSO. Terms permit use/commercialization of anonymized aggregate study materials, so contract review matters ([participant terms](https://www.askable.com/legal/terms), [incentives](https://help.askable.com/en/articles/4275559-about-participant-incentives)). | “10,000 enterprise teams,” panel quality, 38,000+ AI interviews, cost reduction, and AI-moderator skill are vendor claims. The same moderation and synthesis risks as Outset apply; a broad panel may still contain few working DJs with the exact tool chain. | **Conditional alternative to Maze plus recruitment.** Attractive as one vendor if price and niche recruitment are acceptable; too opaque to select without a quote and data-processing review. |
| **Maze** | Unmoderated prototype and live-site tests, surveys, card/tree testing, first-click and path metrics, recordings, panel recruitment, AI study building/moderation, and automated analysis ([pricing](https://maze.co/pricing/)). | Free: one study/month, essential prototype testing, surveys, pay-per-use panel. AI moderation, moderated interviews, mobile experience testing, recordings, and enterprise controls are listed under custom Enterprise. Panel credits are usage-based ([credit guide](https://help.maze.co/articles/2270887486-how-much-do-panel-credits-cost)). | Vendor claims a 5–7M+ panel; that is inventory, not proof of correct representation or data quality. Prototype metrics show what happened in the test, but weak tasks, professional-test behavior, device mismatch, and AI summaries can mislead. | **Best packaged first experiment.** Free/low-commitment prototype testing fits a solo project. Bring carefully screened DJs; do not assume the general panel can supply them. Export only redacted findings. |
| **UserTesting** | Large real-participant network; unmoderated think-aloud, interaction tests, surveys, live interviews, prototype hosting, recordings, transcripts, AI-assisted test creation and insight summaries ([plans](https://www.usertesting.com/plans/), [AI guide](https://help.usertesting.com/hc/en-us/articles/13268801005469-UserTesting-and-Artificial-Intelligence)). | Custom test-consumption or team-based pricing. Integrations publicly listed in procurement material include Qualtrics, Contentsquare, Quantum Metric, Jira, Slack, Miro and FigJam. Security materials describe extensive recording and enterprise controls ([security](https://www.usertesting.com/privacy-center/security)). | Long-standing category visibility and a vendor network are stronger adoption signals than a new synthetic-only service, but public market share and current prices are unavailable. Professional testers, screener gaming, recorder friction, and AI-summary errors remain risks. | **Good but disproportionate.** Choose only if Maze/own recruitment cannot supply target devices or geography and an enterprise budget exists. |
| **Dovetail** | Research repository for recordings, transcripts, documents, tagging, evidence-linked insights, semantic search, AI summaries/translation/agents, and shareable reports ([repository](https://dovetail.com/solutions/research-repository/), [pricing](https://dovetail.com/pricing/)). | Free is one channel/one project; Enterprise is custom-priced and adds redaction, access controls, audit/security features and advanced AI. Vendor says data is not used to train its or other customers' models ([AI data handling](https://dovetail.com/help/dovetail-ai/), [security](https://docs.dovetail.com/help/security-information)). | It synthesizes evidence; it does not make weak recruitment or study design valid. AI tags can erase contradiction and provenance unless every insight is checked against source material. Repository value depends on sustained research volume and actual retrieval. | **Use local Markdown first.** Reconsider when several collaborators and enough studies create a retrieval problem. Never import raw music-library or Spotify content merely for convenience. |
| **Prolific** | Recruitment of verified real participants with demographic prescreening; studies run in external survey/prototype/interview tools. This is a human panel, not a synthetic-user simulator ([pricing](https://www.prolific.com/pricing/), [screening/privacy](https://participant-help.prolific.com/en/articles/449630-prolific-practises-and-security-systems)). | Pay as you go: researcher-set reward plus **42.8% corporate platform fee**; recommended minimum reward US$12/£9 per hour. No subscription is required. Participants use pseudonymous IDs and the platform supports anonymous messaging. | Vendor claims 300,000+ active participants. Independent behavioral-research literature cited by Prolific found higher data quality than several alternatives, but that does not guarantee a rare DJ segment ([peer-reviewed comparison](https://link.springer.com/article/10.3758/s13428-021-01694-3)). Bots, AI-assisted answers, self-report error, and false screener responses still require attention checks and behavior-based screening. | **Best transparent recruitment fallback.** Run a cheap screener/pilot first; require actual workflow evidence without requesting account IDs, playlist names, screenshots, or music files. |
| **Open-source generative-agent systems** | Research code and architectures give LLM agents memory, reflection, plans, roles, and an environment to simulate interactions. UXAgent specifically drives browser tasks and emits interaction logs; broader systems include Generative Agents, SOTOPIA, and OASIS ([UXAgent](https://arxiv.org/abs/2504.09407), [Generative Agents](https://arxiv.org/abs/2304.03442), [SOTOPIA](https://github.com/sotopia-lab/sotopia), [OASIS](https://github.com/camel-ai/oasis)). | Self-hosting can keep invented scenarios local, but model API use may still transmit prompts and output. Engineering, evaluation, and inference costs replace SaaS fees. They integrate through code rather than research-tool connectors. | UXAgent is explicitly framed as a way to refine studies before real-human research and had a small expert evaluation. Other papers evaluate believability, social interaction, or bounded task behavior—not whether agents predict a particular DJ's destructive-action choices. Agent agreement can be correlated model agreement, not independent participants. Results vary with model, prompt, memory, seed, and environment. | **Useful as a test generator only.** Simulate state-machine journeys and adversarial sequences with synthetic facts; do not report agent votes or percentages as user evidence. |

### What is absent or weakly evidenced

- No reviewed product publishes an independently audited guarantee that its
  synthetic personas predict real-user preference or task behavior for a new
  domain.
- Vendor security certifications show controls, not research validity or zero
  privacy risk. Exact retention, deletion, subprocessors, regional hosting,
  model providers, and training terms must be checked in the contract in force
  when a study runs.
- A large general panel does not establish access to DJs who actively use the
  required combination of Rekordbox, Beatport, and Spotify.
- AI-moderated interviews still involve **real users**; they should not be
  grouped with synthetic interviews. Their main risk is moderator and analysis
  quality, not fabricated participants.
- AI synthesis saves clerical time but may create a polished monoculture. Keep
  recordings/transcripts, contradictory cases, and evidence links available
  for human review.

## Privacy and research protocol for DJ Support

The roadmap and API review impose a stronger boundary than ordinary product
research. Spotify content must not be ingested into an ML/AI model, and local
Rekordbox/audio data, Corrections, matching truth, playlist state, account and
playlist identifiers, reports, and recovery evidence are private user data.

Therefore:

1. Build every external study with fictitious artist, track, playlist,
   snapshot, account, and error data. Avoid copied Spotify metadata, artwork,
   screenshots, URLs, URIs, and IDs.
2. Host a static or instrumented fake prototype. Never connect a participant's
   Spotify, Beatport, or Rekordbox account; never request an XML file, audio
   tag, local path, playlist screenshot, Correction, or actual report.
3. Record the minimum: task outcome, clicks, time, confidence, explanation,
   and optional audio/video only with explicit consent. Offer a non-recorded
   path where feasible.
4. Use a short retention deadline, pseudonymous participant IDs, least-access
   roles, encrypted export, and deletion verification. Keep consent records
   separate from observations.
5. Review every AI-generated guide, follow-up, tag, summary, and translation
   against the original human evidence. Label generated material.
6. Store only redacted aggregate findings in the repository. Raw recordings,
   transcripts, screener responses, incentives, and participant contact data
   remain outside Git in approved private storage.

## Continuous discovery loop tied to the roadmap

```text
Roadmap claim
  -> local synthetic challenge with invented facts
  -> prototype and explicit success/risk measures
  -> 2-person pilot
  -> 5-8 correctly screened real DJs per distinct workflow
  -> inspect recordings/transcripts and contradictions
  -> decision: proceed, revise and retest, or stop
  -> redacted evidence note linked to the release gate
  -> post-release opt-in feedback and a new cycle
```

Synthetic critique happens before the pilot so it improves the study rather
than contaminating interpretation afterward. A study tests one decision, not
an entire release. Five is a practical starting point for a narrow qualitative
usability cycle, not a statistical sample or a universal stopping rule; add
participants for distinct skill levels, devices, languages, and observed
variation.

### Release experiments and gates

| Roadmap slice | Real-user experiment | Decision gate |
| --- | --- | --- |
| **0.5 trustworthy foundation** | Clickable Preview/Approval flow with changed-head, private-scope denial, null/unavailable item, and paused-publication scenarios. Ask users to predict whether anything has changed and what happens next. | At least 5/5 understand Preview as non-mutating; 5/5 recognize changed-head re-review; no participant believes Approval silently repairs or learns from removed items. Any unsafe interpretation blocks copy/flow release. |
| **0.6 explain and preserve** | Compare two Drift explanations and a restore Preview using ordered duplicates, source change, manual Spotify edit, relinking, and unknown items. Include request/private-data disclosure. | Users correctly distinguish source change from Playlist Drift in at least 4/5 cases; all understand backup is local and Preview performs zero writes; no design hides unknown/unrestorable items. Revise and rerun if a destructive remedy appears automatic. |
| **0.7 guarded recovery** | Moderated destructive-action study with confirmation, fresh-head mismatch, 101+ item partial failure, duplicate occurrence, pause/resume, and uncertain outcome. Use a fake playlist only. | 5/5 can state destination, losses, call/chunk risk, and recovery state before confirming; 5/5 stop on stale head; no accidental confirmation. This is a hard gate, not a majority vote. |
| **0.8 evidence-led matching** | Blind comparison of existing versus candidate match explanations using synthetic truth cases, followed by real DJs judging ambiguity and Correction affordance—not hidden model accuracy. Separately test Chrome capture/status only after the Transfer contract stabilizes. | No accepted change increases wrong confident selections in the bounded truth set; ambiguity routes to review; all participants understand Correction and Approval. Synthetic-agent output alone can never pass the gate. |

### Cross-release research questions currently missing

The roadmap is strong on correctness and API constraints but under-specifies
these user facts:

- Who is the primary early user: the owner only, an allowlisted technical DJ,
  or a less technical DJ? This changes language, installation, and acceptable
  recovery complexity.
- Which moments create the most anxiety: OAuth consent, matching review,
  Approval, Drift, or restore? Confidence should be measured at each boundary.
- What evidence makes a DJ trust a proposed match: title/artist/version,
  duration difference, ISRC, playable preview, playlist context, or something
  else? Issue #56 and 0.8 should use observed ranking, not assumed copy.
- Does the user think in source playlists, Spotify destinations, or Transfer
  history when recovering? This decides the information architecture for #61
  and durable publication discovery.
- How do DJs interpret “Mirror,” “Snapshot,” “Provisional Playlist,” “Drift,”
  and “Approval” without training? Canonical engineering language still needs
  comprehension testing.
- What is an acceptable waiting, request-cost, and interruption model for large
  libraries? The Batch estimator needs user thresholds as well as API math.

## Recommended tool shortlist

1. **Now: local prototype + live moderated calls + local evidence register.**
   Recruit five known or referred DJs with a consistent screener. This is the
   cheapest and highest-signal setup.
2. **When remote task metrics help: Maze Free.** Use one focused prototype
   study per month and bring the target participants. Disable unnecessary
   recording/AI features and export redacted observations.
3. **When recruitment is the bottleneck: Prolific pay as you go.** Pilot the
   incidence rate before committing; use behavior-based screeners and fair pay.
4. **When asynchronous qualitative scale is genuinely needed: compare Outset
   and Askable.** Require sample data-processing terms, subprocessor/retention
   answers, a niche-panel incidence test, and a human-moderated benchmark.
5. **When evidence retrieval becomes painful: Dovetail.** Until then, a local
   structured Markdown register is cheaper, easier to audit, and better aligned
   with DJ Support's privacy boundary.
6. **Synthetic Users and generative-agent frameworks: ideation only.** The SaaS
   price and validation uncertainty make Synthetic Users a poor purchase;
   open-source agents are justified only if their test-generation value exceeds
   their engineering cost.

UserTesting is a capable enterprise fallback, but quote-only pricing and broad
scope make it unlikely to beat Maze plus direct or Prolific recruitment here.

## Budget bands

These bands are planning envelopes, not vendor quotes. They exclude the
researcher's time and should be recalculated before purchase.

| Band | Setup | Likely use |
| --- | --- | --- |
| **€0–€150 per cycle** | Own calls/prototype; Maze Free; five participants at €20–€30 if recruited directly | Best starting point for each narrow workflow |
| **€150–€600 per cycle** | 5–10 paid niche participants, Prolific fees, prototype hosting, optional transcription | Remote cross-market validation and harder recruitment |
| **€600–€2,500 per cycle** | Specialist recruitment, 10–20 participants, accessibility/device coverage, or a short AI-moderated pilot | High-risk 0.7 recovery gate or multiple distinct cohorts |
| **€10,000+ annually** | Quote-based enterprise suite or Synthetic Users (officially starts at US$12,500/year) | Not justified until repeated research volume, collaboration, and procurement needs are demonstrated |

For Prolific, a US$100 total corporate budget contains US$70 in participant
rewards under its published 42.8% fee example; taxes may apply
([pricing detail](https://researcher-help.prolific.com/en/articles/445239-what-is-your-pricing)).

## Minimal first study

**Decision:** Can a DJ correctly understand the read-only unchanged/changed
Mirror result and choose to inspect a change without expecting an automatic
repair?

**Participants:** Five adults who used Rekordbox to prepare music and Spotify
playlists within the last three months. Aim for at least two who are not
developers. Recruit directly first; do not ask for proof containing private
library data.

**Stimulus:** A five-screen clickable prototype using obviously fictitious
artists and playlists:

1. Select one source playlist.
2. Preview scope and estimated calls.
3. Unchanged Mirror result.
4. Changed snapshot with ordered Drift facts and one unknown item.
5. Choice to inspect, leave unchanged, or return; no restore action.

**Tasks and questions:** Ask the participant to explain what data will be read,
whether Spotify has already changed, what “unchanged” proves, what the changed
case might mean, and what each next action would do. End with unaided recall of
Mirror, Preview, Drift, and Approval; do not teach definitions first.

**Measures:** Task completion, unsafe-action expectation, wrong source-versus-
Spotify attribution, time to explanation, confidence (1–5), terminology
misinterpretation, privacy concern, and verbatim evidence behind each error.

**Gate:** Proceed to the 0.5 tracer UI only if all five understand that Preview
and inspection do not mutate Spotify and at least four correctly distinguish an
unchanged head from proof that every item is healthy. Otherwise change the
facts/copy and repeat with five new participants. This study informs interface
and wording; it does not replace adapter contract tests.

**Cost/time:** 30 minutes each plus a two-person pilot; approximately €100–€200
in participant incentives and one research day for preparation, sessions, and
synthesis. Maze is optional; ordinary screen sharing is enough for the first
cycle.

## Procurement and study checklist

Before using any hosted research or AI service:

- Confirm controller/processor roles, DPA, subprocessors, model providers,
  training use, storage region, retention/deletion, breach notice, export, and
  account deletion in the current contract—not only the marketing page.
- Confirm whether screen, audio, video, transcript, IP/device, interaction and
  generated-analysis data are collected; disclose each to participants.
- Test niche-DJ incidence and participant identity/quality controls with a
  small paid pilot.
- Compare AI moderation and synthesis with a manually reviewed sample; record
  missed probes, leading questions, false themes, and erased contradictions.
- Set a maximum budget, participant count, retention date, and stop rule before
  launch.
- Keep all stimuli synthetic, all raw research private, and the repository
  result aggregate/redacted. Never send Spotify content or private DJ Support
  state into an AI model.

## Conclusion

The missing link is not another roadmap feature or an AI persona subscription.
It is a disciplined chain from roadmap assumption to synthetic challenge, real
DJ observation, explicit decision gate, and redacted durable evidence. Start
with five real DJs and the read-only 0.5/0.6 tracer. Add Maze for repeatable
prototype tasks and Prolific only when recruitment becomes difficult. Keep
enterprise suites and synthetic-user products outside the critical path until
actual research volume proves the need.
