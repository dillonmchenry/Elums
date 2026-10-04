"""These are integration tests, not unit tests: they hit the real running
docker-compose stack over HTTP (default http://localhost:8080, the same
ssh -L tunnel endpoint a reviewer uses), not an in-process ASGI transport.
That means `make up` must already be green before `make test` means
anything — this validates docker-compose.yaml and the Caddy reverse_proxy
hop, not just the FastAPI app in isolation.
"""

from __future__ import annotations

import os

import httpx
import pytest


@pytest.fixture(scope="session")
def base_url() -> str:
    return os.environ.get("API_BASE_URL", "http://localhost:8080")


@pytest.fixture(scope="session")
def client(base_url: str) -> httpx.Client:
    with httpx.Client(base_url=base_url, timeout=10.0) as c:
        yield c
