"""Tue Oct 6 (T3): deterministic test for elums/ingest/chart.py's pure
dict-assembly half (`assemble_chart`). `compute_peaks` needs `soundfile`
(gpu-only dependency group) and is exercised end-to-end only, same
precedent as tests/test_structure.py.
"""

from __future__ import annotations

from elums.ingest.chart import CHART_VERSION, assemble_chart


def test_assemble_chart_is_versioned_and_carries_every_required_field() -> None:
    chart = assemble_chart(
        duration_s=180.0,
        bpm=120.0,
        key_tonic="C",
        key_mode="major",
        key_tonic_from_notes="C",
        key_mode_from_notes="major",
        key_confidence_from_notes=0.5,
        sections=[{"start_s": 0.0, "end_s": 10.0, "label": "intro"}],
        beats=[0.0, 0.5, 1.0],
        downbeats=[0.0],
        words=[{"text": "hi", "start_s": 0.0, "end_s": 0.5, "syllables": []}],
        notes=[{"start_s": 0.0, "end_s": 0.5, "midi": 60, "midi_raw": 60.1, "confidence": 0.9}],
        vocable_events=[],
        vocals_sha256="a" * 64,
        instrumental_sha256="b" * 64,
        peaks_sha256="c" * 64,
    )

    assert chart["version"] == CHART_VERSION
    assert chart["duration_s"] == 180.0
    assert chart["key"]["tonic"] == "C"
    assert chart["key"]["tonic_from_notes"] == "C"
    assert chart["stems"]["vocals_sha256"] == "a" * 64
    assert chart["stems"]["instrumental_sha256"] == "b" * 64
    assert chart["peaks_sha256"] == "c" * 64
    assert len(chart["sections"]) == 1
    assert len(chart["notes"]) == 1
