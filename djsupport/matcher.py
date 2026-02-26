"""Fuzzy matching between Rekordbox tracks and Spotify search results."""

import re
import unicodedata

from rapidfuzz import fuzz

from djsupport.rekordbox import Track

EARLY_EXIT_THRESHOLD = 95  # Skip remaining strategies when Strategy 1 finds a high-confidence exact match
from djsupport.spotify import search_track


def _normalize(text: str) -> str:
    """Lowercase, strip whitespace, and remove common noise."""
    # Fold accents/diacritics so e.g. "För" and "For" compare equally.
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().strip()
    # Remove country tags like (IL), (UA), (UK)
    text = re.sub(r"\s*\([A-Z]{2,3}\)", "", text, flags=re.IGNORECASE)
    # Remove bracket tags like [Permanent Vacation], [Label Name]
    text = re.sub(r"\s*\[.*?\]", "", text)
    # Replace "x" as artist separator with comma
    text = re.sub(r"\s+x\s+", ", ", text)
    # Remove "feat." / "ft." and everything after within the string
    text = re.sub(r"\b(feat\.?|ft\.?)\s+.*", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _strip_mix_info(title: str) -> str:
    """Remove parenthetical remix/mix info and bracket tags from a title.

    e.g. 'Vultora (Original Mix)' -> 'Vultora'
         'Night Drive (Extended)' -> 'Night Drive'
         'Today [Permanent Vacation]' -> 'Today'
         'What Is Real - Deep in the Playa Mix' -> 'What Is Real'
    """
    title = re.sub(r"\s*\(.*?(mix|remix|edit|version|dub|extended|radio|instrumental|short)\)", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s*\[.*?\]", "", title)
    # Strip trailing hyphen descriptors like " - XYZ Remix" used by Spotify
    title = re.sub(r"\s+-\s+[^-]*\b(mix|remix|edit|version|dub)\b.*$", "", title, flags=re.IGNORECASE)
    return title.strip()


def _extract_mix_descriptor(title: str) -> str | None:
    """Extract a remix/mix/edit descriptor from parentheses or brackets."""
    descriptors = _extract_mix_descriptors(title)
    return descriptors[0] if descriptors else None


def _extract_mix_descriptors(title: str) -> list[str]:
    """Extract all version-like descriptors (mix/remix/edit/etc.) from a title."""
    descriptors: list[str] = []
    candidates = re.findall(r"[\(\[]([^\)\]]+)[\)\]]", title)
    for c in candidates:
        if re.search(r"\b(mix|remix|edit|version|dub|extended|radio|instrumental|short)\b", c, flags=re.IGNORECASE):
            descriptors.append(_normalize(c))
    # Spotify often uses "Track Name - XYZ Remix" instead of parentheses
    hyphen_match = re.search(
        r"\s+-\s+([^-]*\b(mix|remix|edit|version|dub)\b.*)$",
        title,
        flags=re.IGNORECASE,
    )
    if hyphen_match:
        descriptors.append(_normalize(hyphen_match.group(1)))
    # Preserve order, remove duplicates
    seen: set[str] = set()
    unique: list[str] = []
    for d in descriptors:
        if d not in seen:
            seen.add(d)
            unique.append(d)
    return unique


def _is_named_variant(mix_descriptor: str | None) -> bool:
    """True for non-original variants like remixes/edits/dubs."""
    if not mix_descriptor:
        return False
    # "Original Mix" is often omitted on Spotify; treat it as the default version.
    return "original" not in mix_descriptor


def _score_components(track: Track, result: dict) -> dict[str, float]:
    """Return matching score components for a Rekordbox/Spotify pair."""
    artist_score = fuzz.token_sort_ratio(
        _normalize(track.artist), _normalize(result["artist"])
    )
    norm_title = _normalize(track.name)
    norm_result = _normalize(result["name"])
    raw_title_score = fuzz.token_sort_ratio(norm_title, norm_result)
    stripped_title_score = fuzz.token_sort_ratio(
        _normalize(_strip_mix_info(track.name)),
        _normalize(_strip_mix_info(result["name"])),
    )
    return {
        "artist_score": artist_score,
        "raw_title_score": raw_title_score,
        "stripped_title_score": stripped_title_score,
    }


def _classify_version_match(track: Track, result: dict) -> str:
    """Classify version agreement as exact or fallback_version."""
    track_mix = _extract_mix_descriptor(track.name)
    result_mix = _extract_mix_descriptor(result["name"])

    track_named_variant = _is_named_variant(track_mix)
    result_named_variant = _is_named_variant(result_mix)

    if track_named_variant:
        if result_mix is None:
            return "fallback_version"
        if fuzz.token_sort_ratio(track_mix or "", result_mix or "") < 80:
            return "fallback_version"
        # If the result includes additional version tags beyond the requested one
        # (e.g. "... (Deep in the Playa Mix) - Video Edit"), classify as fallback.
        result_descriptors = _extract_mix_descriptors(result["name"])
        for desc in result_descriptors[1:]:
            if fuzz.token_sort_ratio(track_mix or "", desc) < 80:
                return "fallback_version"
        if track.remixer:
            remixer = _normalize(track.remixer)
            result_text = _normalize(f'{result["artist"]} {result["name"]}')
            if remixer and remixer not in result_text:
                return "fallback_version"
        return "exact"

    # Track appears to be original/default version. Named remix/edit on Spotify is a fallback.
    if result_named_variant:
        return "fallback_version"
    return "exact"


def _duration_penalty(track_duration_s: int, result_duration_ms: int) -> float:
    """Penalty for duration mismatch between source and Spotify tracks.

    Returns 0 when durations are unavailable or within 30s of each other.
    Beyond 30s, applies 5 points per additional 30s, capped at 15.

    The cap is intentionally low so that duration alone cannot reject an
    otherwise strong artist+title match — common when Beatport lists extended
    DJ versions and Spotify only has shorter radio edits.
    """
    if track_duration_s <= 0 or result_duration_ms <= 0:
        return 0.0
    result_duration_s = result_duration_ms / 1000
    diff = abs(track_duration_s - result_duration_s)
    if diff <= 30:
        return 0.0
    excess = diff - 30
    return min(15.0, (excess / 30) * 5)


def _score_result(
    track: Track, result: dict, components: dict[str, float] | None = None,
) -> float:
    """Score a Spotify result against a Rekordbox track (0-100)."""
    if components is None:
        components = _score_components(track, result)
    artist_score = components["artist_score"]
    title_score = components["raw_title_score"]
    stripped_score = components["stripped_title_score"]
    title_score = max(title_score, stripped_score)

    # Penalize remix/edit variant mismatches. Base-title matching alone can
    # incorrectly treat different versions of the same track as exact matches.
    penalty = 0.0
    if _classify_version_match(track, result) == "fallback_version":
        # Looking for an unavailable/mismatched version. Keep candidate visible,
        # but reduce score so exact-version matches win when they exist.
        penalty += 15.0

    # Penalize duration mismatches (disambiguates original vs extended/radio edits)
    penalty += _duration_penalty(track.duration, result.get("duration_ms", 0))

    # Weight title slightly more since artist names vary in format
    score = artist_score * 0.4 + title_score * 0.6 - penalty
    return max(0.0, min(100.0, score))


def _select_best(track: Track, results: list[dict], threshold: int) -> dict | None:
    """Score and select the best match from a list of Spotify results.

    Deduplicates by URI, scores all candidates, and returns the best match
    meeting the threshold. Prefers exact-version matches over fallback versions.
    """
    if not results:
        return None

    # Dedupe by URI
    seen: set[str] = set()
    unique: list[dict] = []
    for r in results:
        if r["uri"] not in seen:
            seen.add(r["uri"])
            unique.append(r)

    scored: list[tuple[dict, float, float, dict[str, float], str]] = []
    for r in unique:
        components = _score_components(track, r)
        exact_score = _score_result(track, r, components)
        base_score = components["artist_score"] * 0.4 + components["stripped_title_score"] * 0.6
        match_type = _classify_version_match(track, r)
        scored.append((r, exact_score, base_score, components, match_type))

    # First pass: exact version matches only.
    exact_candidates = [s for s in scored if s[4] == "exact"]
    exact_candidates.sort(key=lambda x: x[1], reverse=True)
    if exact_candidates:
        best, best_score, _base_score, _components, _match_type = exact_candidates[0]
        if best_score >= threshold:
            return {**best, "score": best_score, "match_type": "exact"}

    # Second pass: fallback to a different version if the base track is strong.
    # This preserves the user's track intent in reporting while avoiding silent
    # "exact" classifications for remix/version substitutions.
    fallback_candidates = [s for s in scored if s[4] == "fallback_version"]
    fallback_candidates.sort(key=lambda x: x[2], reverse=True)
    if fallback_candidates:
        best, _exact_score, base_score, components, _match_type = fallback_candidates[0]
        if (
            base_score >= threshold
            and components["stripped_title_score"] >= 90
            and components["artist_score"] >= 70
        ):
            return {**best, "score": base_score, "match_type": "fallback_version"}

    return None


def match_track(sp, track: Track, threshold: int = 80) -> dict | None:
    """Try to find a Spotify match for a Rekordbox track.

    Runs search strategies in order and picks the best result across all of them.
    If Strategy 1 returns a high-confidence exact match (>= EARLY_EXIT_THRESHOLD),
    remaining strategies are skipped to reduce API calls.
    """
    all_results: list[dict] = []

    # Strategy 1: search with artist + title
    all_results.extend(search_track(sp, track.artist, track.name))

    # Early exit: if Strategy 1 already found a high-confidence exact match,
    # skip remaining strategies to reduce API calls.
    early = _select_best(track, all_results, EARLY_EXIT_THRESHOLD)
    if early is not None and early["match_type"] == "exact":
        return early

    # Strategy 2: strip mix info from title
    stripped = _strip_mix_info(track.name)
    if stripped != track.name:
        all_results.extend(search_track(sp, track.artist, stripped))

    # Strategy 3: include remixer as part of artist search
    if track.remixer:
        all_results.extend(search_track(sp, f"{track.artist} {track.remixer}", track.name))

    # Strategy 4: clean artist (strips country tags) + stripped title
    clean_artist = _normalize(track.artist)
    clean_title = _normalize(stripped)
    if clean_artist != track.artist.lower().strip() or clean_title != stripped.lower().strip():
        all_results.extend(search_track(sp, clean_artist, clean_title))

    # Strategy 5: plain-text search without field prefixes (forgiving of misspellings)
    if not all_results:
        all_results.extend(search_track(sp, track.artist, track.name, plain=True))

    return _select_best(track, all_results, threshold)


def match_track_cached(
    sp, track: Track, cache: "MatchCache", threshold: int = 80,
    retry_days: int = 7, force_retry: bool = False,
) -> tuple[dict | None, str]:
    """Match with cache support. Returns (result, source).

    source is one of: "cache", "api", "retry"
    """
    from djsupport.cache import MatchCache  # noqa: F811

    entry = cache.lookup(track.artist, track.name, threshold)

    if entry is not None:
        if entry.matched:
            return {
                "uri": entry.spotify_uri,
                "name": entry.spotify_name,
                "artist": entry.spotify_artist,
                "score": entry.score,
                "match_type": entry.match_type or "exact",
            }, "cache"
        else:
            if not cache.is_retry_eligible(track.artist, track.name,
                                           retry_days, force_retry):
                return None, "cache"

    result = match_track(sp, track, threshold=threshold)
    cache.store(track.artist, track.name, threshold, result)
    source = "retry" if entry is not None else "api"
    return result, source
