"""Krumhansl-Schmuckler profile correlation — the pure-math core shared
by elums/ingest/key.py (chroma over the instrumental) and
elums/ingest/notes.py (duration-weighted note-pitch-class histogram, T2's
cross-check). Split out Tue Oct 6 specifically so notes.py's
deterministic layer can use it WITHOUT pulling in librosa (key.py imports
librosa at module scope for `estimate_key`'s own `librosa.load`/
`chroma_cqt` calls) — tests/test_notes.py runs on the host `dev`
environment, which never has librosa installed (gpu-only dependency
group).
"""

from __future__ import annotations

import numpy as np

# Krumhansl & Kessler (1990) key profiles, rooted at C. All 24 candidates
# (12 tonics x 2 modes) are the 12 cyclic rotations of each profile.
MAJOR_PROFILE = np.array(
    [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
)
MINOR_PROFILE = np.array(
    [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
)

PITCH_CLASSES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def correlate_all_candidates(chroma_vector: np.ndarray) -> list[tuple[str, str, float]]:
    """Returns (tonic, mode, correlation) for all 24 candidates, sorted
    best-first. Pearson correlation, not cosine similarity — KS's own
    formulation and what makes "confidence = gap between best and
    second-best" meaningful."""
    candidates: list[tuple[str, str, float]] = []
    chroma_centered = chroma_vector - chroma_vector.mean()
    for mode, profile in (("major", MAJOR_PROFILE), ("minor", MINOR_PROFILE)):
        profile_centered = profile - profile.mean()
        for rotation in range(12):
            rotated = np.roll(profile_centered, rotation)
            denom = np.linalg.norm(chroma_centered) * np.linalg.norm(rotated)
            corr = float(np.dot(chroma_centered, rotated) / denom) if denom > 0 else 0.0
            candidates.append((PITCH_CLASSES[rotation], mode, corr))
    candidates.sort(key=lambda c: c[2], reverse=True)
    return candidates
