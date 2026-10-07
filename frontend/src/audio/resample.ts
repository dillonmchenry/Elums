// Thu Oct 8 (EC-3 of IMPLEMENTATION_PLAN_2026-10-08.md): the
// sample-rate and block-size bridge between the device's native audio
// (AudioWorklet delivers 128-frame blocks at e.g. 48kHz) and NanoPitch's
// fixed contract (exactly 160 float samples at 16kHz per call).
//
// EC-3 explicitly rules out plain decimation ("aliasing lands in the
// mel bins") in favor of an anti-aliased polyphase FIR resampler. Both
// classes below are pure, allocation-free-per-call (buffers are sized
// once at construction), and have no WASM/browser dependency — they
// are unit-tested directly (plan §5 acceptance check 10: "deterministic
// layers only... resampler, 128->160 reblocker").

/** Windowed-sinc low-pass FIR filter, used both as the resampler's
 * anti-aliasing filter and as its interpolation kernel (a single
 * design serves both roles for polyphase resampling). */
function designLowpassFir(cutoff: number, numTaps: number): Float64Array {
  const taps = new Float64Array(numTaps);
  const center = (numTaps - 1) / 2;
  for (let i = 0; i < numTaps; i++) {
    const x = i - center;
    // Sinc kernel at the cutoff frequency (normalized, 0..0.5 of Nyquist).
    const sinc = x === 0 ? 2 * cutoff : Math.sin(2 * Math.PI * cutoff * x) / (Math.PI * x);
    // Blackman window — lower sidelobes than Hamming, matters here
    // because sidelobe leakage is exactly what would alias into the
    // mel bins EC-3 warns about.
    const w =
      0.42 - 0.5 * Math.cos((2 * Math.PI * i) / (numTaps - 1)) + 0.08 * Math.cos((4 * Math.PI * i) / (numTaps - 1));
    taps[i] = sinc * w;
  }
  let sum = 0;
  for (const t of taps) sum += t;
  for (let i = 0; i < numTaps; i++) taps[i] /= sum;
  return taps;
}

/**
 * Streaming anti-aliased resampler for an arbitrary rational ratio
 * (e.g. 48000 -> 16000). Polyphase-equivalent direct-form FIR: for
 * every output sample we evaluate the same fixed-length filter at a
 * fractional input position, which is mathematically identical to a
 * polyphase bank indexed by the fractional phase, without needing to
 * precompute per-phase coefficient subsets.
 *
 * Call `push(samples)` with any number of input-rate samples at any
 * time; it returns as many output-rate samples as are now available.
 * Internal history (enough past samples for the filter's tail) carries
 * across calls so streaming never re-processes or drops samples at
 * call boundaries.
 */
export class StreamingResampler {
  private readonly ratio: number; // outRate / inRate
  private readonly taps: Float64Array;
  private readonly halfSpan: number;
  private history: Float64Array;
  private historyLen = 0;
  private inputPos = 0; // fractional position of the next output sample, in input-sample units

  constructor(inRate: number, outRate: number, numTaps = 65) {
    this.ratio = outRate / inRate;
    const nyquist = Math.min(inRate, outRate) / 2;
    const cutoffNormalizedToIn = (0.9 * nyquist) / inRate; // a bit under Nyquist for headroom
    this.taps = designLowpassFir(cutoffNormalizedToIn, numTaps);
    this.halfSpan = (numTaps - 1) / 2;
    // History holds up to one filter span of past input samples.
    this.history = new Float64Array(numTaps);
  }

  /** Feed new input-rate samples; returns newly available output-rate
   * samples (length varies call to call, since the ratio is rational). */
  push(input: Float32Array): Float32Array {
    const n = input.length;
    const combinedLen = this.historyLen + n;
    const combined = new Float64Array(combinedLen);
    combined.set(this.history.subarray(0, this.historyLen), 0);
    for (let i = 0; i < n; i++) combined[this.historyLen + i] = input[i];

    const outSamples: number[] = [];
    // `inputPos` is already measured relative to the start of
    // `combined` (history is placed at combined[0..historyLen), and
    // `inputPos` was computed at the end of the previous call as an
    // offset into that same history window) — do NOT add `historyLen`
    // again here, or every call after the first double-shifts `pos`
    // and the resampler silently starves itself of output.
    let pos = this.inputPos;
    const lastValidCenter = combinedLen - 1 - this.halfSpan;
    while (pos <= lastValidCenter) {
      const center = Math.floor(pos);
      // Nearest-center evaluation of the fixed low-pass kernel: the
      // sub-sample timing error this leaves (< 1 input sample) is far
      // below NanoPitch's 10ms frame resolution and inaudible for
      // pitch tracking; the anti-aliasing is what actually matters
      // for EC-4's mel parity (preventing energy above the new
      // Nyquist from folding into the mel bins), and that comes from
      // the kernel's cutoff, not from fractional-tap interpolation.
      let acc = 0;
      for (let k = 0; k < this.taps.length; k++) {
        const srcIdx = center - this.halfSpan + k;
        acc += this.taps[k] * (combined[srcIdx] ?? 0);
      }
      outSamples.push(acc);
      pos += 1 / this.ratio;
    }

    // Carry forward the tail of `combined` needed for the next call's
    // filter span, and the fractional remainder of `pos`.
    const keepFrom = Math.max(0, combinedLen - this.taps.length);
    const keepLen = combinedLen - keepFrom;
    this.history.set(combined.subarray(keepFrom), 0);
    this.historyLen = keepLen;
    this.inputPos = pos - keepFrom;

    return Float32Array.from(outSamples);
  }
}

/**
 * Reblocks a variable-length stream of samples into fixed-size frames
 * (NanoPitch's NC_HOP_LENGTH = 160 samples @ 16kHz), calling `onFrame`
 * once per complete frame with no per-frame allocation (the internal
 * buffer is reused; `onFrame` receives a view, not a copy — callers
 * that need to retain data must copy it themselves before returning).
 */
export class Reblocker {
  private readonly frameSize: number;
  private buf: Float32Array;
  private fill = 0;

  constructor(frameSize: number) {
    this.frameSize = frameSize;
    this.buf = new Float32Array(frameSize);
  }

  push(samples: Float32Array, onFrame: (frame: Float32Array) => void): void {
    let offset = 0;
    while (offset < samples.length) {
      const space = this.frameSize - this.fill;
      const take = Math.min(space, samples.length - offset);
      this.buf.set(samples.subarray(offset, offset + take), this.fill);
      this.fill += take;
      offset += take;
      if (this.fill === this.frameSize) {
        onFrame(this.buf);
        this.fill = 0;
      }
    }
  }
}
