"""M7: `POST /api/songs` and the Caddy `/blobs/*` byte path, against the
live stack. Fixtures under `tests/fixtures/` are tiny synthetic clips
generated with ffmpeg (see the comment on each), not real music — no
licensing question, and small enough to commit.
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import httpx
import pytest


def _unique_email() -> str:
    # Matches tests/test_auth.py's convention — `.demo`, not `.test`
    # (email-validator rejects `.test` as an IANA reserved special-use
    # TLD). See that file's comment for the full story.
    return f"pytest-{uuid.uuid4().hex[:12]}@elums.demo"


FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fresh_client(base_url: str) -> httpx.Client:
    with httpx.Client(base_url=base_url, timeout=15.0) as c:
        yield c


@pytest.fixture
def logged_in_client(fresh_client: httpx.Client) -> httpx.Client:
    """A brand-new throwaway user per test, not the seeded @dana — these
    tests rely on exact dedup/first-upload semantics ("this user has
    never uploaded this hash before"), which a shared account across
    tests (or across repeated suite runs) would quietly break."""
    email = _unique_email()
    register = fresh_client.post(
        "/api/auth/register",
        json={"email": email, "display_name": "Song Test User", "password": "a-good-password"},
    )
    assert register.status_code == 201
    return fresh_client


def _blob_url(sha256: str) -> str:
    return f"/blobs/{sha256[:2]}/{sha256[2:4]}/{sha256}"


def test_upload_requires_a_session(fresh_client: httpx.Client) -> None:
    with (FIXTURES_DIR / "short-tone.mp3").open("rb") as f:
        response = fresh_client.post("/api/songs", files={"file": ("short-tone.mp3", f, "audio/mpeg")})
    assert response.status_code == 401


def test_upload_valid_audio_creates_a_private_song(logged_in_client: httpx.Client) -> None:
    with (FIXTURES_DIR / "short-tone.mp3").open("rb") as f:
        response = logged_in_client.post(
            "/api/songs",
            files={"file": ("short-tone.mp3", f, "audio/mpeg")},
            data={"title": "A Test Tone"},
        )
    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "A Test Tone"
    assert body["visibility"] == "private"
    assert len(body["source_blob_sha256"]) == 64

    expected_sha256 = hashlib.sha256((FIXTURES_DIR / "short-tone.mp3").read_bytes()).hexdigest()
    assert body["source_blob_sha256"] == expected_sha256


def test_reuploading_identical_bytes_returns_the_existing_song(
    logged_in_client: httpx.Client,
) -> None:
    with (FIXTURES_DIR / "short-tone.mp3").open("rb") as f:
        first = logged_in_client.post(
            "/api/songs", files={"file": ("short-tone.mp3", f, "audio/mpeg")}, data={"title": "First"}
        )
    assert first.status_code == 201

    with (FIXTURES_DIR / "short-tone.mp3").open("rb") as f:
        second = logged_in_client.post(
            "/api/songs", files={"file": ("short-tone.mp3", f, "audio/mpeg")}, data={"title": "Second"}
        )
    assert second.status_code == 201

    # Same song, same original title — the second upload's "title" was
    # ignored because an identical-bytes song for this user already
    # existed, per the implementation plan's M7 dedup note.
    assert first.json()["id"] == second.json()["id"]
    assert second.json()["title"] == "First"


def test_undecodable_audio_is_415(logged_in_client: httpx.Client) -> None:
    with (FIXTURES_DIR / "not-audio.txt").open("rb") as f:
        response = logged_in_client.post(
            "/api/songs", files={"file": ("not-audio.txt", f, "text/plain")}
        )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "undecodable_audio"


def test_oversized_upload_is_413(logged_in_client: httpx.Client) -> None:
    # One byte over the 30 MB cap. Not real audio — the size check runs
    # (and raises) inside BlobStore.put's streaming write, before ffprobe
    # ever sees the file, so content doesn't matter here.
    oversized = b"0" * (30 * 1024 * 1024 + 1)
    response = logged_in_client.post(
        "/api/songs", files={"file": ("big.bin", oversized, "application/octet-stream")}
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "upload_too_large"


def test_too_long_audio_is_413(logged_in_client: httpx.Client) -> None:
    # ~10m5s of silence, encoded small (silence compresses to almost
    # nothing) — exercises the duration cap specifically, independent of
    # the size cap above.
    with (FIXTURES_DIR / "too-long-silence.mp3").open("rb") as f:
        response = logged_in_client.post(
            "/api/songs", files={"file": ("too-long-silence.mp3", f, "audio/mpeg")}
        )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "upload_too_long"


def test_private_blob_is_403_to_anonymous_and_200_to_owner(
    logged_in_client: httpx.Client, fresh_client: httpx.Client, base_url: str
) -> None:
    with (FIXTURES_DIR / "short-tone.mp3").open("rb") as f:
        song = logged_in_client.post(
            "/api/songs", files={"file": ("short-tone.mp3", f, "audio/mpeg")}
        ).json()
    blob_url = _blob_url(song["source_blob_sha256"])

    with httpx.Client(base_url=base_url, timeout=15.0) as anon:
        anon_response = anon.get(blob_url)
    assert anon_response.status_code == 403

    owner_response = logged_in_client.get(blob_url)
    assert owner_response.status_code == 200
    assert owner_response.content == (FIXTURES_DIR / "short-tone.mp3").read_bytes()


def test_blob_range_request_returns_206_with_correct_content_range(
    logged_in_client: httpx.Client,
) -> None:
    """A11 from the implementation plan: `curl -r 0-1023` on a blob
    returns 206 with a correct Content-Range — Caddy's `file_server`
    handling it, not Python."""
    with (FIXTURES_DIR / "short-tone.mp3").open("rb") as f:
        song = logged_in_client.post(
            "/api/songs", files={"file": ("short-tone.mp3", f, "audio/mpeg")}
        ).json()
    blob_url = _blob_url(song["source_blob_sha256"])
    full_size = (FIXTURES_DIR / "short-tone.mp3").stat().st_size

    response = logged_in_client.get(blob_url, headers={"Range": "bytes=0-1023"})
    assert response.status_code == 206
    assert response.headers["content-range"] == f"bytes 0-1023/{full_size}"
    assert len(response.content) == 1024


def test_unknown_blob_hash_is_403(logged_in_client: httpx.Client) -> None:
    fake_sha256 = uuid.uuid4().hex + uuid.uuid4().hex  # 64 hex chars, matches nothing
    response = logged_in_client.get(_blob_url(fake_sha256))
    assert response.status_code == 403
