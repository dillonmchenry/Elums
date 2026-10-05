import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { LoginPage } from "./LoginPage";

const loginMock = vi.fn();
vi.mock("../client", () => ({
  loginApiAuthLoginPost: (...args: unknown[]) => loginMock(...args),
}));

describe("LoginPage", () => {
  it("surfaces the demo credentials on the page", () => {
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>
    );
    expect(screen.getByTestId("demo-credentials-hint")).toHaveTextContent("dana@elums.demo");
    expect(screen.getByTestId("demo-credentials-hint")).toHaveTextContent("elums-demo-2026");
  });

  it("shows an error on failed login without leaking which field was wrong", async () => {
    loginMock.mockResolvedValueOnce({ data: undefined, error: { detail: "bad creds" } });
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>
    );
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "dana@elums.demo" } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: "wrong" } });
    fireEvent.click(screen.getByRole("button", { name: "Log in" }));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Incorrect email or password.")
    );
  });
});
