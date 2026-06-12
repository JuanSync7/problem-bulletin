/**
 * V5b — Kanban reads from the project-hierarchy endpoint.
 *
 * Asserts:
 *   1. KanbanPage calls `getProjectHierarchy(projectId, {max_depth: 8})`
 *      after the project list resolves, and renders the hierarchy rows
 *      grouped by status into the kanban lanes.
 *   2. The legacy ticket-list fetch (`listTickets`) is NOT invoked.
 *   3. Each child ticket (one with a parent in the tree) renders an
 *      epic-chip referencing its root epic's display_id.
 */
import "@testing-library/jest-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const {
  listProjectsMock,
  getProjectHierarchyMock,
  listTicketsMock,
} = vi.hoisted(() => {
  const epicId = "t-epic";
  const storyId = "t-story";
  const taskId = "t-task";
  const subtaskId = "t-subtask";
  const baseTicket = {
    version: 1,
    project_id: "p-pb",
    labels: [] as string[],
    fix_versions: [] as string[],
    custom_fields: {} as Record<string, unknown>,
    reporter_id: "u-1",
    reporter_type: "user",
    priority: "medium",
  };
  const listProjectsMockFn = vi.fn(async () => ({
    items: [
      {
        id: "p-pb",
        key: "PB",
        name: "Problem-Bulletin",
        created_by: "u-1",
        created_by_type: "user",
      },
    ],
    next_cursor: null,
    total: 1,
  }));
  const getProjectHierarchyMockFn = vi.fn(async () => ({
    items: [
      {
        depth: 0,
        parent_id: null,
        ordinal: 1,
        ticket: {
          ...baseTicket,
          id: epicId,
          display_id: "PB-1",
          seq_number: 1,
          type: "epic",
          status: "backlog",
          title: "Demo epic",
          created_at: "2026-06-01T00:00:00Z",
        },
      },
      {
        depth: 1,
        parent_id: epicId,
        ordinal: 2,
        ticket: {
          ...baseTicket,
          id: storyId,
          display_id: "PB-2",
          seq_number: 2,
          type: "story",
          status: "todo",
          title: "Demo story",
          created_at: "2026-06-01T00:00:01Z",
        },
      },
      {
        depth: 2,
        parent_id: storyId,
        ordinal: 3,
        ticket: {
          ...baseTicket,
          id: taskId,
          display_id: "PB-3",
          seq_number: 3,
          type: "task",
          status: "in_progress",
          title: "Demo task",
          created_at: "2026-06-01T00:00:02Z",
        },
      },
      {
        depth: 3,
        parent_id: taskId,
        ordinal: 4,
        ticket: {
          ...baseTicket,
          id: subtaskId,
          display_id: "PB-4",
          seq_number: 4,
          type: "subtask",
          status: "done",
          title: "Demo subtask",
          created_at: "2026-06-01T00:00:03Z",
        },
      },
    ],
  }));
  const listTicketsMockFn = vi.fn(async () => {
    throw new Error(
      "listTickets must not be called — kanban should source from getProjectHierarchy",
    );
  });
  return {
    listProjectsMock: listProjectsMockFn,
    getProjectHierarchyMock: getProjectHierarchyMockFn,
    listTicketsMock: listTicketsMockFn,
  };
});

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
    listProjects: listProjectsMock,
    listComponents: vi.fn(async () => ({ items: [] })),
    listMembers: vi.fn(async () => ({ items: [] })),
    getProjectHierarchy: getProjectHierarchyMock,
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
    listTickets: listTicketsMock,
    getTicket: vi.fn(),
    getSubtree: vi.fn(async () => ({ items: [] })),
  };
});

import KanbanPage from "../index";

function renderPage() {
  return render(
    <MemoryRouter
      initialEntries={["/board?project=PB"]}
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
  getProjectHierarchyMock.mockClear();
  listTicketsMock.mockClear();
});

describe("V5b — Kanban reads hierarchy as source of truth", () => {
  it("calls getProjectHierarchy with max_depth=8 once the project resolves", async () => {
    renderPage();
    await waitFor(() => {
      expect(getProjectHierarchyMock).toHaveBeenCalled();
    });
    const calls = getProjectHierarchyMock.mock.calls as unknown as ReadonlyArray<
      readonly [string, { max_depth?: number }?]
    >;
    expect(calls.length).toBeGreaterThan(0);
    const first = calls[0]!;
    expect(first[0]).toBe("p-pb");
    expect(first[1]).toEqual(expect.objectContaining({ max_depth: 8 }));
  });

  it("does NOT call the legacy listTickets endpoint", async () => {
    renderPage();
    await waitFor(() => {
      expect(getProjectHierarchyMock).toHaveBeenCalled();
    });
    expect(listTicketsMock).not.toHaveBeenCalled();
  });

  it("renders tickets in the kanban lanes grouped by status", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Demo epic")).toBeInTheDocument();
    });
    const backlog = document.querySelector('[data-status="backlog"]');
    const todo = document.querySelector('[data-status="todo"]');
    const inProgress = document.querySelector('[data-status="in_progress"]');
    const done = document.querySelector('[data-status="done"]');
    expect(backlog).not.toBeNull();
    expect(todo).not.toBeNull();
    expect(inProgress).not.toBeNull();
    expect(done).not.toBeNull();
    expect(within(backlog as HTMLElement).getByText("Demo epic")).toBeInTheDocument();
    expect(within(todo as HTMLElement).getByText("Demo story")).toBeInTheDocument();
    expect(within(inProgress as HTMLElement).getByText("Demo task")).toBeInTheDocument();
    expect(within(done as HTMLElement).getByText("Demo subtask")).toBeInTheDocument();
  });

  it("renders an epic chip on every descendant card (epic_id projected by the flatten step)", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Demo story")).toBeInTheDocument();
    });
    // Every descendant of the root epic (story / task / subtask) MUST have
    // its ``epic_id`` populated by the hierarchy-flatten step so the
    // existing TicketCard chip path lights up. We assert chip *presence*
    // — the chip's display text is the epic's display_id and is owned
    // by TicketCard (out of scope for this slice).
    const chips = await screen.findAllByTestId("ticket-epic-chip");
    expect(chips.length).toBeGreaterThanOrEqual(3);
    // The epic root itself MUST NOT render a chip (no epic ancestor).
    const epicCard = document.querySelector(`[data-ticket-id="${"t-epic"}"]`);
    expect(epicCard).not.toBeNull();
    expect(
      (epicCard as HTMLElement).querySelector(
        '[data-testid="ticket-epic-chip"]',
      ),
    ).toBeNull();
  });
});
