/**
 * V4c — ``agent_invoked_in_comment`` row rendering inside MentionsTab.
 *
 * When a notification carries ``kind: 'agent_invoked_in_comment'``, the
 * row label MUST read "Your agent was invoked in a comment" and the
 * row's click target MUST navigate to the originating ticket so the
 * owner can drop in on the thread.
 *
 * Negative: a plain ``ticket_mention`` row alongside MUST NOT carry the
 * "Your agent was invoked in a comment" label.
 */
import "@testing-library/jest-dom";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
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

vi.mock("../../../realtime/useRealtimeNotifications", () => ({
  useRealtimeNotifications: (_cb: (p: RealtimePayload) => void) => ({
    status: "open" as const,
  }),
}));

function row(
  overrides: Partial<api.TicketNotification>,
): api.TicketNotification {
  return {
    id: "n-1",
    kind: "ticket_mention",
    recipient_type: "user",
    recipient_id: "r-1",
    actor: {
      kind: "agent",
      id: "u-1",
      display_name: "alice-coder",
      handle: "alice_coder",
      email: null,
      avatar_url: null,
    },
    target_type: "ticket",
    target_id: "t-1",
    target_display_id: "TKT-42",
    comment_id: "c-1",
    excerpt: null,
    is_read: false,
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

function renderTab() {
  return render(
    <MemoryRouter
      initialEntries={["/activity"]}
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <Routes>
        <Route path="/activity" element={<MentionsTab />} />
        <Route path="/tickets/:displayId" element={<div />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("AgentInvokedInComment", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders 'Your agent was invoked in a comment' label and links to the ticket", async () => {
    (api.listNotifications as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        row({
          id: "aic-1",
          kind: "agent_invoked_in_comment",
          excerpt: "response_comment_id:c-response",
        }),
        row({ id: "m-1", kind: "ticket_mention" }),
      ],
      next_cursor: null,
      total: 2,
    });
    renderTab();

    await waitFor(() => {
      expect(screen.getAllByTestId("mentions-row")).toHaveLength(2);
    });

    const badge = screen.getByTestId("agent-invoked-chip");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent(/your agent was invoked in a comment/i);

    // Negative: exactly ONE such chip — the ticket_mention row does not
    // render it.
    expect(screen.getAllByTestId("agent-invoked-chip")).toHaveLength(1);

    // Click target — the row's button references the ticket's display id
    // so the navigate() hop opens the originating thread.
    const rows = screen.getAllByTestId("mentions-row");
    const aicRow = rows.find((r) => r.getAttribute("data-id") === "aic-1");
    expect(aicRow).toBeDefined();
    expect(aicRow!.innerHTML).toMatch(/TKT-42/);
  });
});
