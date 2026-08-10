"""Strict, local-only reader for the Beatport CLI V2 export contract."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlparse

from jsonschema import Draft202012Validator, FormatChecker

from djsupport.rekordbox import Track
from djsupport.source_facts import (
    SourceAvailability,
    SourceCommerce,
    SourceDates,
    SourceDuration,
    SourceEntity,
    SourceMusicalKey,
    SourceOccurrence,
    SourcePrice,
    SourcePreview,
    SourceTrackFacts,
)


class BeatportExportError(ValueError):
    """The selected file is not a supported, valid Beatport export."""


@dataclass(frozen=True)
class ParsedBeatportExport:
    name: str
    reference: str
    tracks: list[Track]
    source_kind: str
    curator: str | None = None


SOURCE_URL = re.compile(
    r"^https://www\.beatport\.com/(track|chart|release|label)/[^/]+/([1-9][0-9]*)$"
)
TRACK_URL = re.compile(
    r"^https://www\.beatport\.com/track/[^/]+/([1-9][0-9]*)$"
)
ENTITY_ID = re.compile(r"^beatport:[a-z_]+:([1-9][0-9]*)$")


def _invalid(message: str) -> BeatportExportError:
    return BeatportExportError(f"Invalid Beatport V2 export: {message}")


@lru_cache(maxsize=1)
def _schema_validator() -> Draft202012Validator:
    schema_path = files("djsupport").joinpath(
        "contracts/beatport.export.v2.schema.json"
    )
    schema = json.loads(schema_path.read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _validate_entity(value: object, label: str) -> dict:
    entity = value
    beatport_id = entity["beatport_id"]
    entity_id = entity["entity_id"]
    matched = ENTITY_ID.fullmatch(entity_id)
    if matched is None or int(matched.group(1)) != beatport_id:
        raise _invalid(f"{label}.entity_id does not match its Beatport ID")
    return entity


def _validate_public_reference(value: str, label: str) -> None:
    parsed = urlparse(value)
    hostname = parsed.hostname or ""
    private_host = (
        hostname.casefold() == "localhost"
        or hostname.casefold().endswith((".localhost", ".local"))
    )
    try:
        private_host = private_host or not ipaddress.ip_address(hostname).is_global
    except ValueError:
        pass
    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or private_host
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise _invalid(f"{label} must contain only public web references")


def _validate_track(value: object, position: int) -> dict:
    track = value
    beatport_id = track["beatport_id"]
    if track["entity_id"] != f"beatport:track:{beatport_id}":
        raise _invalid(f"occurrence {position} track entity ID is inconsistent")
    url = track["canonical_url"]
    matched_url = TRACK_URL.fullmatch(url)
    if matched_url is None or int(matched_url.group(1)) != beatport_id:
        raise _invalid(f"occurrence {position} track URL is not canonical")
    for field in ("artists", "remixers"):
        for index, entity in enumerate(track.get(field, ()), start=1):
            _validate_entity(entity, f"occurrence {position} {field} {index}")
    for field in ("genre", "subgenre", "release", "label"):
        if field in track:
            _validate_entity(track[field], f"occurrence {position} track.{field}")
    preview_url = track["preview"].get("url")
    if preview_url is not None:
        _validate_public_reference(
            preview_url, f"occurrence {position} track.preview.url"
        )
    return track


def _validate_document(document: object) -> dict:
    if not isinstance(document, dict) or document.get(
        "schema_version"
    ) != "beatport.export/v2":
        raise BeatportExportError("Beatport export schema must be beatport.export/v2")
    errors = sorted(
        _schema_validator().iter_errors(document),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        raise _invalid("document does not satisfy the normative V2 schema")
    value = document
    source = value["source"]
    kind = source["kind"]
    source_id = source["beatport_id"]
    source_url = source["canonical_url"]
    matched_source = SOURCE_URL.fullmatch(source_url)
    if (
        matched_source is None or matched_source.group(1) != kind
        or int(matched_source.group(2)) != source_id
    ):
        raise _invalid("source URL is not canonical")
    if "curator" in source:
        _validate_entity(source["curator"], "source.curator")
    track_count = value["track_count"]
    occurrences = value["occurrences"]
    if len(occurrences) != track_count:
        raise _invalid("track_count does not match occurrences")
    for index, raw_occurrence in enumerate(occurrences, start=1):
        occurrence = raw_occurrence
        if occurrence["position"] != index:
            raise _invalid("occurrence positions must be contiguous and one-based")
        expected_id = f"beatport:{kind}:{source_id}:{index}"
        if occurrence["occurrence_id"] != expected_id:
            raise _invalid(f"occurrence {index} identity is inconsistent")
        _validate_track(occurrence["track"], index)
    return value


def _entity(value: dict | None) -> SourceEntity | None:
    if value is None:
        return None
    return SourceEntity(
        entity_id=value["entity_id"],
        provider_id=value["beatport_id"],
        name=value["name"],
        slug=value.get("slug"),
    )


def _facts(track: dict) -> SourceTrackFacts:
    key = track.get("key")
    commerce = track["commerce"]
    raw_price = commerce.get("price")
    typed_price = None
    opaque_price = None
    price_code = raw_price.get("code") if isinstance(raw_price, dict) else None
    price_value = raw_price.get("value") if isinstance(raw_price, dict) else None
    if (
        isinstance(raw_price, dict)
        and set(raw_price) <= {"code", "value"}
        and (price_code is None or re.fullmatch(r"[A-Z]{3}", price_code))
        and not isinstance(price_value, bool)
        and isinstance(price_value, (int, float, type(None)))
        and (price_value is None or (price_value >= 0 and math.isfinite(price_value)))
    ):
        typed_price = SourcePrice(
            code=price_code, value=price_value,
        )
    elif raw_price is not None:
        opaque_price = raw_price
    return SourceTrackFacts(
        provider="beatport",
        entity_id=track["entity_id"],
        provider_item_id=track["beatport_id"],
        canonical_url=track["canonical_url"],
        title=track["title"],
        slug=track.get("slug"),
        version_name=track.get("mix_name"),
        artists=tuple(_entity(item) for item in track.get("artists", ())),
        remixers=tuple(_entity(item) for item in track.get("remixers", ())),
        duration=SourceDuration(**track["duration"]),
        recording_code=track.get("isrc"),
        tempo_bpm=track.get("bpm"),
        genre=_entity(track.get("genre")),
        subgenre=_entity(track.get("subgenre")),
        musical_key=(
            SourceMusicalKey(
                provider_id=key.get("id"),
                name=key.get("name"),
                camelot_letter=key.get("camelot_letter"),
                camelot_number=key.get("camelot_number"),
            )
            if key is not None else None
        ),
        release=_entity(track.get("release")),
        label=_entity(track.get("label")),
        catalog_number=track.get("catalog_number"),
        label_track_identifier=track.get("label_track_identifier"),
        dates=SourceDates(**track["dates"]),
        availability=SourceAvailability(**track["availability"]),
        commerce=SourceCommerce(
            price=typed_price,
            opaque_price_evidence=opaque_price,
            currency=commerce.get("currency"),
            sale_type=commerce.get("sale_type"),
            status=commerce.get("status"),
        ),
        preview=SourcePreview(**track["preview"]),
        artwork=track.get("artwork"),
        raw_evidence=track.get("raw_public_facts"),
    )


def _track_from_occurrence(occurrence: dict) -> Track:
    track = occurrence["track"]
    facts = _facts(track)
    mix_name = track.get("mix_name", "")
    title = track["title"]
    if mix_name and mix_name not in {"Original", "Original Mix"}:
        title = f"{title} ({mix_name})"
    artists = ", ".join(
        artist.name for artist in facts.artists if artist.name
    )
    remixers = ", ".join(
        remixer.name for remixer in facts.remixers if remixer.name
    )
    dates = track.get("dates", {})
    duration = track.get("duration", {})
    milliseconds = duration.get("milliseconds", 0)
    return Track(
        track_id=track["entity_id"],
        name=title,
        artist=artists,
        album=facts.release.name if facts.release is not None else "",
        remixer=remixers,
        label=facts.label.name if facts.label is not None else "",
        genre=facts.genre.name if facts.genre is not None else "",
        date_added=dates.get("released", dates.get("published", "")),
        duration=int(milliseconds) // 1000,
        version=mix_name,
        source_occurrence=SourceOccurrence(
            occurrence_id=occurrence["occurrence_id"],
            position=occurrence["position"],
            facts=facts,
        ),
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
    curator = _entity(source.get("curator"))
    return ParsedBeatportExport(
        name=source["name"],
        reference=source["canonical_url"],
        tracks=tracks,
        source_kind=source["kind"],
        curator=(curator.name if curator is not None else None),
    )
