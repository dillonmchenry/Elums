import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getSongProgressApiSongsSongIdProgressGet } from "../client";
import type { SongProgressSchema } from "../client";

// F8 (Session C, IMPLEMENTATION_PLAN_2026-10-09.md): one user's
// progress on one song, per ELUMS_TECHNICAL_APPROACH.md §6.5 --
// personal best as the hero metric, a gated three-way verdict with
// explicit "sing N more" copy below the gate, per-dimension trends
// (not one composite), and an IQR band that widens when recent
// sessions span more than one recording device.

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; progress: SongProgressSchema };

const DIMENSION_LABELS: Record<string, string> = {
  pct_in_tune: "Pitch accuracy (% in tune)",
  pitch_accuracy: "Pitch deviation (cents)",
  timing_accuracy: "Timing accuracy (ms)",
};

const VERDICT_COPY: Record<string, string> = {
  improving: "Improving",
  holding_steady: "Holding steady",
  declining: "Declining",
  insufficient_data: "Not enough data yet",
};

function VerdictBadge({ verdict, performancesNeeded }: { verdict: string; performancesNeeded: number }) {
  if (verdict === "insufficient_data") {
    return (
      <p data-testid="progress-verdict">
        {VERDICT_COPY[verdict]} -- sing {performancesNeeded} more take{performancesNeeded === 1 ? "" : "s"} of this
        song to see a trend.
      </p>
    );
  }
  return <p data-testid="progress-verdict">{VERDICT_COPY[verdict] ?? verdict}</p>;
}

function TrendRow({
  label,
  trend,
}: {
  label: string;
  trend: SongProgressSchema["dimensions"][string];
}) {
  return (
    <li data-testid="progress-dimension-row">
      <strong>{label}:</strong> <VerdictBadge verdict={trend.verdict} performancesNeeded={trend.performances_needed} />
      {trend.rolling_median !== null && (
        <span>
          {" "}
          (recent median {trend.rolling_median.toFixed(2)}
          {trend.iqr_low !== null && trend.iqr_high !== null
            ? `, band [${trend.iqr_low.toFixed(2)}, ${trend.iqr_high.toFixed(2)}]`
            : ""}
          {trend.band_widen_factor > 1 ? " -- widened, device changed recently" : ""})
        </span>
      )}
    </li>
  );
}

export function ProgressPage() {
  const { id } = useParams<{ id: string }>();
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  useEffect(() => {
    if (!id) return;
    let cancelled = false;

    (async () => {
      const { data, error } = await getSongProgressApiSongsSongIdProgressGet({ path: { song_id: id } });
      if (error || !data) {
        if (!cancelled) setState({ kind: "error", message: "Could not load progress for this song." });
        return;
      }
      if (!cancelled) setState({ kind: "ready", progress: data });
    })();

    return () => {
      cancelled = true;
    };
  }, [id]);

  if (state.kind === "loading") return <p>Loading…</p>;
  if (state.kind === "error") return <p role="alert">{state.message}</p>;

  const { progress } = state;

  if (progress.performance_count === 0) {
    return (
      <main>
        <h1>Progress</h1>
        <p>No scored takes of this song yet.</p>
        <Link to={`/songs/${id}/sing`}>Sing it for the first time</Link>
      </main>
    );
  }

  return (
    <main>
      <h1>Progress</h1>
      <p data-testid="progress-performance-count">{progress.performance_count} scored takes</p>

      {progress.personal_best_score_overall !== null && (
        <p data-testid="progress-personal-best">
          <strong>Personal best on this song:</strong> {(progress.personal_best_score_overall * 100).toFixed(0)}%
        </p>
      )}

      {progress.overall && (
        <section data-testid="progress-overall">
          <h2>Overall</h2>
          <VerdictBadge verdict={progress.overall.verdict} performancesNeeded={progress.overall.performances_needed} />
          <p>
            Normalized for song difficulty via{" "}
            {progress.normalization === "per_song_zscore" ? "this song's own score distribution" : "an online Elo-style estimate"}
            .
          </p>
        </section>
      )}

      <section data-testid="progress-dimensions">
        <h2>By dimension</h2>
        <ul>
          {Object.entries(progress.dimensions).map(([key, trend]) => (
            <TrendRow key={key} label={DIMENSION_LABELS[key] ?? key} trend={trend} />
          ))}
        </ul>
      </section>

      {!progress.device_label_consistent && (
        <p role="status">Recent sessions used more than one recording device -- bands above are widened to reflect that.</p>
      )}

      <Link to={`/songs/${id}`}>Back to song</Link>
    </main>
  );
}
