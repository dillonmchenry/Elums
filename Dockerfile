# syntax=docker/dockerfile:1.7
#
# Two targets sharing one pyproject.toml and dependency-group split, per
# ELUMS_TECHNICAL_APPROACH.md §11.6 and IMPLEMENTATION_PLAN_2026-10-03.md M3:
#   - app: no torch — keeps api/worker small and fast to rebuild
#   - gpu: torch (cu130) + the audio stack — used only by gpu-worker
#
# Base is python:3.13-slim, not an nvidia/cuda image: the cu130 torch wheels
# bundle their own CUDA runtime + cuDNN as pip dependencies, so the
# multi-gigabyte devel image buys nothing here (§3 of the implementation
# plan). Revisit nvidia/cuda:13.x-*-ubuntu24.04 only if a future dependency
# turns out to need system CUDA.

FROM python:3.13-slim AS base

# ffmpeg (ffprobe specifically) is needed by BOTH targets now: the gpu
# image needs it just to list/download audio-separator models (see below),
# and the app image needs `ffprobe` to sniff uploads in M7's `POST
# /api/songs` (sniff real audio streams rather than trusting the client's
# content-type/extension). Moved up to `base` directly Oct 3 2026 (M7) so
# it isn't duplicated per-target.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /uvx /usr/local/bin/

ENV UV_LINK_MODE=copy \
    UV_PYTHON_PREFERENCE=only-system \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:${PATH}"

WORKDIR /app
COPY pyproject.toml ./

# --- app target -------------------------------------------------------
# `--group app` is explicit: a bare `uv sync` does not install non-default
# dependency-groups, and we deliberately did not mark `app` as a uv
# default-group (so `uv sync --group gpu` on the VM stays torch-only).
FROM base AS app
RUN uv sync --group app
COPY . .
EXPOSE 8000
CMD ["uvicorn", "elums.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

# --- gpu target --------------------------------------------------------
FROM base AS gpu

# build-essential (gcc) is required because audio-separator transitively
# depends on `diffq` (a Demucs dependency), which has a C extension
# (bitpack.c) with no prebuilt cp313 wheel — verified directly Oct 3 2026
# (M3): without a compiler, `uv sync --group gpu` fails with
# "error: [Errno 2] No such file or directory: 'gcc'". (ffmpeg itself now
# lives in `base`, above — both targets need it.)
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# Skip flash-attn / xformers entirely (§11.6): sequences are short,
# scaled_dot_product_attention is sufficient, and avoiding them avoids a
# long nvcc source-build step in this image.
ENV PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

RUN uv sync --group gpu
COPY . .
CMD ["python", "-c", "print('elums gpu image — entrypoint added in M4/M8')"]
