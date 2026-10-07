// Thu Oct 8 (X2 of IMPLEMENTATION_PLAN_2026-10-08.md): the pitch
// worker. Drains the cleaned-signal audio ring (written by
// capture-worklet.ts), resamples device-rate audio down to NanoPitch's
// fixed 16kHz/160-sample contract (EC-3), runs the WASM engine's
// realtime greedy Viterbi path per frame (§3.1's deliberate choice —
// NOT the offline/batch path, which hides state-carry bugs), converts
// Hz -> MIDI, drops unvoiced frames (there is no confidence field to
// gate a drawn point on, and 0 Hz has no MIDI value — X2's own note),
// and writes (t_s, midi) pairs into the pitch-overlay ring for the
// main thread's rAF loop to read with zero allocation (X2's "one
// performance trap" note: never push f0 points through React state).
//
// Also tracks a live RTF (real-time factor: wall-clock processing time
// / audio time processed) meter, posted periodically via `postMessage`
// — this one path legitimately uses postMessage, since it is a coarse
// (once-per-second) diagnostics number, not a per-frame hot path.

import { createAudioReader, PitchRingWriter } from "./ring";
import { Reblocker, StreamingResampler } from "./resample";
import { loadNanoPitchEngine } from "./nanopitch-loader";
import { f0HzToMidi, NC_HOP_LENGTH } from "./pitch-convert";

export type PitchWorkerInit = {
  cleanedRingSab: SharedArrayBuffer;
  pitchRingSab: SharedArrayBuffer;
  weightsUrl: string;
  deviceSampleRate: number;
  recordingStartTimeS: number; // AudioContext.currentTime at record start, for t_s
};

let running = false;

self.onmessage = async (event: MessageEvent<{ type: string } & Partial<PitchWorkerInit>>) => {
  const msg = event.data;
  if (msg.type !== "init") return;
  const init = msg as PitchWorkerInit & { type: "init" };
  running = true;
  await runLoop(init);
};

async function runLoop(init: PitchWorkerInit): Promise<void> {
  const engine = await loadNanoPitchEngine(init.weightsUrl);
  const reader = createAudioReader(init.cleanedRingSab);
  const pitchWriter = new PitchRingWriter(init.pitchRingSab);
  const resampler = new StreamingResampler(init.deviceSampleRate, 16000);
  const reblocker = new Reblocker(NC_HOP_LENGTH);

  let framesProcessed = 0;
  let processingTimeMs = 0;
  let lastRtfPostAt = performance.now();
  const scratch = new Float32Array(2048);

  function onFrame(frame: Float32Array): void {
    const t0 = performance.now();
    const { f0Hz } = engine.processFrame(frame);
    processingTimeMs += performance.now() - t0;
    framesProcessed++;

    if (f0Hz > 0) {
      const tS = init.recordingStartTimeS + framesProcessed * (NC_HOP_LENGTH / 16000);
      pitchWriter.push(tS, f0HzToMidi(f0Hz));
    }

    const now = performance.now();
    if (now - lastRtfPostAt > 1000) {
      const audioTimeMs = framesProcessed * (NC_HOP_LENGTH / 16000) * 1000;
      const rtf = audioTimeMs > 0 ? processingTimeMs / audioTimeMs : 0;
      self.postMessage({ type: "rtf", rtf, framesProcessed });
      lastRtfPostAt = now;
    }
  }

  function poll(): void {
    if (!running) return;
    const available = reader.available_read();
    if (available > 0) {
      const toRead = Math.min(available, scratch.length);
      const read = reader.dequeue(scratch.subarray(0, toRead));
      if (read > 0) {
        const resampled = resampler.push(scratch.subarray(0, read));
        reblocker.push(resampled, onFrame);
      }
    }
    setTimeout(poll, 5);
  }
  poll();
}
