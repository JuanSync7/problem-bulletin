/**
 * WP60 — ComponentDetail stub route tests.
 *
 * Pattern: mock global fetch directly (project doesn't use MSW yet — see
 * v2.8-WP57 lessons). Component fetches `/api/v1/projects` then iterates
 * `/api/v1/projects/<id>/components` to locate the requested component by id.
 */
import "@testing-library/jest-dom";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ComponentDetail from "../ComponentDetail";

const COMPONENT_ID = "11111111-1111-1111-1111-111111111111";
const PROJECT_ID = "22222222-2222-2222-2222-222222222222";

function mockFetchSequence(responses: Array<{ url: RegExp; body: unknown; ok?: boolean }>) {
  global.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    const match = responses.find((r) => r.url.test(url));
    if (!match) {
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    }
    return {
      ok: match.ok ?? true,
      status: match.ok === false ? 404 : 200,
      json: async () => match.body,
    } as Response;
  }) as typeof fetch;
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <Routes>
        <Route path="/components/:id" element={<ComponentDetail />} />
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

describe("ComponentDetail", () => {
  it("renders heading with component name once resolved", async () => {
    mockFetchSequence([
      {
        url: /\/api\/v1\/projects(\?|$)/,
        body: { items: [{ id: PROJECT_ID, key: "PROJ", name: "My Project" }], next_cursor: null, total: 1 },
      },
      {
        url: new RegExp(`/api/v1/projects/${PROJECT_ID}/components`),
        body: {
          items: [
            {
              id: COMPONENT_ID,
              project_id: PROJECT_ID,
              name: "auth-service",
              description: "Authentication subsystem",
            },
          ],
        },
      },
    ]);

    renderAt(`/components/${COMPONENT_ID}`);

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /auth-service/i })).toBeInTheDocument();
    });
    expect(screen.getByText(/Authentication subsystem/i)).toBeInTheDocument();
    expect(screen.getByText(/My Project/i)).toBeInTheDocument();
  });

  it("renders not-found state when component id is unknown", async () => {
    mockFetchSequence([
      {
        url: /\/api\/v1\/projects(\?|$)/,
        body: { items: [{ id: PROJECT_ID, key: "PROJ", name: "My Project" }], next_cursor: null, total: 1 },
      },
      {
        url: new RegExp(`/api/v1/projects/${PROJECT_ID}/components`),
        body: { items: [] },
      },
    ]);

    renderAt(`/components/missing-id`);

    await waitFor(() => {
      expect(screen.getByText(/component not found/i)).toBeInTheDocument();
    });
  });
});
