/**
 * TicketDetailDrawer unit tests — v2.1-WP7.
 *
 * Covers the merged activity timeline (transitions, comments, links),
 * the "Last touched" header chip, and the agent_step_id chip rendering.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import { TicketDetailDrawer } from "../TicketDetailDrawer";
import type {
  ActivityItem,
  ActivityPage,
  TicketDTO,
} from "../../../api/tickets";

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

// MentionTextarea fires searchPeople under the hood — stub to avoid
// jsdom warnings about unfetchable URLs.
vi.mock("../../../api/people", () => ({
  searchPeople: vi.fn(async () => ({ items: [] })),
}));

function makeTicket(): TicketDTO {
  return {
    id: "11111111-1111-1111-1111-111111111111",
    display_id: "DEF-7",
    title: "WP7 ticket",
    status: "in_progress",
    priority: "medium",
    version: 2,
    last_activity_at: new Date(Date.now() - 7200_000).toISOString(),
  } as TicketDTO;
}

const baseTime = new Date("2026-05-15T10:00:00Z").getTime();

const activityItems: ActivityItem[] = [
  {
    kind: "transition",
    id: "tr-1",
    ticket_id: "11111111-1111-1111-1111-111111111111",
    from_status: "todo",
    to_status: "in_progress",
    actor_type: "agent",
    actor_id: "agent-1",
    agent_step_id: "step-XYZ",
    reason: null,
    created_at: new Date(baseTime + 30_000).toISOString(),
  },
  {
    kind: "comment",
    id: "c-1",
    ticket_id: "11111111-1111-1111-1111-111111111111",
    body: "looks good",
    mentions: [],
    actor_type: "user",
    actor_id: "user-abc123def",
    agent_step_id: null,
    created_at: new Date(baseTime + 20_000).toISOString(),
    edited_at: null,
  },
  {
    kind: "link",
    id: "l-1",
    ticket_id: "11111111-1111-1111-1111-111111111111",
    source_ticket_id: "11111111-1111-1111-1111-111111111111",
    target_ticket_id: "22222222-2222-2222-2222-222222222222",
    link_type: "blocks",
    actor_type: "user",
    actor_id: "user-abc123def",
    agent_step_id: null,
    created_at: new Date(baseTime + 10_000).toISOString(),
  } as ActivityItem,
];

describe("TicketDetailDrawer activity timeline", () => {
  beforeEach(() => {
    getTicketMock.mockReset();
    listActivityMock.mockReset();
    getTicketMock.mockResolvedValue(makeTicket());
    listActivityMock.mockResolvedValue({
      items: activityItems,
      next_cursor: null,
      total: activityItems.length,
    } satisfies ActivityPage);
  });

  it("renders merged timeline with transition, comment, and link rows", async () => {
    render(<TicketDetailDrawer ticketKey="DEF-7" onClose={() => {}} />);
    await waitFor(() => {
      expect(screen.getByTestId("activity-transition")).toBeInTheDocument();
    });
    expect(screen.getByTestId("activity-comment")).toBeInTheDocument();
    expect(screen.getByTestId("activity-link")).toBeInTheDocument();
  });

  it("shows the Last touched header chip from ticket.last_activity_at", async () => {
    render(<TicketDetailDrawer ticketKey="DEF-7" onClose={() => {}} />);
    await waitFor(() => {
      const chip = screen.getByTestId("ticket-last-touched");
      expect(chip).toBeInTheDocument();
      expect(chip.textContent ?? "").toMatch(/Last touched/);
    });
  });

  it("renders an agent_step_id chip when present on a transition row", async () => {
    render(<TicketDetailDrawer ticketKey="DEF-7" onClose={() => {}} />);
    await waitFor(() => {
      const chips = screen.getAllByTestId("activity-step-id");
      expect(chips.length).toBeGreaterThan(0);
      expect(chips[0].textContent).toContain("step-XYZ");
    });
  });

  it("composer renders MentionTextarea (WP9 @-autocomplete wiring)", async () => {
    render(<TicketDetailDrawer ticketKey="DEF-7" onClose={() => {}} />);
    await waitFor(() => {
      expect(screen.getByTestId("mention-textarea-input")).toBeInTheDocument();
    });
  });

  it("calls listActivity with merged include set", async () => {
    render(<TicketDetailDrawer ticketKey="DEF-7" onClose={() => {}} />);
    await waitFor(() => {
      expect(listActivityMock).toHaveBeenCalled();
    });
    const [, opts] = listActivityMock.mock.calls[0];
    expect(opts.include).toEqual(["comments", "links"]);
    expect(opts.limit).toBe(100);
  });
});
