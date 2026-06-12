/**
 * V2b — HumanReviewBadge rendering inside MentionsTab.
 *
 * When a notification row carries ``kind: 'human_review'``, the row
 * renders a visually-distinct chip labelled "Human review". A plain
 * ``ticket_mention`` row in the same list MUST NOT render the chip
 * (negative assertion).
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

function row(overrides: Partial<api.TicketNotification>): api.TicketNotification {
  return {
    id: "n-1",
    kind: "ticket_mention",
    recipient_type: "user",
    recipient_id: "r-1",
    actor: {
      kind: "user",
      id: "u-1",
      display_name: "carol",
      handle: "carol",
      email: null,
      avatar_url: null,
    },
    target_type: "ticket",
    target_id: "t-1",
    target_display_id: "TKT-9",
    comment_id: null,
    excerpt: "please review",
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

describe("HumanReviewBadge", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders a distinct 'Human review' chip for kind='human_review'", async () => {
    (api.listNotifications as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        row({ id: "hr-1", kind: "human_review" }),
        row({ id: "m-1", kind: "ticket_mention" }),
      ],
      next_cursor: null,
      total: 2,
    });
    renderTab();

    await waitFor(() => {
      expect(screen.getAllByTestId("mentions-row")).toHaveLength(2);
    });

    const chip = screen.getByTestId("human-review-chip");
    expect(chip).toBeInTheDocument();
    expect(chip).toHaveTextContent(/human review/i);
    // Negative: only one chip in the document (the ticket_mention row has none).
    expect(screen.getAllByTestId("human-review-chip")).toHaveLength(1);
    // Visual distinctness: the chip carries its own class token.
    expect(chip.className).toMatch(/human-review/);
  });
});
