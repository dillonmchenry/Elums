import { describe, expect, it } from "vitest";
import { buildWavHeader, floatTo16BitPCM } from "./wav";

describe("buildWavHeader", () => {
  it("produces the canonical 44-byte PCM header", () => {
    const header = buildWavHeader(16000, 320, 1, 16);
    const bytes = new Uint8Array(header);
    expect(bytes.length).toBe(44);
    expect(String.fromCharCode(...bytes.slice(0, 4))).toBe("RIFF");
    expect(String.fromCharCode(...bytes.slice(8, 12))).toBe("WAVE");
    expect(String.fromCharCode(...bytes.slice(12, 16))).toBe("fmt ");
    expect(String.fromCharCode(...bytes.slice(36, 40))).toBe("data");

    const view = new DataView(header);
    expect(view.getUint32(4, true)).toBe(36 + 320); // RIFF chunk size
    expect(view.getUint16(20, true)).toBe(1); // PCM format tag
    expect(view.getUint16(22, true)).toBe(1); // mono
    expect(view.getUint32(24, true)).toBe(16000); // sample rate
    expect(view.getUint16(34, true)).toBe(16); // bits per sample
    expect(view.getUint32(40, true)).toBe(320); // data chunk size
  });
});

describe("floatTo16BitPCM", () => {
  it("clamps and scales correctly at the extremes", () => {
    const input = new Float32Array([0, 1, -1, 1.5, -1.5, 0.5]);
    const out = floatTo16BitPCM(input);
    expect(out[0]).toBe(0);
    expect(out[1]).toBe(0x7fff);
    expect(out[2]).toBe(-0x8000);
    expect(out[3]).toBe(0x7fff); // clamped
    expect(out[4]).toBe(-0x8000); // clamped
    expect(out[5]).toBeCloseTo(0x4000, -1);
  });
});
