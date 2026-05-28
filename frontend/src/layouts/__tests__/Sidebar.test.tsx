/**
 * Sidebar WP31 tests — verify unread badge increments/decrements on WS payloads.
 *
 * We mock:
 *  - getUnreadCount: returns initial count.
 *  - useRealtimeNotifications: exposes a trigger function so tests can fire
 *    simulated WS payloads without a real WebSocket.
 */
import "@testing-library/jest-dom";
import { act, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as notifApi from "../../api/notifications";
import type { RealtimePayload } from "../../realtime/useRealtimeNotifications";
import { ThemeProvider } from "../../theme";
import { Sidebar } from "../Sidebar";

// matchMedia is not available in jsdom.
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

// Captured callback so tests can fire payloads.
let capturedCallback: ((p: RealtimePayload) => void) | null = null;

vi.mock("../../realtime/useRealtimeNotifications", () => ({
  useRealtimeNotifications: (cb: (p: RealtimePayload) => void) => {
    capturedCallback = cb;
    return { status: "open" };
  },
}));

vi.mock("../../api/notifications", () => ({
  getUnreadCount: vi.fn(async () => 3),
  listNotifications: vi.fn(async () => ({ items: [], next_cursor: null, total: 0 })),
  markRead: vi.fn(async () => undefined),
  markAllRead: vi.fn(async () => 0),
}));

function renderSidebar() {
  return render(
    <ThemeProvider>
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Sidebar isOpen={true} onClose={vi.fn()} />
      </MemoryRouter>
    </ThemeProvider>,
  );
}

describe("Sidebar realtime badge (WP31)", () => {
  beforeEach(() => {
    capturedCallback = null;
    vi.clearAllMocks();
  });

  it("shows initial unread badge from one-shot fetch", async () => {
    (notifApi.getUnreadCount as ReturnType<typeof vi.fn>).mockResolvedValue(3);
    renderSidebar();
    await waitFor(() => {
      expect(screen.getByLabelText(/3 unread mentions/i)).toBeInTheDocument();
    });
  });

  it("increments badge on ticket_notification WS payload", async () => {
    (notifApi.getUnreadCount as ReturnType<typeof vi.fn>).mockResolvedValue(2);
    renderSidebar();
    await waitFor(() => {
      expect(screen.getByLabelText(/2 unread mentions/i)).toBeInTheDocument();
    });

    act(() => {
      capturedCallback?.({
        type: "ticket_notification",
        kind: "ticket_mention",
        id: "x",
        target_display_id: "TKT-1",
        created_at: null,
      });
    });

    await waitFor(() => {
      expect(screen.getByLabelText(/3 unread mentions/i)).toBeInTheDocument();
    });
  });

  it("decrements badge on notification_read WS payload", async () => {
    (notifApi.getUnreadCount as ReturnType<typeof vi.fn>).mockResolvedValue(5);
    renderSidebar();
    await waitFor(() => {
      expect(screen.getByLabelText(/5 unread mentions/i)).toBeInTheDocument();
    });

    act(() => {
      capturedCallback?.({ type: "notification_read", id: "n-1", count: 1 });
    });

    await waitFor(() => {
      expect(screen.getByLabelText(/4 unread mentions/i)).toBeInTheDocument();
    });
  });

  it("decrements by count on notification_read_all WS payload", async () => {
    (notifApi.getUnreadCount as ReturnType<typeof vi.fn>).mockResolvedValue(10);
    renderSidebar();
    await waitFor(() => {
      expect(screen.getByLabelText(/10 unread mentions/i)).toBeInTheDocument();
    });

    act(() => {
      capturedCallback?.({ type: "notification_read_all", count: 10 });
    });

    // Badge should disappear when count is 0.
    await waitFor(() => {
      expect(
        screen.queryByLabelText(/unread mentions/i),
      ).not.toBeInTheDocument();
    });
  });
});

describe("Sidebar agent_id guard (WP34)", () => {
  beforeEach(() => {
    capturedCallback = null;
    vi.clearAllMocks();
  });

  it("does NOT increment badge for ticket_notification with agent_id", async () => {
    // Agent-inbox notifications should not affect the user-inbox badge.
    (notifApi.getUnreadCount as ReturnType<typeof vi.fn>).mockResolvedValue(2);
    renderSidebar();
    await waitFor(() => {
      expect(screen.getByLabelText(/2 unread mentions/i)).toBeInTheDocument();
    });

    act(() => {
      capturedCallback?.({
        type: "ticket_notification",
        kind: "ticket_mention",
        id: "x",
        agent_id: "agent-uuid-123",  // agent-inbox notification
        target_display_id: "TKT-1",
        created_at: null,
      });
    });

    // Badge must stay at 2 — agent notification does not affect user inbox badge.
    await waitFor(() => {
      expect(screen.getByLabelText(/2 unread mentions/i)).toBeInTheDocument();
    });
  });

  it("does NOT decrement badge for notification_read with agent_id", async () => {
    // Agent-inbox read events should not decrement the user-inbox badge.
    (notifApi.getUnreadCount as ReturnType<typeof vi.fn>).mockResolvedValue(5);
    renderSidebar();
    await waitFor(() => {
      expect(screen.getByLabelText(/5 unread mentions/i)).toBeInTheDocument();
    });

    act(() => {
      capturedCallback?.({
        type: "notification_read",
        id: "n-agent-1",
        count: 1,
        agent_id: "agent-uuid-123",  // agent-inbox read
      });
    });

    // Badge must stay at 5 — agent read does not affect user inbox badge.
    await waitFor(() => {
      expect(screen.getByLabelText(/5 unread mentions/i)).toBeInTheDocument();
    });
  });

  it("does NOT decrement badge for notification_read_all with agent_id", async () => {
    (notifApi.getUnreadCount as ReturnType<typeof vi.fn>).mockResolvedValue(8);
    renderSidebar();
    await waitFor(() => {
      expect(screen.getByLabelText(/8 unread mentions/i)).toBeInTheDocument();
    });

    act(() => {
      capturedCallback?.({
        type: "notification_read_all",
        count: 8,
        agent_id: "agent-uuid-123",  // agent-inbox bulk read
      });
    });

    // Badge must stay at 8.
    await waitFor(() => {
      expect(screen.getByLabelText(/8 unread mentions/i)).toBeInTheDocument();
    });
  });
});
