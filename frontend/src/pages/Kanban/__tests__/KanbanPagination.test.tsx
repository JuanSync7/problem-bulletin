/**
 * v2.1-WP10 / V5b — filter-sentinel + pagination tests for KanbanPage.
 *
 * V5b retired the legacy ``listTickets`` fetch in favour of
 * ``getProjectHierarchy``. With that change:
 *   * Sprint / assignee filters are applied client-side over the
 *     hierarchy flatten — the "null" / "me" sentinels are still the
 *     selector's wire values but they no longer travel to the server.
 *   * Cursor pagination is gone: the hierarchy endpoint returns the
 *     full subtree (capped at ``max_depth``), so the "Load more"
 *     control has no fuel and must not render.
 *
 * The tests below were updated minimally per the V5b slice scope —
 * "If a pre-existing test relies on the old fetch shape, update it
 * minimally to the new shape."
 */
import "@testing-library/jest-dom";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { getProjectHierarchyMock } = vi.hoisted(() => ({
  getProjectHierarchyMock: vi.fn(),
}));

vi.mock("../../../hooks/useTicketStream", () => ({
  useTicketStream: () => undefined,
}));

const projects = [
  {
    id: "p-def",
    key: "DEF",
    name: "Default",
    archived_at: null,
    version: 1,
  },
];

const sprints = [
  {
    id: "sp-1",
    project_id: "p-def",
    name: "Sprint 1",
    state: "active",
  },
];

vi.mock("../../../api/projects", async () => {
  const actual =
    await vi.importActual<typeof import("../../../api/projects")>(
      "../../../api/projects",
    );
  return {
    ...actual,
    listProjects: vi.fn(async () => ({
      items: projects,
      next_cursor: null,
      total: 1,
    })),
    listComponents: vi.fn(async () => ({ items: [] })),
    listMembers: vi.fn(async () => ({ items: [] })),
    getProjectHierarchy: getProjectHierarchyMock,
  };
});

vi.mock("../../../api/sprints", () => ({
  listSprints: vi.fn(async () => ({ items: sprints })),
}));

vi.mock("../../../api/audit", () => ({
  listAgentActivity: vi.fn(async () => []),
}));

vi.mock("../../../api/people", () => ({
  searchPeople: vi.fn(async () => ({ items: [] })),
}));

vi.mock("../../../hooks/useAuth", () => ({
  useAuth: () => ({ user: { id: "u-current" } }),
}));

vi.mock("../../../api/tickets", async () => {
  const actual = await vi.importActual<typeof import("../../../api/tickets")>(
    "../../../api/tickets",
  );
  return {
    ...actual,
    listTickets: vi.fn(async () => ({ items: [] })),
    getTicket: vi.fn(),
    getSubtree: vi.fn(async () => ({ items: [] })),
  };
});

import KanbanPage from "../index";

function renderPage() {
  return render(
    <MemoryRouter
      initialEntries={["/board?project=DEF"]}
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <KanbanPage />
    </MemoryRouter>,
  );
}

const baseTicket = {
  project_id: "p-def",
  type: "task",
  priority: "medium",
  version: 1,
};

function row(
  overrides: Record<string, unknown>,
  ordinal: number,
): { depth: number; parent_id: null; ordinal: number; ticket: Record<string, unknown> } {
  return {
    depth: 0,
    parent_id: null,
    ordinal,
    ticket: { ...baseTicket, ...overrides },
  };
}

beforeEach(() => {
  getProjectHierarchyMock.mockReset();
  getProjectHierarchyMock.mockResolvedValue({ items: [] });
  try {
    window.localStorage.clear();
  } catch {
    /* ignore */
  }
});

describe("Kanban V5b filter sentinels (client-side)", () => {
  it('sprint "No sprint" filters out tickets that carry a sprint_id', async () => {
    getProjectHierarchyMock.mockResolvedValue({
      items: [
        row(
          {
            id: "t1",
            display_id: "DEF-1",
            title: "Has sprint",
            status: "todo",
            sprint_id: "sp-1",
          },
          1,
        ),
        row(
          {
            id: "t2",
            display_id: "DEF-2",
            title: "No sprint here",
            status: "todo",
            sprint_id: null,
          },
          2,
        ),
      ],
    });

    const user = userEvent.setup();
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("Has sprint")).toBeInTheDocument(),
    );

    await user.selectOptions(screen.getByLabelText(/Filter by sprint/), "null");

    await waitFor(() => {
      expect(screen.queryByText("Has sprint")).not.toBeInTheDocument();
      expect(screen.getByText("No sprint here")).toBeInTheDocument();
    });
  });

  it('sprint "All sprints" restores all tickets', async () => {
    getProjectHierarchyMock.mockResolvedValue({
      items: [
        row(
          {
            id: "t1",
            display_id: "DEF-1",
            title: "Has sprint",
            status: "todo",
            sprint_id: "sp-1",
          },
          1,
        ),
        row(
          {
            id: "t2",
            display_id: "DEF-2",
            title: "No sprint here",
            status: "todo",
            sprint_id: null,
          },
          2,
        ),
      ],
    });

    const user = userEvent.setup();
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("Has sprint")).toBeInTheDocument(),
    );

    await user.selectOptions(screen.getByLabelText(/Filter by sprint/), "null");
    await user.selectOptions(
      screen.getByLabelText(/Filter by sprint/),
      "__all__",
    );

    await waitFor(() => {
      expect(screen.getByText("Has sprint")).toBeInTheDocument();
      expect(screen.getByText("No sprint here")).toBeInTheDocument();
    });
  });
});

describe("Kanban V5b pagination retirement", () => {
  it('does NOT render a "Load more" control (hierarchy endpoint returns the full subtree)', async () => {
    getProjectHierarchyMock.mockResolvedValue({
      items: [
        row(
          {
            id: "t1",
            display_id: "DEF-1",
            title: "First",
            status: "todo",
          },
          1,
        ),
        row(
          {
            id: "t2",
            display_id: "DEF-2",
            title: "Second",
            status: "todo",
          },
          2,
        ),
      ],
    });

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("First")).toBeInTheDocument();
      expect(screen.getByText("Second")).toBeInTheDocument();
    });
    expect(
      screen.queryByRole("button", { name: /load more/i }),
    ).not.toBeInTheDocument();
  });
});
