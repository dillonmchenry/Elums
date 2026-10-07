"""Runs the full ingest chain on every real song in data/samples/ via the
live API, then builds a per-song quality table from the structural
invariants + stage timings the plan's T6/M1 sections ask for.

Not a pytest module — this hits the live stack (API + DB), same
convention as the Day 2-4 one-off validation passes, just made reusable
and run across every data/samples/*.mp3 instead of two hand-run uploads.

Usage (from the repo root, host Python with httpx/psycopg available):
    .venv/Scripts/python.exe scripts/validate_sample_songs.py

Writes results/sample_song_quality.json and prints a Markdown table.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
import uuid
from pathlib import Path

import httpx
import psycopg

BASE_URL = "http://127.0.0.1:8080"
DB_DSN = "postgresql://elums:elums@127.0.0.1:5433/elums"
SAMPLES_DIR = Path(__file__).resolve().parent.parent / "data" / "samples"
RESULTS_PATH = Path(__file__).resolve().parent.parent / "results" / "sample_song_quality.json"
POLL_INTERVAL_S = 3
POLL_TIMEOUT_S = 420  # real songs run the full 7-stage chain; generous ceiling

STAGE_ORDER = (
    "separation",
    "structure_beats",
    "rms_vad",
    "lyrics",
    "ctc_alignment",
    "f0",
    "note_grid",
)


def register_and_login(client: httpx.Client) -> None:
    email = f"sample-validation-{uuid.uuid4().hex[:12]}@elums.demo"
    resp = client.post(
        "/api/auth/register",
        json={"email": email, "display_name": "Sample Validation", "password": "a-good-password"},
    )
    resp.raise_for_status()


def upload_song(client: httpx.Client, path: Path) -> str:
    with path.open("rb") as f:
        resp = client.post("/api/songs", files={"file": (path.name, f, "audio/mpeg")})
    resp.raise_for_status()
    return resp.json()["id"]


def poll_until_terminal(client: httpx.Client, song_id: str) -> dict:
    deadline = time.monotonic() + POLL_TIMEOUT_S
    last = {}
    while time.monotonic() < deadline:
        resp = client.get(f"/api/songs/{song_id}/ingest")
        resp.raise_for_status()
        last = resp.json()
        if last["status"] in ("succeeded", "failed"):
            return last
        time.sleep(POLL_INTERVAL_S)
    raise TimeoutError(f"song {song_id} did not reach a terminal status within {POLL_TIMEOUT_S}s (last={last})")


def fetch_bundle(client: httpx.Client, song_id: str) -> dict:
    resp = client.get(f"/api/songs/{song_id}")
    resp.raise_for_status()
    return resp.json()


def blob_path(sha256: str) -> str:
    return f"/blobs/{sha256[0:2]}/{sha256[2:4]}/{sha256}"


def fetch_chart(client: httpx.Client, chart_sha256: str) -> dict:
    resp = client.get(blob_path(chart_sha256))
    resp.raise_for_status()
    return resp.json()


def structural_checks(chart: dict) -> dict:
    words = chart.get("words", [])
    notes_all = chart.get("notes", [])
    notes = [n for n in notes_all if not n.get("is_vocable")]
    duration_s = chart.get("duration_s") or 0.0

    boundary_violations = 0
    for n in notes:
        try:
            syl = words[n["word_index"]]["syllables"][n["syllable_index"]]
        except (IndexError, KeyError, TypeError):
            boundary_violations += 1
            continue
        if n["start_s"] < syl["start_s"] - 1e-6 or n["end_s"] > syl["end_s"] + 1e-6:
            boundary_violations += 1

    out_of_range = sum(
        1 for n in notes_all if not (0 <= n["start_s"] <= duration_s and 0 <= n["end_s"] <= duration_s)
    )
    note_durs = [n["end_s"] - n["start_s"] for n in notes_all]

    return {
        "note_count": len(notes_all),
        "syllable_boundary_violations": boundary_violations,
        "syllable_boundary_violation_rate": (boundary_violations / len(notes)) if notes else None,
        "out_of_range_notes": out_of_range,
        "min_note_duration_s": min(note_durs) if note_durs else None,
        "median_note_duration_s": statistics.median(note_durs) if note_durs else None,
        "word_count": len(words),
        "bpm": chart.get("bpm"),
        "key_tonic": chart.get("key", {}).get("tonic"),
        "key_mode": chart.get("key", {}).get("mode"),
        "key_tonic_from_notes": chart.get("key", {}).get("tonic_from_notes"),
        "key_mode_from_notes": chart.get("key", {}).get("mode_from_notes"),
        "key_confidence_from_notes": chart.get("key", {}).get("confidence_from_notes"),
        "duration_s": duration_s,
    }


def fetch_db_extras(db_conn: psycopg.Connection, song_id: str) -> dict:
    with db_conn.cursor() as cur:
        cur.execute(
            """
            SELECT frame_rate_hz, voiced_frame_ratio, voiced_duration_s,
                   lyrics_source, word_count, syllable_count, vocable_event_count,
                   key_confidence, f0_blob_sha256
            FROM song_analyses WHERE song_id = %s
            """,
            (song_id,),
        )
        row = cur.fetchone()
    db_conn.commit()
    if row is None:
        return {}
    (
        frame_rate_hz, voiced_frame_ratio, voiced_duration_s,
        lyrics_source, word_count, syllable_count, vocable_event_count,
        key_confidence, f0_blob_sha256,
    ) = row
    return {
        "frame_rate_hz": frame_rate_hz,
        "voiced_frame_ratio": voiced_frame_ratio,
        "voiced_duration_s": voiced_duration_s,
        "lyrics_source": lyrics_source,
        "word_count_db": word_count,
        "syllable_count": syllable_count,
        "vocable_event_count": vocable_event_count,
        "key_confidence_chroma": key_confidence,
        "f0_blob_sha256": f0_blob_sha256,
    }


def fetch_f0_frame_count(client: httpx.Client, f0_blob_sha256: str | None) -> int | None:
    if not f0_blob_sha256:
        return None
    import io

    import numpy as np

    resp = client.get(blob_path(f0_blob_sha256))
    resp.raise_for_status()
    with np.load(io.BytesIO(resp.content)) as npz:
        return int(npz["f0_hz"].shape[0])


def fetch_stage_results(db_conn: psycopg.Connection, song_id: str) -> dict:
    with db_conn.cursor() as cur:
        cur.execute("SELECT stage_results FROM ingest_jobs WHERE song_id = %s", (song_id,))
        row = cur.fetchone()
    db_conn.commit()
    return row[0] if row else {}


def validate_one(client: httpx.Client, db_conn: psycopg.Connection, path: Path) -> dict:
    print(f"=== {path.name} ===", flush=True)
    result: dict = {"file": path.name}
    try:
        song_id = upload_song(client, path)
        result["song_id"] = song_id
        status = poll_until_terminal(client, song_id)
        result["final_status"] = status["status"]
        if status["status"] != "succeeded":
            result["error_message"] = status.get("error_message")
            return result

        bundle = fetch_bundle(client, song_id)
        chart_sha = bundle.get("chart_blob_sha256")
        if not chart_sha:
            result["error_message"] = "succeeded but no chart_blob_sha256 on the bundle"
            return result

        chart = fetch_chart(client, chart_sha)
        result.update(structural_checks(chart))
        result.update(fetch_db_extras(db_conn, song_id))

        f0_sha = result.get("f0_blob_sha256")
        frame_count = fetch_f0_frame_count(client, f0_sha)
        if frame_count is not None and result.get("frame_rate_hz") and result.get("duration_s"):
            expected = round(result["duration_s"] * result["frame_rate_hz"])
            result["f0_frame_count"] = frame_count
            result["f0_frame_count_expected"] = expected
            result["f0_frame_count_diff"] = frame_count - expected

        stage_results = fetch_stage_results(db_conn, song_id)
        result["stage_results"] = {
            stage: {
                "duration_ms": stage_results.get(stage, {}).get("duration_ms"),
                "vram_peak_mb": stage_results.get(stage, {}).get("vram_peak_mb"),
            }
            for stage in STAGE_ORDER
            if stage in stage_results
        }
    except Exception as exc:  # noqa: BLE001
        result["error_message"] = f"{type(exc).__name__}: {exc}"
    return result


def render_markdown_table(results: list[dict]) -> str:
    headers = [
        "File", "Status", "Duration (s)", "Note count", "Boundary violations",
        "Out-of-range", "F0 frame diff", "Voiced ratio (RMVPE vs VAD)",
        "Key (chroma vs notes)", "Lyrics source", "Vocable events",
    ]
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for r in results:
        if r.get("final_status") != "succeeded":
            lines.append(
                f"| {r['file']} | **{r.get('final_status', 'error')}** | - | - | - | - | - | - | - | - | - ({r.get('error_message', '')}) |"
            )
            continue
        voiced_rmvpe = r.get("voiced_frame_ratio")
        voiced_vad = (r.get("voiced_duration_s") / r["duration_s"]) if r.get("voiced_duration_s") and r.get("duration_s") else None
        voiced_cell = (
            f"{voiced_rmvpe:.3f} vs {voiced_vad:.3f}" if voiced_rmvpe is not None and voiced_vad is not None else "-"
        )
        key_cell = f"{r.get('key_tonic')} {r.get('key_mode')} vs {r.get('key_tonic_from_notes')} {r.get('key_mode_from_notes')}"
        viol = r.get("syllable_boundary_violations")
        viol_rate = r.get("syllable_boundary_violation_rate")
        viol_cell = f"{viol} ({viol_rate:.1%})" if viol is not None and viol_rate is not None else str(viol)
        lines.append(
            "| "
            + " | ".join(
                [
                    r["file"],
                    r.get("final_status", "?"),
                    f"{r.get('duration_s', 0):.1f}",
                    str(r.get("note_count", "-")),
                    viol_cell,
                    str(r.get("out_of_range_notes", "-")),
                    str(r.get("f0_frame_count_diff", "-")),
                    voiced_cell,
                    key_cell,
                    str(r.get("lyrics_source", "-")),
                    str(r.get("vocable_event_count", "-")),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def main() -> int:
    mp3_files = sorted(SAMPLES_DIR.glob("*.mp3"))
    if len(sys.argv) > 1:
        limit = int(sys.argv[1])
        mp3_files = mp3_files[:limit]
    if not mp3_files:
        print(f"no .mp3 files found in {SAMPLES_DIR}", file=sys.stderr)
        return 1
    print(f"validating {len(mp3_files)} songs: {[p.name for p in mp3_files]}")

    results: list[dict] = []
    with httpx.Client(base_url=BASE_URL, timeout=30.0) as client, psycopg.connect(DB_DSN) as db_conn:
        register_and_login(client)
        for path in mp3_files:
            results.append(validate_one(client, db_conn, path))

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nwrote {RESULTS_PATH}\n")
    print(render_markdown_table(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
