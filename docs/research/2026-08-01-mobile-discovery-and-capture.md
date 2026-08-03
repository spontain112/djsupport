# Mobile discovery and capture: evidence for the DJ Support roadmap

**Date:** 2026-08-01

**Status:** Planning research only. No production code, live account access, private
music data, or playlist mutation was involved.

## Answer in brief

The available first-party evidence does **not** support the claim that DJs seldom
search Beatport on phones. Beatport deliberately offers mobile search, discovery,
artist/label following, Track ID, and playlist management. What the evidence does
support is a mobile-to-later pattern: capture tracks into a playlist while away
from the desk, then continue in Beatport, DJ software, or hardware later.

For DJ Support, the defensible roadmap choice is therefore personal and
evidence-gated rather than a market generalization:

- lead with laptop browsing and immediate conversion because that is the owner's
  stated behavior and already has a working Chrome prototype;
- preserve a separate future mobile intent—**remember this for later**—behind the
  same narrow intake contract;
- do not build a mobile product until a small diary or usage sample shows where
  Beatport's own playlist handoff fails the owner's Spotify workflow.

## What first-party sources establish

1. **Beatport intends mobile to support discovery, not merely passive playback.**
   Beatport describes its app as optimized for mobile music search and says it
   supports discovering music, creating playlists, and following genres, artists,
   and labels through My Beatport
   ([Beatport Mobile v1.2](https://www.beatportal.com/articles/201000-introducing-beatport-mobile-v1-2-now-free-for-all-users)).

2. **The official cross-device journey explicitly includes “collect now, continue
   later.”** The current App Store listing says users can discover music and add
   tracks to playlists on the go, then access those finds on Beatport.com to check
   out and download them
   ([Beatport on the App Store](https://apps.apple.com/us/app/beatport-music-for-djs-app/id1543739988)).
   Beatport's streaming page likewise presents mobile as a place to build
   playlists, discover music, add tracks, and identify heard tracks with Track ID
   ([Beatport Streaming](https://stream.beatport.com/)).

3. **Beatport presents mobile playlists as portable preparation artifacts.** Its
   official getting-started guidance says playlists created on mobile are
   immediately available in Beatport DJ, the store, and integrated DJ software
   and hardware
   ([Getting Started with Beatport Mobile](https://www.beatportal.com/videos/92586-getting-started-with-beatport-mobile)).
   A first-party artist demonstration describes listening on a phone while on the
   road, putting a track in a playlist, and later arriving and playing it
   ([Eats Everything explores Beatport Streaming](https://www.beatportal.com/videos/831864-eats-everything-explores-beatport-streaming-cdj-3000s)).

4. **There is meaningful distribution, but no public behavioral split.** The
   official Google Play listing reports 500K+ installs and advertises on-the-go
   discovery and playlist building. Install count does not tell us how often DJs
   search, merely capture, or complete downstream playlist work on mobile
   ([Beatport on Google Play](https://play.google.com/store/apps/details?id=com.beatport.mobile)).

5. **The existing Chrome extension is inherently laptop-first.** Google states
   that Chrome extensions can only be used on computers and cannot be installed
   on mobile devices
   ([Chrome Web Store Help](https://support.google.com/chrome_webstore/answer/1698338)).
   A future iPhone doorway is technically possible as a Safari Web Extension, but
   it would require an iOS containing app, signing, and App Store distribution; it
   is not a free deployment of the current Chrome artifact
   ([Apple Safari Web Extensions](https://developer.apple.com/documentation/safariservices/distributing-your-safari-web-extension)).

## Evidence, inference, and unknowns

### Evidence

- Beatport provides and promotes mobile search, discovery, following, Track ID,
  and playlist management.
- Beatport supports handing a mobile-created playlist into later desktop, store,
  software, and hardware contexts.
- The existing DJ Support Chrome doorway is a computer surface, not a mobile one.

### Reasonable inference

- “Remember this for later” is a credible mobile intent because Beatport itself
  has designed around it and published a concrete artist workflow exhibiting it.
- A DJ Support mobile inbox could be useful specifically when the desired final
  destination is Spotify or when the source is outside Beatport—not because
  mobile discovery is rare.
- Laptop-first is the lowest-risk next slice for this single-user product because
  the owner confirmed immediate conversion as the browser default and a working
  prototype already exists.

### Unknown

- No reviewed first-party source provides the proportion of Beatport discovery,
  search, or playlist activity performed on mobile versus desktop.
- There is no evidence here about how often mobile users want Spotify conversion
  immediately rather than later.
- We do not yet know whether the owner's easiest mobile capture is a shared URL,
  a Beatport playlist, a system share-sheet action, or no DJ Support action at all.
- We do not know whether mobile capture happens often enough to justify a new
  client and its authentication, synchronization, privacy, and packaging costs.

## Roadmap implications

### Leading path: laptop immediate conversion

Use the current Chrome interaction as the first doorway: on a supported desktop
Beatport page, the ordinary action means “make this Spotify playlist now.” Chrome
captures context and intent; durable `Transfer` owns source facts, matching,
review, publication, recovery, and retained state. This continues the evidence
already recorded in [Chrome discovery-to-Spotify workflow](2026-08-01-chrome-discovery-workflow.md)
and [Simplest Chrome-to-DJ Support product boundary](2026-08-01-simplest-chrome-gui-boundary.md).

### Later option: mobile capture inbox

Treat mobile as a different job: “remember this source or selection for me.” A
future adapter could submit a URL or explicit source reference to a private inbox,
without starting Spotify mutation or inferring Snapshot, Mirror, following, or
Approval. At the laptop, the owner would decide whether to start a Transfer.

Before making that a release commitment, collect a lightweight personal diary:
for each phone discovery, note the source, what was worth keeping, what action was
taken, and where the owner expected it to appear later. This can reveal whether
DJ Support needs a mobile intake at all, or whether importing/reusing a Beatport
playlist is the simpler seam. No private diary evidence belongs in Git.

## Wayfinder recommendation

Keep both branches on the decision frontier, but put laptop immediate conversion
first and make mobile capture conditional on personal evidence. Do not justify
that order by claiming DJs rarely use Beatport on mobile, and do not revive the
dropped standalone Mirror/Drift UX study or PR #76.

The next plain-language question should be:

> The next time you find music on your phone, what would be the least-effort way
> to leave it for DJ Support: share the page, add it to a named Beatport playlist,
> or simply copy the link?
