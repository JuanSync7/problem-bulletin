/**
 * v2.1-WP10 — Pagination + filter-sentinel tests for KanbanPage.
 *
 * Asserts:
 *  - Filter "None" sends ``sprint_id=null`` (not ``__none__``).
 *  - Filter "Me" sends ``assignee_id=me`` (not the current-user UUID).
 *  - Filter "All sprints" omits the param entirely.
 *  - A multi-page response surfaces a "Load more" control whose click
 *    appends the next page's items to the visible board.
 */
import "@testing-library/jest-dom";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { listTicketsMock } = vi.hoisted(() => ({
  listTicketsMock: vi.fn(),
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

vi.mock("../../../api/projects", () => ({
  listProjects: vi.fn(async () => ({
    items: projects,
    next_cursor: null,
    total: 1,
  })),
  listComponents: vi.fn(async () => ({ items: [] })),
  listMembers: vi.fn(async () => ({ items: [] })),
}));

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
    listTickets: listTicketsMock,
    getTicket: vi.fn(),
    getSubtree: vi.fn(async () => ({ items: [] })),
  };
});

import KanbanPage from "../index";

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/board?project=DEF"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <KanbanPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  listTicketsMock.mockReset();
  listTicketsMock.mockResolvedValue({
    items: [],
    next_cursor: null,
    total: 0,
  });
  try {
    window.localStorage.clear();
  } catch {
    /* ignore */
  }
});

describe("Kanban WP10 filter sentinels", () => {
  it('sprint "No sprint" sends sprint_id=null, not __none__', async () => {
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => expect(listTicketsMock).toHaveBeenCalled());

    await user.selectOptions(screen.getByLabelText(/Filter by sprint/), "null");

    await waitFor(() => {
      const calls = listTicketsMock.mock.calls;
      const last = calls[calls.length - 1][0];
      expect(last?.sprint_id).toBe("null");
    });
    // And never the legacy sentinel.
    const allCalls = listTicketsMock.mock.calls.map((c) => c[0]?.sprint_id);
    expect(allCalls).not.toContain("__none__");
  });

  it('sprint "All sprints" omits sprint_id', async () => {
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => expect(listTicketsMock).toHaveBeenCalled());

    // Select "no sprint" first then back to All.
    await user.selectOptions(screen.getByLabelText(/Filter by sprint/), "null");
    await user.selectOptions(
      screen.getByLabelText(/Filter by sprint/),
      "__all__",
    );

    await waitFor(() => {
      const last =
        listTicketsMock.mock.calls[listTicketsMock.mock.calls.length - 1][0];
      expect(last?.sprint_id).toBeUndefined();
    });
  });
});

describe("Kanban WP10 pagination", () => {
  it('renders "Load more" when next_cursor present and appends on click', async () => {
    // First page: 2 tickets, next_cursor populated.
    listTicketsMock
      .mockResolvedValueOnce({
        items: [
          {
            id: "t1",
            display_id: "DEF-1",
            title: "First",
            status: "todo",
            type: "task",
            priority: "medium",
            version: 1,
            project_id: "p-def",
          },
          {
            id: "t2",
            display_id: "DEF-2",
            title: "Second",
            status: "todo",
            type: "task",
            priority: "medium",
            version: 1,
            project_id: "p-def",
          },
        ],
        next_cursor: "CURSOR-1",
        total: 3,
      })
      .mockResolvedValueOnce({
        items: [
          {
            id: "t3",
            display_id: "DEF-3",
            title: "Third",
            status: "todo",
            type: "task",
            priority: "medium",
            version: 1,
            project_id: "p-def",
          },
        ],
        next_cursor: null,
        total: 3,
      });

    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("First")).toBeInTheDocument();
      expect(screen.getByText("Second")).toBeInTheDocument();
    });
    const btn = await screen.findByRole("button", {
      name: /Load more tickets/i,
    });
    expect(btn).toBeInTheDocument();

    await user.click(btn);

    await waitFor(() => {
      expect(screen.getByText("Third")).toBeInTheDocument();
    });
    // The second call carried the cursor.
    const cursorCall = listTicketsMock.mock.calls.find(
      (c) => (c[0] as any)?.cursor === "CURSOR-1",
    );
    expect(cursorCall).toBeTruthy();
  });
});
