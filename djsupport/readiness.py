"""Side-effect-free local setup facts for the first Transfer guide."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from djsupport.config import ConfigManager, validate_rekordbox_xml


FIRST_TRANSFER_CALLBACK = "http://127.0.0.1:8888/callback"


@dataclass(frozen=True)
class FirstTransferReadiness:
    spotify_configured: bool
    spotify_authenticated: bool
    rekordbox_configured: bool
    rekordbox_available: bool
    xml_path: str | None = None


def inspect_first_transfer_readiness(
    explicit_xml_path: str | None = None,
    *,
    authorize_private_source: bool = False,
) -> FirstTransferReadiness:
    """Inspect names and file presence without reading credentials or tokens."""
    spotify_configured = (
        "SPOTIPY_CLIENT_ID" in os.environ
        and "SPOTIPY_CLIENT_SECRET" in os.environ
        and os.environ.get("SPOTIPY_REDIRECT_URI") == FIRST_TRANSFER_CALLBACK
    )
    cache_name = ".cache"
    spotify_username = os.environ.get("SPOTIPY_CLIENT_USERNAME")
    if spotify_username:
        cache_name = f"{cache_name}-{spotify_username}"
    spotify_authenticated = spotify_configured and Path(cache_name).is_file()

    selected_path = explicit_xml_path
    if selected_path is None:
        config = ConfigManager()
        config.load()
        selected_path = config.get_rekordbox_xml_path()
    configured = selected_path is not None
    available = False
    if selected_path is not None:
        try:
            path = Path(selected_path).expanduser()
            available = path.exists() and path.is_file()
            selected_path = str(path)
        except OSError:
            available = False
    if authorize_private_source and available and selected_path is not None:
        available, _ = validate_rekordbox_xml(selected_path)
    return FirstTransferReadiness(
        spotify_configured=spotify_configured,
        spotify_authenticated=spotify_authenticated,
        rekordbox_configured=configured,
        rekordbox_available=available,
        xml_path=selected_path,
    )
