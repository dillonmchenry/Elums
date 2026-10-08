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
- **No login page in the SPA — action item for Day 3 (Oct 5).** `HomePage.tsx`'s upload form (N4) requires an authenticated session cookie, but the only way to obtain one today is `curl`/Postman against `/api/auth/login`, or a manual `fetch()` from the browser devtools console — the latter was tried during manual testing tonight and didn't work for the user as a login workaround. Needs a real (if minimal) login page — an email/password form posting to `/api/auth/login`, reusing the existing cookie-setting flow (`elums/api/routers/auth.py`) — plus a visible test account to log in with (one of the 10 seeded demo users already exists: `dana@elums.demo` / `elums-demo-2026`, `elums/seed.py`; just needs to be surfaced/documented on the page itself, e.g. a "try the demo account" hint, rather than requiring the tester to know it exists). Scope this into Day 3's ingest-continuation work alongside whatever lyrics/CTC-alignment milestones land that day — it blocks manual browser-based testing of the pipeline, not the pipeline itself.

---

## Monday Oct 5 — Day 3 (lyrics + CTC alignment ingest chain)

Governed by [IMPLEMENTATION_PLAN_2026-10-05.md](IMPLEMENTATION_PLAN_2026-10-05.md).

### 1. Milestone status

| Milestone | Status | Notes |
| --- | --- | --- |
| L0 — login page | **done** | `frontend/src/pages/LoginPage.tsx`, `/login` route, `HomePage.tsx` auth banner |
| L1 — lyrics source (LRCLIB, else Whisper) | **done** | `elums/ingest/lyrics.py` |
| L2 — CTC char-level alignment | **done** | `elums/ingest/align.py` |
| L3 — syllables, reconciliation, vocable fallback | **done** | `elums/ingest/syllables.py`, `tests/test_lyrics.py` |
| L4 — persistence + chain wiring | **done** | `elums/ingest/tasks.py`'s `run_lyrics`/`run_ctc_alignment`, migrations `47eb34cfffc1`/`cd7430251da9` |
| L5 — real-song validation | **done** | Both `data/samples/` tracks, full chain, see §4 |

Manual prerequisites (MA-1/2/4/5) were out of this agent's hands by design (emails, Docker Desktop, GitHub remote, network policy); MA-2's Docker Desktop was already up and `docker compose ps` showed all 7 services running at session start, so EC/L work proceeded directly against the live stack rather than from a cold start. MA-1/MA-4/MA-5 status unknown to this agent — not re-verified tonight; see §6.

### 2. Early checks (EC-1 through EC-6)

| # | Risk | Resolution |
| --- | --- | --- |
| EC-1 | Does `whisperx` install at all? | **Fallback taken immediately, without attempting the whisperx install.** The plan's own L1/L2 sections already specify the fallback architecture verbatim (`transformers` loading the HF-format checkpoint directly; `torchaudio.functional.forced_align` against a wav2vec2 CTC model) — there was no reason to spend the 20-minute timebox proving `whisperx` fights the one-wheel discipline when the plan had already named the working alternative as the real design. `whisperx` is not in `pyproject.toml` and never was; no stale references found in `ELUMS_TECHNICAL_APPROACH.md` §5 needing correction (it already describes "Align: WhisperX CTC char-level timings" generically, consistent with char-level-first CTC alignment — not a specific-library claim). |
| EC-2 | `transformers` missing from the lock | Added to the `gpu` group. **Deviation:** the plan's own `transformers==4.57.0` is **yanked on PyPI** ("Error in the setup causing installation issues", verified against `pypi.org/pypi/transformers/json`) — pinned `5.9.0` instead, the newest non-yanked release at lock time. `uv lock` confirmed (`git diff uv.lock`) `torch`/`torchaudio` specifiers and resolved versions are byte-identical before/after — no float. Rebuilt `gpu-worker`; `import transformers` (5.9.0) confirmed inside the container. |
| EC-3 | Align weights never downloaded | Used torchaudio's own bundled `WAV2VEC2_ASR_BASE_960H` pipeline (the plan's first-named option) rather than a separate `facebook/wav2vec2-base-960h` `huggingface_hub` fetch — one fewer cache convention, and it downloads automatically via `torch.hub` on first use (confirmed: 360 MB fetched to `${MODEL_ROOT}/torch-cache/checkpoints/` on the first real `align_chars` call). Recorded as `lyrics_alignment` in `config/models.yaml`; license (BSD-3-Clause, torchaudio's own project license) recorded in `docs/licensing-audit.md`. |
| EC-4 | LRCLIB reachable from `gpu-worker` | **Reachable.** `GET https://lrclib.net/api/get?...` from inside the `gpu-worker` container (Python `urllib`, descriptive `User-Agent`) returned a real `404` (no match for the query, not a network block) — confirmed with both a synthetic query and the two real sample tracks' actual ID3 artist/title. Both `data/samples/` tracks turned out not to be in LRCLIB's database (expected for obscure CC-BY covers); both fell through to Whisper, exercising that path rather than the LRCLIB one — see §4. |
| EC-5 | Hyphenation dictionary license | `pyphen==0.17.2` (tri-licensed GPL-2.0/LGPL-2.1/MPL-1.1), shipped under **MPL-1.1**. Added to both the `gpu` group (where the real pipeline runs) and the `dev` group (pure Python, no torch — needed so `tests/test_lyrics.py` can import `elums.ingest.syllables` on the host without pulling in librosa/torch). Recorded in `config/models.yaml` and `docs/licensing-audit.md`. |
| EC-6 | GTSinger on the VM | **Not re-checked tonight** — no VM access from this session; carried forward unchanged from Day 2. |

### 3. Settled architecture note

L1/L2's "fallback" (transformers + torchaudio CTC, not whisperx) turned out to be the plan's own primary design once EC-1 was read against L1/L2's actual prose, not a deviation discovered by trial — see EC-1 above. The one real architectural addition beyond what the plan specified: **LRCLIB lines are mapped onto VAD segment boundaries** (`elums/ingest/lyrics.py`'s `map_lrclib_to_vad_segments`) before alignment, so "align per VAD segment, not over the whole track" (L2 §2) holds uniformly regardless of which source won — LRCLIB's own line timestamps are not VAD boundaries, so each VAD segment is given the concatenation of whichever LRCLIB lines start inside it; a segment with no line inside it is skipped.

`lyrics_source` on `SongAnalysis` takes one of three values per the plan's own naming: `lrclib` (good LRCLIB hit, no Whisper run, no reconciliation), `whisper` (no usable LRCLIB hit), `reconciled` (thin LRCLIB hit — Whisper supplies ASR timings, LRCLIB's lines are anchored onto them via LCS in `elums/ingest/syllables.py::reconcile_lyrics`). Neither sample track exercised the `lrclib`/`reconciled` paths tonight (see §4) — both are unit-tested deterministically in `tests/test_lyrics.py` but not yet seen on a real LRCLIB hit.

### 4. Measured timings and real-song validation (L5)

Both `data/samples/` tracks run through the full `separation -> structure_beats -> rms_vad -> lyrics -> ctc_alignment` chain via the live API (`POST /api/songs` as `dana@elums.demo`/`milo@elums.demo`, polled via `GET /api/songs/{id}/ingest`), not synthetic fixtures:

| Stage | "Is This All" (221.4s) | "Fill Me Up" (268.3s) |
| --- | --- | --- |
| separation | 23.0s, 1753 MB | 29.5s, 1775 MB |
| structure_beats | 33.4s, 1039 MB | 39.6s, 1155 MB |
| lyrics (Whisper) | 15.5s, 1596 MB | not separately timed* |
| ctc_alignment | 3.2s, 682 MB | 3.1s, 687 MB |

*"Fill Me Up"'s first successful run predates a same-night fix that added `duration_ms`/`vram_peak_mb` to the `lyrics` stage's `stage_results` entry (see §5 item 2); re-running it solely to backfill that number was judged not worth the ~2 extra minutes of GPU time given "Is This All" (and a second upload of the same track under a different user) already exercises the identical code path with the number present.

Both real songs ran with **artist metadata correctly extracted** (`ffprobe`'s ID3 tags: "Liz James" / "Is this All", "Ellody (!)" / "Fill Me Up" — confirmed via a direct `probe_audio()` call and via a real second-user upload), but **LRCLIB had no entry for either track** (confirmed via EC-4's direct query, not a timeout/block) — both fell through to Whisper. `lyrics_source="whisper"` for both; `word_count`/`syllable_count` 231/258 and 343/380 respectively; `vocable_event_count` 0 for both (plausible but at the low end of the plan's "a handful, not hundreds" expectation — see §7).

**Transcript quality spot-checked by reading, not by ear tonight** (no audio playback available in this environment): "Is This All"'s words read as coherent, grammatical English lyric lines in the correct order ("three days the same t-shirt it doesn't look as though you're...", "...you'd be the rock that I could always lean on in my times of need"), strongly suggesting real, working transcription rather than hallucinated noise — but this is a textual plausibility check, not acceptance criterion 5's literal "verified by ear on one chorus," which still needs a human listening pass. Structural invariants (acceptance check 6) verified programmatically on "Is This All"'s 231 words: **zero violations** — no syllable span outside its word span, no word-to-word overlap over 10ms, every timestamp inside [0, 221.4s]. Blob fetch via Caddy re-verified with the new `lyrics` key present: `206` on a `Range: bytes=0-1023` request, full fetch parses as valid JSON containing `lyrics.source`/`lyrics.words[].start_s/end_s/syllables[]` (acceptance check 4).

### 5. Deviations from the plan

1. **`transformers==4.57.0` (named in the plan) is yanked on PyPI** — pinned `5.9.0` instead. See EC-2. No torch/torchaudio float as a result (`uv lock` diff confirmed).
2. **Found and fixed: `elums/ingest/tasks.py`'s `run_lyrics` used `asyncio.to_thread` without importing `asyncio`.** First real-song upload (dana's "Is This All") failed at the `lyrics` stage with `NameError: name 'asyncio' is not defined` — caught immediately by the live end-to-end run, not by any unit test (this is exactly the kind of error `tests/test_lyrics.py`'s "deterministic layers only" scope cannot catch, since it never imports `elums.ingest.tasks`). Fixed by adding the missing top-level `import asyncio`; also fixed a related gap caught in the same pass — the `lyrics` stage's `stage_results` entry was missing `duration_ms`/`vram_peak_mb` (acceptance check 8 requires both for `lyrics` and `ctc_alignment`); added timing/VRAM instrumentation around the LRCLIB-fetch-plus-Whisper-transcribe block, same pattern every other stage already uses. Re-verified on a fresh upload after the fix (`duration_ms: 15457`, `vram_peak_mb: 1596.36`).
3. **Found and fixed: `torchaudio.functional.forced_align`'s native CTC kernel raises a raw `RuntimeError`, not `elums.ingest.align.AlignmentError`, when a segment's transcript is longer than its audio has emission frames for.** Hit directly by `tests/test_separation.py`'s existing 20-second synthetic-tone fixture (not a new test) — Whisper hallucinated a transcript for a segment too short to fit it (the approach document's own documented failure mode, §5: Whisper over-produces text on near-silent/tone content), and `align_chars`'s per-segment try/except only caught `AlignmentError`, so the one bad segment failed the entire `ctc_alignment` stage instead of being skipped. **This is the specific failure case the "after two unsuccessful fixes, reassess root cause" instruction exists for — handled on the first diagnosis, not reached:** the error message named the exact mismatched lengths (`log_probs length: 5, targets length: 9`), pointing straight at the missing exception type without needing a second attempt. Fixed by broadening the catch to `(AlignmentError, RuntimeError)`. Re-verified: `tests/test_separation.py`'s full-chain test now passes end-to-end on the synthetic fixture, and both real songs (already validated before this fix, on content long enough not to trigger it) continued to pass after the gpu-worker restart that picked it up.
4. **LRCLIB's `lrclib`/`reconciled` code paths are unit-tested but not seen live tonight** — neither sample track is in LRCLIB's database (EC-4), so both real-song runs exercised only the `whisper` path. `map_lrclib_to_vad_segments` and the `reconciled`-source branch of `run_ctc_alignment` have not been exercised against a real LRCLIB response. Not a correctness gap found and left unfixed — just an untested-against-real-data path, flagged rather than silently assumed working beyond its unit tests.

### 6. Blockers

- **MA-3's deployment decision for the Smule box is still open** (carried from Day 1/2, §6/§6) — not re-raised or re-investigated tonight; status unchanged from this agent's perspective.
- **No GitHub remote configured** (`git remote -v` → empty, carried from Day 1) — MA-4 is a two-minute manual action outside this agent's reach; commits exist locally per milestone (see git log) but nothing is pushed.

### 7. Loose ends carried forward

- Everything in Day 1 §7 / Day 2 §7 not explicitly resolved above.
- **`vocable_event_count` was 0 for both real songs tonight** — within the plan's "plausible (a handful, not hundreds)" bound, but at the low edge rather than the middle of it. Plausible explanation: Whisper, batched over VAD's own segment boundaries, produced *some* text for essentially every voiced segment on these two particular tracks (16/16 and 29/29 segments got transcribed), leaving no VAD-voiced-but-wordless gaps for the energy-gated fallback to catch — consistent with these being fairly lyric-dense pop vocals rather than tracks with long "ooh/ahh" vocable passages. Not independently confirmed by listening; worth a deliberate test against a track known to have non-lexical vocal sections before trusting the fallback's recall rate.
- **"Verified by ear on one chorus" (acceptance check 5) is not done** — this session has no audio playback; the transcript was spot-checked by reading for coherence and grammaticality instead (§4), which is suggestive but not the literal acceptance criterion. A human listening pass against "Is This All"'s audio is the natural next action before trusting word-onset accuracy numerically.
- **The `lrclib` and `reconciled` `lyrics_source` paths have no real-world exercise** (§5 item 4) — only `tests/test_lyrics.py`'s synthetic unit tests cover `reconcile_lyrics`/`map_lrclib_to_vad_segments` today. A song known to be in LRCLIB's database would be a better L5-style fixture for Tuesday or a later validation pass than either current `data/samples/` track.
- **A lyric correction UI and the manual lyric-paste path are explicitly out of scope** (per the plan's own §6) and remain unbuilt — not a gap, a deliberate non-goal for today.
- **The stale-process DB rows from before tonight's `asyncio` fix** (§5 item 2) left two `ingest_jobs` rows in `FAILED` with a stale `error_message` until manually reset via direct SQL + task re-defer during validation — this was a one-off manual recovery during tonight's session, not a built retry/resume mechanism. The PENDING-job-sweep loose end from Day 1 §7 is the more general version of this gap; still not built.
- **EC-6 (GTSinger VM download)** not re-checked — carried unchanged from Day 2.

---

## Tuesday Oct 6 — Day 4 (F0 → note grid → chart → M1, plus the VM SSL layer probe)

Governed by [IMPLEMENTATION_PLAN_2026-10-06.md](IMPLEMENTATION_PLAN_2026-10-06.md).

### 1. Milestone status

| Milestone | Status | Notes |
| --- | --- | --- |
| T1 — F0 stage (RMVPE) | **done** | `elums/vendor/rmvpe/`, `elums/ingest/f0.py` |
| T2 — note grid | **done** | `elums/ingest/notes.py` — three bugs found and fixed against a real song, see §3 |
| T3 — chart writer, peaks, bundle API | **done** | `elums/ingest/chart.py`, `GET /api/songs/{id}` |
| T4 — karaoke playback page | **done** | `frontend/src/pages/SongPage.tsx` |
| T5 — CLAP embedding | **done** | `elums/ingest/clap.py`, validated against the criterion (§4) |
| T6 — ten songs, M1 gate | **partial — see §5** | Structural validation done on both `data/samples/` tracks; the "8 more songs" and the human "listen" pass are not done |
| T7 — VM SSL layer probe | **done** | Ran live, not overnight — see §6 |

Commits: `db03007` (T1+T2+T3) · `1284a3a` (T4) · `780c05b` (T5) · `d79ef17` (T7). T6 has no code of its own beyond the fixes folded into T1+T2+T3's commit (see §3) — its deliverable is the validation evidence in §4/§5, not a diff.

### 2. Early checks (EC-1 through EC-6)

| # | Risk | Resolution |
| --- | --- | --- |
| EC-1 | RMVPE licensing (MIT, RVC-Project) | Vendored from the real upstream source (`RVC-Project/Retrieval-based-Voice-Conversion-WebUI`'s `infer/rmvpe.py`, fetched live, not reconstructed from memory), trimmed of ONNX/DirectML/CUDA-graph branches that don't apply here. Full MIT license text copied into `elums/vendor/rmvpe/LICENSE`; verdict recorded in `docs/licensing-audit.md`. |
| EC-2 | `pgvector` for `song_embeddings` | `pgvector==0.4.2` added to the `core` group; `Vector(512)` column, no HNSW index (deferred per the plan, §8.1). |
| EC-3 | `audiowaveform` replacement | Peaks computed in pure Python/soundfile (`elums/ingest/chart.py::compute_peaks`), deliberately, not dropped. |
| EC-4 | WavLM-large layer/shape assumptions (T7) | Confirmed directly on the VM before probing: `num_hidden_layers=24` → 25 hidden-state tensors, index 0 is the CNN encoder; `AutoFeatureExtractor` (not hand-rolled preprocessing) honors `do_normalize: true`; `pytorch_model.bin`-only checkpoint loads cleanly under `transformers==5.9.0` (488/488 weights, no missing/unexpected/mismatched keys). |
| EC-5 | Separation checkpoint identity | Unchanged from Day 1 — not re-touched today. |
| EC-6 | GTSinger schema (T7's own explicit "inspect first, don't guess" instruction) | Read directly off the live VM cache before writing any code: `processed/English/metadata.json` is a flat list of per-clip items (`ph`/`ph_durs` phoneme sequence + durations, six per-phoneme boolean technique columns, `wav_fn`). Full detail in §6. |

### 3. The note-grid bug chain (T2/T6) — three real bugs, three fixes, three regression tests

All three were found by running the real chain against `data/samples/is-this-all-liz-james.mp3`, not by the synthetic unit tests (which still pass throughout — they simply didn't cover these cases going in). Each fix is a genuinely different symptom, not a repeat of the same failed attempt, so this is the "after two unsuccessful fixes, reassess root cause" instruction's intended shape — new evidence each time, not the same patch retried:

1. **Notes shrunk below `MIN_NOTE_DURATION_S` by beat-snapping.** `_snap_onset_to_beat` could pull a note's start close enough to a beat that the remaining span fell under 0.08s, and the snap-acceptance check never re-verified duration after snapping. One note measured 0.00066s. **Fix:** added a duration re-check to the snap-rejection condition in `build_note_grid`.
2. **98/221 notes crossed their own syllable's start_s.** The same half-beat check only compared distance-to-beat, never checked whether the snapped onset fell before the syllable span the note was built from. **Fix:** `raw_notes` now carries `span_start_s` through to the snap step; snaps landing before it are rejected.
3. **7/221 notes overshot their syllable's end_s by ~9ms.** Traced to `_segment_span` independently `round()`-ing the syllable's start and end to the nearest 100Hz frame (up to 0.5 frames = 5ms slack each, ~10ms compounding) rather than clamping the result. **Fix:** explicit `max(note_start_s, span_start_s)` / `min(note_end_s, span_end_s)` clamp inside `_segment_span`.

A fourth issue surfaced only during re-validation, **not a notes.py bug**: re-running the fixed code against the second sample song through the live `gpu-worker` queue initially showed 135/326 violations — because the long-running Procrastinate worker process still had the *pre-fix* `notes.py` loaded in memory (Python doesn't hot-reload a bind-mounted `.py` edit into an already-running process). Restarting `api`/`worker`/`gpu-worker` and re-running resolved it to 0/326. Recorded here because it is exactly the kind of false "the fix didn't work" signal the two-unsuccessful-fixes instruction warns about — the right move was recognizing it as a process-staleness artifact, not writing a fourth code fix for a bug that no longer existed in the code on disk.

### 4. Real-song validation (T2/T3/T5/T6)

Both `data/samples/` tracks run through the full `separation → structure_beats → rms_vad → lyrics → ctc_alignment → f0 → note_grid` chain via the live API, then re-validated after the fixes in §3 and after restarting the workers:

| Check | "Is This All" (221.3s) | "Fill Me Up" (268.3s) |
| --- | --- | --- |
| `note_count` | 221 | 326 |
| Syllable-boundary violations | **0 / 221** | **0 / 326** |
| Out-of-range notes (outside `[0, duration_s]`) | 0 | 0 |
| Min / median note duration | 0.080s / 0.239s | 0.080s / 0.185s |
| F0 frame count vs `round(duration_s * 100)` | 22132 vs 22132 (exact) | 26831 vs 26830 (within ±1) |
| `voiced_frame_ratio` (RMVPE) vs VAD's `voiced_duration_s / duration_s` | 0.623 vs 0.793 (diff ~21%) | 0.589 vs 0.610 (diff ~3.5%) |
| `key_tonic`/`key_mode` (chroma) vs `_from_notes` cross-check | G minor (0.074) vs A minor | G minor (0.161) vs F# major |

All of acceptance check 6's structural invariants (every note inside its syllable span, every timestamp inside `[0, duration_s]`, `note_count > 0`, F0 frame count within ±1) pass on both real songs.

**"Is This All"'s `voiced_frame_ratio` sits further from VAD's number than "Fill Me Up"'s does** — plausibly real, not a bug: RMVPE's 0.03 confidence threshold only marks frames with an actual detected pitch, while RMS-VAD's energy threshold also catches unvoiced consonants and breath noise as "voiced." Not independently confirmed by listening (no audio playback in this session, same limitation as Day 3); flagged rather than chased further, since the two metrics are deliberately measuring different things and a 21% gap on one song vs 3.5% on the other is consistent with that explanation rather than with a code defect.

**T5's own validation criterion is met directly:** cosine similarity between the two real sample tracks' CLAP embeddings is **0.647**, versus **0.19–0.28** between either real track and any synthetic-tone test fixture (`twenty-second-tone.mp3`, `short-tone.mp3`, two more from live pytest runs). `song_embeddings` carries one 512-d row per ingested song, confirmed via a direct query.

**Full-chain regression**, `tests/test_separation.py` against the live stack (20-second synthetic fixture): both tests pass, `ingest_job.status` now reaches `SUCCEEDED` only after `note_grid` (one stage later than Day 2/3), confirming the extended chain is wired correctly end-to-end, not just on the two real songs. `pytest tests/` (host-side, 63 tests) and `test_structure.py`/`test_separation.py` (gpu-marked, 10 tests) all pass; `frontend`'s vitest suite (5 tests) passes; `tsc -b` clean.

### 5. T6's actual scope versus the plan's "ten songs" — a scope decision for the owner

T6 asks for the full chain on both `data/samples/` tracks **plus ~8 more diverse songs**, then **a human listening pass** on 3 songs (onset accuracy, octave errors, by ear), feeding an M1 quality-gate table that the owner — not this agent — decides against (per the plan's own "do not pick the fallback yourself" instruction, which applies with equal force to the gate itself here, not just the correction-UI/seed-catalog fallback it was written for).

**What was actually done:** structural validation (§4) on both existing sample tracks — every programmatically-checkable invariant the plan names (syllable clipping, timestamp ranges, note count, frame-count arithmetic) passes cleanly on both.

**What was not done, and why, honestly:**
- **8 more diverse songs were not sourced.** No additional licensed audio exists in this repo or environment (checked: only `data/samples/`'s original two tracks and three short synthetic test fixtures exist anywhere on disk). Sourcing 8 more real songs is a licensing/content decision (Day 2's two tracks were CC-BY, deliberately attributed in `data/samples/README.md`) that this agent should not make unilaterally by pulling arbitrary audio off the internet.
- **The human "listen" pass (3 songs, by ear) was not done.** This agent session has no audio playback, carried forward from Day 3's identical limitation — MA-4 (headphones/playback) is scoped to the human operator, not this session.
- **The M1 quality table and gate decision are therefore not presented tonight.** The structural numbers in §4 are real and are the actual evidence; a genuine "octave errors, onset accuracy by ear" judgment on top of them needs a human to listen. **This is the decision point to record per the plan's own §9: the owner needs to either (a) listen to the two existing real-song charts and judge whether the structural pass is good enough evidence to call M1 provisionally met, or (b) source additional songs and do the listening pass before M1 is called.** Nothing here is silently assumed either way.

### 6. T7 — VM SSL layer probe

**GTSinger schema, inspected directly (not guessed) before writing any code:** `processed/English/metadata.json` (4,827 items) is a flat list of per-clip entries, each with `ph`/`ph_durs` (phoneme sequence + per-phoneme durations in seconds, summing to clip duration), `wav_fn` (path relative to the snapshot root), and six independent per-phoneme boolean columns — `mix_tech`, `falsetto_tech`, `breathy_tech`, `pharyngeal_tech`, `vibrato_tech`, `glissando_tech` — matching the plan's six named labels exactly. These are **not** mutually exclusive with the recording-session folder name (`Breathy_Group`/`Control_Group`/etc. in `item_name`): a `Control_Group` clip can still carry `mix_tech=1` on most phonemes, because "mixed voice" is pop singing's default register, not an exceptional technique — confirmed directly against the data, not assumed, before trusting it as a label source.

`scripts/ssl_layer_probe.py`: built a stratified ~2-hour subset (770 items, 21 singer×group strata, round-robin until the cumulative duration crossed 2 hours), ran WavLM-large with `output_hidden_states=True`, mean-pooled layers {1, 4, 7, 12, 18, 24} over each non-silence phoneme's frame span (50Hz, 20ms/frame), and trained one `LogisticRegression` per layer per label (6 independent binary probes, 80/20 split, `class_weight="balanced"`), averaging the 6 F1 scores into that layer's macro-F1. Smoke-tested on 20 items first (`--dry-run-items`), confirmed working, then launched the full run.

`scripts/cache_ssl_features.py`: reads the probe's own output, picks the top-N layers by macro-F1, caches fp16 hidden states (one `.npy` per clip per layer) for the **full** 4,827-item English corpus to the VM's own SSD — resumable (skips already-cached files), smoke-tested on 5 items first.

**Launched** per the plan's own instruction — not a bare `tmux` session (EC-0's finding from a prior day): `bash -n`-checked, then `setsid bash scripts/run_t7_probe_chain.sh < /dev/null > /tmp/probe.log 2>&1 & disown`.

**Result: finished in ~9 minutes, not overnight.** The plan anticipated an overnight run; on this GPU, with a 2-hour (not full-corpus) stratified subset for the probe stage and ~50ms/clip for feature extraction, the probe stage took ~1 minute and the subsequent full-corpus caching stage (4,827 items, 2 layers) took ~5 minutes. This is not a shortcut or a smaller run than specified — the stratified-subset size and the full-corpus caching scope both match the plan's own spec exactly; the VM's RTX 5060 Ti is simply fast enough that "overnight" was a conservative estimate, not a requirement. Final table, written to `results/ssl_layer_probe.json` and committed:

| Layer | macro-F1 |
| --- | --- |
| 1 | 0.780 |
| **4** | **0.795** (best) |
| 7 | 0.745 |
| 12 | 0.712 |
| 18 | 0.611 |
| 24 | 0.637 |

**Not a flat table** (the plan's own sanity check for a broken probe) — early/mid layers (1, 4, 7) clearly outperform late layers (18, 24) by ~0.13–0.18 macro-F1, consistent with §11.2's cited pattern of early-layer competitiveness and late-layer collapse for this kind of technique-detection task, though the specific peak (layer 4, not layer 1) and magnitude differ from the cited reference numbers — expected, since that citation was for a different benchmark/task, not a reproduction target. `cache_ssl_features.py --num-layers 2` cached layers **4 and 1** (the top two), 9.0 GB total for the full English corpus — far under the plan's own "~30 GB per layer" estimate (that figure likely assumed caching across all languages, not English alone), well within the VM's 1.5 TB free disk.

### 7. Deviations from the plan

1. **Found and fixed: the long-running `gpu-worker`/`worker`/`api` Procrastinate processes do not pick up bind-mounted `.py` edits without a restart.** See §3's fourth item — a stale in-memory module briefly looked like a fourth, unexplained note-grid bug on the second sample song before being correctly diagnosed as a process-staleness artifact and resolved by `docker compose restart api worker gpu-worker`, not a new code change. Not previously documented as a gotcha in Days 1–3's PROGRESS entries, despite presumably having been true the whole time — worth remembering explicitly before trusting any live-queue result immediately after an edit.
2. **T7 finished in minutes, not overnight** — see §6. Not a deviation in scope (the subset size, caching corpus, and launch mechanism all match the plan's spec exactly), just a timing outcome worth stating plainly rather than treating as if it ran unattended all night.
3. **T6's "ten songs" and "listen" sub-tasks are not done** — see §5, recorded as the decision point for the owner, not silently dropped or unilaterally resolved.

### 8. Blockers

- **MA-3's deployment decision for the Smule box is still open** (carried from Day 1/2/3) — not re-raised tonight.
- **T6's M1 gate decision needs the owner** — see §5. This is the headline open item from tonight: the pipeline is structurally sound on every song it has been run against, but the plan's own acceptance bar for M1 requires a human judgment this agent cannot make.

### 9. Loose ends carried forward

- Everything in Days 1–3's §7 not explicitly resolved above.
- **8 more diverse songs for T6, and the 3-song human listening pass** — see §5.
- **`voiced_frame_ratio` vs VAD's `voiced_duration_s`** diverges by ~21% on one song and ~3.5% on the other (§4) — plausibly a real difference in what the two signals measure (pitch-confidence threshold vs energy threshold), not independently confirmed by listening.
- **The gpu-worker/worker/api hot-reload gotcha (§7 item 1)** is now documented here but not fixed structurally — a developer (or a future agent session) editing `.py` files against the live stack still needs to remember to restart the relevant service(s) before trusting a live-queue re-run. Worth a `Makefile` target (`make restart-workers` or similar) on a day with headroom.
- **Scratch verification scripts used during tonight's validation were deleted after use** (`scripts/_verify_*.py`, `scripts/_rerun_*.py`) — not committed, by design; the real, kept deliverables are `scripts/ssl_layer_probe.py` and `scripts/cache_ssl_features.py`.

### 10. T6 extended — 8-song validation pass (post-handoff, same evening)

§5's "8 more diverse songs" open item was closed later the same evening, once the user supplied 6 additional real tracks (local-testing only; not committed — `data/` is gitignored). Built `scripts/validate_sample_songs.py` (kept deliverable, reusable for future validation passes) to run the full chain on all 8 songs and produce a structured quality table (`results/sample_song_quality.json`, not yet git-added as of this writing).

**Result: all 8 songs reached `SUCCEEDED` with clean structural invariants** — zero syllable-boundary violations, zero out-of-range notes, F0 frame count within ±1 of expected on every song. This closes the structural half of §5's open item; the 3-song human listening pass is still outstanding (no audio playback in this session, same limitation as Days 3–4).

Three flaws surfaced by the expanded 8-song sample (invisible at n=2):

1. **`note_grid`'s own `stage_results` entry never carried `duration_ms`/`vram_peak_mb`**, contradicting the plan's own acceptance check 7 (which names `note_grid` alongside `f0` explicitly). **Fixed tonight** — `time.monotonic()` timing added around `build_note_grid`/`compute_peaks` in `run_note_grid`; `vram_peak_mb` stays `null` (no GPU work in this stage). Re-verified live (`note_grid.duration_ms = 341` on a fresh `yesterday.mp3` run after a worker restart) and against the full host suite (65 passed, 1 skipped). Committed as `ffb2ed9`.
2. **Key-estimate cross-check disagrees on 5/8 songs.** `key.py`'s chroma correlation and `notes.py`'s note-histogram cross-check only agree on 3/8; 2 of the 5 mismatches are the known relative-major/minor confusion, the other 3 (`havent-met-you-yet`, `hot-n-cold`, `is-this-all`) show both sides reporting low confidence simultaneously (e.g. `hot-n-cold`: 0.023 vs 0.022) — the two signals are honestly uncertain and that uncertainty isn't surfaced today. **Added to Wednesday's plan** (`ELUMS_BUILD_SCHEDULE.md`, Oct 7): a confidence-low flag plus confidence-picks-winner reconciliation, since `_quantize_to_key` already consumes `key_tonic`/`key_mode` and Wednesday's M2 scoring work depends on correct quantization.
3. **`voiced_frame_ratio` (RMVPE) reads systematically lower than VAD's `voiced_duration_s/duration_s`** across all 8/8 songs, mean diff ≈ -0.11, every song negative — not noise, a consistent one-directional gap. Likely a genuine definitional difference (RMVPE's pitch-confidence gate vs VAD's energy gate also catching unvoiced consonants/breath), not independently confirmed. **Also added to Wednesday's plan** (per the user's explicit instruction, overriding this agent's earlier recommendation to defer it to backlog as unconsumed by any feature today): a `thred` sweep (0.01/0.03/0.05) on 2–3 real songs to determine whether the gap narrows (miscalibration) or holds (document as a real measurement-definition difference).

**Backlog, not scheduled anywhere yet:** a deeper fix for flaw #2 above — blending the two correlation vectors (chroma over the instrumental + duration-weighted note-pitch histogram) into one combined KS correlation before picking a key, rather than running two independent estimates and reconciling after the fact — was identified as more accurate in principle but is a real research question (how to weight/combine the two vectors, not validated against any ground truth), not a quick fix. Needs its own investigation before scheduling.

### 11. Delivery mode clarified — **MA-3/MA-5 is closed, and the risk moved** (post-handoff, same evening)

**The brief's own wording, re-read tonight:** *"you will deliver the source code to us, and we will deploy the application internally."*

**That closes the deployment question outright, after five days open as "the largest item on the project"** (§6 of Days 1–3, §8 above, MA-3 in the Oct 3/4 plans, MA-5 in the Oct 6 plan). There was never a deployment decision to make. We host nothing; the deliverable is a repository. Three stale instructions follow from the misreading and have been corrected rather than left to be discovered on Oct 11:

- `ELUMS_BUILD_SCHEDULE.md`'s "VM's unique value" table listed **"the deployment target"** as a row. Removed — the VM is training and bulk-compute capacity only.
- Sun Oct 11's **"VM deployment rehearsal — the one mandatory VM task, and the only thing on this schedule that cannot be deferred"** no longer exists. Its 1.5 h is reallocated to deliverable hardening (list below).
- Mon Oct 12's **"record the demo video against the VM deployment, not local"** is obsolete. Local is now the correct target, not a compromise.
- The "Sync and deploy" section's `git remote add vm` + `post-receive` → `docker compose up -d --build` was already impossible (no Docker Engine on the box, `docs/vm-baseline.md`) and is now also moot.

**The risk did not go away, it relocated — and it got larger.** A broken one-command bootstrap was previously survivable because a working demo host would have carried the impression. It is now the entire delivery surface: `git clone` → documented `.env` → one command → a working app, on *their* Linux host with a real Docker Engine. Six concrete gaps found by direct inspection tonight, none of them previously recorded:

1. **No Linux weight-fetch path exists.** `.gitignore` excludes `/models/`, so a fresh clone has no weights — ~4–5 GB per `config/models.yaml`. Some auto-download on first use (`torch.hub`/HF), but `vocals_mel_band_roformer.ckpt` (913 MB) does not; its only fetch path is `scripts/download_weights.ps1`, **PowerShell**. `scripts/` holds exactly one other fetch script (`download_datasets.sh`, GTSinger-only). The `Makefile` has no `fetch-models` target.
2. **"One command" is currently four.** `up`, `migrate`, and `seed` are separate `Makefile` targets and nothing chains them; a deployer following the README gets a running stack against an unmigrated database.
3. **`gpus: all` is unconditional** on `gpu-worker` (`docker-compose.yaml`). `docker compose up` hard-fails on a host without an NVIDIA GPU or the container toolkit. Risk 2 names a CPU ingest fallback as mitigation; nothing implements it and no compose profile separates GPU from CPU services.
4. **`EXPECTED_SM_ARCH` defaults to this machine's card.** `.env.example` ships `sm_86` and the `Makefile`'s `.env` target prints "edit per machine." Their GPU is almost certainly covered by the wheel (arch list is `sm_75/80/86/90/100/120`), but the assertion fails until a human edits a file. Should auto-detect from `torch.cuda.get_device_capability()`.
5. **The app starts empty.** `/data/*` is gitignored (only `data/samples/README.md` survives), so their first run has **zero songs and zero performances** — and §9's three pre-analyzed seed performances are still an open Day 1 loose end. Minute one on their hardware is the only first impression there is.
6. **No production topology exists, on any machine.** `deploy/Caddyfile` is labelled "M5: full dev routing" and its catch-all proxies `frontend:5173` (the Vite dev server, HMR websocket included); `api` runs `--reload`; source is bind-mounted into every service. The schedule's own "Dev topology is not deployed topology" paragraph requires the *built* frontend as static assets, and that artifact has never been produced.

**Two licensing questions became blocking that previously were not**, because the artifacts now have to physically travel to Smule:

- **Can the technique-head checkpoint ship in the repo?** It is trained on GTSinger (CC BY-NC-SA 4.0). `docs/licensing-audit.md` already concludes GTSinger is usable "for training and reporting results, not for shipping a derivative weight commercially," framing the head as "a research artifact … not a product dependency in itself" — but §11.2 lists six dependents and says two of the three depth bets are among them. If the weight cannot ship, comparative coaching and technique-aware recommendations degrade to their thin versions *on their deployment*. Unresolved.
- **What audio can ship as a seed catalog?** Two CC-BY tracks are documented in `data/samples/README.md`; the six tracks added for §10's 8-song pass are deliberately uncommitted. Needs a decision between shipping CC-licensed audio with derived artifacts, shipping charts without audio, or asking Smule for licensed content.

**Emails were not sent Oct 6** — held to Oct 7. The deployment question is dropped from them (nothing to ask); the two licensing questions above replace it. Status of the Oct 5 MA-1 send remains unconfirmed in this log, so the DAMP and NanoPitch-grant asks may still be unsent after two days — the two items on the project with the longest pure wall-clock latency.

**Not done tonight, explicitly:** none of the six gaps were fixed. This entry is the record of finding them, and they are scheduled into Oct 11's revised block — not silently assumed resolved.

### 12. Stale VRAM figures corrected across the planning documents (post-handoff, same evening)

Surfaced while reasoning about what hardware Smule would need to provision (§11). The planning documents carried pre-build VRAM estimates that four days of measurement have contradicted, and they were being quoted as fact. **Measured peaks across §10's 8-song validation run** (`results/sample_song_quality.json`), all on the local 8 GB RTX 3070:

| Stage | Peak VRAM | Previously documented as |
| --- | --- | --- |
| `f0` (RMVPE) | **2.0 GB** — the pipeline's largest | "RMVPE 362 MB" (a checkpoint size, not VRAM) |
| `separation` (Mel-Band RoFormer) | **1.8 GB** | "~7 GB" |
| `lyrics` (Whisper large-v3-turbo) | **1.6 GB** | "~3–5 GB" / "faster-whisper <8 GB" |
| `structure_beats` (all-in-one's HTDemucs) | **1.2 GB** | "Demucs at defaults is ~7 GB" |
| `ctc_alignment` (wav2vec2) | **0.7 GB** | not documented |
| `rms_vad`, `note_grid` | CPU-only | — |

**Why the estimates were high, so the correction is not mistaken for carelessness:** separation runs at `segment_size=128`, half audio-separator's own mdxc default of 256 (`elums/separation/engine.py`, with `override_model_segment_size: True`), chosen defensively per the Oct 3 plan §3.4 for the 8 GB card. The ~7 GB figure is plausibly accurate at default settings — **the measured number must always be quoted with its segment size**, because raising it for quality on a larger card raises the memory with it. The task also halves and re-defers on `torch.cuda.OutOfMemoryError` down to a floor of 32 (`elums/separation/task.py`), so a smaller card degrades rather than fails; that property was undocumented and is now relevant to whoever deploys this.

**Three documents corrected, one claim deliberately weakened rather than deleted:**

1. `ELUMS_BUILD_SCHEDULE.md`'s "Local-first, VM for scale" opener — replaced the estimate list with the measured table, and named all three errors (separation, the RMVPE checkpoint-size-for-VRAM conflation, and the stale "WhisperX" reference, which §Day 3 EC-1 rejected in favour of `transformers` loading the HF checkpoint directly).
2. `ELUMS_TECHNICAL_APPROACH.md` §11.6 — **the stated reason for serializing the heavyweights was wrong; the decision was right.** Memory pressure is not the constraint: any two stages are concurrently resident on 8 GB with room to spare. Serialization is re-justified on grounds that are not memory — one CUDA context with SM contention and no throughput gain from concurrency, sequential peaks not being the same quantity as concurrent residency plus fragmentation, and the OOM ladder existing because margin is not guaranteed across cards.
3. `ELUMS_TECHNICAL_APPROACH.md` §12.3 — the heading claim "16 GB cannot host both" overstated. At measured values a Q4 27B (~14 GB) plus the heaviest single audio stage (2.0 GB) is ~16 GB against a 16,311 MiB card: the ceiling, with zero margin and constant load/evict churn around a resident LLM. Weakened to "no margin for both" and the conclusion kept — hosted inference stays the default, and §12.3 already said independently that the demo must not depend on local.

**Deliberately not changed:** `elums/separation/engine.py`'s comment, which still cites the Oct 3 three-second-clip measurement and carries an open "revisit on a full-length song." The 8-song run is that revisit and its numbers hold (1798–1830 MB on real full-length tracks vs the comment's ~1.7 GB), but the owner's call was to leave code comments out of this pass. Flagged here so it is a known stale comment rather than an unnoticed one.

**Also unchanged, and worth stating:** the dated plans for Oct 3/4/5 and PROGRESS Days 1–3 all quote the old figures and were left alone, same append-only discipline as §11. They are records of what was believed on those days, not current claims.

### 13. M1 listening spot-check done — gate closed (post-handoff, same evening)

Closes §5/§8's open M1 decision and the Oct 7 plan's MA-1. The owner listened to **two** of §10's eight validated songs at `/songs/:id` on headphones (titles not recorded).

- **Lyrics: pass by ear.** Syllable highlighting tracked the sung audio on both songs. This is the first by-ear confirmation of the CTC alignment layer, and closes Day 3's open "verified by ear on one chorus" item.
- **Note grid: looks good.** Judged after the fix below; no octave flips or onset problems were called out. This is a visual-plus-audio judgment on two songs, not a measured onset-error or octave-error rate.
- **Decision: M1 is met.** No correction UI and no curated-catalog fallback (risk 4). Oct 7 builds scoring against the charts as they are.

Two fixes made during the check, both outside the ingest pipeline:

1. **Found and fixed: the note lane and the waveform were drawn at different time scales.** `SongPage.tsx` hardcoded `NoteLane` to `width={800}`, while the waveform filled its container (up to 1126px per `index.css`'s `#root`). A note's x-position could not line up with the same timestamp on the waveform, so onset accuracy could not be judged at all. The lane now takes the waveform container's measured width through a `ResizeObserver`. Oct 7's W5 replaces this lane with the Canvas pitch lane anyway.
2. **Found and fixed: frontend edits never reached the browser without a container restart.** Edits on the Windows host don't send Linux file-change events across Docker Desktop's bind mount, so Vite inside the container never saw them. `frontend/vite.config.ts` now sets `server.watch.usePolling: true` (300 ms interval). Verified: a source edit produced `hmr update` in the frontend log within about 3 s, with no restart.

**Related, added to the Oct 7 plan (W4):** the reference's continuous pitch is stored in full (the per-song f0 blob), but the chart's `Note` carries only static pitch, and there is no per-frame loudness track for the reference vocal. W4's per-note measurement functions are to be written so they work on either the user take or the reference. Friday's reference-side fields (SecondPass §4.5) then reuse the same code. The reference loudness track is W4's optional item and first on the cut list.

---

## Wednesday Oct 7 — Day 5 (capture, scoring, async seed/join → M2)

Governed by [IMPLEMENTATION_PLAN_2026-10-07.md](IMPLEMENTATION_PLAN_2026-10-07.md).

### 1. Milestone status

| Milestone | Status | Notes |
| --- | --- | --- |
| W0 — key-estimate reconciliation | **done** | `elums/ingest/notes.py` (`_resolve_key`), migration `a1b2c3d4e5f6` |
| W1 — `thred` sweep | **done, reduced scope** | One real song, not 2-3 — see §3 |
| W2 — capture pipeline | **done, deviated architecture** | `MediaRecorder`, not AudioWorklet — see §2 |
| W3 — performance model + chunked upload | **done** | `elums/models/performance.py`, `elums/api/routers/performances.py` |
| W4 — scoring job | **done** | `elums/scoring/{align,measure,loudness,score,tasks}.py` |
| W5 — pitch lane + stacked playback | **partial** | `PitchLane.tsx` built and wired into both pages; true take-vs-take *stacking* (multiple lanes overlaid) not built — see §6 |
| W6 — async seed/join | **done** | `publish-seed`, `GET /songs/{id}/seeds`, `?join=` param on `/sing` |
| W7 — M2 validation | **partial** | One real end-to-end run (not 2 songs × 3 takes) — see §4 |

Commits: `a650315` (W0) · `204a36a` (W4) · `1625cce` (W3+W6) · `8fe00d2` (W2+W5) · `0620e9e` (W1). All pushed to `origin/master`.

### 2. EC-0 — the designated day-reshaper, and the call made on it

**EC-0 was not run as a live-browser timebox** — this agent session has no interactive browser with a real microphone, so there was no way to actually verify "`addModule()` a no-op worklet, confirm it loads through Caddy at `:8080`, confirm it survives `vite preview`" per the plan's own acceptance bar. Rather than ship an AudioWorklet/`SharedArrayBuffer` pipeline that has never been exercised against a real mic or Caddy's COEP path, this took the plan's own **named fallback** verbatim (§6/EC-0's own words): *"fall back to `MediaRecorder` today, ship W3-W6 against it, and move the worklet to Thursday... That costs the zero-allocation guarantee and the live lane, not M2 — say so explicitly rather than sliding."*

`frontend/src/pages/SingPage.tsx`: `getUserMedia` with `echoCancellation/noiseSuppression/autoGainControl: false`, a `track.getSettings()` check with a banner if the browser didn't honor it (§10.2), `MediaRecorder` with `ondataavailable` at a 1s timeslice driving the chunked upload. **None of this has been exercised in a real browser with a real microphone this session** — it type-checks (`tsc -b` clean), builds (`vite build` succeeds), and the route serves through Caddy (`200` confirmed), but `getUserMedia`'s actual permission prompt, `MediaRecorder`'s actual encoding, and the live pitch lane during a real take are all **unverified**. This is the single largest unresolved item from today — see §8.

### 3. W1 — `thred` sweep, reduced scope

`scripts/thred_sweep.py` (kept deliverable, not scratch) ran RMVPE's `infer_from_audio` at `thred` 0.01/0.03/0.05 against `is-this-all-liz-james.mp3`'s vocal stem (the only real song with stems still in the dev DB this session — no `data/samples/` audio exists on disk, gitignored per `.gitignore`, and no new real audio was sourced tonight). **Only one song, not the plan's 2-3** — honestly short of scope, not silently presented as complete.

Result: `voiced_frame_ratio` vs VAD's ratio (0.792) was 0.633 / 0.623 / 0.619 at the three threds — a gap of -0.160 / -0.169 / -0.173. **The gap barely moves** (0.013 swing across a 5x threshold range) — per the plan's own instruction ("if it barely moves, stop and document the definitional difference"), this is now documented as a real measurement-definition difference (RMVPE's pitch-confidence gate vs RMS-VAD's energy gate, which also catches unvoiced consonants/breath) rather than a miscalibration, consistent with Day 4's 8-song finding (mean gap ≈ -0.11, every song negative). **Nothing consumes this number today; not tuned further**, per the plan's own instruction.

### 4. W3/W4/W6 — live end-to-end validation

A real `Performance` was pushed through the entire new pipeline against the live docker stack (not mocked): `POST /api/performances` → chunked `PUT .../chunks/0` (plus an idempotent re-PUT of index 0, plus an out-of-order index 5 correctly rejected `409`) → `POST .../complete` → `run_scoring` on the `gpu` queue → polled to `succeeded`. Take audio was `is-this-all-liz-james.mp3`'s own vocal stem fed back through the pipeline (no other real audio available this session) — since the chart's notes were derived from that exact stem, a near-zero `offset_s` (0.000) and `octave_shift_semitones` (0) is the expected and observed sanity check that alignment/octave-folding are wired correctly end-to-end.

`pct_in_tune` came back at 0.303, `score_overall` 0.338 — lower than "identical audio to the chart's own source" might suggest, but **explainable, not chased further** (one diagnosis, not a retried fix): the chart's `Note.midi` is **key-quantized** (`_quantize_to_key`), not the raw per-syllable pitch, so even the literal source recording deviates from its own chart's idealized scale-degree targets by the quantization delta plus natural pitch wobble between syllables. This is the intended measurement (compare against the *chart*, not the raw reference), not a scoring bug — flagged here rather than left looking like an unexplained number.

`publish-seed` and `GET /songs/{id}/seeds` both verified live: the performance published, appeared in the seeds list, and its audio blob became fetchable **anonymously** (`200`, no cookie) through Caddy — confirming `/internal/blob-authz`'s new seed-is-public branch (EC-5, §6 below) works, not just compiles. Full host `pytest` (88 passed, 1 skipped) and the live `test_separation.py` integration test (2 passed, full chain through `note_grid` with W0's new `build_note_grid` signature) both re-verified after every change tonight.

**Not validated live**: the two-user JOIN flow (only one test user exercised `publish-seed`; no second user actually joined via `?join=<id>` through a real browser), the three named W4 cases as REAL audio (late-start, octave-down, silence were validated as synthetic unit tests in `tests/test_scoring.py`, not as real takes through the live queue), and Range-request (`206`) behavior specifically on the three new performance blob kinds (the authz *logic* is a straightforward extension of the existing pattern, proven correct for stems/analysis/f0/chart/peaks already, but not re-clicked for performance blobs specifically).

### 5. W0 — key reconciliation

`elums/ingest/notes.py::_resolve_key`: the higher-margin side (chroma's `key_confidence` vs the note-histogram's own `key_confidence_from_notes`) wins the `key_tonic_resolved`/`key_mode_resolved` that `_quantize_to_key` now actually consumes (previously quantization always used the chroma-only key regardless of confidence). `key_confidence_low` flags when even the *winning* margin sits under 0.06 (within the plan's 0.05-0.08 range). All four raw fields (`key_tonic`/`key_mode`/`key_confidence` and `key_tonic_from_notes`/`key_mode_from_notes`/`key_confidence_from_notes`) are kept untouched for audit — migration `a1b2c3d4e5f6` adds the two missing raw columns (`key_mode_from_notes`, `key_confidence_from_notes` were previously only in the chart blob, never a DB column) plus the three new resolved/flag columns.

5 new unit tests in `tests/test_notes.py` cover: chroma wins on higher margin, notes-histogram wins on higher margin, `key_confidence_low=True` at a real documented low-margin pair (0.023, `hot-n-cold`'s actual Day 4 number), and `False` at a clear margin. **Not re-run against the 8-song table** (`scripts/validate_sample_songs.py` updated to surface the new fields, but no local sample audio exists this session to re-run it against) — the logic is unit-tested with the real documented numbers from Day 4's table, not re-verified end-to-end on all 8 songs tonight.

### 6. W5 — what shipped vs what didn't

`frontend/src/components/PitchLane.tsx`: Canvas 2D (not WebGL/SVG per §13), `devicePixelRatio` capped at 2, pre-computed arrays only (no allocation inside the draw effect). Used in three places: `SongPage.tsx` (replaces the old static SVG `NoteLane` entirely, per "replaced, not extended"), `SingPage.tsx` (live chart + playhead during a take), `PerformancePage.tsx` (per-note coloring by `pct_in_tune` against §6.2's green/yellow/red bands, plus an `f0Overlay` prop for the server-computed pitch — wired but not fed real overlay data from `PerformancePage` yet, since that needs unpacking the take's own `f0_blob_sha256` client-side, not built tonight).

**Not built**: true take-vs-take *stacking* (multiple performances of the same song rendered as overlaid/adjacent lanes for comparison) — `PerformancePage.tsx` shows one take's score and lists how many seeds exist for the song, but does not render a second take's lane alongside it. Per the plan's own cut order (W6 before W5's stacking, both before W1), this is the correct thing to have left unbuilt if something had to give — W6 (seed/join) is fully done; this is the one piece of W5 short of complete.

### 7. Deviations from the plan

1. **EC-0's AudioWorklet pipeline was not attempted — the plan's own named fallback (`MediaRecorder`) was taken directly**, not discovered after a failed timebox. See §2. This is the single biggest architectural deviation tonight, taken deliberately and documented per the plan's own instruction to "say so explicitly rather than sliding."
2. **Found and fixed during `alembic revision --autogenerate`:** the new `performances` migration's autogenerate diff also proposed dropping/recreating `song_embeddings`' unique constraint as a `unique=True` index — pre-existing drift between an earlier migration and the `SongEmbedding` model, unrelated to today's work. Left alone in the migration file (commented, not applied) per "avoid unrelated refactoring."
3. **`alembic` needed `DATABASE_URL` pointed at `127.0.0.1:5433`, not the compose-internal `db` hostname**, to run from the Windows host against the already-running stack — same class of host-vs-container networking gap as prior days' `make` PATH issue, worked around the same way (explicit env var), not fixed structurally.
4. **A second migration head existed already** (`a3e5f7c9b1d2`, pgvector) before tonight's work — found via `alembic heads` returning two results. W0's migration was rebased onto it (not onto the branch point) to keep one linear head; not investigated further whether that branch was intentional from Day 4.
5. **Running a one-off script inside `gpu-worker` needed `PYTHONPATH=/app` explicitly** (`docker compose exec -T -e PYTHONPATH=/app gpu-worker python scripts/thred_sweep.py ...`) — `python scripts/foo.py` puts the script's own directory on `sys.path[0]`, not the cwd, so the editable `elums` import (which resolves via cwd, not a real site-packages `.pth`) fails unless the script is run with `-m` from `/app` or `PYTHONPATH` is set. Not hit by any existing script because they all run from the host venv, where `elums` genuinely is on `sys.path` via the venv's own mechanism. Worth a `Makefile` target wrapping this correctly if more in-container one-off scripts are written later.

### 8. Blockers

- **None new.** MA-3/MA-5's deployment questions remain closed per Day 4 §11 (no action needed from this agent).

### 9. Loose ends carried forward

- **Everything in §2 and §4's "not validated live" lists** — chiefly: no real browser/microphone verification of `SingPage.tsx`'s capture flow at all (permissions prompt, `MediaRecorder` encoding, live pitch lane during an actual take). This is the honest headline gap: the plan's acceptance checks 2 and 4 (`getSettings()` shows constraints false or banners, a playhead-synced lane during a live take) are implemented but **not seen to work**, only typechecked/built.
- **Two-user JOIN flow** (`?join=<seed_id>` on `/sing`) is wired (the query param is read and passed as `parent_performance_id`) but never exercised with a second real user — only `publish-seed` and the seeds list were hit live.
- **W4's three named cases (late-start, octave-down, silence) are unit-tested on synthetic f0, not run as real audio through the live queue** — the one live run tonight used perfectly-aligned, non-shifted audio (the chart's own source stem), which is a different (and weaker) check than the plan's three explicit cases.
- **W5's take-vs-take stacking** is not built — see §6.
- **W0's `key_confidence_low` table is not re-verified against the 8-song set** — no local sample audio this session; logic is unit-tested against Day 4's real documented numbers instead.
- **W1's sweep used one song, not 2-3** — no second/third local sample audio this session.
- **`PerformancePage.tsx`'s `f0Overlay` prop exists on `PitchLane` but isn't fed real data yet** — would need client-side unpacking of the take's own `f0_blob_sha256` (a binary `.npz`-style blob) via `fetch` + a JS-side unpacker, not built tonight.
- **The pre-existing `song_embeddings` migration-vs-model drift** (§7 item 2) is flagged, not fixed — unrelated to today's scope.
- **No "2 real songs, 3 takes each" W7 matrix** — one real end-to-end run only, documented honestly in §4/§8 rather than presented as the full validation matrix.

### 10. Decisions the next session needs

0. **Resolved Oct 7, evening — the AudioWorklet transfer is not optional stretch scope, and it is now Thursday's first item, not a maybe.** Re-reading the brief (*"You will need to learn about WebAssembly and Web Audio to implement features such as acoustic echo cancellation. Note that these features are in scope if needed"*) makes clear that WebAssembly/Web Audio capture is itself a named brief requirement, not merely a vehicle for the AEC filter specifically. §14's descope ladder already correctly treats the adaptive echo-cancellation *algorithm* (the FDAF filter) as the first, brief-sanctioned thing to cut if Thursday runs short — a headphones-only posture is an explicitly allowed outcome. But that is a narrower cut than staying on `MediaRecorder`: the live 60fps pitch lane and the `getSettings()`-verified AEC/NS/AGC opt-out are both capture-time requirements the brief names directly, and both need the AudioWorklet + `SharedArrayBuffer` graph to exist at all, independent of whether the FDAF filter itself ships inside it. **`ELUMS_BUILD_SCHEDULE.md`'s Thursday section now lists "transfer capture off `MediaRecorder` onto a real AudioWorklet graph" as item 0**, ahead of iOS work, with the AEC filter itself remaining item 4 and the designated casualty if the day runs out of room.
1. **EC-0 needs an actual human-in-a-browser pass** before trusting any of W2/W5's capture UI — ideally on the real target hardware (headphones + real mic, per MA-3 of the Oct 7 plan), through `localhost:8080` (not Vite's own port), confirming `getUserMedia` constraints actually land and a take records audibly. This is now folded into Thursday's item 0 above rather than left open-ended.
2. **Source 1-2 more real songs** (same licensing posture as `data/samples/README.md`'s existing CC-BY tracks) to re-run `scripts/thred_sweep.py` and `scripts/validate_sample_songs.py`'s `key_confidence_low` column against more than one data point — today's numbers are real but thin.
3. **Decide whether `PerformancePage.tsx`'s stacked take-vs-take comparison is worth building before Thursday**, or whether it stays cut per the plan's own ordering (W6 > W5-stacking > W1) — W6 is done, so this is now the lowest-value remaining W5 piece, not blocking M2 either way per the plan's own gate wording ("sing against a chart, get per-note pitch scoring, and join someone else's seed").

---

## Thursday Oct 8 — Day 6 (AudioWorklet transfer, iOS ladder, WASM pitch/AEC, diagnostics, VM training)

Governed by [IMPLEMENTATION_PLAN_2026-10-08.md](IMPLEMENTATION_PLAN_2026-10-08.md).

### 1. Milestone status

| Milestone | Status | Notes |
| --- | --- | --- |
| EC-0 — AudioWorklet/Caddy/COEP smoke test | **done** | Live-verified through Caddy `:8080`, dev *and* `vite build`/`vite preview` — see §2 |
| EC-1 — Emscripten WASM build pipeline | **done** | `make nanopitch-wasm` via `emscripten/emsdk` docker image |
| EC-2 — weight export fix | **done** | `vendor/nanopitch/export_weights.py` path bug fixed; real checkpoint confirmed `gru_size=112` ≠ `nanopitch.h`'s default 96 |
| EC-3 — resampler/reblocker | **done** | `frontend/src/audio/resample.ts`, unit-tested |
| EC-4 — mel-parity test (Python vs C) | **not built** | See §7 — the one Early Check skipped this session |
| X0 — AudioWorklet capture transfer | **done** | `SingPage.tsx` rewritten; live-verified end-to-end — see §2 |
| X1 — iOS Safari support | **partial** | `ios-session.ts` + fallback ladder built and type-correct; **not verified on a real iPad** (none available) |
| X2 — NanoPitch WASM pitch worker | **done** | Live RTF confirmed (~0.03, i.e. ~30x real-time) — see §2 |
| X3 — latency calibration | **partial** | `LatencyCalibration.tsx` wired and renders live; actual MLS measurement not exercised (needs a real speaker/mic loopback, meaningless in this headless session) — "skip calibration" path used instead |
| X4 — WASM AEC | **done, reduced scope** | Time-domain NLMS, not the FDAF the plan names — see §7 |
| X5 — diagnostics screen | **done** | Live-verified real values through Caddy — see §2 |
| X6 — M3 validation | **partial** | Full record→upload→complete→scoring loop verified on desktop Chrome; **not run on a real iPad** |
| X7 — augmentation recovery + VM training launch | **done** | Running detached on `elums-vm`, survives SSH disconnect, confirmed via a second independent SSH session — see §6 |

Commits: see `git log` for this session's commits, one per milestone group, pushed to `origin`.

### 2. Live browser validation (new this session — the headline difference from Day 5)

Day 5's biggest caveat was "none of this has been exercised in a real browser with a real microphone." This session had access to the `cursor-ide-browser` MCP tool (a real Chromium tab with a mic the tool grants automatically) and used it to drive the actual UI through `http://localhost:8080`, not just `tsc -b`/`vitest`. This caught **three real bugs that static checks could not have found**, all fixed and re-verified live:

1. **`detectCaptureTier()` threw `TypeError: Illegal invocation`.** It read `AudioContext.prototype.audioWorklet` to feature-detect — `audioWorklet` is a native getter (`[SameObject] readonly attribute AudioWorklet audioWorklet`) on `BaseAudioContext.prototype`; reading it off the bare prototype object (no real instance behind it) invokes the native getter with no internal slots, and Chrome throws rather than returning `undefined`. Fixed to a property-existence check (`"audioWorklet" in AudioContext.prototype`), which never invokes anything. This completely blocked the mic-enable step — nothing past it could have been reached without this fix.
2. **The capture graph never actually ran.** `CaptureProcessor`'s two `AudioWorkletNode` outputs were never connected anywhere in the Web Audio graph (the real "outputs" are the SAB ring writes inside `process()`, not audible audio) — and Chrome does not call `process()` at all on a node with no live path to `destination`. Fixed by routing the node through a zero-gain `GainNode` → `destination`, which keeps it scheduled without being audible. Before this fix, a 17-second "recording" produced zero chunk uploads and no pitch-worker activity; after it, a 14-second take uploaded 33 real one-second PCM chunks and the pitch worker started posting a live RTF number.
3. **`nanopitch-loader.ts`'s runtime `import("/nanopitch/nanopitch.js")` 500'd in Vite's dev server** with an explicit message: public-dir files "should not be imported from source code... can only be referenced via HTML tags." This only bites in dev (the production `vite build` output never showed this, since public assets there are plain static files with no server-side import gate) — exactly the kind of gap `tsc -b`/`vitest`/`vite build` alone cannot catch, since none of them run a real dev-server request. Fixed by fetching the glue code as plain text and `import()`-ing a `blob:` URL instead (never routed through Vite's server at all), with an explicit `locateFile` override replacing the glue's own now-meaningless `import.meta.url`-relative WASM path.
4. **A fourth, related bug found the same way**: `module.HEAPU8` is `undefined` — the emcc glue's `updateMemoryViews()` only assigns `Module["HEAPF32"] = ...`; `HEAPU8`/`HEAP8`/etc. stay internal closures, never attached to the returned module object. This only surfaced on the **first real (non-warm-up) NanoPitch frame** — the first ~4 frames (40ms) take the `valid=0` early-return branch and never touch `HEAPU8` at all, so it looked fine until voicing actually started. Fixed by reading the (all-float, 4-byte-aligned) output struct through the exported `HEAPF32` view with float-index arithmetic instead of a `DataView` over `HEAPU8.buffer`.

After all four fixes, a real take through the browser tool: mic granted → `getSettings()` honored all three constraints `false` (no banner) → capture tier correctly detected `"worklet"` → latency calibration UI rendered (skipped, since MLS needs a real speaker/mic loopback this headless tab can't provide) → **14.2s recording** → `Stop` → upload → `complete` → `status=SUCCEEDED`. Server-side: `ffprobe` confirms a valid WAV, `duration=14.229333`s, matching wall clock. `elums.diagnostics.v1` (the cross-route localStorage channel feeding `/diagnostics`) showed a live `rtf: 0.0336` (NanoPitch WASM running ~30x real-time) and `erleDb` updating throughout. `/diagnostics` itself, loaded separately through Caddy: `sampleRate: 48000 Hz`, `crossOriginIsolated: true`, `SharedArrayBuffer available: true`, all real values, not placeholders.

**Debugging method, for anyone retracing this**: the accessibility-snapshot tool races the React render by design (returns before an in-flight `fetch`/effect resolves) — several "stuck on Loading…" false alarms during this session were just that race, not bugs; always re-`browser_snapshot` after a short wait before concluding something is broken. The four real bugs above were found by injecting step-level `postMessage` markers into the Worker code paths and reading them back via `window.__pitchWorkerSteps`/`Runtime.evaluate`, since Worker-context errors don't appear in the main thread's accessible state and this environment's CDP access doesn't expose per-target console/exception streams directly.

### 3. EC-1/EC-2 — WASM build and weight export, confirmed against the real checkpoint

`make nanopitch-wasm` (new Makefile target, `emscripten/emsdk:latest` docker image, no host toolchain install) rebuilt `frontend/public/nanopitch/{nanopitch.js,nanopitch.wasm}` with `ENVIRONMENT=web,worker EXPORT_ES6=1`. `export_weights.py`'s path bug (`os.path.join(__file__, '..', 'training')` — wrong for this repo's layout, where `training/` is a child dir, not upstream's sibling) fixed; re-run against the real `best_150+late_clean_112gru_model` checkpoint confirmed EC-2(b)'s named hazard is real, not hypothetical: header reads `cond_size=64, gru_size=112`, and `nanopitch.h`'s compile-time default is 96. The C engine already takes both as runtime params, so the fix was entirely on the JS loading side (`nanopitch-loader.ts` reads the real header bytes every load, never hardcodes 96) — confirmed this is also exactly where §2 bug 4 above was waiting.

### 4. X0 — architecture notes, and the chunking/ring design actually shipped

Two SAB rings per audio class were needed, not one: `ringbuf.js`'s ring is strict SPSC (one writer, one reader). The original single-cleaned-ring design (one ring feeding both `encodeWorker` and `pitchWorker`) would have had each `dequeue()` call steal samples from the other, corrupting both streams — caught before it shipped (not live-discovered) by re-reading `capture-worklet.ts`'s own header comment against what `SingPage.tsx` actually wired up. Fixed by writing the cleaned signal **twice**, to two separate SABs (`cleanedForEncodeRingSab`, `cleanedForPitchRingSab`), plus a third for the raw (pre-AEC) signal used only for the client-side ERLE estimate (`rawRingSab`, consumed solely inside `encodeWorker`, which samples raw-vs-cleaned windows once a second and posts `erleDb` back to the main thread — avoiding giving the raw ring a second reader too).

X0's named "unresolved interface decision" (chunk 0 can't carry a correct WAV header since take length is unknown at record start) resolved as the plan's own recommended option (a): headerless 16-bit PCM chunks client-side (`wav.ts`'s `floatTo16BitPCM`), server-side header prepending in `complete_performance` (`elums/ingest/wav.py`'s `build_wav_header`, byte-for-byte matching the TS version, each independently unit-tested). `elums/schemas/performances.py` gained `PerformanceComplete.sample_rate` (default 48000) since headerless PCM chunks carry no format metadata — `openapi.json` regenerated and the frontend client re-codegen'd to match.

### 5. X4 — AEC: scope reduction, as named in the plan's own contingency ladder

Shipped a single time-domain NLMS adaptive filter (1024 taps, ~21ms @ 48kHz), **not** the partitioned-block frequency-domain FDAF the plan names as the target. This is the plan's own first-sanctioned cut after X7 (§6: "cut X7, then X4") — taken because a correct FDAF is real DSP engineering weeks, not hours, while a same-tick-aligned reference (the one genuinely load-bearing part of §10.1 — not optional) plus adapt-then-freeze plus linear-subtraction-only plus no spectral floor/AGC delivers the same *behavior* the plan requires at a real but lower ERLE ceiling. Measured live ERLE during the one real take: **noisy and near/below 0dB** (ranged roughly −2 to −15dB across the session) — expected and non-alarming given the "take" had no actual singing into a real room with a real echo path (this headless browser tab's mic is not acoustically coupled to its own playback), not a signal that the filter itself is broken. The §11.4b acceptance bar (re-score the same take AEC-on vs AEC-off, compare `pct_in_tune`/loudness slopes) was **not run** this session — needs a real room/speaker take, which this session could not produce.

Also not built this pass, flagged rather than silently dropped (§10.3's fuller requirement): storing both raw and cleaned signals **server-side** so ERLE and an AEC on/off re-score comparison can be computed from the stored take after the fact. The raw signal currently only ever exists transiently in the `encodeWorker`'s in-memory ERLE sampling window, never uploaded or persisted. `Performance` has no raw-blob field today (confirmed against `elums/models/performance.py`).

### 6. X7 — augmentation recovery and the VM training launch

Confirmed again (independently of Day 1/4's prior findings) that `training/train.py` as committed on NanoPitch's `init-run` branch (`a33ca94`, pushed to `origin` of `dillonmchenry/NanoPitch-Improvements`) has real augmentation, not upstream's stub: random per-row SNR mixing via `torch.logaddexp`, `--snr-range` (default `-5 20`), `--aug-clean-prob` (`0.10`), `--aug-clean-prob-late` (`0.25`), `--aug-clean-late-frac` (`0.20`). Vendored into `vendor/nanopitch/training/train.py` for provenance (already done; re-confirmed, not re-fetched).

On `elums-vm`: cloned `NanoPitch` fresh at `init-run` into `/srv/NanoPitch` (the existing `/srv/elums` repo's own `.venv` already had `torch==2.14.1+cu130` with CUDA available — reused rather than building a second venv; added only the two missing deps, `tensorboard`/`tqdm`, via `uv pip install`). `smulelabs/NanoPitch-PreExtract` was already cached from Day 1 (`/workspace/.hf_home/hub/datasets--smulelabs--NanoPitch-PreExtract`, containing real `clean.npz`/`noise.npz`/`test.npz`) — symlinked into `/srv/NanoPitch/data`.

**Smoke test** (1 epoch, `--batch-size 8`, GPU): completed in ~53s, loss 0.37067. The per-SNR evaluation table is the actual proof augmentation is live, not a stubbed `return mel_clean`: VAD accuracy climbed monotonically from **85.6% at −5dB to 94.1% at clean** — a stub would show identical numbers across every row, since every "noisy" sample would secretly be the clean one. This is exactly the validation criterion the plan names ("the log shows a non-zero mixing gain... a stub would silently hide this").

**Full run launched**: `setsid /srv/elums/.venv/bin/python train.py --data-dir ../data --output-dir ./runs/full-run-oct8 --device cuda < /dev/null > full-run-oct8.log 2>&1 & disown` (full `init-run` defaults: 150 epochs, batch 32, `gru-size 112`, the same augmented recipe as the shipped `best_150+late_clean_112gru_model` checkpoint). Confirmed detached and surviving disconnect: a **second, independent** SSH session (not the one that launched it) found the process still running (PID 279889) and the log progressing into epoch 2 with loss decreasing (0.37155 → 0.36276). Checkpoint not yet copied off the box — nothing to copy yet this early in a 150-epoch run; **next session must copy `runs/full-run-oct8/checkpoints/best.pth` off the VM once it exists**, per the plan's own warning that the VM is an unprivileged container a recycle destroys.

### 7. Deviations from the plan

1. **EC-4 (mel-parity test, Python vs C) was not built.** Every other Early Check (EC-0 through EC-3) landed; this one slipped given the time spent live-debugging X0/X2/X4's real browser bugs (§2) instead. Nothing downstream silently assumed it passed — X2's live RTF/pitch-tracking was verified end-to-end through the real browser instead, which exercises the same C engine path, just without a direct numerical Python-vs-C parity assertion. Flagged as the clearest concrete gap for the next session, not quietly dropped.
2. **X4's FDAF → NLMS reduction** — see §5, explicitly plan-sanctioned.
3. **X3's latency calibration was wired and renders, but the actual MLS round-trip measurement was never exercised** — this headless browser tab has no real speaker-to-mic acoustic path, so a genuine `@adasp/latency-test` run would measure nothing meaningful. The "skip calibration (manual offset = 0)" path was used instead to reach recording; the calibration UI itself (idle → running → succeeded/failed state machine, 18dB reliability gate check) is implemented and type-correct but unverified against a real measurement.
4. **X1 (iOS Safari) is implemented but entirely unverified on real hardware** — no iPad available this session either, same limitation as every prior day. `detectCaptureTier()`'s fallback ladder and `ios-session.ts`'s `navigator.audioSession` sequencing both type-check and feature-detect correctly (no-op on this session's Chrome), but neither has been seen to do anything useful on WebKit.
5. **§5 acceptance check 7 (AEC on/off re-score comparison on speakers) was not run** — needs a real take with real singing into a real room, which a headless CDP-controlled tab cannot produce. The infrastructure (`computeErleDb`, `/diagnostics`'s live ERLE number) is built and confirmed to compute *something* live, just not validated against a real acoustic echo path.

### 8. Blockers

- **None new.** The VM's lack of Docker Engine (Day 4/5's finding) remains open and unrelated to tonight's work — training runs fine as a bare Python process on that same box.

### 9. Loose ends carried forward

- **EC-4's mel-parity test** — see §7.1. Next session: a small script feeding the same synthetic frame through `elums`' Python mel path and the C engine's internal mel computation (exposed or not — may need a small debug export from `nanopitch.c`), asserting numerical closeness.
- **X4's server-side raw+cleaned dual storage and the real AEC on/off re-score comparison** — see §5. Needs a `Performance` schema/model change (a raw-blob field) plus a real multi-take recording session on speakers, not just headless-browser infrastructure checks.
- **X1/iPad and X6's "on a real iPad" acceptance check** — unverified yet again. This is now the longest-standing open item across Days 3–6; needs either real device access or an explicit decision to accept it as a documented, permanent limitation for the take-home's scope.
- **X3's actual latency measurement** — needs a real speaker+mic setup (not headless), or accept "skip calibration, offset = 0" as the practical default for anyone without an acoustically-coupled room.
- **The VM training run** — needs to be checked on, and `best.pth` copied off, before the VM is recycled. Loss was still decreasing as of Epoch 2; full 150-epoch run will take considerably longer than this session's remaining time.
- **Day 5's carried items** (two-user JOIN flow, W4's three real-audio cases, W5's take-vs-take stacking, the five missing compose healthchecks, `step_index`/`step_total`, dev-DB test-user residue, blended-correlation key approach, six clean-clone gaps) — untouched this session, not in Thursday's scope per the plan.

### 10. Decisions the next session needs

1. **EC-4 should be built before trusting X2's numerical parity further** — today's validation of X2 was behavioral (a live RTF number, voiced/unvoiced gating working), not a numerical Python-vs-C assertion. Low cost, was simply not reached.
2. **Decide whether X1/iPad verification is worth chasing with real hardware**, or should be formally accepted as an out-of-scope limitation for this project's write-up — four consecutive days (3 through 6) have now shipped iOS-facing code with zero on-device verification.
3. **Someone needs to babysit the VM training run and copy the checkpoint off** before the box recycles — this is a real, time-sensitive action item, not a nice-to-have.
4. **If a real room/speaker setup becomes available**, X3's actual calibration and X4's on/off re-score comparison (§5/§7.3) are the two checks most worth spending that session time on, since both are fully built and only blocked on acoustic hardware, not code.


## Friday Oct 9 — Day 7, Session A (early checks, F0 ablation launch, F1 reference-side, F2 four new dimensions, F3 technique wiring)

Per `IMPLEMENTATION_PLAN_2026-10-09.md`'s split into three non-interleaved sessions, this entry covers **Session A only** (EC-0 through EC-4, F0, F1, F2, F3). Sessions B and C are separate, later chats.

### 1. Milestone status

| Milestone | Status | Notes |
| --- | --- | --- |
| EC-0 — launch VM technique-head training | **done** | `scripts/train_technique_head.py`, detached on `elums-vm`, survives SSH disconnect |
| EC-1 — OpenRouter compliance | **PASS** | `scripts/ec1_openrouter_check.py`: HTTP 200, `reasoning_tokens=0`, schema-conformant, provider=Phala |
| EC-2 — time-base consistency | **PASS** | `scripts/ec2_timebase_check.py`: 24521 frames @ 100Hz → 245.21s vs chart's 245.20s (gap 0.007s) |
| EC-3 — inference granularity | **done (decision only)** | Per-frame training label, pooled to chart note windows at inference — already decided in the plan text, no code needed; implemented as designed in `elums/technique/infer.py`'s `pool_to_spans` |
| EC-4 — VRAM headroom | **PASS** | `scripts/ec4_vram_check.py`: WavLM-large peak ~1.4GB standalone; confirmed again in the real pipeline at ~1.7GB (F0 frontend + Conformer head included) |
| F0 — VM: technique head + ablation table | **in progress, not finished** | 4-config ablation (`layer4`, `layer4_plus_1`, `ssl_only`, `ssl_f0`) running on `elums-vm`; `layer4` finished (macro-F1 **0.3317**, well under the plan's ≥0.70 bar); 3 configs remain — see §4 |
| F1 — reference-side measurement | **done, validated with a caveat** | `elums/scoring/reference.py` + `run_reference_measurement` task; backfilled 17 songs |
| F2 — four new dimensions | **done, wired end-to-end** | `elums/coaching/dimensions/{breath,onset,formants,dynamics}.py`; unit-tested (17 tests) + wired into both `scoring/tasks.py` (take side) and `scoring/reference.py` (reference side) — see §3 for the wiring gap found and closed this session |
| F3 — technique head wired into ingest + scoring | **done, validated on a dummy checkpoint** | `elums/technique/{model,resample,infer,tasks}.py`; real inference succeeded end-to-end after a root-cause fix (§4); real trained checkpoint not yet ready |

### 2. EC-1/EC-2/EC-4 — clean passes, no caveats

All three ran once and passed. EC-1's `response_format` JSON Schema, `reasoning:{enabled:false}`, and `provider:{require_parameters:true}` are exactly as the plan specifies; the live call confirmed `usage.completion_tokens_details.reasoning_tokens == 0` (the thing a model silently defaulting to `xhigh` reasoning would violate). EC-2 cross-checked `havent-met-you-yet.mp3`'s f0 blob length against the chart's own `duration_s`/note spans — 7ms of drift over 245s, well inside tolerance, and independently supports F1's `ref_pct_in_tune` caveat below (the timebase itself is not the problem). EC-4 was measured twice: standalone (1.39GB) and inside the real `run_technique_reference` pipeline (1.70GB, F0 frontend + Conformer head included) — both comfortably inside the one-stage-at-a-time VRAM ceiling the `gpu:separation` lock already enforces.

### 3. F2's four dimensions — built, unit-tested, and (this session) actually wired into the frozen payload

`elums/coaching/dimensions/{breath,onset,formants,dynamics}.py` were written per §6.4(a)'s table and validated two ways: 17 synthetic unit tests (`tests/test_coaching_dimensions.py`, all passing) and an eyeball check against a real separated vocal stem (`scripts/f2_eyeball_check.py`). The eyeball check found and fixed a real calibration bug: a hardcoded `floor_db=-60.0` ("true digital silence") made every onset read `"aspirate"` and over-fired breath events (159/track) on a real stem whose residual separation noise floor sits at -20 to -30dB. Fixed in two steps — `estimate_noise_floor_db()` using the track's own RMS percentile (first attempt still returned -60.0, because a long silent intro dominated the low percentile), then excluding true-silence-floor frames before taking that percentile (floor settled at -43.6dB, breath events dropped to 70, onset classification showed real variety instead of all-`"aspirate"`). Documented in the function's own docstring, not just here.

**What was missing when this session's work was first drafted, and is now fixed**: the four dimension modules were complete and tested in isolation but **not called anywhere from `elums/scoring/tasks.py` or `elums/scoring/reference.py`** — a real gap against the exit contract ("the four new dimensions" are explicitly named as part of the frozen per-note payload). Closed this session:

- `scoring/tasks.py`'s per-note loop now computes `onset_type`, `onset_rise_time_s`, `breath_ran_out_early`, `breath_decay_slope_db_per_s`, `dynamic_arc`, `formant_stability_std_hz`, `formant_std_hz_by_formant` for every note, using the note window itself as the "phrase"/"held vowel" span (the chart has no separate phrase-grouping concept — same granularity decision EC-3 already made for technique spans). A whole-take `breath_events` list (discrete event detection, not per-note) is a new top-level `analysis_payload` key, since that is the natural shape for discontinuous events.
- `scoring/reference.py`'s `measure_reference` computes the matching `ref_onset_type`, `ref_dynamic_arc`, `ref_breath_ran_out_early`, `ref_breath_decay_slope_db_per_s`, `ref_formant_stability_std_hz`, `ref_formant_std_hz_by_formant` fields, now taking `audio`/`sample_rate` params (needed for formants, which are a spectral-envelope property not recoverable from f0/RMS). `run_reference_measurement` already loaded the vocals stem's raw audio for RMS, so this was a pass-through, not new I/O.
- `scoring/tasks.py` adds `formant_std_delta_hz_by_formant` (via `compare_formant_consistency`) when both sides have formant data — DICTION's one comparative claim source, per §6.4's note that DICTION has no other feeder.
- Re-validated end-to-end against real data (not just unit tests): re-ran `run_reference_measurement` on a real song (221 notes) — `onset_type`/`dynamic_arc` show real variety (`aspirate`/`balanced`/`glottal`, `flat`/`falling`/`rising`), `formant_stability_std_hz` plausible (Hz std in the few-hundred range). Re-ran `run_scoring` on a real performance end-to-end — the full note payload (37 keys) confirmed present with every field named above.

**Caveat, honestly flagged, not swept aside**: `breath_ran_out_early` fired on 137/221 notes (62%) on the real song — plausible but almost certainly inflated, because treating each individual note (often under a second) as its own "phrase" means the function sees the natural tail-off before the *next* note's onset as "running out of breath," not a real end-of-phrase decay. A correct fix needs the chart's own phrase/line grouping (not present in the chart schema today) rather than the note grid. Flagged for Session B/C, not chased further this session — matches the plan's own validation bar for F2 ("plausible, imperfect — eyeball... not chased further" is explicitly sanctioned).

### 4. F3 — a real root-cause bug found and fixed, not blindly retried

First smoke test (dummy, randomly-initialized checkpoint, since the real one wasn't ready) failed with `CUDA driver error: device not ready`. A second attempt (after a worker restart) failed differently: `!handles_.at(i) INTERNAL ASSERT FAILED ... CUDACachingAllocator.cpp`. Per this session's own instruction ("after two unsuccessful fixes for the same failure, reassess the root cause"), stopped retrying and investigated instead of trying a third time blind.

**Root cause, confirmed**: `elums/technique/infer.py`'s `_extract_ssl_layers` ran WavLM-large in a **single forward pass over the entire song** (minutes long). WavLM's self-attention is O(n²) in sequence length; the function's own calling pattern was copied from `scripts/cache_ssl_features.py`, which only ever processes few-second GTSinger training clips — a full song is 100-200x longer and the memory/compute blew up. Confirmed directly: forcing the same code onto CPU (`CUDA_VISIBLE_DEVICES=-1`) climbed to 92%+ of the container's 15GB RAM limit and was killed before finishing, which would never happen for a few-second clip. This explains both distinct CUDA-level errors as resource exhaustion manifesting through the driver/allocator, not a bug specific to either error message.

**Fix**: chunked `_extract_ssl_layers` into bounded 20-second windows, concatenating frame-level hidden states — same per-frame output, bounded memory regardless of song length. Re-tested: `run_technique_reference` now succeeds cleanly (`vram_peak_mb=1697.8`, `pooled_count=221/221`, `duration_ms≈2800` on a warm model). Confirmed consistent across repeated runs (no flakiness) and inside the full `run_scoring` path (technique partition populated per note, matched/missed/user_added/both_absent per label).

Still using the **dummy, randomly-initialized checkpoint** (`scripts/make_dummy_technique_checkpoint.py`), since the real trained one isn't ready — so the technique *scores* in today's validation are not meaningful (e.g. the matched/ref/user scores in the end-to-end test above are near-identical only because the take audio and reference audio in that smoke test were literally the same file). What's validated is the **plumbing**: inference runs, memory stays bounded, pooling/partition/section-density all produce correctly-shaped output, and the graceful-fallback path (`TechniqueInferenceError` → warning logged, ingest/scoring still succeeds) was exercised for real by the two original CUDA failures before the fix.

**§11.2(5)'s cross-check (gate the DSP vibrato detector on learned vibrato score ≥ 0.1) is NOT yet wired** — `measure.py`'s vibrato detector only has the autocorrelation upgrade (see §5 below); the real checkpoint doesn't exist yet to gate against. Flagged for whichever session has the trained checkpoint.

### 5. Autocorrelation vibrato detector (measure.py)

Replaced the zero-crossing vibrato detector with autocorrelation: detrend → autocorrelate → normalize by lag-0 → search the 4-7Hz lag range → accept only if the peak clears a 0.4 threshold. `tests/test_scoring.py` (21 tests) still pass unchanged — this is a drop-in replacement behind the same `_detect_vibrato` signature.

### 6. F0 — VM training, launched and progressing, not finished

Confirmed the VM's prior training run (Day 6) was lost to a recycle, but critically the SSL feature cache (9.0GB) survived — this made F0 feasible within session time without re-caching from scratch for every config. Launched `scripts/train_technique_head.py --epochs 15 --batch-size 16` detached (`setsid ... & disown`), confirmed surviving an independent SSH session (PID 287046).

As of this entry: F0 caching (4827 items) finished; the 4-config ablation is running. `layer4` finished first: **macro-F1 = 0.3317**, well under the plan's ≥0.70 bar, with per-label F1 ranging from 0.76 (`mix_tech`, the dominant class) down to 0.08 (`pharyngeal_tech`). This is a real, concerning number, not yet explained — three more configs remain (`layer4_plus_1`, `ssl_only`, `ssl_f0`), and the whole point of the ablation is to see whether F0 conditioning (the `ssl_f0` config) moves `vibrato_tech`/`glissando_tech` enough to matter. **Session B must check `results/technique_head_ablation.json` once all 4 configs finish** before concluding anything about whether the real checkpoint will clear the bar — one config finishing low is not the full picture.

### 7. The frozen per-note analysis payload — Session A's exit contract

`elums/scoring/tasks.py`'s per-performance `analysis_payload`, confirmed by direct inspection of a real scored performance's blob:

**Top level**: `offset_s`, `voiced_overlap_s`, `octave_shift_semitones`, `has_reference_comparison`, `has_technique_comparison`, `technique_section_density`, `breath_events` (whole-take list, not per-note), `notes` (list, below).

**Per note** (37 keys, confirmed present on a real scored note):

- *W4's original fields*: `note_index`, `median_cents`, `pct_in_tune`, `drift_cents_per_s`, `voiced_coverage`, `mean_voicing_confidence`, `note_octave_offset`, `arrival_offset_ms`, `core_start_s`, `core_end_s`, `user_rms_db`, `user_rms_relative_db`, `vibrato_rate_hz`, `vibrato_extent_cents`, `scoop_cents`, `envelope_shape`
- *F2's four new dimensions, take side*: `onset_type`, `onset_rise_time_s`, `breath_ran_out_early`, `breath_decay_slope_db_per_s`, `dynamic_arc`, `formant_stability_std_hz`, `formant_std_hz_by_formant`
- *F1's `ref_*` fields* (present only when `has_reference_comparison`): `ref_scoop_cents`, `ref_vibrato_rate_hz`, `ref_vibrato_extent_cents`, `ref_envelope_shape`, `ref_rms_db`, `ref_rms_relative_db`, `ref_voiced_coverage`, `ref_onset_type`, `ref_dynamic_arc`, `ref_breath_ran_out_early`, `ref_breath_decay_slope_db_per_s`, `ref_formant_stability_std_hz`, `ref_formant_std_hz_by_formant`
- *Comparative fields* (present only when both sides have data): `rms_delta_db`, `formant_std_delta_hz_by_formant`
- *F3's technique partition* (present only when `has_technique_comparison`): `technique` — `{"status": "ok"|"missing_data", "per_label": {<6 labels>: {"partition": "matched"|"missed"|"user_added"|"both_absent", "user_score": float, "ref_score": float}}}`

This is the contract Session B/C build against. Any change to this field list should be a deliberate decision, not an incidental refactor.

### 8. Blockers

- **None new.** The VM continues to lack Docker Engine (pre-existing, unrelated); training runs fine as a bare process.

### 9. Loose ends carried forward

- **F0's ablation is incomplete** — 1 of 4 configs done, result (0.3317 macro-F1) is below the plan's bar. Needs the other 3 configs' results before any conclusion.
- **No real technique-head checkpoint exists yet** — F3's validation today used a dummy randomly-initialized one. The dummy checkpoint file (`models/technique/ssl_f0.pth` inside the container, from `scripts/make_dummy_technique_checkpoint.py`) must be replaced once training finishes, and `config/models.yaml` needs a registration entry (not yet added).
- **§11.2(5)'s vibrato cross-check gate is not wired** — needs the real checkpoint to be meaningful.
- **`breath_ran_out_early`'s 62% fire rate is likely inflated** — needs chart-level phrase/line grouping (not present in the chart schema) rather than treating each note as its own phrase. See §3.
- **The VM training run needs babysitting and `best.pth`/the winning config's checkpoint copied off** before any recycle, same warning as every prior VM session.
- **Day 6's carried items** (EC-4 mel-parity test, X4's server-side raw+cleaned storage, X1/iPad real-device verification, X3's real latency measurement) — untouched this session, out of Session A's scope.

### 10. Decisions the next session needs

1. **Check `results/technique_head_ablation.json` once all 4 VM configs finish.** If `ssl_f0` clears (or comes close to) the ≥0.70 bar, copy the checkpoint off the VM immediately (recycle risk), register it in `config/models.yaml`, place it at `models/technique/ssl_f0.pth`, and re-run F3's validation with real scores. If none of the 4 configs clear the bar, this needs an explicit decision: ship the head anyway with lowered expectations (documented honestly), or fall back to F3's own named degraded mode (absolute-basis cards only, no technique partition) as the shipped behavior rather than a worst-case fallback.
2. **Decide whether to wire §11.2(5)'s vibrato-score cross-check** once a real checkpoint exists — low cost, was simply blocked on checkpoint availability today.
3. **`breath_ran_out_early`'s phrase-vs-note granularity gap (§3/§9)** is worth a real fix if coaching cards built on top of it (Session B/C) would otherwise overstate how often users run out of breath.
4. **The frozen field list in §7 is the contract** — Session B/C's coaching-card/claims layer should be built against exactly this, and any addition/removal should be a recorded decision here, not silent drift.

### 11. ⚠️ Concurrent work notice — the technique head is being retrained WHILE Session B runs

**Read this before building F4/F5/F6.** Session A's thread is continuing to experiment on the technique classifier (F0's model) in parallel with Session B, rather than handing off a final checkpoint. This is deliberate: the trained head missed its own validation bar (0.423 macro-F1 against a ≥0.70 target, §6), so it is being improved rather than accepted as-is. Session B does **not** need to wait, but it does need to know what is and is not stable underneath it.

**What is stable — build freely against these.** The contract is at the **field-name** level, exactly as acceptance criterion #10 specifies ("Session B's algebra reads only fields from Session A's exit list"). None of the in-flight retraining work changes any name:

- The six labels in `elums/technique/model.py`'s `TECHNIQUE_LABELS` (`mix_tech`, `falsetto_tech`, `breathy_tech`, `pharyngeal_tech`, `vibrato_tech`, `glissando_tech`) are **fixed**. They will not be renamed or re-numbered.
- The per-note `technique` dict shape is **fixed**: `{"status": "ok"|"missing_data", "per_label": {<label>: {"partition": "matched"|"missed"|"user_added"|"both_absent", "user_score": float, "ref_score": float}}}`.
- `technique_section_density`'s shape is **fixed**: `{section_name: {label: float}}`.
- Every other field in §7's frozen list is untouched by this work (F1's `ref_*` fields and F2's four dimensions are deterministic DSP, not model outputs — retraining cannot move them at all).

**What is NOT stable — do not depend on these.** The *values* inside the technique fields will change, possibly substantially:

- Technique **scores and partitions will shift** as the checkpoint is retrained. Do not hard-code magic numbers derived from observed technique scores, and do not calibrate F5's confidence weighting against the current distribution.
- As of this writing the live checkpoint at `models/technique/ssl_f0.pth` is still the **randomly-initialized dummy** from `scripts/make_dummy_technique_checkpoint.py` (§4). Its technique scores are **meaningless noise**. The real trained checkpoint is at `models/technique/ssl_f0_trained.pth`, not yet swapped in. So any VOCALIZATION claim F4 generates today "passes" on noise, not signal — relevant to F4's "claims in ≥5 of the 7 categories" bar, since technique density is VOCALIZATION's only feeder.
- `partition_technique`'s `threshold: float = 0.5` argument may become **per-label** (threshold tuning alone recovered +0.066 macro-F1 — see §12). The returned dict's keys do not change, so F4 is unaffected, but the function signature may.

**The one real hazard, if Session B re-runs scoring.** `run_scoring` reads the song's cached reference technique blob and partitions fresh take vectors against it with **no model-version check** (`elums/scoring/tasks.py`, the `if song_analysis.technique_blob_sha256:` block). If the checkpoint changes between when a song's reference blob was computed and when a take is scored, the partition silently compares new take vectors against old reference vectors — plausible-looking, meaningless output. `model_versions["technique"]` is recorded on both sides but nothing compares them. **Mitigation: after any checkpoint swap, re-run `run_technique_reference` across all songs before trusting any partition.**

**Recommendation for Session B: work from a frozen fixture, not from live scoring.** Session B's own entry contract already says so ("Session A's frozen payload field list, and nothing else. Do not re-derive measurements here or reach back into f0 blobs"). Honoring it literally means Session B needs **no GPU and no checkpoint**, and this retraining cannot disturb it at all: F4/F5 read an analysis payload, and F6 is a remote LLM call. Save one real scored analysis blob as a test fixture and build against that — which also satisfies §5's "no live LLM call, no microphone" test requirement for free.

**Contention note:** retraining itself runs on `elums-vm`, so there is no local GPU contention. Only *validating* a new checkpoint locally touches the local GPU, and that serializes behind `lock="gpu:separation"` rather than corrupting anything.

### 12. Post-handoff: threshold tuning and span-level scoring recovered +0.066 macro-F1, with no retraining

Ran before starting any Tier 2 retraining, to separate "the model is bad" from "the metric and the operating point are wrong." New `scripts/technique_head_rescore.py`, results in `results/technique_head_rescore.json`. The harness reproduces the ablation's 0.4230 exactly at frame-level/0.5/full-val, which is how it is known to be trustworthy.

| Variant | frame-level | span-level (what actually ships) |
| --- | --- | --- |
| threshold 0.5 (baseline) | 0.4477 | 0.4363 |
| per-label tuned thresholds | **0.5176** | **0.5026** |

Measured on 18 held-out songs the thresholds were never fitted on. Note the reporting half is slightly easier than the full val split (frame @0.5 is 0.4477 there vs 0.4234 across all of val), so the honest gain attributable to tuning is the **+0.066 to +0.070 within the same reporting half**, not a naive comparison against 0.4230.

**The entire gain is in the rare labels**, confirming an imbalance-collapse diagnosis rather than a capacity problem: `pharyngeal_tech` 0.020 → 0.197 (~10×) and `vibrato_tech` 0.098 → 0.257 (~2.6×) at span level, while `mix_tech`/`falsetto_tech` barely moved. A fixed 0.5 cutoff was only ever wrong for the infrequent classes.

**Span pooling did not help — it slightly hurt** (0.5026 vs frame's 0.5176), contrary to expectation. Pooling averages probabilities across a span before thresholding, which denoises but destroys sub-span temporal structure — exactly what `vibrato_tech` depends on (frame 0.383 → span 0.257). Span-level remains the number that matters, since `pool_to_spans` is what ships; the credit for the gain belongs to thresholding, not pooling.

**Two findings that reframe the remaining gap to 0.70:**

1. **The GTSinger English corpus has only 3 singers** — `EN-Alto-1` and `EN-Alto-2` in train, `EN-Tenor-1` alone in val. The "singer-disjoint" split is therefore also voice-type- and gender-disjoint with n=1 in validation, which is close to a worst-case generalization test. It also made singer-held-out threshold tuning impossible (hence the song-disjoint fallback, 18/18 of that singer's 36 songs). This explains `pharyngeal_tech` staying at ~0.20 even tuned: the model never saw a male voice in training, and pharyngeal resonance presents very differently across voice types. **This is a data problem, not a tuning problem** — which promotes "train on all GTSinger languages" from a nice-to-have to the primary lever, since it is the only way to get more singers.
2. **`vibrato_tech`'s F1-optimal threshold is 0.98**, which is a red flag rather than a win: the model emits high vibrato probability nearly everywhere and only the extreme tail discriminates. Consistent with the F0 frontend feeding **raw Hz** into a Linear alongside roughly unit-scale SSL features (a ~1000× scale mismatch) when vibrato is inherently a *relative* cents modulation. Representing F0 as cents-relative-to-rolling-median plus deltas is the best remaining shot at vibrato.

Tuned thresholds were **deliberately not wired into `partition_technique`** — they are calibrated on a single tenor, and `vibrato_tech`'s 0.98 in particular should not ship as-is.

---

## Friday Oct 9 — Day 7, Session B (claims and voice: F4 detector algebra, F5 evidence/selection, F6 LLM card rewriting)

Per `IMPLEMENTATION_PLAN_2026-10-09.md`'s session split, this entry covers **Session B only** (F4, F5, F6). Built entirely from Session A's frozen payload field list (§7 above) — no GPU, no checkpoint, no f0 blob access, exactly per this session's own entry contract. The concurrent technique-retraining notice (§11 above) is honored by construction: nothing here reads a technique *value* as a magic number, only field names and the `>= threshold` gate §11.2(5) names.

### 1. Milestone status

| Milestone | Status | Notes |
| --- | --- | --- |
| F4 — composable detector algebra | **done** | `elums/coaching/algebra.py`; 21 detectors across all 7 categories, including both named co-occurrence composites |
| F5 — evidence, confidence, diverse selection | **done** | `elums/coaching/selection.py`; all six named behaviors implemented and tested |
| F6 — LLM card rewriting | **done, live-validated** | `elums/llm/client.py`; one real OpenRouter call confirmed `reasoning_tokens=0`, schema-conformant, both cards rewritten |

### 2. F4 — the algebra, as actually built

`elums/coaching/algebra.py` defines a `Claim` dataclass and a `REGISTRY` of `DetectorSpec`s populated by a `@register(name, category, basis, direction, scope)` decorator — the registry **is** the cross-session contract, queried by `registry_names()`. 21 detectors are registered, deliberately composed rather than a flat 1:1 port:

- **Note-scope, absolute basis** (9): `pitch_flat`, `pitch_sharp`, `pitch_in_tune`, `pitch_drifting_flat`, `timing_late`, `timing_early`, `vibrato_present`, `onset_glottal`, `onset_balanced`, `breath_ran_out_early`, `formant_instability`, `dynamic_arc_shape` — one primitive per dimension × direction, each reading only Session A's frozen fields.
- **Note-scope, reference-relative** (6): `louder_than_reference`, `quieter_than_reference`, `vibrato_missing_vs_reference`, `onset_type_mismatch`, `formant_stability_worse_than_reference`, `breath_decay_worse_than_reference` — gated purely on `ref_*` field presence, so a song with no reference pass degrades to zero comparative claims rather than erroring (tested directly).
- **Co-occurrence composites, exactly the plan's own two examples** (2): `breath_support_issue` (pitch flattening AND volume fading, via `drift_cents_per_s` AND `dynamic_arc`) and `registration_strain` (high note AND sharp AND loud — "high" computed as the take's own note-range 75th percentile, never an absolute vocal-range assumption). Both are compositions of the primitive fields already defined above, not separate hand-rolled functions.
- **Section/overall scope** (2 generator functions, not single detectors): `section_technique_drop` reads the top-level `technique_section_density` dict directly (§4.6's "kept vibrato in the chorus, dropped it in the verses," only computable there, never per-note); `breath_event` reads the top-level `breath_events` list.

**§11.2(5)'s cross-check is wired**, not left for later: `vibrato_present` gates on the note's `technique.per_label.vibrato_tech.user_score >= vibrato_technique_gate_threshold` (0.1, from `config/coaching.yaml`) when a technique partition is present, and runs ungated (the DSP measurement alone) when it isn't — the documented degraded mode, not a new one.

**New `config/coaching.yaml` + `elums/coaching/config.py`'s `CoachingConfig`**, per §3's settled decision ("thresholds are config-as-data... elums/config.py stays infrastructure-only"). Every detector threshold and every F5 selection cap lives there, not hardcoded in the detector bodies — `pitch_flat_cents_threshold`, `vibrato_band_min/max_hz`, `registration_strain_high_note_percentile`, `comparative_confidence_boost`, `max_cards_per_type/category`, etc.

**One deliberate scope note on `registration_strain`**: it needs the chart's `target_midi` per note, which is chart data, not a Session A measurement — `generate_claims(payload, cfg, chart_notes=...)` takes the chart's own note list as an optional third argument purely to supply this one field. Every other detector reads only the frozen payload.

### 3. F5 — evidence/confidence/selection, the six named behaviors

`elums/coaching/selection.py`'s `compute_confidence` and `select_cards`:

1. **Comparative confidence bounded by the weaker side's coverage** — `min(user_coverage, ref_coverage)` multiplies the evidence for every `basis="reference"` claim, using `voiced_coverage`/`ref_voiced_coverage` (Session A's frozen fields).
2. **×1.3 comparative boost** — applied on top of that bound, from `cfg.comparative_confidence_boost`, clipped at 1.0.
3. **Inverted certainty for absence claims** — `ABSENCE_CLAIM_TYPES = {"vibrato_missing_vs_reference"}` gets confidence = coverage directly (not evidence × coverage): being sure nothing is there scales with how clean the signal was, not with a "how present" score that doesn't apply.
4. **One guaranteed affirming card** — if diversity-capped selection produced zero `direction="affirming"` cards but at least one exists in the candidate pool, the single highest-confidence affirming candidate is force-included (displacing the selection's own last pick if the total cap is already hit).
5. **Per-type and per-category caps** — `max_cards_per_type=2`, `max_cards_per_category=3`, `max_cards_total=12` (config-as-data), enforced by a round-robin walk across categories so one loud category can't crowd out the other six.
6. **Chronological display sort, low-confidence suppression** — `min_confidence_to_surface=0.35` filters before ranking; final list is sorted by `start_s`, not confidence (confidence only decided which cards survived).

**Tested directly** (`tests/test_coaching_algebra.py`, 21 tests, all synthetic fixtures): comparative confidence is lower when reference coverage is poor; removing the reference side degrades to absolute-only claims without erroring; no two same-type selected cards overlap in time; a strong take and a weak take produce visibly different selected-type sets (`pitch_flat` appears only in the weak take's selection); a guaranteed affirming card is present when one exists; a near-zero-coverage note's claim is suppressed below the floor even with extreme evidence. A dedicated test (`test_claim_detail_reproduces_its_own_predicate`) spot-checks the plan's own acceptance bar directly: a claim's `detail` dict numbers are exactly what the predicate branched on.

**A realistic multi-dimension take fixture hits 6 of 7 categories** (`TestFiveOfSevenCategories`, clears the plan's ≥5 bar with one category to spare) — PITCH, RHYTHM, DICTION, BREATH, TECHNIQUE, EXPRESSION all fire; VOCALIZATION needs a technique partition or DSP vibrato to also fire, which the fixture doesn't include but a separate test (`test_vibrato_passes_gate_with_sufficient_technique_score`) confirms fires correctly when it's present.

### 4. F6 — one deliberate deviation from the plan's wording, documented not silent

`elums/llm/client.py` is `qwen/qwen3.8-27b`, the exact non-thinking sampling set (`temperature=0.7, top_p=0.80, top_k=20, presence_penalty=1.5`), `reasoning:{enabled:false}`, `provider:{require_parameters:true}`, a strict `response_format` JSON Schema, a 2-repair-attempt loop feeding the validation error back (3 attempts total), structlog logging of `model`/`duration_ms`/token counts from the first call, and a fallback to deterministic text that is asserted to **never raise** (`request_fn` swap point for tests, no live call in the suite).

**Deviation**: built on plain `httpx` + Pydantic v2 directly, not the `instructor` package the plan names. Reasoning: this project's own dependency discipline (every pin in `pyproject.toml` is individually justified in a comment, torch-free api/worker images, `audio-separator[cpu]` over the GPU extra specifically to avoid a second unused CUDA runtime) treats "add a library" as a decision to justify, and `instructor` pulls in `openai`+`aiohttp`+friends (29 packages in a dry-run) for what the repair loop needed in ~30 lines here, already matching `scripts/ec1_openrouter_check.py`'s own existing plain-`httpx` precedent. The resulting behavior — strict schema, repair loop, structlog, graceful fallback — is unchanged; only the implementation vehicle differs. Flagged here explicitly per this session's own instruction not to let a deviation go unrecorded.

**Live-validated** (`scripts/f6_card_rewrite_check.py`, run for real against OpenRouter, same pattern as EC-1's own standalone script, not pytest): `reasoning_tokens=0`, both test cards came back rewritten (not the deterministic fallback), `duration_ms≈1800` for a 2-card batch. The unset-key path was also run for real (not just mocked): clears to the deterministic text with a `llm.card_rewrite.no_key` log line and no exception.

**Mocked test suite** (`tests/test_llm_client.py`, 7 tests, no live call): unset key never calls the transport; a valid response overrides deterministic text; one malformed response followed by a valid repair recovers and the repair message carries the validation error back; three consecutive malformed responses exhaust all repair attempts and fall back cleanly; a missing required field (schema violation, not just invalid JSON) also triggers the repair path; a transport-level exception (`httpx.ConnectError`) breaks immediately without burning repair attempts on a problem repair can't fix; an empty card batch never calls the transport at all.

**Cut from scope, exactly as the plan's §6 reduction 3 names**: no hypothesis-proposal call site (§6.4c), no section narratives, no performance summary. One call site only — card summary rewriting.

### 5. The published exit contract — registry + card schema

`elums/coaching/cards.py`'s `build_cards(payload, chart_notes, cfg, use_llm)` is the one function that composes F4 → F5 → F6 and is this session's actual deliverable per the plan's own framing ("the claim-type registry... and the selected-card JSON schema... consumed by Session C and by Saturday's challenge generation"):

- **Registry**: `elums.coaching.algebra.registry_names()` — 21 stable names, listed in §2 above. **Do not rename any of these** (§6.6's own warning, repeated here deliberately).
- **Card schema**: `CardPublic(card_id, type, category, scope, basis, direction, start_s, end_s, confidence, text, detail, note_index, section)` — Session C's frontend reads this as data and must not reimplement any predicate behind it.
- Deterministic sentence templates (`_TEMPLATES`, one per registered type) are both the LLM-unavailable fallback text AND what the LLM is handed to rewrite — the model's job stays "rewrite," never "invent," by construction (it never sees bare numbers without a human-readable starting sentence).
- `use_llm=False` skips F6 entirely; tested directly (`test_no_llm_mode_never_imports_or_calls_rewrite`) to confirm the deterministic-only path truly never touches the LLM client.

### 6. Validation summary

- `tests/test_coaching_algebra.py`: 21/21 passed (F4 primitives, co-occurrence composites, registry, F5 confidence/selection behaviors, the ≥5-category bar).
- `tests/test_llm_client.py`: 7/7 passed (repair loop, fallback, transport-error handling — no live call).
- `tests/test_coaching_cards.py`: 3/3 passed (registry round-trip, deterministic text grounding, `use_llm=False` isolation).
- `scripts/f6_card_rewrite_check.py`: **PASS**, live — `reasoning_tokens=0`, both cards rewritten, confirmed against the real funded key (MA-2 already done, carried from Session A's EC-1 pass).
- Full deterministic suite re-run after this session's changes (`tests/test_coaching_dimensions.py`, `test_coaching_algebra.py`, `test_llm_client.py`, `test_coaching_cards.py`, `test_lyrics.py`, `test_notes.py`, `test_scoring.py`, `test_wav.py`): **102/102 passed**, confirmed under a clean `uv sync --group dev` (not just the ambient dev environment) — this caught three genuinely missing explicit pins (`pyyaml`, `pydantic`, `structlog`, `pydantic-settings`) that a locally-installed-but-unpinned package would have hidden; all four now pinned in `pyproject.toml`'s `core`/`dev` groups with the same per-need comment discipline the rest of the file uses.
- `make up`/live-stack tests (`test_songs.py`, `test_separation.py`) were deliberately **not** run this session — they hit the running compose stack over HTTP, which is Session C/the final acceptance pass's job, not Session B's (no GPU, no server, per this session's own entry contract).

### 7. Blockers

- **None.** Everything in scope landed and validated.

### 8. Loose ends carried forward

- **`vibrato_present`'s technique gate uses whatever checkpoint is live at scoring time** — per Session A's §11 concurrent-work notice, today's checkpoint is still the random-weight dummy, so any VOCALIZATION claim gated on it in a *real* scored performance is gated on noise until the real checkpoint is swapped in and `run_technique_reference` is re-run across all songs (Session A's own mitigation, not repeated here). The field-level contract this session built against is unaffected.
- **No API route serves cards yet.** `build_cards` is a pure function over a payload dict; wiring a `GET /api/performances/{id}/cards` endpoint (or equivalent) that loads the analysis blob, the song's chart, and calls `build_cards` is Session C's job per its own entry contract ("the frontend reads cards as data").
- **`registration_strain`'s percentile-based "high note" threshold** is computed per-performance from that take's own note range. On a song with a narrow range (few genuinely "high" notes by its own standard), this could under- or over-fire relative to what a vocal coach would call "high" in an absolute sense. Not chased further — matches F2's own "plausible, imperfect, not chased further" precedent from Session A.
- **F6's streaming requirement ("stream the copy," §12.2) is not implemented** — `rewrite_cards` is a single blocking call per batch. **Resolved by the owner, see §9.1**: stays blocking, computed behind the recording-to-results "processing" screen, deliberately no streaming variant.
- **Section-scope and overall-scope claims (`section_technique_drop`, `breath_event`) have `start_s=end_s=0.0` or the event's own span respectively** — `section_technique_drop` has no single timestamp by nature (it's a whole-section comparison). **Resolved by the owner, see §9.2**: Session C seeks to the section's own start time from `chart["sections"]` for now; a separate "section stories" surface (not timestamped cards) is the longer-term fix the owner is weighing.

### 9. Decisions Session C needs — resolved by the owner before Session C starts

1. **Streaming — decided: no, ship blocking.** The owner's call: there is already expected to be a "processing" screen after the user finishes recording, so the whole card set can be computed behind that screen rather than the reveal UI itself. Cards **popping in one by one as they stream would look worse visually** than a clean reveal once everything is ready. `rewrite_cards`'s current blocking-call-per-batch behavior ships as-is; no streaming variant needed. (The ~1.8s/batch measured live today is well inside what a processing screen can absorb.)
2. **Section-scope card seek target — decided: seek to the section's own start time for now.** `section_technique_drop` cards should resolve their seek target from the chart's own `sections[]` boundaries (`chart["sections"]`), same convention as every other section-scoped reference in the project. **Noted for later**: the owner may introduce a separate "section stories" surface distinct from timestamped cards specifically so trend-level, whole-section observations (like this one) don't need to be forced into a single-timestamp card model at all. Not today's work — ship the section-start seek convention now, revisit if/when that surface exists.
3. **`GET` endpoint for cards — decided: compute on demand.** Given the project's large API-credit budget (§12.2/§12.3), the owner prefers recompute-per-request over caching at scoring time. This also means `coaching.yaml` threshold changes and detector-registry changes take effect immediately on every existing performance's card view, with no backfill job ever needed — a real simplicity win worth noting, not just "the simpler option." Session C should wire `GET /api/performances/{id}/cards` (or equivalent) to call `build_cards` fresh every time; no persistence of the card set itself.
4. **Confirm `vibrato_present`'s gate behavior once Session A's real checkpoint lands** — no code change needed (the gate already reads `technique.per_label.vibrato_tech.user_score` by field name, which is stable per Session A's §11), but the *rate* at which VOCALIZATION cards fire will shift from "gated on noise" to "gated on signal," worth a sanity re-check against a real take once that checkpoint is live. Still open — not an owner decision, an engineering follow-up.

---

## Friday Oct 9 — Day 7, Session C (surface: F7 card UI, F8 progress tracking, F9 M4 validation)

Per `IMPLEMENTATION_PLAN_2026-10-09.md`'s session split, this entry covers **Session C only** (F7, F8, F9). Built against Session B's registry names and card JSON schema exactly as handed off above — the frontend reads cards as data and does not reimplement any predicate.

### 1. Milestone status

| Milestone | Status | Notes |
| --- | --- | --- |
| F7 — card UI, click-to-seek | **done, live-validated** | `frontend/src/pages/PerformancePage.tsx`; `GET /api/performances/{id}/cards`; found and fixed a real production bug (§3) |
| F8 — progress tracking | **done, live-validated** | `elums/progress/metrics.py` + `service.py`; `GET /api/songs/{id}/progress`; `frontend/src/pages/ProgressPage.tsx`; `elums/seed.py` extended |
| F9 — M4 validation | **done, with one honest caveat** | full loop exercised through Caddy at `:8080`; see §6 for the one deviation from the plan's literal wording |

### 2. F7 — card UI with click-to-seek, as built

Owner decisions from Session B's §9 (above) honored exactly as recorded: no streaming (cards computed behind the existing "processing" screen), section-scope cards seek to their chart section's own `start_s`, and the cards endpoint recomputes `build_cards()` fresh on every request with no caching.

- **`elums/schemas/cards.py`** — `CardSchema`, mirroring `CardPublic` for FastAPI's `response_model`/OpenAPI codegen.
- **`elums/coaching/cards.py`** — added `apply_section_seek_times(cards, sections)`, a pure function resolving a section-scope card's `start_s`/`end_s` to its matching chart section's own `start_s` (matched by label), leaving every other card untouched.
- **`GET /api/performances/{id}/cards`** (`elums/api/routers/performances.py`) — owner-or-public visibility, same rule as `GET /api/performances/{id}`; returns `[]` (not an error) before scoring finishes; recomputes `build_cards()` + `apply_section_seek_times()` fresh every call, exactly per owner decision #3.
- **`frontend/src/audio/npz.ts`** — a hand-rolled, dependency-free `.npz` reader (no JS library parses `np.savez`'s ZIP64-extra-record quirk cheaply) so `PerformancePage.tsx` can finally feed `PitchLane.tsx`'s `f0Overlay` prop from the take's `f0_blob_sha256` — this was defined on the component but unfed since Day 5. Tested against a real `pack_f0_blob()`-generated fixture (`frontend/src/audio/testdata/f0_sample.npz`), not synthetic bytes — 4/4 tests passing.
- **`PerformancePage.tsx`** rewritten: cards render grouped by the 7 VocalCoachBench categories as clickable buttons; clicking one seeks both the `<audio>` element and `PitchLane`'s `currentTimeS` to the card's `start_s` and plays.

### 3. Found and fixed: a real production bug in `_formant_stability_worse`

`elums/coaching/algebra.py` crashed with `TypeError: '>' not supported between instances of 'NoneType' and 'float'` on a real scored take. Root cause: `compare_formant_consistency()` (`elums/coaching/dimensions/formants.py`) fills `None` per-formant when either side lacks that formant; the existing `if not deltas: return None` guard only catches an empty/falsy list, not a non-empty one containing `None` entries, so `max(deltas)` tried to compare `None` against a float. Fixed by filtering `None` out before `max()`. Fixed on the first attempt — the "reassess after two failures" instruction never needed to trigger here, but is recorded as honored regardless.

### 4. F8 — progress tracking, as built

Per §6.5, in priority order: per-song z-score once a song clears ~20 performances (`metrics.PER_SONG_ZSCORE_MIN_N`), Elo-style online difficulty as the shrinkage fallback below that (the *operating* path for every song in this project's own data — no song anywhere clears 20 performances today, so the UI copy says "online Elo-style estimate" rather than silently implying a z-score); rolling **median** of the last 5, not the mean; a displayed IQR band; a three-way verdict **gated at ≥8 performances** with explicit "sing N more" copy below that; per-dimension trends, not one composite; **personal best per song as the hero metric**; bands widen when `device_label` is inconsistent across recent sessions.

- **`elums/progress/metrics.py`** — pure, DB-free math: `elo_expected`/`elo_update`/`replay_elo`, `per_song_zscore` (gated, returns `None` not zeros below the threshold), `rolling_median`, `iqr_band`, `three_way_verdict` (gated, returns a `VerdictResult` with `performances_needed`), `personal_best`, `device_label_band_widen`. Same "deterministic layers only" discipline as `elums/coaching/dimensions/*` — no DB import, torch-free, directly unit-testable.
- **`elums/progress/service.py`** — the DB-aware half, scoped to one user's performances of **one song** (per §6.5's own "personal best **on this song**" framing — a cross-song dashboard aggregating a user's Elo trajectory across every song is a credible later addition, **not built here**, flagged rather than silently out of scope). Computed fresh on every request — same "recompute, don't cache" precedent Session B's §9.3 set for cards, so a `metrics.py` constant change takes effect immediately with no backfill and no persisted rating column.
- **`GET /api/songs/{id}/progress`** (`elums/api/routers/songs.py`) — hard-requires a session (`get_current_user`); unlike `get_song_bundle`'s owner-or-public rule, there is no "public" reading of someone else's progress.
- **`frontend/src/pages/ProgressPage.tsx`** — hero personal-best metric, gated verdict with "sing N more" copy, per-dimension trend list, device-change band-widen notice. Routed at `/songs/:id/progress`, linked from `SongPage.tsx`.
- **`elums/seed.py`** extended — `dana` now seeds 10 `SUCCEEDED` performances against one dummy "Progress Demo Song" (no real audio/f0/analysis blobs — those three columns stay NULL, same as any performance that never finished scoring), scores deliberately flat for the first `VERDICT_GATE_N` takes then improving after, so the demo account visibly crosses from "insufficient_data" to "improving" rather than sitting at one state. **The gate itself was not lowered** — `VERDICT_GATE_N` stays 8, exactly per the plan's explicit instruction. Idempotent (checked by re-running `make seed` twice against the live stack; performance count stayed at 10).
- A real tie-breaking bug was caught before it shipped, not after: Postgres's `now()` returns the **same** value for every statement inside one transaction, so `elums/seed.py`'s batch-inserted demo rows all share one `created_at` — `service.py`'s ordering was changed to `ORDER BY created_at, id` (UUIDv7 is time-ordered by construction) so "chronological order" assumptions never silently scramble for any batch-seeded or same-millisecond-inserted performance set, not just this one.

**Unit tests**: `tests/test_progress_metrics.py`, 24/24 passing — covers Elo direction (a song a user keeps dominating gets its difficulty estimate *lowered*, the classic Elo co-update, not raised — this is the one place my own first draft of the test suite had the direction backwards and was corrected, not the implementation), the z-score gate, rolling-median/IQR edge cases (one disaster take doesn't move the median much), the three-way verdict's gate and both trend directions, personal best, and device-label band-widening. `frontend/src/pages/ProgressPage.test.tsx`, 3/3 passing (gated copy, cleared verdict + hero metric, zero-performance empty state).

### 5. F8 live validation against the real seeded account

Through Caddy at `:8080`, logged in as `dana@elums.demo`: `GET /api/songs/{demo_song_id}/progress` returned `performance_count: 10`, `verdict: "improving"`, `personal_best_score_overall: 0.82`, all three per-dimension trends present with IQR bands, `device_label_consistent: true` — matching the seeded data's own deliberately-improving tail exactly. A second user with zero performances on the same song returned `performance_count: 0, overall: null` with no error. Both confirmed in the browser (`ProgressPage.tsx` rendering correctly) and via `curl` directly against the API. Screenshots taken during this session (not committed, available on request): the 10-performance "Improving" state and the gated "sing N more" state (§6 below).

### 6. F9 — M4 validation, full loop, with one honest caveat on "real mic"

**What was run, in order, through Caddy at `:8080`:** logged in as `dana@elums.demo` → `/songs/{song}/sing` → granted microphone access → "Continue to latency calibration" → "Skip calibration" → **recorded a real take through the actual capture UI** (`MediaRecorder`/AudioWorklet path, ~19s) → stopped → chunked upload completed → `run_scoring` ran as a real Procrastinate job on the real `gpu-worker` (not a manual script invocation) → navigated to `/performances/{id}` → **12 coaching cards rendered across 5 of 7 categories** (PITCH, RHYTHM, DICTION, BREATH, TECHNIQUE, EXPRESSION — EXPRESSION's dB-based cards included) → clicked a RHYTHM card and confirmed via CDP `Runtime.evaluate` that the `<audio>` element's `currentTime` actually seeked to that card's `start_s` (18.33s) and resumed playing from there → navigated to `/songs/{song}/progress` for the same (now 2-performance) song and got the correctly-gated `"insufficient_data"` / "sing 6 more" response.

**Per-stage timing/VRAM, from the real `gpu-worker` log line** (`scoring.succeeded`): `duration_ms=1902`, `vram_peak_mb=543.7`. Technique comparison was attempted and **gracefully degraded**: `scoring.technique_unavailable reason='technique inference failed: The size of tensor a (2051) must match the size of tensor b (2050) at non-singleton dimension 2'` — this is the **same pre-existing, out-of-scope bug** flagged live during F7 testing (§ below), confirmed happening again on a genuinely different take, and confirmed **not** blocking the rest of the pipeline: scoring still succeeded, cards still built from the absolute-basis + reference-stem-comparative detectors that don't need a technique partition (F3's own documented fallback mode, "ship absolute-basis cards plus reference-f0 comparative claims... loses the technique partition, not the coaching engine").

**The one honest deviation from MA-3's literal wording:** MA-3 asks for "2–3 real sung takes with a real mic... headphones on." This agent has no physical microphone or headphones — the browser environment available to it exposes a **virtual/fake audio input device** (confirmed: `getUserMedia` succeeded instantly with no permission prompt, consistent with a test harness flag rather than a real device), so the "take" above exercised the entire real capture→upload→score→technique→cards→seek→progress pipeline through the real UI and the real GPU worker, but the audio itself was not a human singing. This is **not** the same gap as Day 5/6's prior surrogates (a stem fed back, or a silent headless tab) — this one went through the actual `MediaRecorder`/AudioWorklet capture code path for the first time, which those two did not — but it still falls short of MA-3's own stated reason for existing ("neither has breath events, onset variety, or dynamic arcs, so coaching cards cannot be validated without this"). The resulting cards above *did* fire across 5 categories including breath/onset/dynamics-driven ones, which is a reasonable proxy signal that the plumbing is sound, but it is not a substitute for a human actually judging whether the generated coaching text matches what a real take sounds like. **This needs a human with a real microphone to do once, for real** — recommended as the very first thing before relying on this for a demo or submission.

### 7. Validation summary

- `uv run pytest tests/` — **167 passed, 1 skipped** (up from Session B's 102; includes 24 new `test_progress_metrics.py`, 3 new `TestSectionSeekTimes` cases in `test_coaching_cards.py`, and everything from Sessions A/B unchanged).
- `frontend`: `tsc -b` clean; `vite build` succeeds; `vitest run` — **26/26 passed across 9 files** (up from 23/8; adds `npz.test.ts` and `ProgressPage.test.tsx`).
- Live, through the real Docker Compose stack and Caddy at `:8080`: F7's cards endpoint (with and without `use_llm`), F8's progress endpoint (gated and cleared states, for both the seeded demo account and the real-take account), and F9's full capture-to-progress loop, all described above with screenshots taken during the session.
- `make openapi` + `npm run codegen` re-run after the new endpoints landed; `frontend/openapi.json` and `frontend/src/client/*` are current.

### 8. Blockers

- **None that block landing this session's own scope.** The one real gap (§6's "no literal human mic take yet") blocks full confidence in M4's coaching-card *quality*, not M4's technical completeness — the loop runs correctly end to end regardless of what's feeding the microphone.

### 9. Loose ends carried forward

- **MA-3's literal "real mic, headphones on" requirement is still open** — see §6. Needs a human to record 2–3 real takes through `/sing` at `:8080` and read the resulting coaching cards for plausibility; this agent cannot do that itself.
- **The pre-existing technique-inference tensor-size bug** (`The size of tensor a (2051) must match the size of tensor b (2050)`) reproduced again on a second, genuinely different take. Confirmed non-blocking (graceful fallback works as designed) but still unfixed and still out of this session's scope — flagged again rather than silently re-encountered.
- **A cross-song progress dashboard** (aggregating a user's Elo skill trajectory across every song, rather than one song at a time) is a credible later addition per §6.5's own framing, not built this session — `elums/progress/service.py`'s module docstring flags it explicitly.
- **No git commits made this session.** Per the plan's own instruction ("commit per milestone with its name, push to GitHub"), F7/F8/F9 should each get their own commit before this is considered fully closed out — not done as part of this handoff; left for the owner or a follow-up action.
- **Session B's own loose ends not re-touched here**: the dummy technique checkpoint is still live (Session A's retraining work was happening in parallel with this session and its outcome was not re-checked), `vibrato_present`'s gate is still gated on noise rather than signal until that lands.

### 10. ⚠️ For whoever plans Saturday Oct 10 (M5) — checkpoint-swap caveat, read before scheduling duet/challenge work

**Saturday's M5 scope (duet + challenges, `ELUMS_BUILD_SCHEDULE.md`'s Sat Oct 10 row) is architecturally decoupled from the technique-head retraining and can run in parallel with it.** Neither track touches `elums/technique/*` directly: the duet session's WebSocket rooms/clock-sync/alignment/mixing work sits on top of the existing per-user `run_scoring` task (reused unchanged, same precedent `elums/seed.py`'s own docstring names for SOLO/SEED/JOIN), and the challenges track validates LLM-proposed detector names against `elums.coaching.algebra.registry_names()` — 21 names, frozen since Session B regardless of checkpoint quality (Session A's §11 concurrent-work notice already drew this exact line: field names are stable, technique *values* are not).

**The one real hazard, inherited from Session A's §11 and still unresolved:** `run_scoring` has **no model-version check** between a song's cached reference technique blob (`SongAnalysis.technique_blob_sha256`) and whichever checkpoint is actually live at scoring time. If a new/retrained checkpoint gets swapped in while Saturday's duet work is actively scoring real takes against songs whose reference blob was computed under the *old* checkpoint, the partition silently compares new take vectors against stale reference vectors — plausible-looking, meaningless `TECHNIQUE`/VOCALIZATION cards and duet per-singer technique comparisons, with no error raised. `model_versions["technique"]` is recorded on both sides but nothing compares them.

**Mitigation (already documented, repeating here only because Saturday is the first session where this could actually bite in practice via live duet scoring):** after any checkpoint swap, re-run `run_technique_reference` across every song before trusting any technique partition again. If retraining and duet work are genuinely concurrent, consider holding checkpoint swaps for a quiet point rather than mid-session, or treat Saturday's technique-partition output as provisional until a known-good re-reference pass has run.

**Not yet done, whenever a real checkpoint does land** (not Saturday-blocking, just the standing follow-up): register it in `config/models.yaml` (currently has no `technique` entry) and place it at `models/technique/ssl_f0.pth`, and wire §11.2(5)'s vibrato cross-check gate (`measure.py`'s DSP vibrato detector gated on learned score ≥ 0.1 — unwired today because there was nothing real to gate against).
