// Thu Oct 8 (X5 of IMPLEMENTATION_PLAN_2026-10-08.md): a small
// `localStorage`-backed pub/sub channel so values produced during a
// take on `/sing/:id` (X2's live RTF, X3's measured RTT/reliability,
// X4's measured ERLE) can be read on `/diagnostics`, a different
// route entirely. `localStorage` (not a ring, not a context) is
// deliberate — these are a handful of scalars updated a few times a
// second at most, cross-tab/cross-route, and `storage` events give
// `/diagnostics` live updates for free with zero polling.

export type DiagnosticValues = {
  rtf?: number;
  erleDb?: number;
  latencyOffsetMs?: number;
  latencyReliable?: boolean;
};

const STORAGE_KEY = "elums.diagnostics.v1";

export function publishDiagnostic(patch: Partial<DiagnosticValues>): void {
  const current = readDiagnostics();
  const next = { ...current, ...patch };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
}

export function readDiagnostics(): DiagnosticValues {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as DiagnosticValues) : {};
  } catch {
    return {};
  }
}

/** Subscribe to live updates. Returns an unsubscribe function. */
export function subscribeDiagnostics(onChange: (values: DiagnosticValues) => void): () => void {
  const handler = (event: StorageEvent) => {
    if (event.key === STORAGE_KEY) onChange(readDiagnostics());
  };
  window.addEventListener("storage", handler);
  return () => window.removeEventListener("storage", handler);
}
