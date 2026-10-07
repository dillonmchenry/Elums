// Thu Oct 8 (X0 of IMPLEMENTATION_PLAN_2026-10-08.md): thin wrappers
// around `ringbuf.js`'s SPSC SharedArrayBuffer ring, used to cross the
// audio-thread / worker / main-thread boundaries with no `postMessage`
// and no per-frame allocation (§10.1/§13's zero-allocation rule).
//
// Two distinct rings exist in the graph:
//   - An interleaved-float32 audio ring (AudioWriter/AudioReader, from
//     ringbuf.js directly) carrying mono samples at the device's native
//     sample rate from the AudioWorkletProcessor to a Worker.
//   - A small (t_s, midi) pair ring (below) carrying the live pitch
//     overlay from pitchWorker to the main thread's rAF loop, read
//     into a preallocated typed array behind a ref rather than React
//     state (X2's "one performance trap §13's guarantee does not
//     cover" note).

import { RingBuffer, AudioReader, AudioWriter } from "ringbuf.js";

/** Capacity in samples (mono float32) for the raw/cleaned audio ring
 * feeding a Worker. ~2s at 48kHz is generous slack against a Worker
 * being briefly busy (e.g. a GC pause) without ever blocking the
 * real-time audio thread, which only ever writes and never waits. */
export const AUDIO_RING_CAPACITY_SAMPLES = 48000 * 2;

export function createAudioRingSab(): SharedArrayBuffer {
  return RingBuffer.getStorageForCapacity(AUDIO_RING_CAPACITY_SAMPLES, Float32Array);
}

export function createAudioWriter(sab: SharedArrayBuffer): AudioWriter {
  return new AudioWriter(new RingBuffer(sab, Float32Array));
}

export function createAudioReader(sab: SharedArrayBuffer): AudioReader {
  return new AudioReader(new RingBuffer(sab, Float32Array));
}

/** Pitch-overlay ring: pairs of (t_s, midi) float32s, one pair per
 * voiced NanoPitch frame (10ms hop). Capacity is generous (10 minutes
 * of voiced frames) since the ring only needs to survive one take and
 * each pair is 8 bytes. */
export const PITCH_RING_CAPACITY_PAIRS = 100 * 60 * 10;

export function createPitchRingSab(): SharedArrayBuffer {
  return RingBuffer.getStorageForCapacity(PITCH_RING_CAPACITY_PAIRS * 2, Float32Array);
}

export class PitchRingWriter {
  private writer: AudioWriter;
  private scratch = new Float32Array(2);

  constructor(sab: SharedArrayBuffer) {
    this.writer = new AudioWriter(new RingBuffer(sab, Float32Array));
  }

  /** Push one (t_s, midi) pair. Drops the pair if the ring is full
   * rather than blocking — the live lane can tolerate an occasional
   * dropped point, it cannot tolerate a stall. */
  push(tS: number, midi: number): void {
    this.scratch[0] = tS;
    this.scratch[1] = midi;
    this.writer.enqueue(this.scratch);
  }
}

export class PitchRingReader {
  private reader: AudioReader;
  private scratch: Float32Array;

  constructor(sab: SharedArrayBuffer, scratchPairs = 64) {
    this.reader = new AudioReader(new RingBuffer(sab, Float32Array));
    this.scratch = new Float32Array(scratchPairs * 2);
  }

  /** Drain all currently-available pairs into `out` (a preallocated
   * ring-backed typed array owned by the caller), calling `onPair` for
   * each. Allocates nothing per call beyond the fixed `scratch` buffer
   * reused every time. */
  drain(onPair: (tS: number, midi: number) => void): number {
    let total = 0;
    for (;;) {
      const read = this.reader.dequeue(this.scratch);
      if (read === 0) break;
      for (let i = 0; i < read; i += 2) {
        onPair(this.scratch[i], this.scratch[i + 1]);
      }
      total += read / 2;
      if (read < this.scratch.length) break;
    }
    return total;
  }
}
