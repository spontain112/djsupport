"""Participant-visible contract for the disposable Mirror/Drift study kit."""

from html.parser import HTMLParser
from pathlib import Path


PROTOTYPE = (
    Path(__file__).parents[1]
    / "docs"
    / "research"
    / "studies"
    / "mirror-drift"
    / "index.html"
)
STUDY_GUIDE = PROTOTYPE.with_name("README.md")


class PrototypeParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.screen_ids: list[str] = []
        self.links: list[str] = []
        self.playlist_choices: list[tuple[str, bool]] = []
        self.selection_gated_links = 0

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "section" and attributes.get("data-screen"):
            self.screen_ids.append(attributes["data-screen"])
        if tag == "a" and attributes.get("href", "").startswith("#"):
            self.links.append(attributes["href"][1:])
            if "data-requires-selection" in attributes:
                self.selection_gated_links += 1
        if tag == "input" and attributes.get("name") == "source-playlist":
            self.playlist_choices.append(
                (attributes.get("value", ""), "required" in attributes)
            )


class TestMirrorDriftStudyKit:
    def test_participant_can_navigate_the_five_study_screens(self):
        parser = PrototypeParser()
        parser.feed(PROTOTYPE.read_text())

        assert parser.screen_ids == [
            "select",
            "preview",
            "unchanged",
            "changed",
            "choice",
        ]
        assert set(parser.screen_ids).issubset(parser.links)
        assert parser.playlist_choices == [
            ("late-shift", True),
            ("sunrise-tools", True),
        ]
        assert parser.selection_gated_links == 1
        assert "Selected source: Late Shift" in PROTOTYPE.read_text()
        assert "Selected source: Sunrise Tools" in PROTOTYPE.read_text()

    def test_preview_and_inspection_explicitly_make_no_spotify_changes(self):
        content = " ".join(PROTOTYPE.read_text().split()).lower()

        assert "preview makes no changes to spotify" in content
        assert "inspection makes no changes to spotify" in content
        assert "nothing will be repaired automatically" in content

    def test_changed_mirror_preserves_ordered_occurrences_and_uncertainty(self):
        changed = PROTOTYPE.read_text().split('<section id="changed"', 1)[1]
        changed = changed.split("</section>", 1)[0]
        expected_facts = [
            "01 · Cinder Arc — Night Signal · unchanged",
            "02 · Vale Index — Second Light · moved from 03",
            "03 · Vale Index — Second Light · duplicate occurrence added",
            "04 · Unknown item · unavailable on Spotify · identity uncertain",
        ]

        positions = [changed.index(fact) for fact in expected_facts]
        assert positions == sorted(positions)
        assert "Cause not inferred" in changed

    def test_study_guide_carries_the_exact_real_user_gate(self):
        guide = STUDY_GUIDE.read_text()
        normalized_guide = " ".join(guide.lower().split())

        for heading in (
            "## Participant screener",
            "## Moderator script",
            "## Observation template",
            "## Pilot checklist",
            "## Five-participant checklist",
            "## Redacted decision note",
        ):
            assert heading in guide
        assert "All 5/5" in guide
        assert "At least 4/5" in guide
        assert "proceed, revise and retest, or stop" in normalized_guide
        assert "separate project approval and participant consent" in normalized_guide
