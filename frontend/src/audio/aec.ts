// Thu Oct 8 (X4 of IMPLEMENTATION_PLAN_2026-10-08.md): the adaptive
// filter itself, split out from capture-worklet.ts so it can be unit
// tested on synthetic signals with no AudioWorklet/browser dependency
// (plan §5 acceptance check 10: "the FDAF's frequency-domain block
// math on synthetic signals. No WASM module and no microphone in a
// unit test"). See capture-worklet.ts's own header comment for the
// full design rationale and the documented reduction from a
// partitioned-block frequency-domain filter to this time-domain NLMS
// filter.

const FILTER_LENGTH = 1024;
const NLMS_STEP_SIZE = 0.5; // normalized step (0 < mu < 2), conservative for stability
const NLMS_EPSILON = 1e-6; // regularization against near-silent reference frames

export class AdaptiveEchoCanceller {
  private readonly weights = new Float32Array(FILTER_LENGTH);
  private readonly refHistory = new Float32Array(FILTER_LENGTH);
  private historyPos = 0;
  private frozen = false;

  freeze(): void {
    this.frozen = true;
  }

  isFrozen(): boolean {
    return this.frozen;
  }

  /** Sum of squared weights — a cheap scalar proxy for "did the
   * filter change," used only by tests (freeze() should hold this
   * exactly constant across subsequent `step()` calls). */
  weightsEnergy(): number {
    let energy = 0;
    for (const w of this.weights) energy += w * w;
    return energy;
  }

  /** Called once per sample pair as they arrive. Updates `refHistory`
   * regardless of freeze state (the filter still needs current
   * reference context to subtract even when frozen); only the weight
   * update is gated by `frozen`. Returns the cleaned (error) sample:
   * `micSample - estimate`, i.e. strict linear subtraction with no
   * suppressor or spectral floor (§10.3). */
  step(micSample: number, refSample: number): number {
    this.refHistory[this.historyPos] = refSample;

    // Estimate = dot(weights, refHistory), read oldest-to-newest via
    // the ring position so index 0 of `weights` always means "most
    // recent reference sample."
    let estimate = 0;
    let energy = NLMS_EPSILON;
    for (let i = 0; i < FILTER_LENGTH; i++) {
      const idx = (this.historyPos - i + FILTER_LENGTH) % FILTER_LENGTH;
      const r = this.refHistory[idx];
      estimate += this.weights[i] * r;
      energy += r * r;
    }

    const error = micSample - estimate; // this is the cleaned sample

    if (!this.frozen) {
      const gain = (NLMS_STEP_SIZE * error) / energy;
      for (let i = 0; i < FILTER_LENGTH; i++) {
        const idx = (this.historyPos - i + FILTER_LENGTH) % FILTER_LENGTH;
        this.weights[i] += gain * this.refHistory[idx];
      }
    }

    this.historyPos = (this.historyPos + 1) % FILTER_LENGTH;
    return error;
  }
}

/** ERLE (Echo Return Loss Enhancement) in dB: 10*log10(refPower /
 * residualPower) over matched-length raw/cleaned sample arrays.
 * Shared by the worklet's own client-side diagnostics estimate (X5)
 * and by this module's own convergence test. */
export function computeErleDb(raw: Float32Array, cleaned: Float32Array): number {
  let rawPower = 0;
  let cleanedPower = 0;
  const n = Math.min(raw.length, cleaned.length);
  for (let i = 0; i < n; i++) {
    rawPower += raw[i] * raw[i];
    cleanedPower += cleaned[i] * cleaned[i];
  }
  rawPower /= n;
  cleanedPower /= n;
  if (cleanedPower <= 0) return Infinity;
  return 10 * Math.log10(rawPower / cleanedPower);
}
