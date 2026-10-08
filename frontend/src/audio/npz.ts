// Fri Oct 9 (F7 of IMPLEMENTATION_PLAN_2026-10-09.md): a performance's
// `f0_blob_sha256` is `elums/ingest/f0.py::pack_f0_blob`'s output -- a
// binary `.npz` (NumPy's own uncompressed-ZIP container, `np.savez`,
// NOT `savez_compressed`) holding two float16 arrays, `f0_hz` and
// `confidence`. The plan's "feed Day 5's unfed f0Overlay" means this
// file is the client-side mirror of that one Python call -- no server
// format change, no new blob kind, just a reader for the one that
// already exists.
//
// `np.savez` writes a plain `zipfile.ZIP_STORED` archive (no
// compression) -- confirmed against `elums/ingest/f0.py`'s own
// docstring ("np.savez into an in-memory buffer... self-describing").
// That means no DEFLATE decoder is needed here: this module only has
// to walk a ZIP's local file headers and read each entry's bytes
// verbatim, then parse NumPy's own `.npy` v1.0 header (a Python dict
// literal, ASCII, newline-terminated) off the front of each entry.
//
// Pure, allocation-light, no external dependency -- same discipline as
// resample.ts's hand-rolled FIR filter, for the same reason (no npm
// package here does "parse an uncompressed .npz in the browser" as a
// one-liner worth a new dependency for ~120 lines of code).

export class UnsupportedNpzError extends Error {}

type NpyArray = {
  dtype: string;
  shape: number[];
  data: DataView;
};

/** Reads every entry out of an uncompressed-ZIP (ZIP_STORED) buffer,
 * by name. Walks local file headers directly rather than the central
 * directory at the end -- simpler, and `np.savez`'s own output is
 * written as one contiguous sequence of stored entries with no
 * spanning/encryption to worry about. */
function readZipStoredEntries(buf: ArrayBuffer): Map<string, ArrayBuffer> {
  const view = new DataView(buf);
  const bytes = new Uint8Array(buf);
  const entries = new Map<string, ArrayBuffer>();
  let offset = 0;

  const LOCAL_FILE_HEADER_SIG = 0x04034b50;
  const CENTRAL_DIR_SIG = 0x02014b50;
  const EOCD_SIG = 0x06054b50;

  while (offset + 4 <= buf.byteLength) {
    const sig = view.getUint32(offset, true);
    if (sig === CENTRAL_DIR_SIG || sig === EOCD_SIG) break; // done with local entries
    if (sig !== LOCAL_FILE_HEADER_SIG) {
      throw new UnsupportedNpzError(`Unexpected ZIP signature at offset ${offset}: 0x${sig.toString(16)}`);
    }

    const compressionMethod = view.getUint16(offset + 8, true);
    let compressedSize = view.getUint32(offset + 18, true);
    const nameLen = view.getUint16(offset + 26, true);
    const extraLen = view.getUint16(offset + 28, true);
    const nameStart = offset + 30;
    const name = new TextDecoder("ascii").decode(bytes.subarray(nameStart, nameStart + nameLen));
    const extraStart = nameStart + nameLen;

    if (compressionMethod !== 0) {
      throw new UnsupportedNpzError(
        `${name}: compression method ${compressionMethod} is not STORED -- np.savez_compressed output is not supported here.`
      );
    }

    // `np.savez` writes ZIP64 extra records even for tiny (<4GB)
    // entries -- confirmed directly against a real `pack_f0_blob()`
    // output: the base local-file-header size fields are the
    // 0xFFFFFFFF sentinel and the real sizes live in a tag-0x0001
    // extra field instead (APPNOTE.TXT 4.5.3). Per that spec, when
    // BOTH the base `uncompressed size` and `compressed size` fields
    // are the sentinel (always true for `np.savez`'s own output),
    // the ZIP64 record carries them in that order: 8-byte
    // uncompressed size, then 8-byte compressed size.
    if (compressedSize === 0xffffffff) {
      let p = extraStart;
      const extraEnd = extraStart + extraLen;
      let found = false;
      while (p + 4 <= extraEnd) {
        const tag = view.getUint16(p, true);
        const size = view.getUint16(p + 2, true);
        if (tag === 0x0001 && size >= 16) {
          // Only the low 32 bits are read -- an f0/confidence track
          // this project ever produces is nowhere near 4GB.
          compressedSize = view.getUint32(p + 4 + 8, true);
          found = true;
          break;
        }
        p += 4 + size;
      }
      if (!found) {
        throw new UnsupportedNpzError(`${name}: ZIP64 size sentinel with no ZIP64 extra record.`);
      }
    }

    const dataStart = extraStart + extraLen;
    entries.set(name, buf.slice(dataStart, dataStart + compressedSize));
    offset = dataStart + compressedSize;
  }

  return entries;
}

// NPY magic is 6 bytes: one non-ASCII byte (0x93) followed by the
// ASCII text "NUMPY" -- expressed as a numeric byte array rather than
// a string literal containing an escaped non-ASCII code point.
const NPY_MAGIC_BYTES = [0x93, 0x4e, 0x55, 0x4d, 0x50, 0x59];

/** Parses one .npy v1.0/2.0 buffer: the 6-byte magic above, a version
 * byte pair, a little-endian header-length field (2 bytes for v1.0, 4
 * for v2.0+), then an ASCII Python-dict-literal header giving
 * `descr`/`shape`. */
function parseNpy(buf: ArrayBuffer): NpyArray {
  const view = new DataView(buf);
  const bytes = new Uint8Array(buf);
  for (let i = 0; i < NPY_MAGIC_BYTES.length; i++) {
    if (bytes[i] !== NPY_MAGIC_BYTES[i]) {
      throw new UnsupportedNpzError("Not an .npy buffer (bad magic bytes).");
    }
  }
  const majorVersion = view.getUint8(6);
  let headerLen: number;
  let headerStart: number;
  if (majorVersion === 1) {
    headerLen = view.getUint16(8, true);
    headerStart = 10;
  } else {
    headerLen = view.getUint32(8, true);
    headerStart = 12;
  }
  const headerStr = new TextDecoder("ascii").decode(bytes.subarray(headerStart, headerStart + headerLen));

  const descrMatch = headerStr.match(/'descr':\s*'([^']+)'/);
  const shapeMatch = headerStr.match(/'shape':\s*\(([^)]*)\)/);
  if (!descrMatch || !shapeMatch) {
    throw new UnsupportedNpzError(`Could not parse .npy header: ${headerStr}`);
  }
  const dtype = descrMatch[1];
  const shape = shapeMatch[1]
    .split(",")
    .map((s) => s.trim())
    .filter((s) => s.length > 0)
    .map(Number);

  const dataStart = headerStart + headerLen;
  return { dtype, shape, data: new DataView(buf, dataStart, buf.byteLength - dataStart) };
}

/** IEEE 754 half-precision -> JS number, via direct bit manipulation
 * (no native Float16Array dependency) -- same category of "write the
 * ~15 lines by hand" decision resample.ts's own FIR filter already
 * made for this codebase. */
function decodeFloat16(bits: number): number {
  const sign = bits & 0x8000 ? -1 : 1;
  const exponent = (bits >> 10) & 0x1f;
  const fraction = bits & 0x03ff;
  if (exponent === 0) {
    return sign * 2 ** -14 * (fraction / 1024);
  }
  if (exponent === 0x1f) {
    return fraction ? NaN : sign * Infinity;
  }
  return sign * 2 ** (exponent - 15) * (1 + fraction / 1024);
}

function float16ArrayToFloat64(npy: NpyArray): Float64Array {
  if (npy.dtype !== "<f2") {
    throw new UnsupportedNpzError(`Expected float16 ('<f2'), got dtype ${npy.dtype}.`);
  }
  const count = npy.shape.reduce((a, b) => a * b, 1);
  const out = new Float64Array(count);
  for (let i = 0; i < count; i++) {
    out[i] = decodeFloat16(npy.data.getUint16(i * 2, true));
  }
  return out;
}

export type F0Track = { f0Hz: Float64Array; confidence: Float64Array };

/** The one function callers need: raw .npz bytes (as fetched from
 * `/blobs/<f0_blob_sha256>`) in, the two float16 arrays
 * `pack_f0_blob` wrote (`f0_hz`, `confidence`) out, as plain
 * Float64Arrays ready for cents/MIDI conversion. */
export function unpackF0Blob(buf: ArrayBuffer): F0Track {
  const entries = readZipStoredEntries(buf);
  const f0Entry = entries.get("f0_hz.npy");
  const confEntry = entries.get("confidence.npy");
  if (!f0Entry || !confEntry) {
    throw new UnsupportedNpzError(
      `Missing expected .npz entries (found: ${Array.from(entries.keys()).join(", ")}).`
    );
  }
  return {
    f0Hz: float16ArrayToFloat64(parseNpy(f0Entry)),
    confidence: float16ArrayToFloat64(parseNpy(confEntry)),
  };
}

// elums/ingest/f0.py's own frozen constant (FRAME_RATE_HZ = 100, "a
// fixed 100 Hz frame rate" per that module's docstring, independently
// confirmed by Day 7's EC-2 check: "24521 frames @ 100Hz"). Not sent
// over the wire anywhere today -- hardcoded here with the same
// justification resample.ts gives NanoPitch's own fixed 160-sample
// hop: it is a genuinely frozen interface constant, not a guess.
export const F0_FRAME_RATE_HZ = 100;

/** Hz -> MIDI, with 0 (unvoiced, per `pack_f0_blob`'s own convention)
 * passed through as 0 rather than -Infinity -- PitchLane's own
 * `f0Overlay` prop already treats `midi <= 0` as a line break. */
export function hzToMidiOrZero(hz: number): number {
  if (!(hz > 0)) return 0;
  return 69 + 12 * Math.log2(hz / 440);
}

/** Resamples an unpacked f0 track into PitchLane's own
 * `{ t_s, midi }[]` overlay shape. */
export function f0TrackToOverlay(
  track: F0Track,
  frameRateHz: number = F0_FRAME_RATE_HZ
): { t_s: number; midi: number }[] {
  const out = new Array<{ t_s: number; midi: number }>(track.f0Hz.length);
  for (let i = 0; i < track.f0Hz.length; i++) {
    out[i] = { t_s: i / frameRateHz, midi: hzToMidiOrZero(track.f0Hz[i]) };
  }
  return out;
}
