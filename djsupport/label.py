"""Beatport record label scraper."""

import json
import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import quote_plus

import requests

from djsupport.beatport import USER_AGENT, REQUEST_TIMEOUT, MAX_RESPONSE_SIZE, _parse_duration
from djsupport.rekordbox import Track

BEATPORT_LABEL_URL_PREFIX = "beatport.com/label/"
BEATPORT_LABEL_PATTERN = re.compile(
    r"^https://(www\.)?beatport\.com/label/[\w-]+/\d+(/tracks)?/?$"
)
PER_PAGE = 150
MAX_PAGES = 100  # Hard cap: 100 * 150 = 15,000 tracks maximum
LARGE_LABEL_THRESHOLD = 1000


class LabelParseError(Exception):
    """Raised when label page structure cannot be parsed."""


class InvalidLabelURL(ValueError):
    """Raised when a URL is not a valid Beatport label URL."""


@dataclass
class LabelResult:
    """A label search result from Beatport."""
    name: str
    url: str
    track_count: int
    latest_release: str
    latest_release_date: str


def validate_label_url(url: str) -> str:
    """Validate and normalize a Beatport label URL.

    Accepts both beatport.com/label/<slug>/<id> and
    beatport.com/label/<slug>/<id>/tracks.

    Raises InvalidLabelURL if the URL doesn't match the expected pattern.
    """
    url = url.split("?")[0].split("#")[0].rstrip("/")
    if not BEATPORT_LABEL_PATTERN.match(url):
        raise InvalidLabelURL(
            f"Not a valid Beatport label URL: {url}\n"
            "Expected: https://www.beatport.com/label/<name>/<id>"
        )
    # Normalize: strip /tracks suffix for the base URL
    if url.endswith("/tracks"):
        url = url[: -len("/tracks")]
    return url


def _fetch_page(url: str, page: int) -> str:
    """Fetch a single page of label tracks and return the HTML."""
    page_url = f"{url}/tracks?page={page}&per_page={PER_PAGE}"
    response = requests.get(
        page_url,
        headers={"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT,
        stream=True,
    )
    response.raise_for_status()

    chunks = []
    size = 0
    for chunk in response.iter_content(chunk_size=8192, decode_unicode=False):
        size += len(chunk)
        if size > MAX_RESPONSE_SIZE:
            response.close()
            raise LabelParseError("Response too large — does not look like a label page.")
        chunks.append(chunk)
    html = b"".join(chunks).decode(response.encoding or "utf-8")

    final_url = response.url
    if BEATPORT_LABEL_URL_PREFIX not in final_url:
        raise LabelParseError(
            f"Beatport redirected to an unexpected URL: {final_url}"
        )

    if "/human-test/" in html or "findProof" in html:
        raise LabelParseError(
            "Beatport returned an anti-bot challenge page. "
            "This may be temporary — try again in a few minutes."
        )

    return html


def _extract_next_data(html: str) -> dict:
    """Extract __NEXT_DATA__ JSON from HTML."""
    match = re.search(
        r'<script\s+id="__NEXT_DATA__"\s*[^>]*>(.*?)</script>',
        html,
        re.DOTALL,
    )
    if not match:
        raise LabelParseError(
            "Could not find label data on page. "
            "Beatport may have changed their page structure."
        )
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as e:
        raise LabelParseError(
            f"Invalid JSON in page data: {e}. "
            "Beatport may have changed their page structure."
        ) from e


def _parse_label_page(data: dict) -> tuple[str, list[Track], int]:
    """Extract label name, tracks, and total count from __NEXT_DATA__ JSON.

    Returns (label_name, tracks, total_count).
    """
    try:
        queries = data["props"]["pageProps"]["dehydratedState"]["queries"]
    except (KeyError, TypeError) as e:
        raise LabelParseError(
            f"Unexpected page data structure (missing key: {e}). "
            "Beatport may have changed their page format."
        ) from e

    # Find the query containing track results
    track_query = None
    for q in queries:
        if not isinstance(q, dict):
            continue
        state_data = q.get("state", {}).get("data", {})
        results = state_data.get("results")
        if isinstance(results, list) and results and isinstance(results[0], dict):
            if "artists" in results[0]:
                track_query = q
                break

    if not track_query:
        # Could be an empty label — check if we got a valid page with 0 results
        for q in queries:
            if not isinstance(q, dict):
                continue
            state_data = q.get("state", {}).get("data", {})
            results = state_data.get("results")
            if isinstance(results, list) and len(results) == 0:
                # Extract label name from page props
                page_props = data["props"]["pageProps"]
                label_name = page_props.get("label", {}).get("name", "Unknown Label")
                return label_name, [], 0

        raise LabelParseError(
            "Could not locate track data in label page queries. "
            f"Found {len(queries)} queries but none contained track results."
        )

    state_data = track_query["state"]["data"]
    results = state_data["results"]
    total_count = state_data.get("count", len(results))

    # Extract label name from page props
    page_props = data["props"]["pageProps"]
    label_name = page_props.get("label", {}).get("name", "Unknown Label")

    tracks = [_parse_label_track(item, i) for i, item in enumerate(results)]
    return label_name, tracks, total_count


def _parse_label_track(item: dict, position: int) -> Track:
    """Convert a Beatport label track JSON object to a Track dataclass."""
    raw_artists = item.get("artists", [])
    if not isinstance(raw_artists, list):
        raw_artists = []
    artists = ", ".join(
        a["name"] for a in raw_artists
        if isinstance(a, dict) and "name" in a
    )

    mix_name = item.get("mix_name", "")
    title = item.get("name", "")

    if mix_name and mix_name not in ("Original Mix", "Original"):
        title = f"{title} ({mix_name})"

    # Use publish_date or new_release_date for chronological ordering
    date_added = item.get("publish_date", item.get("new_release_date", ""))

    return Track(
        track_id=f"bp-label-{item.get('id', position)}",
        name=title,
        artist=artists,
        album=item.get("release", {}).get("name", ""),
        remixer="",
        label=item.get("release", {}).get("label", {}).get("name", ""),
        genre=item.get("genre", {}).get("name", ""),
        date_added=date_added,
        duration=_parse_duration(item.get("length", "")),
    )


def deduplicate_tracks(tracks: list[Track]) -> tuple[list[Track], int]:
    """Remove duplicate tracks that appear on multiple releases.

    Keys on normalized (artist, track_name). Keeps the first occurrence
    (newest, since the list is ordered newest-first).

    Returns (unique_tracks, duplicates_removed_count).
    """
    seen: set[tuple[str, str]] = set()
    unique: list[Track] = []
    for track in tracks:
        key = (track.artist.lower().strip(), track.name.lower().strip())
        if key not in seen:
            seen.add(key)
            unique.append(track)
    return unique, len(tracks) - len(unique)


def fetch_label_tracks(
    url: str,
    *,
    on_total: Callable[[int], bool | None] | None = None,
    on_page: Callable[[int, int], None] | None = None,
    on_page_error: Callable[[int, int, Exception], None] | None = None,
) -> tuple[str, list[Track]]:
    """Fetch all tracks from a Beatport label page with pagination.

    Args:
        url: Validated Beatport label URL (without /tracks suffix).
        on_total: Optional callback called with total track count after first page.
                  Should return False to abort fetching.
        on_page: Optional callback called after each page with (page_num, total_pages).

    Returns (label_name, tracks) where tracks are ordered newest first.
    Raises LabelParseError on structure issues, requests.RequestException on network issues.
    """
    # Fetch first page
    html = _fetch_page(url, 1)
    data = _extract_next_data(html)
    label_name, tracks, total_count = _parse_label_page(data)

    if not tracks:
        return label_name, []

    total_pages = min(math.ceil(total_count / PER_PAGE), MAX_PAGES)

    # Allow caller to abort (e.g., >1000 track warning)
    if on_total and on_total(total_count) is False:
        return label_name, []

    if on_page:
        on_page(1, total_pages)

    # Fetch remaining pages
    for page in range(2, total_pages + 1):
        try:
            html = _fetch_page(url, page)
            data = _extract_next_data(html)
            _, page_tracks, _ = _parse_label_page(data)
            tracks.extend(page_tracks)
        except (LabelParseError, requests.RequestException) as e:
            if on_page_error:
                on_page_error(page, total_pages, e)
            break

        if on_page:
            on_page(page, total_pages)

    return label_name, tracks


def _slugify(name: str) -> str:
    """Convert a label name to a URL slug (lowercase, hyphens for spaces)."""
    slug = re.sub(r"[^\w\s-]", "", name.lower())
    return re.sub(r"[\s_]+", "-", slug).strip("-")


def search_labels(query: str) -> list[LabelResult]:
    """Search Beatport for labels matching a name.

    Returns a list of LabelResult sorted by relevance.
    """
    search_url = f"https://www.beatport.com/search/labels?q={quote_plus(query)}"
    response = requests.get(
        search_url,
        headers={"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT,
        stream=True,
    )
    response.raise_for_status()

    chunks = []
    size = 0
    for chunk in response.iter_content(chunk_size=8192, decode_unicode=False):
        size += len(chunk)
        if size > MAX_RESPONSE_SIZE:
            response.close()
            raise LabelParseError("Search response too large.")
        chunks.append(chunk)
    html = b"".join(chunks).decode(response.encoding or "utf-8")

    if "/human-test/" in html or "findProof" in html:
        raise LabelParseError(
            "Beatport returned an anti-bot challenge page. "
            "This may be temporary — try again in a few minutes."
        )

    data = _extract_next_data(html)

    try:
        queries = data["props"]["pageProps"]["dehydratedState"]["queries"]
    except (KeyError, TypeError) as e:
        raise LabelParseError(
            f"Unexpected search page structure (missing key: {e})."
        ) from e

    # Find the query containing label results.
    # Beatport returns results under "data" (new format) or "results" (old format).
    items: list[dict] = []
    for q in queries:
        if not isinstance(q, dict):
            continue
        state_data = q.get("state", {}).get("data", {})
        # New format: nested under "data" key with label_name/label_id fields
        candidates = state_data.get("data") or state_data.get("results")
        if isinstance(candidates, list) and candidates and isinstance(candidates[0], dict):
            if "label_name" in candidates[0] or "name" in candidates[0]:
                items = candidates
                break

    label_results = []
    for item in items:
        # Support both new (label_id/label_name) and old (id/name/slug) formats
        label_id = item.get("label_id") or item.get("id", "")
        name = item.get("label_name") or item.get("name", "Unknown")
        slug = item.get("slug") or _slugify(name)

        # Extract latest release info if available
        last_release = item.get("last_release", {}) or {}
        latest_release = last_release.get("name", "")
        latest_release_date = last_release.get("publish_date", last_release.get("new_release_date", ""))

        label_url = f"https://www.beatport.com/label/{slug}/{label_id}"
        track_count = item.get("track_count", 0)

        label_results.append(LabelResult(
            name=name,
            url=label_url,
            track_count=track_count,
            latest_release=latest_release,
            latest_release_date=latest_release_date,
        ))

    return label_results
