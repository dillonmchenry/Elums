"""Single source of infrastructure configuration — read from the environment.

Per IMPLEMENTATION_PLAN_2026-10-03.md M4 and ELUMS_BUILD_SCHEDULE.md's
portability disciplines: everything machine-specific lives here, backed by
.env, and nothing is a hardcoded path. The VM gets a different .env and
nothing else changes.

Per-threshold coaching config (§6 of ELUMS_TECHNICAL_APPROACH.md) is
deliberately NOT here — that is config-as-data in a separate YAML file,
added when the coaching engine exists (Fri Oct 9). This module is
infrastructure only.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Database ---
    database_url: str = "postgresql+psycopg://elums:elums@db:5432/elums"

    # --- Cache / queue ---
    valkey_url: str = "valkey://valkey:6379/0"

    # --- Storage roots (never a literal path elsewhere in the codebase) ---
    blob_root: Path = Path("/data/blobs")
    model_root: Path = Path("/app/models")
    data_root: Path = Path("/data")

    # --- Sessions (§9 of the approach document) ---
    # false for `ssh -L` tunnel access (today); true once the Cloudflare
    # Tunnel is live (Thu Oct 8) — see M6 of the implementation plan.
    session_cookie_secure: bool = False
    session_cookie_name: str = "elums_session"

    # --- LLM (placeholder only — no call sites exist before Fri Oct 9) ---
    openrouter_api_key: str = ""

    # --- Upload limits (M7) ---
    max_upload_bytes: int = 30 * 1024 * 1024  # 30 MB
    max_upload_duration_s: int = 600  # 10 minutes

    # --- Performance chunked upload staging (W3, Wed Oct 7) ---
    # A sibling of blob_root, never a literal path elsewhere — chunks
    # land here mid-take and are assembled into one file for
    # BlobStore.put on `complete`, then the staging directory for that
    # performance is removed.
    performance_staging_root: Path = Path("/data/performance-staging")
    max_take_bytes: int = 60 * 1024 * 1024  # ~3 min of 48kHz stereo WAV, generous


settings = Settings()
