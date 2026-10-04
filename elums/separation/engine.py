"""Mel-Band RoFormer vocal separation — the actual (blocking, GPU-bound)
work. Kept free of any DB/Procrastinate import so it's a plain function:
`elums/separation/task.py` runs it via `asyncio.to_thread`.

Checkpoint identity resolved for EC-5 and recorded in config/models.yaml
and docs/licensing-audit.md: `vocals_mel_band_roformer.ckpt`, Kimberley
Jensen's Mel-Band RoFormer, MIT (relicensed from GPL-3.0, April 2026).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import torch
from audio_separator.separator import Separator

CHECKPOINT_FILENAME = "vocals_mel_band_roformer.ckpt"

# EC-4: audio-separator's own mdxc default segment_size is 256. §3.4 flags
# separation as "the one tight fit on 8-12 GB" — start reduced, measure the
# peak, and only raise it if there's headroom. Verified directly Oct 3
# 2026 (M8): 128 peaks at ~1.7 GB on a 3-second clip on the local RTX 3070
# (8 GB) — comfortable room to spare, revisit on a full-length song.
DEFAULT_SEGMENT_SIZE = 128
MIN_SEGMENT_SIZE = 32


class CheckpointNotReadyError(Exception):
    """The checkpoint isn't on disk yet (M1's background download may
    still be running, or hasn't started on a fresh machine). Procrastinate
    retries this with backoff rather than failing the job outright — see
    the `retry=` on elums/separation/task.py's `separate` task."""


@dataclass(frozen=True)
class SeparationOutput:
    vocals_path: Path
    instrumental_path: Path
    duration_ms: int
    vram_peak_mb: float


def run_separation(
    source_path: Path, output_dir: Path, model_root: Path, segment_size: int
) -> SeparationOutput:
    checkpoint_path = model_root / CHECKPOINT_FILENAME
    if not checkpoint_path.exists():
        raise CheckpointNotReadyError(f"{checkpoint_path} not found")

    output_dir.mkdir(parents=True, exist_ok=True)

    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()

    t0 = time.monotonic()
    separator = Separator(
        model_file_dir=str(model_root),
        output_dir=str(output_dir),
        output_format="FLAC",  # lossless, ~half the bytes of WAV — §output contract
        mdxc_params={
            "segment_size": segment_size,
            "override_model_segment_size": True,
            "batch_size": None,
            "overlap": None,
            "pitch_shift": 0,
        },
    )
    separator.load_model(model_filename=CHECKPOINT_FILENAME)
    # `custom_output_names` is what gets clean `vocals.flac`/`instrumental.flac`
    # filenames instead of this model's default stem name of "other" for
    # the non-vocal stem (verified directly Oct 3 2026 by running it once
    # and reading the actual output filenames — the docs don't name it).
    separator.separate(
        str(source_path), custom_output_names={"vocals": "vocals", "other": "instrumental"}
    )
    duration_ms = int((time.monotonic() - t0) * 1000)

    vram_peak_mb = (
        torch.cuda.max_memory_allocated() / 1024 / 1024 if torch.cuda.is_available() else 0.0
    )

    return SeparationOutput(
        vocals_path=output_dir / "vocals.flac",
        instrumental_path=output_dir / "instrumental.flac",
        duration_ms=duration_ms,
        vram_peak_mb=vram_peak_mb,
    )
