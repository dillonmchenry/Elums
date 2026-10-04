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

# Krumhansl & Kessler (1990) key profiles, rooted at C. All 24 candidates
# (12 tonics x 2 modes) are the 12 cyclic rotations of each profile.
_MAJOR_PROFILE = np.array(
    [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
)
_MINOR_PROFILE = np.array(
    [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
)

_PITCH_CLASSES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _correlate_all_candidates(chroma_vector: np.ndarray) -> list[tuple[str, str, float]]:
    """Returns (tonic, mode, correlation) for all 24 candidates, sorted
    best-first. Pearson correlation, not cosine similarity — KS's own
    formulation and what makes the "confidence = gap between best and
    second-best" framing in run_key_estimation meaningful."""
    candidates: list[tuple[str, str, float]] = []
    chroma_centered = chroma_vector - chroma_vector.mean()
    for mode, profile in (("major", _MAJOR_PROFILE), ("minor", _MINOR_PROFILE)):
        profile_centered = profile - profile.mean()
        for rotation in range(12):
            rotated = np.roll(profile_centered, rotation)
            denom = np.linalg.norm(chroma_centered) * np.linalg.norm(rotated)
            corr = float(np.dot(chroma_centered, rotated) / denom) if denom > 0 else 0.0
            candidates.append((_PITCH_CLASSES[rotation], mode, corr))
    candidates.sort(key=lambda c: c[2], reverse=True)
    return candidates


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
