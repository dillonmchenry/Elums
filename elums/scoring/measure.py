"""Per-note measurement — Wed Oct 7 (W4 of IMPLEMENTATION_PLAN_2026-10-07.md).

SecondPass §4: octave folding (§4.2), arrival detection with edge-margin
rejection (§4.3), core-window trimming+shifting (§4.4). Written
side-agnostic per the plan's own instruction — every function here takes
an `F0Track`-shaped pair of arrays (`f0_hz`, `confidence`) plus an
optional RMS dB track, and a list of note windows, never a `Performance`
object. Friday's reference-side measurement (SecondPass §4.5's `ref_*`
fields) reuses these exact functions over the song's own f0 blob; this
module must never import anything performance- or song-specific to keep
that true.

**Frozen** per the plan's own instruction — Friday's detectors consume
this: `NoteMeasurement(note_index, median_cents, pct_in_tune,
drift_cents_per_s, voiced_coverage, mean_voicing_confidence,
note_octave_offset, arrival_offset_ms, core_start_s, core_end_s,
user_rms_db, user_rms_relative_db, vibrato_rate_hz, vibrato_extent_cents,
scoop_cents, envelope_shape)`.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# §6.2's own thresholds — green <=25 cents, yellow 25-50, red >50.
CENTS_IN_TUNE_THRESHOLD = 25.0

EDGE_MARGIN_S = 0.02  # §4.3: 20ms edge-margin rejection
CORE_TRIM_S = 0.05  # §4.4: 50ms trimmed each side

# A note needs at least this much core duration for vibrato/scoop
# detection to mean anything — below it, these fields are None rather
# than a number computed from noise.
MIN_VIBRATO_WINDOW_S = 0.3
VIBRATO_RATE_MIN_HZ = 3.0  # below Sundberg's "wobble" cutoff is still reported, just bounded loosely
VIBRATO_RATE_MAX_HZ = 9.0


@dataclass(frozen=True)
class NoteMeasurement:
    note_index: int
    median_cents: float | None
    pct_in_tune: float | None
    drift_cents_per_s: float | None
    voiced_coverage: float
    mean_voicing_confidence: float
    note_octave_offset: int
    arrival_offset_ms: float | None
    core_start_s: float
    core_end_s: float
    user_rms_db: float | None
    user_rms_relative_db: float | None
    vibrato_rate_hz: float | None
    vibrato_extent_cents: float | None
    scoop_cents: float | None
    envelope_shape: str | None


def _midi_to_hz(midi: float) -> float:
    return 440.0 * 2.0 ** ((midi - 69.0) / 12.0)


def hz_to_cents_relative(f0_hz: np.ndarray, ref_midi: float) -> np.ndarray:
    """Cents deviation of every voiced frame from `ref_midi`. NaN where
    unvoiced (f0_hz <= 0) — never a bogus large deviation from log(0)."""
    ref_hz = _midi_to_hz(ref_midi)
    out = np.full(f0_hz.shape, np.nan, dtype=np.float64)
    voiced = f0_hz > 0
    out[voiced] = 1200.0 * np.log2(f0_hz[voiced].astype(np.float64) / ref_hz)
    return out


def fold_octave_cents(cents: np.ndarray) -> np.ndarray:
    """§4.2: per-frame +/-600-cent folding — brings any residual back
    into [-600, 600) by adding/subtracting whole octaves. NaN stays NaN."""
    folded = np.where(np.isnan(cents), np.nan, np.mod(cents + 600.0, 1200.0) - 600.0)
    return folded


def estimate_octave_shift(per_note_residual_semitones: list[float]) -> int:
    """§4.2: the global octave shift as the rounded median of per-note
    residuals (raw pitch minus the chart's expected pitch, in semitones),
    rounded to the nearest whole octave. `note_octave_offset` (per note,
    see `measure_note`) is surfaced separately — this is the one GLOBAL
    value applied uniformly before per-note measurement."""
    if not per_note_residual_semitones:
        return 0
    median_semitones = float(np.median(np.asarray(per_note_residual_semitones, dtype=np.float64)))
    return int(round(median_semitones / 12.0)) * 12


def detect_arrival(
    voiced_mask: np.ndarray,
    frame_rate_hz: float,
    note_start_s: float,
    note_end_s: float,
    mode: str = "onset",
) -> float | None:
    """§4.3: the first voiced frame inside [note_start_s, note_end_s),
    in `onset` mode (a fresh attack expected) or `continuation` mode (the
    previous note's voicing may already be running, so arrival at the
    window's very start is a legitimate zero, not a boundary artifact).
    Edge-margin rejection applies to the END of the window in both modes
    (an arrival detected only just before the note ends is almost
    certainly bleed from the NEXT note, never a real arrival for this
    one) and to the START as well in `onset` mode (a "late" onset within
    EDGE_MARGIN_S of the note's start is not distinguishable from
    on-time, so it's not rejected — only an onset detected suspiciously
    close to the FAR edge is). Returns `None` when no acceptable
    candidate exists — never a confident zero manufactured from nothing.
    """
    start_idx = int(round(note_start_s * frame_rate_hz))
    end_idx = int(round(note_end_s * frame_rate_hz))
    if end_idx <= start_idx or start_idx >= voiced_mask.shape[0] or start_idx < 0:
        return None
    end_idx = min(end_idx, voiced_mask.shape[0])
    window = voiced_mask[start_idx:end_idx]
    margin_frames = max(1, round(EDGE_MARGIN_S * frame_rate_hz))

    voiced_indices = np.flatnonzero(window)
    if voiced_indices.size == 0:
        return None
    arrival_idx = int(voiced_indices[0])

    # Reject an arrival so close to the far edge that it's indistinguishable
    # from bleed out of the NEXT note's onset, in both modes.
    if arrival_idx > window.shape[0] - margin_frames:
        return None
    if mode == "onset" and window.shape[0] <= margin_frames:
        return None

    return (arrival_idx / frame_rate_hz) * 1000.0


def core_window(note_start_s: float, note_end_s: float, arrival_offset_s: float = 0.0) -> tuple[float, float]:
    """§4.4: trims `CORE_TRIM_S` off each side of the (arrival-shifted)
    note span. A note too short to survive trimming collapses to its own
    midpoint (zero-length core) rather than inverting start>end."""
    shifted_start = note_start_s + arrival_offset_s
    core_start = shifted_start + CORE_TRIM_S
    core_end = note_end_s - CORE_TRIM_S
    if core_end <= core_start:
        midpoint = (shifted_start + note_end_s) / 2.0
        return midpoint, midpoint
    return core_start, core_end


def _linear_slope(x: np.ndarray, y: np.ndarray) -> float | None:
    if x.size < 2 or np.allclose(x, x[0]):
        return None
    coeffs = np.polyfit(x, y, 1)
    return float(coeffs[0])


def _detect_vibrato(cents_detrended: np.ndarray, frame_rate_hz: float, duration_s: float) -> tuple[float | None, float | None]:
    """Zero-crossing-based rate/extent estimate over a detrended cents
    signal — deliberately simple (no FFT), matching this module's "no
    model, no throwaway detector" precedent. A full cycle is two
    zero-crossings; rate = crossings / 2 / duration. `None` on too short
    a window or an implausible rate (outside a generous 3-9 Hz band —
    wider than Sundberg's 4.5-6.5 Hz "trained classical" range per §6.2's
    own instruction that pop vibrato is not classical vibrato)."""
    if duration_s < MIN_VIBRATO_WINDOW_S or cents_detrended.size < 4:
        return None, None
    signs = np.sign(cents_detrended)
    signs[signs == 0] = 1
    crossings = int(np.sum(signs[1:] != signs[:-1]))
    if crossings < 2:
        return None, None
    rate_hz = (crossings / 2.0) / duration_s
    extent_cents = float(np.ptp(cents_detrended))
    if not (VIBRATO_RATE_MIN_HZ <= rate_hz <= VIBRATO_RATE_MAX_HZ):
        return None, extent_cents if extent_cents > 0 else None
    return rate_hz, extent_cents


def measure_note(
    note_index: int,
    f0_hz: np.ndarray,
    confidence: np.ndarray,
    frame_rate_hz: float,
    note_start_s: float,
    note_end_s: float,
    target_midi: int,
    octave_shift_semitones: int = 0,
    arrival_mode: str = "onset",
    rms_db: np.ndarray | None = None,
    rms_frame_rate_hz: float | None = None,
    median_rms_db: float | None = None,
) -> NoteMeasurement:
    """Measures one note window against `target_midi` (the chart's
    expected pitch for this note), after applying the GLOBAL
    `octave_shift_semitones` (§4.2) to the user's raw pitch before
    comparing — so a user singing a whole octave down against the chart
    still measures as in-tune, with the shift itself surfaced on the
    performance, not swallowed."""
    start_idx = int(round(note_start_s * frame_rate_hz))
    end_idx = int(round(note_end_s * frame_rate_hz))
    start_idx = max(0, start_idx)
    end_idx = min(f0_hz.shape[0], max(start_idx, end_idx))

    full_f0 = f0_hz[start_idx:end_idx]
    full_conf = confidence[start_idx:end_idx]
    full_voiced = full_f0 > 0
    voiced_coverage = float(np.count_nonzero(full_voiced) / full_voiced.size) if full_voiced.size else 0.0
    mean_voicing_confidence = float(np.mean(full_conf)) if full_conf.size else 0.0

    voiced_mask_for_arrival = f0_hz > 0
    arrival_offset_ms = detect_arrival(voiced_mask_for_arrival, frame_rate_hz, note_start_s, note_end_s, arrival_mode)
    arrival_offset_s = (arrival_offset_ms / 1000.0) if arrival_offset_ms is not None else 0.0

    core_start_s, core_end_s = core_window(note_start_s, note_end_s, arrival_offset_s)
    core_start_idx = max(0, int(round(core_start_s * frame_rate_hz)))
    core_end_idx = min(f0_hz.shape[0], max(core_start_idx, int(round(core_end_s * frame_rate_hz))))

    core_f0 = f0_hz[core_start_idx:core_end_idx]
    shifted_midi = target_midi + octave_shift_semitones
    core_cents_raw = hz_to_cents_relative(core_f0, shifted_midi)
    core_cents = fold_octave_cents(core_cents_raw)
    voiced_core = ~np.isnan(core_cents)

    if np.any(voiced_core):
        cents_voiced = core_cents[voiced_core]
        median_cents = float(np.median(cents_voiced))
        pct_in_tune = float(np.mean(np.abs(cents_voiced) <= CENTS_IN_TUNE_THRESHOLD))
        times = np.flatnonzero(voiced_core) / frame_rate_hz
        drift_cents_per_s = _linear_slope(times, cents_voiced)
        detrended = cents_voiced - np.median(cents_voiced)
        duration_s = core_end_s - core_start_s
        vibrato_rate_hz, vibrato_extent_cents = _detect_vibrato(detrended, frame_rate_hz, duration_s)
        head = cents_voiced[: max(1, cents_voiced.size // 5)]
        scoop_cents = float(np.mean(head) - median_cents) if cents_voiced.size >= 3 else None
    else:
        median_cents = None
        pct_in_tune = None
        drift_cents_per_s = None
        vibrato_rate_hz = None
        vibrato_extent_cents = None
        scoop_cents = None

    note_octave_offset = 0
    if np.any(full_voiced):
        full_cents_raw = hz_to_cents_relative(full_f0, target_midi)
        residual_octaves = full_cents_raw[~np.isnan(full_cents_raw)] / 1200.0
        note_octave_offset = int(round(float(np.median(residual_octaves)))) if residual_octaves.size else 0

    user_rms_db = None
    user_rms_relative_db = None
    envelope_shape = None
    if rms_db is not None and rms_frame_rate_hz:
        rms_start = max(0, int(round(note_start_s * rms_frame_rate_hz)))
        rms_end = min(rms_db.shape[0], max(rms_start, int(round(note_end_s * rms_frame_rate_hz))))
        note_rms = rms_db[rms_start:rms_end]
        if note_rms.size:
            user_rms_db = float(np.mean(note_rms))
            if median_rms_db is not None:
                user_rms_relative_db = user_rms_db - median_rms_db
            if note_rms.size >= 2:
                slope = _linear_slope(np.arange(note_rms.size, dtype=np.float64), note_rms)
                if slope is not None:
                    envelope_shape = "rising" if slope > 0.5 else "falling" if slope < -0.5 else "flat"

    return NoteMeasurement(
        note_index=note_index,
        median_cents=median_cents,
        pct_in_tune=pct_in_tune,
        drift_cents_per_s=drift_cents_per_s,
        voiced_coverage=voiced_coverage,
        mean_voicing_confidence=mean_voicing_confidence,
        note_octave_offset=note_octave_offset,
        arrival_offset_ms=arrival_offset_ms,
        core_start_s=core_start_s,
        core_end_s=core_end_s,
        user_rms_db=user_rms_db,
        user_rms_relative_db=user_rms_relative_db,
        vibrato_rate_hz=vibrato_rate_hz,
        vibrato_extent_cents=vibrato_extent_cents,
        scoop_cents=scoop_cents,
        envelope_shape=envelope_shape,
    )
