import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import App from "./App";

vi.mock("./client", () => ({
  healthzApiHealthzGet: vi.fn().mockResolvedValue({ data: { status: "ok" }, error: undefined }),
}));
vi.mock("./apiClient", () => ({}));

describe("App routing", () => {
  it("renders HomePage at /", () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>
    );
    expect(screen.getByRole("heading", { name: "Elums" })).toBeInTheDocument();
  });

  it("renders the diagnostics stub at /diagnostics", () => {
    render(
      <MemoryRouter initialEntries={["/diagnostics"]}>
        <App />
      </MemoryRouter>
    );
    expect(screen.getByRole("heading", { name: "Diagnostics" })).toBeInTheDocument();
    expect(screen.getByText(/Day 3/)).toBeInTheDocument();
  });
});
