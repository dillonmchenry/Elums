"""Lyrics source — Mon Oct 5 (L1 of IMPLEMENTATION_PLAN_2026-10-05.md).
DB-free and blocking (except `fetch_lrclib`'s one HTTP call), mirroring
elums/ingest/structure.py's shape: called from elums/ingest/tasks.py.

EC-1's resolution: the schedule names "WhisperX" for this stage, but
the "fallback" is what this module actually implements — see
PROGRESS.md Day 3 EC-1. `transformers` loads the HF-format
whisper-large-v3-turbo checkpoint already on disk directly; there is no
whisperx import anywhere in this codebase. Word/char-level alignment is
a separate stage (elums/ingest/align.py), not whisperx's bundled aligner.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

LRCLIB_BASE_URL = "https://lrclib.net/api/get"
# LRCLIB's own API etiquette asks for a descriptive User-Agent identifying
# the application (EC-4).
_USER_AGENT = "Elums/0.1 (karaoke lyric ingest; contact: dev@elums.local)"
_LRCLIB_TIMEOUT_S = 8

# §1's "thin LRCLIB result" thresholds — run Whisper anyway when LRCLIB's
# hit looks this sparse, rather than trusting any hit unconditionally.
MIN_LRCLIB_LINES = 4
MIN_LRCLIB_COVERAGE_FRACTION = 0.4

_TIMESTAMP_RE = re.compile(r"^\[(\d{2}):(\d{2})\.(\d{2,3})\](.*)$")


@dataclass(frozen=True)
class LrcLine:
    start_s: float
    text: str


@dataclass(frozen=True)
class LrcLines:
    lines: list[LrcLine]
    plain_lyrics: str | None  # unsynced fallback text LRCLIB also returns


@dataclass(frozen=True)
class SegmentText:
    start_s: float  # absolute song time — the VAD segment's own start_s
    end_s: float
    text: str


def _parse_synced_lyrics(synced_lyrics: str) -> list[LrcLine]:
    lines: list[LrcLine] = []
    for raw_line in synced_lyrics.splitlines():
        match = _TIMESTAMP_RE.match(raw_line.strip())
        if match is None:
            continue
        minutes, seconds, frac, text = match.groups()
        frac_s = float(f"0.{frac}") if len(frac) else 0.0
        start_s = int(minutes) * 60 + int(seconds) + frac_s
        text = text.strip()
        if text:
            lines.append(LrcLine(start_s=start_s, text=text))
    return lines


def fetch_lrclib(artist: str | None, title: str | None, duration_s: float) -> LrcLines | None:
    """One `GET lrclib.net/api/get`, per EC-4's finding. Returns None on
    any miss (404), any network failure, or missing artist/title — never
    raises, since "no LRCLIB text" is an expected, common outcome that
    falls straight through to Whisper, not an error condition."""
    if not artist or not title:
        return None

    params = {
        "artist_name": artist,
        "track_name": title,
        "duration": str(int(round(duration_s))),
    }
    url = f"{LRCLIB_BASE_URL}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})

    try:
        with urllib.request.urlopen(request, timeout=_LRCLIB_TIMEOUT_S) as response:
            import json

            payload = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError):
        return None

    synced = payload.get("syncedLyrics")
    plain = payload.get("plainLyrics")
    if not synced:
        return None  # instrumental-marked or sync-free entries carry no usable timing

    lines = _parse_synced_lyrics(synced)
    if not lines:
        return None

    return LrcLines(lines=lines, plain_lyrics=plain)


def map_lrclib_to_vad_segments(
    result: LrcLines, vad_segments: list[tuple[float, float]]
) -> list[SegmentText]:
    """L2 ("align per VAD segment, not over the whole track") needs a
    segment/text pairing regardless of which source won — LRCLIB's own
    line timestamps aren't VAD boundaries, so each VAD segment is given
    the concatenation of whichever LRCLIB lines fall inside it (by their
    own start_s). A segment with no line inside it is dropped (nothing
    to align there); a line whose start_s falls in a silence gap between
    segments is likewise dropped — VAD's own voiced/silent call is
    trusted over a lyric timestamp that may itself be a few hundred ms
    off (sync-tagged lyrics are hand-aligned to roughly that precision)."""
    out: list[SegmentText] = []
    for seg_start, seg_end in vad_segments:
        texts = [line.text for line in result.lines if seg_start <= line.start_s < seg_end]
        if texts:
            out.append(SegmentText(start_s=seg_start, end_s=seg_end, text=" ".join(texts)))
    return out


def lrclib_result_is_thin(result: LrcLines, voiced_duration_s: float) -> bool:
    """§1's "thin" test: fewer than MIN_LRCLIB_LINES lines, or covering
    under MIN_LRCLIB_COVERAGE_FRACTION of the song's own voiced duration
    (a crude but cheap proxy — real line *durations* aren't known until
    the next line's timestamp or the track's end, so coverage here is
    approximated as the span from the first to the last line divided by
    voiced duration, which is what the decision actually needs: "is this
    lyric sparse enough that Whisper is worth the extra ~30s of GPU?")."""
    if len(result.lines) < MIN_LRCLIB_LINES:
        return True
    if voiced_duration_s <= 0:
        return False
    span_s = result.lines[-1].start_s - result.lines[0].start_s
    return (span_s / voiced_duration_s) < MIN_LRCLIB_COVERAGE_FRACTION


# --- Whisper transcription ---------------------------------------------

_WHISPER_SAMPLE_RATE = 16_000


def transcribe_segments(vocals_path: str, segments: list[tuple[float, float]]) -> list[SegmentText]:
    """Batches `transformers`' whisper-large-v3-turbo over the VAD
    segments already persisted in the analysis blob — never re-run VAD
    (settled decision, §3 of the Oct 5 plan). Segment offsets are added
    back so every returned timestamp is absolute song time. Cross-segment
    conditioning is off: it is the documented hallucination-loop path,
    and batching over independent segments is the entire point (§5 of
    the approach document)."""
    import os

    from elums.config import settings

    os.environ.setdefault("HF_HOME", str(settings.model_root / "hf-cache"))

    import librosa
    import torch
    from transformers import WhisperForConditionalGeneration, WhisperProcessor

    model_path = str(settings.model_root / "whisper-large-v3-turbo")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32

    processor = WhisperProcessor.from_pretrained(model_path)
    model = WhisperForConditionalGeneration.from_pretrained(model_path, dtype=dtype).to(device)
    model.eval()

    y, _sr = librosa.load(vocals_path, sr=_WHISPER_SAMPLE_RATE, mono=True)

    results: list[SegmentText] = []
    for start_s, end_s in segments:
        start_sample = int(start_s * _WHISPER_SAMPLE_RATE)
        end_sample = int(end_s * _WHISPER_SAMPLE_RATE)
        clip = y[start_sample:end_sample]
        if clip.size == 0:
            continue

        inputs = processor(clip, sampling_rate=_WHISPER_SAMPLE_RATE, return_tensors="pt")
        input_features = inputs.input_features.to(device=device, dtype=dtype)

        with torch.no_grad():
            # language="en", no cross-segment conditioning: each segment
            # is transcribed independently (§5's documented hallucination
            # mitigation — batching over VAD boundaries, not a single
            # long-form pass).
            predicted_ids = model.generate(
                input_features,
                language="en",
                task="transcribe",
                condition_on_prev_tokens=False,
            )
        text = processor.batch_decode(predicted_ids, skip_special_tokens=True)[0].strip()
        if text:
            results.append(SegmentText(start_s=start_s, end_s=end_s, text=text))

    return results
