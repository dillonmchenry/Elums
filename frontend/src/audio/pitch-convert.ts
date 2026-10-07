// Pure pitch-unit conversion, split out from nanopitch-loader.ts so it
// can be unit tested without pulling in the WASM module import (which
// only resolves inside a real browser/worker serving
// /nanopitch/nanopitch.js, not under vitest's jsdom environment).

export const NC_HOP_LENGTH = 160; // samples @ 16kHz, must match nanopitch.h
export const NC_PITCH_BINS = 360;
export const PITCH_FMIN_HZ = 31.7;
export const PITCH_CENTS_PER_BIN = 20;

export function f0HzToMidi(f0Hz: number): number {
  return 69 + 12 * Math.log2(f0Hz / 440);
}
