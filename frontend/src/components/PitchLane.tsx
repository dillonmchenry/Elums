import { useEffect, useRef } from "react";

// Wed Oct 7 (W5 of IMPLEMENTATION_PLAN_2026-10-07.md): Canvas 2D, not
// WebGL or SVG — §13's own instruction ("the lane needs tens of draws
// per frame, not thousands; Canvas 2D handles 1,000-3,000 at 60fps").
// Replaces SongPage.tsx's static SVG `NoteLane` entirely, per the
// plan's own "replaced, not extended" instruction.
//
// Zero allocation in the frame loop: every array this component reads
// is pre-computed by the caller (ChartNote[]/NoteScore[] are already
// plain arrays) and the draw loop itself allocates nothing — no new
// arrays, no closures created per frame, same discipline §13 asks for
// even though real-time capture here uses the MediaRecorder fallback
// (see SingPage.tsx's own docstring for why), not an AudioWorklet.

export type LaneNote = {
  start_s: number;
  end_s: number;
  midi: number;
  is_vocable?: boolean;
};

export type NoteScore = {
  note_index: number;
  pct_in_tune: number | null;
};

type Props = {
  notes: LaneNote[];
  durationS: number;
  width: number;
  height?: number;
  currentTimeS?: number;
  /** Per-note scoring (same index order as `notes`) — colors each note
   * by §6.2's bands instead of the default pitch color. Omit for the
   * plain pre-performance chart view. */
  scores?: NoteScore[];
  /** Server-computed f0 overlay, already resampled to (t_s, midi) pairs
   * by the caller — drawn as a thin continuous line over the note
   * blocks, per T4/W5's "overlays the server-computed f0 on playback." */
  f0Overlay?: { t_s: number; midi: number }[];
};

const DEFAULT_HEIGHT = 140;
const MIDI_RANGE = 24;
const MAX_DEVICE_PIXEL_RATIO = 2; // §13: cap devicePixelRatio at 2

function colorForPctInTune(pct: number | null): string {
  if (pct === null) return "#2d6cdf";
  if (pct >= 0.7) return "#2e9e4f"; // green
  if (pct >= 0.4) return "#e0a500"; // yellow
  return "#d94f4f"; // red
}

export function PitchLane({ notes, durationS, width, height = DEFAULT_HEIGHT, currentTimeS, scores, f0Overlay }: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  // Pre-allocated once per `notes`/`scores` identity change — never
  // recomputed inside the draw loop itself.
  const scoreByIndex = useRef<Map<number, number | null>>(new Map());

  useEffect(() => {
    const map = new Map<number, number | null>();
    for (const s of scores ?? []) map.set(s.note_index, s.pct_in_tune);
    scoreByIndex.current = map;
  }, [scores]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const dpr = Math.min(window.devicePixelRatio || 1, MAX_DEVICE_PIXEL_RATIO);
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const duration = durationS || 1;
    const midiValues = notes.map((n) => n.midi);
    const centerMidi = midiValues.length
      ? midiValues.slice().sort((a, b) => a - b)[Math.floor(midiValues.length / 2)]
      : 60;
    const minMidi = centerMidi - MIDI_RANGE / 2;
    const xFor = (t: number) => (t / duration) * width;
    const yFor = (midi: number) => height - ((midi - minMidi) / MIDI_RANGE) * height;

    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = "#0b1320";
    ctx.fillRect(0, 0, width, height);

    for (const note of notes) {
      const x0 = xFor(note.start_s);
      const x1 = xFor(note.end_s);
      const y = yFor(note.midi);
      const idx = notes.indexOf(note);
      const pct = scoreByIndex.current.get(idx) ?? null;
      ctx.fillStyle = note.is_vocable ? "#777" : scores ? colorForPctInTune(pct) : "#2d6cdf";
      ctx.fillRect(x0, y - 2, Math.max(1, x1 - x0), 4);
    }

    if (f0Overlay && f0Overlay.length > 1) {
      ctx.strokeStyle = "#ffffffaa";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      let started = false;
      for (const point of f0Overlay) {
        if (point.midi <= 0) {
          started = false;
          continue;
        }
        const x = xFor(point.t_s);
        const y = yFor(point.midi);
        if (!started) {
          ctx.moveTo(x, y);
          started = true;
        } else {
          ctx.lineTo(x, y);
        }
      }
      ctx.stroke();
    }

    if (currentTimeS !== undefined) {
      const x = xFor(currentTimeS);
      ctx.strokeStyle = "#ffffff";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, height);
      ctx.stroke();
    }
  }, [notes, durationS, width, height, currentTimeS, scores, f0Overlay]);

  return <canvas ref={canvasRef} data-testid="pitch-lane" role="img" aria-label="Pitch lane" />;
}
