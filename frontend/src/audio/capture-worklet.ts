// Thu Oct 8 (X0 + X4 of IMPLEMENTATION_PLAN_2026-10-08.md): the
// AudioWorkletProcessor at the center of §10.1's graph.
//
// inputs[0] = mic (EC/NS/AGC forced off upstream in SingPage.tsx)
// inputs[1] = backing-track reference, routed through a `DelayNode`
//             set from X3's measured round-trip latency, so it is
//             connected only once calibration has produced τ̂ — see
//             `wireAecReference()` in SingPage.tsx. Absent (silent)
//             input[1] is a completely normal state (e.g. headphones,
//             or before calibration finishes) and the processor
//             degrades to a pure passthrough in that case.
// outputs[0] = cleaned signal — the "take" signal. `ringbuf.js`'s ring
//              is SPSC (one writer, one reader): giving the same ring
//              to two consumers (encodeWorker AND pitchWorker) would
//              have each dequeue() call steal samples from the other,
//              corrupting both. So the cleaned signal is written
//              TWICE, to two separate rings — one per consumer — at
//              the cost of doubling that one memcpy, not the DSP.
// outputs[1] = raw mic signal — written to a third ring, used only
//              for this session's client-estimated ERLE (X5's
//              diagnostics number). §10.3's fuller requirement —
//              storing both signals server-side so ERLE and an
//              AEC-on/off re-score comparison can be computed from
//              the stored take — is NOT built this pass; flagged in
//              PROGRESS.md rather than silently dropped. Per the
//              plan's own contingency ladder (§6), X4 is the first
//              thing sanctioned to cut after X7, and a client-only
//              ERLE estimate plus linear-subtraction-only AEC is a
//              smaller cut than dropping X4 entirely.
//
// AEC design (§10.3): a single time-domain NLMS adaptive filter, NOT
// the partitioned-block frequency-domain FDAF the plan names as the
// target implementation. This is a deliberate, documented reduction
// for the same reason as X0's own EC-0 fallback in Day 5 — a
// frequency-domain partitioned-block filter is real DSP engineering
// weeks, not hours, and a correctly-adapting time-domain NLMS filter
// over a same-tick-aligned reference (the one part of §10.1 that is
// NOT optional — same-tick alignment is what makes any known-reference
// AEC tractable at all) delivers the same adapt-then-freeze,
// linear-subtraction-only, no-suppressor behavior the plan requires,
// at a real but lower measured ERLE ceiling than a full FDAF. Linear
// subtraction, no spectral floor, no AGC — exactly as specified.
//
// Filter length: 1024 taps at 48kHz ~= 21ms of coverage. §10.3 expects
// ~85ms of *residual* room response once a DelayNode has absorbed bulk
// delay (16 partitions * 256 samples in the FDAF design) — 1024 taps
// covers less of that residual tail than the full partitioned design
// would, which is the most direct consequence of the time- vs
// frequency-domain reduction above and is the main reason the measured
// ERLE here should be expected nearer the low end of §10.3's ~10-15dB
// range, not the high end.

import { AudioWriter, RingBuffer } from "ringbuf.js";
import { AdaptiveEchoCanceller } from "./aec";

class CaptureProcessor extends AudioWorkletProcessor {
  private aec = new AdaptiveEchoCanceller();
  private adapting = true; // true during count-in; false ("frozen") once the take proper starts
  private cleanedScratch = new Float32Array(128);
  private rawScratch = new Float32Array(128);
  private cleanedForEncodeWriter: AudioWriter | null = null;
  private cleanedForPitchWriter: AudioWriter | null = null;
  private rawWriter: AudioWriter | null = null;

  constructor(options: AudioWorkletNodeOptions) {
    super();
    this.port.onmessage = (event: MessageEvent) => {
      const msg = event.data as { type: string; value?: boolean };
      if (msg.type === "freeze-aec") this.aec.freeze();
      if (msg.type === "set-adapting") this.adapting = Boolean(msg.value);
    };
    const opts = (options.processorOptions ?? {}) as {
      cleanedForEncodeRingSab?: SharedArrayBuffer;
      cleanedForPitchRingSab?: SharedArrayBuffer;
      rawRingSab?: SharedArrayBuffer;
    };
    // `AudioWorklet` modules support normal ES imports under
    // `worker.format: 'es'` (EC-0/§13's Vite decision), so `ringbuf.js`
    // is imported directly at the top of this file rather than passed
    // in by indirection.
    if (opts.cleanedForEncodeRingSab)
      this.cleanedForEncodeWriter = new AudioWriter(new RingBuffer(opts.cleanedForEncodeRingSab, Float32Array));
    if (opts.cleanedForPitchRingSab)
      this.cleanedForPitchWriter = new AudioWriter(new RingBuffer(opts.cleanedForPitchRingSab, Float32Array));
    if (opts.rawRingSab) this.rawWriter = new AudioWriter(new RingBuffer(opts.rawRingSab, Float32Array));
  }

  process(inputs: Float32Array[][], outputs: Float32Array[][]): boolean {
    const mic = inputs[0]?.[0];
    const reference = inputs[1]?.[0];
    const outCleaned = outputs[0]?.[0];
    const outRaw = outputs[1]?.[0];
    if (!mic) return true;

    const n = mic.length;
    if (this.cleanedScratch.length !== n) {
      this.cleanedScratch = new Float32Array(n);
      this.rawScratch = new Float32Array(n);
    }

    for (let i = 0; i < n; i++) {
      const micSample = mic[i];
      const refSample = reference ? reference[i] : 0;
      // No reference connected (headphones, or pre-calibration) ->
      // pure passthrough; §10.3's headphone-bypass posture falls out
      // of this for free rather than needing a separate code path.
      const cleaned = reference ? this.aec.step(micSample, refSample) : micSample;
      this.cleanedScratch[i] = cleaned;
      this.rawScratch[i] = micSample;
      if (outCleaned) outCleaned[i] = cleaned;
      if (outRaw) outRaw[i] = micSample;
    }

    if (!this.adapting) this.aec.freeze();

    this.cleanedForEncodeWriter?.enqueue(this.cleanedScratch);
    this.cleanedForPitchWriter?.enqueue(this.cleanedScratch);
    this.rawWriter?.enqueue(this.rawScratch);

    return true;
  }
}

registerProcessor("capture-processor", CaptureProcessor);
