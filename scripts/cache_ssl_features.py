"""T7 (IMPLEMENTATION_PLAN_2026-10-06.md) — cache the winning WavLM layers.

Reads `results/ssl_layer_probe.json` (written by `scripts/ssl_layer_probe.py`),
picks the top `--num-layers` (default 2) by macro-F1, and caches those
layers' frame-level hidden states (fp16) for every clip in GTSinger's
English `processed/metadata.json` to the VM's own SSD — explicitly *not*
synced back to this repo (§11.2 / the schedule's "never cache SSL features
locally" applies to the dev machine, not the VM's own disk, which this
script is the sanctioned exception for).

One `.npy` per (item_name, layer), fp16, shape (num_frames, 1024), under
`--cache-root` (default `/workspace/ssl_cache`). Frame count matches
`ssl_layer_probe.py`'s own `output_hidden_states` output exactly, so
Friday's technique head can re-derive the same phoneme-span pooling
without re-running WavLM.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import numpy as np
import torch

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("cache_ssl_features")

GTSINGER_SNAPSHOT = Path(
    "/workspace/.hf_home/hub/datasets--GTSinger--GTSinger/snapshots/"
    "4426c862beed558b7e1cb8a4dce7e8c0c83bb208"
)
METADATA_PATH = GTSINGER_SNAPSHOT / "processed" / "English" / "metadata.json"
WAVLM_MODEL_ID = "microsoft/wavlm-large"
WAVLM_SAMPLE_RATE = 16_000
PROBE_RESULTS_PATH = Path(__file__).resolve().parent.parent / "results" / "ssl_layer_probe.json"
DEFAULT_CACHE_ROOT = Path("/workspace/ssl_cache")


def pick_top_layers(probe_results: dict, num_layers: int) -> list[int]:
    ranked = sorted(
        probe_results["results_by_layer"].items(), key=lambda kv: kv[1]["macro_f1"], reverse=True
    )
    top = [int(layer) for layer, _ in ranked[:num_layers]]
    log.info("top %d layers by macro-F1: %s", num_layers, top)
    return top


def safe_item_filename(item_name: str) -> str:
    # item_name is "Language#Singer#Technique#Song#Group#index" — "/" never
    # appears, but song titles contain spaces/apostrophes; keep those as-is
    # (valid on this VM's ext4/overlay fs) and only swap the one separator
    # character ("#") that would otherwise be fine too, for readability.
    return item_name.replace("#", "__")


def cache_item(model, feature_extractor, device, item: dict, layers: list[int], cache_root: Path) -> bool:
    out_paths = {layer: cache_root / f"{safe_item_filename(item['item_name'])}__layer{layer}.npy" for layer in layers}
    if all(p.exists() for p in out_paths.values()):
        return True  # resumable: already cached from an earlier (possibly interrupted) run

    import soundfile as sf

    wav_path = GTSINGER_SNAPSHOT / item["wav_fn"]
    try:
        audio, sr = sf.read(str(wav_path), dtype="float32", always_2d=False)
    except Exception as exc:  # noqa: BLE001
        log.warning("skip.audio_load_failed item=%s error=%s", item["item_name"], exc)
        return False
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != WAVLM_SAMPLE_RATE:
        import librosa

        audio = librosa.resample(audio, orig_sr=sr, target_sr=WAVLM_SAMPLE_RATE)

    inputs = feature_extractor(audio, sampling_rate=WAVLM_SAMPLE_RATE, return_tensors="pt")
    input_values = inputs["input_values"].to(device)
    with torch.no_grad():
        outputs = model(input_values, output_hidden_states=True)

    for layer in layers:
        hidden = outputs.hidden_states[layer][0].to(torch.float16).cpu().numpy()
        np.save(out_paths[layer], hidden)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--num-layers", type=int, default=2)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    parser.add_argument("--limit-items", type=int, default=None, help="Smoke-test on a small item count.")
    args = parser.parse_args()

    if not PROBE_RESULTS_PATH.exists():
        log.error("missing %s — run scripts/ssl_layer_probe.py first", PROBE_RESULTS_PATH)
        return 1
    probe_results = json.loads(PROBE_RESULTS_PATH.read_text(encoding="utf-8"))
    layers = pick_top_layers(probe_results, args.num_layers)

    args.cache_root.mkdir(parents=True, exist_ok=True)

    with METADATA_PATH.open(encoding="utf-8") as f:
        items = json.load(f)
    if args.limit_items is not None:
        items = items[: args.limit_items]
    log.info("caching %d layers for %d items into %s", len(layers), len(items), args.cache_root)

    from transformers import AutoFeatureExtractor, WavLMModel

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    feature_extractor = AutoFeatureExtractor.from_pretrained(WAVLM_MODEL_ID)
    model = WavLMModel.from_pretrained(WAVLM_MODEL_ID).to(device).eval()

    start_time = time.monotonic()
    done = 0
    skipped = 0
    for i, item in enumerate(items):
        ok = cache_item(model, feature_extractor, device, item, layers, args.cache_root)
        if ok:
            done += 1
        else:
            skipped += 1
        if (i + 1) % 100 == 0 or i + 1 == len(items):
            elapsed = time.monotonic() - start_time
            log.info("progress %d/%d (cached=%d skipped=%d), %.1fs elapsed", i + 1, len(items), done, skipped, elapsed)

    log.info("cache_ssl_features done: cached=%d skipped=%d root=%s", done, skipped, args.cache_root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
