/**
 * v2.2-WP16 — TicketDetailDrawer cursor-based "Load more" tests.
 *
 * 1. First fetch renders rows; "Load more" visible when next_cursor present.
 * 2. Click "Load more" → fetches with cursor param; appends rows;
 *    button hides when next_cursor=null.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";

import { TicketDetailDrawer } from "../TicketDetailDrawer";
import type { ActivityItem, ActivityPage, TicketDTO } from "../../../api/tickets";

const { getTicketMock, listActivityMock } = vi.hoisted(() => ({
  getTicketMock: vi.fn(),
  listActivityMock: vi.fn(),
}));

vi.mock("../../../api/tickets", async () => {
  const actual = await vi.importActual<typeof import("../../../api/tickets")>(
    "../../../api/tickets",
  );
  return {
    ...actual,
    getTicket: (...args: unknown[]) => getTicketMock(...args),
    listActivity: (...args: unknown[]) => listActivityMock(...args),
  };
});

vi.mock("../../../api/people", () => ({
  searchPeople: vi.fn(async () => ({ items: [] })),
}));

function makeTicket(): TicketDTO {
  return {
    id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    display_id: "WP16-1",
    title: "Cursor test ticket",
    status: "in_progress",
    priority: "medium",
    version: 1,
    last_activity_at: new Date(Date.now() - 3600_000).toISOString(),
  } as TicketDTO;
}

const baseTime = new Date("2026-05-18T10:00:00Z").getTime();

function makeTransition(n: number): ActivityItem {
  return {
    kind: "transition",
    id: `tr-${n}`,
    ticket_id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    from_status: null,
    to_status: "in_progress",
    actor_type: "user",
    actor_id: "user-1",
    agent_step_id: null,
    reason: null,
    created_at: new Date(baseTime + n * 1000).toISOString(),
  };
}

describe("TicketDetailDrawer — cursor Load more", () => {
  beforeEach(() => {
    getTicketMock.mockReset();
    listActivityMock.mockReset();
    getTicketMock.mockResolvedValue(makeTicket());
  });

  it("renders first page rows and shows Load more when next_cursor present", async () => {
    const page1: ActivityPage = {
      items: [makeTransition(2), makeTransition(1)],
      next_cursor: "opaque-cursor-abc",
      total: 4,
    };
    listActivityMock.mockResolvedValueOnce(page1);

    render(<TicketDetailDrawer ticketKey="WP16-1" onClose={() => {}} />);
    await waitFor(() => {
      expect(screen.getAllByTestId("activity-transition")).toHaveLength(2);
    });
    // Load more button visible because next_cursor is non-null.
    expect(screen.getByTestId("activity-load-more")).toBeInTheDocument();
    // First call has no cursor param.
    const [, opts] = listActivityMock.mock.calls[0];
    expect(opts.cursor).toBeUndefined();
  });

  it("click Load more appends rows and hides button on last page", async () => {
    const page1: ActivityPage = {
      items: [makeTransition(2), makeTransition(1)],
      next_cursor: "opaque-cursor-abc",
      total: 4,
    };
    const page2: ActivityPage = {
      items: [makeTransition(4), makeTransition(3)],
      next_cursor: null,
      total: null,
    };
    listActivityMock
      .mockResolvedValueOnce(page1)
      .mockResolvedValueOnce(page2);

    render(<TicketDetailDrawer ticketKey="WP16-1" onClose={() => {}} />);
    await waitFor(() => {
      expect(screen.getAllByTestId("activity-transition")).toHaveLength(2);
    });

    const btn = screen.getByTestId("activity-load-more");
    fireEvent.click(btn);

    // After load more, both pages' rows are rendered.
    await waitFor(() => {
      expect(screen.getAllByTestId("activity-transition")).toHaveLength(4);
    });
    // Button is hidden because next_cursor is null after page 2.
    expect(screen.queryByTestId("activity-load-more")).not.toBeInTheDocument();

    // Second call received the cursor from page 1.
    const [, opts2] = listActivityMock.mock.calls[1];
    expect(opts2.cursor).toBe("opaque-cursor-abc");
  });
});
