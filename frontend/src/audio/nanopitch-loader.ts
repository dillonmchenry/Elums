// Thu Oct 8 (EC-2 + X2 of IMPLEMENTATION_PLAN_2026-10-08.md): loads the
// NanoPitch WASM module and weight file, reading `cond_size`/`gru_size`
// from the `.bin` header rather than assuming `nanopitch.h`'s compile-
// time defaults (`NC_COND_SIZE 64`, `NC_GRU_SIZE 96`).
//
// EC-2(b)'s hazard, confirmed against the real shipped checkpoint
// (`vendor/nanopitch/training/runs/best_150+late_clean_112gru_model/`):
// its header reads `cond_size=64, gru_size=112` — the GRU size genuinely
// does NOT match `nanopitch.h`'s default of 96. The C engine itself
// already takes both sizes as runtime parameters (`nanopitch_load_weights`
// and `nanopitch_create_state` both accept `gru_size`), so the only
// place this can go wrong is a JS loader that hardcodes 96 — avoided
// here by reading the real header bytes every time.

import { NC_HOP_LENGTH, NC_PITCH_BINS } from "./pitch-convert";

export { NC_HOP_LENGTH, NC_PITCH_BINS, PITCH_FMIN_HZ, PITCH_CENTS_PER_BIN, f0HzToMidi } from "./pitch-convert";

type WasmExports = {
  _malloc(n: number): number;
  _free(ptr: number): void;
  _nanopitch_load_weights(dataPtr: number, nFloats: number, condSize: number, gruSize: number): number;
  _nanopitch_create_state(gruSize: number): number;
  _nanopitch_reset_state(statePtr: number, gruSize: number): void;
  _nanopitch_process_frame(weightsPtr: number, statePtr: number, framePtr: number, outPtr: number): number;
  // The emcc glue's `updateMemoryViews()` only assigns
  // `Module["HEAPF32"] = ...` — `HEAPU8`/`HEAP8`/etc. stay internal
  // closure variables, never attached to the returned module object.
  // `module.HEAPU8` is therefore always `undefined` (confirmed live,
  // X6 validation: crashed with "Cannot read properties of undefined
  // (reading 'buffer')" on the first real, non-warm-up frame, the
  // first call that actually reached the `HEAPU8`-reading branch
  // below). The output struct is all 4-byte-aligned floats, so
  // `HEAPF32` alone (which IS exported) is sufficient — no `HEAPU8`.
  HEAPF32: Float32Array;
};

export type NanoPitchEngine = {
  /** Process exactly NC_HOP_LENGTH (160) samples @ 16kHz. Returns f0Hz
   * (0 = unvoiced/warm-up) and the VAD score. */
  processFrame(frame: Float32Array): { f0Hz: number; vad: number };
  reset(): void;
};

/** `out` struct layout matches `NanoPitchOutput` in nanopitch.h:
 *   float vad;                     (offset 0,   4 bytes)
 *   float pitch_posterior[360];    (offset 4,   1440 bytes)
 *   float f0_hz;                   (offset 1444, 4 bytes)
 *   float mel[40];                 (offset 1448, 160 bytes)
 */
const OUT_STRUCT_BYTES = 4 + NC_PITCH_BINS * 4 + 4 + 40 * 4;
// Float-index offsets (not byte offsets) into `HEAPF32`, since the
// whole struct is floats and `HEAPF32` is the only exported view.
const OUT_VAD_FLOAT_OFFSET = 0;
const OUT_F0_FLOAT_OFFSET = 1 + NC_PITCH_BINS;

export async function loadNanoPitchEngine(weightsUrl: string): Promise<NanoPitchEngine> {
  // `nanopitch.js` lives under `frontend/public/nanopitch/` (EC-1), not
  // `src/` — it's emcc-generated glue code with no corresponding
  // source module Vite can bundle. Two things this rules out:
  //   - A static top-level import fails `vite build` with
  //     UNRESOLVED_IMPORT (Vite can't see a `public/` path in the
  //     module graph at build time).
  //   - A plain runtime `import("/nanopitch/nanopitch.js")` works in
  //     the PRODUCTION build (public assets are just static files
  //     there) but 500s in Vite's DEV SERVER specifically — Vite's
  //     dev middleware hard-refuses any `?import`-tagged module
  //     request whose resolved path is under `public/`, exactly the
  //     "should not be imported from source code... only referenced
  //     via HTML tags" restriction its own error names. Confirmed live
  //     (X6 validation): `fetch('/nanopitch/nanopitch.js?import')`
  //     returns a 500 with that message verbatim.
  // Fix: fetch the glue code as plain TEXT (an ordinary static GET,
  // not a module import — never intercepted by that dev-only rule),
  // wrap it in a `Blob`, and `import()` the resulting `blob:` URL.
  // `blob:` URLs are never routed through Vite's dev server at all, so
  // this one code path works identically in dev and in the production
  // build. The emcc glue's own WASM-locating logic resolves relative
  // to `import.meta.url`, which would be nonsensical for a `blob:`
  // URL — sidestepped by passing an explicit `locateFile` override
  // instead, pointing straight at the real `/nanopitch/` static path.
  const nanopitchJsText = await (await fetch("/nanopitch/nanopitch.js")).text();
  const blobUrl = URL.createObjectURL(new Blob([nanopitchJsText], { type: "text/javascript" }));
  let module: WasmExports;
  try {
    const mod = (await import(/* @vite-ignore */ blobUrl)) as { default: (opts?: object) => Promise<WasmExports> };
    module = await mod.default({ locateFile: (path: string) => `/nanopitch/${path}` });
  } finally {
    URL.revokeObjectURL(blobUrl);
  }
  const weightsResponse = await fetch(weightsUrl);
  const weightsBuf = await weightsResponse.arrayBuffer();
  const header = new DataView(weightsBuf, 0, 20);
  const magic = String.fromCharCode(header.getUint8(0), header.getUint8(1), header.getUint8(2), header.getUint8(3));
  if (magic !== "NCWT") throw new Error(`Unexpected weights file magic: ${magic}`);
  const condSize = header.getUint32(8, true);
  const gruSize = header.getUint32(12, true);
  const nWeights = header.getUint32(16, true);
  const floats = new Float32Array(weightsBuf, 20, nWeights);

  const dataPtr = module._malloc(nWeights * 4);
  module.HEAPF32.set(floats, dataPtr / 4);
  const weightsPtr = module._nanopitch_load_weights(dataPtr, nWeights, condSize, gruSize);
  if (!weightsPtr) throw new Error(`nanopitch_load_weights failed (cond=${condSize}, gru=${gruSize})`);
  const statePtr = module._nanopitch_create_state(gruSize);

  const framePtr = module._malloc(NC_HOP_LENGTH * 4);
  const outPtr = module._malloc(OUT_STRUCT_BYTES);

  return {
    processFrame(frame: Float32Array) {
      if (frame.length !== NC_HOP_LENGTH) {
        throw new Error(`processFrame expects exactly ${NC_HOP_LENGTH} samples, got ${frame.length}`);
      }
      module.HEAPF32.set(frame, framePtr / 4);
      const valid = module._nanopitch_process_frame(weightsPtr, statePtr, framePtr, outPtr);
      if (!valid) return { f0Hz: 0, vad: 0 }; // warm-up frames (first 40ms)
      const outFloatBase = outPtr / 4;
      return {
        f0Hz: module.HEAPF32[outFloatBase + OUT_F0_FLOAT_OFFSET],
        vad: module.HEAPF32[outFloatBase + OUT_VAD_FLOAT_OFFSET],
      };
    },
    reset() {
      module._nanopitch_reset_state(statePtr, gruSize);
    },
  };
}
