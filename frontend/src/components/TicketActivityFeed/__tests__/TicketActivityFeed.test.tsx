/**
 * TicketActivityFeed component — v2.4-WP26
 *
 * Covers:
 *  1. Loading state while fetching.
 *  2. Empty state when no activity items returned.
 *  3. Renders transition, comment, and link rows from the API.
 *  4. "Load more" button visible when next_cursor present; hidden when null.
 *  5. Clicking "Load more" fetches next page with cursor and appends rows.
 *  6. Error state when initial fetch fails.
 */
import "@testing-library/jest-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";

import { TicketActivityFeed } from "../index";
import type { ActivityItem, ActivityPage } from "../../../api/tickets";

const { listActivityMock } = vi.hoisted(() => ({
  listActivityMock: vi.fn(),
}));

vi.mock("../../../api/tickets", async () => {
  const actual = await vi.importActual<typeof import("../../../api/tickets")>(
    "../../../api/tickets",
  );
  return {
    ...actual,
    listActivity: (...args: unknown[]) => listActivityMock(...args),
  };
});

const TICKET_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa";
const TICKET_DISPLAY_ID = "TEST-1";

const baseTime = new Date("2026-05-18T10:00:00Z").getTime();

function makeTransition(n: number): ActivityItem {
  return {
    kind: "transition",
    id: `tr-${n}`,
    ticket_id: TICKET_ID,
    from_status: null,
    to_status: "in_progress",
    actor_type: "user",
    actor_id: "user-1",
    agent_step_id: null,
    reason: null,
    created_at: new Date(baseTime + n * 1000).toISOString(),
  };
}

function makeComment(n: number): ActivityItem {
  return {
    kind: "comment",
    id: `c-${n}`,
    ticket_id: TICKET_ID,
    body: `Comment body ${n}`,
    mentions: [],
    actor_type: "user",
    actor_id: "user-abc123",
    agent_step_id: null,
    created_at: new Date(baseTime + n * 1000).toISOString(),
    edited_at: null,
  };
}

function makeLink(n: number): ActivityItem {
  return {
    kind: "link",
    id: `l-${n}`,
    source_ticket_id: TICKET_ID,
    target_ticket_id: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    link_type: "blocks",
    actor_type: "user",
    actor_id: "user-1",
    agent_step_id: null,
    created_at: new Date(baseTime + n * 1000).toISOString(),
  } as ActivityItem;
}

function renderFeed() {
  return render(
    <TicketActivityFeed ticketId={TICKET_ID} ticketDisplayId={TICKET_DISPLAY_ID} />,
  );
}

describe("TicketActivityFeed", () => {
  beforeEach(() => {
    listActivityMock.mockReset();
  });

  it("shows loading state while fetching", () => {
    // Never resolves — keep it in loading state
    listActivityMock.mockReturnValue(new Promise(() => {}));
    renderFeed();
    expect(screen.getByTestId("activity-feed-loading")).toBeInTheDocument();
  });

  it("shows empty state when no activity returned", async () => {
    const emptyPage: ActivityPage = { items: [], next_cursor: null, total: 0 };
    listActivityMock.mockResolvedValue(emptyPage);
    renderFeed();
    await waitFor(() => {
      expect(screen.getByTestId("activity-feed-empty")).toBeInTheDocument();
    });
  });

  it("renders transition rows", async () => {
    const page: ActivityPage = {
      items: [makeTransition(1), makeTransition(2)],
      next_cursor: null,
      total: 2,
    };
    listActivityMock.mockResolvedValue(page);
    renderFeed();
    await waitFor(() => {
      expect(screen.getAllByTestId("activity-transition")).toHaveLength(2);
    });
  });

  it("renders comment rows", async () => {
    const page: ActivityPage = {
      items: [makeComment(1)],
      next_cursor: null,
      total: 1,
    };
    listActivityMock.mockResolvedValue(page);
    renderFeed();
    await waitFor(() => {
      expect(screen.getByTestId("activity-comment")).toBeInTheDocument();
    });
    expect(screen.getByTestId("activity-comment")).toHaveTextContent("Comment body 1");
  });

  it("renders link rows", async () => {
    const page: ActivityPage = {
      items: [makeLink(1)],
      next_cursor: null,
      total: 1,
    };
    listActivityMock.mockResolvedValue(page);
    renderFeed();
    await waitFor(() => {
      expect(screen.getByTestId("activity-link")).toBeInTheDocument();
    });
  });

  it("shows load-more button when next_cursor is present", async () => {
    const page: ActivityPage = {
      items: [makeTransition(1)],
      next_cursor: "cursor-xyz",
      total: 5,
    };
    listActivityMock.mockResolvedValue(page);
    renderFeed();
    await waitFor(() => {
      expect(screen.getByTestId("activity-load-more")).toBeInTheDocument();
    });
  });

  it("hides load-more button when next_cursor is null", async () => {
    const page: ActivityPage = {
      items: [makeTransition(1)],
      next_cursor: null,
      total: 1,
    };
    listActivityMock.mockResolvedValue(page);
    renderFeed();
    await waitFor(() => {
      expect(screen.getAllByTestId("activity-transition")).toHaveLength(1);
    });
    expect(screen.queryByTestId("activity-load-more")).not.toBeInTheDocument();
  });

  it("clicking load-more fetches next page with cursor and appends rows", async () => {
    const page1: ActivityPage = {
      items: [makeTransition(1), makeTransition(2)],
      next_cursor: "cursor-page2",
      total: 4,
    };
    const page2: ActivityPage = {
      items: [makeTransition(3), makeTransition(4)],
      next_cursor: null,
      total: null,
    };
    listActivityMock
      .mockResolvedValueOnce(page1)
      .mockResolvedValueOnce(page2);

    renderFeed();
    await waitFor(() => {
      expect(screen.getAllByTestId("activity-transition")).toHaveLength(2);
    });

    fireEvent.click(screen.getByTestId("activity-load-more"));

    await waitFor(() => {
      expect(screen.getAllByTestId("activity-transition")).toHaveLength(4);
    });

    // Load more button gone after last page
    expect(screen.queryByTestId("activity-load-more")).not.toBeInTheDocument();

    // Second call used the cursor from page 1
    const [, opts2] = listActivityMock.mock.calls[1];
    expect(opts2.cursor).toBe("cursor-page2");
  });

  it("passes include=[comments,links] to listActivity", async () => {
    const page: ActivityPage = { items: [], next_cursor: null, total: 0 };
    listActivityMock.mockResolvedValue(page);
    renderFeed();
    await waitFor(() => {
      expect(listActivityMock).toHaveBeenCalled();
    });
    const [, opts] = listActivityMock.mock.calls[0];
    expect(opts.include).toEqual(["comments", "links"]);
  });

  it("shows error state when initial fetch rejects", async () => {
    listActivityMock.mockRejectedValue(new Error("Network error"));
    renderFeed();
    await waitFor(() => {
      expect(screen.getByTestId("activity-feed-error")).toBeInTheDocument();
    });
    expect(screen.getByTestId("activity-feed-error")).toHaveTextContent("Network error");
  });
});
