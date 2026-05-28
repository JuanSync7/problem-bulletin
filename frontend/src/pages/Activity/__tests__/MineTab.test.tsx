/**
 * WP23 — MineTab tests.
 *
 * Covers:
 *  1. Renders empty state when API returns no items.
 *  2. Renders ticket rows with display_id + title.
 *  3. Clicking a row navigates to /tickets/<display_id>.
 *  4. "Open only" toggle changes the API call (status filter present vs absent).
 */
import "@testing-library/jest-dom";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as ticketsApi from "../../../api/tickets";
import MineTab from "../MineTab";

// Stub tickets API.
vi.mock("../../../api/tickets", () => ({
  listTickets: vi.fn(),
}));

// Stub useAuth with a resolved user.
vi.mock("../../../hooks/useAuth", () => ({
  useAuth: () => ({
    user: { id: "user-uuid-1", email: "alice@example.com", displayName: "Alice", role: "user" },
    isAuthenticated: true,
    isLoading: false,
    error: null,
  }),
}));

function LocationProbe() {
  const loc = useLocation();
  return (
    <div data-testid="probe-location">
      {loc.pathname}
      {loc.search}
    </div>
  );
}

function renderTab(initial = "/activity") {
  return render(
    <MemoryRouter initialEntries={[initial]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <Routes>
        <Route
          path="/activity"
          element={
            <>
              <MineTab />
              <LocationProbe />
            </>
          }
        />
        <Route path="/tickets/:displayId" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

function fakeTicket(overrides: Partial<ticketsApi.TicketDTO> = {}): ticketsApi.TicketDTO {
  return {
    id: "t-uuid-1",
    display_id: "DEF-7",
    title: "Fix the login bug",
    status: "in_progress",
    priority: "high",
    project_key: "DEF",
    project_id: "proj-uuid-1",
    assignee_id: "user-uuid-1",
    assignee_type: "user",
    last_activity_at: new Date().toISOString(),
    created_at: new Date().toISOString(),
    version: 1,
    ...overrides,
  };
}

describe("MineTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders empty state when API returns no items", async () => {
    (ticketsApi.listTickets as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [],
      next_cursor: null,
      total: 0,
      column_counts: null,
    });

    renderTab();

    await waitFor(() => {
      expect(screen.getByTestId("mine-empty")).toBeInTheDocument();
    });
    expect(screen.getByTestId("mine-empty")).toHaveTextContent(
      /no tickets assigned to you/i,
    );
  });

  it("renders ticket rows with display_id and title", async () => {
    (ticketsApi.listTickets as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [fakeTicket()],
      next_cursor: null,
      total: 1,
      column_counts: null,
    });

    renderTab();

    await waitFor(() => {
      expect(screen.getByTestId("mine-row")).toBeInTheDocument();
    });
    const row = screen.getByTestId("mine-row");
    expect(row).toHaveTextContent("DEF-7");
    expect(row).toHaveTextContent("Fix the login bug");
  });

  it("clicking a row navigates to /tickets/<display_id>", async () => {
    (ticketsApi.listTickets as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [fakeTicket()],
      next_cursor: null,
      total: 1,
      column_counts: null,
    });

    const user = userEvent.setup();
    renderTab();

    await waitFor(() => {
      expect(screen.getByTestId("mine-row")).toBeInTheDocument();
    });

    const btn = screen.getByTestId("mine-row").querySelector("button")!;
    await act(async () => {
      await user.click(btn);
    });

    await waitFor(() => {
      expect(screen.getByTestId("probe-location")).toHaveTextContent(
        "/tickets/DEF-7",
      );
    });
  });

  it("Open only toggle (default) calls listTickets with status filter", async () => {
    const mock = ticketsApi.listTickets as ReturnType<typeof vi.fn>;
    mock.mockResolvedValue({
      items: [],
      next_cursor: null,
      total: 0,
      column_counts: null,
    });

    renderTab();

    await waitFor(() => {
      expect(mock).toHaveBeenCalledWith(
        expect.objectContaining({
          assignee_id: "me",
          status: expect.arrayContaining(["todo", "in_progress", "in_review", "blocked", "backlog"]),
        }),
      );
    });

    // Status filter must NOT include terminal statuses.
    const call = mock.mock.calls[0][0] as ticketsApi.ListTicketsParams;
    expect(call.status).not.toContain("done");
    expect(call.status).not.toContain("cancelled");
  });

  it("switching to All toggle calls listTickets without a status filter", async () => {
    const mock = ticketsApi.listTickets as ReturnType<typeof vi.fn>;
    mock.mockResolvedValue({
      items: [],
      next_cursor: null,
      total: 0,
      column_counts: null,
    });

    const user = userEvent.setup();
    renderTab();

    // Wait for initial (Open only) load.
    await waitFor(() => {
      expect(mock).toHaveBeenCalledTimes(1);
    });

    const allBtn = screen.getByRole("tab", { name: /^all$/i });
    await user.click(allBtn);

    // Second call should have no status filter.
    await waitFor(() => {
      expect(mock).toHaveBeenCalledTimes(2);
    });

    const secondCall = mock.mock.calls[1][0] as ticketsApi.ListTicketsParams;
    expect(secondCall.status).toBeUndefined();
    expect(secondCall.assignee_id).toBe("me");
  });
});
