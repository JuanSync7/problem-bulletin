/**
 * v2.14-WP04 (B5) — regression: Leaderboard surfaces the backend's
 * structured error-envelope message instead of `Failed to load
 * leaderboard (NNN)`.
 */
import "@testing-library/jest-dom";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import Leaderboard from "../Leaderboard";

function mockFetchEnvelopeError(status: number, envelope: unknown) {
  global.fetch = vi.fn(async () => ({
    ok: false,
    status,
    statusText: "",
    json: async () => envelope,
  })) as unknown as typeof fetch;
}

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Leaderboard — parseApiError envelope handling", () => {
  it("renders the unified envelope message on non-2xx response", async () => {
    mockFetchEnvelopeError(503, {
      error: {
        code: "service_unavailable",
        message: "Leaderboard service is currently unavailable.",
        correlation_id: "corr-lb-1",
        details: null,
      },
    });

    render(<Leaderboard />);

    await waitFor(() => {
      expect(
        screen.getByText("Leaderboard service is currently unavailable."),
      ).toBeInTheDocument();
    });

    expect(
      screen.queryByText(/Failed to load leaderboard \(503\)/),
    ).not.toBeInTheDocument();
  });
});
