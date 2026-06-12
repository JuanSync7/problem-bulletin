/**
 * B3 — Retire Kanban inline hierarchy panel.
 *
 * Asserts:
 *   1. The old "Hierarchy" toggle button is NOT in the DOM (the view=tree mode
 *      is removed; "Hierarchy" is now a dedicated page).
 *   2. A link "View full hierarchy" is present in the toolbar.
 *   3. The link href points to `/projects/<projectId>/hierarchy`.
 *
 * Red-first: written before the implementation. Running against the current
 * codebase (with HierarchyTreeView still present) will fail on assertions 1
 * and 2 — which is the expected red state.
 */
import "@testing-library/jest-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// ---- Module mocks (must precede the KanbanPage import) -------------------

vi.mock("../../../hooks/useTicketStream", () => ({
  useTicketStream: () => undefined,
}));

vi.mock("../../../hooks/useAuth", () => ({
  useAuth: () => ({
    isAuthenticated: true,
    user: { id: "u-1", email: "test@x", displayName: "Test", role: "member" },
    isLoading: false,
    error: null,
  }),
}));

vi.mock("../../../api/projects", async () => {
  const actual =
    await vi.importActual<typeof import("../../../api/projects")>(
      "../../../api/projects",
    );
  return {
    ...actual,
    listProjects: vi.fn(async () => ({
      items: [
        {
          id: "p-abc",
          key: "TST",
          name: "Test Project",
          created_by: "u-1",
          created_by_type: "user",
        },
      ],
    })),
    listComponents: vi.fn(async () => ({ items: [] })),
    listMembers: vi.fn(async () => ({ items: [] })),
    // V5b — kanban now sources from getProjectHierarchy. Stub it to
    // return an empty tree so existing assertions (toolbar / links)
    // still mount without errors.
    getProjectHierarchy: vi.fn(async () => ({ items: [] })),
  };
});

vi.mock("../../../api/sprints", () => ({
  listSprints: vi.fn(async () => ({ items: [] })),
}));

vi.mock("../../../api/audit", () => ({
  listAgentActivity: vi.fn(async () => []),
}));

vi.mock("../../../api/people", () => ({
  searchPeople: vi.fn(async () => ({ items: [] })),
}));

vi.mock("../../../api/tickets", async () => {
  const actual =
    await vi.importActual<typeof import("../../../api/tickets")>(
      "../../../api/tickets",
    );
  return {
    ...actual,
    listTickets: vi.fn(async () => ({ items: [], total: 0, column_counts: {} })),
    getTicket: vi.fn(),
    getSubtree: vi.fn(async () => ({ items: [] })),
  };
});

import KanbanPage from "../index";

function renderPage() {
  return render(
    <MemoryRouter
      initialEntries={["/board?project=TST"]}
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <KanbanPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  try {
    window.localStorage.clear();
  } catch {
    /* ignore */
  }
});

describe("B3 — no inline hierarchy panel", () => {
  it("does NOT render a 'Hierarchy' toggle button (the old tree-view mode)", async () => {
    renderPage();
    // Wait for the board to stabilise (project loads, toolbar renders).
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /refresh/i })).toBeInTheDocument();
    });
    // The old "Hierarchy" button used to switch view=tree should be gone.
    expect(
      screen.queryByRole("button", { name: /^hierarchy$/i }),
    ).not.toBeInTheDocument();
  });

  it("renders a 'View full hierarchy' link pointing to /projects/<id>/hierarchy", async () => {
    renderPage();
    await waitFor(() => {
      const link = screen.getByRole("link", { name: /view full hierarchy/i });
      expect(link).toBeInTheDocument();
      // href must end with /projects/p-abc/hierarchy (project id from mock).
      expect(link).toHaveAttribute("href", expect.stringMatching(/\/projects\/p-abc\/hierarchy/));
    });
  });
});
