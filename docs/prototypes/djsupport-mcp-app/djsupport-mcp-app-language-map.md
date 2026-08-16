---
classification: concept
artifact: MCP App prototype language and real-estate map
---

# DJ Support MCP App: user language and screen density

This prototype keeps DJ Support's canonical domain model intact while translating it at the interface boundary. The UI describes the user's goal, the visible effect, and whether Spotify will change. Technical terms remain available to implementation code, logs, diagnostics, and durable records; users should not need to learn them to complete a playlist.

## Human journey

Choose a Rekordbox file → choose one playlist → find Spotify matches → review uncertain songs → create a private Spotify playlist → optionally remember confirmed matches.

## Interface language map

| Canonical/domain term | User-facing wording |
| --- | --- |
| Rekordbox library / XML export | Rekordbox playlists / Rekordbox playlist file |
| Transfer | Copy or update a playlist |
| Preview | Check Spotify matches |
| Run Preview | Find matches |
| Qualification | Review uncertain songs |
| Qualification Draft | Your match choices |
| Proposal / candidate | Possible Spotify match |
| Strong proposal | Confident match |
| Selected source | Your Rekordbox version |
| Occurrence | Playlist entry |
| Represented | Matched and included |
| Unresolved | No match chosen yet / not found |
| Match collision | Possible duplicate |
| Apply draft | Send these choices to Spotify |
| Spotify write / playlist mutation | Change Spotify / playlist change |
| Authorize and apply | Create private playlist / update playlist |
| Approval | Remember these matches |
| Durable matching authority | Remembered choices for next time |
| Mapping | Song match |
| Source order retained | Same order as Rekordbox |

Avoid `Publish` in this flow because the resulting Spotify playlist is private. Avoid `Preview` because DJs can reasonably read it as audio playback. Avoid `queue` because it suggests a playback queue. Avoid `Approval` for the final memory step because the Spotify change has already happened.

## Screen real-estate contract

| Screen | Surface | Must earn space | Removed or deferred |
| --- | --- | --- | --- |
| First run | Compact inline card | File chooser, why the file is needed, what happens next, Spotify-unchanged reassurance, export help | Fullscreen onboarding, setup expansion, unverified privacy guarantees |
| Preparing playlists | Compact inline card | Progress, current plain-language status, safe-to-close note | Technical parsing checklist |
| Choose playlist | Medium browser | Playlist names, track counts, one selection, one CTA | Result-type choices and privacy exposition; expand only for a genuinely long library |
| Check matches | Compact confirmation | Playlist, song count, Spotify-unchanged promise | Operation taxonomy and audition settings |
| Match results | Compact summary | Matched / needs choice / not found, review CTA | Internal reason breakdown |
| Review uncertain songs | Large comparison panel | Progress, source version, Spotify version, play/open controls, four plain choices | Full-viewport chrome, domain-state banner, and authority language |
| Choose Spotify version | Wide inline comparison | Version, release, duration, listen/select controls | Queue management and decorative art |
| Create Spotify playlist | Compact consequential confirmation | Exact playlist name, privacy, additions, omissions, order, one-time permission | Generic authorization language |
| Remember matches | Compact optional follow-up | Spotify already changed, open Spotify, benefit of remembering | Manifest and durability terminology |
| Complete | Compact result | Playlist name, matched/missing counts, Spotify link, next action | Mirror/Transfer terminology |

## Consequential action rule

Before a button can change Spotify, the same compact surface must define a result the user can verify afterwards:

- the exact playlist name;
- whether it will be new or existing;
- its privacy state;
- the exact number of reviewed songs included, with no implied extras;
- which source songs are left out and why;
- the resulting song order;
- whether permission is one-time; and
- a button label that names the result, such as `Create this 32-song playlist`.

Use concrete outcome badges such as `PRIVATE`, `32 SONGS`, and `SAME ORDER`. Avoid abstract process badges such as `WILL HAPPEN` and `WON'T HAPPEN`.

The following step may remember confirmed matches, but it must explicitly say that Spotify will not change again.

## Visual hierarchy contract

The prototype uses color sparingly and semantically. These are concept colors, not production brand tokens.

- Dark: the single next action on the surface.
- Green: achieved, selected, ready, or successfully verified state.
- Amber: information that needs the user's attention or choice; it does not mean destructive or dangerous.
- Grey: explanation, metadata, and secondary actions.

Numbers carry more visual weight than their labels when they describe an outcome. For example, completion shows `32` prominently with `matched` as supporting text. The results screen emphasizes the songs needing a choice over the already matched total because that is the user's next job.

The current surface sizes follow the amount of work required:

| Surface | Prototype size |
| --- | --- |
| Choose file | 720 × 440 |
| Prepare playlists | 720 × 440 |
| Choose playlist | 920 × 620 |
| Confirm match check | 720 × 360 |
| Match results | 720 × 330 |
| Review uncertain songs | 1040 × 580 |
| Compare Spotify versions | 920 × 480 |
| Confirm Spotify playlist | 720 × 480 |
| Remember matches | 720 × 470 |
| Playlist ready | 720 × 380 |

## Trust-copy rule

Confidence comes from naming observable behavior, not from broad privacy claims. Until the MCP App's upload and model-context boundaries are verified in the implementation, the interface must not claim that ChatGPT cannot see the file or that the file never leaves the device.

The first-run screen therefore says what the file is used for—finding playlist names and track details—what happens next—the user chooses one playlist—and what does not happen yet—no Spotify playlist is created or changed.
