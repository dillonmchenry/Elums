"""W1 (Wed Oct 7, IMPLEMENTATION_PLAN_2026-10-07.md): sweeps RMVPE's
`thred` parameter (0.01 / 0.03 / 0.05) over real songs' vocal stems,
comparing `voiced_frame_ratio` against RMS-VAD's own
`voiced_duration_s / duration_s` for the same song — Day 4's finding was
a systematic ~-0.11 gap at the default 0.03 across all 8 validated
songs. Run INSIDE the gpu-worker container (needs torch + the RMVPE
checkpoint):

    docker compose exec gpu-worker python scripts/thred_sweep.py <song_id> [<song_id> ...]

No pipeline change — this is an offline read, never called from
elums/ingest/tasks.py.
"""

from __future__ import annotations

import sys

import librosa
import numpy as np
import psycopg

from elums.config import settings
from elums.blobs.store import LocalBlobStore
from elums.vendor.rmvpe.model import RMVPE

DB_DSN = settings.database_url.replace("+psycopg", "")
THREDS = (0.01, 0.03, 0.05)


def main() -> int:
    song_ids = sys.argv[1:]
    if not song_ids:
        print("usage: thred_sweep.py <song_id> [<song_id> ...]", file=sys.stderr)
        return 1

    blob_store = LocalBlobStore(settings.blob_root)
    rows = []
    with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
        for song_id in song_ids:
            cur.execute(
                """
                SELECT s.title, st.blob_sha256, sa.voiced_duration_s
                FROM songs s
                JOIN stems st ON st.song_id = s.id AND st.kind = 'VOCALS'
                JOIN song_analyses sa ON sa.song_id = s.id
                WHERE s.id = %s
                """,
                (song_id,),
            )
            row = cur.fetchone()
            if row is None:
                print(f"song {song_id}: no vocal stem / analysis found, skipping", file=sys.stderr)
                continue
            rows.append((song_id, *row))

    rmvpe = RMVPE(str(settings.model_root / "rmvpe.pt"), device="cuda" if __import__("torch").cuda.is_available() else "cpu")

    print(f"{'song':30s} {'vad_ratio':>10s} " + " ".join(f"thred={t:<6}" for t in THREDS))
    for song_id, title, vocals_sha, voiced_duration_s in rows:
        path = blob_store.local_path(vocals_sha)
        audio, _sr = librosa.load(str(path), sr=16000, mono=True)
        duration_s = audio.shape[0] / 16000.0
        vad_ratio = (voiced_duration_s / duration_s) if duration_s else None

        results = {}
        for thred in THREDS:
            f0_hz, _confidence = rmvpe.infer_from_audio(audio, thred=thred)
            ratio = float(np.count_nonzero(f0_hz) / f0_hz.size) if f0_hz.size else 0.0
            results[thred] = ratio

        vad_str = f"{vad_ratio:.3f}" if vad_ratio is not None else "?"
        print(f"{title[:30]:30s} {vad_str:>10s} " + " ".join(f"{results[t]:.3f}       " for t in THREDS))
        for thred in THREDS:
            gap = results[thred] - (vad_ratio or 0.0)
            print(f"    thred={thred}: ratio={results[thred]:.3f}, gap vs VAD={gap:+.3f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
