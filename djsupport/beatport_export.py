"""Strict, local-only reader for the Beatport CLI V2 export contract."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from djsupport.rekordbox import Track


class BeatportExportError(ValueError):
    """The selected file is not a supported, valid Beatport export."""


@dataclass(frozen=True)
class ParsedBeatportExport:
    name: str
    reference: str
    tracks: list[Track]
    source_kind: str
    curator: str | None = None


TOP_LEVEL_FIELDS = {
    "schema_version", "source", "extracted_at", "track_count", "occurrences",
}
SOURCE_FIELDS = {"kind", "beatport_id", "canonical_url", "name", "curator"}
ENTITY_FIELDS = {"entity_id", "beatport_id", "name", "slug"}
OCCURRENCE_FIELDS = {"position", "occurrence_id", "track"}
TRACK_FIELDS = {
    "entity_id", "beatport_id", "canonical_url", "title", "slug",
    "mix_name", "artists", "remixers", "duration", "isrc", "bpm",
    "genre", "subgenre", "key", "release", "label", "catalog_number",
    "label_track_identifier", "dates", "availability", "commerce",
    "preview", "artwork", "raw_public_facts",
}
TRACK_REQUIRED = {
    "entity_id", "beatport_id", "canonical_url", "title", "duration",
    "dates", "availability", "commerce", "preview",
}
NESTED_FIELDS = {
    "duration": {"display", "milliseconds"},
    "dates": {"published", "released"},
    "availability": {
        "worldwide", "streaming", "pre_order", "enabled", "hidden",
        "exclusive", "explicit", "classic",
    },
    "commerce": {"price", "currency", "sale_type", "status"},
    "preview": {"url", "start_ms", "end_ms"},
    "key": {"id", "name", "camelot_letter", "camelot_number"},
}
SOURCE_URL = re.compile(
    r"^https://www\.beatport\.com/(track|chart|release|label)/[^/]+/([1-9][0-9]*)$"
)
TRACK_URL = re.compile(
    r"^https://www\.beatport\.com/track/[^/]+/([1-9][0-9]*)$"
)
ENTITY_ID = re.compile(r"^beatport:[a-z_]+:([1-9][0-9]*)$")


def _invalid(message: str) -> BeatportExportError:
    return BeatportExportError(f"Invalid Beatport V2 export: {message}")


def _object(
    value: object, *, label: str, allowed: set[str], required: set[str] = frozenset(),
) -> dict:
    if not isinstance(value, dict):
        raise _invalid(f"{label} must be an object")
    unknown = set(value) - allowed
    missing = required - set(value)
    if unknown:
        raise _invalid(f"{label} contains unsupported fields")
    if missing:
        raise _invalid(f"{label} is missing required fields")
    return value


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _invalid(f"{label} must be a positive integer")
    return value


def _non_empty_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise _invalid(f"{label} must be a non-empty string")
    return value


def _validate_entity(value: object, label: str) -> dict:
    entity = _object(
        value, label=label, allowed=ENTITY_FIELDS,
        required={"entity_id", "beatport_id", "name"},
    )
    beatport_id = _positive_int(entity["beatport_id"], f"{label}.beatport_id")
    entity_id = _non_empty_string(entity["entity_id"], f"{label}.entity_id")
    matched = ENTITY_ID.fullmatch(entity_id)
    if matched is None or int(matched.group(1)) != beatport_id:
        raise _invalid(f"{label}.entity_id does not match its Beatport ID")
    _non_empty_string(entity["name"], f"{label}.name")
    if "slug" in entity:
        _non_empty_string(entity["slug"], f"{label}.slug")
    return entity


def _validate_track(value: object, position: int) -> dict:
    track = _object(
        value, label=f"occurrence {position} track", allowed=TRACK_FIELDS,
        required=TRACK_REQUIRED,
    )
    beatport_id = _positive_int(
        track["beatport_id"], f"occurrence {position} track.beatport_id",
    )
    if track["entity_id"] != f"beatport:track:{beatport_id}":
        raise _invalid(f"occurrence {position} track entity ID is inconsistent")
    url = _non_empty_string(
        track["canonical_url"], f"occurrence {position} track.canonical_url",
    )
    matched_url = TRACK_URL.fullmatch(url)
    if matched_url is None or int(matched_url.group(1)) != beatport_id:
        raise _invalid(f"occurrence {position} track URL is not canonical")
    _non_empty_string(track["title"], f"occurrence {position} track.title")
    for field in ("slug", "mix_name", "isrc", "catalog_number", "label_track_identifier"):
        if field in track and not isinstance(track[field], str):
            raise _invalid(f"occurrence {position} track.{field} must be a string")
    for field in ("artists", "remixers"):
        if field in track:
            if not isinstance(track[field], list):
                raise _invalid(f"occurrence {position} track.{field} must be a list")
            for index, entity in enumerate(track[field], start=1):
                _validate_entity(entity, f"occurrence {position} {field} {index}")
    for field in ("genre", "subgenre", "release", "label"):
        if field in track:
            _validate_entity(track[field], f"occurrence {position} track.{field}")
    for field in ("duration", "dates", "availability", "commerce", "preview", "key"):
        if field not in track:
            continue
        nested = _object(
            track[field], label=f"occurrence {position} track.{field}",
            allowed=NESTED_FIELDS[field],
        )
        if field == "availability" and any(
            not isinstance(item, bool) for item in nested.values()
        ):
            raise _invalid(f"occurrence {position} availability must be boolean")
        if field == "duration" and "milliseconds" in nested and (
            isinstance(nested["milliseconds"], bool)
            or not isinstance(nested["milliseconds"], int)
            or nested["milliseconds"] < 0
        ):
            raise _invalid(f"occurrence {position} duration is invalid")
    if "raw_public_facts" in track and not isinstance(
        track["raw_public_facts"], dict,
    ):
        raise _invalid(f"occurrence {position} raw public facts must be an object")
    return track


def _validate_document(document: object) -> dict:
    value = _object(
        document, label="document", allowed=TOP_LEVEL_FIELDS,
        required=TOP_LEVEL_FIELDS,
    )
    if value["schema_version"] != "beatport.export/v2":
        raise BeatportExportError("Beatport export schema must be beatport.export/v2")
    extracted_at = _non_empty_string(value["extracted_at"], "extracted_at")
    try:
        datetime.fromisoformat(extracted_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid("extracted_at must be an ISO date-time") from exc
    source = _object(
        value["source"], label="source", allowed=SOURCE_FIELDS,
        required={"kind", "beatport_id", "canonical_url", "name"},
    )
    kind = source["kind"]
    if kind not in {"track", "chart", "release", "label"}:
        raise _invalid("source kind is unsupported")
    source_id = _positive_int(source["beatport_id"], "source.beatport_id")
    source_url = _non_empty_string(source["canonical_url"], "source.canonical_url")
    matched_source = SOURCE_URL.fullmatch(source_url)
    if (
        matched_source is None or matched_source.group(1) != kind
        or int(matched_source.group(2)) != source_id
    ):
        raise _invalid("source URL is not canonical")
    _non_empty_string(source["name"], "source.name")
    if "curator" in source:
        _validate_entity(source["curator"], "source.curator")
    track_count = _positive_int(value["track_count"], "track_count")
    occurrences = value["occurrences"]
    if not isinstance(occurrences, list) or len(occurrences) != track_count:
        raise _invalid("track_count does not match occurrences")
    for index, raw_occurrence in enumerate(occurrences, start=1):
        occurrence = _object(
            raw_occurrence, label=f"occurrence {index}",
            allowed=OCCURRENCE_FIELDS, required=OCCURRENCE_FIELDS,
        )
        if occurrence["position"] != index:
            raise _invalid("occurrence positions must be contiguous and one-based")
        expected_id = f"beatport:{kind}:{source_id}:{index}"
        if occurrence["occurrence_id"] != expected_id:
            raise _invalid(f"occurrence {index} identity is inconsistent")
        _validate_track(occurrence["track"], index)
    return value


def _entity_name(value: object) -> str:
    return value.get("name", "") if isinstance(value, dict) else ""


def _track_from_occurrence(occurrence: dict) -> Track:
    track = occurrence["track"]
    mix_name = track.get("mix_name", "")
    title = track["title"]
    if mix_name and mix_name not in {"Original", "Original Mix"}:
        title = f"{title} ({mix_name})"
    artists = ", ".join(
        _entity_name(artist) for artist in track.get("artists", [])
        if _entity_name(artist)
    )
    remixers = ", ".join(
        _entity_name(remixer) for remixer in track.get("remixers", [])
        if _entity_name(remixer)
    )
    dates = track.get("dates", {})
    duration = track.get("duration", {})
    milliseconds = duration.get("milliseconds", 0)
    return Track(
        track_id=track["entity_id"],
        name=title,
        artist=artists,
        album=_entity_name(track.get("release")),
        remixer=remixers,
        label=_entity_name(track.get("label")),
        genre=_entity_name(track.get("genre")),
        date_added=dates.get("released", dates.get("published", "")),
        duration=int(milliseconds) // 1000,
        version=mix_name,
        occurrence_id=occurrence["occurrence_id"],
        source_position=occurrence["position"],
        source_facts=dict(track),
    )


def read_beatport_export(
    path: str | Path, *, expected_sha256: str | None = None,
) -> ParsedBeatportExport:
    """Read one explicitly selected V2 file without contacting Beatport."""
    selected = Path(path)
    try:
        content = selected.read_bytes()
        if (
            expected_sha256 is not None
            and hashlib.sha256(content).hexdigest() != expected_sha256
        ):
            raise BeatportExportError(
                "Selected Beatport export changed after selection"
            )
        document = json.loads(content)
    except (OSError, json.JSONDecodeError) as exc:
        raise BeatportExportError("Could not read a valid Beatport export") from exc
    document = _validate_document(document)
    source = document["source"]
    occurrences = document["occurrences"]
    tracks = [_track_from_occurrence(item) for item in occurrences]
    curator_name = _entity_name(source.get("curator"))
    return ParsedBeatportExport(
        name=source["name"],
        reference=source["canonical_url"],
        tracks=tracks,
        source_kind=source["kind"],
        curator=curator_name or None,
    )
