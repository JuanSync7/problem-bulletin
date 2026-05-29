/**
 * v2.14-WP04 (B5) — regression: Feed surfaces the backend's structured
 * error-envelope message instead of a synthetic `Failed to load problems
 * (500)` string.
 *
 * Pre-WP04, the silent-swallow path was:
 *
 *     throw new Error(`Failed to load problems (${res.status})`);
 *
 * which discarded the unified envelope's `message` (and dropped
 * `code` / `correlation_id` entirely). This test mocks `fetch` to return
 * a non-2xx with the canonical envelope shape and asserts the rendered
 * error reflects the envelope's `message`, proving the page now routes
 * through `parseApiError`.
 */
import "@testing-library/jest-dom";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import Feed from "../Feed";

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
  // Feed uses IntersectionObserver for infinite-scroll. jsdom doesn't
  // provide one; stub a no-op so the component mounts cleanly.
  class StubIO {
    observe() {}
    unobserve() {}
    disconnect() {}
    takeRecords() {
      return [];
    }
  }
  // @ts-expect-error — assigning test stub onto global
  global.IntersectionObserver = StubIO;
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Feed — parseApiError envelope handling", () => {
  it("surfaces the unified envelope message on non-2xx response", async () => {
    mockFetchEnvelopeError(429, {
      error: {
        code: "rate_limited",
        message: "Slow down — try again in a minute.",
        correlation_id: "corr-feed-1",
        details: null,
      },
    });

    render(<Feed />);

    // The page-level error region uses role="alert" and renders the
    // captured message verbatim. parseApiError extracts `message` from
    // the envelope; the pre-WP04 path would have produced
    // "Failed to load problems (429)" instead.
    await waitFor(() => {
      expect(
        screen.getByText("Slow down — try again in a minute."),
      ).toBeInTheDocument();
    });

    // Negative assertion: the legacy synthetic message must NOT appear.
    expect(
      screen.queryByText(/Failed to load problems \(429\)/),
    ).not.toBeInTheDocument();
  });
});
