/**
 * WP13 — Activity page tests.
 *
 * Asserts:
 *  1. /activity renders with the agent tab active when no ?tab= param.
 *  2. Switching tab via click updates the URL ?tab=mentions and renders the mentions stub.
 *  3. Visiting /activity?tab=mine directly renders the mine stub panel.
 *  4. The agent tab panel renders the AgentActivityFeed component (via test-id + mock fetch).
 */
import "@testing-library/jest-dom";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Mock the audit API so AgentActivityFeed resolves immediately.
vi.mock("../../../api/audit", () => ({
  listAgentActivity: vi.fn(async () => []),
}));

// Mock WebSocket stream hook — no-op.
vi.mock("../../../hooks/useTicketStream", () => ({
  useTicketStream: () => undefined,
}));

// WP14 — MentionsTab fetches notifications. Stub the API.
vi.mock("../../../api/notifications", () => ({
  listNotifications: vi.fn(async () => ({ items: [], next_cursor: null, total: 0 })),
  getUnreadCount: vi.fn(async () => 0),
  markRead: vi.fn(async () => undefined),
  markAllRead: vi.fn(async () => 0),
}));

// WP23 — MineTab fetches tickets. Stub the API.
vi.mock("../../../api/tickets", () => ({
  listTickets: vi.fn(async () => ({ items: [], next_cursor: null, total: 0, column_counts: null })),
}));

// WP23 — MineTab uses useAuth. Stub a resolved user so the tab loads.
vi.mock("../../../hooks/useAuth", () => ({
  useAuth: () => ({
    user: { id: "u-1", email: "test@example.com", displayName: "Test", role: "user" },
    isAuthenticated: true,
    isLoading: false,
    error: null,
  }),
}));

import ActivityPage from "../index";

function renderActivity(initialEntry = "/activity") {
  return render(
    <MemoryRouter initialEntries={[initialEntry]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <ActivityPage />
    </MemoryRouter>,
  );
}

describe("ActivityPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders with agent tab active by default (no ?tab= param)", async () => {
    renderActivity("/activity");

    // Agent tab button should be marked active.
    const agentTab = screen.getByRole("tab", { name: /agent activity/i });
    expect(agentTab).toHaveAttribute("aria-selected", "true");

    // Agent panel should be visible.
    expect(screen.getByTestId("panel-agent")).toBeInTheDocument();

    // Other panels should not be in the DOM.
    expect(screen.queryByTestId("panel-mentions")).not.toBeInTheDocument();
    expect(screen.queryByTestId("panel-mine")).not.toBeInTheDocument();
  });

  it("clicking Mentions tab updates active tab and shows mentions stub", async () => {
    const user = userEvent.setup();
    renderActivity("/activity");

    const mentionsTab = screen.getByRole("tab", { name: /mentions/i });
    await user.click(mentionsTab);

    // Mentions tab is now active.
    await waitFor(() => {
      expect(mentionsTab).toHaveAttribute("aria-selected", "true");
    });

    // Mentions panel visible with correct data-tab and MentionsTab rendered.
    const panel = screen.getByTestId("panel-mentions");
    expect(panel).toBeInTheDocument();
    expect(panel).toHaveAttribute("data-tab", "mentions");
    expect(panel.querySelector('[data-testid="mentions-tab"]')).not.toBeNull();

    // Agent panel gone.
    expect(screen.queryByTestId("panel-agent")).not.toBeInTheDocument();
  });

  it("renders mine panel when visiting /activity?tab=mine directly", async () => {
    renderActivity("/activity?tab=mine");

    const mineTab = screen.getByRole("tab", { name: /my tickets/i });
    expect(mineTab).toHaveAttribute("aria-selected", "true");

    const panel = screen.getByTestId("panel-mine");
    expect(panel).toBeInTheDocument();
    expect(panel).toHaveAttribute("data-tab", "mine");

    // MineTab renders when API resolves (empty state).
    await waitFor(() => {
      expect(panel.querySelector('[data-testid="mine-tab"]')).not.toBeNull();
    });
  });

  it("agent tab panel renders AgentActivityFeed (shows loading state or feed container)", async () => {
    renderActivity("/activity");

    // The AgentActivityFeed renders a section.activity-feed — wait for it.
    await waitFor(() => {
      const panel = screen.getByTestId("panel-agent");
      // AgentActivityFeed renders aria-label="Agent activity feed"
      expect(panel.querySelector('[aria-label="Agent activity feed"]')).not.toBeNull();
    });
  });
});
