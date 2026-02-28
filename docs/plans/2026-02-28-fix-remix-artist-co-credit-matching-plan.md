---
title: Remix Artist Co-Credit Matching
type: fix
status: pending
date: 2026-02-28
---

# Remix Artist Co-Credit Matching

## Problem

Spotify frequently lists remix artists as co-credits on tracks, while Beatport only lists the original artist. This causes artist score mismatches that drop otherwise perfect matches below threshold.

**Example:**
- Beatport: `Balad - The Hours (Allies for Everyone Remix)`
- Spotify: `Balad, Allies for Everyone - The Hours - Allies for Everyone Remix`
- Artist score: "balad" vs "balad, allies for everyone" = 32/100
- Title score (stripped): 100/100
- Final: 72.9 — below threshold 80

## Scope

This affects any track where:
- The remix/edit artist is credited as a co-artist on Spotify but not on Beatport
- The original artist alone doesn't score high enough against the co-credited Spotify artist string

Common in electronic music where remixers are prominent (e.g., "Track - DJ Name Remix" with DJ Name as co-artist).

## Proposed Approach

When a remix descriptor is detected in the title (e.g., "Allies for Everyone Remix"), extract the remixer name and include it in the artist comparison. If the Spotify artist string contains both the original artist and the remixer name, boost the artist score.

Alternatively, when `stripped_title_score >= 95` and the original artist is a substring match of the Spotify artist, relax the artist threshold for version-fallback matches.

## Impact

Would improve match rates for remix-heavy labels and Beatport imports. The Blindfold Recordings test case has 1 track (0.7%) affected; remix-focused labels would see larger improvements.
