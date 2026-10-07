.PHONY: up down build migrate seed logs ps verify-gpu test openapi nanopitch-wasm

# M4 EC-8: `make` was missing locally (Windows) — installed via
# `winget install ezwinports.make`. No Windows-only logic lives here;
# this Makefile is identical on both machines.

# BUILDX_NO_DEFAULT_ATTESTATIONS=1: without it, BuildKit's provenance
# attestation gets a fresh manifest digest on every `--build` even with a
# 100%-cache-hit build, so compose sees the image as "changed" and
# recreates api/worker/gpu-worker/frontend every single `make up` — a
# harmless few seconds, but not actually the no-op A5 requires. Found
# directly during the M8 end-of-day validation pass.
up: .env
	BUILDX_NO_DEFAULT_ATTESTATIONS=1 docker compose up -d --build
	@echo "Tunnel from your laptop: ssh -L 8080:localhost:8080 elums-tunnel"
	@echo "Then open http://localhost:8080/api/healthz"

down:
	docker compose down

build:
	docker compose build

# Schema convention (M4): Alembic owns tables, Procrastinate owns its own
# queue schema — both are idempotent and safe to re-run.
migrate:
	docker compose run --rm api alembic upgrade head
	docker compose run --rm api python -m procrastinate --app=elums.jobs.app.app schema --apply

seed:
	docker compose run --rm api python -m elums.seed

logs:
	docker compose logs -f

ps:
	docker compose ps

verify-gpu:
	docker compose run --rm -e EXPECTED_SM_ARCH=$${EXPECTED_SM_ARCH:-sm_86} gpu-worker python scripts/verify_gpu.py

# Host-side, against the real running stack (make up first) — see
# tests/conftest.py. `uv sync --group dev` installs pytest/httpx into a
# local .venv, never into any image.
test:
	uv sync --group dev
	uv run pytest -q

# Regenerate the committed openapi.json from the running api service.
# Note: on Windows, run this from `make` (not a bare PowerShell `>`
# redirect) — PowerShell's `>` writes UTF-16LE with a BOM by default and
# silently corrupts the file; this was hit directly Oct 3 2026 (M5).
openapi:
	docker compose exec api python -c "import json; from elums.api.main import app; print(json.dumps(app.openapi(), indent=2, sort_keys=True))" > openapi.json

.env:
	cp .env.example .env
	@echo "Created .env from .env.example — edit EXPECTED_SM_ARCH per machine."

# EC-1 (Oct 8): `emcc` is not on PATH and the host has no emsdk install.
# `emscripten/emsdk` (Docker image) is Linux-reproducible and avoids a
# host-local toolchain, matching the project's portability discipline.
# Mounts the repo root so the script reads vendor/ and writes into
# frontend/public/nanopitch/ (that path crosses the frontend service's
# own build context/bind-mount boundary — see build.sh's own comment).
nanopitch-wasm:
	docker run --rm -v "$(CURDIR):/repo" -w /repo/vendor/nanopitch/wasm emscripten/emsdk:latest bash build.sh
