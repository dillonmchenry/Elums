import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { HomePage } from "./HomePage";

vi.mock("../client", () => ({
  healthzApiHealthzGet: vi.fn().mockResolvedValue({
    data: { status: "ok", db: "ok", valkey: "ok" },
    error: undefined,
  }),
  meApiMeGet: vi.fn().mockResolvedValue({ data: undefined, error: { detail: "not authenticated" } }),
}));

describe("HomePage", () => {
  it("renders the health status once the API call resolves", async () => {
    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>
    );

    expect(screen.getByTestId("health-status")).toHaveTextContent("Checking API health");

    await waitFor(() =>
      expect(screen.getByTestId("health-status")).toHaveTextContent(
        '{"status":"ok","db":"ok","valkey":"ok"}'
      )
    );
  });
});
