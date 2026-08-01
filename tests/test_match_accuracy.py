"""Run local regression knowledge against the live matcher and report accuracy.

Usage:
    python -m tests.test_match_accuracy [--knowledge-path PATH]

Requires SPOTIPY_CLIENT_ID, SPOTIPY_CLIENT_SECRET, SPOTIPY_REDIRECT_URI
in .env (same as normal djsupport usage). The input stays in versioned local
application storage and is never loaded from a repository fixture.
"""

import argparse
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from djsupport.matcher import match_track
from djsupport.rekordbox import Track
from djsupport.spotify import get_client
from djsupport.regression import load_local_regressions
from djsupport.transfer import default_matching_knowledge_path


def run_accuracy_test(knowledge_path: Path | None = None):
    knowledge_path = knowledge_path or default_matching_knowledge_path()
    regression_cases = load_local_regressions(knowledge_path)
    if not regression_cases:
        raise ValueError(
            f"No local regression knowledge found at {knowledge_path}. "
            "Approve a Correction before running live accuracy."
        )
    print(f"Loaded {len(regression_cases)} regression tracks\n")

    sp = get_client()

    correct = 0
    wrong = 0
    missed = 0
    results = []

    for row in regression_cases:
        duration = int(row.get("duration", 0) or 0)
        track = Track(
            track_id="test",
            name=row["song"],
            artist=row["artist"],
            album="",
            remixer="",
            label="",
            genre="",
            date_added="",
            duration=duration,
        )

        result = match_track(sp, track, threshold=80)
        expected_uri = row["expected_uri"]

        if result is None:
            status = "MISS"
            missed += 1
            results.append({
                "track": track,
                "status": status,
                "expected_uri": expected_uri,
                "got_uri": None,
                "score": None,
                "match_type": None,
                "got_name": None,
                "got_artist": None,
            })
        elif result["uri"] == expected_uri:
            status = "OK"
            correct += 1
            results.append({
                "track": track,
                "status": status,
                "expected_uri": expected_uri,
                "got_uri": result["uri"],
                "score": result["score"],
                "match_type": result.get("match_type"),
                "got_name": result["name"],
                "got_artist": result["artist"],
                "got_duration_ms": result.get("duration_ms"),
            })
        else:
            status = "WRONG"
            wrong += 1
            results.append({
                "track": track,
                "status": status,
                "expected_uri": expected_uri,
                "got_uri": result["uri"],
                "score": result["score"],
                "match_type": result.get("match_type"),
                "got_name": result["name"],
                "got_artist": result["artist"],
                "got_duration_ms": result.get("duration_ms"),
            })

    # Print results
    print("=" * 80)
    print(f"{'STATUS':<7} {'SCORE':>5} {'TYPE':<10} {'TRACK'}")
    print("-" * 80)

    for r in results:
        track = r["track"]
        score_str = f"{r['score']:.0f}" if r["score"] is not None else "—"
        type_str = r["match_type"] or "—"
        print(f"{r['status']:<7} {score_str:>5} {type_str:<10} {track.artist} - {track.name}")
        if r["status"] == "WRONG":
            print(f"        Expected: {r['expected_uri']}")
            print(f"        Got:      {r['got_uri']}")
            print(f"                  {r['got_artist']} - {r['got_name']}")
            if r.get("got_duration_ms"):
                got_s = r["got_duration_ms"] / 1000
                print(f"                  Duration: {int(got_s//60)}:{int(got_s%60):02d}")
            track = r["track"]
            if track.duration > 0:
                print(f"        Rekordbox duration: {track.duration//60}:{track.duration%60:02d}")
        if r["status"] == "MISS":
            print(f"        Expected: {r['expected_uri']}")

    # Summary
    total = len(regression_cases)
    print()
    print("=" * 80)
    print(f"TOTAL: {total}  |  OK: {correct} ({correct/total*100:.0f}%)  |  WRONG: {wrong}  |  MISS: {missed}")
    print("=" * 80)

    # Research: check duration_ms from Spotify for all expected tracks
    print("\n\nDURATION RESEARCH — Spotify duration_ms for expected tracks:")
    print("-" * 80)
    track_ids = [row["expected_uri"].split(":")[-1] for row in regression_cases]
    # Spotify API allows up to 50 tracks per call
    tracks_info = sp.tracks(track_ids)
    for i, item in enumerate(tracks_info["tracks"]):
        if item:
            duration_s = item["duration_ms"] / 1000
            minutes = int(duration_s // 60)
            seconds = int(duration_s % 60)
            print(f"  {regression_cases[i]['artist']:<45} {minutes}:{seconds:02d}  ({item['duration_ms']}ms)")
        else:
            print(f"  {regression_cases[i]['artist']:<45} NOT FOUND")

    return correct, wrong, missed


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--knowledge-path", type=Path, default=default_matching_knowledge_path(),
        help="Versioned local matching-knowledge file (never a repository fixture).",
    )
    run_accuracy_test(parser.parse_args().knowledge_path)
