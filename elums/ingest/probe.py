"""ffprobe sniffing for upload validation — M7. Never trust the client's
Content-Type header or the filename extension; ask ffprobe what's
actually in the file. ffmpeg/ffprobe live in the Dockerfile's shared
`base` stage (moved there directly Oct 3 2026, M7) so this works in both
the api and gpu-worker images.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path


class UndecodableAudioError(Exception):
    """No decodable audio stream — ffprobe either exited non-zero or
    found zero audio streams in the file."""


@dataclass(frozen=True)
class AudioProbe:
    duration_s: float
    codec_name: str
    title: str | None = None
    artist: str | None = None


async def probe_audio(path: Path) -> AudioProbe:
    # Mon Oct 5 (L1): `format_tags=title,artist` added alongside the
    # existing stream/format entries — `songs` had `title` but no
    # `artist` (IMPLEMENTATION_PLAN_2026-10-05.md §4's "metadata gap"),
    # and LRCLIB's `/api/get` needs both. Never trust the client's
    # multipart `title` field alone for LRCLIB lookups; the file's own
    # ID3/vorbis tags are read here the same way codec/duration already
    # are, as one more thing never taken from the client at face value.
    proc = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=codec_name:format=duration:format_tags=title,artist",
        "-of",
        "json",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise UndecodableAudioError(stderr.decode("utf-8", errors="replace"))

    try:
        payload = json.loads(stdout)
        streams = payload.get("streams") or []
        if not streams:
            raise UndecodableAudioError("ffprobe found no audio stream")
        codec_name = streams[0].get("codec_name", "unknown")
        duration_s = float(payload["format"]["duration"])
        tags = payload["format"].get("tags") or {}
        title = tags.get("title") or None
        artist = tags.get("artist") or None
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        raise UndecodableAudioError(f"could not parse ffprobe output: {exc}") from exc

    return AudioProbe(duration_s=duration_s, codec_name=codec_name, title=title, artist=artist)


def split_artist_title_from_filename(filename: str) -> tuple[str | None, str | None]:
    """Fallback when the file carries no artist/title tags: split the
    stem on the first ``" - "`` — the smallest change that makes LRCLIB
    usable per the Oct 5 plan's L1 §1. Returns (artist, title), either of
    which may be None if the filename doesn't contain the separator."""
    stem = Path(filename).stem
    if " - " not in stem:
        return None, None
    artist, _, title = stem.partition(" - ")
    artist, title = artist.strip(), title.strip()
    return (artist or None), (title or None)
