import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import {
  completePerformanceApiPerformancesPerformanceIdCompletePost,
  createPerformanceApiPerformancesPost,
  getSongBundleApiSongsSongIdGet,
} from "../client";
import type { SongBundlePublic } from "../client";
import { PitchLane } from "../components/PitchLane";
import { LatencyCalibration } from "../components/LatencyCalibration";
import { createAudioRingSab, createPitchRingSab, PitchRingReader } from "../audio/ring";
import { publishDiagnostic } from "../audio/diagnostics-channel";
import {
  detectCaptureTier,
  setAudioSessionAuto,
  setAudioSessionPlayAndRecord,
  teardownAudioSession,
  type CaptureTier,
} from "../audio/ios-session";
import captureWorkletUrl from "../audio/capture-worklet.ts?worker&url";

// Thu Oct 8 (X0/X1/X2/X3/X4 of IMPLEMENTATION_PLAN_2026-10-08.md): the
// real AudioWorklet + SharedArrayBuffer capture graph, replacing Day
// 5's deliberately-named `MediaRecorder` fallback (W2's own docstring,
// kept below verbatim as history). §10.1's graph:
//
//   getUserMedia (mic, EC/NS/AGC off) ----> inputs[0] \
//   backing track -> DelayNode(τ̂) --------> inputs[1]  } capture-processor (AEC)
//                  \-> destination (audible)           outputs[0] cleaned -> ring -> encodeWorker + pitchWorker
//                                                       outputs[1] raw     -> ring -> (client ERLE estimate only)
//
// X0's two gaps closed: the backing track is now actually decoded and
// played (`AudioBufferSourceNode -> destination`), and chunks are now
// real 16-bit PCM (`content_type="audio/wav"` is now true, not
// mislabeled WebM).
//
// Capture fallback ladder (X1): worklet -> MediaRecorder -> banner, so
// a WebKit refusal (or a browser with no SharedArrayBuffer/COEP) still
// records something rather than blanking. The MediaRecorder tier is
// Day 5's original implementation, kept verbatim as the fallback.
//
// NOT verified against a real microphone or a real iPad this session
// (no interactive browser-with-mic or iOS device available — see
// PROGRESS.md's Day 6 handoff for exactly what was and wasn't run).
// Builds clean (`tsc -b`), and the worklet-loads-through-Caddy part of
// EC-0 (no mic needed for that check) was verified live.

type ChartNote = { start_s: number; end_s: number; midi: number; is_vocable: boolean };
type Chart = { duration_s: number; notes: ChartNote[] };

type ConstraintCheck = { echoCancellation: boolean; noiseSuppression: boolean; autoGainControl: boolean };

type RecordState =
  | { kind: "idle" }
  | { kind: "denied"; message: string }
  | { kind: "ready"; stream: MediaStream; constraintsBad: ConstraintCheck | null; tier: CaptureTier }
  | { kind: "calibrating"; stream: MediaStream; audioContext: AudioContext }
  | { kind: "armed"; stream: MediaStream; audioContext: AudioContext; latencyOffsetMs: number | null }
  | { kind: "recording"; performanceId: string }
  | { kind: "uploading" }
  | { kind: "scoring"; performanceId: string }
  | { kind: "error"; message: string };

const CHUNK_TIMESLICE_MS = 1000;
const COUNT_IN_MS = 3000; // AEC adapts during this window, then freezes for the take (§10.3)
const MAX_OVERLAY_POINTS = 4000; // preallocated — the whole point of X2's "ref, not React state per point" note

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

function blobUrl(sha256: string): string {
  return `/blobs/${sha256.slice(0, 2)}/${sha256.slice(2, 4)}/${sha256}`;
}

export function SingPage() {
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const parentPerformanceId = searchParams.get("join") ?? undefined;

  const [loaded, setLoaded] = useState<{ bundle: SongBundlePublic; chart: Chart } | null>(null);
  const [state, setState] = useState<RecordState>({ kind: "idle" });
  const [currentTimeS, setCurrentTimeS] = useState(0);
  const [overlaySnapshot, setOverlaySnapshot] = useState<{ t_s: number; midi: number }[]>([]);

  // Preallocated circular buffer, written by the rAF loop draining the
  // pitch ring — never reallocated per point (X2's "one performance
  // trap" note). `overlaySnapshot` above is a periodic, throttled
  // shallow copy for PitchLane's prop, not a per-point allocation.
  const overlayBufRef = useRef<{ t_s: number; midi: number }[]>(
    Array.from({ length: MAX_OVERLAY_POINTS }, () => ({ t_s: 0, midi: 0 })),
  );
  const overlayWriteIdxRef = useRef(0);
  const overlayCountRef = useRef(0);

  const performanceIdRef = useRef<string | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const startTimeRef = useRef(0);
  const rafRef = useRef<number | null>(null);
  const pitchRingReaderRef = useRef<PitchRingReader | null>(null);
  const pitchWorkerRef = useRef<Worker | null>(null);
  const encodeWorkerRef = useRef<Worker | null>(null);
  const captureNodeRef = useRef<AudioWorkletNode | null>(null);
  const backingSourceRef = useRef<AudioBufferSourceNode | null>(null);

  // MediaRecorder fallback tier state (X1's ladder, Day 5's original path).
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunkIndexRef = useRef(0);

  useEffect(() => {
    if (!id) return;
    fetchChart(id).then(setLoaded);
  }, [id]);

  const requestMic = useCallback(async () => {
    try {
      setAudioSessionAuto(); // X1/§10.4: before getUserMedia
      // §10.2: these three MUST be false — Chrome-wide AEC3 is
      // default-on and corrupts both latency and recorded alignment.
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
      });
      setAudioSessionPlayAndRecord(); // X1/§10.4: immediately after getUserMedia
      const track = stream.getAudioTracks()[0];
      const settings = track?.getSettings() as ConstraintCheck | undefined;
      const bad =
        settings && (settings.echoCancellation || settings.noiseSuppression || settings.autoGainControl)
          ? settings
          : null;
      const tier = detectCaptureTier();
      setState({ kind: "ready", stream, constraintsBad: bad, tier });
    } catch (err) {
      setState({ kind: "denied", message: String(err) });
    }
  }, []);

  const proceedToCalibration = useCallback(() => {
    if (state.kind !== "ready") return;
    const audioContext = new AudioContext({ latencyHint: 0 });
    setState({ kind: "calibrating", stream: state.stream, audioContext });
  }, [state]);

  const onCalibrated = useCallback((offsetMs: number) => {
    publishDiagnostic({ latencyOffsetMs: offsetMs, latencyReliable: true });
    setState((prev) => {
      if (prev.kind !== "calibrating") return prev;
      return { kind: "armed", stream: prev.stream, audioContext: prev.audioContext, latencyOffsetMs: offsetMs };
    });
  }, []);

  const skipCalibration = useCallback(() => {
    setState((prev) => {
      if (prev.kind !== "calibrating") return prev;
      return { kind: "armed", stream: prev.stream, audioContext: prev.audioContext, latencyOffsetMs: null };
    });
  }, []);

  const pushOverlayPoint = useCallback((tS: number, midi: number) => {
    const buf = overlayBufRef.current;
    buf[overlayWriteIdxRef.current] = { t_s: tS, midi };
    overlayWriteIdxRef.current = (overlayWriteIdxRef.current + 1) % MAX_OVERLAY_POINTS;
    overlayCountRef.current = Math.min(overlayCountRef.current + 1, MAX_OVERLAY_POINTS);
  }, []);

  const startRecordingWorklet = useCallback(
    async (audioContext: AudioContext, stream: MediaStream, latencyOffsetMs: number | null) => {
      if (!id) return;
      const { data, error } = await createPerformanceApiPerformancesPost({
        body: {
          song_id: id,
          parent_performance_id: parentPerformanceId ?? null,
          latency_offset_ms: latencyOffsetMs,
        },
      });
      if (error || !data) {
        setState({ kind: "error", message: "Could not create a performance." });
        return;
      }
      performanceIdRef.current = data.id;
      audioCtxRef.current = audioContext;
      startTimeRef.current = audioContext.currentTime;

      await audioContext.audioWorklet.addModule(captureWorkletUrl);

      // Two separate cleaned-signal rings, one per consumer — the
      // worklet's SAB ring is SPSC, see capture-worklet.ts's header note.
      const cleanedForEncodeRingSab = createAudioRingSab();
      const cleanedForPitchRingSab = createAudioRingSab();
      const rawRingSab = createAudioRingSab();
      const pitchRingSab = createPitchRingSab();

      const micSource = audioContext.createMediaStreamSource(stream);
      const node = new AudioWorkletNode(audioContext, "capture-processor", {
        numberOfInputs: 2,
        numberOfOutputs: 2,
        outputChannelCount: [1, 1],
        processorOptions: { cleanedForEncodeRingSab, cleanedForPitchRingSab, rawRingSab },
      });
      captureNodeRef.current = node;
      micSource.connect(node, 0, 0);
      // A disconnected-output AudioWorkletNode is NOT guaranteed to
      // have `process()` called at all — Web Audio only pulls nodes
      // reachable from a destination. The two outputs here are never
      // meant to be heard (the real "outputs" are the SAB rings
      // written as a side effect inside `process()`), but the node
      // still needs a live path to `destination` to be scheduled.
      // Route it through a zero-gain node so nothing is audible.
      const keepAliveGain = audioContext.createGain();
      keepAliveGain.gain.value = 0;
      node.connect(keepAliveGain, 0).connect(audioContext.destination);

      // Backing track: decoded and actually played this time (X0's own
      // "never played the backing track" gap), and routed through a
      // DelayNode set from X3's measured round-trip latency as the
      // AEC reference (§10.1 — the reference must arrive on the SAME
      // audio-thread tick as the mic for sample-accurate subtraction).
      if (loaded?.bundle.instrumental_blob_sha256) {
        const res = await fetch(blobUrl(loaded.bundle.instrumental_blob_sha256));
        const arrayBuf = await res.arrayBuffer();
        const audioBuffer = await audioContext.decodeAudioData(arrayBuf);
        const source = audioContext.createBufferSource();
        source.buffer = audioBuffer;
        backingSourceRef.current = source;

        const monitorGain = audioContext.createGain();
        source.connect(monitorGain).connect(audioContext.destination);

        const delay = audioContext.createDelay(1.0);
        delay.delayTime.value = latencyOffsetMs !== null ? latencyOffsetMs / 1000 : 0;
        source.connect(delay);
        delay.connect(node, 0, 1);

        source.start();
      }

      pitchWorkerRef.current = new Worker(new URL("../audio/pitchWorker.ts", import.meta.url), { type: "module" });
      pitchWorkerRef.current.postMessage({
        type: "init",
        cleanedRingSab: cleanedForPitchRingSab,
        pitchRingSab,
        weightsUrl: "/nanopitch/weights.bin",
        deviceSampleRate: audioContext.sampleRate,
        recordingStartTimeS: 0,
      });
      pitchWorkerRef.current.onmessage = (e: MessageEvent<{ type: string; rtf?: number }>) => {
        if (e.data.type === "rtf" && typeof e.data.rtf === "number") {
          publishDiagnostic({ rtf: e.data.rtf });
        }
      };
      pitchRingReaderRef.current = new PitchRingReader(pitchRingSab);

      encodeWorkerRef.current = new Worker(new URL("../audio/encodeWorker.ts", import.meta.url), { type: "module" });
      encodeWorkerRef.current.postMessage({
        type: "init",
        cleanedRingSab: cleanedForEncodeRingSab,
        rawRingSab,
        performanceId: data.id,
        deviceSampleRate: audioContext.sampleRate,
        chunkDurationMs: CHUNK_TIMESLICE_MS,
      });
      encodeWorkerRef.current.onmessage = (e: MessageEvent<{ type: string; erleDb?: number }>) => {
        if (e.data.type === "erle" && typeof e.data.erleDb === "number") {
          publishDiagnostic({ erleDb: e.data.erleDb });
        }
      };

      // AEC adapt-during-count-in-then-freeze (§10.3).
      setTimeout(() => node.port.postMessage({ type: "freeze-aec" }), COUNT_IN_MS);

      setState({ kind: "recording", performanceId: data.id });

      const tick = () => {
        if (audioCtxRef.current) setCurrentTimeS(audioCtxRef.current.currentTime - startTimeRef.current);
        pitchRingReaderRef.current?.drain(pushOverlayPoint);
        rafRef.current = requestAnimationFrame(tick);
      };
      rafRef.current = requestAnimationFrame(tick);

      // Periodic (not per-point) overlay snapshot for PitchLane's
      // prop — throttled well below the per-frame rate so the React
      // re-render cost stays far from the 100x/s hazard X2 calls out.
      const snapshotInterval = setInterval(() => {
        const count = overlayCountRef.current;
        const buf = overlayBufRef.current;
        const start = (overlayWriteIdxRef.current - count + MAX_OVERLAY_POINTS) % MAX_OVERLAY_POINTS;
        const snapshot: { t_s: number; midi: number }[] = [];
        for (let i = 0; i < count; i++) snapshot.push(buf[(start + i) % MAX_OVERLAY_POINTS]);
        setOverlaySnapshot(snapshot);
      }, 150);
      // Cleared on stop via stopRecordingWorklet's own cleanup below.
      (node as unknown as { __snapshotInterval?: ReturnType<typeof setInterval> }).__snapshotInterval = snapshotInterval;
    },
    [id, parentPerformanceId, loaded, pushOverlayPoint],
  );

  const stopRecordingWorklet = useCallback(async () => {
    const performanceId = performanceIdRef.current;
    if (!performanceId || !audioCtxRef.current) return;
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    const node = captureNodeRef.current;
    const interval = (node as unknown as { __snapshotInterval?: ReturnType<typeof setInterval> })?.__snapshotInterval;
    if (interval) clearInterval(interval);

    setState({ kind: "uploading" });

    backingSourceRef.current?.stop();
    const sampleRate = audioCtxRef.current.sampleRate;

    const done = new Promise<void>((resolve) => {
      if (!encodeWorkerRef.current) return resolve();
      encodeWorkerRef.current.onmessage = (e: MessageEvent<{ type: string }>) => {
        if (e.data.type === "done") resolve();
      };
    });
    encodeWorkerRef.current?.postMessage({ type: "stop" });
    await done;

    const { error } = await completePerformanceApiPerformancesPerformanceIdCompletePost({
      path: { performance_id: performanceId },
      body: { sample_rate: Math.round(sampleRate) },
    });
    if (error) {
      setState({ kind: "error", message: "Could not complete the take." });
      return;
    }
    teardownAudioSession();
    setState({ kind: "scoring", performanceId });
  }, []);

  // --- MediaRecorder fallback tier (X1's ladder) — Day 5's original path, unchanged ---

  const startRecordingFallback = useCallback(async () => {
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
    setState({ kind: "recording", performanceId: data.id });

    const tick = () => {
      if (audioCtxRef.current) setCurrentTimeS(audioCtxRef.current.currentTime - startTimeRef.current);
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
  }, [state, id, parentPerformanceId]);

  const stopRecordingFallback = useCallback(async () => {
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
          {state.tier === "media-recorder" && (
            <p role="alert">
              AudioWorklet/SharedArrayBuffer unsupported here — falling back to MediaRecorder (no live pitch lane
              during recording, no client-side AEC).
            </p>
          )}
          {state.tier === "unsupported" && <p role="alert">This browser cannot record audio here at all.</p>}
          {state.tier === "worklet" && (
            <button type="button" onClick={proceedToCalibration}>
              Continue to latency calibration
            </button>
          )}
          {state.tier !== "worklet" && state.tier !== "unsupported" && (
            <button type="button" onClick={startRecordingFallback}>
              Start recording (fallback)
            </button>
          )}
        </>
      )}
      {state.kind === "calibrating" && (
        <>
          <LatencyCalibration audioContext={state.audioContext} inputStream={state.stream} onCalibrated={onCalibrated} />
          <button type="button" onClick={skipCalibration}>
            Skip calibration (manual offset = 0)
          </button>
        </>
      )}
      {state.kind === "armed" && (
        <button
          type="button"
          onClick={() => startRecordingWorklet(state.audioContext, state.stream, state.latencyOffsetMs)}
        >
          Start recording
        </button>
      )}
      {state.kind === "recording" && (
        <>
          <p>Recording… {currentTimeS.toFixed(1)}s</p>
          <PitchLane
            notes={loaded.chart.notes}
            durationS={loaded.chart.duration_s}
            width={800}
            currentTimeS={currentTimeS}
            f0Overlay={overlaySnapshot}
          />
          <button
            type="button"
            onClick={() => (captureNodeRef.current ? stopRecordingWorklet() : stopRecordingFallback())}
          >
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
