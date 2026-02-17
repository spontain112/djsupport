"""Parse Rekordbox XML library exports."""

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Track:
    track_id: str
    name: str
    artist: str
    album: str
    remixer: str
    label: str
    genre: str
    date_added: str  # e.g. "2024-03-15"

    @property
    def display(self) -> str:
        return f"{self.artist} - {self.name}"


@dataclass
class Playlist:
    name: str
    path: str  # e.g. "Baime 2022/Peak - Melodic"
    track_ids: list[str] = field(default_factory=list)


def parse_xml(xml_path: str | Path) -> tuple[dict[str, Track], list[Playlist]]:
    """Parse a Rekordbox XML export file.

    Returns:
        Tuple of (tracks dict keyed by TrackID, list of Playlists).
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()

    # Parse all tracks from COLLECTION
    tracks: dict[str, Track] = {}
    collection = root.find("COLLECTION")
    if collection is not None:
        for track_el in collection.findall("TRACK"):
            tid = track_el.get("TrackID", "")
            tracks[tid] = Track(
                track_id=tid,
                name=track_el.get("Name", ""),
                artist=track_el.get("Artist", ""),
                album=track_el.get("Album", ""),
                remixer=track_el.get("Remixer", ""),
                label=track_el.get("Label", ""),
                genre=track_el.get("Genre", ""),
                date_added=track_el.get("DateAdded", ""),
            )

    # Parse playlist tree
    playlists: list[Playlist] = []
    playlists_el = root.find("PLAYLISTS")
    if playlists_el is not None:
        root_node = playlists_el.find("NODE")
        if root_node is not None:
            _walk_nodes(root_node, "", playlists)

    return tracks, playlists


def _walk_nodes(node: ET.Element, parent_path: str, playlists: list[Playlist]) -> None:
    """Recursively walk the playlist node tree."""
    node_type = node.get("Type", "")
    name = node.get("Name", "")

    if node_type == "0":
        # Folder node — recurse into children
        folder_path = f"{parent_path}/{name}" if parent_path else name
        # Skip the ROOT folder itself in path
        if name == "ROOT":
            folder_path = ""
        for child in node.findall("NODE"):
            _walk_nodes(child, folder_path, playlists)
    elif node_type == "1":
        # Playlist node — collect track references
        path = f"{parent_path}/{name}" if parent_path else name
        track_ids = [t.get("Key", "") for t in node.findall("TRACK") if t.get("Key")]
        playlists.append(Playlist(name=name, path=path, track_ids=track_ids))
