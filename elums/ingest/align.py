"""CTC character/word alignment — Mon Oct 5 (L2 of
IMPLEMENTATION_PLAN_2026-10-05.md). DB-free and blocking; called via
`asyncio.to_thread` from elums/ingest/tasks.py, same shape as
elums/ingest/structure.py and elums/ingest/lyrics.py.

EC-1's resolution (PROGRESS.md Day 3): wav2vec2 CTC emissions via
`torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H`, Viterbi forced alignment
via `torchaudio.functional.forced_align` against the normalized
transcript — the same algorithm WhisperX's own aligner uses internally
(char-level spans first, word collapse second), not a redesign. This is
the architecture the plan's L2 section describes directly; no whisperx
import exists anywhere in this codebase.

**Interface frozen per the plan's own instruction** — Tuesday's note grid
consumes `WordSpan.char_spans` directly:
    CharSpan(char, start_s, end_s, score) -> WordSpan(text, start_s, end_s, char_spans, score)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Forced alignment is O(frames x tokens); aligning per VAD segment (not
# over the whole track) bounds both memory and the risk of mis-locking
# across long instrumental gaps — §2 of the Oct 5 plan.
_SAMPLE_RATE = 16_000
_NON_VOCAB_RE = re.compile(r"[^A-Z' ]+")


class AlignmentError(Exception):
    """A segment's transcript produced zero usable characters after
    normalization (e.g. it was pure punctuation/digits), or forced
    alignment itself raised. Callers skip the segment rather than fail
    the whole stage — one bad segment should not lose the rest of a
    song's alignment."""


@dataclass(frozen=True)
class CharSpan:
    char: str
    start_s: float
    end_s: float
    score: float


@dataclass(frozen=True)
class WordSpan:
    text: str
    start_s: float
    end_s: float
    char_spans: list[CharSpan]
    score: float


def normalize_for_ctc(text: str) -> str:
    """Uppercase, punctuation stripped, single spaces collapsed — the CTC
    vocabulary (WAV2VEC2_ASR_BASE_960H's labels) is letters, apostrophe,
    and `|` as the word separator; nothing else is representable."""
    upper = text.upper()
    stripped = _NON_VOCAB_RE.sub(" ", upper)
    return " ".join(stripped.split())


class CtcAligner:
    """Loads the wav2vec2 CTC model once; `align_segment` is called once
    per VAD segment so the model load cost (not the per-segment forward
    pass) is amortized across a song, mirroring transcribe_segments'
    single-load-many-segments shape in elums/ingest/lyrics.py."""

    def __init__(self, model_root) -> None:  # noqa: ANN001 — Path, kept untyped to avoid importing it twice
        import os

        os.environ.setdefault("HF_HOME", str(model_root / "hf-cache"))

        import torch
        from torchaudio.pipelines import WAV2VEC2_ASR_BASE_960H

        torch.hub.set_dir(str(model_root / "torch-cache"))

        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        self._bundle = WAV2VEC2_ASR_BASE_960H
        self._model = self._bundle.get_model().to(self._device)
        self._model.eval()
        self._labels = self._bundle.get_labels()
        self._label_to_index = {label: i for i, label in enumerate(self._labels)}

    def align_segment(self, waveform, text: str, offset_s: float) -> list[WordSpan]:  # noqa: ANN001
        """`waveform`: 1D float tensor at `_SAMPLE_RATE`, already sliced to
        this VAD segment. `offset_s`: the segment's own absolute start_s
        in the song, added back so every returned timestamp is absolute
        song time (never segment-relative)."""
        import torch
        import torchaudio

        normalized = normalize_for_ctc(text)
        if not normalized:
            raise AlignmentError("transcript has no CTC-representable characters")

        # Word separator is the literal `|` token in the vocab, not a
        # plain space — the model was trained with `|` as its inter-word
        # symbol (torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H.get_labels()
        # confirms index 1 is `|`, not a space character).
        chars = list(normalized.replace(" ", "|"))
        try:
            token_ids = [self._label_to_index[c] for c in chars]
        except KeyError as exc:
            raise AlignmentError(f"character not in CTC vocabulary: {exc}") from exc

        with torch.inference_mode():
            input_values = waveform.unsqueeze(0).to(self._device)
            emission, _ = self._model(input_values)

            targets = torch.tensor([token_ids], dtype=torch.int32, device=self._device)
            aligned_tokens, alignment_scores = torchaudio.functional.forced_align(
                emission, targets, blank=0
            )
            token_spans = torchaudio.functional.merge_tokens(
                aligned_tokens[0], alignment_scores[0]
            )

        num_frames = emission.size(1)
        ratio = waveform.size(0) / num_frames / _SAMPLE_RATE  # seconds per emission frame

        if len(token_spans) != len(chars):
            # Should not happen (forced alignment is 1:1 with the target
            # sequence by construction) — guarded explicitly rather than
            # silently mis-indexing into `chars` below.
            raise AlignmentError(
                f"token span count {len(token_spans)} != transcript length {len(chars)}"
            )

        char_spans: list[CharSpan] = []
        for char, span in zip(chars, token_spans):
            char_spans.append(
                CharSpan(
                    char=char,
                    start_s=offset_s + span.start * ratio,
                    end_s=offset_s + span.end * ratio,
                    score=float(span.score),
                )
            )

        return _collapse_words(char_spans)


def _collapse_words(char_spans: list[CharSpan]) -> list[WordSpan]:
    """Splits on the `|` word-separator char — never splits a word evenly
    in time (the specific UltraSinger failure §3 of the plan calls out);
    every boundary comes straight from the CTC alignment itself."""
    words: list[WordSpan] = []
    current: list[CharSpan] = []

    def _flush() -> None:
        if not current:
            return
        text = "".join(c.char for c in current)
        scores = [c.score for c in current]
        words.append(
            WordSpan(
                text=text,
                start_s=current[0].start_s,
                end_s=current[-1].end_s,
                char_spans=list(current),
                score=sum(scores) / len(scores),
            )
        )

    for char_span in char_spans:
        if char_span.char == "|":
            _flush()
            current = []
        else:
            current.append(char_span)
    _flush()

    return words


def align_chars(vocals_path: str, segments: list[tuple[float, float, str]], model_root) -> list[WordSpan]:  # noqa: ANN001
    """`segments`: (start_s, end_s, text) triples — the VAD segment
    boundaries paired with whichever source (LRCLIB line(s) or Whisper
    transcript) won for that span. Loads the vocal stem once, aligns each
    segment independently against its own slice, and returns every
    segment's words concatenated in song order."""
    import librosa
    import torch

    y, _sr = librosa.load(vocals_path, sr=_SAMPLE_RATE, mono=True)
    waveform_full = torch.from_numpy(y).float()

    aligner = CtcAligner(model_root)

    all_words: list[WordSpan] = []
    for start_s, end_s, text in segments:
        start_sample = int(start_s * _SAMPLE_RATE)
        end_sample = int(end_s * _SAMPLE_RATE)
        segment_waveform = waveform_full[start_sample:end_sample]
        if segment_waveform.numel() == 0:
            continue
        try:
            words = aligner.align_segment(segment_waveform, text, offset_s=start_s)
        except (AlignmentError, RuntimeError):
            # RuntimeError: torchaudio's native forced_align_impl raises a
            # C++-level error (not an AlignmentError) when the transcript
            # is longer than the segment has emission frames for — hit
            # directly on a short/near-silent clip where Whisper
            # hallucinated more words than the audio could possibly fit
            # (the approach document's documented hallucination failure
            # mode, §5). One bad segment doesn't lose the rest of the song.
            continue
        all_words.extend(words)

    return all_words
