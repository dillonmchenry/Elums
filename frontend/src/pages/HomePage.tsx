import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  healthzApiHealthzGet,
  meApiMeGet,
  uploadSongApiSongsPost,
  getIngestStatusApiSongsSongIdIngestGet,
} from "../client";
import type { IngestJobPublic, UserPublic } from "../client";

type HealthState =
  | { kind: "loading" }
  | { kind: "ok"; body: Record<string, unknown> }
  | { kind: "error"; message: string };

// Mon Oct 5 (L0): current-user banner, link to /login on 401 — so a
// tester lands here, sees they're logged out, and knows where to go
// rather than hitting an upload form that silently 401s.
type AuthState = { kind: "loading" } | { kind: "authenticated"; user: UserPublic } | { kind: "anonymous" };

// N4 (Oct 4): minimal ingest progress UI — IMPLEMENTATION_PLAN_2026-10-04.md's
// "7 stage labels with status, refreshed every 2s". No upload form existed
// before today; this adds just enough of one to drive the poll, not a real
// song-library page (that is out of today's scope).
const STAGES: Array<{ key: keyof IngestJobPublic; label: string }> = [
  { key: "separation_status", label: "Separation" },
  { key: "structure_beats_status", label: "Structure & beats" },
  { key: "rms_vad_status", label: "Vocal activity" },
  { key: "lyrics_status", label: "Lyrics" },
  { key: "ctc_alignment_status", label: "Alignment" },
  { key: "f0_status", label: "Pitch" },
  { key: "note_grid_status", label: "Note grid" },
];

const POLL_INTERVAL_MS = 2000;

function StageStatus({ job }: { job: IngestJobPublic }) {
  return (
    <ul data-testid="ingest-stages">
      {STAGES.map(({ key, label }) => (
        <li key={key}>
          {label}: {String(job[key])}
        </li>
      ))}
    </ul>
  );
}

export function HomePage() {
  const [health, setHealth] = useState<HealthState>({ kind: "loading" });
  const [auth, setAuth] = useState<AuthState>({ kind: "loading" });
  const [songId, setSongId] = useState<string | null>(null);
  const [job, setJob] = useState<IngestJobPublic | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    healthzApiHealthzGet()
      .then(({ data, error }) => {
        if (error) {
          setHealth({ kind: "error", message: JSON.stringify(error) });
        } else {
          setHealth({ kind: "ok", body: data as Record<string, unknown> });
        }
      })
      .catch((err: unknown) => setHealth({ kind: "error", message: String(err) }));
  }, []);

  useEffect(() => {
    meApiMeGet()
      .then(({ data, error }) => {
        setAuth(!error && data ? { kind: "authenticated", user: data } : { kind: "anonymous" });
      })
      .catch(() => setAuth({ kind: "anonymous" }));
  }, []);

  useEffect(() => {
    if (!songId) return;

    const poll = async () => {
      const { data, error } = await getIngestStatusApiSongsSongIdIngestGet({
        path: { song_id: songId },
      });
      if (!error && data) {
        setJob(data);
        if (data.status === "succeeded" || data.status === "failed") {
          if (pollRef.current) clearInterval(pollRef.current);
        }
      }
    };

    void poll();
    pollRef.current = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [songId]);

  async function handleUpload(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setUploadError(null);
    const form = e.currentTarget;
    const fileInput = form.elements.namedItem("file") as HTMLInputElement;
    const file = fileInput.files?.[0];
    if (!file) return;

    const { data, error } = await uploadSongApiSongsPost({
      body: { file },
    });
    if (error || !data) {
      setUploadError(JSON.stringify(error ?? "upload failed"));
      return;
    }
    setJob(null);
    setSongId(data.id);
  }

  return (
    <main>
      <h1>Elums</h1>
      <p data-testid="health-status">
        {health.kind === "loading" && "Checking API health…"}
        {health.kind === "ok" && `API: ${JSON.stringify(health.body)}`}
        {health.kind === "error" && `API unreachable: ${health.message}`}
      </p>

      <p data-testid="auth-status">
        {auth.kind === "loading" && "Checking login…"}
        {auth.kind === "authenticated" && `Logged in as ${auth.user.display_name}`}
        {auth.kind === "anonymous" && (
          <>
            Not logged in. <Link to="/login">Log in</Link> to upload a song.
          </>
        )}
      </p>

      <form onSubmit={handleUpload}>
        <input type="file" name="file" accept="audio/*" />
        <button type="submit">Upload song</button>
      </form>
      {uploadError && <p role="alert">{uploadError}</p>}

      {job && (
        <section data-testid="ingest-progress">
          <p>Overall status: {job.status}</p>
          {job.message && <p>{job.message}</p>}
          {job.error_message && <p role="alert">{job.error_message}</p>}
          <StageStatus job={job} />
          {/* Tue Oct 6 (T4): once the chain succeeds, link straight to the
              karaoke page — the progress UI's own job is done at that point. */}
          {job.status === "succeeded" && songId && (
            <p>
              <Link to={`/songs/${songId}`}>Play song</Link>
            </p>
          )}
        </section>
      )}
    </main>
  );
}
