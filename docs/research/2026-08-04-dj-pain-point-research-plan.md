# DJ pain-point research plan

**Date:** 2026-08-04

**Status:** proposed primary-research plan; no product commitment

**Decision:** Which recurring preparation, analysis, and music-discovery pain
points should DJ Support solve next?

## Executive summary

DJ Support should first test a **DJ Briefing with a short decision queue**:
for one explicitly selected crate or Batch, answer “is this ready, what changed,
and what needs me?” It would combine facts DJ Support already knows—unmatched
tracks, questionable versions, unavailable Approved Matches, Match Collisions,
Playlist Drift, incomplete work, local-audio availability, and expected Spotify
cost—without changing Spotify or inventing musical judgment.

This is the strongest hypothesis, not yet a proven user need. It fits the
product better than a generic discovery engine or a second audio analyzer:

- DJ Support already retains the relevant typed facts and defines safe Preview,
  Approval, Drift, and recovery behavior through Transfer
  ([product context](../../CONTEXT.md), [current report model](../../djsupport/report.py)).
- Established DJ products already invest heavily in BPM, key, waveform, cue,
  energy, smart-playlist, and related-track analysis. Their repeated presence
  demonstrates that preparation and discovery are real job categories, but not
  that DJ Support should duplicate them. Rekordbox offers analysis, Intelligent
  Playlists, Collection/Streaming Radar, and track suggestions
  ([Rekordbox overview](https://rekordbox.com/en/feature/overview/)); Serato
  analyzes corruption, waveform, gain, key, BPM, and grids
  ([Serato preparation](https://support.serato.com/hc/en-us/articles/202538540-Preparing-and-Analyzing-Your-Files));
  and Mixed In Key analyzes key, BPM, energy, and cues while explicitly telling
  DJs to confirm important transitions by listening
  ([Mixed In Key energy workflow](https://mixedinkey.com/workflows/use-energy-level-detection/)).
- Beatport already personalizes daily recommendations from purchases, playlists,
  carts, streams, and DJ Charts
  ([Beatport recommendations](https://support.beatport.com/hc/en-us/articles/39971015802388-How-do-my-track-recommendations-work)).
  Spotify no longer gives newer Development Mode applications access to
  Recommendations, Audio Features, or Audio Analysis
  ([Spotify developer change](https://developer.spotify.com/blog/2024-11-27-changes-to-the-web-api)).
  A catalog-wide recommendation engine would therefore compete where DJ Support
  has weaker data and a constrained API.
- DJ Support's distinctive asset is cross-system intent and uncertainty: it
  knows the selected source, proposed and Approved Matches, Corrections,
  publication state, Drift, and what is still unresolved. No reviewed incumbent
  is evidenced here as combining those exact facts across Rekordbox, Beatport,
  and Spotify.

Run a two-week lean study with 6–8 working or actively practicing DJs. Observe
their most recent preparation and discovery workflows using participant-
controlled screens or synthetic data, then evaluate three plain-language
concepts: **DJ Briefing**, **Crate X-Ray / rediscovery**, and **What’s New?
Radar**. If Briefing survives discovery, run a counterbalanced test against the
current detailed report. Do not build Set Flow, a recommendation engine, or a
new dashboard before this evidence exists.

## What the evidence establishes—and what it does not

The sources below are first-party product documentation. They show that vendors
have built around a job; they do **not** establish frequency, severity,
satisfaction, or willingness to adopt DJ Support for that job. Those remain
hypotheses for primary research.

| Candidate pain | Existing evidence | Still a hypothesis |
| --- | --- | --- |
| “I do not know whether this crate is ready.” | Serato recommends analyzing selected crates before a gig and exposes not-yet-analyzed counts; Traktor offers a collection Consistency Check with missing and unanalysed-track reports ([Serato](https://support.serato.com/hc/en-us/articles/202538540-Preparing-and-Analyzing-Your-Files), [Traktor collection manual](https://www.native-instruments.com/ni-tech-manuals/traktor-pro-manual/en/managing-your-track-collection)). DJ Support already reports unresolved, unavailable, collision, Drift, and progress facts. | DJs currently perform a final readiness check; the cross-system uncertainty DJ Support sees is among their highest-cost concerns; one briefing would reduce rechecking. |
| “My library has become hard to understand.” | Serato supports nested crates, Smart Crates, “Show in Crates,” and per-crate counts; Engine DJ Smartlists update from collection rules; Traktor has Smartlists, playlist maintenance, duplicate removal, and consistency checks ([Serato crates](https://support.serato.com/hc/en-us/articles/227561407-Crates-in-Serato-DJ-Pro-Serato-DJ-Lite-4-0), [Engine DJ Smartlists](https://support.enginedj.com/support/solutions/articles/69000839766-engine-dj-smartlists-frequently-asked-questions), [Traktor playlists](https://www.native-instruments.com/ni-tech-manuals/traktor-pro-manual/en/working-with-playlists)). | Cross-crate overlap, forgotten tracks, and nearly duplicate crates are frequent enough to justify a separate Crate X-Ray; DJs cannot already answer these questions quickly in their main software. |
| “I lose track of what changed.” | Engine DJ requires re-export after Smartlist rules or contents change, and Rekordbox/Serato/Traktor all maintain evolving playlist structures. DJ Support already distinguishes source change from Spotify Playlist Drift and retains content-bound Batch identity ([Engine DJ Smartlists](https://support.enginedj.com/support/solutions/articles/69000839766-engine-dj-smartlists-frequently-asked-questions), [roadmap](../plans/2026-08-01-playlist-management-roadmap.md)). | A historical “what changed?” view is a recurring preparation job rather than an occasional recovery need; users want history grouped around a source crate rather than Spotify destination or Transfer. |
| “I forget good music I already own.” | Rekordbox offers Related Tracks, Track Suggestion, Collection Radar, and Intelligent Playlists; Serato exposes all crates containing a track. These support retrieval and rediscovery inside an existing collection ([Rekordbox operations FAQ](https://rekordbox.com/en/support/faq/operation-hints-7/), [Serato crates](https://support.serato.com/hc/en-us/articles/227561407-Crates-in-Serato-DJ-Pro-Serato-DJ-Lite-4-0)). | DJs want another local, explainable rediscovery layer based on labels, remixers, genres, dates, and crate relationships; DJ Support's suggestions would beat simply using Rekordbox. |
| “Finding genuinely new music takes too much digging.” | Beatport recommendations refresh daily and use behavioral and DJ Chart data. Beatport also promotes on-the-go discovery and playlists that continue into desktop and DJ contexts ([Beatport recommendations](https://support.beatport.com/hc/en-us/articles/39971015802388-How-do-my-track-recommendations-work), [mobile evidence](2026-08-01-mobile-discovery-and-capture.md)). | DJs need DJ Support to monitor explicit labels/charts or keep a discovery inbox; existing Beatport playlists and feeds fail at a specific handoff. |
| “A playlist is not yet a coherent set.” | Mixed In Key markets key, BPM, Energy Level, and cue-based set planning, while warning that context and listening still decide whether a transition works. Rekordbox offers Dual Player, key/phrase analysis, and related-track tools ([Mixed In Key](https://mixedinkey.com/workflows/use-energy-level-detection/), [Rekordbox overview](https://rekordbox.com/en/feature/overview/)). | DJs lack satisfactory set-flow support; they trust metadata-only warnings; DJ Support can add value without acquiring or deriving richer audio-analysis data. |
| “Files or metadata break at the wrong time.” | Rekordbox, Serato, Traktor, and Engine DJ all document missing-file relocation or collection checks; Serato analysis explicitly detects corrupt files ([Rekordbox missing files](https://rekordbox.com/en/support/faq/v6/#faq-4787), [Serato lost files](https://support.serato.com/hc/en-us/articles/14359604291599-Relocate-Lost-Files), [Engine DJ missing files](https://support.enginedj.com/support/solutions/articles/69000856265-missing-files-within-engine-dj-deleting-removing-groups-and-selected-tracks)). | File health belongs in DJ Support rather than the DJ application that owns the local library; users want DJ Support to read or change more local files. |

The current roadmap deliberately prioritizes safe state explanation and recovery
before speculative expansion, and requires consequential UX decisions to be
validated with real DJs ([roadmap principles](../plans/2026-08-01-playlist-management-roadmap.md)).
The earlier AI/UX review also concludes that synthetic users may improve a study
but cannot replace correctly screened human participants
([AI/UX research](2026-08-01-ai-ux-research-tools.md)).

## Pain-point taxonomy

Use this taxonomy for observation and coding. It describes jobs and failure
costs rather than proposed screens.

1. **Readiness and trust** — not knowing whether intended tracks are present,
   playable, analyzed, correctly represented, and safe to rely on before a set.
2. **Exception closure** — finding and resolving the few wrong, missing,
   unavailable, conflicting, or manually changed tracks without rereading a
   complete report or rerunning everything.
3. **Change awareness** — understanding what changed in the source, Spotify,
   or the Transfer since the last trusted state and deciding what, if anything,
   to do.
4. **Library comprehension** — seeing overlap, stale/near-duplicate crates,
   repeated artists/labels/remixers, unique tracks, and tracks that bridge
   several crates.
5. **Rediscovery** — recovering useful music already owned or previously
   approved but forgotten, with an understandable reason for each suggestion.
6. **External discovery continuity** — taking a promising label, chart, track,
   or page from encounter to a reviewable shortlist without losing it or
   publishing prematurely.
7. **Set-shaping judgment** — deciding whether order, tempo, key, phrase,
   energy, vocals, and crowd context form the intended journey. Software can
   narrow candidates; the DJ's ears and context remain authoritative.
8. **Library integrity** — missing files, corrupt audio, stale analysis, bad
   paths, and destructive maintenance. This is important but likely belongs
   primarily to Rekordbox/Serato/Traktor/Engine unless research exposes a
   cross-system gap.

Across every category, record the consequence: wasted preparation time,
repeated API calls, lost discovery, low confidence, wrong version, silence or
glitch risk, or unwanted playlist mutation.

## Target DJ segments

The first study is intentionally narrow enough to influence DJ Support while
including a small comparator group.

| Segment | Target | Why include it |
| --- | ---: | --- |
| Rekordbox + local files + Spotify, with at least monthly set preparation | 3–4 | Primary product workflow and highest architectural fit. |
| Beatport-heavy electronic DJ who creates charts/playlists or follows labels/artists | 2–3, overlapping above where possible | Tests discovery handoff, “what’s new,” and Snapshot use. |
| Serato, Traktor, or Engine DJ user who also manages Spotify playlists | 1–2 | Separates universal DJ preparation pain from Rekordbox-specific mechanics. |
| At least two non-developers and a mix of hobby/semi-professional/professional frequency | Across sample | Tests whether agent-native explanations work without assuming engineering knowledge and exposes differences in risk/frequency. |

Do not recruit only product enthusiasts or only the owner's friends. Direct
referrals are suitable for the first cycle; use a paid panel only if it can
screen for actual recent DJ preparation behavior. Six to eight interviews are
for qualitative pattern finding, not prevalence estimates.

## Two-week lean research plan

### Week 1 — discover the real work

**Days 1–2: prepare and pilot**

- Define the one decision: which pain deserves the next prototype.
- Prepare a fictitious 20-track “Basement Saturday” crate with examples of an
  unavailable track, wrong version, duplicate representation, manual Spotify
  removal, recent additions, overlapping crates, and two plausible discoveries.
- Pilot the guide with the owner and one DJ. Remove leading or technical wording.
- Set a private observation register with participant codes, pain episodes,
  workarounds, consequences, confidence, and quotes stripped of music metadata.

**Days 3–7: 6–8 contextual interviews, 45 minutes each**

- Ask participants to reconstruct their most recent real preparation and music-
  discovery journey.
- Observe their own tool only through participant-controlled screen sharing, or
  use the fictitious crate when they prefer not to show private material.
- Capture concrete episodes: trigger, intended outcome, tools crossed, repeated
  work, uncertainty, workaround, consequence, and how they knew they were done.
- Do not show feature concepts until the participant has described the work.
- At the end, give each participant 100 points to allocate across the pain
  episodes they would most want removed. Treat this as prioritization evidence,
  not market sizing.

At the end of week 1, stop any hypothesis that has fewer than three concrete
recent episodes across the sample or whose existing DJ software already solves
the job satisfactorily for nearly everyone observed.

### Week 2 — test the smallest competing concepts

**Days 8–9: synthesize and prototype**

- Affinity-code episodes using the taxonomy above; preserve contradictions and
  segment differences.
- Create three static, agent-style responses over the same synthetic crate:
  1. **DJ Briefing:** ready/not ready, what changed, what needs a decision, and
     cost/data boundary.
  2. **Crate X-Ray:** overlap, unique tracks, repeated provenance, and two
     explainable rediscovery candidates from the local collection.
  3. **What’s New? Radar:** new items from one explicitly chosen Beatport source
     since the last check, with no automatic publication.
- If set-flow pain survives week 1, include it only as a low-fidelity fourth
  card with visible caveats—not as working audio analysis.

**Days 10–12: concept and task evaluation, 5–6 DJs**

- Ask participants to perform realistic tasks without teaching DJ Support's
  domain terms.
- Randomize concept order. For DJ Briefing, counterbalance current detailed
  report first versus Briefing first.
- Measure correct issue identification, time to first correct action, unsafe
  assumptions, confidence, usefulness for the next real preparation, and which
  existing tool they would replace or complement.
- Ask participants to remove information until only what changes a decision
  remains; this protects against building an analytics dashboard by accumulation.

**Days 13–14: decide and record**

- Score each hypothesis with the rubric below using observed evidence.
- Produce a redacted evidence note containing counts, coded patterns,
  contradictions, decision, and limitations. Raw notes and recordings remain
  private and are not repository content.
- Choose one outcome: specify a bounded implementation ticket, revise and run
  one more focused cycle, or stop.

## Recruitment screener

Use neutral questions and reject professional-study answers that cannot supply
a recent example.

1. Are you 18 or older, and where are you based?
2. When did you last prepare music for a DJ set, recorded mix, stream, or serious
   practice session? What were you preparing for?
3. Which DJ software did you use during that preparation? Select all that apply:
   Rekordbox, Serato, Traktor, Engine DJ, other.
4. During the last three months, how often have you prepared playlists or crates?
5. Where did the music for your most recent preparation come from: owned local
   files, Beatport, another store, streaming, another person's list, or elsewhere?
6. Did Spotify play any role before, during, or after that preparation? Describe
   the role in one sentence.
7. Think of the last track that was difficult to find, organize, verify, or use.
   What happened? Do not include a track or playlist name.
8. Think of the last new track or release you wanted to remember. What did you do
   with it next?
9. Would you be comfortable sharing your screen while you control it? You may
   hide anything, use our fictional data instead, and decline recording.
10. Which description fits best: DJing is a hobby; I play occasional paid or
    public events; I play regularly; it is a primary profession.

Include participants who prepared within the last four weeks and can describe a
specific recent workflow. Do not request screenshots, XML, audio, Spotify IDs,
playlist names, or proof containing private music data.

## Interview and task guide

The moderator should use ordinary language and ask for examples before opinions.

### Recent-work interview

1. “Tell me about the last time you got music ready to play. Start wherever you
   actually started.”
2. “What told you the playlist or crate was ready?”
3. “What did you check twice? What were you worried might be wrong?”
4. “Show me how you usually do that, but hide anything you do not want to share.
   We can use the fictional library instead.”
5. “Where did you wait, repeat work, or switch tools?”
6. “Tell me about the last wrong version, missing track, broken file, or playlist
   change you found. How did you notice it? What did you do?”
7. “How did you find the newest track you used? What happened between finding it
   and knowing it belonged in this set?”
8. “Have you recently remembered a track you already owned but had forgotten?
   What brought it back?”
9. “When you choose the next track, what can software help with and what still
   requires listening?”
10. “If one part of that preparation disappeared tomorrow, which part would you
    miss least? Which part would you pay to remove?”

### Prototype tasks

Do not explain “Mirror,” “Snapshot,” “Drift,” or “Approval” before these tasks.

1. “You are playing on Saturday. Use this to decide whether the crate is ready.”
2. “Point to the first thing you would deal with. What would you do next?”
3. “A track was removed in Spotify last night. Show me how you would work out
   whether it should stay removed.”
4. “You looked at this label two weeks ago. Find only what is new and tell me
   what, if anything, has happened to Spotify.”
5. “Find one track already in the library that might fit this crate. Tell me why
   the suggestion is—or is not—credible.”
6. “Remove anything from this response that would not change a decision.”
7. “What would you expect the assistant to ask before reading your library?
   Before changing Spotify?”
8. “Would you use any of this during your next preparation? At what exact moment?”

After each concept ask: “What do you think happened already?”, “What happens if
you choose this?”, “What is missing?”, and “What would make you distrust it?”

## Observed-artifact method

Use two complementary evidence modes; never copy a participant's library into
the project.

### Participant-controlled reconstruction

The participant opens their own DJ software and controls screen sharing. Ask
them to retrace a recent preparation, point to the places where they checked,
searched, switched tools, or stopped, and narrate one real problem. They may
hide names, stop sharing, or move to the synthetic task at any time. Record only
the workflow event (for example, “checked three crates for prior use”), its
duration/consequence, and the participant's explanation. Do not capture track
lists, file paths, account data, screenshots, or exports.

### Synthetic task kit

Use invented artists, tracks, playlists, IDs, errors, and URLs. The same kit
contains enough realistic states to compare concepts without accessing
Rekordbox, audio, Beatport, or Spotify. If a participant wants to use their own
data, the prototype runs locally under their control and returns only aggregate
task measures; no raw facts are uploaded, pasted into an AI harness, or retained.

Synthetic tasks test comprehension and interaction. Participant-controlled
reconstruction supplies behavioral context. Neither synthetic personas nor
vendor feature lists count as evidence that the pain is frequent.

## Privacy and consent boundaries

These boundaries follow DJ Support's rule that source libraries, matching
knowledge, reports, playlists, and user-derived regression evidence remain
private ([ADR-0001](../adr/0001-keep-user-data-out-of-the-repository.md)).

- Obtain informed consent separately for participation, screen sharing, audio,
  and video. Notes-only is the default; declining recording does not exclude a
  participant.
- State the purpose, duration, compensation, voluntary nature, right to skip or
  stop, intended readers, retention, and deletion date before the session.
- Never request credentials, OAuth access, XML, audio, file paths, actual track
  or playlist names, Spotify/Beatport URLs or IDs, Corrections, Approved Matches,
  screenshots, or reports.
- Never connect the research prototype to a participant's Spotify, Beatport, or
  DJ-software account. Spotify Development Mode is limited to five allowlisted
  users and is explicitly intended for personal experimentation
  ([Spotify quota modes](https://developer.spotify.com/documentation/web-api/concepts/quota-modes));
  the research does not need that access.
- Keep contact/consent records separate from coded observations. Use participant
  IDs, least-access private storage, and delete raw recordings/transcripts 30
  days after the decision unless the participant agreed to a shorter period.
- Do not paste participant-controlled music data into Codex or another AI model.
  AI may help rehearse with synthetic facts and may draft coding suggestions,
  but a researcher checks every theme against the original evidence.
- Only redacted aggregate findings enter Git. A useful participant quotation is
  paraphrased if its exact wording reveals music, venue, identity, or account
  context.
- A research session never authorizes a Transfer or Spotify mutation. Under the
  agent-native contract, capability inspection, bounded planning, private-source
  authorization, Spotify-write authorization, execution/resume, and outcome are
  separate; conversation is not authority
  ([ADR-0002](../adr/0002-make-transfer-agent-native.md), [agent contract](../../djsupport/agent.py)).

## Prioritization rubric

Score 1–5 only after the study. Cite the episode or task evidence behind every
score.

| Criterion | Weight | A score of 5 means |
| --- | ---: | --- |
| Recurrence | 25% | The pain appeared in recent work for most target participants or repeatedly for the core segment. |
| Consequence | 20% | It risks an unusable set/wrong playlist or consumes substantial repeated time and confidence. |
| Evidence strength | 15% | Multiple directly observed recent episodes and prototype behaviors agree; contradictions are understood. |
| DJ Support advantage | 20% | Existing Transfer facts solve it distinctly better than the main DJ/retail tools without creating a second authority. |
| Smallest useful delivery | 10% | A useful result can ship as a bounded, read-only agent operation with little new infrastructure. |
| Privacy/API safety | 10% | It needs no broad scan, new OAuth scope, undocumented catalog dependency, or inferred user intent. |

Weighted score is a comparison aid, not a substitute for the hard safety and
evidence gates below.

## Decision thresholds

### Proceed to a bounded implementation specification

- At least **5 of 8** discovery participants describe a concrete recent episode
  in the same pain family, including at least **3 core Rekordbox users**.
- At least **4 of 8** rank it among their top two pains or allocate at least 20
  of their 100 priority points to it.
- In evaluation, at least **5 of 6** participants correctly identify the most
  important next action without prompting, and the concept materially improves
  either time-to-correct-action or correct issue identification versus the
  current report.
- **All** participants understand whether the concept has read private data and
  whether Spotify has changed. Any inferred mutation, Approval, or automatic
  repair is a blocking failure.
- At least **4 of 6** can name the exact moment in their next preparation when
  they would use it and do not prefer an existing tool for the same job.

### Revise and retest

- The pain is strong but terminology, information order, or the boundary between
  “fact” and “suggestion” causes errors.
- Core and comparator segments diverge, or the useful concept is narrower than
  the original hypothesis.
- Participants value the output but cannot identify a recurring use moment.

### Stop or defer

- Fewer than three recent concrete episodes appear.
- The job is already solved satisfactorily in participants' DJ software.
- Value depends on background monitoring, broad private-library scans, opaque
  taste inference, or Spotify endpoints unavailable in Development Mode.
- A safe read-only prototype cannot prevent users from assuming automatic
  publication, Approval, restoration, or set-quality authority.

The thresholds are explicit decision rules for this small cycle; they are not
population estimates or statistical significance claims.

## Ranked product hypotheses before primary research

Scores are provisional judgments using repository and first-party category
evidence. Primary research must replace them.

| Rank | Hypothesis | Recurrence | Consequence | Evidence | Advantage | Small delivery | Safety | Weighted |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | **DJ Briefing + “needs me” queue** | 5 | 5 | 4 | 5 | 5 | 5 | **4.85** |
| 2 | **Crate X-Ray**: overlap, unique tracks, stale/near-duplicate crates, provenance patterns | 4 | 3 | 3 | 4 | 4 | 5 | **3.75** |
| 3 | **Manual What’s New? Radar** for an explicitly chosen Beatport label/chart or retained source | 4 | 3 | 3 | 4 | 3 | 3 | **3.45** |
| 4 | **Explainable local rediscovery**: tracks already owned that fit a selected crate by visible metadata/relationships | 3 | 3 | 3 | 4 | 3 | 5 | **3.40** |
| 5 | **Set Flow lens**: BPM/key/energy/order warnings to audition, never automatic ordering | 3 | 4 | 3 | 2 | 2 | 4 | **3.00** |
| 6 | **Private discovery inbox** for explicitly captured pages or links | 3 | 2 | 3 | 3 | 3 | 4 | **2.90** |

The ranking deliberately separates **rediscovery** (finding useful music already
owned) from **catalog discovery** (finding new releases). They have different
data, competitors, and user moments.

## Top recommendation: DJ Briefing

### Why this should be tested first

DJ Briefing turns DJ Support's strongest existing facts into the answer a DJ is
likely trying to obtain: “Can I rely on this, and what deserves my attention?”
It does not ask DJ Support to out-analyze Rekordbox or Mixed In Key, or
out-recommend Beatport. It reduces the current gap between a comprehensive
Transfer report and a small number of human decisions.

It also fits the product's chosen operating surface. AI harnesses are first-
class clients, but they receive versioned, redacted facts and no implied
authority ([ADR-0002](../adr/0002-make-transfer-agent-native.md)). A DJ should be
able to ask:

- “Brief this crate.”
- “What changed since I last trusted it?”
- “Only show what needs me.”
- “What can I safely do next?”

The answer should use plain words first and canonical terms only when they help
the decision.

### Smallest prototype

Build no persistent UI and no new analysis pipeline. Render one static or local
agent response from a synthetic `BatchPlan` and `PlaylistReport`:

1. **Verdict:** Ready, needs attention, or incomplete—never an opaque score.
2. **What changed:** additions/removals, Spotify edits, availability, or paused
   work, with source change separated from Spotify change.
3. **What needs you:** a maximum of five ordered decisions with the exact reason
   and permitted choices.
4. **Cost and privacy:** expected Spotify lookups; selected private source; no
   mutation in Preview.
5. **Next action:** inspect, supply a Correction, choose restore/revoke, resume,
   or do nothing. Never preselect a destructive choice.

Prototype only three states: clean/ready, five mixed exceptions, and paused
partial work. Use invented data.

### Evaluation

Run a counterbalanced within-participant comparison:

- Half see the existing detailed report then DJ Briefing; half see the reverse.
- Ask each to decide whether the crate is ready, identify the first action,
  explain what changed, and state whether Spotify has already been modified.
- Measure time, correct blockers found, false blockers, unsafe expectations,
  confidence, and what information they remove.
- Proceed only under the decision thresholds above. If Briefing merely hides
  facts or creates false confidence, keep the detailed report and stop.

An accepted prototype should become one bounded issue for a Transfer-owned,
privacy-safe briefing fact model and thin agent/CLI rendering—not a dashboard
epic.

## Rejected or deferred ideas

| Idea | Disposition | Reason |
| --- | --- | --- |
| Generic AI recommendation engine | Reject now | Beatport and Rekordbox already own richer catalog/behavior signals, while Spotify restricts the relevant developer endpoints. An opaque model would be difficult to validate and could misuse Spotify content. |
| Full key/BPM/energy/cue analyzer | Reject now | Rekordbox, Serato, Traktor, and Mixed In Key already specialize here. DJ Support should first prove a cross-system gap rather than clone mature analysis. |
| Automatic set ordering or “best transition” | Reject | Key, BPM, and energy narrow choices but do not know crowd, intent, phrasing, or taste. Even Mixed In Key instructs the DJ to listen. Suggestions may support auditioning; the software must not claim musical authority. |
| Set Flow production feature | Defer to prototype | Potentially valuable, but DJ Support's current Rekordbox model does not retain BPM/key/energy facts and richer analysis raises scope and trust questions. Require observed unmet need first. |
| Background label/artist monitoring | Defer | Adds schedules, notifications, retained subscriptions, and dependence on Beatport's undocumented page shape. Begin with explicit “check now” only if discovery research supports it. |
| Large analytics dashboard | Reject now | A dashboard risks vanity metrics and duplicates an agent-native surface before the recurring decisions are known. Test the smallest briefing and X-Ray outputs first. |
| Mobile DJ Support application | Defer | Beatport already supports mobile discovery and cross-device playlists; the current evidence does not show where that handoff fails often enough to justify a new client ([mobile research](2026-08-01-mobile-discovery-and-capture.md)). |
| Chrome-owned matching or publication | Reject | The existing Chrome project is useful interaction evidence, but a second matcher/cache/publication authority would diverge from Transfer ([Chrome workflow research](2026-08-01-chrome-discovery-workflow.md)). |
| Broad whole-library scan by default | Reject | It conflicts with explicit bounded Batch selection, increases private-data and compute exposure, and repeats the API-cost problem DJ Support was designed to control. |
| File relocation or metadata repair suite | Defer outside the core | Main DJ applications already own file paths, corruption and analysis state. DJ Support may report a cross-system symptom, but must not modify files or tags without a separately validated capability. |

## Final recommendation

Authorize the two-week research cycle, not a feature build. Test **DJ Briefing**
as the leading hypothesis against **Crate X-Ray / local rediscovery** and a
manual **What’s New? Radar**. The smallest credible product direction is an
agent-native, read-only answer that helps the DJ finish preparation and exposes
only decisions requiring human judgment. Discovery and set-flow work should
enter the roadmap only when real recent workflows show a gap that Rekordbox,
Beatport, Mixed In Key, Serato, Traktor, or Engine DJ do not already solve well.
