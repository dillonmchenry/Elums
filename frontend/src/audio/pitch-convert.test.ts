import { describe, expect, it } from "vitest";
import { f0HzToMidi } from "./pitch-convert";

describe("f0HzToMidi", () => {
  it("converts A4 (440Hz) to MIDI 69 exactly", () => {
    expect(f0HzToMidi(440)).toBeCloseTo(69, 5);
  });

  it("converts C4 (middle C, 261.63Hz) to MIDI 60", () => {
    expect(f0HzToMidi(261.6256)).toBeCloseTo(60, 2);
  });

  it("is monotonically increasing with frequency", () => {
    expect(f0HzToMidi(220)).toBeLessThan(f0HzToMidi(440));
    expect(f0HzToMidi(440)).toBeLessThan(f0HzToMidi(880));
  });
});
