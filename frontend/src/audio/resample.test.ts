import { describe, expect, it } from "vitest";
import { Reblocker, StreamingResampler } from "./resample";

describe("StreamingResampler", () => {
  it("resamples 48kHz -> 16kHz to roughly a third as many samples", () => {
    const inRate = 48000;
    const outRate = 16000;
    const r = new StreamingResampler(inRate, outRate);
    const durationS = 1;
    const n = inRate * durationS;
    const freq = 440;
    const input = new Float32Array(n);
    for (let i = 0; i < n; i++) input[i] = Math.sin((2 * Math.PI * freq * i) / inRate);

    // Feed in device-sized chunks (128 frames), like an AudioWorklet would.
    let total = 0;
    for (let off = 0; off < n; off += 128) {
      const chunk = input.subarray(off, Math.min(off + 128, n));
      total += r.push(chunk).length;
    }
    // Should land close to outRate * durationS, within filter-latency slop.
    expect(total).toBeGreaterThan(outRate * durationS - 100);
    expect(total).toBeLessThan(outRate * durationS + 100);
  });

  it("attenuates energy above the new Nyquist (anti-aliasing, not decimation)", () => {
    const inRate = 48000;
    const outRate = 16000;
    // A tone above outRate/2 (8000 Hz) that naive decimation would fold
    // down into the audible/pitch-relevant band.
    const aliasFreq = 15000;
    const n = inRate; // 1s
    const input = new Float32Array(n);
    for (let i = 0; i < n; i++) input[i] = Math.sin((2 * Math.PI * aliasFreq * i) / inRate);

    const r = new StreamingResampler(inRate, outRate);
    const out: number[] = [];
    for (let off = 0; off < n; off += 128) {
      out.push(...r.push(input.subarray(off, Math.min(off + 128, n))));
    }
    const settled = out.slice(Math.floor(out.length / 2)); // skip filter warm-up
    const rms = Math.sqrt(settled.reduce((s, v) => s + v * v, 0) / settled.length);
    // Input RMS of a unit sine is ~0.707; a properly anti-aliased
    // resampler should suppress this out-of-band tone heavily.
    expect(rms).toBeLessThan(0.1);
  });
});

describe("Reblocker", () => {
  it("emits fixed-size frames regardless of input chunk size", () => {
    const frameSize = 160;
    const reblocker = new Reblocker(frameSize);
    const frames: number[][] = [];
    // Simulate 128-frame AudioWorklet pushes feeding a 160-sample consumer.
    const totalSamples = 128 * 20;
    const input = new Float32Array(totalSamples);
    for (let i = 0; i < totalSamples; i++) input[i] = i;

    for (let off = 0; off < totalSamples; off += 128) {
      const chunk = input.subarray(off, Math.min(off + 128, totalSamples));
      reblocker.push(chunk, (frame) => frames.push(Array.from(frame)));
    }

    expect(frames.length).toBe(Math.floor(totalSamples / frameSize));
    for (const frame of frames) expect(frame.length).toBe(frameSize);
    // Frames must be contiguous and in order — frame 0 starts at sample 0.
    expect(frames[0][0]).toBe(0);
    expect(frames[1][0]).toBe(frameSize);
  });

  it("never drops or duplicates samples across many small pushes", () => {
    const frameSize = 160;
    const reblocker = new Reblocker(frameSize);
    const received: number[] = [];
    const totalSamples = 160 * 7;
    const input = new Float32Array(totalSamples);
    for (let i = 0; i < totalSamples; i++) input[i] = i;

    // Odd push sizes to stress boundary handling.
    for (let off = 0; off < totalSamples; off += 37) {
      const chunk = input.subarray(off, Math.min(off + 37, totalSamples));
      reblocker.push(chunk, (frame) => received.push(...frame));
    }

    expect(received.length).toBe(Math.floor(totalSamples / frameSize) * frameSize);
    for (let i = 0; i < received.length; i++) expect(received[i]).toBe(i);
  });
});
