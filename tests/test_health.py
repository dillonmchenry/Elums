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
    assert response.json()["error"]["code"] == "not_found"


def test_frontend_served_with_cross_origin_isolation_headers(client: httpx.Client) -> None:
    """M5: COOP/COEP, required for the SharedArrayBuffer ring buffer the
    AudioWorklet/pitch-worker pipeline needs later (ELUMS_TECHNICAL_APPROACH.md
    §11.5) — must be present on every page Caddy serves, not just /api."""
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["cross-origin-opener-policy"] == "same-origin"
    assert response.headers["cross-origin-embedder-policy"] == "require-corp"


def test_diagnostics_route_reachable(client: httpx.Client) -> None:
    response = client.get("/diagnostics")
    assert response.status_code == 200
