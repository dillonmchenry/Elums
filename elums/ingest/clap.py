"""CLAP embedding — Tue Oct 6 (T5 of IMPLEMENTATION_PLAN_2026-10-06.md).
DB-free and blocking, same shape as the rest of elums/ingest/; called via
`asyncio.to_thread` from `run_clap_embedding` in elums/ingest/tasks.py,
which is deferred fire-and-forget AFTER `run_note_grid` sets the ingest
job `SUCCEEDED` — a CLAP failure must never fail an ingest job (that
task's own try/except is where this is enforced, not here).

EC-4's resolution: `models/clap-music-speech/` is laion's
larger_clap_music_and_speech checkpoint, loaded via `transformers`'
`ClapModel`/`ClapProcessor` from `settings.model_root` (never a literal
path). 48 kHz input, 512-d pooled output — both confirmed against the
checkpoint's own `config.json` before this module was written.
"""

from __future__ import annotations

import numpy as np

CLAP_SAMPLE_RATE = 48_000
CLAP_EMBEDDING_DIM = 512
CLAP_MODEL_DIRNAME = "clap-music-speech"


class ClapEmbeddingError(Exception):
    """The checkpoint failed to load, or the forward pass raised."""


def embed_audio(audio_path: str, model_root) -> np.ndarray:  # noqa: ANN001 — Path, untyped to avoid importing it twice
    """Returns a single L2-normalized 512-d float32 vector for the whole
    track (CLAP's own pooled audio embedding — no per-frame output)."""
    import os

    os.environ.setdefault("HF_HOME", str(model_root / "hf-cache"))

    import librosa
    import torch
    from transformers import ClapModel, ClapProcessor

    try:
        audio, _sr = librosa.load(audio_path, sr=CLAP_SAMPLE_RATE, mono=True)
    except Exception as exc:  # noqa: BLE001 — librosa/soundfile/audioread's own exceptions
        raise ClapEmbeddingError(f"Could not decode audio for CLAP: {exc}") from exc

    model_path = str(model_root / CLAP_MODEL_DIRNAME)
    try:
        processor = ClapProcessor.from_pretrained(model_path)
        model = ClapModel.from_pretrained(model_path)
    except Exception as exc:  # noqa: BLE001 — transformers' own loading exceptions
        raise ClapEmbeddingError(f"Could not load CLAP checkpoint: {exc}") from exc

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = model.to(device).eval()

    try:
        # `audios=` is accepted upstream but deprecated under
        # transformers==5.9.0 (raises, not just warns) — `audio=` is the
        # current kwarg name. Verified directly Oct 6 2026 against the
        # real checkpoint, not guessed from docs.
        inputs = processor(audio=audio, sampling_rate=CLAP_SAMPLE_RATE, return_tensors="pt")
        inputs = {k: v.to(device) for k, v in inputs.items()}
        with torch.inference_mode():
            audio_outputs = model.get_audio_features(**inputs)
    except Exception as exc:  # noqa: BLE001 — model forward pass
        raise ClapEmbeddingError(f"CLAP forward pass failed: {exc}") from exc

    # transformers==5.9.0 returns a BaseModelOutputWithPooling, not a bare
    # tensor — verified directly against the real checkpoint, not
    # assumed from older docs/examples. `.pooler_output` is the
    # projected, ALREADY L2-normalized 512-d embedding (the model's own
    # `get_audio_features` applies `F.normalize` before returning).
    embedding = audio_outputs.pooler_output
    vector = embedding.squeeze(0).float().cpu().numpy()
    if vector.shape[0] != CLAP_EMBEDDING_DIM:
        raise ClapEmbeddingError(
            f"Unexpected CLAP embedding dimension: {vector.shape[0]} (expected {CLAP_EMBEDDING_DIM})"
        )

    norm = float(np.linalg.norm(vector))
    if norm > 0:
        vector = vector / norm
    return vector.astype(np.float32)
