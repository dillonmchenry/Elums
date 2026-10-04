# VM baseline — captured Oct 3 2026 (M2)

Re-verified live against `108.39.26.2:48585` (alias `elums-vm` in `~/.ssh/config`) after the day's recon. See [IMPLEMENTATION_PLAN_2026-10-03.md](../IMPLEMENTATION_PLAN_2026-10-03.md) §3.1 for the consequences of what follows.

## What this box actually is

**A vast.ai unprivileged Docker container, not a VM.** `/etc/vast-agents-guide.md` states this explicitly: root access without kernel module loading, Docker-in-Docker, or cgroup/sysctl control. `docker: command not found` — confirmed, no Docker Engine present. Services run under `supervisor`; a Caddy instance already runs as the Instance Portal auth edge (do not stop `caddy`, `instance_portal`, or `tunnel_manager`).

## Hardware and CUDA

| | Value |
| --- | --- |
| GPU | NVIDIA GeForce RTX 5060 Ti |
| VRAM | 16,311 MiB |
| Driver version | 595.58.03 |
| Driver max CUDA | 13.2 |
| Installed CUDA (partial toolkit) | 13.2 — includes nvcc, cudart, nvrtc, **cuBLAS, cuDNN**, cuFFT, cuSPARSE, cuSOLVER, cuRAND, NPP, nvJPEG; **NCCL absent** (irrelevant, single GPU) |
| Compute capability | 12.0 → `sm_120` (Blackwell) |
| Min CUDA for wheels | 12.8 (confirms §3.2/§11.6's cu130 pin requirement) |
| Forward compat | available but not enabled — correct, since driver already supports CUDA 13.2 natively |
| CPU | 128 vCPU |
| RAM | 251 GB total, 42 GB free, 179 GB "available" (reclaimable from buff/cache) |

## Disk

`/` is an overlay filesystem, 1.5 TB, 53 MB used — effectively all free. **No separate volume is mounted** (`workspace_is_volume: false`). Everything here is container-local storage and does **not** survive a recycle or destroy. GTSinger (54 GB) and NanoPitch-PreExtract (3.64 GB) are acceptable to re-download if lost; code, results, and trained checkpoints are not, and must be pushed off-box as they're produced.

## Software present

`tmux 3.4`, `git 2.43.0`, `uv 0.12.10`, `ffmpeg 6.1.1-3ubuntu5` (older than local's 9.0.2 — not expected to matter for separation/analysis use), `python3` system is 3.12.3 with `/venv/main` as the default managed env, `supervisorctl`, `caddy` (as the instance portal). **Absent:** `docker`, `postgres`, `valkey`, Node on non-login shells (nvm-managed, needs `bash -lc`).

## Network — ports already allocated (fixed at creation, cannot add more)

| Container port | Public port | Service |
| --- | --- | --- |
| 22 | 48585 | SSH (this is how we reach it) |
| 1111 | 48511 | Instance Portal |
| 6006 | 48228 | Tensorboard |
| 8080 | 48162 | Jupyter Terminal |
| 8384 | 48289 | Syncthing |
| 72299 | 48355 (self-mapped) | — |

All five normal ports are in use. **This does not block the browser access pattern** — `ssh -L 8080:127.0.0.1:<app-internal-port>` reaches any `127.0.0.1`-bound port inside the container directly, bypasses the Caddy auth edge, needs no token, and exposes nothing publicly. This is exactly what §13 of the approach document already assumed. The `elums-tunnel` host in `~/.ssh/config` implements this.

## SSH access

Working as of Oct 3 2026 via two `~/.ssh/config` entries (`elums-vm` for commands, `elums-tunnel` for the long-lived browser tunnel), using the relocated key at `~/.ssh/smule_vm`. The connection banner is from vast.ai's MOTD, not an error — it always prints `"Welcome to vast.ai... Have fun!"` before the agent-guide reminder, even on success.

## GPU architecture verification (M3) — PASSED

Verified Oct 3 2026 via `uv sync --group gpu` + `uv run python scripts/verify_gpu.py` directly on the VM (no Docker — see §3.1):

- [x] `sm_120` present in `torch.cuda.get_arch_list()`
- [x] forced kernel launch succeeds
- [x] `torch.version.cuda` recorded: `13.0`

**One pin, both architectures.** The resolved arch list — `['sm_75', 'sm_80', 'sm_86', 'sm_90', 'sm_100', 'sm_120']` — contains both `sm_86` (local RTX 3070) and `sm_120` (this box), identical on both machines. §3.2's "documented fork" fallback was never needed; `torch==2.14.1` from `whl/cu130` is confirmed as the single pin for the whole project.

Locally, the same check inside the `elums:gpu` Docker image (`docker compose run --rm -e EXPECTED_SM_ARCH=sm_86 gpu-worker python scripts/verify_gpu.py`) also passed.

**Two build-environment findings from standing up the gpu image/sync, recorded so they aren't rediscovered:**
- `audio-separator` needs `ffmpeg` on `PATH` even just to list or download models (crashes at init otherwise). Present on this VM already; added explicitly to the local Docker image.
- `audio-separator` transitively depends on `diffq` (via Demucs), which compiles a C extension with no prebuilt cp313 wheel. This VM already has a compiler; `python:3.13-slim` locally does not and needed `build-essential` added.

## Consequences for the plan (cross-reference)

1. **No Docker Compose deployment here.** Breaks the literal reading of §13's deployment story and Sun Oct 11's "fresh clone, `docker compose up -d --build`." Needs a decision — see MA-3 in the implementation plan — before Sunday.
2. **Nothing persists.** Code/results must be pushed to GitHub (or at minimum copied locally) immediately, not left only here.
3. **`ssh -L` is the only viable browser access path** — confirmed compatible with existing design intent, no change needed.
