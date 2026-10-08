import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { ProgressPage } from "./ProgressPage";

const mockGetSongProgress = vi.fn();

vi.mock("../client", () => ({
  getSongProgressApiSongsSongIdProgressGet: (...args: unknown[]) => mockGetSongProgress(...args),
}));

function renderAt(songId: string) {
  return render(
    <MemoryRouter initialEntries={[`/songs/${songId}/progress`]}>
      <Routes>
        <Route path="/songs/:id/progress" element={<ProgressPage />} />
      </Routes>
    </MemoryRouter>
  );
}

describe("ProgressPage", () => {
  it("shows the gated 'sing N more' copy below the verdict threshold", async () => {
    mockGetSongProgress.mockResolvedValue({
      data: {
        performance_count: 3,
        normalization: "elo",
        overall: {
          verdict: "insufficient_data",
          performances_needed: 5,
          rolling_median: 0.6,
          iqr_low: 0.5,
          iqr_high: 0.7,
          band_widen_factor: 1.0,
        },
        dimensions: {},
        personal_best_score_overall: 0.6,
        device_label_consistent: true,
      },
      error: undefined,
    });

    renderAt("song-a");

    await waitFor(() =>
      expect(screen.getByTestId("progress-verdict")).toHaveTextContent("sing 5 more takes")
    );
  });

  it("shows the personal best hero metric and a cleared verdict once gated", async () => {
    mockGetSongProgress.mockResolvedValue({
      data: {
        performance_count: 10,
        normalization: "elo",
        overall: {
          verdict: "improving",
          performances_needed: 0,
          rolling_median: 1510.2,
          iqr_low: 1505.0,
          iqr_high: 1512.0,
          band_widen_factor: 1.0,
        },
        dimensions: {
          pct_in_tune: {
            verdict: "improving",
            performances_needed: 0,
            rolling_median: 0.8,
            iqr_low: 0.7,
            iqr_high: 0.9,
            band_widen_factor: 1.0,
          },
        },
        personal_best_score_overall: 0.82,
        device_label_consistent: true,
      },
      error: undefined,
    });

    renderAt("song-b");

    await waitFor(() => expect(screen.getByTestId("progress-personal-best")).toHaveTextContent("82%"));
    expect(screen.getByTestId("progress-performance-count")).toHaveTextContent("10 scored takes");
    expect(screen.getAllByTestId("progress-verdict")[0]).toHaveTextContent("Improving");
  });

  it("renders a no-data message when the song has never been scored", async () => {
    mockGetSongProgress.mockResolvedValue({
      data: {
        performance_count: 0,
        normalization: "elo",
        overall: null,
        dimensions: {},
        personal_best_score_overall: null,
        device_label_consistent: true,
      },
      error: undefined,
    });

    renderAt("song-c");

    await waitFor(() => expect(screen.getByText(/No scored takes/)).toBeInTheDocument());
  });
});
