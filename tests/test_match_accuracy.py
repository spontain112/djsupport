"""Run match_test_data.csv against the live matcher and report accuracy.

Usage:
    python -m tests.test_match_accuracy

Requires SPOTIPY_CLIENT_ID, SPOTIPY_CLIENT_SECRET, SPOTIPY_REDIRECT_URI
in .env (same as normal djsupport usage).
"""

import csv
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from djsupport.matcher import match_track, _score_components, _classify_version_match
from djsupport.rekordbox import Track
from djsupport.spotify import get_client


def _uri_from_url(url: str) -> str:
    """Convert Spotify URL to URI. e.g. https://open.spotify.com/track/ABC -> spotify:track:ABC"""
    track_id = url.rstrip("/").split("/")[-1].split("?")[0]
    return f"spotify:track:{track_id}"


def load_test_data(path: Path) -> list[dict]:
    """Load tab-separated test data CSV."""
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            url = row.get("Spotify URL", "").strip()
            if url:
                rows.append({
                    "artist": row["Artist Name"].strip(),
                    "song": row["Song Name"].strip(),
                    "expected_uri": _uri_from_url(url),
                    "expected_url": url,
                })
    return rows


def run_accuracy_test():
    csv_path = Path(__file__).parent / "fixtures" / "match_test_data.csv"
    test_data = load_test_data(csv_path)
    print(f"Loaded {len(test_data)} test tracks\n")

    sp = get_client()

    correct = 0
    wrong = 0
    missed = 0
    results = []

    for row in test_data:
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
    total = len(test_data)
    print()
    print("=" * 80)
    print(f"TOTAL: {total}  |  OK: {correct} ({correct/total*100:.0f}%)  |  WRONG: {wrong}  |  MISS: {missed}")
    print("=" * 80)

    # Research: check duration_ms from Spotify for all expected tracks
    print("\n\nDURATION RESEARCH — Spotify duration_ms for expected tracks:")
    print("-" * 80)
    track_ids = [row["expected_uri"].split(":")[-1] for row in test_data]
    # Spotify API allows up to 50 tracks per call
    tracks_info = sp.tracks(track_ids)
    for i, item in enumerate(tracks_info["tracks"]):
        if item:
            duration_s = item["duration_ms"] / 1000
            minutes = int(duration_s // 60)
            seconds = int(duration_s % 60)
            print(f"  {test_data[i]['artist']:<45} {minutes}:{seconds:02d}  ({item['duration_ms']}ms)")
        else:
            print(f"  {test_data[i]['artist']:<45} NOT FOUND")

    return correct, wrong, missed


if __name__ == "__main__":
    run_accuracy_test()
