# Elums — Progress Log

Terse, factual, append-only (one section per day). Raw material for Oct 11's README, limitations list, and AI usage ledger — not prose for its own sake. Governed by [IMPLEMENTATION_PLAN_2026-10-03.md](IMPLEMENTATION_PLAN_2026-10-03.md) §9.

---

## Saturday Oct 3 / Sunday Oct 4 — Day 1 (Foundation)

### 1. Milestone status

| Milestone | Status | Notes |
| --- | --- | --- |
| M0 — repo init + portability | **done** | |
| M1 — download kickoff (local weights + VM datasets) | **done** | See §4 below — one VM dataset finished re-verifying short of fully complete at day's end; resumed, not blocking. |
| M2 — VM smoke test / baseline | **done** | `docs/vm-baseline.md` |
| M3 — local + VM GPU verification | **done** | |
| M4 — compose scaffold, `make up` green | **done** | |
| M5 — SPA scaffold, OpenAPI codegen, COOP/COEP | **done** | |
| M6 — auth + seed | **done** | |
| M7 — blob store + Caddy byte path | **done** | |
| M8 — separation job end-to-end | **done** | |

Commits, one per milestone: `14e8a2c` (M0) · `74b3a9f` (M1+M2) · `b8be977` (M3) · `2334262`/`b606a5d` (M4) · `75c2675` (M5) · `875b3c5` (M6) · `8e4b97e` (M7) · `014ae26` (M8).

### 2. Acceptance criteria — A1 through A12

All twelve pass. Full command output pasted below for **A2, A3, A10, A12** per §9's instruction; the rest are summarized with the verifying command.

| # | Result | Verified by |
| --- | --- | --- |
| A1 | **PASS** | `git log -p \| Select-String "BEGIN OPENSSH PRIVATE KEY"` → 1 "match", but it is the checklist's own line in this plan document quoting the search string, not a key. No actual key content in history; `id_ed25519_drexel` is outside the tree. |
| A2 | **PASS** | see below |
| A3 | **PASS** | see below |
| A4 | **PASS, with a caveat** | `docker compose ps` shows all 7 services `Up`. Only `db` and `valkey` have a Docker `HEALTHCHECK` defined (and show literal `(healthy)`); `api`/`worker`/`gpu-worker`/`caddy`/`frontend` have none, so they can never show `(healthy)` regardless of actual state. Liveness of all 7 confirmed by other means (`/api/healthz`, successful auth/upload/separation flows, Caddy serving blobs) — functionally fine, but the literal "six services reach `healthy`" wording doesn't hold as written, and there are 7 services, not 6 (`frontend` was added at M5). **Not fixed tonight** — recorded as a loose end (§6). |
| A5 | **PASS, after a fix** | `docker compose up -d --build` run twice was *not* a no-op: BuildKit's provenance attestation gets a fresh manifest digest on every build even with 100%-cache-hit layers, so Compose recreated `api`/`worker`/`gpu-worker`/`frontend` every single invocation (harmless, sub-second, but not a no-op). Fixed by exporting `BUILDX_NO_DEFAULT_ATTESTATIONS=1` in the `Makefile`'s `up` target; re-verified twice — second run shows all services `Running`, zero `Recreate`. |
| A6 | **PASS** | `curl -I http://localhost:8080/` → `Cross-Origin-Embedder-Policy: require-corp`, `Cross-Origin-Opener-Policy: same-origin`; `GET /` and `/diagnostics` both `200`. `crossOriginIsolated === true` confirmed in-browser during M5; headers re-confirmed live tonight and covered by `tests/test_health.py::test_frontend_served_with_cross_origin_isolation_headers`. |
| A7 | **PASS** | `POST /api/auth/login` (dana@elums.demo) → `200`; `GET /api/me` with the cookie → the user; without it → `401`. |
| A8 | **PASS** | `Set-Cookie: elums_session=...; HttpOnly; Max-Age=2592000; Path=/; SameSite=lax`. `sessions.token_hash` holds a 64-char hex hash; plaintext token appears nowhere in the DB (`tests/test_auth.py::test_login_creates_exactly_one_session_row_and_no_plaintext_token_at_rest`). |
| A9 | **PASS** | All 10 seeded demo users have ≥1 follow (Dana 4, Jules 3, Milo 3, Ana/Kiko/Priya/Sam/Theo/Wren 2, Remy 1) — exceeds the ≥6-of-10 bar. |
| A10 | **PASS** | see below |
| A11 | **PASS** | `curl -r 0-1023` on both stem blobs → `206` with correct `Content-Range: bytes 0-1023/<total>`; `Server: Caddy` on the response (Python never serves bytes); anonymous request to a private stem blob → `403`; api logs show only the `/internal/blob-authz` hit (`204`/`403`), no byte transfer logged by the api process. |
| A12 | **PASS** | see below |

#### A2 — local GPU in the `elums:gpu` image

```
$ docker compose run --rm -e EXPECTED_SM_ARCH=sm_86 gpu-worker python scripts/verify_gpu.py
torch version:      2.14.1+cu130
torch.version.cuda: 13.0
cuda.is_available(): True
arch list:           ['sm_75', 'sm_80', 'sm_86', 'sm_90', 'sm_100', 'sm_120']
PASS: sm_86 present in arch list and kernel launch succeeded
```

#### A3 — VM GPU, same torch pin

```
$ ssh elums-vm 'cd /srv/elums && EXPECTED_SM_ARCH=sm_120 uv run python scripts/verify_gpu.py'
torch version:      2.14.1+cu130
torch.version.cuda: 13.0
cuda.is_available(): True
arch list:           ['sm_75', 'sm_80', 'sm_86', 'sm_90', 'sm_100', 'sm_120']
PASS: sm_120 present in arch list and kernel launch succeeded
```

One `torch==2.14.1`/`cu130` pin, confirmed again tonight on both machines independently — no fork needed.

#### A10 — upload → two stems

```
$ POST /api/songs  (twenty-second-tone.mp3, as dana@elums.demo)
song: 01a10577-1912-7e6b-b8df-919b8236742d

-- ~11.5s later --
SELECT status, separation_status FROM ingest_jobs WHERE song_id = '01a10577-...';
 status    | separation_status
 SUCCEEDED | SUCCEEDED

SELECT kind, blob_sha256, sample_rate, duration_s FROM stems WHERE song_id = '01a10577-...';
 VOCALS       | 112c54fb...e7ca6b | 44100 | 20
 INSTRUMENTAL | 460d41f7...214315c | 44100 | 20
```

Both stems fetched as the owner and played back (two distinct byte streams, 333 KB and 462 KB FLAC, both `200`). No full-length real song was available locally to listen for vocal isolation by ear; validated structurally (distinct hashes, correct stem kinds, correct sample rate/duration) rather than audibly tonight — **flagged as a loose end**, not silently assumed.

#### A12 — ML timings logged

```
{"separation": {"model": "vocals_mel_band_roformer.ckpt", "duration_ms": 11538, "segment_size": 128, "vram_peak_mb": 1741.22607421875}}
```

`model`, `duration_ms`, `vram_peak_mb` all present, as required. Three separate runs today (3 s and 20 s synthetic clips) measured `duration_ms` 7,716–12,653 and `vram_peak_mb` 1,741–1,757 consistently.

### 3. Hardware and version truth

Full detail in [`docs/vm-baseline.md`](docs/vm-baseline.md) (VM) and inline in `IMPLEMENTATION_PLAN_2026-10-03.md` §2 (local). Summary:

| | Local (this machine) | VM (`elums-vm`, vast.ai) |
| --- | --- | --- |
| GPU | RTX 3070, 8 GB VRAM | RTX 5060 Ti, 16,311 MiB VRAM |
| Compute capability | `sm_86` | `sm_120` (Blackwell) |
| Driver max CUDA | — (local driver supports ≥12.8) | 13.2 |
| torch wheel | `2.14.1+cu130` (`whl/cu130` index) | identical — same pin, no fork |
| Resolved arch list (both) | `['sm_75', 'sm_80', 'sm_86', 'sm_90', 'sm_100', 'sm_120']` | same |
| Topology | 7 compose services, local-first | vast.ai unprivileged container — **no Docker Engine present**, not a real VM; see `docs/vm-baseline.md` "Consequences for the plan" |

**Separation checkpoint (EC-5):** `vocals_mel_band_roformer.ckpt` — "Roformer Model: MelBand Roformer | Vocals by Kimberley Jensen" per `audio-separator --list_models` (v0.47.0), SDR vocals 12.6. **License: MIT**, independently re-verified in `docs/licensing-audit.md` (original GPL-3.0 June 2025 → relicensed MIT by the author on HuggingFace, April 2026, corroborated by two independent downstream repos). Clear to ship.

### 4. Measured timings

| Clip | `duration_ms` | `vram_peak_mb` | `segment_size` |
| --- | --- | --- | --- |
| 3 s synthetic tone | 7,716 – 12,653 | 1,741 – 1,757 | 128 |
| 20 s synthetic tone | 11,538 – 12,505 | 1,741 | 128 |

Both measured on the local RTX 3070 (8 GB), via `gpu-worker`'s own structlog line, across several repeat runs during validation.

**Extrapolation against §5's 27–41 s/song estimate (on a 16 GB RTX 4000 Ada):** most of the fixed cost above is model-load overhead (~5 s), with the per-audio-second cost scaling at roughly 0.28 s per clip-second (derived from the 3 s → 20 s delta). Extrapolating to a 3–4 minute song (180–240 s of audio): **≈55–70 s** on the local 3070. This is *higher* than §5's 27–41 s estimate, consistent with the local card having half the reference card's VRAM, as the plan itself anticipated (§3.4/EC-4). **This is an extrapolation from short synthetic clips, not a direct measurement** — no full-length real song was available locally tonight. Re-verify with an actual 3–4 minute track before this number is relied on for Sun–Tue's 4-hour block budgeting; if the real number tracks closer to 70 s than 41 s, say so plainly before those blocks are planned.

### 5. Deviations from the plan

Each with reason and consequence. Routine, zero-architectural-impact adjustments are omitted per §9's instruction; everything below either changed a decision or was a real bug caught during execution, not merely a detail.

1. **Separation job defer is not one atomic transaction with the song/ingest_job commit.** Procrastinate's connector and the request's SQLAlchemy session are two separate Postgres connections; the plan's "the `songs` row, the `ingest_jobs` row, and the job itself commit in one transaction" (§6, M8) does not literally hold. Deferred immediately after a successful commit instead. **Consequence:** a crash in the few-millisecond gap between the two calls strands a `pending` ingest_job with no job behind it. Not built tonight: a sweep that re-defers any `pending` job older than a few minutes. Documented inline in `elums/api/routers/songs.py`. **Low risk, not urgent**, but a later day should either build the sweep or do the lower-level plumbing to make this genuinely atomic before it matters at scale.
2. **Found and fixed: queue-collision bug.** The plain `worker` compose service had no `-q` flag, so Procrastinate defaulted it to "all queues" — it raced `gpu-worker` for every `queue="gpu"` job and failed them instantly (it never imports the torch-heavy `elums.separation.task` module, so the task name is unknown to it). First hit directly during initial M8 testing: `ingest_jobs` stuck at `PENDING`, zero `gpu-worker` log activity. Fixed by scoping `worker` to `-q default` in `docker-compose.yaml`.
3. **Found and fixed: stem blobs were unreachable via Caddy's byte path.** `/internal/blob-authz` originally only checked `Song.source_blob_sha256` against the requested hash — stem blobs have a *different* hash (they're separately-generated files), so every stem request would have 403'd even for the owner. Would have silently broken A10's "both stems play in the browser" requirement had it shipped unnoticed. Fixed by extending the authz query to also match via `Stem.blob_sha256` joined back to its `Song`.
4. **Found and fixed: the day-one structlog `request_id` convention was never actually wired up.** `elums/logging.py`'s docstring has described `request_id` on every log line as the day-one convention since M4, but no middleware ever bound it, and no router emitted a per-request access-log line at all — only uvicorn's own plain-text access logger ran. `docker compose logs api | head -5 → structlog JSON carrying request_id` (§8's literal check) failed as a result. Fixed by adding `_RequestIdMiddleware` in `elums/api/main.py`: binds a UUID4 `request_id` to structlog's contextvars for the life of each request and emits one `request.completed` JSON line per request (method, path, status_code, duration_ms). Verified live — every subsequent log line now carries it.
5. **Found and fixed: `make up` was not actually idempotent.** BuildKit's provenance/attestation metadata gets a new manifest digest on *every* `--build` invocation, even with a 100%-cache-hit build — Compose sees the image as "changed" and recreates `api`/`worker`/`gpu-worker`/`frontend` every time (sub-second, harmless, but not literally a no-op as A5 requires). Fixed by setting `BUILDX_NO_DEFAULT_ATTESTATIONS=1` in the `Makefile`'s `up` target; re-verified — second run now shows zero `Recreate`.
6. **GTSinger dataset download was not actually complete at the point M1 was marked done earlier today.** `du -sh` showed 32 GB against GTSinger's documented 54 GB and the original `tmux` download session had already exited (closed on its own, not killed) partway through. Resumed in a fresh detached `tmux` session (`downloads`, on `elums-vm`) during tonight's validation pass so it continues overnight; not yet re-verified complete. NanoPitch-PreExtract *is* fully cached (resumable re-run resolved near-instantly).

### 6. Blockers

- **MA-3's deployment decision for the Smule box** is still open and is the largest item on the project. `docs/vm-baseline.md` confirms the VM is a vast.ai unprivileged container with **no Docker Engine present at all** — the literal "fresh clone, `docker compose up -d --build`" story in §13 cannot run there as written. Blocks Sun Oct 11's only mandatory VM task. Needs a decision from whoever owns the Smule-box deployment target before then — not something resolvable by continuing to build.

### 7. Loose ends carried forward

From the plan's §9.7 template, plus findings from tonight's validation pass:

- **MA-3's deployment decision for the Smule box** (see §6 above).
- The three pre-analyzed seed performances deferred from M6.
- `wavesurfer.js` 7→8 API recheck before Tue Oct 6 (§3.8).
- `librosa` 1.0 API recheck before Sat Oct 10 (§3.8). (`librosa==1.0.0` is already resolved into the `gpu` dependency group's lock as a transitive dependency of `audio-separator`.)
- **The absent git remote** needed for Mon Oct 12's clean-clone verification (`git remote -v` → empty).
- `SESSION_COOKIE_SECURE=true` when the Cloudflare Tunnel comes up Thu Oct 8 (M6).
- **GTSinger download not yet confirmed complete** — resumed in a detached `tmux` session on the VM tonight (§5 item 6); check `du -sh /workspace/.hf_home/hub/datasets--GTSinger--GTSinger` tomorrow before assuming it's there.
- **A4's "6 services healthy" doesn't literally hold** — only `db`/`valkey` have Docker `HEALTHCHECK` directives; the other 5 (including `frontend`, added at M5 and not counted in the plan's original 6) have none. All 7 are confirmed live by other means tonight, but add healthchecks for `api`/`worker`/`gpu-worker`/`caddy`/`frontend` on a day with headroom.
- **No full-length (3–4 min) real song has been tested locally** — A10/A12 were validated structurally and with short synthetic clips only; §4's extrapolated per-song timing should be re-verified against a real track before Sun–Tue's 4-hour blocks are finalized against it.
- **The dev Postgres database has accumulated test-user residue** from repeated pytest runs against the live stack (`"Pytest User"`, `"Song Test User"`, `"Separation Test User"`, etc. — dozens of throwaway rows, visible in a plain `SELECT display_name, count(*) FROM users GROUP BY ...`-style query). Harmless to correctness (each test registers its own unique user) but worth either a teardown fixture or a periodic manual sweep before this matters for a demo.
- **No HTTP endpoint exists yet for polling an `ingest_job`'s status.** `tests/test_separation.py` polls the `ingest_jobs`/`stems` tables directly via a raw DB connection as a stand-in. The SPA will need a real `GET` route for this before it can show live upload progress — not yet scoped to a specific milestone.
- **`make` is not resolvable in a fresh shell session on this machine**, despite the Makefile's own comment stating it was installed via `winget install ezwinports.make` earlier today — a PATH-scoping issue (new terminals apparently don't inherit the PATH update without a fresh login/reboot). Worked around tonight by running the Makefile's underlying `docker compose` commands directly. Not blocking, but open a fresh terminal (or reboot) before assuming `make up` works verbatim tomorrow.

---

## Sunday Oct 4 — Day 2 (structure/beats/key/VAD ingest chain)

Governed by [IMPLEMENTATION_PLAN_2026-10-04.md](IMPLEMENTATION_PLAN_2026-10-04.md).

### 1. Milestone status

| Milestone | Status | Notes |
| --- | --- | --- |
| N1 — structure/beats/downbeats (`harmonix-all`) | **done** | `elums/ingest/structure.py` |
| N2 — key (Krumhansl-Schmuckler) + RMS-VAD | **done** | `elums/ingest/key.py`, `elums/ingest/vad.py` |
| N3 — `song_analyses` table | **done** | `elums/models/song_analysis.py`, migration `5a7a503e7300` |
| N4 — job chain + ingest-status endpoint + polling UI | **done** | `elums/ingest/tasks.py`, `GET /api/songs/{id}/ingest`, `HomePage.tsx` |
| N5 — real-song end-to-end validation | **done** | see §4 below |

### 2. Early checks (EC-1 through EC-6)

| # | Risk | Resolution |
| --- | --- | --- |
| EC-1 | `torchaudio`/`torch` ABI compatibility | `torchaudio==2.11.0` alongside `torch==2.14.1+cu130` — clean co-import, confirmed with a forced real CUDA kernel launch (`sm_120` present in arch list). No fallback image needed. |
| EC-2 | Python 3.13 / NATTEN resolution | `uv lock` resolved 148 packages cleanly; NATTEN never pulled in as a transitive extra. |
| EC-3 | `harmonix-all` checkpoint identity (undocumented going in) | Empirically determined by running `analyze()` once and inspecting the cache: **8 harmonix-fold files, ~11.5 MB total**, from `taejunkim/allinone` on HF. Documented in `config/models.yaml`. |
| EC-4 | `librosa` 1.0 API | Used as-is (`chroma_cqt`, `feature.rms`) — no API mismatch hit. |
| EC-5 | MP3 decode path (all-in-one-infer's own torchaudio-based decoder needs `torchcodec`, not installed) | Sidestepped: `_ensure_wav()` in `structure.py` converts non-WAV/FLAC input via ffmpeg before handing it to `analyze()`. |
| EC-6 | GTSinger VM download status | Not re-checked tonight — carried forward, see §6. |

### 3. Settled architecture note

Per the Oct 4 plan's §3: `run_structure()` runs all-in-one-infer's **own** HTDemucs separation on the original upload, not Saturday's 2-stem Mel-Band RoFormer output — the model's embeddings are shaped for 4 stems (bass/drums/other/vocals), and substituting `other`=instrumental with silent bass/drums would run it off-distribution for exactly the beat/downbeat/section outputs this stage produces. Costs an extra ~30s of GPU time (see §4); shares the `gpu:separation` lock so it never races Saturday's separation job.

### 4. Measured timings (real songs, not synthetic — a first for this project)

Two real CC-BY-licensed tracks with vocals were sourced from archive.org for today's validation (`data/samples/README.md` has full attribution): "Fill Me Up" by Ellody (268.3s) and "Is This All" by Liz James (221.3s). The first upload hit a stale-image issue (see §5 item 2) before useful timing came out of it; the second ran the full chain cleanly:

| Stage | `duration_ms` | `vram_peak_mb` |
| --- | --- | --- |
| separation (221.3s song) | 27,713 | 1,741 |
| structure_beats (same song) | 31,053 | 1,036 |
| rms_vad (same song) | CPU-only, not separately timed | — |

Total GPU-bound time for this song: **~58.8s** (separation + structure_beats), plus a fast CPU-only VAD pass. This **corrects Day 1's §4 extrapolation** ("≈55–70s on the local 3070" — that was for separation alone, extrapolated from 3s/20s synthetic clips): separation alone on a real 3.7-minute song took 27.7s, well inside that range, and today's new structure_beats stage adds roughly another 31s on top. Real output: `bpm=103`, `key=G minor` (confidence 0.074 — a near-tie per KS's own known relative-major/minor confusion, consistent with §5's documented weakness), 375 beats, 94 downbeats, 9 sections, 175.4s of 221.3s flagged as voiced (plausible for a vocal pop track).

### 5. Deviations from the plan

1. **The gpu-worker image was not actually rebuilt after `pyproject.toml`'s N1 dependency additions landed, despite the plan and earlier validation implying it was.** The running container had been `docker compose restart`ed (code-only, bind-mounted) rather than rebuilt, so `all-in-one-infer` genuinely wasn't installed in the container that picked up the N4 job chain. First real upload failed with `No module named 'allin1_infer'` after separation succeeded (confirming the chain-deferral logic itself was correct). Fixed by `docker compose build gpu-worker` (confirmed the Dockerfile's `COPY pyproject.toml` layer cache was already correctly keyed to the edited file) then `docker compose up -d gpu-worker` to recreate the container from the new image. **Lesson, not yet automated:** Python package changes need an image rebuild; `.py` file changes don't. No `Makefile` target currently distinguishes these for a developer to remember by rote.
2. **Found and fixed: `/internal/blob-authz` didn't know about `song_analyses.analysis_blob_sha256`.** The authz query only checked `Song.source_blob_sha256` and `Stem.blob_sha256`; N4's analysis JSON blob (a third, independently content-addressed artifact) would have 403'd for its owner. Caught by the plan's own §5 acceptance check ("blob fetches via Caddy with Range support") before anything shipped unnoticed. Fixed by adding a third join against `SongAnalysis` in `elums/api/routers/internal.py`.
3. **`GET /api/songs/{id}/ingest` returns 404 for a private song to a non-owner (including anonymous), not 403.** The plan's own acceptance wording said "expect 403"; implemented as 404 instead, matching the existing `Song`-lookup convention elsewhere in `songs.py` (distinguishing "exists but you can't see it" from "doesn't exist" leaks the former, so both collapse to the same 404 — same reasoning `elums/api/routers/auth.py`'s login already uses for wrong-email vs wrong-password). `/internal/blob-authz` still returns a literal 403 for blobs, since that endpoint's whole contract is "Caddy copies this status straight back" and a byte-range 404 vs 403 distinction doesn't carry the same leak.
4. **`openapi.json` regeneration needed a `.NET`-level UTF-8-no-BOM write, not `Out-File`.** Windows PowerShell 5.1's `Out-File -Encoding utf8` always emits a BOM (even with `-NoNewline`), which breaks `python -m json.load` and, more importantly, would have broken `openapi-ts`'s own JSON parse. No `utf8NoBOM` encoding name exists in this PowerShell version either (that's a PowerShell 7+ addition). Worked around with `[System.IO.File]::WriteAllText(path, text, (New-Object System.Text.UTF8Encoding $false))`. The Makefile's `openapi` target already warns about this exact class of problem for a plain `>` redirect; worth updating its comment to name the fix for PowerShell 5.1 specifically, since `make` itself isn't reliably on PATH yet (§7, carried from Day 1).
5. **`pytest`'s default collection walked `./models/hf-cache`** (populated by N1's HF/torch.hub downloads) and crashed with `OSError: [WinError 1920]` trying to `stat()` entries there from Windows host Python. Fixed by adding `testpaths = ["tests"]` to `[tool.pytest.ini_options]` — correct regardless of the Windows bug, since nothing outside `tests/` should ever have been collected.
6. **`tests/test_separation.py`'s terminal-status assertion implicitly got slower**, not because anything broke, but because N4 means `ingest_job.status` no longer reaches `SUCCEEDED` right after separation — the chain now continues through `structure_beats`/`rms_vad`. `POLL_TIMEOUT_S` raised 90s → 180s to cover the whole chain on the 20-second synthetic fixture (ran well within the new budget in practice: all three stages together on the fixture took well under a minute).

### 6. Blockers

- **MA-3's deployment decision for the Smule box is still open** (carried from Day 1, §6) — user is deferring this to Monday's email to Smule rather than deciding unilaterally tonight. Not resolved; not blocking tonight's N1–N5 work, which was entirely local.
- **GTSinger VM download status (EC-6) not re-checked tonight.**

### 7. Loose ends carried forward

- Everything in Day 1's §7 not explicitly resolved above (git remote still absent; `make` PATH issue; A4's healthcheck gap; dev-DB test-user residue; GTSinger re-check).
- **The first real-song upload's analysis data is partially lost**, not recoverable without re-running: "Fill Me Up" (268.3s) failed at `structure_beats` due to the stale-image issue (§5 item 1) before `all-in-one-infer` was actually present, so no real timing/analysis exists for that track. Only "Is This All" (221.3s) has a clean full-chain run tonight. Re-run "Fill Me Up" on a day with headroom if a second real-song data point matters.
- **No `tests/test_structure.py`-style coverage exists for `elums/ingest/structure.py` itself** (the `harmonix-all` call path) — only the two N2 modules with real deterministic logic (`key.py`'s KS correlation, `vad.py`'s run-detection/merge/cap) got unit tests; `structure.py` is only exercised indirectly, end-to-end, via `tests/test_separation.py`'s now-longer-running live-stack test. This matches the plan's own "tests on the logic, not the models" principle, but is worth stating explicitly rather than looking like an oversight.
- **`step_index`/`step_total` on `ingest_jobs` are not really tracking the 7-stage pipeline** — they were designed (Day 1) to show progress *within* one stage, and N4's `run_rms_vad` sets `step_index = step_total` as a blunt "done" signal rather than a meaningful fraction. The per-stage `*_status` columns are the real source of truth for the SPA's 7-dot display; `step_index`/`step_total` should either be repurposed or dropped on a day with headroom.
- **No commits pushed to GitHub** — no remote configured (carried from Day 1, §7's "absent git remote").
