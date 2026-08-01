# Mirror and Drift comprehension study

This research-only kit tests one question: can a DJ understand an unchanged or
changed Mirror and inspect it without expecting an automatic repair? Open
`index.html` directly in a browser. It uses fictitious data, makes no network
requests, and connects to no music service.

Run a two-person pilot, revise confusing instructions, and then run five
30-minute individual sessions. Do not teach DJ Support terminology before the
tasks. Do not collect real playlists, screenshots, XML, audio, URLs, account
identifiers, Corrections, or reports.

## Participant screener

Include adults who used Rekordbox to prepare music and Spotify playlists within
the last three months. Include at least two people who are not developers. Ask
only about recent tool use and general frequency; never request private-library
proof. Exclude anyone who helped design this prototype.

## Moderator script

1. Explain that the screens contain invented data and that the product is not
   connected to Spotify. Do not record by default. Recording requires separate
   project approval and participant consent; private written notes require
   participant consent.
2. Share the prototype at the first screen. Ask the participant to think aloud.
3. Ask: “What will happen if you continue?” Do not correct their answer.
4. At the unchanged result ask: “What does this prove? Could an individual
   track still have a problem?”
5. Continue to the changed example. Ask what happened, who or what might have
   caused it, and what “Inspect differences” will do.
6. At the final choice ask what each action will do and whether anything has
   already changed in Spotify.
7. Close the prototype. Ask for unaided meanings of Preview, Mirror, Playlist
   Drift, and Approval. Ask what felt unsafe, unclear, or private.

Avoid leading questions and teaching. Record what the participant did and said,
including contradictions, before interpreting it.

## Observation template

Use a private copy per participant and retain only the redacted aggregate note
in Git.

| Observation | Evidence |
| --- | --- |
| Pseudonymous participant ID | |
| Relevant recent workflow | |
| Task outcome | |
| Preview understood as non-mutating: yes/no | |
| Inspection understood as non-mutating: yes/no | |
| Unchanged head distinguished from item health: yes/no | |
| Source-versus-Spotify attribution errors | |
| Unsafe action expected or attempted | |
| Time to explain each result | |
| Confidence, 1–5 | |
| Terminology misinterpretation | |
| Privacy concern | |
| Contradiction or minority case | |

## Pilot checklist

- [ ] Two people can open and navigate every screen using keyboard only.
- [ ] The task prompts do not reveal the intended answer.
- [ ] The moderator records behavior before interpretation.
- [ ] No real account or music-library data appears or is requested.
- [ ] Revise only instructions or presentation; do not change the decision gate.

## Five-participant checklist

- [ ] Five eligible DJs completed separate sessions.
- [ ] At least two participants are not developers.
- [ ] Note-taking consent was explicit; any recording had separate project
      approval and participant consent.
- [ ] Every participant saw both unchanged and changed cases.
- [ ] Contradictions and unsafe expectations were retained.
- [ ] Raw notes, contact data, consent, and recordings remain outside Git.

## Redacted decision note

Copy this section into a dated Markdown file under `docs/research/`. Include no
names, account data, playlists, recordings, or identifying quotations.

```markdown
# Mirror and Drift comprehension decision

**Decision:** Proceed / Revise and retest / Stop
**Study dates:**
**Participants:** 5 eligible DJs; non-developers: N

## Gate

- All 5/5 understand that Preview and inspection make no Spotify changes: PASS/FAIL
- At least 4/5 distinguish an unchanged head from proof every item is healthy: PASS/FAIL

## Observed behavior

Aggregate outcomes and short redacted evidence, including contradictions.

## Decision and roadmap effect

State proceed, revise and retest, or stop. Link the affected 0.5/0.6 roadmap
gate and list the smallest resulting change. Do not infer beyond the evidence.
```
