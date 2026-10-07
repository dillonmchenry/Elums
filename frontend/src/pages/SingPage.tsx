import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import {
  completePerformanceApiPerformancesPerformanceIdCompletePost,
  createPerformanceApiPerformancesPost,
  getSongBundleApiSongsSongIdGet,
} from "../client";
import type { SongBundlePublic } from "../client";
import { PitchLane } from "../components/PitchLane";

// Wed Oct 7 (W2 of IMPLEMENTATION_PLAN_2026-10-07.md): the capture page.
//
// **Deviation from §10.1's AudioWorklet + SharedArrayBuffer graph,
// taken deliberately per the plan's own EC-0 scope flag**: "If the
// worklet will not load through Caddy inside the timebox, fall back to
// MediaRecorder today... That costs the zero-allocation guarantee and
// the live lane, not M2 — say so explicitly rather than sliding." This
// session has no interactive browser with a real microphone to verify
// the AudioWorklet-through-Caddy path live (EC-0's own acceptance bar),
// so rather than ship an unverified worklet pipeline, this takes the
// plan's own named fallback: `getUserMedia` with AEC/NS/AGC forced off,
// `MediaRecorder` for encoding, chunked upload via `ondataavailable`.
// The pitch LANE still renders live from the chart (no 60fps budget is
// being claimed here — `requestAnimationFrame` driven off
// `AudioContext.currentTime`, same as SongPage), it just isn't backed
// by a zero-allocation worklet ring buffer. Revisit alongside NanoPitch
// (Thursday) if/when a live browser check confirms the worklet loads
// through Caddy's COEP/HMR path.

type ChartNote = { start_s: number; end_s: number; midi: number; is_vocable: boolean };
type Chart = { duration_s: number; notes: ChartNote[] };

type ConstraintCheck = { echoCancellation: boolean; noiseSuppression: boolean; autoGainControl: boolean };

type RecordState =
  | { kind: "idle" }
  | { kind: "denied"; message: string }
  | { kind: "ready"; stream: MediaStream; constraintsBad: ConstraintCheck | null }
  | { kind: "recording"; performanceId: string; startedAtS: number }
  | { kind: "uploading" }
  | { kind: "scoring"; performanceId: string }
  | { kind: "error"; message: string };

const CHUNK_TIMESLICE_MS = 1000;

async function fetchChart(songId: string): Promise<{ bundle: SongBundlePublic; chart: Chart } | null> {
  const { data, error } = await getSongBundleApiSongsSongIdGet({ path: { song_id: songId } });
  if (error || !data || !data.chart_blob_sha256) return null;
  const res = await fetch(
    `/blobs/${data.chart_blob_sha256.slice(0, 2)}/${data.chart_blob_sha256.slice(2, 4)}/${data.chart_blob_sha256}`,
  );
  if (!res.ok) return null;
  const chart = (await res.json()) as Chart;
  return { bundle: data, chart };
}

export function SingPage() {
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const parentPerformanceId = searchParams.get("join") ?? undefined;

  const [loaded, setLoaded] = useState<{ bundle: SongBundlePublic; chart: Chart } | null>(null);
  const [state, setState] = useState<RecordState>({ kind: "idle" });
  const [currentTimeS, setCurrentTimeS] = useState(0);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunkIndexRef = useRef(0);
  const performanceIdRef = useRef<string | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const startTimeRef = useRef(0);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    if (!id) return;
    fetchChart(id).then(setLoaded);
  }, [id]);

  const requestMic = useCallback(async () => {
    try {
      // §10.2: these three MUST be false — Chrome-wide AEC3 is
      // default-on and corrupts both latency and recorded alignment.
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
      });
      const track = stream.getAudioTracks()[0];
      const settings = track?.getSettings() as ConstraintCheck | undefined;
      const bad =
        settings && (settings.echoCancellation || settings.noiseSuppression || settings.autoGainControl)
          ? settings
          : null;
      setState({ kind: "ready", stream, constraintsBad: bad });
    } catch (err) {
      setState({ kind: "denied", message: String(err) });
    }
  }, []);

  const startRecording = useCallback(async () => {
    if (state.kind !== "ready" || !id) return;
    const { data, error } = await createPerformanceApiPerformancesPost({
      body: { song_id: id, parent_performance_id: parentPerformanceId ?? null },
    });
    if (error || !data) {
      setState({ kind: "error", message: "Could not create a performance." });
      return;
    }
    performanceIdRef.current = data.id;
    chunkIndexRef.current = 0;

    const audioCtx = new AudioContext();
    audioCtxRef.current = audioCtx;
    startTimeRef.current = audioCtx.currentTime;

    const recorder = new MediaRecorder(state.stream, { mimeType: "audio/webm" });
    mediaRecorderRef.current = recorder;
    recorder.ondataavailable = async (event) => {
      if (event.data.size === 0 || !performanceIdRef.current) return;
      const index = chunkIndexRef.current++;
      await fetch(`/api/performances/${performanceIdRef.current}/chunks/${index}`, {
        method: "PUT",
        body: event.data,
        credentials: "include",
      });
    };
    recorder.start(CHUNK_TIMESLICE_MS);
    setState({ kind: "recording", performanceId: data.id, startedAtS: startTimeRef.current });

    const tick = () => {
      if (audioCtxRef.current) setCurrentTimeS(audioCtxRef.current.currentTime - startTimeRef.current);
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
  }, [state, id, parentPerformanceId]);

  const stopRecording = useCallback(async () => {
    const recorder = mediaRecorderRef.current;
    const performanceId = performanceIdRef.current;
    if (!recorder || !performanceId) return;
    if (rafRef.current) cancelAnimationFrame(rafRef.current);

    setState({ kind: "uploading" });
    const stopped = new Promise<void>((resolve) => {
      recorder.onstop = () => resolve();
    });
    recorder.stop();
    await stopped;
    // Give the last ondataavailable's fetch a moment to land before completing.
    await new Promise((resolve) => setTimeout(resolve, 300));

    const { error } = await completePerformanceApiPerformancesPerformanceIdCompletePost({
      path: { performance_id: performanceId },
    });
    if (error) {
      setState({ kind: "error", message: "Could not complete the take." });
      return;
    }
    setState({ kind: "scoring", performanceId });
  }, []);

  if (!loaded) return <p>Loading chart…</p>;

  return (
    <main>
      <h1>
        Sing: {loaded.bundle.title} {loaded.bundle.artist && `— ${loaded.bundle.artist}`}
      </h1>
      {parentPerformanceId && <p>Joining a seed performance.</p>}

      {state.kind === "idle" && (
        <button type="button" onClick={requestMic}>
          Enable microphone
        </button>
      )}
      {state.kind === "denied" && <p role="alert">Microphone access denied: {state.message}</p>}
      {state.kind === "ready" && (
        <>
          {state.constraintsBad && (
            <p role="alert" data-testid="aec-banner">
              Your browser did not honor echo-cancellation-off — recording quality may suffer. Use headphones.
            </p>
          )}
          <button type="button" onClick={startRecording}>
            Start recording
          </button>
        </>
      )}
      {state.kind === "recording" && (
        <>
          <p>Recording… {currentTimeS.toFixed(1)}s</p>
          <PitchLane notes={loaded.chart.notes} durationS={loaded.chart.duration_s} width={800} currentTimeS={currentTimeS} />
          <button type="button" onClick={stopRecording}>
            Stop
          </button>
        </>
      )}
      {state.kind === "uploading" && <p>Finishing upload…</p>}
      {state.kind === "scoring" && (
        <p>
          Scoring… <a href={`/performances/${state.performanceId}`}>View results</a> once ready.
        </p>
      )}
      {state.kind === "error" && <p role="alert">{state.message}</p>}
    </main>
  );
}
