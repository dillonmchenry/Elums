# Elums — Build Schedule

**Window:** Sat Oct 3 → Mon Oct 12, 2026. **62 working hours across 10 days.**
Companion to [ELUMS_TECHNICAL_APPROACH.md](ELUMS_TECHNICAL_APPROACH.md); section references below point into it.

> Hours assume heavy LLM collaboration, not solo typing. Every day ends with something demonstrable — that is the scheduling invariant, because it is the only way to know whether you are actually on track.

---

## Overview

| Day | Hrs | Where | Focus | Milestone at end of day | Done |
| --- | --- | --- | --- | --- | --- |
| Sat Oct 3 | 8 | Local + 30min VM | Foundation: scaffold, auth, separation, VM smoke test | `make up` green; log in; MP3 → stems | [ ] |
| Sun Oct 4 | 4 | Local | Ingest A: structure, beats, key, vocal-activity segments | Song row with sections + beats + key | [ ] |
| Mon Oct 5 | 4 | Local | **Send Smule emails**, then Ingest B: lyrics + alignment | Word- and syllable-level timings | [ ] |
| Tue Oct 6 | 4 | Local, VM overnight | Ingest C: F0, note grid, chart writer | **M1 — upload any MP3, get a playable chart** | [ ] |
| Wed Oct 7 | 8 | Local | Capture, scoring, async seed/join | **M2 — sing and get scored; join a seed** | [ ] |
| Thu Oct 8 | 8 | Local, VM overnight | Mobile + real-time audio (iOS, NanoPitch WASM, AEC) | **M3 — works on a real iPhone** | [ ] |
| Fri Oct 9 | 8 | Local, VM training | Coaching engine (6h) + progress tracking (2h) | **M4 — coaching cards with click-to-hear** | [ ] |
| Sat Oct 10 | 8 | Local | Live duet (6h) + challenges (2h) | **M5 — two-device duet artifact** | [ ] |
| Sun Oct 11 | 8 | Local | Recommendations + sharing (5h), **deliverable hardening (1.5h)**, buffer + prep (1.5h) | **M6 — the loop closes** | [ ] |
| Mon Oct 12 | 2 | Local + clean-room check | Finalize submission | Shipped | [ ] |

**Three structural decisions behind this shape.** The 4-hour weekday blocks get ingest, because ingest decomposes cleanly into independent stages that each fit a half-day and do not require long debugging runs. The three days off work get the three things that *do* need uninterrupted blocks: mobile audio, the coaching engine, and the duet session. And Depth Bet 3 is split across the back three days as a second track rather than given its own day, which is what buys the Sunday buffer.

---

## Local-first, VM for scale

**Build locally. Bring the VM in for the three things it is uniquely good at.** The local GPU has far more headroom than this document originally estimated. Measured peaks across the 8-song validation run (`results/sample_song_quality.json`), all on the 8 GB RTX 3070:

| Stage | Peak VRAM |
| --- | --- |
| `f0` (RMVPE) — **the pipeline's largest** | 2.0 GB |
| `separation` (Mel-Band RoFormer) | 1.8 GB |
| `lyrics` (Whisper large-v3-turbo) | 1.6 GB |
| `structure_beats` (all-in-one's own HTDemucs) | 1.2 GB |
| `ctc_alignment` (wav2vec2) | 0.7 GB |
| `rms_vad`, `note_grid` | CPU-only |

Three corrections to what this line used to say. **Separation was estimated at ~7 GB and measures 1.8 GB** — because the pipeline runs `segment_size=128`, half audio-separator's own mdxc default of 256 (`elums/separation/engine.py`), and halves again on OOM down to a floor of 32, so a smaller card degrades rather than fails. **RMVPE was listed as "362 MB,"** which is its checkpoint size, not its VRAM footprint; it is in fact the heaviest stage. And **WhisperX is not used at all** — `transformers` loads the HF checkpoint directly (PROGRESS Day 3 EC-1).

The pipeline still serializes the heavyweights under Procrastinate's `lock="gpu:separation"` — **not** because memory cannot hold two at once, which it comfortably can, but because there is one CUDA context and concurrent jobs contend for the same SMs with no throughput gain (§11.6).

What the VM is actually for:

| VM's unique value | First needed |
| --- | --- |
| The 1.5 TB SSD — GTSinger at 54 GB, cached SSL features at ~30 GB per layer | Tue night |
| Unattended overnight runs that do not tie up the dev machine | Tue night |
| Bulk catalog ingest while you work on something else | Sat / Sun |

> **Corrected Oct 6, evening — the VM is not the deployment target, and never was.** The brief states the delivery mode plainly: *"you will deliver the source code to us, and we will deploy the application internally."* What ships is a repository, not a running host. The VM is training and bulk-compute capacity only; the deployment row that used to sit in this table was a misreading. See [PROGRESS.md](PROGRESS.md) Day 4 §11.

Walking the schedule, you are genuinely unblocked until **Tuesday night**, and with deployment off the VM there is no hard VM requirement anywhere on this schedule. Wednesday and Thursday are local by physics: `getUserMedia`, AudioWorklet, the WASM AEC, MLS calibration, and iOS testing all need a real browser on a real device with a real microphone, which a headless box cannot provide at any point in the project.

**Dev topology is not deployed topology.** The deployed topology is whatever Smule stands up from the repo — Caddy, API, both workers, Postgres, Valkey, blobs, every model, and the *built* frontend as static assets, from one command on their hardware. Neither your local machine nor the VM ships anything: **what ships is the clean clone.** That makes one-command bootstrap the deliverable itself rather than a nicety, and it is the single thing most worth protecting from here on. The browser keeps a real compute tier by design, not by limitation: NanoPitch WASM for live pitch, the known-reference AEC in an AudioWorklet, the Canvas pitch lane, local full-quality recording, and latency calibration.

### Portability disciplines — hold these from the first commit

These were written for the transition to the VM; they matter more now that the real target is **Smule's own Linux host, running the repo unattended**. Every one of them is a thing that works on Windows and fails on Linux, with nobody there to debug it. Budget one hour on Saturday.

- [ ] **Dockerize from commit one**, and exercise the containers at least once a day even if you normally run with `uv run` for speed. The failure mode is "works in my venv, no container exists"
- [ ] **No absolute Windows paths, ever.** `pathlib` everywhere, roots from env vars. This is the most common breakage by a wide margin
- [ ] **Case-sensitivity discipline.** Windows is case-insensitive, Linux is not — `import Foo` resolving to `foo.py` works locally and dies on any Linux host, including Smule's
- [ ] **`.gitattributes` with `* text=auto eol=lf`**, or CRLF line endings turn shell scripts into `bad interpreter` errors
- [ ] **Everything machine-specific in `.env`** — device, VRAM budget, segment size, blob root, model cache. The VM gets a different `.env` and nothing else changes
- [ ] **Blob store behind the `BlobStore` Protocol** with its root from config (already in the plan, §4)
- [ ] **One CUDA wheel for both machines.** Local is Ampere or Ada (sm_86/sm_89), the VM is Blackwell (sm_120); a cu130 wheel should cover all three. Verify with `torch.cuda.get_arch_list()` on each

### Working on the VM

It is a Linux computer you drive through a terminal — nothing more exotic. Every bit of Docker knowledge transfers unchanged, which is the point: the scary part of remote machines is environment drift, and containers eliminate it.

- **Cursor Remote-SSH** gives you a full IDE on the box: file tree, editor, terminal, agent. Test it Saturday rather than discovering a problem Tuesday night
- **Port forwarding covers most graphical needs**, since backend tooling is web-based anyway — TablePlus on 5432, Grafana on 3000, the app on 8080, Jupyter on 8888
- **`http://localhost:<port>` through the tunnel is a secure context**, so `getUserMedia`, AudioWorklet, service workers, and `SharedArrayBuffer` (with COOP/COEP) all work against a VM-hosted API
- **Skip remote desktop.** Installing a desktop environment on a headless server to look at a file manager is wasted effort
- **Learn `tmux` — the one genuinely new skill, ten minutes.** Closing an SSH session kills anything running in it, so starting an overnight job and shutting your laptop will silently murder it. `tmux new -s train`, start the job, `Ctrl-B` then `D` to detach, `tmux attach -t train` to return. Practice this during Saturday's smoke test, because Tuesday and Thursday both depend on it

### Sync

Code lives in git and is checked out in both places, so the local GPU can run it. **GitHub is the sync mechanism and the deliverable**; the VM gets code by `git pull` on its own clone at `/srv/elums`.

> **Superseded Oct 6.** This section used to propose the VM as a second git remote with a `post-receive` hook running `docker compose up -d --build`. That cannot work — the box has no Docker Engine ([docs/vm-baseline.md](docs/vm-baseline.md)) — and it is moot regardless, since the VM is not a deployment target. Nothing is "deployed" by us at all.

**The VM must not hold the only copy of anything.** It is an unprivileged container with `workspace_is_volume: false`: a recycle destroys it. Push code to GitHub at every milestone, and copy trained checkpoints and results off the box the moment they exist.

---

## Background jobs calendar

These consume wall-clock, not working hours. Forgetting them is the most likely way to lose a day.

| When | Where | Job | Blocks |
| --- | --- | --- | --- |
| Sat, first 30 min | **Local** | Inference weights: Mel-Band RoFormer, RMVPE, Whisper large-v3-turbo, WhisperX align model, all-in-one checkpoints, LAION-CLAP (~20 GB) | Everything from Sunday on |
| Sat, first 30 min | **VM**, in `tmux` | GTSinger (54 GB) + NanoPitch-PreExtract (3.64 GB) — these only ever matter where the training happens | Tue night |
| Tue overnight | **VM** | SSL layer probe on a 2-hour GTSinger subset, then cache the 2–3 winning layers (~30 GB) | Fri technique-head training |
| Thu overnight | **VM** | NanoPitch training with the augmentation stub implemented | Nothing — pure artifact |
| Fri daytime | **VM** | Technique head on cached features + ablation sweep | Nothing — runs light (<4 GB) |
| Sat or Sun | **VM** | Bulk-ingest the 20–30 song demo catalog (~1 hr GPU) | Sun recommendations (CLAP embeddings need the full catalog) |

Two rules. Keep the heavy overnight runs off the same night as anything else — a Q4 LLM, separation, and ASR cannot share 16 GB (§12.3). And **do not cache SSL features locally**: one WavLM layer over 80 h of GTSinger is ~30 GB and you want two or three, on top of GTSinger itself, ~20 GB of weights, Docker images, and accumulating audio blobs. That is well past comfortable on 200–500 GB free. Features live on the VM where there is 1.5 TB.

---

## Sat Oct 3 — 8hr — Foundation (local) + VM smoke test

- [ ] **First 30 min:** kick off the local inference-weight downloads (see calendar above)
- [ ] **VM smoke test, 30 min.** Defer the *work*, not the *verification* — the worst outcome is discovering Tuesday night that the driver is broken. Note the command Smule gave you has `-N`, which means "do not execute a remote command" and **will not give you a shell**. Drop it:

```bash
ssh -i <key> -p 48585 root@108.39.26.2
nvidia-smi                                                     # GPU present? driver version?
docker run --rm --gpus all nvidia/cuda:13.0-base nvidia-smi     # container toolkit wired up?
df -h                                                           # is the 1.5 TB actually mounted?
nproc && free -g                                                # 16 vCPU, how much RAM?
git --version && tmux -V
```

- [ ] Start the GTSinger + NanoPitch-PreExtract downloads on the VM **inside `tmux`**, then detach. This is also your tmux practice run
- [ ] Confirm Cursor Remote-SSH connects to the VM. If it is going to be a problem, find out today
- [ ] Work the **portability disciplines checklist** above — about an hour, and it is what makes the later transition a non-event
- [ ] Local GPU verification: install torch with a CUDA ≥12.8 wheel (cu130 covers your card and the VM's), assert your arch is in `torch.cuda.get_arch_list()`, then **force a real kernel launch** — `is_available()` returns `True` on a wheel with no matching kernels (§11.6)
- [ ] Scaffold: docker compose with `api` / `worker` / `gpu-worker` / Postgres 18 / Valkey / Caddy; Vite 8 + React 19; FastAPI + SQLAlchemy 2 async + Alembic; Procrastinate; `@hey-api/openapi-ts` codegen in the Vite build; `make up`
- [ ] Auth + seed: opaque session tokens, Argon2id, 10 demo users with a pre-populated social graph (§9)
- [ ] Blob store: content-addressed filesystem, `BlobStore` Protocol, Caddy `forward_auth` + `file_server` so Python stays out of the byte path (§4)
- [ ] Separation job end-to-end on one song via `python-audio-separator`

**End state:** `make up` is green, you can log in as a seeded user, and uploading an MP3 returns a vocal stem and an instrumental. The VM is verified and downloading in the background.

> Separation at ~7 GB is the one tight fit on 8–12 GB. If it will not hold, turn `--mdxc_segment_size` down — slower, but it fits. Find this out today, not Sunday.
>
> **Resolved Oct 3, confirmed Oct 6 — this was the right instruction and it worked.** `segment_size` was set to 128 (half audio-separator's mdxc default of 256) on Day 1 and separation measures **1.8 GB**, not 7 GB, on real full-length songs. An OOM ladder halving down to a floor of 32 was built as well, so the escape hatch is automatic rather than manual. See the measured table at the top of this document.

---

## Sun Oct 4 — 4hr — Ingest A: structure

- [ ] `all-in-one-infer` wired with `--stems-from-dir` so it reuses Saturday's stems instead of separating again
- [ ] Sections (verse/chorus/bridge), beats, downbeats, tempo
- [ ] Key via Krumhansl-Schmuckler over instrumental CQT chroma, cross-checked later against the note histogram (§5)
- [ ] RMS-VAD segmentation of the vocal stem — threshold 0.1, min silence 1.0 s, max segment 30 s
- [ ] Procrastinate job chain with the step-indexed progress the UI will poll, and `lock="gpu:separation"` as the GPU semaphore

**End state:** a song row carrying sections, beats, key, and vocal-activity segments, with visible per-stage progress.

---

## Mon Oct 5 — 4hr — Emails, then Ingest B: lyrics

- [ ] **First 30 min: send both Smule emails.** One to each group, so make them count. Research: DAMP access (Stanford pulled it and the Zenodo mirrors are restricted — amateur karaoke audio would materially improve the coaching metrics), and whether a stronger NanoPitch checkpoint exists. Product: the assumptions list they offered. Draft these Sunday evening so Monday is a send, not a writing session. **Do not plan around the reply.**
- [ ] LRCLIB lookup first — line-level synced lyrics for free reduce this to word-within-line
- [ ] Whisper large-v3-turbo over the VAD segments as the fallback, batched (the gain is better segment boundaries, not cleaner audio — §5)
- [ ] WhisperX CTC alignment on the vocal stem; harvest `char_segments_arr`
- [ ] Syllable grouping: hyphenation dictionary for split points, CTC timings for boundaries
- [ ] Anchor-sequence reconciliation when reference lyrics exist
- [ ] Energy-gated fallback emitting wordless note events where the stem is loud but the transcript is empty (Whisper deletes >50% of vocables — §5)

**End state:** word- and syllable-level timings over a real song, verified by eye against the audio.

---

## Tue Oct 6 — 4hr — Ingest C: note grid → **M1**

- [ ] RMVPE f0 over the vocal stem
- [ ] Note segmentation: derivative-peak + inverse-confidence, constrained to syllable spans, snapped to the beat grid, quantized to key
- [ ] Chart writer + song bundle schema; `audiowaveform` peaks precomputed for wavesurfer
- [ ] CLAP embedding job, fire-and-forget per song (cheap now, unblocks Sunday)
- [ ] Karaoke playback page: scrolling lyrics against the instrumental
- [ ] Run the full pipeline on 10 diverse songs and look at the note grids honestly

> **M1 — upload an arbitrary MP3 and get a playable karaoke chart.** This is the gate for everything after it. If the note grids are poor, decide today whether to add a correction UI or fall back to a curated seed catalog (risk 4) — do not discover it on Friday.

- [ ] **First real VM job.** Before bed, `git push vm main`, then start the SSL layer probe and feature caching **in `tmux`** and detach. Batch work, nothing interactive, low stakes — exactly the right first contact

---

## Wed Oct 7 — 8hr — Capture, scoring, async duet → **M2**

- [ ] **Key-estimate reconciliation (carried from the Day 4 8-song validation pass).** `key.py`'s chroma correlation and `notes.py`'s note-histogram cross-check disagree on 5/8 real songs — 2 are the known relative-major/minor confusion, 3 show both sides at low confidence (e.g. `hot-n-cold`: 0.023 vs 0.022), i.e. the algorithm is honestly uncertain and that isn't surfaced today. Fix cheaply, before `_quantize_to_key` matters for M2 scoring: add a `key_confidence_low` flag (threshold ~0.05–0.08) when either estimate is near a tie, and have confidence pick the resolved winner between chroma/notes rather than reporting two unreconciled numbers (keep both raw values for audit). Do **not** attempt the deeper blended-correlation approach here — see PROGRESS.md's backlog note.
- [ ] **`voiced_frame_ratio` threshold sweep (carried from the Day 4 8-song validation pass).** RMVPE's `voiced_frame_ratio` reads systematically lower than VAD's `voiced_duration_s/duration_s` on all 8/8 real songs (mean diff ≈ -0.11, every song negative, not noise). Likely a genuine definitional gap (RMVPE's `thred=0.03` pitch-confidence gate vs VAD's RMS energy gate also catching unvoiced consonants/breath), but not confirmed. Sweep RMVPE's `thred` (0.01 / 0.03 / 0.05) on 2–3 real songs; if the gap narrows, the current threshold is miscalibrated — if it barely moves, document the gap as a real measurement-definition difference rather than tuning further.
- [ ] AudioWorklet capture → SharedArrayBuffer ring (`ringbuf.js`) → Web Worker WAV encode; COOP/COEP headers set and `crossOriginIsolated` asserted
- [ ] `getUserMedia` with `echoCancellation / noiseSuppression / autoGainControl` all false, then **verify with `getSettings()`** and banner if they came back true (§10.2)
- [ ] Chunked upload during recording, so post-song wait is seconds
- [ ] Server analysis job: f0, alignment to the chart, per-note measurement vector, median-anchored loudness
- [ ] Canvas 2D pitch lane at 60fps, driven by `AudioContext.currentTime`, zero per-frame allocation, DPR capped at 2 (§13)
- [ ] Playback with stacked takes for comparison
- [ ] **Async seed/join:** publish a take as a joinable seed; a joiner sings against seed + backing. ~90% shared backend with Saturday's live room, and it is the demo safety net

> **M2 — sing a song against a chart, get per-note pitch scoring, and join someone else's seed.** "Singing together" is now satisfied in its async form, five days before the deadline.

> **Deviation taken, flagged for Thursday.** EC-0's AudioWorklet + `SharedArrayBuffer` capture graph was not attempted live tonight — no interactive browser/microphone was available in this session to verify it loads through Caddy's COOP/COEP path, which was EC-0's own acceptance bar. `SingPage.tsx` shipped against the plan's own named fallback (`MediaRecorder`) instead, per its own words: *"fall back to MediaRecorder today, ship W3-W6 against it, and move the worklet to Thursday... That costs the zero-allocation guarantee and the live lane, not M2 — say so explicitly rather than sliding."* See `PROGRESS.md`'s Day 5 section for the full writeup. **Re-read against the brief, this is not optional stretch scope**: the brief states *"You will need to learn about WebAssembly and Web Audio to implement features such as acoustic echo cancellation. Note that these features are in scope if needed"* — i.e. AudioWorklet/WebAssembly audio work is itself named in the brief, not merely a vehicle for the AEC filter alone. The descope ladder below still correctly treats the **WASM AEC filter** as the first thing to cut if Thursday runs out of room (headphones are a documented, legitimate product posture per §10.3) — but **transferring capture off `MediaRecorder` and onto a real AudioWorklet graph is not the same cut**, since the live 60fps pitch lane (also named directly in the brief) depends on the worklet's `SharedArrayBuffer` ring, not on the echo canceller. Thursday should therefore prioritize the AudioWorklet transfer itself ahead of the AEC filter specifically.

---

## Thu Oct 8 — 8hr — Mobile + real-time audio → **M3**

Real iPhone in hand from hour one. **Work this list top-down and cut from the bottom** — the ordering is deliberate.

- [ ] **0. Transfer capture off `MediaRecorder` onto a real AudioWorklet graph** (carried from Wednesday's EC-0 fallback — see the note above). First, a 15-minute sanity check in a real browser: a no-op worklet loads through Caddy at `:8080` (not Vite's dev port) with COOP/COEP headers set and `crossOriginIsolated` asserted, and survives a production `vite build` + `vite preview`. Only once that is confirmed, replace `SingPage.tsx`'s `MediaRecorder`/chunked-blob-upload path with: `getUserMedia` → `AudioWorkletNode` → `SharedArrayBuffer` ring (`ringbuf.js`) → a Worker draining the ring for upload, and a second Worker consumer for the live pitch lane (item 2 below). This item, not item 4's AEC filter, is the one the brief's "WebAssembly and Web Audio" line actually makes non-negotiable — see the note above the descope ladder's "cut WASM AEC first" entry for why those are two different cuts
- [ ] **1. iOS Safari works at all.** `audioSession.type` dance: `auto` → `getUserMedia` → `play-and-record`; teardown `playback` → `auto` or output fidelity stays degraded. Silent-switch fix. Capture fallback ladder. Never force `sampleRate` (§10.4)
- [ ] **2. NanoPitch WASM in the pitch worker.** Emscripten build of `nanopitch.c`, realtime Viterbi, live pitch meter (§2.2)
- [ ] **3. Latency calibration.** `@adasp/latency-test`, 3 runs, gate on the 18 dB reliability ratio, share the **main** AudioContext, use the **full** round-trip without subtracting `outputLatency`. Ship the manual nudge slider (§10.4)
- [ ] **4. WASM known-reference AEC.** Partitioned-block FDAF, backing track as `inputs[1]`, bulk delay absorbed by a `DelayNode`, adapt-then-freeze, strictly linear on the stored take. Expect 10–15 dB ERLE, not 30 (§10.3)
- [ ] **5. Diagnostics screen.** `sampleRate`, `baseLatency`, `outputLatency`, `crossOriginIsolated`, `getSettings()`, measured RTT, estimated ERLE, live RTF meter

> **M3 — record, score, and see a live pitch lane on a real iPhone.** Item 4 is the designated casualty if iOS eats the day; headphones bypass AEC and that is a documented product posture, not a failure.

- [ ] Kick off NanoPitch training on the **VM** overnight, in `tmux`

---

## Fri Oct 9 — 8hr — Coaching engine + progress → **M4**

**Coaching (6hr) — measurement breadth first, detectors second.** The whole §6.4 argument is that detectors are cheap once the measurements exist.

- [ ] Five new measurement dimensions: breath events and breath management, registration transitions, onset type, vowel formant consistency, phrase dynamic arc — each behind the same measurement contract so any one is independently skippable (risk 14)
- [ ] Composable detector algebra: dimension × direction × scope × basis × co-occurrence, searched per performance
- [ ] Evidence scoring, confidence tiering, suppression of low-confidence claims, diversity-aware selection
- [ ] Thresholds from §6.2 in config-as-data: 25/50 cent pitch bands, ±50 ms timing green with late weighted harder than early, 4.5–6.5 Hz vibrato, pitch-error flagging suppressed inside detected vibrato
- [ ] LLM voice layer on `qwen/qwen3.8-27b`: `reasoning: {enabled: false}`, non-thinking sampling set, invariant prefix first for caching, JSON Schema + `require_parameters: true`, `instructor` repair loop. Assert `reasoning_tokens == 0` in the test suite (§12)
- [ ] Card UI with click-a-card-to-seek-the-waveform
- [ ] *Stretch:* the propose-and-verify loop (§6.4c) — additive, cut freely

**Progress (2hr)**

- [ ] Per-song z-score normalization; Elo-style song difficulty as the shrinkage fallback
- [ ] Rolling median of last 5, IQR uncertainty band, three-way verdict gated at ≥8 performances with "sing N more" copy below
- [ ] Per-dimension trends; **personal best per song** as the hero metric

- [ ] Background, on the **VM**: train the technique head on the cached features, run the ablation, save the table. Light enough (<4 GB) to share the card with nothing else competing

> **M4 — timestamped coaching cards you can click to hear, plus a progress view that refuses to over-claim.**

---

## Sat Oct 10 — 8hr — Live duet + challenges → **M5**

**Duet (6hr)**

- [ ] FastAPI WebSocket rooms, one `asyncio` task per room so message handling is sequential and races vanish
- [ ] NTP-style clock handshake; song starts at an **absolute server timestamp**; only correct playback position when >50 ms off (Smule's own method — §7.2)
- [ ] Lobby, ready-up, 4-beat count-in
- [ ] Dual local recording at full quality; **state-only channel at 5–10 Hz with the voice channel muted during the take** (§7.3 — this is the decision most people get wrong)
- [ ] GCC-PHAT alignment: band-limit 200 Hz–4 kHz, constrain to ±500 ms, parabolic interpolation at 16× upsample. Use backing-track bleed as the free reference where present
- [ ] Two-point drift estimator; resample only when the delta exceeds 15 ms. Never time-stretch
- [ ] `pyloudnorm` per stem gated on voiced regions → common vocal bus → ffmpeg chain → **two-pass linear** `loudnorm` to −14 LUFS / −1 dBTP with explicit `-ar 48000`
- [ ] Keep dry stems; make the mix re-renderable
- [ ] Graceful degradation: peer drops → solo take auto-published as a joinable seed

**Challenges (2hr)**

- [ ] Closed-vocabulary LLM generation, detector names validated against the real registry, unknowns dropped
- [ ] Deterministic evaluation by the existing detectors
- [ ] Group challenges that **show individual contribution**; rank on process not score (§6.6)
- [ ] Valkey sorted sets for leaderboards, rebuildable from Postgres

> **M5 — two devices sing a duet and get one mixed artifact with per-singer scores.**

---

## Sun Oct 11 — 8hr — Recommendations, sharing, deliverable hardening → **M6**

**Recommendations (3hr)**

- [ ] Multi-retriever union: vocal-fit filter, CLAP kNN, metadata match, popularity-by-segment prior, item-item co-occurrence (§8.1)
- [ ] `hnsw.iterative_scan = relaxed_order` and `ANALYZE` after bulk load, or filtered recall silently collapses
- [ ] Linear-blend ranker over ~8 features; LLM writes the explanation from a **closed candidate list with IDs**
- [ ] Duet partner matching by complementary range — handoff, not compromise
- [ ] Post-song "what next," causally tied to the analysis that just completed
- [ ] Fit-vs-taste slider

**Sharing (2hr)**

- [ ] ffmpeg render: 9:16, 1080×1920, H.264 + AAC, 15–30 s of the best-scoring section, burned-in captions
- [ ] Web Share with `canShare({files})` checked first and `share()` as the **first await** in the gesture handler; copy-link fallback
- [ ] Pillow OG cards (deterministic → cacheable); Jinja2 share pages at `/s/{id}`

**Deliverable hardening (1.5hr)** — replaces the former "VM deployment rehearsal." Smule deploys this themselves, so the clean clone *is* the product and this is the only work that protects it

- [ ] **Production compose topology.** Today's stack is a dev stack: [deploy/Caddyfile](deploy/Caddyfile) proxies the Vite dev server at `frontend:5173`, `api` runs `--reload`, and source is bind-mounted into every service. Add a built-frontend target served as static assets, with no bind mounts and no reload
- [ ] **A cross-platform model fetch.** `/models/` is gitignored, so a fresh clone has no weights — and the only fetch script is `scripts/download_weights.ps1`, which is PowerShell. Add `make fetch-models` that works on Linux, covering everything in [config/models.yaml](config/models.yaml) (~4–5 GB; the 913 MB RoFormer checkpoint is the one that does not auto-download)
- [ ] **Make one command actually one command.** `up`, `migrate`, and `seed` are three separate `Makefile` targets today; a deployer following the README gets a running stack against an unmigrated database
- [ ] **GPU/CPU compose profiles.** `gpus: all` is unconditional on `gpu-worker`, so `docker compose up` hard-fails on a host without an NVIDIA GPU or the container toolkit. Risk 2 already names the CPU ingest fallback; wire it to a profile. Auto-detect `EXPECTED_SM_ARCH` from `torch.cuda.get_device_capability()` rather than defaulting to this machine's `sm_86`
- [ ] **Decide what ships as seed content.** `/data/*` is gitignored, so their first run has zero songs and zero performances. Resolve the two licensing questions (GTSinger-derived technique-head checkpoint; shippable demo audio) and ship whatever is clear
- [ ] Bulk-ingest the 20–30 song demo catalog locally for your own demo recording, and re-run the CLAP embedding job over the full catalog
- [ ] Named **Cloudflare Tunnel** for phone testing — quick `trycloudflare.com` tunnels cap at 200 in-flight requests and do not support SSE, which would make this look broken in a way that reads as your bug (§13)

**Buffer + submission prep (1.5hr)**

- [ ] README with the honest limitations list and the licensing audit
- [ ] **AI usage and cost ledger** (§12.5) — replace the estimated token counts with observed ones
- [ ] Ablation tables: technique head, NanoPitch delta
- [ ] Demo script

> **M6 — the loop closes.** Sing → coached → measured → recommended → challenged → sing again.

---

## Mon Oct 12 — 2hr — Finalize

- [ ] Final pass on the README and writeup
- [ ] Record a demo walkthrough video **against the local stack** — correct now that Smule deploys the repo themselves; there is no deployment of ours for it to be recorded against
- [ ] **Clean-room verification on a real Linux Docker host.** Fresh clone, documented `.env`, fetch models, one command, seed data loads, a take uploads and scores. This is the deliverable's only acceptance test, and neither Docker Desktop nor the VM can run it — Docker Desktop goes through the WSL2 shim rather than a native Engine plus `nvidia-container-toolkit`, and the VM has no Docker at all. An hour on a throwaway hourly GPU box is the cheapest way to have actually checked
- [ ] Push and submit

---

## Descope ladder

The original §14 had a full buffer day; compressing into your hours spent most of it. The schedule stays safe by **shedding scope predictably instead of slipping days.** Cut from the bottom up:

| Cut | Cost | Still satisfies the brief? |
| --- | --- | --- |
| 6. Technique head → use the STARS checkpoint as-is | Lose the ablation table and ~0.2 macro-F1 | Yes |
| 5. Propose-verify LLM loop → deterministic claims only | Less card variety | Yes |
| 4. Live duet room → async seed/join only (working since Wed) | Lose simultaneity, keep the artifact | Yes — "two users sing together" is met |
| 3. Partner matching + fit slider → song recommendations only | Lose the duet-matching differentiator | Yes |
| 2. Group challenges → individual only | Lose the group-competition angle | Partially — the brief names groups |
| 1. WASM AEC *filter* → document the headphone assumption | Lose a brief-named stretch item | Yes — it is "in scope if needed" |

Cutting 1 and 2 first is deliberate: AEC is explicitly optional in the brief, and group challenges are the smallest slice of a required feature. Anything below line 4 starts costing a required feature, so treat line 4 as the floor.

> **Clarified Oct 7, evening.** Line 1 is specifically the adaptive echo-cancellation *algorithm* (partitioned-block FDAF) — cutting it means shipping with the headphones-only posture, which the brief's own "if needed" wording allows. It does **not** mean staying on `MediaRecorder` instead of AudioWorklet: the live pitch lane and `getSettings()`-verified AEC/NS/AGC opt-out are both named directly in the brief's capture requirements, and both need the AudioWorklet + `SharedArrayBuffer` graph to exist regardless of whether the FDAF filter itself gets built inside it. Transferring off `MediaRecorder` is Thursday's item 0, ahead of this ladder.

## Daily discipline

- **End every day at a demonstrable state**, even if the day's scope shrank. A working narrow thing beats a broken broad one, and it is the only honest progress signal.
- **Commit at every milestone** with the milestone name in the message, so the git history is itself a progress narrative for the reviewers.
- **Log token counts and GPU timings from day one** (structlog JSON with `model` / `duration_ms` / `vram_peak_mb`). Sunday's ledger is then a query, not an archaeology project.
- **Timebox mobile debugging.** If any single iOS issue exceeds 90 minutes, write it into the limitations list and move on.
- **Never debug two machines at once.** When something breaks, reproduce it on one machine before touching the other. Cross-machine debugging where you do not yet know which side is at fault is a specific and expensive time sink, and it is the main reason this schedule is local-first.
- **Push to GitHub at every milestone, not just to the VM.** Nine days of work must not live only on a box you do not control.
