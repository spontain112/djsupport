"""Tests for djsupport.rekordbox — XML parsing."""

import textwrap
from pathlib import Path

import pytest

from djsupport.rekordbox import Track, Playlist, parse_xml


class TestParseXml:
    def test_parses_correct_number_of_tracks(self, library_xml):
        tracks, _ = parse_xml(library_xml)
        assert len(tracks) == 3

    def test_track_basic_fields(self, library_xml):
        tracks, _ = parse_xml(library_xml)
        t = tracks["1"]
        assert t.track_id == "1"
        assert t.name == "Vultora (Original Mix)"
        assert t.artist == "Solomun"
        assert t.album == "Vultora"
        assert t.label == "Diynamic"
        assert t.date_added == "2024-01-15"

    def test_track_with_remixer(self, library_xml):
        tracks, _ = parse_xml(library_xml)
        t = tracks["2"]
        assert t.remixer == "Joris Voorn"
        assert t.artist == "Eagles & Butterflies"

    def test_track_with_accented_characters(self, library_xml):
        tracks, _ = parse_xml(library_xml)
        t = tracks["3"]
        assert t.artist == "Âme"
        assert t.name == "Für Immer"

    def test_track_duration_parsed(self, library_xml):
        tracks, _ = parse_xml(library_xml)
        assert tracks["1"].duration == 412
        assert tracks["2"].duration == 368
        assert tracks["3"].duration == 485

    def test_parses_correct_number_of_playlists(self, library_xml):
        _, playlists = parse_xml(library_xml)
        assert len(playlists) == 2

    def test_playlist_names(self, library_xml):
        _, playlists = parse_xml(library_xml)
        names = {p.name for p in playlists}
        assert "Peak Time" in names
        assert "Deep" in names

    def test_peak_time_playlist_track_ids(self, library_xml):
        _, playlists = parse_xml(library_xml)
        peak = next(p for p in playlists if p.name == "Peak Time")
        assert "1" in peak.track_ids
        assert "2" in peak.track_ids
        assert len(peak.track_ids) == 2

    def test_deep_playlist_track_ids(self, library_xml):
        _, playlists = parse_xml(library_xml)
        deep = next(p for p in playlists if p.name == "Deep")
        assert "3" in deep.track_ids
        assert len(deep.track_ids) == 1

    def test_playlist_path_includes_folder(self, library_xml):
        _, playlists = parse_xml(library_xml)
        peak = next(p for p in playlists if p.name == "Peak Time")
        assert "My Playlists" in peak.path
        assert "Peak Time" in peak.path

    def test_playlist_path_separator(self, library_xml):
        _, playlists = parse_xml(library_xml)
        peak = next(p for p in playlists if p.name == "Peak Time")
        assert "/" in peak.path

    def test_root_folder_not_in_path(self, library_xml):
        _, playlists = parse_xml(library_xml)
        for p in playlists:
            assert not p.path.startswith("ROOT")

    def test_empty_collection(self, tmp_path):
        xml = tmp_path / "empty.xml"
        xml.write_text(textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <DJ_PLAYLISTS Version="1.0.0">
                <COLLECTION Entries="0"/>
                <PLAYLISTS>
                    <NODE Type="0" Name="ROOT" Count="0"/>
                </PLAYLISTS>
            </DJ_PLAYLISTS>
        """))
        tracks, playlists = parse_xml(xml)
        assert tracks == {}
        assert playlists == []

    def test_missing_collection_node(self, tmp_path):
        xml = tmp_path / "no_collection.xml"
        xml.write_text(textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <DJ_PLAYLISTS Version="1.0.0">
                <PLAYLISTS>
                    <NODE Type="0" Name="ROOT" Count="0"/>
                </PLAYLISTS>
            </DJ_PLAYLISTS>
        """))
        tracks, playlists = parse_xml(xml)
        assert tracks == {}

    def test_nested_folders(self, tmp_path):
        xml = tmp_path / "nested.xml"
        xml.write_text(textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <DJ_PLAYLISTS Version="1.0.0">
                <COLLECTION Entries="1">
                    <TRACK TrackID="10" Name="Track" Artist="Artist"
                           Album="" Remixer="" Label="" Genre="" DateAdded="2024-01-01"/>
                </COLLECTION>
                <PLAYLISTS>
                    <NODE Type="0" Name="ROOT" Count="1">
                        <NODE Type="0" Name="Folder A" Count="1">
                            <NODE Type="0" Name="Subfolder B" Count="1">
                                <NODE Type="1" Name="Playlist C" KeyType="0" Entries="1">
                                    <TRACK Key="10"/>
                                </NODE>
                            </NODE>
                        </NODE>
                    </NODE>
                </PLAYLISTS>
            </DJ_PLAYLISTS>
        """))
        _, playlists = parse_xml(xml)
        assert len(playlists) == 1
        assert playlists[0].name == "Playlist C"
        assert "Folder A" in playlists[0].path
        assert "Subfolder B" in playlists[0].path


class TestTrackDataclass:
    def test_display_format(self):
        t = Track(
            track_id="1",
            name="Vultora (Original Mix)",
            artist="Solomun",
            album="Vultora",
            remixer="",
            label="Diynamic",
            genre="",
            date_added="2024-01-15",
        )
        assert t.display == "Solomun - Vultora (Original Mix)"

    def test_display_with_accented_chars(self):
        t = Track(
            track_id="3",
            name="Für Immer",
            artist="Âme",
            album="",
            remixer="",
            label="",
            genre="",
            date_added="",
        )
        assert t.display == "Âme - Für Immer"
