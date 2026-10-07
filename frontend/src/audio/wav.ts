// Thu Oct 8 (X0 of IMPLEMENTATION_PLAN_2026-10-08.md): X0's own
// "unresolved interface decision" — resolved here as option (a),
// the plan's recommended one: chunk 0 (and every chunk) carries
// headerless 16-bit PCM, and the server's `complete` step
// (elums/api/routers/performances.py::complete_performance) prepends
// a real WAV header once the total length is known. `probe_audio`
// then sees a valid file on the assembled result, same as before.
//
// This module provides the client-side Float32 -> Int16 PCM encode
// (used by encodeWorker.ts) and the WAV-header builder, shared so the
// same byte-exact header logic can be unit-tested here without a
// server round trip. The server-side header prepend
// (`elums/ingest/wav.py`) is a separate, Python port of the same
// 44-byte canonical PCM WAV header.

export function floatTo16BitPCM(input: Float32Array): Int16Array {
  const out = new Int16Array(input.length);
  for (let i = 0; i < input.length; i++) {
    const clamped = Math.max(-1, Math.min(1, input[i]));
    out[i] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
  }
  return out;
}

/** Build a canonical 44-byte PCM WAV header for `dataLength` bytes of
 * 16-bit mono PCM at `sampleRate`. Byte-for-byte compatible with
 * `elums/ingest/wav.py::build_wav_header` — covered by both sides'
 * unit tests against the same fixed expected-byte vector. */
export function buildWavHeader(sampleRate: number, dataLength: number, numChannels = 1, bitsPerSample = 16): ArrayBuffer {
  const blockAlign = (numChannels * bitsPerSample) / 8;
  const byteRate = sampleRate * blockAlign;
  const buffer = new ArrayBuffer(44);
  const view = new DataView(buffer);

  const writeStr = (offset: number, s: string) => {
    for (let i = 0; i < s.length; i++) view.setUint8(offset + i, s.charCodeAt(i));
  };

  writeStr(0, "RIFF");
  view.setUint32(4, 36 + dataLength, true);
  writeStr(8, "WAVE");
  writeStr(12, "fmt ");
  view.setUint32(16, 16, true); // fmt chunk size
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, numChannels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, byteRate, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, bitsPerSample, true);
  writeStr(36, "data");
  view.setUint32(40, dataLength, true);

  return buffer;
}
