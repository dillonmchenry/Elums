#!/bin/bash
# ===========================================================================
# Build NanoPitch C inference engine -> WebAssembly (WASM)
#
# This compiles nanopitch.c into a .wasm binary + .js glue code that
# can run in any modern web browser. The browser's JavaScript calls
# the C functions through the WASM interface.
#
# Prerequisites:
#   1. Install Emscripten SDK: https://emscripten.org/docs/getting_started/
#   2. Activate it: source /path/to/emsdk/emsdk_env.sh
#   (or: `make nanopitch-wasm`, which runs this inside the
#   `emscripten/emsdk` Docker image — no host install needed.)
#
# Usage:
#   ./build.sh            # optimized build -> frontend/public/nanopitch/
#   ./build.sh --debug    # debug build with assertions enabled
#
# What the flags mean:
#   -O3                    Maximum optimization (smaller + faster WASM)
#   -s WASM=1              Emit WebAssembly (not asm.js)
#   -s EXPORTED_FUNCTIONS   Which C functions to make callable from JS
#   -s EXPORTED_RUNTIME_METHODS  JS helpers for memory access (HEAPF32 etc.)
#   -s ALLOW_MEMORY_GROWTH Allow WASM to allocate more memory as needed
#   -s MODULARIZE          Wrap output in a module (avoids global pollution)
#   -s EXPORT_NAME         Name of the JS constructor function
#   -s ENVIRONMENT=web,worker  Target both browser main-thread and Worker
#                              contexts (EC-1 — the pitchWorker runs in a
#                              dedicated Worker, not the main thread)
#   -s EXPORT_ES6=1         Emit an ES module (`import NanoPitchModule
#                            from "./nanopitch.js"`), matching Vite's
#                            `worker.format: 'es'` and `build.target:
#                            'esnext'` (ELUMS_TECHNICAL_APPROACH.md §13)
#   -lm                    Link the C math library (sin, cos, exp, log)
#
# Oct 8 (EC-1): the prebuilt vendor/nanopitch/web/nanopitch.js was built
# `ENVIRONMENT=web` with a hardcoded `ENVIRONMENT_IS_WORKER=false` baked
# in at build time, so it is untrustworthy inside the pitchWorker (X2).
# Rebuilt here with `ENVIRONMENT=web,worker` and `EXPORT_ES6=1`.
# ===========================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# Retargeted from `../web` (vendor/nanopitch/web/, the upstream reference
# layout) to `frontend/public/nanopitch/`. The `frontend` compose service
# builds from `context: ./frontend` and bind-mounts only
# `./frontend:/app` — nothing under `vendor/` is visible to it, and
# Vite's dev server refuses to serve outside its own root regardless.
# Override with OUT_DIR=... if needed.
OUT_DIR="${OUT_DIR:-$SCRIPT_DIR/../../../frontend/public/nanopitch}"
mkdir -p "$OUT_DIR"

DEBUG=""
OPT="-O3"
if [ "$1" = "--debug" ]; then
    DEBUG="-g -s ASSERTIONS=1"
    OPT="-O0"
fi

echo "Building NanoPitch WASM..."
emcc $OPT $DEBUG \
    -s WASM=1 \
    -s EXPORTED_FUNCTIONS='[
        "_nanopitch_load_weights",
        "_nanopitch_free_weights",
        "_nanopitch_create_state",
        "_nanopitch_free_state",
        "_nanopitch_reset_state",
        "_nanopitch_process_frame",
        "_nanopitch_compute_mel",
        "_malloc",
        "_free"
    ]' \
    -s EXPORTED_RUNTIME_METHODS='["ccall","cwrap","getValue","setValue","HEAPF32"]' \
    -s ALLOW_MEMORY_GROWTH=1 \
    -s INITIAL_MEMORY=16777216 \
    -s MODULARIZE=1 \
    -s EXPORT_NAME="NanoPitchModule" \
    -s ENVIRONMENT=web,worker \
    -s EXPORT_ES6=1 \
    -lm \
    "$SCRIPT_DIR/nanopitch.c" \
    -o "$OUT_DIR/nanopitch.js"

echo "Build complete:"
ls -lh "$OUT_DIR/nanopitch.js" "$OUT_DIR/nanopitch.wasm"
