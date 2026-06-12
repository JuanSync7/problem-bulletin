/**
 * WP60 — LabelDetail stub route tests.
 *
 * Looks up the label via the existing public `GET /api/tags?q=<name>`
 * endpoint and matches case-insensitively for the exact name.
 */
import "@testing-library/jest-dom";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import LabelDetail from "../LabelDetail";

function mockFetchOnce(body: unknown, ok = true) {
  global.fetch = vi.fn(async () => ({
    ok,
    status: ok ? 200 : 404,
    json: async () => body,
  })) as unknown as typeof fetch;
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <Routes>
        <Route path="/labels/:name" element={<LabelDetail />} />
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

describe("LabelDetail", () => {
  it("renders heading with label name once resolved", async () => {
    mockFetchOnce([
      {
        id: "tag-1",
        name: "frontend",
        created_at: "2026-01-01T00:00:00Z",
        usage_count: 12,
      },
    ]);

    renderAt(`/labels/frontend`);

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /frontend/i })).toBeInTheDocument();
    });
    expect(screen.getByText(/12/)).toBeInTheDocument();
  });

  it("renders not-found state when label is unknown", async () => {
    mockFetchOnce([]);

    renderAt(`/labels/missing-id`);

    await waitFor(() => {
      expect(screen.getByText(/label not found/i)).toBeInTheDocument();
    });
  });
});
