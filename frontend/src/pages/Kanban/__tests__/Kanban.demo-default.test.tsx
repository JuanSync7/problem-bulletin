/**
 * V5b — Default project selector to the seeded PB demo project.
 *
 * When listProjects returns a project with key === "PB", KanbanPage should
 * pick that project on initial load (instead of "DEF" or the first project).
 */
import "@testing-library/jest-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

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
          id: "p-other",
          key: "DEF",
          name: "Other project",
          created_by: "u-1",
          created_by_type: "user",
        },
        {
          id: "p-pb",
          key: "PB",
          name: "Problem-Bulletin",
          created_by: "u-1",
          created_by_type: "user",
        },
      ],
      next_cursor: null,
      total: 2,
    })),
    listComponents: vi.fn(async () => ({ items: [] })),
    listMembers: vi.fn(async () => ({ items: [] })),
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
      initialEntries={["/board"]}
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

describe("V5b — project selector defaults to PB", () => {
  it("selects the PB project when present in listProjects", async () => {
    renderPage();
    await waitFor(() => {
      const select = screen.getByLabelText("Project") as HTMLSelectElement;
      expect(select.value).toBe("PB");
    });
  });
});
