"""Beatport DJ chart scraper."""

import json
import re

import requests

from djsupport.rekordbox import Track

BEATPORT_CHART_URL_PREFIX = "beatport.com/chart/"
BEATPORT_CHART_PATTERN = re.compile(
    r"^https://(www\.)?beatport\.com/chart/[\w-]+/\d+/?$"
)
USER_AGENT = "Mozilla/5.0 (compatible; djsupport/0.3.0)"
REQUEST_TIMEOUT = (5, 30)  # (connect, read) seconds
MAX_RESPONSE_SIZE = 5 * 1024 * 1024  # 5 MB


class BeatportParseError(Exception):
    """Raised when chart page structure cannot be parsed."""


class InvalidBeatportURL(ValueError):
    """Raised when a URL is not a valid Beatport chart URL."""


def validate_url(url: str) -> str:
    """Validate and normalize a Beatport chart URL.

    Raises InvalidBeatportURL if the URL doesn't match the expected pattern.
    """
    url = url.split("?")[0].rstrip("/")  # strip query params and trailing slash
    if not BEATPORT_CHART_PATTERN.match(url):
        raise InvalidBeatportURL(
            f"Not a valid Beatport chart URL: {url}\n"
            "Expected: https://www.beatport.com/chart/<name>/<id>"
        )
    return url


def fetch_chart(url: str) -> tuple[str, str, list[Track]]:
    """Fetch and parse a Beatport DJ chart page.

    Returns (chart_name, curator, tracks) where tracks are ordered by chart position.
    Raises BeatportParseError on structure issues, requests.RequestException on network issues.
    """
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT,
        stream=True,
    )
    response.raise_for_status()

    # Read with size limit
    chunks = []
    size = 0
    for chunk in response.iter_content(chunk_size=8192, decode_unicode=False):
        size += len(chunk)
        if size > MAX_RESPONSE_SIZE:
            response.close()
            raise BeatportParseError("Response too large — does not look like a chart page.")
        chunks.append(chunk)
    html = b"".join(chunks).decode(response.encoding or "utf-8")

    # Validate final URL after redirects
    final_url = response.url
    if BEATPORT_CHART_URL_PREFIX not in final_url:
        raise BeatportParseError(
            f"Beatport redirected to an unexpected URL: {final_url}"
        )

    # Extract __NEXT_DATA__ JSON via regex (no BeautifulSoup needed)
    match = re.search(
        r'<script\s+id="__NEXT_DATA__"\s*[^>]*>(.*?)</script>',
        html,
        re.DOTALL,
    )
    if not match:
        # Detect anti-bot challenge page
        if "/human-test/" in html or "findProof" in html:
            raise BeatportParseError(
                "Beatport returned an anti-bot challenge page. "
                "This may be temporary — try again in a few minutes."
            )
        raise BeatportParseError(
            "Could not find chart data on page. "
            "Beatport may have changed their page structure."
        )

    data = json.loads(match.group(1))
    return _parse_chart_data(data, url)


def _parse_chart_data(data: dict, url: str) -> tuple[str, str, list[Track]]:
    """Extract chart info and tracks from __NEXT_DATA__ JSON."""
    try:
        queries = data["props"]["pageProps"]["dehydratedState"]["queries"]
    except (KeyError, TypeError) as e:
        raise BeatportParseError(
            f"Unexpected page data structure (missing key: {e}). "
            "Beatport may have changed their page format."
        ) from e

    # Find the query containing track results
    track_query = None
    for q in queries:
        if not isinstance(q, dict):
            continue
        results = q.get("state", {}).get("data", {}).get("results")
        if isinstance(results, list) and results and isinstance(results[0], dict):
            if "artists" in results[0]:
                track_query = q
                break

    if not track_query:
        raise BeatportParseError(
            f"Could not locate track data in chart page queries. "
            f"Found {len(queries)} queries but none contained track results."
        )

    results = track_query["state"]["data"]["results"]

    # Extract chart metadata from page props
    page_props = data["props"]["pageProps"]
    chart_name = page_props.get("chart", {}).get("name", "Unknown Chart")
    curator = page_props.get("chart", {}).get("dj", {}).get("name", "Unknown")

    tracks = [_parse_track(item, i) for i, item in enumerate(results)]
    return chart_name, curator, tracks


def _parse_duration(length_str: str) -> int:
    """Parse a duration string like '4:44' or '1:04:30' to seconds.

    Returns 0 on unparseable input.
    """
    if not length_str or ":" not in length_str:
        return 0
    parts = length_str.split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except ValueError:
        return 0
    return 0


def _parse_track(item: dict, position: int) -> Track:
    """Convert a Beatport track JSON object to a Track dataclass."""
    raw_artists = item.get("artists", [])
    if not isinstance(raw_artists, list):
        raw_artists = []
    artists = ", ".join(
        a["name"] for a in raw_artists
        if isinstance(a, dict) and "name" in a
    )

    mix_name = item.get("mix_name", "")
    title = item.get("name", "")

    # Append mix name if it's not "Original Mix" (adds noise to matching)
    if mix_name and mix_name != "Original Mix":
        title = f"{title} ({mix_name})"

    return Track(
        track_id=f"bp-{item.get('id', position)}",
        name=title,
        artist=artists,
        album=item.get("release", {}).get("name", ""),
        remixer="",
        label=item.get("release", {}).get("label", {}).get("name", ""),
        genre=item.get("genre", {}).get("name", ""),
        date_added="",
        duration=_parse_duration(item.get("length", "")),
    )
