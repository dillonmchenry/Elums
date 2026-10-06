"""Key estimation — Sun Oct 4 (N2 of IMPLEMENTATION_PLAN_2026-10-04.md).

Krumhansl-Schmuckler profile correlation over the instrumental's chroma
(ELUMS_TECHNICAL_APPROACH.md §5). No model, no download — a classical DSP
estimator chosen partly because Essentia's tuned alternative is AGPL-3.0
and this is code Smule deploys internally (§5's licensing posture).

Known weakness, documented rather than hidden: KS makes well-known
relative-major/minor and circle-of-fifths confusions. §5 says to
cross-check this against the note histogram once Tuesday's RMVPE track
exists — this module persists the full 24-way correlation vector (not
just the winner) specifically so that cross-check has something to
reconcile against.
"""

from __future__ import annotations

from dataclasses import dataclass

import librosa
import numpy as np

# Tue Oct 6: the profile constants and the pure correlation function now
# live in elums/ingest/key_profiles.py (no librosa import there) so
# elums/ingest/notes.py's T2 note-histogram cross-check can reuse them
# without pulling librosa into the host `dev` test environment. Re-bound
# to the original private names here so this module's own call site
# (estimate_key, below) and existing tests/test_structure.py imports
# (`from elums.ingest.key import _correlate_all_candidates`,
# `_MAJOR_PROFILE`) keep working unchanged.
from elums.ingest.key_profiles import MAJOR_PROFILE as _MAJOR_PROFILE
from elums.ingest.key_profiles import PITCH_CLASSES as _PITCH_CLASSES
from elums.ingest.key_profiles import correlate_all_candidates as _correlate_all_candidates


@dataclass(frozen=True)
class KeyEstimate:
    tonic: str
    mode: str
    confidence: float
    correlations: list[tuple[str, str, float]]  # all 24, for Tuesday's note-histogram cross-check


def estimate_key(instrumental_path: str) -> KeyEstimate:
    y, sr = librosa.load(instrumental_path, sr=None, mono=True)
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    chroma_vector = chroma.mean(axis=1)

    candidates = _correlate_all_candidates(chroma_vector)
    best_tonic, best_mode, best_corr = candidates[0]
    second_corr = candidates[1][2]

    return KeyEstimate(
        tonic=best_tonic,
        mode=best_mode,
        confidence=best_corr - second_corr,
        correlations=candidates,
    )
