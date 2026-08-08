"""Process-local, path-redacted media adapter for selected Rekordbox audio."""

from __future__ import annotations

import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator
from urllib.parse import unquote, urlparse

from djsupport.rekordbox import Track


MEDIA_TYPES = {
    ".aif": "audio/aiff",
    ".aiff": "audio/aiff",
    ".flac": "audio/flac",
    ".m4a": "audio/mp4",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".wav": "audio/wav",
}


@dataclass(frozen=True)
class LocalAuditionCapability:
    available: bool = True
    reason: str | None = None


@dataclass(frozen=True)
class LocalAuditionResult:
    """Path-free facts returned after one explicitly authorized media open."""

    status: str
    handle: str | None = None
    media_type: str | None = None
    content_length: int = 0
    reason: str | None = None
    expires_in: int | None = None

    @classmethod
    def unavailable(cls, reason: str) -> LocalAuditionResult:
        return cls(status="unavailable", reason=reason)


@dataclass(frozen=True)
class AuditionStream:
    status_code: int
    media_type: str
    content_length: int
    body: Iterator[bytes]
    content_range: str | None = None


class AuditionHandleUnavailable(LookupError):
    """An audition handle is invalid, expired, or process-local elsewhere."""


class AuditionRangeNotSatisfiable(ValueError):
    def __init__(self, total_size: int) -> None:
        super().__init__("Audition byte range is not satisfiable")
        self.total_size = total_size


@dataclass
class _AuditionResource:
    transfer_id: str
    item_id: str
    path: Path
    media_type: str
    content_length: int
    expires_at: float


class LocalSourceAudition:
    """Issue short-lived handles for exact selected local audio references."""

    def __init__(
        self,
        *,
        ttl_seconds: int = 600,
        max_range_bytes: int = 2 * 1024 * 1024,
        chunk_bytes: int = 64 * 1024,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_range_bytes = max_range_bytes
        self._chunk_bytes = chunk_bytes
        self._clock = clock
        self._resources: dict[str, _AuditionResource] = {}

    def capability(self) -> LocalAuditionCapability:
        """Inspect support without reading source media."""
        return LocalAuditionCapability()

    def preflight(self, track: Track) -> LocalAuditionResult:
        resolved = self._resolve_track(track)
        if isinstance(resolved, LocalAuditionResult):
            return resolved
        path, media_type, size = resolved
        del path
        return LocalAuditionResult(
            status="available",
            media_type=media_type,
            content_length=size,
        )

    def open(
        self, transfer_id: str, item_id: str, track: Track,
    ) -> LocalAuditionResult:
        resolved = self._resolve_track(track)
        if isinstance(resolved, LocalAuditionResult):
            return resolved
        path, media_type, size = resolved
        self._purge_expired()
        for handle, resource in list(self._resources.items()):
            if (
                resource.transfer_id == transfer_id
                and resource.item_id == item_id
            ):
                self._resources.pop(handle, None)
        handle = secrets.token_urlsafe(32)
        self._resources[handle] = _AuditionResource(
            transfer_id=transfer_id,
            item_id=item_id,
            path=path,
            media_type=media_type,
            content_length=size,
            expires_at=self._clock() + self._ttl_seconds,
        )
        return LocalAuditionResult(
            status="available",
            handle=handle,
            media_type=media_type,
            content_length=size,
            expires_in=self._ttl_seconds,
        )

    def invalidate_transfer(self, transfer_id: str) -> None:
        for handle, resource in list(self._resources.items()):
            if resource.transfer_id == transfer_id:
                self._resources.pop(handle, None)

    def stream(
        self, handle: str | None, range_header: str | None = None,
    ) -> AuditionStream:
        self._purge_expired()
        if not handle or handle not in self._resources:
            raise AuditionHandleUnavailable("Audition handle is unavailable")
        resource = self._resources[handle]
        start, end, status = self._range(
            range_header, resource.content_length,
        )
        length = max(0, end - start + 1)
        return AuditionStream(
            status_code=status,
            media_type=resource.media_type,
            content_length=length,
            content_range=(
                f"bytes {start}-{end}/{resource.content_length}"
                if status == 206 else None
            ),
            body=self._read(resource.path, start, length),
        )

    def _purge_expired(self) -> None:
        now = self._clock()
        for handle, resource in list(self._resources.items()):
            if resource.expires_at <= now:
                self._resources.pop(handle, None)

    def _resolve_track(
        self, track: Track,
    ) -> tuple[Path, str, int] | LocalAuditionResult:
        location = track.location
        if not location:
            return LocalAuditionResult.unavailable("missing_location")
        parsed = urlparse(location)
        if parsed.scheme and parsed.scheme != "file":
            return LocalAuditionResult.unavailable("unsupported_location")
        if parsed.scheme == "file" and parsed.netloc not in ("", "localhost"):
            return LocalAuditionResult.unavailable("unsupported_location")
        raw_path = unquote(parsed.path) if parsed.scheme else location
        if not raw_path:
            return LocalAuditionResult.unavailable("missing_location")
        if any(character in raw_path for character in ("*", "?", "[", "]")):
            return LocalAuditionResult.unavailable("unsafe_location")
        path = Path(raw_path)
        media_type = MEDIA_TYPES.get(path.suffix.casefold())
        if media_type is None:
            return LocalAuditionResult.unavailable("unsupported_format")
        try:
            if not path.is_file():
                return LocalAuditionResult.unavailable("missing_file")
            size = path.stat().st_size
            with path.open("rb"):
                pass
        except PermissionError:
            return LocalAuditionResult.unavailable("unreadable_media")
        except OSError:
            return LocalAuditionResult.unavailable("unreadable_media")
        return path, media_type, size

    def _range(
        self, header: str | None, total: int,
    ) -> tuple[int, int, int]:
        if header is None:
            return 0, total - 1, 200
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", header.strip())
        if match is None or not any(match.groups()) or total <= 0:
            raise AuditionRangeNotSatisfiable(total)
        start_text, end_text = match.groups()
        if start_text:
            start = int(start_text)
            end = int(end_text) if end_text else min(
                total - 1, start + self._max_range_bytes - 1,
            )
        else:
            suffix = int(end_text)
            if suffix <= 0 or suffix > self._max_range_bytes:
                raise AuditionRangeNotSatisfiable(total)
            start = max(0, total - suffix)
            end = total - 1
        if (
            start < 0 or start >= total or end < start or end >= total
            or end - start + 1 > self._max_range_bytes
        ):
            raise AuditionRangeNotSatisfiable(total)
        return start, end, 206

    def _read(self, path: Path, start: int, length: int) -> Iterator[bytes]:
        with path.open("rb") as media:
            media.seek(start)
            remaining = length
            while remaining:
                chunk = media.read(min(self._chunk_bytes, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk
