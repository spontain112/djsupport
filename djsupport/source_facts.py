"""Canonical, immutable source evidence carried by a Transfer occurrence."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from typing import Any


@dataclass(frozen=True)
class SourceEntity:
    """One provider entity translated into DJ Support vocabulary."""

    entity_id: str
    provider_id: int
    name: str
    slug: str | None = None


@dataclass(frozen=True)
class SourceDuration:
    display: str | None = None
    milliseconds: int | None = None


@dataclass(frozen=True)
class SourceDates:
    published: str | None = None
    released: str | None = None


@dataclass(frozen=True)
class SourceAvailability:
    """Tri-state availability; ``None`` means the producer omitted the fact."""

    worldwide: bool | None = None
    streaming: bool | None = None
    pre_order: bool | None = None
    enabled: bool | None = None
    hidden: bool | None = None
    exclusive: bool | None = None
    explicit: bool | None = None
    classic: bool | None = None


@dataclass(frozen=True)
class SourcePrice:
    code: str | None = None
    value: int | float | None = None


@dataclass(frozen=True)
class SourceCommerce:
    price: SourcePrice | None = None
    opaque_price_evidence: Any = None
    currency: str | None = None
    sale_type: str | None = None
    status: str | None = None


@dataclass(frozen=True)
class SourcePreview:
    url: str | None = None
    start_ms: int | None = None
    end_ms: int | None = None


@dataclass(frozen=True)
class SourceMusicalKey:
    provider_id: int | None = None
    name: str | None = None
    camelot_letter: str | None = None
    camelot_number: int | None = None


@dataclass(frozen=True)
class SourceTrackFacts:
    """Provider-neutral public facts retained as evidence, never authority."""

    provider: str
    entity_id: str
    provider_item_id: int
    canonical_url: str
    title: str
    slug: str | None = None
    version_name: str | None = None
    artists: tuple[SourceEntity, ...] = ()
    remixers: tuple[SourceEntity, ...] = ()
    duration: SourceDuration = field(default_factory=SourceDuration)
    recording_code: str | None = None
    tempo_bpm: int | float | None = None
    genre: SourceEntity | None = None
    subgenre: SourceEntity | None = None
    musical_key: SourceMusicalKey | None = None
    release: SourceEntity | None = None
    label: SourceEntity | None = None
    catalog_number: str | None = None
    label_track_identifier: str | None = None
    dates: SourceDates = field(default_factory=SourceDates)
    availability: SourceAvailability = field(default_factory=SourceAvailability)
    commerce: SourceCommerce = field(default_factory=SourceCommerce)
    preview: SourcePreview = field(default_factory=SourcePreview)
    artwork: Any = None
    raw_evidence: dict[str, Any] | None = None

    def to_storage(self) -> dict:
        """Return the canonical durable representation."""
        return asdict(self)

    def to_review_facts(self) -> dict:
        """Return public evidence while excluding the opaque raw record."""
        facts = self.to_storage()
        facts.pop("raw_evidence", None)
        facts.pop("artwork", None)
        facts.get("commerce", {}).pop("opaque_price_evidence", None)

        def omit_absent(value):
            if isinstance(value, dict):
                return {
                    key: omit_absent(item)
                    for key, item in value.items()
                    if item is not None
                }
            if isinstance(value, list):
                return [omit_absent(item) for item in value]
            if isinstance(value, tuple):
                return [omit_absent(item) for item in value]
            return value

        return omit_absent(facts)

    def for_public_review(self) -> SourceTrackFacts:
        return replace(
            self,
            raw_evidence=None,
            artwork=None,
            commerce=replace(self.commerce, opaque_price_evidence=None),
        )

    @classmethod
    def from_storage(cls, value: dict) -> SourceTrackFacts:
        def entity(item: dict | None) -> SourceEntity | None:
            return SourceEntity(**item) if item is not None else None

        return cls(
            **{
                **value,
                "artists": tuple(
                    SourceEntity(**item) for item in value.get("artists", ())
                ),
                "remixers": tuple(
                    SourceEntity(**item) for item in value.get("remixers", ())
                ),
                "duration": SourceDuration(**value.get("duration", {})),
                "genre": entity(value.get("genre")),
                "subgenre": entity(value.get("subgenre")),
                "musical_key": (
                    SourceMusicalKey(**value["musical_key"])
                    if value.get("musical_key") is not None else None
                ),
                "release": entity(value.get("release")),
                "label": entity(value.get("label")),
                "dates": SourceDates(**value.get("dates", {})),
                "availability": SourceAvailability(
                    **value.get("availability", {})
                ),
                "commerce": SourceCommerce(
                    **{
                        **value.get("commerce", {}),
                        "price": (
                            SourcePrice(**value["commerce"]["price"])
                            if value.get("commerce", {}).get("price") is not None
                            else None
                        ),
                    }
                ),
                "preview": SourcePreview(**value.get("preview", {})),
            }
        )


@dataclass(frozen=True)
class SourceOccurrence:
    """Stable identity, order, and evidence for one selected source occurrence."""

    occurrence_id: str
    position: int
    facts: SourceTrackFacts | None = None

    def for_public_review(self) -> SourceOccurrence:
        return SourceOccurrence(
            occurrence_id=self.occurrence_id,
            position=self.position,
            facts=(
                self.facts.for_public_review()
                if self.facts is not None else None
            ),
        )

    @classmethod
    def from_storage(cls, value: dict) -> SourceOccurrence:
        facts = value.get("facts")
        return cls(
            occurrence_id=value["occurrence_id"],
            position=value["position"],
            facts=(SourceTrackFacts.from_storage(facts) if facts is not None else None),
        )
