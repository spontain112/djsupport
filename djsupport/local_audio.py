"""Optional, local-only audio identity boundary for Rekordbox Transfers."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urlparse

from djsupport.rekordbox import Track
from djsupport.transfer import LocalAudioObservation


@dataclass(frozen=True)
class LocalAudioCapability:
    available: bool
    algorithm: str = "chromaprint"
    algorithm_version: str | None = None
    reason: str | None = None


class ChromaprintLocalAudio:
    """Calculate Chromaprint evidence without uploading or changing audio."""

    def __init__(
        self,
        *,
        executable: str | None = None,
        runner: Callable = subprocess.run,
        timeout: float = 30.0,
    ) -> None:
        self._explicit_executable = executable
        self._runner = runner
        self._timeout = timeout
        self._capability: LocalAudioCapability | None = None

    def capability(self) -> LocalAudioCapability:
        """Inspect the optional binary without reading a library or audio file."""
        if self._capability is not None:
            return self._capability
        executable = self._explicit_executable or shutil.which("fpcalc")
        if executable is None:
            self._capability = LocalAudioCapability(
                available=False, reason="binary_unavailable",
            )
            return self._capability
        try:
            completed = self._runner(
                [executable, "-version"], capture_output=True, text=True,
                timeout=self._timeout, check=False,
            )
        except (OSError, subprocess.SubprocessError):
            self._capability = LocalAudioCapability(
                available=False, reason="binary_unavailable",
            )
            return self._capability
        if completed.returncode != 0:
            self._capability = LocalAudioCapability(
                available=False, reason="binary_unavailable",
            )
            return self._capability
        version_match = re.search(
            r"(?:fpcalc\s+version\s+)?([0-9]+(?:\.[0-9]+)+)",
            completed.stdout,
        )
        self._capability = LocalAudioCapability(
            available=True,
            algorithm_version=(version_match.group(1) if version_match else "unknown"),
        )
        return self._capability

    def preflight(self, track: Track) -> str:
        """Classify a reference without opening or calculating from the audio."""
        path = self._path(track.location)
        if path is None:
            return "unsupported_location" if track.location else "missing_location"
        return "eligible" if path.is_file() else "missing_file"

    def observe(self, track: Track) -> LocalAudioObservation:
        path = self._path(track.location)
        if path is None:
            return LocalAudioObservation.unavailable(
                "unsupported_location" if track.location else "missing_location"
            )
        if not path.is_file():
            return LocalAudioObservation.unavailable("missing_file")
        capability = self.capability()
        if not capability.available:
            return LocalAudioObservation.unavailable(
                capability.reason or "binary_unavailable"
            )
        executable = self._explicit_executable or shutil.which("fpcalc")
        assert executable is not None
        try:
            completed = self._runner(
                [executable, "-json", str(path)], capture_output=True, text=True,
                timeout=self._timeout, check=False,
            )
        except subprocess.TimeoutExpired:
            return LocalAudioObservation.unavailable("timeout")
        except (OSError, subprocess.SubprocessError):
            return LocalAudioObservation.unavailable("calculation_failed")
        if completed.returncode != 0:
            return LocalAudioObservation.unavailable("calculation_failed")
        try:
            payload = json.loads(completed.stdout)
            fingerprint = payload["fingerprint"]
            duration = int(float(payload.get("duration", track.duration)))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return LocalAudioObservation.unavailable("invalid_output")
        if not isinstance(fingerprint, str) or not fingerprint:
            return LocalAudioObservation.unavailable("invalid_output")
        return LocalAudioObservation.available(
            fingerprint=fingerprint,
            algorithm="chromaprint",
            algorithm_version=capability.algorithm_version or "unknown",
            duration=duration,
        )

    @staticmethod
    def _path(location: str) -> Path | None:
        if not location:
            return None
        parsed = urlparse(location)
        if parsed.scheme and parsed.scheme != "file":
            return None
        if parsed.scheme == "file" and parsed.netloc not in ("", "localhost"):
            return None
        raw_path = unquote(parsed.path) if parsed.scheme else location
        if not raw_path:
            return None
        return Path(raw_path)

