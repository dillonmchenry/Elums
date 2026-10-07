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
