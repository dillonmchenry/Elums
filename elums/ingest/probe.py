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


async def probe_audio(path: Path) -> AudioProbe:
    proc = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=codec_name:format=duration",
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
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        raise UndecodableAudioError(f"could not parse ffprobe output: {exc}") from exc

    return AudioProbe(duration_s=duration_s, codec_name=codec_name)
