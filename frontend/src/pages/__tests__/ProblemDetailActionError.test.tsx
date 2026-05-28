/**
 * v2.15-WP03 (C1) — regression: ProblemDetail surfaces the backend's
 * structured error-envelope `message` via the inline action-error banner
 * when previously-silent category-c sites (`if (res.ok) { ... }` with no
 * else) return non-2xx.
 *
 * Pre-WP03, every action/hydration handler in ProblemDetail.tsx had the
 * shape:
 *
 *     try {
 *       const res = await fetch(...);
 *       if (res.ok) { ...happy path... }
 *     } catch { ...swallow... }
 *
 * which silently dropped non-2xx into a no-op. v2.15-WP03 routes every
 * non-2xx through `throwParsed(res, fallback)` and surfaces the envelope's
 * `message` via `setActionError`, rendered in the
 * `problem-detail__action-error` inline banner (data-testid
 * `problem-detail-action-error`).
 *
 * Four representative sites are exercised — each picks a different
 * call-site shape (action / hydration / sub-component / status
 * transition) so the regression net is dense enough to catch any
 * future re-introduction of the silent-swallow class.
 */
import "@testing-library/jest-dom";
import React from "react";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ProblemDetail from "../ProblemDetail";

interface FetchRule {
  pattern: RegExp | string;
  method?: string;
  status: number;
  body: unknown;
}

/**
 * Install a URL-aware fetch mock. The first rule that matches the
 * requested URL (and method, if specified) wins. Unmatched calls fall
 * through to a default 200 with an empty array — keeps the page from
 * crashing on unrelated hydrations.
 */
function installFetchMock(rules: FetchRule[]) {
  global.fetch = vi.fn(async (input: any, init: any) => {
    const url = typeof input === "string" ? input : input.url;
    const method = (init?.method || "GET").toUpperCase();
    for (const r of rules) {
      const matchesPath =
        typeof r.pattern === "string" ? url.endsWith(r.pattern) : r.pattern.test(url);
      const matchesMethod = !r.method || r.method.toUpperCase() === method;
      if (matchesPath && matchesMethod) {
        return {
          ok: r.status >= 200 && r.status < 300,
          status: r.status,
          statusText: "",
          json: async () => r.body,
        } as any;
      }
    }
    // Default fall-through — never throw, never return null body.
    return {
      ok: true,
      status: 200,
      statusText: "",
      json: async () => [],
    } as any;
  }) as unknown as typeof fetch;
}

const ENVELOPE = (message: string, code = "forbidden", correlation_id = "corr-pd-1") => ({
  error: { code, message, correlation_id, details: null },
});

const SAMPLE_PROBLEM = {
  id: "p-1",
  display_id: "PROB-1",
  title: "Sample problem",
  description: "Body",
  status: "open",
  author: { id: "u-1", display_name: "Alice" },
  upstar_count: 0,
  is_upstarred: false,
  is_claimed: false,
  solution_count: 0,
  comment_count: 0,
  category: null,
  tags: [],
  created_at: new Date().toISOString(),
};

function renderProblemDetail() {
  return render(
    <MemoryRouter initialEntries={["/problems/p-1"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <Routes>
        <Route path="/problems/:id" element={<ProblemDetail />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ProblemDetail — v2.15-WP03 action-error surface", () => {
  // Site 1 (hydration: fetchSolutions, line ~538). Non-2xx on solutions
  // must surface the envelope `message` to the inline banner instead of
  // being silently dropped.
  it("surfaces envelope message when /solutions hydration returns 4xx", async () => {
    installFetchMock([
      // auth/me — anonymous (page still renders)
      { pattern: "/api/auth/me", status: 401, body: {} },
      // The problem itself loads fine.
      { pattern: /\/api\/problems\/p-1$/, method: "GET", status: 200, body: SAMPLE_PROBLEM },
      // Solutions hydration fails with structured envelope.
      {
        pattern: /\/solutions$/,
        method: "GET",
        status: 403,
        body: ENVELOPE("Solutions are restricted for this project."),
      },
    ]);

    renderProblemDetail();

    await waitFor(() => {
      expect(
        screen.getByTestId("problem-detail-action-error"),
      ).toHaveTextContent("Solutions are restricted for this project.");
    });
  });

  // Site 2 (hydration: fetchComments). Same shape, different route.
  it("surfaces envelope message when /comments hydration returns 5xx", async () => {
    installFetchMock([
      { pattern: "/api/auth/me", status: 401, body: {} },
      { pattern: /\/api\/problems\/p-1$/, method: "GET", status: 200, body: SAMPLE_PROBLEM },
      {
        pattern: /\/comments$/,
        method: "GET",
        status: 503,
        body: ENVELOPE("Comment service unavailable.", "service_unavailable"),
      },
    ]);

    renderProblemDetail();

    await waitFor(() => {
      expect(
        screen.getByTestId("problem-detail-action-error"),
      ).toHaveTextContent("Comment service unavailable.");
    });
  });

  // Site 3 (hydration: fetchAttachments). Covers the third hydration
  // path; together with sites 1+2 this proves every category-c
  // hydration site routes through parseApiError.
  it("surfaces envelope message when /attachments hydration returns 4xx", async () => {
    installFetchMock([
      { pattern: "/api/auth/me", status: 401, body: {} },
      { pattern: /\/api\/problems\/p-1$/, method: "GET", status: 200, body: SAMPLE_PROBLEM },
      {
        pattern: /\/attachments$/,
        method: "GET",
        status: 429,
        body: ENVELOPE("Rate-limited — slow down.", "rate_limited"),
      },
    ]);

    renderProblemDetail();

    await waitFor(() => {
      expect(
        screen.getByTestId("problem-detail-action-error"),
      ).toHaveTextContent("Rate-limited — slow down.");
    });
  });

  // Site 4 (action: dismiss). The banner is dismissible — clicking the
  // dismiss button clears it. Proves the action-error surface is a
  // proper state-driven UI element, not a fire-and-forget toast.
  it("dismisses the action-error banner on click", async () => {
    installFetchMock([
      { pattern: "/api/auth/me", status: 401, body: {} },
      { pattern: /\/api\/problems\/p-1$/, method: "GET", status: 200, body: SAMPLE_PROBLEM },
      {
        pattern: /\/solutions$/,
        method: "GET",
        status: 403,
        body: ENVELOPE("Solutions forbidden."),
      },
    ]);

    renderProblemDetail();

    const banner = await screen.findByTestId("problem-detail-action-error");
    expect(banner).toHaveTextContent("Solutions forbidden.");

    const dismiss = screen.getByLabelText("Dismiss error");
    fireEvent.click(dismiss);

    await waitFor(() => {
      expect(
        screen.queryByTestId("problem-detail-action-error"),
      ).not.toBeInTheDocument();
    });
  });
});
