"""M6: register/login/logout/me/following against the live stack. Uses a
fresh httpx.Client per test (not the shared session-scoped `client`
fixture) so each test's session cookie doesn't leak into the next.

A few tests connect directly to Postgres via the `db:5433` host-port that
docker-compose.yaml exposes for "ad-hoc psql" — needed to assert DB-level
invariants (no plaintext token at rest, exactly one session row per
login, logout deletes the row) that aren't observable from the HTTP API
alone. Per the implementation plan's M6 "Focused tests" list.
"""

from __future__ import annotations

import os
import uuid

import httpx
import psycopg
import pytest


def _unique_email() -> str:
    # Not @elums.test: `.test` is an IANA special-use reserved TLD
    # (RFC 2606) and email-validator rejects it outright — hit directly
    # Oct 3 2026 (M6). `.demo` matches elums/seed.py's convention instead.
    return f"pytest-{uuid.uuid4().hex[:12]}@elums.demo"


@pytest.fixture
def fresh_client(base_url: str) -> httpx.Client:
    with httpx.Client(base_url=base_url, timeout=10.0) as c:
        yield c


@pytest.fixture
def db_conn():
    # 127.0.0.1, not "localhost": DNS resolution of "localhost" on this
    # machine took 60s+ and looked exactly like a hung connection — hit
    # directly Oct 3 2026 (M6). The direct IP connects in <20ms.
    dsn = os.environ.get(
        "TEST_DB_DSN", "postgresql://elums:elums@127.0.0.1:5433/elums"
    )
    with psycopg.connect(dsn) as conn:
        yield conn


def test_register_sets_cookie_and_returns_public_user(fresh_client: httpx.Client) -> None:
    email = _unique_email()
    response = fresh_client.post(
        "/api/auth/register",
        json={"email": email, "display_name": "Pytest User", "password": "a-good-password"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == email
    assert body["display_name"] == "Pytest User"
    assert "password" not in body and "password_hash" not in body
    assert "elums_session" in fresh_client.cookies


def test_register_duplicate_email_is_409(fresh_client: httpx.Client) -> None:
    email = _unique_email()
    payload = {"email": email, "display_name": "Pytest User", "password": "a-good-password"}
    first = fresh_client.post("/api/auth/register", json=payload)
    assert first.status_code == 201

    second = fresh_client.post("/api/auth/register", json=payload)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "email_taken"


def test_me_requires_a_session(fresh_client: httpx.Client) -> None:
    response = fresh_client.get("/api/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


def test_login_with_seeded_demo_user_then_me_then_logout(fresh_client: httpx.Client) -> None:
    """Exercises elums/seed.py's actual output, not a throwaway account —
    this is the "can I log in as @dana" check from
    ELUMS_TECHNICAL_APPROACH.md's auth section, automated."""
    login = fresh_client.post(
        "/api/auth/login", json={"email": "dana@elums.demo", "password": "elums-demo-2026"}
    )
    assert login.status_code == 200
    assert login.json()["email"] == "dana@elums.demo"

    me = fresh_client.get("/api/me")
    assert me.status_code == 200
    assert me.json()["email"] == "dana@elums.demo"

    logout = fresh_client.post("/api/auth/logout")
    assert logout.status_code == 204

    me_after_logout = fresh_client.get("/api/me")
    assert me_after_logout.status_code == 401


def test_login_wrong_password_is_401_and_does_not_leak_which_part_was_wrong(
    fresh_client: httpx.Client,
) -> None:
    response = fresh_client.post(
        "/api/auth/login", json={"email": "dana@elums.demo", "password": "definitely-wrong"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"

    response2 = fresh_client.post(
        "/api/auth/login", json={"email": "no-such-user@elums.demo", "password": "whatever"}
    )
    assert response2.status_code == 401
    assert response2.json()["error"]["code"] == "invalid_credentials"


def test_wrong_password_creates_no_session_row(
    fresh_client: httpx.Client, db_conn: psycopg.Connection
) -> None:
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM sessions s JOIN users u ON u.id = s.user_id WHERE u.email = %s",
            ("dana@elums.demo",),
        )
        (before,) = cur.fetchone()

    response = fresh_client.post(
        "/api/auth/login", json={"email": "dana@elums.demo", "password": "definitely-wrong"}
    )
    assert response.status_code == 401

    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM sessions s JOIN users u ON u.id = s.user_id WHERE u.email = %s",
            ("dana@elums.demo",),
        )
        (after,) = cur.fetchone()

    assert after == before


def test_login_creates_exactly_one_session_row_and_no_plaintext_token_at_rest(
    fresh_client: httpx.Client, db_conn: psycopg.Connection
) -> None:
    email = _unique_email()
    fresh_client.post(
        "/api/auth/register",
        json={"email": email, "display_name": "Token Check", "password": "a-good-password"},
    )
    raw_token = fresh_client.cookies.get("elums_session")
    assert raw_token

    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*), array_agg(token_hash) FROM sessions s "
            "JOIN users u ON u.id = s.user_id WHERE u.email = %s",
            (email,),
        )
        count, token_hashes = cur.fetchone()

    assert count == 1
    # The plaintext token appears nowhere in `sessions` — only its SHA-256
    # hash does, per ELUMS_TECHNICAL_APPROACH.md's session design.
    assert raw_token not in token_hashes
    assert all(raw_token != h for h in token_hashes)


def test_logout_deletes_the_session_row(
    fresh_client: httpx.Client, db_conn: psycopg.Connection
) -> None:
    email = _unique_email()
    fresh_client.post(
        "/api/auth/register",
        json={"email": email, "display_name": "Logout Check", "password": "a-good-password"},
    )

    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM sessions s JOIN users u ON u.id = s.user_id WHERE u.email = %s",
            (email,),
        )
        (before,) = cur.fetchone()
    assert before == 1

    logout = fresh_client.post("/api/auth/logout")
    assert logout.status_code == 204

    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM sessions s JOIN users u ON u.id = s.user_id WHERE u.email = %s",
            (email,),
        )
        (after,) = cur.fetchone()
    assert after == 0


def test_social_graph_is_present_for_at_least_six_of_ten_demo_users(
    fresh_client: httpx.Client, db_conn: psycopg.Connection
) -> None:
    """A9 from the implementation plan: `GET /api/users/{id}/following`
    is non-empty for at least 6 of 10 demo users."""
    with db_conn.cursor() as cur:
        # Exclude this test file's own `pytest-<uuid>@elums.demo` throwaway
        # accounts — they share elums/seed.py's `.demo` domain convention
        # but aren't part of the seeded social graph.
        cur.execute(
            "SELECT id FROM users WHERE email LIKE %s AND email NOT LIKE 'pytest-%%' ORDER BY email",
            ("%@elums.demo",),
        )
        demo_user_ids = [str(row[0]) for row in cur.fetchall()]

    assert len(demo_user_ids) >= 10

    non_empty = 0
    for user_id in demo_user_ids:
        response = fresh_client.get(f"/api/users/{user_id}/following")
        assert response.status_code == 200
        if response.json():
            non_empty += 1

    assert non_empty >= 6


def test_following_unknown_user_is_404(fresh_client: httpx.Client) -> None:
    response = fresh_client.get(f"/api/users/{uuid.uuid4()}/following")
    assert response.status_code == 404
