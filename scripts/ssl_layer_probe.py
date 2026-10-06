"""T7 (IMPLEMENTATION_PLAN_2026-10-06.md) — SSL layer-selection probe.

Builds a stratified ~2-hour English subset of GTSinger (singer x technique
group), extracts WavLM-large hidden states at candidate layers
{1, 4, 7, 12, 18, 24} per phoneme span, trains one logistic-regression probe
per layer over the six per-phoneme technique labels (mixed, falsetto,
breathy, pharyngeal, vibrato, glissando), and writes a macro-F1-per-layer
table to results/ssl_layer_probe.json.

Runs on the VM via `uv run` (no Docker there — docs/vm-baseline.md).
Schema inspected directly against the live GTSinger cache before writing
this (not guessed): `processed/English/metadata.json` is a flat list of
items, each with `ph`/`ph_durs` (phoneme sequence and durations, seconds,
summing to the clip's own duration), six per-phoneme boolean label arrays
(`mix_tech`, `falsetto_tech`, `breathy_tech`, `pharyngeal_tech`,
`vibrato_tech`, `glissando_tech`), and `wav_fn` (relative to the snapshot
root). `<SP>` is the silence/pause phoneme token — excluded from both
pooling spans and label statistics, since a silence span carries no
singing-technique signal by construction.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ssl_layer_probe")

GTSINGER_SNAPSHOT = Path(
    "/workspace/.hf_home/hub/datasets--GTSinger--GTSinger/snapshots/"
    "4426c862beed558b7e1cb8a4dce7e8c0c83bb208"
)
METADATA_PATH = GTSINGER_SNAPSHOT / "processed" / "English" / "metadata.json"

WAVLM_MODEL_ID = "microsoft/wavlm-large"
WAVLM_SAMPLE_RATE = 16_000
# Confirmed Oct 5 on the VM (plan's own T7 note): num_hidden_layers=24, so
# output_hidden_states=True returns 25 tensors; index 0 is the CNN feature
# encoder. ~20ms/frame (50Hz) is this family's standard conv-stack stride.
CANDIDATE_LAYERS = (1, 4, 7, 12, 18, 24)
FRAME_RATE_HZ = 50.0
SILENCE_PHONEMES = {"<SP>", "SP", "<AP>", "AP"}
LABEL_COLUMNS = (
    "mix_tech",
    "falsetto_tech",
    "breathy_tech",
    "pharyngeal_tech",
    "vibrato_tech",
    "glissando_tech",
)
TARGET_SUBSET_SECONDS = 2 * 3600.0  # "~2-hour" per the plan's own T7 wording
RESULTS_PATH = Path(__file__).resolve().parent.parent / "results" / "ssl_layer_probe.json"


def _item_group(item: dict) -> str:
    """`item_name` is `Language#Singer#TechniqueFolder#Song#Group#index` —
    `Group` (Breathy_Group/Control_Group/Falsetto_Group/...) is the
    recording-session stratum; it is not the same thing as the six
    per-phoneme technique flags (a Control_Group clip can still carry
    mix_tech=1 on most phonemes — "mixed voice" is pop singing's default
    register, not an exceptional technique; confirmed directly against
    the data before writing this)."""
    return item["item_name"].split("#")[4]


def _item_duration_s(item: dict) -> float:
    return float(sum(item["ph_durs"]))


def build_stratified_subset(items: list[dict], target_seconds: float) -> list[dict]:
    """Round-robins across (singer, group) strata so every combination
    present in the corpus contributes before any one stratum dominates,
    stopping once the cumulative audio duration crosses `target_seconds`."""
    strata: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for item in items:
        strata[(item["singer"], _item_group(item))].append(item)
    for bucket in strata.values():
        bucket.sort(key=lambda it: it["item_name"])

    stratum_keys = sorted(strata.keys())
    cursors = {key: 0 for key in stratum_keys}
    selected: list[dict] = []
    total_s = 0.0
    while total_s < target_seconds:
        progressed = False
        for key in stratum_keys:
            bucket = strata[key]
            idx = cursors[key]
            if idx >= len(bucket):
                continue
            item = bucket[idx]
            cursors[key] += 1
            selected.append(item)
            total_s += _item_duration_s(item)
            progressed = True
            if total_s >= target_seconds:
                break
        if not progressed:
            break  # exhausted every stratum before reaching the target
    log.info("stratified subset: %d items, %.1f minutes, %d strata", len(selected), total_s / 60.0, len(stratum_keys))
    return selected


def load_audio_16k(wav_path: Path) -> np.ndarray:
    import soundfile as sf

    audio, sr = sf.read(str(wav_path), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != WAVLM_SAMPLE_RATE:
        import librosa

        audio = librosa.resample(audio, orig_sr=sr, target_sr=WAVLM_SAMPLE_RATE)
    return audio


def phoneme_spans_s(item: dict) -> list[tuple[float, float, int]]:
    """Returns (start_s, end_s, phoneme_index) for every non-silence
    phoneme in `item`, via a running cumulative sum of `ph_durs`."""
    spans = []
    cursor = 0.0
    for i, (ph, dur) in enumerate(zip(item["ph"], item["ph_durs"])):
        start_s, end_s = cursor, cursor + float(dur)
        cursor = end_s
        if ph not in SILENCE_PHONEMES and end_s > start_s:
            spans.append((start_s, end_s, i))
    return spans


def extract_layer_features(
    model, feature_extractor, device: torch.device, item: dict, snapshot_root: Path
) -> dict[int, list[np.ndarray]] | None:
    """Returns {layer: [pooled_vector_per_phoneme_span, ...]} for this one
    clip, aligned 1:1 with `phoneme_spans_s(item)`'s order, or None if the
    audio file is missing/unreadable (logged, not fatal — one bad clip
    should not abort the whole overnight run)."""
    wav_path = snapshot_root / item["wav_fn"]
    try:
        audio = load_audio_16k(wav_path)
    except Exception as exc:  # noqa: BLE001
        log.warning("skip.audio_load_failed item=%s error=%s", item["item_name"], exc)
        return None

    spans = phoneme_spans_s(item)
    if not spans:
        return None

    inputs = feature_extractor(audio, sampling_rate=WAVLM_SAMPLE_RATE, return_tensors="pt")
    input_values = inputs["input_values"].to(device)

    with torch.no_grad():
        outputs = model(input_values, output_hidden_states=True)

    num_frames = outputs.hidden_states[0].shape[1]
    per_layer: dict[int, list[np.ndarray]] = {layer: [] for layer in CANDIDATE_LAYERS}
    for start_s, end_s, _ in spans:
        start_frame = max(0, min(num_frames - 1, int(round(start_s * FRAME_RATE_HZ))))
        end_frame = max(start_frame + 1, min(num_frames, int(round(end_s * FRAME_RATE_HZ))))
        for layer in CANDIDATE_LAYERS:
            hidden = outputs.hidden_states[layer][0, start_frame:end_frame, :]
            per_layer[layer].append(hidden.mean(dim=0).float().cpu().numpy())
    return per_layer


def run_probe(limit_items: int | None = None, target_seconds: float = TARGET_SUBSET_SECONDS) -> dict:
    from transformers import AutoFeatureExtractor, WavLMModel

    log.info("loading metadata from %s", METADATA_PATH)
    with METADATA_PATH.open(encoding="utf-8") as f:
        items = json.load(f)
    log.info("total English items available: %d", len(items))

    subset = build_stratified_subset(items, target_seconds)
    if limit_items is not None:
        subset = subset[:limit_items]
        log.info("limit_items set: truncated subset to %d items (dry run)", len(subset))

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    log.info("device=%s", device)

    log.info("loading %s", WAVLM_MODEL_ID)
    feature_extractor = AutoFeatureExtractor.from_pretrained(WAVLM_MODEL_ID)
    model = WavLMModel.from_pretrained(WAVLM_MODEL_ID).to(device).eval()

    features_by_layer: dict[int, list[np.ndarray]] = {layer: [] for layer in CANDIDATE_LAYERS}
    labels: list[list[int]] = []

    start_time = time.monotonic()
    processed = 0
    skipped = 0
    for i, item in enumerate(subset):
        per_layer = extract_layer_features(model, feature_extractor, device, item, GTSINGER_SNAPSHOT)
        if per_layer is None:
            skipped += 1
            continue
        spans = phoneme_spans_s(item)
        for span_idx, (_, _, phoneme_idx) in enumerate(spans):
            labels.append([int(item[col][phoneme_idx]) for col in LABEL_COLUMNS])
            for layer in CANDIDATE_LAYERS:
                features_by_layer[layer].append(per_layer[layer][span_idx])
        processed += 1
        if (i + 1) % 25 == 0 or i + 1 == len(subset):
            elapsed = time.monotonic() - start_time
            log.info(
                "progress %d/%d items (processed=%d skipped=%d), %d phoneme spans so far, %.1fs elapsed",
                i + 1, len(subset), processed, skipped, len(labels), elapsed,
            )

    log.info("feature extraction done: %d phoneme spans from %d clips (%d skipped)", len(labels), processed, skipped)
    if len(labels) < 20:
        raise RuntimeError(f"only {len(labels)} phoneme spans collected — subset or audio paths are likely broken")

    return train_and_score(features_by_layer, labels)


def train_and_score(features_by_layer: dict[int, list[np.ndarray]], labels: list[list[int]]) -> dict:
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import f1_score
    from sklearn.model_selection import train_test_split
    from sklearn.preprocessing import StandardScaler

    y = np.asarray(labels, dtype=np.int64)
    label_rate = y.mean(axis=0)
    log.info("per-label positive rate: %s", dict(zip(LABEL_COLUMNS, label_rate.tolist())))

    results: dict[str, dict] = {}
    for layer in CANDIDATE_LAYERS:
        X = np.stack(features_by_layer[layer], axis=0)
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=0,
        )
        scaler = StandardScaler().fit(X_train)
        X_train = scaler.transform(X_train)
        X_test = scaler.transform(X_test)

        per_label_f1: dict[str, float] = {}
        for label_idx, label_name in enumerate(LABEL_COLUMNS):
            y_train_col = y_train[:, label_idx]
            y_test_col = y_test[:, label_idx]
            if y_train_col.min() == y_train_col.max():
                # Degenerate split (label never flips in this fold) — a
                # constant predictor scores 0, not a crash; flagged, not
                # silently skipped, since it changes how that layer's
                # macro-F1 should be read.
                per_label_f1[label_name] = 0.0
                log.warning("layer=%d label=%s has a single class in the train split", layer, label_name)
                continue
            clf = LogisticRegression(max_iter=2000, class_weight="balanced")
            clf.fit(X_train, y_train_col)
            pred = clf.predict(X_test)
            per_label_f1[label_name] = float(f1_score(y_test_col, pred, zero_division=0))

        macro_f1 = float(np.mean(list(per_label_f1.values())))
        results[str(layer)] = {"macro_f1": macro_f1, "per_label_f1": per_label_f1}
        log.info("layer=%d macro_f1=%.4f per_label=%s", layer, macro_f1, per_label_f1)

    return {
        "model": WAVLM_MODEL_ID,
        "candidate_layers": list(CANDIDATE_LAYERS),
        "num_phoneme_spans": int(y.shape[0]),
        "label_positive_rate": dict(zip(LABEL_COLUMNS, label_rate.tolist())),
        "results_by_layer": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run-items", type=int, default=None,
        help="Process only this many stratified items (smoke test before the full overnight run).",
    )
    parser.add_argument(
        "--target-seconds", type=float, default=TARGET_SUBSET_SECONDS,
        help="Target cumulative audio duration for the stratified subset, in seconds.",
    )
    args = parser.parse_args()

    output = run_probe(limit_items=args.dry_run_items, target_seconds=args.target_seconds)

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(output, indent=2), encoding="utf-8")
    log.info("wrote %s", RESULTS_PATH)

    ranked = sorted(output["results_by_layer"].items(), key=lambda kv: kv[1]["macro_f1"], reverse=True)
    log.info("layers ranked by macro-F1: %s", [(layer, round(res["macro_f1"], 4)) for layer, res in ranked])
    return 0


if __name__ == "__main__":
    sys.exit(main())
