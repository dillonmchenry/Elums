"""M4 acceptance criterion A4 ('a green health check'), as an actual test
instead of a one-off curl — see IMPLEMENTATION_PLAN_2026-10-03.md."""

from __future__ import annotations

import httpx


def test_healthz_reports_ok(client: httpx.Client) -> None:
    response = client.get("/api/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok", "valkey": "ok"}


def test_healthz_is_json(client: httpx.Client) -> None:
    response = client.get("/api/healthz")
    assert response.headers["content-type"].startswith("application/json")


def test_unknown_route_uses_the_one_error_shape(client: httpx.Client) -> None:
    """elums/api/errors.py's error-shape convention, exercised end-to-end:
    FastAPI's default 404 for an unmatched route should still come back
    through Caddy with a real JSON body, not an HTML error page."""
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
