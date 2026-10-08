import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import {
  getPerformanceApiPerformancesPerformanceIdGet,
  getPerformanceCardsApiPerformancesPerformanceIdCardsGet,
  getSongBundleApiSongsSongIdGet,
  listSeedsApiSongsSongIdSeedsGet,
  publishSeedApiPerformancesPerformanceIdPublishSeedPost,
} from "../client";
import type { CardSchema, PerformancePublic } from "../client";
import { PitchLane } from "../components/PitchLane";
import { f0TrackToOverlay, unpackF0Blob } from "../audio/npz";

// Wed Oct 7 (W5/W6 of IMPLEMENTATION_PLAN_2026-10-07.md): a single
// take's results — overall score, per-note coloring against §6.2's
// bands via the server-persisted analysis blob, and "publish as a
// seed" (§7.3's async seed/join, taken by a plain POST once scoring has
// succeeded).
//
// Fri Oct 9 (F7 of IMPLEMENTATION_PLAN_2026-10-09.md): coaching cards,
// grouped by VocalCoachBench's 7 categories, each clickable to seek the
// take's own audio and the pitch lane's playhead to the card's
// `start_s` — and the f0 overlay Day 5 left unfed, now unpacked
// client-side from the take's own `f0_blob_sha256` (`../audio/npz.ts`).

type ChartNote = { start_s: number; end_s: number; midi: number; is_vocable: boolean };
type Chart = { duration_s: number; notes: ChartNote[] };
type NoteScore = { note_index: number; pct_in_tune: number | null };

const POLL_INTERVAL_MS = 2000;
// VocalCoachBench's 7 categories (§6.4), display order kept stable
// regardless of which categories a given take actually fired cards in
// — an empty category section is simply omitted, not reordered.
const CATEGORY_ORDER = ["PITCH", "RHYTHM", "DICTION", "BREATH", "VOCALIZATION", "TECHNIQUE", "EXPRESSION"];

async function fetchBlobJson<T>(sha256: string): Promise<T> {
  const res = await fetch(`/blobs/${sha256.slice(0, 2)}/${sha256.slice(2, 4)}/${sha256}`);
  if (!res.ok) throw new Error(`blob fetch failed: ${res.status}`);
  return (await res.json()) as T;
}

async function fetchBlobBytes(sha256: string): Promise<ArrayBuffer> {
  const res = await fetch(`/blobs/${sha256.slice(0, 2)}/${sha256.slice(2, 4)}/${sha256}`);
  if (!res.ok) throw new Error(`blob fetch failed: ${res.status}`);
  return await res.arrayBuffer();
}

function blobUrl(sha256: string): string {
  return `/blobs/${sha256.slice(0, 2)}/${sha256.slice(2, 4)}/${sha256}`;
}

function groupCardsByCategory(cards: CardSchema[]): Map<string, CardSchema[]> {
  const groups = new Map<string, CardSchema[]>();
  for (const category of CATEGORY_ORDER) groups.set(category, []);
  for (const card of cards) {
    if (!groups.has(card.category)) groups.set(card.category, []);
    groups.get(card.category)!.push(card);
  }
  return groups;
}

function CardList({ cards, onSeek }: { cards: CardSchema[]; onSeek: (startS: number) => void }) {
  const groups = groupCardsByCategory(cards);
  const nonEmpty = [...groups.entries()].filter(([, list]) => list.length > 0);

  if (nonEmpty.length === 0) return null;

  return (
    <section data-testid="coaching-cards">
      <h2>Coaching cards</h2>
      {nonEmpty.map(([category, categoryCards]) => (
        <div key={category} data-testid={`card-category-${category}`}>
          <h3>{category}</h3>
          <ul>
            {categoryCards.map((card) => (
              <li key={card.card_id}>
                <button
                  type="button"
                  data-testid="coaching-card"
                  data-card-type={card.type}
                  onClick={() => onSeek(card.start_s)}
                  style={{
                    display: "block",
                    width: "100%",
                    textAlign: "left",
                    marginBottom: "4px",
                    borderLeft: card.direction === "issue" ? "3px solid #d94f4f" : card.direction === "affirming" ? "3px solid #2e9e4f" : "3px solid #777",
                  }}
                >
                  {card.text}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </section>
  );
}

export function PerformancePage() {
  const { id } = useParams<{ id: string }>();
  const [performance, setPerformance] = useState<PerformancePublic | null>(null);
  const [chart, setChart] = useState<Chart | null>(null);
  const [noteScores, setNoteScores] = useState<NoteScore[] | null>(null);
  const [seedCount, setSeedCount] = useState<number | null>(null);
  const [published, setPublished] = useState(false);
  const [cards, setCards] = useState<CardSchema[]>([]);
  const [f0Overlay, setF0Overlay] = useState<{ t_s: number; midi: number }[] | undefined>(undefined);
  const [currentTimeS, setCurrentTimeS] = useState(0);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const poll = async () => {
      const { data, error } = await getPerformanceApiPerformancesPerformanceIdGet({
        path: { performance_id: id },
      });
      if (cancelled) return;
      if (!error && data) {
        setPerformance(data);
        if (data.status !== "succeeded" && data.status !== "failed") {
          timer = setTimeout(poll, POLL_INTERVAL_MS);
        } else if (data.status === "succeeded") {
          const bundleResp = await getSongBundleApiSongsSongIdGet({ path: { song_id: data.song_id } });
          if (bundleResp.data?.chart_blob_sha256) {
            const chartData = await fetchBlobJson<Chart>(bundleResp.data.chart_blob_sha256);
            if (!cancelled) setChart(chartData);
          }
          if (data.analysis_blob_sha256) {
            const analysis = await fetchBlobJson<{ notes: NoteScore[] }>(data.analysis_blob_sha256);
            if (!cancelled) setNoteScores(analysis.notes);
          }
          // F7: the server-computed f0 track, unpacked client-side —
          // `../audio/npz.ts`'s own module docstring explains why this
          // is a hand-rolled reader rather than a dependency.
          if (data.f0_blob_sha256) {
            try {
              const bytes = await fetchBlobBytes(data.f0_blob_sha256);
              const track = unpackF0Blob(bytes);
              if (!cancelled) setF0Overlay(f0TrackToOverlay(track));
            } catch (err) {
              // Non-fatal: the overlay is a nice-to-have on top of the
              // per-note coloring that already works without it.
              console.warn("f0 overlay unavailable", err);
            }
          }
          // F7: coaching cards, recomputed fresh server-side on every
          // request per the owner's own decision (PROGRESS.md Day 7
          // Session B §9.3) — no caching here either.
          const cardsResp = await getPerformanceCardsApiPerformancesPerformanceIdCardsGet({
            path: { performance_id: id },
          });
          if (!cancelled && cardsResp.data) setCards(cardsResp.data);

          const seeds = await listSeedsApiSongsSongIdSeedsGet({ path: { song_id: data.song_id } });
          if (!cancelled && seeds.data) setSeedCount(seeds.data.length);
        }
      }
    };
    void poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [id]);

  async function handlePublish() {
    if (!id) return;
    const { data } = await publishSeedApiPerformancesPerformanceIdPublishSeedPost({
      path: { performance_id: id },
    });
    if (data) {
      setPerformance(data);
      setPublished(true);
    }
  }

  // Click-to-seek: moves the real <audio> element's playhead, which in
  // turn drives `currentTimeS` (and so the pitch lane's playhead) via
  // the `timeupdate` listener below — one source of truth, not two
  // separately-set positions that could drift apart.
  function handleCardSeek(startS: number) {
    const audio = audioRef.current;
    if (!audio) return;
    audio.currentTime = startS;
    void audio.play();
  }

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    const onTimeUpdate = () => setCurrentTimeS(audio.currentTime);
    audio.addEventListener("timeupdate", onTimeUpdate);
    return () => audio.removeEventListener("timeupdate", onTimeUpdate);
  }, [performance?.audio_blob_sha256]);

  if (!performance) return <p>Loading…</p>;

  return (
    <main>
      <h1>Performance results</h1>
      <p>Status: {performance.status}</p>
      {performance.error_message && <p role="alert">{performance.error_message}</p>}

      {performance.status === "succeeded" && (
        <section data-testid="performance-results">
          <p>
            Overall score: <strong>{((performance.score_overall ?? 0) * 100).toFixed(1)}%</strong>
          </p>
          <p>In tune: {((performance.pct_in_tune ?? 0) * 100).toFixed(1)}%</p>
          {performance.octave_shift_semitones !== 0 && (
            <p>Octave shift detected: {performance.octave_shift_semitones} semitones</p>
          )}
          {performance.alignment_warning && (
            <p role="alert" data-testid="alignment-warning">
              We couldn't confidently align this take to the chart — the score above may not be reliable.
            </p>
          )}

          {performance.audio_blob_sha256 && (
            <audio
              ref={audioRef}
              data-testid="take-audio"
              controls
              src={blobUrl(performance.audio_blob_sha256)}
              style={{ display: "block", width: "100%", marginBottom: "8px" }}
            />
          )}

          {chart && (
            <PitchLane
              notes={chart.notes}
              durationS={chart.duration_s}
              width={800}
              scores={noteScores ?? undefined}
              f0Overlay={f0Overlay}
              currentTimeS={currentTimeS}
            />
          )}

          <CardList cards={cards} onSeek={handleCardSeek} />

          {performance.kind === "solo" && !published && (
            <button type="button" onClick={handlePublish}>
              Publish as a joinable seed
            </button>
          )}
          {performance.kind === "seed" && <p>This take is published as a seed.</p>}
          {seedCount !== null && <p>{seedCount} seed performance(s) exist for this song.</p>}
        </section>
      )}
    </main>
  );
}
