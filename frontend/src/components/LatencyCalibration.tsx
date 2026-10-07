import { useCallback, useEffect, useRef, useState } from "react";
// Thu Oct 8 (X3 of IMPLEMENTATION_PLAN_2026-10-08.md): round-trip
// latency calibration via `@adasp/latency-test`'s `<latency-test>` web
// component — MLS + cross-correlation, gated on the 18dB reliability
// ratio (§10.4). Runs on the **main** `AudioContext` the caller passes
// in (not a throwaway one) and the **full measured round-trip** — both
// named in §10.4 as the two things a naive implementation gets wrong
// ("subtracting outputLatency was a formula bug").
//
// Calibrate AFTER the mic is open (§10.4: Bluetooth renegotiates
// A2DP->HFP the moment `getUserMedia` is called, changing both latency
// and mic bandwidth) — enforced here by requiring the caller to pass
// an already-open `MediaStream`.
import "@adasp/latency-test";

const RELIABILITY_GATE_DB = 18;
const NUMBER_OF_TESTS = 3;

type Props = {
  audioContext: AudioContext;
  inputStream: MediaStream;
  onCalibrated: (offsetMs: number) => void;
};

type CalibrationState =
  | { kind: "idle" }
  | { kind: "running" }
  | { kind: "succeeded"; meanMs: number; reliable: boolean }
  | { kind: "failed"; message: string };

export function LatencyCalibration({ audioContext, inputStream, onCalibrated }: Props) {
  const [state, setState] = useState<CalibrationState>({ kind: "idle" });
  const elRef = useRef<InstanceType<typeof HTMLElement> | null>(null);

  useEffect(() => {
    const el = elRef.current as unknown as {
      audioContext: AudioContext | null;
      inputStream: MediaStream | null;
      numberOfTests: number;
      start: () => Promise<void>;
      addEventListener: (type: string, cb: (e: Event) => void) => void;
      removeEventListener: (type: string, cb: (e: Event) => void) => void;
    } | null;
    if (!el) return;
    el.audioContext = audioContext;
    el.inputStream = inputStream;
    el.numberOfTests = NUMBER_OF_TESTS;

    const onComplete = (e: Event) => {
      const detail = (e as CustomEvent<{ mean: number; results: { reliable: boolean }[] }>).detail;
      const allReliable = detail.results.every((r) => r.reliable);
      setState({ kind: "succeeded", meanMs: detail.mean, reliable: allReliable });
      if (allReliable) onCalibrated(detail.mean);
    };
    const onError = (e: Event) => {
      const detail = (e as CustomEvent<{ message: string }>).detail;
      setState({ kind: "failed", message: detail.message });
    };
    el.addEventListener("latency-complete", onComplete);
    el.addEventListener("latency-error", onError);
    return () => {
      el.removeEventListener("latency-complete", onComplete);
      el.removeEventListener("latency-error", onError);
    };
  }, [audioContext, inputStream, onCalibrated]);

  const run = useCallback(async () => {
    const el = elRef.current as unknown as { start: () => Promise<void> } | null;
    if (!el) return;
    setState({ kind: "running" });
    await el.start();
  }, []);

  return (
    <div data-testid="latency-calibration">
      {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
      {/* @ts-expect-error -- custom element, typed via index.d.ts from @adasp/latency-test at runtime only */}
      <latency-test ref={elRef} number-of-tests={NUMBER_OF_TESTS}></latency-test>
      <button type="button" onClick={run} disabled={state.kind === "running"}>
        {state.kind === "running" ? "Calibrating…" : "Calibrate latency"}
      </button>
      {state.kind === "succeeded" && (
        <p>
          Mean round-trip latency: {state.meanMs.toFixed(1)}ms{" "}
          {state.reliable ? `(reliable, ≥${RELIABILITY_GATE_DB}dB)` : "(NOT reliable — try again or use the manual nudge)"}
        </p>
      )}
      {state.kind === "failed" && <p role="alert">Calibration failed: {state.message}</p>}
    </div>
  );
}
