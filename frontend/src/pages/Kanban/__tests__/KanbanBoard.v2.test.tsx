/**
 * Kanban v2 board integration test — WP5.
 *
 * Mocks the v2 REST surface (`listProjects`, `listSprints`, `listComponents`,
 * `listMembers`, `listTickets`) and exercises:
 *   - project selector renders + drives URL state
 *   - switching project triggers refetch with `project_id`
 *   - sprint filter narrows tickets correctly
 *   - swimlane "By Epic" groups tickets correctly
 *   - type-filter chips toggle on/off
 *   - Backlog column appears leftmost
 *
 * The WS hook (`useTicketStream`) is no-op'd because jsdom can't open a real
 * WebSocket and the test only cares about the REST-driven board.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

vi.mock("../../../hooks/useTicketStream", () => ({
  useTicketStream: () => undefined,
}));
vi.mock("../../../hooks/useAuth", () => ({
  useAuth: () => ({
    isAuthenticated: true,
    user: { id: "user-1", email: "u@x", displayName: "U", role: "member" },
    isLoading: false,
    error: null,
  }),
}));

const projects = [
  {
    id: "p-def",
    key: "DEF",
    name: "Default",
    created_by: "u",
    created_by_type: "user",
  },
  {
    id: "p-aion",
    key: "AION",
    name: "Aion",
    created_by: "u",
    created_by_type: "user",
  },
];

const sprints = [
  { id: "sp-1", project_id: "p-def", name: "Sprint 12", state: "active" as const },
  { id: "sp-2", project_id: "p-def", name: "Sprint 13", state: "planned" as const },
];

const { listTicketsMock, getProjectHierarchyMock } = vi.hoisted(() => ({
  listTicketsMock: vi.fn(),
  getProjectHierarchyMock: vi.fn(),
}));

const ticketsByProject: Record<string, any[]> = {
  "p-def": [
    {
      id: "t-1",
      display_id: "DEF-1",
      title: "Backlog item",
      status: "backlog",
      type: "story",
      priority: "medium",
      version: 1,
      project_id: "p-def",
      sprint_id: null,
      epic_id: "t-e1",
    },
    {
      id: "t-2",
      display_id: "DEF-2",
      title: "Doing it",
      status: "in_progress",
      type: "task",
      priority: "high",
      version: 1,
      project_id: "p-def",
      sprint_id: "sp-1",
      epic_id: "t-e1",
    },
    {
      id: "t-3",
      display_id: "DEF-3",
      title: "No epic",
      status: "todo",
      type: "bug",
      priority: "medium",
      version: 1,
      project_id: "p-def",
      sprint_id: null,
      epic_id: null,
    },
    {
      id: "t-e1",
      display_id: "DEF-10",
      title: "An epic",
      status: "in_progress",
      type: "epic",
      priority: "medium",
      version: 1,
      project_id: "p-def",
      epic_id: null,
    },
  ],
  "p-aion": [
    {
      id: "t-9",
      display_id: "AION-1",
      title: "Aion task",
      status: "todo",
      type: "task",
      priority: "medium",
      version: 1,
      project_id: "p-aion",
    },
  ],
};

// V5b — kanban now reads from getProjectHierarchy. The legacy
// listTickets mock is preserved but unused so the import surface
// stays intact for any downstream helper that still references it.
listTicketsMock.mockImplementation(async () => ({ items: [] }));

getProjectHierarchyMock.mockImplementation(async (projectId: string) => {
  const items = (ticketsByProject[projectId] ?? []).map((t, idx) => ({
    depth: 0,
    parent_id: null,
    ordinal: idx + 1,
    ticket: t,
  }));
  return { items };
});

vi.mock("../../../api/projects", async () => {
  const actual =
    await vi.importActual<typeof import("../../../api/projects")>(
      "../../../api/projects",
    );
  return {
    ...actual,
    listProjects: vi.fn(async () => ({ items: projects })),
    listComponents: vi.fn(async () => ({ items: [] })),
    listMembers: vi.fn(async () => ({ items: [] })),
    getProjectHierarchy: getProjectHierarchyMock,
  };
});

vi.mock("../../../api/sprints", () => ({
  listSprints: vi.fn(async (projectId: string) => ({
    items: sprints.filter((s) => s.project_id === projectId),
  })),
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
    <MemoryRouter initialEntries={["/board"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <KanbanPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  listTicketsMock.mockClear();
  getProjectHierarchyMock.mockClear();
  // Re-install the implementation (mockClear preserves it but be explicit
  // — mockReset would wipe it).
  try {
    window.localStorage.clear();
  } catch {
    /* ignore */
  }
});

describe("KanbanBoard v2", () => {
  it("renders the project selector populated with non-archived projects", async () => {
    renderPage();
    await waitFor(() => {
      const sel = screen.getByLabelText("Project") as HTMLSelectElement;
      expect(sel).toBeInTheDocument();
      // DEF default
      expect(sel.value).toBe("DEF");
    });
    // Both options present
    expect(screen.getByRole("option", { name: /DEF/ })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /AION/ })).toBeInTheDocument();
  });

  it("renders Backlog as the leftmost column", async () => {
    renderPage();
    await waitFor(() => {
      const headers = screen.getAllByText(
        /^(Backlog|To Do|In Progress|In Review|Done)$/,
      );
      expect(headers[0]).toHaveTextContent("Backlog");
    });
  });

  it("switching project triggers refetch with new project_id", async () => {
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(getProjectHierarchyMock).toHaveBeenCalled();
    });
    const callsBefore = getProjectHierarchyMock.mock.calls.length;

    await user.selectOptions(screen.getByLabelText("Project"), "AION");

    await waitFor(() => {
      const newCalls = getProjectHierarchyMock.mock.calls.slice(callsBefore);
      expect(newCalls.some((c) => c[0] === "p-aion")).toBe(true);
    });

    // AION ticket should appear, DEF tickets should not.
    await waitFor(() => {
      expect(screen.getByText("Aion task")).toBeInTheDocument();
    });
    expect(screen.queryByText("Backlog item")).not.toBeInTheDocument();
  });

  it("sprint filter narrows tickets (client-side filter over hierarchy)", async () => {
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Backlog item")).toBeInTheDocument();
    });

    await user.selectOptions(
      screen.getByLabelText(/Filter by sprint/),
      "sp-1",
    );

    // V5b — filtering moved client-side over the hierarchy flatten;
    // assert the visible-tickets pruning rather than a server call shape.
    await waitFor(() => {
      // Only DEF-2 has sprint_id = sp-1
      expect(screen.getByText("Doing it")).toBeInTheDocument();
      expect(screen.queryByText("Backlog item")).not.toBeInTheDocument();
    });
  });

  it("swimlane 'By Epic' renders a header for the grouping epic", async () => {
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Backlog item")).toBeInTheDocument();
    });

    await user.selectOptions(screen.getByLabelText(/Swimlanes mode/), "epic");

    // The two tickets with epic_id=t-e1 should render under a swimlane header
    // whose key is the epic id. Stable test id from the component.
    await waitFor(() => {
      expect(screen.getByTestId("swimlane-header-t-e1")).toBeInTheDocument();
    });
    // The orphan ticket falls under the "__none__" lane.
    expect(screen.getByTestId("swimlane-header-__none__")).toBeInTheDocument();
  });

  it("type filter chips toggle and forward the type[] query", async () => {
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Backlog item")).toBeInTheDocument();
    });

    const taskChip = screen.getByRole("checkbox", { name: /Task/ });
    expect(taskChip).toHaveAttribute("aria-checked", "false");
    await user.click(taskChip);
    expect(taskChip).toHaveAttribute("aria-checked", "true");

    // V5b — type filter is client-side; assert the lane content shifts
    // instead of inspecting an API query param.
    await waitFor(() => {
      expect(screen.getByText("Doing it")).toBeInTheDocument(); // task
      expect(screen.queryByText("Backlog item")).not.toBeInTheDocument(); // story
    });

    // Toggle off
    await user.click(taskChip);
    expect(taskChip).toHaveAttribute("aria-checked", "false");
  });
});
