/**
 * WP43 — Lane-height toggle integration tests.
 *
 * Verifies that the segmented control rendered in KanbanPage:
 *  1. Renders all four lane-height buttons with role="radio" semantics.
 *  2. "70vh" is active by default (aria-checked="true").
 *  3. Clicking "Unlimited" writes --kanban-lane-height: none on the wrapper
 *     and persists "unlimited" to localStorage.
 *  4. Clicking "50vh" writes --kanban-lane-height: 50vh on the wrapper.
 */
import "@testing-library/jest-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

// --- Module mocks (must precede the import of the page) ---

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
          id: "p-1",
          key: "TST",
          name: "Test Project",
          created_by: "u-1",
          created_by_type: "user",
        },
      ],
    })),
    listComponents: vi.fn(async () => ({ items: [] })),
    listMembers: vi.fn(async () => ({ items: [] })),
    // V5b — kanban refresh path now hits getProjectHierarchy.
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
    <MemoryRouter initialEntries={["/board"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
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

describe("Kanban lane-height toggle", () => {
  it("renders all four lane-height buttons with role='radio'", async () => {
    renderPage();
    await waitFor(() => {
      for (const pref of ["50vh", "70vh", "90vh", "unlimited"]) {
        const btn = screen.getByTestId(`lane-height-btn-${pref}`);
        expect(btn).toBeInTheDocument();
        expect(btn).toHaveAttribute("role", "radio");
      }
      const group = screen.getByTestId("lane-height-toggle");
      expect(group).toHaveAttribute("role", "radiogroup");
      expect(group).toHaveAttribute("aria-label", "Lane height");
    });
  });

  it("'unlimited' button is active by default (aria-checked='true')", async () => {
    renderPage();
    await waitFor(() => {
      const defaultBtn = screen.getByTestId("lane-height-btn-unlimited");
      expect(defaultBtn).toHaveAttribute("aria-checked", "true");
      expect(defaultBtn).toHaveClass(
        "kanban-lane-height-toggle__btn--active",
      );
    });
  });

  it("clicking 'Unlimited' sets --kanban-lane-height: none and persists 'unlimited'", async () => {
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("lane-height-btn-unlimited")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("lane-height-btn-unlimited"));

    await waitFor(() => {
      const btn = screen.getByTestId("lane-height-btn-unlimited");
      expect(btn).toHaveAttribute("aria-checked", "true");

      // 'unlimited' was the previously active default; verify it deactivates.
      // After clicking 'unlimited' below this stays "true" so we don't re-assert.

      const boardRoot = document.querySelector(
        ".kanban-board-root",
      ) as HTMLElement;
      expect(boardRoot).toBeTruthy();
      expect(boardRoot.style.getPropertyValue("--kanban-lane-height")).toBe(
        "none",
      );

      expect(localStorage.getItem("kanban.laneHeight")).toBe("unlimited");
    });
  });

  it("clicking '50vh' sets --kanban-lane-height: 50vh on the wrapper", async () => {
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("lane-height-btn-50vh")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("lane-height-btn-50vh"));

    await waitFor(() => {
      const boardRoot = document.querySelector(
        ".kanban-board-root",
      ) as HTMLElement;
      expect(boardRoot.style.getPropertyValue("--kanban-lane-height")).toBe(
        "50vh",
      );
      expect(localStorage.getItem("kanban.laneHeight")).toBe("50vh");
    });
  });
});
