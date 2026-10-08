import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { f0TrackToOverlay, hzToMidiOrZero, unpackF0Blob } from "./npz";

const FIXTURE_PATH = join(dirname(fileURLToPath(import.meta.url)), "testdata", "f0_sample.npz");

describe("unpackF0Blob", () => {
  it("round-trips a real pack_f0_blob() output", () => {
    const buf = readFileSync(FIXTURE_PATH);
    const track = unpackF0Blob(buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength));
    expect(track.f0Hz.length).toBe(5);
    expect(track.confidence.length).toBe(5);
    expect(track.f0Hz[0]).toBeCloseTo(0, 1);
    expect(track.f0Hz[1]).toBeCloseTo(220, 0);
    expect(track.f0Hz[2]).toBeCloseTo(440, 0);
    expect(track.f0Hz[3]).toBeCloseTo(880, -1);
    expect(track.f0Hz[4]).toBeCloseTo(0, 1);
    expect(track.confidence[2]).toBeCloseTo(0.9, 1);
  });

  it("throws UnsupportedNpzError on garbage input, not a silent wrong parse", () => {
    const garbage = new Uint8Array([1, 2, 3, 4]).buffer;
    expect(() => unpackF0Blob(garbage)).toThrow();
  });
});

describe("hzToMidiOrZero", () => {
  it("maps A440 to MIDI 69 and passes 0/unvoiced through as 0", () => {
    expect(hzToMidiOrZero(440)).toBeCloseTo(69, 5);
    expect(hzToMidiOrZero(0)).toBe(0);
    expect(hzToMidiOrZero(-1)).toBe(0);
  });
});

describe("f0TrackToOverlay", () => {
  it("produces one point per frame at the given frame rate", () => {
    const overlay = f0TrackToOverlay({ f0Hz: new Float64Array([0, 440]), confidence: new Float64Array([0, 1]) }, 100);
    expect(overlay).toHaveLength(2);
    expect(overlay[0]).toEqual({ t_s: 0, midi: 0 });
    expect(overlay[1].t_s).toBeCloseTo(0.01, 5);
    expect(overlay[1].midi).toBeCloseTo(69, 5);
  });
});
