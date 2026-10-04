"""M8: separation end-to-end, against the live stack. Marked `gpu` — skip
this file (`pytest -m "not gpu"`) on a machine with no `gpu-worker`
running or no checkpoint on disk.

Polls the `ingest_jobs`/`stems` tables directly rather than through an
HTTP endpoint: no `GET /api/songs/{id}` status route exists yet (a later
milestone's job, once the SPA needs to poll it) — this test only needs to
observe the result, not exercise an API surface that doesn't exist.
"""

from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

import httpx
import psycopg
import pytest

pytestmark = pytest.mark.gpu

FIXTURES_DIR = Path(__file__).parent / "fixtures"
POLL_TIMEOUT_S = 90
POLL_INTERVAL_S = 2


def _unique_email() -> str:
    return f"pytest-{uuid.uuid4().hex[:12]}@elums.demo"


@pytest.fixture
def logged_in_client(base_url: str) -> httpx.Client:
    with httpx.Client(base_url=base_url, timeout=15.0) as c:
        email = _unique_email()
        register = c.post(
            "/api/auth/register",
            json={"email": email, "display_name": "Separation Test User", "password": "a-good-password"},
        )
        assert register.status_code == 201
        yield c


@pytest.fixture
def db_conn():
    dsn = os.environ.get("TEST_DB_DSN", "postgresql://elums:elums@127.0.0.1:5433/elums")
    with psycopg.connect(dsn) as conn:
        yield conn


def _poll_ingest_job_status(db_conn: psycopg.Connection, song_id: str) -> str:
    deadline = time.monotonic() + POLL_TIMEOUT_S
    while time.monotonic() < deadline:
        with db_conn.cursor() as cur:
            cur.execute("SELECT status FROM ingest_jobs WHERE song_id = %s", (song_id,))
            row = cur.fetchone()
        # Force this connection off its (idle-in-transaction) snapshot so
        # the next poll actually observes commits made by the worker's
        # own, separate connection in the meantime.
        db_conn.commit()
        if row is not None and row[0] in ("SUCCEEDED", "FAILED"):
            return row[0]
        time.sleep(POLL_INTERVAL_S)
    pytest.fail(f"ingest_job for song {song_id} did not reach a terminal status within {POLL_TIMEOUT_S}s")


def test_separation_end_to_end_on_a_twenty_second_clip(
    logged_in_client: httpx.Client, db_conn: psycopg.Connection
) -> None:
    with (FIXTURES_DIR / "twenty-second-tone.mp3").open("rb") as f:
        song = logged_in_client.post(
            "/api/songs", files={"file": ("twenty-second-tone.mp3", f, "audio/mpeg")}
        ).json()
    song_id = song["id"]

    status = _poll_ingest_job_status(db_conn, song_id)
    assert status == "SUCCEEDED"

    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT kind, blob_sha256, sample_rate, duration_s FROM stems "
            "WHERE song_id = %s ORDER BY kind",
            (song_id,),
        )
        stems = cur.fetchall()

    assert len(stems) == 2
    kinds = {row[0] for row in stems}
    assert kinds == {"INSTRUMENTAL", "VOCALS"}

    hashes = {row[1] for row in stems}
    assert len(hashes) == 2  # distinct blobs for vocals vs instrumental

    with db_conn.cursor() as cur:
        cur.execute("SELECT sha256 FROM blobs WHERE sha256 = ANY(%s)", (list(hashes),))
        blob_rows = cur.fetchall()
    assert len(blob_rows) == 2  # both stem blobs actually recorded

    with db_conn.cursor() as cur:
        cur.execute("SELECT stage_results FROM ingest_jobs WHERE song_id = %s", (song_id,))
        (stage_results,) = cur.fetchone()
    assert stage_results["separation"]["vram_peak_mb"] is not None
    assert stage_results["separation"]["duration_ms"] > 0


def test_undecodable_upload_never_reaches_separation(
    logged_in_client: httpx.Client, db_conn: psycopg.Connection
) -> None:
    """Belt-and-suspenders: ffprobe at upload time (M7) should already
    reject this before a song/ingest_job row ever exists, so there is
    nothing for the separation stage to run on."""
    with (FIXTURES_DIR / "not-audio.txt").open("rb") as f:
        response = logged_in_client.post(
            "/api/songs", files={"file": ("not-audio.txt", f, "text/plain")}
        )
    assert response.status_code == 415
