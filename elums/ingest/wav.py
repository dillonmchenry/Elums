"""WAV header assembly — Thu Oct 8 (X0 of IMPLEMENTATION_PLAN_2026-10-08.md).

X0's own "unresolved interface decision," resolved as option (a): the
client (`frontend/src/audio/encodeWorker.ts`) uploads headerless 16-bit
PCM chunks, because a take's final length isn't known until it stops —
chunk 0 cannot carry a correct WAV header. The server's own `complete`
step (``elums/api/routers/performances.py::complete_performance``)
prepends a real header once the assembled byte count is known, so
``probe_audio`` (and anything else downstream) sees a valid file.

Byte-for-byte port of ``frontend/src/audio/wav.ts::buildWavHeader`` —
both sides are unit-tested against the same fixed expected-byte vector
(``tests/test_wav.py``, ``frontend/src/audio/wav.test.ts``).
"""

from __future__ import annotations

import struct


def build_wav_header(
    sample_rate: int, data_length: int, num_channels: int = 1, bits_per_sample: int = 16
) -> bytes:
    """Canonical 44-byte PCM WAV header for ``data_length`` bytes of
    ``bits_per_sample``-bit PCM audio at ``sample_rate``."""
    block_align = num_channels * bits_per_sample // 8
    byte_rate = sample_rate * block_align
    return b"".join(
        [
            b"RIFF",
            struct.pack("<I", 36 + data_length),
            b"WAVE",
            b"fmt ",
            struct.pack("<I", 16),  # fmt chunk size
            struct.pack("<H", 1),  # PCM format tag
            struct.pack("<H", num_channels),
            struct.pack("<I", sample_rate),
            struct.pack("<I", byte_rate),
            struct.pack("<H", block_align),
            struct.pack("<H", bits_per_sample),
            b"data",
            struct.pack("<I", data_length),
        ]
    )
