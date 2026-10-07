import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import WaveSurfer from "wavesurfer.js";
import { getSongBundleApiSongsSongIdGet } from "../client";
import type { SongBundlePublic } from "../client";
import { PitchLane } from "../components/PitchLane";

// Tue Oct 6 (T4 of IMPLEMENTATION_PLAN_2026-10-06.md): the karaoke
// playback page — press play, hear the instrumental, watch lyrics scroll
// in time, see the note grid as a static lane. This is the "playable
// chart" half of M1; the 60fps Canvas pitch lane with a live performance
// overlay is Wednesday's work, not an extension of this scaffolding.

type ChartSyllable = { text: string; start_s: number; end_s: number };
type ChartWord = { text: string; start_s: number; end_s: number; syllables: ChartSyllable[] };
type ChartNote = {
  start_s: number;
  end_s: number;
  midi: number;
  midi_raw: number;
  confidence: number;
  is_vocable: boolean;
};
type Chart = {
  duration_s: number;
  bpm: number | null;
  words: ChartWord[];
  notes: ChartNote[];
};
type Peaks = { buckets: number; min: number[]; max: number[] };

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; bundle: SongBundlePublic; chart: Chart; peaks: Peaks | null };

async function fetchBlobJson<T>(sha256: string): Promise<T> {
  const res = await fetch(`/blobs/${sha256.slice(0, 2)}/${sha256.slice(2, 4)}/${sha256}`);
  if (!res.ok) throw new Error(`blob fetch failed: ${res.status}`);
  return (await res.json()) as T;
}

function LyricsView({ chart, currentTimeS }: { chart: Chart; currentTimeS: number }) {
  // Active-syllable highlight driven by the media element's currentTime
  // in a requestAnimationFrame loop (see SongPage's effect below) — never
  // re-rendering the whole word list on every animation frame, just the
  // highlighted index, since React's own diffing handles the rest cheaply
  // enough at this word count (tens to low hundreds per song).
  return (
    <p data-testid="lyrics-view">
      {chart.words.map((word, wi) => (
        <span key={wi}>
          {word.syllables.map((syl, si) => {
            const active = currentTimeS >= syl.start_s && currentTimeS < syl.end_s;
            return (
              <span
                key={si}
                data-testid="syllable"
                style={active ? { fontWeight: "bold", textDecoration: "underline" } : undefined}
              >
                {syl.text.toLowerCase()}
              </span>
            );
          })}{" "}
        </span>
      ))}
    </p>
  );
}

export function SongPage() {
  const { id } = useParams<{ id: string }>();
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [currentTimeS, setCurrentTimeS] = useState(0);
  // Shared with NoteLane below so the two timelines render at the same
  // pixels-per-second scale — previously the note lane was hardcoded to
  // 800px while the waveform filled its container's actual width (near
  // 1126px per index.css's `#root`), so a note's x-position could not
  // line up with the same timestamp on the waveform at all. Found during
  // the Day 5 MA-1 listening spot-check: onset-accuracy judgment is
  // unreliable if the two lanes are drawn to different scales.
  const [laneWidth, setLaneWidth] = useState(800);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const waveSurferRef = useRef<WaveSurfer | null>(null);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;

    (async () => {
      const { data, error } = await getSongBundleApiSongsSongIdGet({ path: { song_id: id } });
      if (error || !data) {
        if (!cancelled) setState({ kind: "error", message: "Song not found or not ready yet." });
        return;
      }
      if (!data.chart_blob_sha256 || !data.instrumental_blob_sha256) {
        if (!cancelled) setState({ kind: "error", message: "Ingest hasn't produced a chart yet." });
        return;
      }
      try {
        const chart = await fetchBlobJson<Chart>(data.chart_blob_sha256);
        const peaks = data.peaks_blob_sha256 ? await fetchBlobJson<Peaks>(data.peaks_blob_sha256) : null;
        if (!cancelled) setState({ kind: "ready", bundle: data, chart, peaks });
      } catch (err) {
        if (!cancelled) setState({ kind: "error", message: String(err) });
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [id]);

  useEffect(() => {
    if (state.kind !== "ready" || !containerRef.current) return;
    // Measures the waveform container's actual rendered width and keeps
    // NoteLane in lockstep with it (ResizeObserver, not just a one-shot
    // read) so the two lanes stay pixel-for-pixel aligned across window
    // resizes too, not just on first paint.
    const observer = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width;
      if (width && width > 0) setLaneWidth(width);
    });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, [state.kind]);

  useEffect(() => {
    if (state.kind !== "ready" || !containerRef.current) return;

    // Interleaved min/max per bucket, flattened into one channel array —
    // EC-3's resolution: Python-computed peaks stand in for
    // `audiowaveform`'s own JSON format, which wavesurfer's `peaks`
    // option accepts the same way (one flat per-channel amplitude array).
    const peaksChannel = state.peaks
      ? Float32Array.from(state.peaks.min.flatMap((min, i) => [min, state.peaks!.max[i]]))
      : undefined;

    const ws = WaveSurfer.create({
      container: containerRef.current,
      url: `/blobs/${state.bundle.instrumental_blob_sha256!.slice(0, 2)}/${state.bundle.instrumental_blob_sha256!.slice(2, 4)}/${state.bundle.instrumental_blob_sha256}`,
      peaks: peaksChannel ? [peaksChannel] : undefined,
      duration: state.chart.duration_s,
      waveColor: "#9bb8e8",
      progressColor: "#2d6cdf",
      height: 80,
    });
    waveSurferRef.current = ws;

    const tick = () => {
      setCurrentTimeS(ws.getCurrentTime());
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);

    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      ws.destroy();
      waveSurferRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.kind === "ready" ? state.bundle.id : null]);

  if (state.kind === "loading") return <p>Loading…</p>;
  if (state.kind === "error") return <p role="alert">{state.message}</p>;

  return (
    <main>
      <h1>{state.bundle.title}</h1>
      {state.bundle.artist && <p>{state.bundle.artist}</p>}

      <div ref={containerRef} data-testid="waveform" />
      <button type="button" onClick={() => waveSurferRef.current?.playPause()}>
        Play / pause
      </button>
      <Link to={`/songs/${state.bundle.id}/sing`}>Sing this</Link>

      {/* Wed Oct 7 (W5): Canvas pitch lane, replacing the static SVG
          NoteLane — "replaced, not extended" per the plan's own
          instruction. */}
      <PitchLane notes={state.chart.notes} durationS={state.chart.duration_s} width={laneWidth} currentTimeS={currentTimeS} />
      <LyricsView chart={state.chart} currentTimeS={currentTimeS} />
    </main>
  );
}
