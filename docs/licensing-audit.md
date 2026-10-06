# Licensing audit

Ongoing log of license verification for every third-party model, dataset, and package Elums depends on. Each entry records what was claimed in [ELUMS_TECHNICAL_APPROACH.md](../ELUMS_TECHNICAL_APPROACH.md), what was independently verified, the source(s), and the date checked. Per risk 12 in the approach document, the goal is zero NC/GPL-licensed assets reaching the shipped product; anything short of that must be an explicit, documented exception confined to a research artifact.

## Models

### `vocals_mel_band_roformer.ckpt` (Kimberley Jensen, Mel-Band RoFormer vocals)

- **Claimed (§5):** "Kimberley Jensen's `vocals_mel_band_roformer` checkpoint was relicensed from GPL-3.0 to MIT in April 2026 — any guide written before mid-2026 will tell you otherwise."
- **Resolved filename (EC-5):** `vocals_mel_band_roformer.ckpt`, listed by `audio-separator --list_models` (v0.47.0) as `Roformer Model: MelBand Roformer | Vocals by Kimberley Jensen`, SDR vocals* 12.6.
- **Verified independently, Oct 3 2026:**
  - Original release: GPL-3.0, June 17 2025 (HuggingFace `KimberleyJSN/melbandroformer`, Discussion #2).
  - Relicensed to MIT by the author on HuggingFace, April 18–22 2026 (README front-matter `license: mit`, commit `ac9b061`).
  - Independently corroborated by two downstream repos that updated their own license tables/tests in response: `lucasnewman/mlx-audio` commit `2a6db6d` ("docs: update Kim Vocal 2 license to MIT (relicensed by author)") and the `mlx-community/mel-roformer-kim-vocal-2-mlx` model card, which documents the full provenance timeline.
- **Verdict: MIT. Clear to ship.** The claim in the approach document is correct, not merely plausible — do not re-litigate this on a later day without new information.

### `audio-separator` (PyPI package, `nomadkaraoke/python-audio-separator`)

- GitHub API confirms `license: MIT`, 1,399 stars (checked Oct 3 2026). PyPI distribution name is `audio-separator`, **not** `python-audio-separator` — that is the GitHub repo name only (§3.3 of the implementation plan).

### `smule-renaissance`, `windowed-roformer` (Smule Labs)

- GitHub API: both report `license: MIT` (checked Oct 3 2026, consistent with §2 of the approach document).

### `smulelabs/NanoPitch`

- GitHub API reports `license: NOASSERTION` (6 stars). Matches §2.2's description exactly — the LICENSE file is CC BY-NC-ND 4.0 but GitHub's tooling does not detect it, so it displays as unassessed rather than as the real restrictive license. **Do not treat `NOASSERTION` as "no license" — read the file.** A written grant from Smule Labs has been requested (see MA-4 in the implementation plan); until it arrives, NanoPitch work is a research artifact only, per the license's own NonCommercial/NoDerivatives terms, and is not shipped.

### `openmirlab/all-in-one-infer`

- GitHub API reports `license: NOASSERTION` (27 stars). Matches risk 10 in the approach document (single-maintainer fork). License text itself not yet re-read in full; re-verify before Sun Oct 4 when this becomes load-bearing.

### `transformers` (PyPI package, Hugging Face)

- **Resolved Mon Oct 5 (L1, EC-2):** runs the HF-transformers-format `whisper-large-v3-turbo` checkpoint already on disk — `whisperx` was evaluated and rejected (see PROGRESS.md Day 3 EC-1); `transformers` is the library that actually loads that checkpoint.
- PyPI/GitHub: **Apache-2.0**. `transformers==4.57.0` (the version named in the Oct 5 plan's dependency surface) is **yanked on PyPI** ("Error in the setup causing installation issues", verified via `pypi.org/pypi/transformers/json` Oct 5 2026) — pinned to `5.9.0` instead, the newest non-yanked release at lock time.
- **Verdict: Apache-2.0. Clear to ship.**

### `pyphen` (PyPI package, hyphenation dictionaries)

- **Resolved Mon Oct 5 (L3, EC-5):** syllable split points for the hyphenation grouping step.
- PyPI metadata: tri-licensed **GPL-2.0 / LGPL-2.1 / MPL-1.1**, per the Oct 5 plan's own finding. Shipped under **MPL-1.1** (the permissive option of the three; does not trigger GPL/LGPL copyleft obligations for Elums' own code, which is not itself GPL/LGPL).
- `cmudict` (BSD-2) was considered as the cleaner alternative (per the plan's own suggestion) but not used: `pyphen`'s `hyphenate_word` returns direct character-offset split points compatible with L2's char-level spans, whereas `cmudict`'s phoneme counts would need a second mapping step back to character offsets with no corresponding win in license cleanliness once MPL-1.1 is selected.
- **Verdict: MPL-1.1. Clear to ship.**

### `torchaudio`'s `WAV2VEC2_ASR_BASE_960H` bundle (CTC alignment model, L2)

- **Resolved Mon Oct 5 (L2, EC-3):** wav2vec2 CTC emissions for forced alignment, torchaudio's own bundled pipeline (`torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H`) rather than a separate `facebook/wav2vec2-base-960h` fetch via `huggingface_hub` — keeps the download path identical to `structure_beats`' existing `torch.hub.set_dir()`-rooted cache (no second credential/cache convention for one more checkpoint).
- Underlying checkpoint: fairseq's wav2vec 2.0 ASR base model, fine-tuned on LibriSpeech 960h — distributed by the torchaudio project itself as part of its pretrained-pipelines surface, under torchaudio's own **BSD-3-Clause** project license (verified via `pytorch/audio` GitHub repo license, Oct 5 2026). No separate NC/restrictive license attaches to pipeline weights distributed this way (distinct from madmom's case, EC-3 of the approach doc's risk register).
- **Verdict: BSD-3-Clause. Clear to ship.**

### RVC-Project's `infer/rmvpe.py` (RMVPE inference code, vendored)

- **Resolved Tue Oct 6 (T1, EC-1):** there is no PyTorch RMVPE package on PyPI, only the checkpoint (`models/rmvpe.pt`, already on disk since Day 1). Fetched `infer/rmvpe.py` directly from `RVC-Project/Retrieval-based-Voice-Conversion-WebUI`'s GitHub repo (main branch, Oct 6 2026) and vendored a trimmed copy into `elums/vendor/rmvpe/model.py` — the ONNX/DirectML branch, `tools.cuda_graph`, and `configs.config` auto-selection (all RVC-WebUI-specific, none of it load-bearing here) were removed; the DeepUnet/E2E/MelSpectrogram architecture and decode logic are otherwise unchanged.
- GitHub repo license: **MIT**, copyright liujing04 / 源文雨 / Ftps (2023). Full text copied verbatim into `elums/vendor/rmvpe/LICENSE`.
- **Verdict: MIT. Clear to ship.**

### `laion/larger_clap_music_and_speech` (CLAP checkpoint)

- Already covered under "Datasets" below for the HuggingFace `gated`/`private` check (Oct 3 2026) — the model repo's own license field has not been independently re-verified beyond that gated/private check; recorded as a gap, not asserted clear. `transformers==5.9.0`'s `ClapModel`/`ClapProcessor` (Apache-2.0, already audited above) is the loading code; no additional package license risk from T5's own work.

## Datasets

### `GTSinger/GTSinger`, `smulelabs/NanoPitch-PreExtract`, `laion/larger_clap_music_and_speech`

- HuggingFace API: all three report `gated: false, private: false` (checked Oct 3 2026). No token or access request needed. GTSinger itself is CC BY-NC-SA 4.0 (per §11.1 of the approach document) — usable for training and reporting results, not for shipping a derivative weight commercially; this is already accounted for in the approach document's framing of the technique head as a research artifact with a documented ablation, not a product dependency in itself.

## Still to audit (carried forward, not blocking today)

- `psola` (GPL-3) — scheduled for Sat Oct 10 (pitch correction, default-off stretch feature). Confirm it never enters a required code path.
- `madmom` pretrained model files (CC BY-NC-SA) — the approach document already excludes madmom via the `all-in-one-infer` fork; confirm the fork genuinely ships no madmom-derived weights before Sun Oct 4.
- Essentia (AGPL), PESTO (LGPL), MuQ/MERT (CC-BY-NC) — named in the approach document as excluded by design (§11.5); no code should import any of them. Spot-check `requirements`/`pyproject.toml` for accidental transitive pulls once they exist.
