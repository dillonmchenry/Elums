import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import {
  getPerformanceApiPerformancesPerformanceIdGet,
  getSongBundleApiSongsSongIdGet,
  listSeedsApiSongsSongIdSeedsGet,
  publishSeedApiPerformancesPerformanceIdPublishSeedPost,
} from "../client";
import type { PerformancePublic } from "../client";
import { PitchLane } from "../components/PitchLane";

// Wed Oct 7 (W5/W6 of IMPLEMENTATION_PLAN_2026-10-07.md): a single
// take's results — overall score, per-note coloring against §6.2's
// bands via the server-persisted analysis blob, and "publish as a
// seed" (§7.3's async seed/join, taken by a plain POST once scoring has
// succeeded).

type ChartNote = { start_s: number; end_s: number; midi: number; is_vocable: boolean };
type Chart = { duration_s: number; notes: ChartNote[] };
type NoteScore = { note_index: number; pct_in_tune: number | null };

const POLL_INTERVAL_MS = 2000;

async function fetchBlobJson<T>(sha256: string): Promise<T> {
  const res = await fetch(`/blobs/${sha256.slice(0, 2)}/${sha256.slice(2, 4)}/${sha256}`);
  if (!res.ok) throw new Error(`blob fetch failed: ${res.status}`);
  return (await res.json()) as T;
}

export function PerformancePage() {
  const { id } = useParams<{ id: string }>();
  const [performance, setPerformance] = useState<PerformancePublic | null>(null);
  const [chart, setChart] = useState<Chart | null>(null);
  const [noteScores, setNoteScores] = useState<NoteScore[] | null>(null);
  const [seedCount, setSeedCount] = useState<number | null>(null);
  const [published, setPublished] = useState(false);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const poll = async () => {
      const { data, error } = await getPerformanceApiPerformancesPerformanceIdGet({
        path: { performance_id: id },
      });
      if (cancelled) return;
      if (!error && data) {
        setPerformance(data);
        if (data.status !== "succeeded" && data.status !== "failed") {
          timer = setTimeout(poll, POLL_INTERVAL_MS);
        } else if (data.status === "succeeded") {
          const bundleResp = await getSongBundleApiSongsSongIdGet({ path: { song_id: data.song_id } });
          if (bundleResp.data?.chart_blob_sha256) {
            const chartData = await fetchBlobJson<Chart>(bundleResp.data.chart_blob_sha256);
            if (!cancelled) setChart(chartData);
          }
          if (data.analysis_blob_sha256) {
            const analysis = await fetchBlobJson<{ notes: NoteScore[] }>(data.analysis_blob_sha256);
            if (!cancelled) setNoteScores(analysis.notes);
          }
          const seeds = await listSeedsApiSongsSongIdSeedsGet({ path: { song_id: data.song_id } });
          if (!cancelled && seeds.data) setSeedCount(seeds.data.length);
        }
      }
    };
    void poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [id]);

  async function handlePublish() {
    if (!id) return;
    const { data } = await publishSeedApiPerformancesPerformanceIdPublishSeedPost({
      path: { performance_id: id },
    });
    if (data) {
      setPerformance(data);
      setPublished(true);
    }
  }

  if (!performance) return <p>Loading…</p>;

  return (
    <main>
      <h1>Performance results</h1>
      <p>Status: {performance.status}</p>
      {performance.error_message && <p role="alert">{performance.error_message}</p>}

      {performance.status === "succeeded" && (
        <section data-testid="performance-results">
          <p>
            Overall score: <strong>{((performance.score_overall ?? 0) * 100).toFixed(1)}%</strong>
          </p>
          <p>In tune: {((performance.pct_in_tune ?? 0) * 100).toFixed(1)}%</p>
          {performance.octave_shift_semitones !== 0 && (
            <p>Octave shift detected: {performance.octave_shift_semitones} semitones</p>
          )}
          {performance.alignment_warning && (
            <p role="alert" data-testid="alignment-warning">
              We couldn't confidently align this take to the chart — the score above may not be reliable.
            </p>
          )}

          {chart && (
            <PitchLane notes={chart.notes} durationS={chart.duration_s} width={800} scores={noteScores ?? undefined} />
          )}

          {performance.kind === "solo" && !published && (
            <button type="button" onClick={handlePublish}>
              Publish as a joinable seed
            </button>
          )}
          {performance.kind === "seed" && <p>This take is published as a seed.</p>}
          {seedCount !== null && <p>{seedCount} seed performance(s) exist for this song.</p>}
        </section>
      )}
    </main>
  );
}
