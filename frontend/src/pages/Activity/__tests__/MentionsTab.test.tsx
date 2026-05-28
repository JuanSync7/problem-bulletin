/**
 * WP14/WP25 — MentionsTab tests.
 *
 * Covers:
 *  1. Empty-state when API returns no items.
 *  2. Rows render actor handle + target_display_id + excerpt.
 *  3. Unread/All toggle re-fetches with `only_unread` flipped.
 *  4. Clicking a row calls markRead + navigates to /tickets/<display_id>.
 *  5. (WP25) ticket_assigned kind renders "assigned to you" label.
 *  6. (WP25) ticket_state_change kind renders excerpt as status chain.
 *  7. (WP25) Unknown kind renders fallback "activity on" label.
 *  8. (WP25) Me/My-agents toggle switches recipient_kind.
 *  9. (WP25) My-agents button is disabled with tooltip when hasAgentAccounts=false.
 */
import "@testing-library/jest-dom";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../../../api/notifications";
import type { RealtimePayload } from "../../../realtime/useRealtimeNotifications";
import MentionsTab from "../MentionsTab";

vi.mock("../../../api/notifications", () => ({
  listNotifications: vi.fn(),
  getUnreadCount: vi.fn(async () => 0),
  markRead: vi.fn(async () => undefined),
  markAllRead: vi.fn(async () => 0),
}));

// WP31: capture the WS callback so we can fire simulated payloads.
let capturedWsCallback: ((p: RealtimePayload) => void) | null = null;
vi.mock("../../../realtime/useRealtimeNotifications", () => ({
  useRealtimeNotifications: (cb: (p: RealtimePayload) => void) => {
    capturedWsCallback = cb;
    return { status: "open" };
  },
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

function renderTab(
  initial = "/activity",
  props: Partial<React.ComponentProps<typeof MentionsTab>> = {},
) {
  return render(
    <MemoryRouter initialEntries={[initial]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <Routes>
        <Route
          path="/activity"
          element={
            <>
              <MentionsTab {...props} />
              <LocationProbe />
            </>
          }
        />
        <Route path="/board" element={<LocationProbe />} />
        <Route path="/tickets/:displayId" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

function fakeRow(overrides: Partial<api.TicketNotification> = {}): api.TicketNotification {
  return {
    id: "n-1",
    kind: "ticket_mention",
    recipient_type: "user",
    recipient_id: "r-1",
    actor: {
      kind: "user",
      id: "u-1",
      display_name: "alice",
      handle: "alice",
      email: null,
      avatar_url: null,
    },
    target_type: "ticket",
    target_id: "t-1",
    target_display_id: "TKT-42",
    comment_id: "c-1",
    excerpt: "please look",
    is_read: false,
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

describe("MentionsTab", () => {
  beforeEach(() => {
    capturedWsCallback = null;
    vi.clearAllMocks();
  });

  it("renders empty state when API returns no items", async () => {
    (api.listNotifications as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [],
      next_cursor: null,
      total: 0,
    });
    renderTab();
    await waitFor(() => {
      expect(screen.getByTestId("mentions-empty")).toBeInTheDocument();
    });
    expect(screen.getByTestId("mentions-empty")).toHaveTextContent(/no mentions yet/i);
  });

  it("renders rows with actor display_name + target_display_id + excerpt", async () => {
    (api.listNotifications as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [fakeRow()],
      next_cursor: null,
      total: 1,
    });
    renderTab();
    await waitFor(() => {
      expect(screen.getByTestId("mentions-row")).toBeInTheDocument();
    });
    const row = screen.getByTestId("mentions-row");
    expect(row).toHaveTextContent("alice");
    expect(row).toHaveTextContent("TKT-42");
    expect(row).toHaveTextContent("please look");
    expect(row).toHaveAttribute("data-unread", "true");
  });

  it("All/Unread toggle re-fetches with only_unread flipped", async () => {
    const mock = api.listNotifications as ReturnType<typeof vi.fn>;
    mock.mockResolvedValueOnce({
      items: [fakeRow({ id: "u" })],
      next_cursor: null,
      total: 1,
    });
    mock.mockResolvedValueOnce({
      items: [fakeRow({ id: "a-1" }), fakeRow({ id: "a-2", is_read: true })],
      next_cursor: null,
      total: 2,
    });
    const user = userEvent.setup();
    renderTab();

    await waitFor(() => {
      expect(mock).toHaveBeenCalledWith(
        expect.objectContaining({ only_unread: true }),
      );
    });

    const allBtn = screen.getByRole("tab", { name: /^all$/i });
    await user.click(allBtn);

    await waitFor(() => {
      expect(mock).toHaveBeenCalledWith(
        expect.objectContaining({ only_unread: false }),
      );
    });
    await waitFor(() => {
      expect(screen.getAllByTestId("mentions-row")).toHaveLength(2);
    });
  });

  it("clicks row → calls markRead and navigates to /tickets/<display_id>", async () => {
    (api.listNotifications as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [fakeRow()],
      next_cursor: null,
      total: 1,
    });
    const user = userEvent.setup();
    renderTab();
    await waitFor(() => {
      expect(screen.getByTestId("mentions-row")).toBeInTheDocument();
    });
    const btn = screen.getByTestId("mentions-row").querySelector("button")!;
    await act(async () => {
      await user.click(btn);
    });
    expect(api.markRead).toHaveBeenCalledWith("n-1");
    await waitFor(() => {
      expect(screen.getByTestId("probe-location")).toHaveTextContent(
        "/tickets/TKT-42",
      );
    });
  });

  // --- WP25 new tests ---

  it("ticket_assigned kind renders 'assigned to you' label", async () => {
    (api.listNotifications as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        fakeRow({
          id: "n-2",
          kind: "ticket_assigned",
          excerpt: "Assigned to you: My ticket",
        }),
      ],
      next_cursor: null,
      total: 1,
    });
    renderTab();
    await waitFor(() => {
      expect(screen.getByTestId("mentions-row")).toBeInTheDocument();
    });
    const row = screen.getByTestId("mentions-row");
    expect(row).toHaveTextContent(/assigned to you/i);
    expect(row).toHaveTextContent("TKT-42");
  });

  it("ticket_state_change kind renders status excerpt", async () => {
    (api.listNotifications as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        fakeRow({
          id: "n-3",
          kind: "ticket_state_change",
          excerpt: "todo → in_progress",
          comment_id: null,
        }),
      ],
      next_cursor: null,
      total: 1,
    });
    renderTab();
    await waitFor(() => {
      expect(screen.getByTestId("mentions-row")).toBeInTheDocument();
    });
    const row = screen.getByTestId("mentions-row");
    expect(row).toHaveTextContent(/status/i);
    expect(row).toHaveTextContent("todo → in_progress");
    expect(row).toHaveTextContent("TKT-42");
  });

  it("unknown kind renders fallback 'activity on' label", async () => {
    (api.listNotifications as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        fakeRow({
          id: "n-4",
          kind: "ticket_unknown_future_kind",
          excerpt: null,
        }),
      ],
      next_cursor: null,
      total: 1,
    });
    renderTab();
    await waitFor(() => {
      expect(screen.getByTestId("mentions-row")).toBeInTheDocument();
    });
    const row = screen.getByTestId("mentions-row");
    expect(row).toHaveTextContent(/activity on/i);
    expect(row).toHaveTextContent("TKT-42");
  });

  it("Me/My-agents toggle switches to agent recipient_kind when hasAgentAccounts=true", async () => {
    const mock = api.listNotifications as ReturnType<typeof vi.fn>;
    mock.mockResolvedValue({ items: [], next_cursor: null, total: 0 });
    const user = userEvent.setup();
    renderTab("/activity", { hasAgentAccounts: true });

    await waitFor(() => {
      expect(mock).toHaveBeenCalledWith(
        expect.objectContaining({ recipient_kind: "user" }),
      );
    });

    const agentsBtn = screen.getByRole("tab", { name: /my agents/i });
    expect(agentsBtn).not.toBeDisabled();
    await user.click(agentsBtn);

    await waitFor(() => {
      expect(mock).toHaveBeenCalledWith(
        expect.objectContaining({ recipient_kind: "agent" }),
      );
    });
  });

  it("My-agents button is disabled with tooltip when hasAgentAccounts=false", async () => {
    (api.listNotifications as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [],
      next_cursor: null,
      total: 0,
    });
    renderTab("/activity", { hasAgentAccounts: false });
    await waitFor(() => {
      expect(
        api.listNotifications as ReturnType<typeof vi.fn>,
      ).toHaveBeenCalled();
    });
    const agentsBtn = screen.getByRole("tab", { name: /my agents/i });
    expect(agentsBtn).toBeDisabled();
    expect(agentsBtn).toHaveAttribute("title", "No agent accounts linked");
  });

  // --- WP30 new tests ---

  it("ticket_watcher_added kind renders 'Watching · <display_id>'", async () => {
    (api.listNotifications as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        fakeRow({
          id: "n-watcher",
          kind: "ticket_watcher_added",
          excerpt: null,
        }),
      ],
      next_cursor: null,
      total: 1,
    });
    renderTab();
    await waitFor(() => {
      expect(screen.getByTestId("mentions-row")).toBeInTheDocument();
    });
    const row = screen.getByTestId("mentions-row");
    expect(row).toHaveTextContent(/watching/i);
    expect(row).toHaveTextContent("TKT-42");
  });

  // --- WP41: ticket_watcher_added badge + excerpt ---

  it("ticket_watcher_added renders neutral 'watcher' badge with excerpt", async () => {
    (api.listNotifications as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        fakeRow({
          id: "n-watcher-wp41",
          kind: "ticket_watcher_added",
          excerpt: "You were added as a watcher",
        }),
      ],
      next_cursor: null,
      total: 1,
    });
    renderTab();
    await waitFor(() => {
      expect(screen.getByTestId("mentions-row")).toBeInTheDocument();
    });
    const row = screen.getByTestId("mentions-row");
    expect(row).toHaveTextContent("TKT-42");
    expect(row).toHaveTextContent(/you were added as a watcher/i);
    // WP41: neutral/info badge — NOT red (blocked) or green (resolved).
    const badge = row.querySelector(".mentions-row__badge--watcher");
    expect(badge).toBeInTheDocument();
    expect(row.querySelector(".mentions-row__badge--blocked")).toBeNull();
    expect(row.querySelector(".mentions-row__badge--resolved")).toBeNull();
  });

  it("ticket_blocked kind renders 'Blocked · <display_id>' with blocked badge", async () => {
    (api.listNotifications as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        fakeRow({
          id: "n-blocked",
          kind: "ticket_blocked",
          excerpt: null,
        }),
      ],
      next_cursor: null,
      total: 1,
    });
    renderTab();
    await waitFor(() => {
      expect(screen.getByTestId("mentions-row")).toBeInTheDocument();
    });
    const row = screen.getByTestId("mentions-row");
    expect(row).toHaveTextContent(/blocked/i);
    expect(row).toHaveTextContent("TKT-42");
    // Badge element should be present
    const badge = row.querySelector(".mentions-row__badge--blocked");
    expect(badge).toBeInTheDocument();
  });

  // --- WP37 new tests ---

  it("ticket_resolved kind renders 'Resolved · <display_id>' with resolved badge", async () => {
    (api.listNotifications as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        fakeRow({
          id: "n-resolved",
          kind: "ticket_resolved",
          excerpt: "in_progress → done",
        }),
      ],
      next_cursor: null,
      total: 1,
    });
    renderTab();
    await waitFor(() => {
      expect(screen.getByTestId("mentions-row")).toBeInTheDocument();
    });
    const row = screen.getByTestId("mentions-row");
    expect(row).toHaveTextContent(/resolved/i);
    expect(row).toHaveTextContent("TKT-42");
    const badge = row.querySelector(".mentions-row__badge--resolved");
    expect(badge).toBeInTheDocument();
  });

  // --- WP40 new test ---

  it("ticket_cancelled kind renders 'Cancelled · <display_id>' with cancelled badge", async () => {
    (api.listNotifications as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        fakeRow({
          id: "n-cancelled",
          kind: "ticket_cancelled",
          excerpt: "in_progress → cancelled",
        }),
      ],
      next_cursor: null,
      total: 1,
    });
    renderTab();
    await waitFor(() => {
      expect(screen.getByTestId("mentions-row")).toBeInTheDocument();
    });
    const row = screen.getByTestId("mentions-row");
    expect(row).toHaveTextContent(/cancelled/i);
    expect(row).toHaveTextContent("TKT-42");
    const badge = row.querySelector(".mentions-row__badge--cancelled");
    expect(badge).toBeInTheDocument();
  });

  it("ticket_due_soon kind renders 'Due soon · <display_id>' with warning badge", async () => {
    (api.listNotifications as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        fakeRow({
          id: "n-due-soon",
          kind: "ticket_due_soon",
          excerpt: "Due 2026-05-20T00:00:00+00:00",
        }),
      ],
      next_cursor: null,
      total: 1,
    });
    renderTab();
    await waitFor(() => {
      expect(screen.getByTestId("mentions-row")).toBeInTheDocument();
    });
    const row = screen.getByTestId("mentions-row");
    expect(row).toHaveTextContent(/due soon/i);
    expect(row).toHaveTextContent("TKT-42");
    const badge = row.querySelector(".mentions-row__badge--warning");
    expect(badge).toBeInTheDocument();
  });

  // --- WP31 realtime tests ---

  it("(WP31) prepends a stub row when ticket_notification WS payload arrives", async () => {
    (api.listNotifications as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [fakeRow({ id: "existing-1" })],
      next_cursor: null,
      total: 1,
    });
    renderTab();
    await waitFor(() => {
      expect(screen.getAllByTestId("mentions-row")).toHaveLength(1);
    });

    act(() => {
      capturedWsCallback?.({
        type: "ticket_notification",
        kind: "ticket_mention",
        id: "rt-new",
        target_display_id: "TKT-99",
        created_at: new Date().toISOString(),
      });
    });

    await waitFor(() => {
      expect(screen.getAllByTestId("mentions-row")).toHaveLength(2);
    });
    // First row should be the new stub (unread).
    const rows = screen.getAllByTestId("mentions-row");
    expect(rows[0]).toHaveAttribute("data-unread", "true");
  });
});
