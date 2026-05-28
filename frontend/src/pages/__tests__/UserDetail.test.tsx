/**
 * WP60 — UserDetail stub route tests.
 *
 * Resolves a handle via the existing `GET /api/v1/people/search?q=<handle>`
 * endpoint. The handle may belong to either a user or an agent account; the
 * page must display the kind in either case.
 */
import "@testing-library/jest-dom";
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import UserDetail from "../UserDetail";

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
        <Route path="/users/:handle" element={<UserDetail />} />
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

describe("UserDetail", () => {
  it("renders heading with display name for a user handle", async () => {
    mockFetchOnce({
      items: [
        {
          kind: "user",
          id: "u-1",
          display_name: "Alice Doe",
          handle: "alice",
          email: "alice@example.com",
        },
      ],
    });

    renderAt(`/users/alice`);

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /alice doe/i })).toBeInTheDocument();
    });
    expect(screen.getByText(/@alice/)).toBeInTheDocument();
  });

  it("renders agent kind when handle resolves to an agent", async () => {
    mockFetchOnce({
      items: [
        {
          kind: "agent",
          id: "a-1",
          display_name: "Triage Bot",
          handle: "triage-bot",
          email: null,
        },
      ],
    });

    renderAt(`/users/triage-bot`);

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /triage bot/i })).toBeInTheDocument();
    });
    expect(screen.getByText(/agent/i)).toBeInTheDocument();
  });

  it("renders not-found state when handle is unknown", async () => {
    mockFetchOnce({ items: [] });

    renderAt(`/users/missing-id`);

    await waitFor(() => {
      expect(screen.getByText(/user not found/i)).toBeInTheDocument();
    });
  });
});
