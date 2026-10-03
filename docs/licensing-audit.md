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

## Datasets

### `GTSinger/GTSinger`, `smulelabs/NanoPitch-PreExtract`, `laion/larger_clap_music_and_speech`

- HuggingFace API: all three report `gated: false, private: false` (checked Oct 3 2026). No token or access request needed. GTSinger itself is CC BY-NC-SA 4.0 (per §11.1 of the approach document) — usable for training and reporting results, not for shipping a derivative weight commercially; this is already accounted for in the approach document's framing of the technique head as a research artifact with a documented ablation, not a product dependency in itself.

## Still to audit (carried forward, not blocking today)

- `psola` (GPL-3) — scheduled for Sat Oct 10 (pitch correction, default-off stretch feature). Confirm it never enters a required code path.
- `madmom` pretrained model files (CC BY-NC-SA) — the approach document already excludes madmom via the `all-in-one-infer` fork; confirm the fork genuinely ships no madmom-derived weights before Sun Oct 4.
- Essentia (AGPL), PESTO (LGPL), MuQ/MERT (CC-BY-NC) — named in the approach document as excluded by design (§11.5); no code should import any of them. Spot-check `requirements`/`pyproject.toml` for accidental transitive pulls once they exist.
