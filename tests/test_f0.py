"""Tue Oct 6 (T1): deterministic-layer unit tests for the pure parts of
elums/ingest/f0.py — the binary blob pack/unpack round-trip and the
voiced-frame-ratio helper. The RMVPE forward pass itself needs torch +
the vendored model and is exercised only end-to-end (not unit-tested),
same "tests on the logic, not the models" precedent as
tests/test_structure.py.
"""

from __future__ import annotations

import numpy as np

from elums.ingest.f0 import FRAME_RATE_HZ, pack_f0_blob, unpack_f0_blob, voiced_frame_ratio


def test_frame_rate_is_100hz_per_rmvpes_native_hop() -> None:
    assert FRAME_RATE_HZ == 100.0


def test_pack_unpack_round_trips_float16_arrays() -> None:
    f0_hz = np.array([0.0, 220.0, 440.5, 0.0, 110.25], dtype=np.float16)
    confidence = np.array([0.0, 0.9, 0.8, 0.0, 0.5], dtype=np.float16)

    blob = pack_f0_blob(f0_hz, confidence)
    f0_out, conf_out = unpack_f0_blob(blob)

    assert f0_out.dtype == np.float16
    assert conf_out.dtype == np.float16
    np.testing.assert_array_equal(f0_out, f0_hz)
    np.testing.assert_array_equal(conf_out, confidence)


def test_pack_f0_blob_is_small_binary_not_json() -> None:
    # §4's tiering rule: a 3-minute take is ~18,000 frames, ~70KB per
    # channel as float16 — this is a sanity check that the blob is in
    # that ballpark, not a multi-hundred-KB JSON text dump.
    n_frames = 18_000
    f0_hz = np.random.default_rng(0).uniform(0, 500, n_frames).astype(np.float16)
    confidence = np.random.default_rng(1).uniform(0, 1, n_frames).astype(np.float16)

    blob = pack_f0_blob(f0_hz, confidence)

    assert len(blob) < 150_000  # well under JSON's text-encoding overhead for the same data


def test_voiced_frame_ratio_counts_nonzero_frames() -> None:
    f0_hz = np.array([0.0, 100.0, 100.0, 0.0, 100.0], dtype=np.float16)
    assert voiced_frame_ratio(f0_hz) == 0.6


def test_voiced_frame_ratio_on_empty_array_is_zero() -> None:
    assert voiced_frame_ratio(np.array([], dtype=np.float16)) == 0.0


def test_voiced_frame_ratio_all_unvoiced_is_zero() -> None:
    f0_hz = np.zeros(10, dtype=np.float16)
    assert voiced_frame_ratio(f0_hz) == 0.0
