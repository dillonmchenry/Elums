"""Structure, beats, downbeats, tempo — Sun Oct 4 (N1 of
IMPLEMENTATION_PLAN_2026-10-04.md). Mirrors elums/separation/engine.py's
shape exactly: a DB/Procrastinate-free blocking function, called via
`asyncio.to_thread` from elums/ingest/tasks.py, so it stays unit-testable
without a database.

Model: all-in-one-infer==3.1.0's default `harmonix-all` — an 8-fold
ensemble (~300K params/fold), not one checkpoint. Resolved by running it
once rather than guessing; see config/models.yaml's `structure_beats`
entry and PROGRESS.md's Day 2 section for the full finding (EC-3).

Per IMPLEMENTATION_PLAN_2026-10-04.md §3 (a settled deviation from the
schedule's `--stems-from-dir` line): this runs the package's OWN HTDemucs
separation on the ORIGINAL uploaded mix, not Saturday's 2-stem Mel-Band
RoFormer output — the structure model's embeddings are shaped
[stems=4, time, 24] (bass/drums/other/vocals), and substituting
other=instrumental with silent bass/drums would run it off its training
distribution for exactly the beat/downbeat/section outputs this stage
exists to produce. Cost is the extra ~20-40s of GPU time; it shares the
`gpu:separation` lock in elums/ingest/tasks.py so it never runs
concurrently with Saturday's separation job.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

CHECKPOINT_SIZE_BYTES = 11_534_336  # 8 harmonix folds, ~1.4 MB each — config/models.yaml


class StructureAnalysisError(Exception):
    """all-in-one-infer raised, or ffmpeg's WAV conversion step failed.
    No special retry semantics here (unlike separation's
    CheckpointNotReadyError) — the model downloads its own weights from
    HuggingFace on first use rather than requiring a pre-staged local
    file, so there is no "not ready yet" state to distinguish from a
    genuine failure."""


@dataclass(frozen=True)
class Section:
    start_s: float
    end_s: float
    label: str


@dataclass(frozen=True)
class StructureOutput:
    bpm: float | None  # None on input with no detectable beat (e.g. pure silence)
    beats: list[float]
    downbeats: list[float]
    sections: list[Section]
    duration_ms: int
    vram_peak_mb: float


def _ensure_wav(source_path: Path, work_dir: Path) -> Path:
    """EC-5 (Oct 4 plan §2): all-in-one-infer's 3.1.0 release decodes
    WAV/FLAC via `soundfile` but MP3 via `torchaudio`, which needs the
    separate `torchcodec` package on torchaudio>=2.11 — not installed
    here (§11.6: keep the gpu image's dependency surface deliberately
    small). Converting once via ffmpeg (already in the Dockerfile's
    shared `base` stage) sidesteps that entirely rather than adding a
    second MP3 decode path alongside the one `elums/ingest/probe.py`
    already trusts."""
    if source_path.suffix.lower() in {".wav", ".flac"}:
        return source_path

    wav_path = work_dir / "source.wav"
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", str(source_path), "-ar", "44100", str(wav_path)],
        capture_output=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise StructureAnalysisError(
            f"ffmpeg WAV conversion failed: {result.stderr.decode('utf-8', errors='replace')}"
        )
    return wav_path


def run_structure(source_path: Path, work_dir: Path, model_root: Path) -> StructureOutput:
    # Must happen BEFORE importing torch/allin1_infer: torch.hub.set_dir()
    # only affects downloads issued after the call, and HF_HOME is read at
    # import time by huggingface_hub. Both point at ${MODEL_ROOT} (never a
    # literal path — elums/config.py's Settings.model_root) so weights
    # survive container rebuilds instead of landing in the ephemeral
    # /root/.cache that a `docker compose run --rm` discards. Verified
    # directly Oct 4 2026 that torch.hub does NOT honor a bare TORCH_HOME
    # env var for this package's HTDemucs checkpoint download — it must
    # be set via torch.hub.set_dir(), not the environment.
    import os

    os.environ.setdefault("HF_HOME", str(model_root / "hf-cache"))

    import torch

    torch.hub.set_dir(str(model_root / "torch-cache"))

    from allin1_infer import analyze

    work_dir.mkdir(parents=True, exist_ok=True)
    wav_path = _ensure_wav(source_path, work_dir)

    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()

    t0 = time.monotonic()
    try:
        # multiprocess=False: this job already holds the `gpu:separation`
        # lock (only one GPU-bound job runs at a time, §4 of the approach
        # doc), so spawning a worker pool for spectrogram extraction buys
        # nothing but adds a failure mode (shared-memory limits inside a
        # container) for a stage that is not the bottleneck here.
        result = analyze(
            str(wav_path),
            out_dir=str(work_dir / "results"),
            model="harmonix-all",
            multiprocess=False,
        )
    except Exception as exc:  # noqa: BLE001 — all-in-one-infer's own exceptions land here
        raise StructureAnalysisError(f"Structure analysis failed: {exc}") from exc

    duration_ms = int((time.monotonic() - t0) * 1000)
    vram_peak_mb = (
        torch.cuda.max_memory_allocated() / 1024 / 1024 if torch.cuda.is_available() else 0.0
    )

    sections = [
        Section(start_s=float(seg.start), end_s=float(seg.end), label=seg.label)
        for seg in (result.segments or [])
    ]

    return StructureOutput(
        bpm=float(result.bpm) if result.bpm is not None else None,
        beats=[float(b) for b in (result.beats or [])],
        downbeats=[float(d) for d in (result.downbeats or [])],
        sections=sections,
        duration_ms=duration_ms,
        vram_peak_mb=vram_peak_mb,
    )
