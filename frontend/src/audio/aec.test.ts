import { describe, expect, it } from "vitest";
import { AdaptiveEchoCanceller, computeErleDb } from "./aec";

/** A synthetic "echo path": the reference signal passed through a
 * fixed, known FIR (a stand-in for a room/speaker-to-mic response),
 * scaled down (speaker-to-mic attenuation) — exactly the known-reference
 * scenario §10.1 describes ("the far-end signal is exactly known,
 * because we play it"). */
function applySyntheticEchoPath(reference: Float32Array): Float32Array {
  const echoTaps = [0.6, 0.25, -0.1, 0.05]; // short, fixed, arbitrary
  const out = new Float32Array(reference.length);
  for (let i = 0; i < reference.length; i++) {
    let acc = 0;
    for (let k = 0; k < echoTaps.length; k++) {
      if (i - k >= 0) acc += echoTaps[k] * reference[i - k];
    }
    out[i] = acc;
  }
  return out;
}

describe("AdaptiveEchoCanceller", () => {
  it("converges to a positive ERLE on a known-reference synthetic echo", () => {
    const n = 48000 * 2; // 2s at 48kHz
    const reference = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      // Broadband-ish reference (sum of a few tones), closer to a
      // real backing track than a pure sine, since a single-frequency
      // reference is trivially cancelled and would not exercise the
      // filter the way the plan's real backing-track signal would.
      reference[i] =
        0.3 * Math.sin((2 * Math.PI * 220 * i) / 48000) +
        0.2 * Math.sin((2 * Math.PI * 440 * i) / 48000) +
        0.1 * Math.sin((2 * Math.PI * 880 * i) / 48000);
    }
    const echo = applySyntheticEchoPath(reference);
    // "Singer" contributes nothing in this test — isolates the AEC's
    // own convergence from any vocal content, matching the
    // adapt-during-count-in design (count-in has no singer present).
    const mic = echo;

    const aec = new AdaptiveEchoCanceller();
    const cleaned = new Float32Array(n);
    for (let i = 0; i < n; i++) cleaned[i] = aec.step(mic[i], reference[i]);

    // Settle window: skip the first second to let the filter converge.
    const settledFrom = 48000;
    const rawSettled = echo.subarray(settledFrom);
    const cleanedSettled = cleaned.subarray(settledFrom);
    const erleDb = computeErleDb(rawSettled, cleanedSettled);

    // §10.3 names ~10-15dB for a converged *linear* filter on real
    // speakerphone audio; this synthetic case has an exactly-known,
    // stationary, short echo path (easier than a real room), so a
    // materially higher ERLE here is expected and is the right sanity
    // check that the filter is actually adapting, not a claim about
    // real-world ERLE (that number can only come from X6's live
    // on-device measurement).
    expect(erleDb).toBeGreaterThan(20);
  });

  it("freeze() stops adaptation — weights (and therefore cancellation) stop changing", () => {
    const n = 48000;
    const reference = new Float32Array(n);
    for (let i = 0; i < n; i++) reference[i] = Math.sin((2 * Math.PI * 300 * i) / 48000);
    const echo = applySyntheticEchoPath(reference);

    const aec = new AdaptiveEchoCanceller();
    // Adapt for half the signal.
    for (let i = 0; i < n / 2; i++) aec.step(echo[i], reference[i]);
    aec.freeze();
    expect(aec.isFrozen()).toBe(true);
    const energyAtFreeze = aec.weightsEnergy();

    // After freezing, continuing to feed the rest of the (still
    // echo-y) signal must NOT move the weights at all — this is what
    // "adapt during count-in, then freeze for the take" (§10.3)
    // actually requires: an unfrozen filter would keep adapting here
    // and this assertion would fail if freeze() were a no-op.
    for (let i = Math.floor(n / 2); i < n; i++) aec.step(echo[i], reference[i]);
    expect(aec.weightsEnergy()).toBeCloseTo(energyAtFreeze, 10);
  });

  it("passes the mic signal through unchanged when the reference is silent", () => {
    const aec = new AdaptiveEchoCanceller();
    const micSample = 0.42;
    const cleaned = aec.step(micSample, 0);
    expect(cleaned).toBeCloseTo(micSample, 5);
  });
});

describe("computeErleDb", () => {
  it("is 0 dB when cleaned equals raw (no cancellation)", () => {
    const raw = new Float32Array([0.5, -0.5, 0.3, -0.3]);
    expect(computeErleDb(raw, raw)).toBeCloseTo(0, 5);
  });

  it("is positive and large when cleaned is near-silent relative to raw", () => {
    const raw = new Float32Array(1000).fill(0.5);
    const cleaned = new Float32Array(1000).fill(0.0005);
    expect(computeErleDb(raw, cleaned)).toBeGreaterThan(40);
  });
});
