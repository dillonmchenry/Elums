"""F0 (pitch) extraction — Tue Oct 6 (T1 of
IMPLEMENTATION_PLAN_2026-10-06.md). DB-free and blocking, mirroring
elums/ingest/structure.py: called via `asyncio.to_thread` from
elums/ingest/tasks.py.

EC-1's resolution: there is no PyTorch RMVPE package on PyPI, only the
checkpoint (models/rmvpe.pt). Vendored RVC-Project's own inference code
into elums/vendor/rmvpe/ (MIT, see that directory's LICENSE) rather than
`rmvpe-onnx` (a different checkpoint, CPU-only onnxruntime) — this keeps
F0 on the GPU and uses the weights already downloaded/audited.

RMVPE's native hop is 160 samples at 16 kHz -> a fixed 100 Hz frame rate.
Resampling to 16 kHz happens inside this module (`extract_f0` accepts any
input the vocal stem happens to be at) — never pushed onto the caller.

**Frozen interface — Wednesday's scoring consumes this directly:**
`F0Track(frame_rate_hz, f0_hz, confidence)`, frame i at `i / frame_rate_hz`
seconds. Both arrays are float16 (§4's data-tiering rule: a 3-minute
take is ~18,000 frames, ~70 KB per channel as a binary float16 blob —
this is why the blob format is binary, not JSON).
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

_RMVPE_SAMPLE_RATE = 16_000
_RMVPE_HOP_LENGTH = 160
FRAME_RATE_HZ = _RMVPE_SAMPLE_RATE / _RMVPE_HOP_LENGTH  # 100.0


class F0ExtractionError(Exception):
    """RMVPE's own forward pass raised, or the vocal stem could not be
    decoded/resampled."""


@dataclass(frozen=True)
class F0Track:
    frame_rate_hz: float
    f0_hz: np.ndarray  # float16, Hz, 0.0 where unvoiced
    confidence: np.ndarray  # float16, RMVPE's own salience-peak signal
    duration_ms: int
    vram_peak_mb: float


def extract_f0(vocals_path: str, model_root) -> F0Track:  # noqa: ANN001 — Path, untyped to avoid importing it twice
    """Loads the vocal stem at any sample rate, resamples to 16 kHz mono
    for RMVPE, and returns one F0/confidence pair per 10ms frame."""
    import os

    os.environ.setdefault("HF_HOME", str(model_root / "hf-cache"))

    import librosa
    import torch

    from elums.vendor.rmvpe.model import RMVPE

    try:
        audio, _sr = librosa.load(vocals_path, sr=_RMVPE_SAMPLE_RATE, mono=True)
    except Exception as exc:  # noqa: BLE001 — librosa/soundfile/audioread's own exceptions
        raise F0ExtractionError(f"Could not decode vocal stem: {exc}") from exc

    device = "cuda" if torch.cuda.is_available() else "cpu"
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()

    t0 = time.monotonic()
    try:
        model_path = str(model_root / "rmvpe.pt")
        rmvpe = RMVPE(model_path, device=device)
        f0_hz, confidence = rmvpe.infer_from_audio(audio)
    except Exception as exc:  # noqa: BLE001 — RMVPE's own forward pass
        raise F0ExtractionError(f"RMVPE inference failed: {exc}") from exc
    duration_ms = int((time.monotonic() - t0) * 1000)
    vram_peak_mb = (
        torch.cuda.max_memory_allocated() / 1024 / 1024 if torch.cuda.is_available() else 0.0
    )

    return F0Track(
        frame_rate_hz=FRAME_RATE_HZ,
        f0_hz=f0_hz.astype(np.float16),
        confidence=confidence.astype(np.float16),
        duration_ms=duration_ms,
        vram_peak_mb=vram_peak_mb,
    )


def voiced_frame_ratio(f0_hz: np.ndarray) -> float:
    """Fraction of frames with a nonzero (voiced) F0 — compared against
    `voiced_duration_s / duration_s` from the VAD stage per T1's own
    validation note; a large gap means the resample or hop is wrong."""
    if f0_hz.size == 0:
        return 0.0
    return float(np.count_nonzero(f0_hz) / f0_hz.size)


def pack_f0_blob(f0_hz: np.ndarray, confidence: np.ndarray) -> bytes:
    """Binary float16 blob, not JSON — §4's tiering rule. `np.savez`
    into an in-memory buffer keeps both arrays (plus their shapes/dtype)
    in one self-describing file, loadable with `np.load` on the other
    end without a bespoke header format."""
    import io

    buf = io.BytesIO()
    np.savez(buf, f0_hz=f0_hz.astype(np.float16), confidence=confidence.astype(np.float16))
    return buf.getvalue()


def unpack_f0_blob(data: bytes) -> tuple[np.ndarray, np.ndarray]:
    import io

    buf = io.BytesIO(data)
    with np.load(buf) as npz:
        return npz["f0_hz"], npz["confidence"]
