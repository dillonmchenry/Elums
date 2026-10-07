import { useEffect, useState } from "react";
import { readDiagnostics, subscribeDiagnostics, type DiagnosticValues } from "../audio/diagnostics-channel";

// Thu Oct 8 (X5 of IMPLEMENTATION_PLAN_2026-10-08.md): the real
// diagnostics screen. Two value families, two sources:
//
//   - AudioContext-level facts (sampleRate, baseLatency,
//     outputLatency, crossOriginIsolated, getSettings()) are read
//     fresh on THIS page, from a context/stream opened here — they
//     don't depend on a take being in progress.
//   - Take-derived numbers (X2's RTF, X3's RTT/reliability, X4's
//     ERLE) are produced on `/sing/:id` during a take, on a different
//     route entirely, so they cross routes via
//     `audio/diagnostics-channel.ts`'s localStorage pub/sub rather
//     than React state or a prop.
//
// §5 acceptance #8 ("renders every X5 field with real values on both
// devices") was NOT verified on a real iPad this session — no device
// was available — see PROGRESS.md's Day 6 handoff.

type ConstraintSettings = {
  echoCancellation?: boolean;
  noiseSuppression?: boolean;
  autoGainControl?: boolean;
};

function fmt(value: number | undefined, digits = 1, suffix = ""): string {
  return value === undefined || Number.isNaN(value) ? "—" : `${value.toFixed(digits)}${suffix}`;
}

export function DiagnosticsPage() {
  const [ctxInfo, setCtxInfo] = useState<{
    sampleRate: number;
    baseLatency: number;
    outputLatency: number;
  } | null>(null);
  const [constraints, setConstraints] = useState<ConstraintSettings | null>(null);
  const [micError, setMicError] = useState<string | null>(null);
  const [live, setLive] = useState<DiagnosticValues>(readDiagnostics());

  useEffect(() => {
    const unsub = subscribeDiagnostics(setLive);
    return unsub;
  }, []);

  useEffect(() => {
    // jsdom (the vitest/App.test.tsx environment) has no Web Audio
    // API at all — feature-detect rather than assume a real browser.
    if (typeof AudioContext === "undefined") return;
    const ctx = new AudioContext();
    setCtxInfo({
      sampleRate: ctx.sampleRate,
      baseLatency: ctx.baseLatency ?? NaN,
      outputLatency: ctx.outputLatency ?? NaN,
    });
    ctx.close();
  }, []);

  const checkMic = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
      });
      const track = stream.getAudioTracks()[0];
      setConstraints(track?.getSettings() as ConstraintSettings);
      stream.getTracks().forEach((t) => t.stop());
    } catch (err) {
      setMicError(String(err));
    }
  };

  return (
    <main>
      <h1>Diagnostics</h1>

      <section>
        <h2>AudioContext</h2>
        <ul>
          <li>sampleRate: {ctxInfo ? `${ctxInfo.sampleRate} Hz` : "—"}</li>
          <li>baseLatency: {ctxInfo ? fmt(ctxInfo.baseLatency * 1000, 2, " ms") : "—"}</li>
          <li>outputLatency: {ctxInfo ? fmt(ctxInfo.outputLatency * 1000, 2, " ms") : "—"}</li>
          <li>
            crossOriginIsolated:{" "}
            <strong>{typeof window !== "undefined" && window.crossOriginIsolated ? "true" : "false"}</strong>
          </li>
          <li>SharedArrayBuffer available: <strong>{typeof SharedArrayBuffer !== "undefined" ? "true" : "false"}</strong></li>
        </ul>
      </section>

      <section>
        <h2>Microphone constraints</h2>
        <button type="button" onClick={checkMic}>
          Check getSettings()
        </button>
        {micError && <p role="alert">{micError}</p>}
        {constraints && (
          <ul>
            <li>echoCancellation: {String(constraints.echoCancellation)}</li>
            <li>noiseSuppression: {String(constraints.noiseSuppression)}</li>
            <li>autoGainControl: {String(constraints.autoGainControl)}</li>
          </ul>
        )}
      </section>

      <section>
        <h2>Live take diagnostics (from the most recent take on /sing/:id)</h2>
        <ul>
          <li>X2 pitch-worker RTF: {fmt(live.rtf, 3)}</li>
          <li>X4 measured ERLE: {fmt(live.erleDb, 1, " dB")}</li>
          <li>
            X3 latency offset: {fmt(live.latencyOffsetMs, 1, " ms")}{" "}
            {live.latencyReliable !== undefined && <span>({live.latencyReliable ? "reliable" : "unreliable"})</span>}
          </li>
        </ul>
        <p>These update live via a localStorage channel while a take is recording on another tab/route.</p>
      </section>
    </main>
  );
}
