// Thu Oct 8 (X0 of IMPLEMENTATION_PLAN_2026-10-08.md): the encode +
// upload worker. Drains the cleaned-signal audio ring (written by
// capture-worklet.ts) at the device's native sample rate, converts to
// 16-bit PCM (X0's own "unresolved interface decision," resolved as
// option (a) — headerless PCM chunks, server prepends the WAV header
// once total length is known; see elums/ingest/wav.py's docstring),
// and PUTs each ~1s chunk to `/api/performances/{id}/chunks/{index}`
// in upload order, same chunk cadence `MediaRecorder`'s
// `CHUNK_TIMESLICE_MS` used.

import { createAudioReader } from "./ring";
import { floatTo16BitPCM } from "./wav";
import { computeErleDb } from "./aec";

export type EncodeWorkerInit = {
  cleanedRingSab: SharedArrayBuffer;
  // Optional: the raw (pre-AEC) mic ring. When present, this worker is
  // the SAB's single consumer and periodically computes X5's
  // client-estimated ERLE from paired raw/cleaned windows, posting it
  // back to the main thread rather than giving the SPSC raw ring a
  // second reader (see capture-worklet.ts's SPSC note).
  rawRingSab?: SharedArrayBuffer;
  performanceId: string;
  deviceSampleRate: number;
  chunkDurationMs?: number;
};

let running = false;

self.onmessage = (event: MessageEvent<{ type: string } & Partial<EncodeWorkerInit>>) => {
  const msg = event.data;
  if (msg.type === "init") {
    running = true;
    runLoop(msg as EncodeWorkerInit & { type: "init" });
  } else if (msg.type === "stop") {
    running = false;
  }
};

async function runLoop(init: EncodeWorkerInit): Promise<void> {
  const reader = createAudioReader(init.cleanedRingSab);
  const rawReader = init.rawRingSab ? createAudioReader(init.rawRingSab) : null;
  const rawScratch = new Float32Array(4096);
  const chunkSamples = Math.round(init.deviceSampleRate * ((init.chunkDurationMs ?? 1000) / 1000));
  const scratch = new Float32Array(4096);
  let pending: number[] = [];
  let pendingRaw: number[] = [];
  let chunkIndex = 0;
  let uploadedBytes = 0;

  // Separate from `poll`'s per-chunk cadence: sample raw vs. cleaned
  // once a second purely for the live ERLE number, independent of
  // upload chunking.
  function sampleErle(cleanedWindow: number[]): void {
    if (!rawReader) return;
    const available = rawReader.available_read();
    if (available === 0) return;
    const toRead = Math.min(available, rawScratch.length);
    const read = rawReader.dequeue(rawScratch.subarray(0, toRead));
    for (let i = 0; i < read; i++) pendingRaw.push(rawScratch[i]);
    const n = Math.min(pendingRaw.length, cleanedWindow.length, 16000);
    if (n < 4000) return; // need enough samples for a stable estimate
    const erleDb = computeErleDb(Float32Array.from(pendingRaw.slice(0, n)), Float32Array.from(cleanedWindow.slice(0, n)));
    pendingRaw = pendingRaw.slice(n);
    self.postMessage({ type: "erle", erleDb });
  }

  async function flushChunk(samples: number[]): Promise<void> {
    const pcm = floatTo16BitPCM(Float32Array.from(samples));
    const index = chunkIndex++;
    uploadedBytes += pcm.byteLength;
    // `pcm.buffer` is always a plain (non-shared) ArrayBuffer at
    // runtime — it comes from `Float32Array.from(samples)` on a
    // regular `number[]`, never from a SharedArrayBuffer-backed view —
    // but TS's lib types it as the generic `ArrayBufferLike` union, so
    // `fetch`'s `BodyInit` (which excludes `SharedArrayBuffer`) needs
    // an explicit assertion here.
    await fetch(`/api/performances/${init.performanceId}/chunks/${index}`, {
      method: "PUT",
      body: pcm.buffer as ArrayBuffer,
      credentials: "include",
    });
    self.postMessage({ type: "chunk-uploaded", index, uploadedBytes });
  }

  async function poll(): Promise<void> {
    const available = reader.available_read();
    if (available > 0) {
      const toRead = Math.min(available, scratch.length);
      const read = reader.dequeue(scratch.subarray(0, toRead));
      for (let i = 0; i < read; i++) pending.push(scratch[i]);
      sampleErle(pending);
      while (pending.length >= chunkSamples) {
        const toFlush = pending.slice(0, chunkSamples);
        pending = pending.slice(chunkSamples);
        await flushChunk(toFlush);
      }
    }
    if (running) {
      setTimeout(poll, 10);
    } else {
      // Drain + flush any final partial chunk, then signal done.
      const finalAvailable = reader.available_read();
      if (finalAvailable > 0) {
        const toRead = Math.min(finalAvailable, scratch.length);
        const read = reader.dequeue(scratch.subarray(0, toRead));
        for (let i = 0; i < read; i++) pending.push(scratch[i]);
      }
      if (pending.length > 0) await flushChunk(pending);
      self.postMessage({ type: "done", chunkCount: chunkIndex, uploadedBytes });
    }
  }
  poll();
}
