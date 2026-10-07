// Thu Oct 8 (X1 of IMPLEMENTATION_PLAN_2026-10-08.md): iOS/iPadOS
// Safari's audio-session dance (ELUMS_TECHNICAL_APPROACH.md §10.4).
// `navigator.audioSession` is a real but non-standard, feature-detect-
// only API (Safari-specific); everything here is a no-op on any
// browser that doesn't implement it, so this is safe to call
// unconditionally on every platform.
//
// NOT verified on a real iPad this session (no iOS device available —
// same limitation PROGRESS.md's Day 3/4/5 entries already recorded for
// audio playback/capture testing). The sequencing below follows §10.4's
// text exactly; it has not been confirmed to produce the described
// effect on real hardware.

type AudioSessionType = "auto" | "playback" | "play-and-record" | "transient" | "transient-solo" | "ambient";

interface NavigatorWithAudioSession extends Navigator {
  audioSession?: { type: AudioSessionType };
}

function getAudioSession(): { type: AudioSessionType } | null {
  const nav = navigator as NavigatorWithAudioSession;
  return nav.audioSession ?? null;
}

export function supportsAudioSession(): boolean {
  return getAudioSession() !== null;
}

/** Call BEFORE `getUserMedia`. §10.4: "the working order is
 * `audioSession.type = 'auto'` -> `getUserMedia` -> `'play-and-record'`." */
export function setAudioSessionAuto(): void {
  const session = getAudioSession();
  if (session) session.type = "auto";
}

/** Call immediately AFTER `getUserMedia` resolves. */
export function setAudioSessionPlayAndRecord(): void {
  const session = getAudioSession();
  if (session) session.type = "play-and-record";
}

/** Call on teardown (stop recording / leave the page). §10.4: "on
 * teardown `'playback'` then immediately `'auto'`, or output fidelity
 * stays degraded." */
export function teardownAudioSession(): void {
  const session = getAudioSession();
  if (!session) return;
  session.type = "playback";
  session.type = "auto";
}

export type CaptureTier = "worklet" | "media-recorder" | "unsupported";

/** X1's capture fallback ladder: worklet -> MediaRecorder -> explicit
 * banner, so a WebKit refusal degrades instead of blanking (§10.4/§1's
 * risk register item 1). Feature-detects rather than UA-sniffs. */
export function detectCaptureTier(): CaptureTier {
  // `audioWorklet` is a native getter on `BaseAudioContext.prototype`
  // (`[SameObject] readonly attribute AudioWorklet audioWorklet`).
  // Reading it via `AudioContext.prototype.audioWorklet` INVOKES that
  // getter with `this` bound to the bare prototype object, which has
  // no internal native slots — Chrome throws `TypeError: Illegal
  // invocation`, not `undefined`. Use `in` (a property-existence
  // check, never a call) instead.
  const hasWorkletSupport =
    typeof AudioContext !== "undefined" &&
    "audioWorklet" in AudioContext.prototype &&
    typeof SharedArrayBuffer !== "undefined" &&
    typeof self !== "undefined" &&
    (self as unknown as { crossOriginIsolated?: boolean }).crossOriginIsolated === true;
  if (hasWorkletSupport) return "worklet";
  if (typeof MediaRecorder !== "undefined") return "media-recorder";
  return "unsupported";
}
