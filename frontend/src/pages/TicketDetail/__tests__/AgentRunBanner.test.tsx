/**
 * V4b — AgentRunBanner test
 *
 * Mounts TicketDetail with a fixture ticket whose assignee is an agent
 * and which has 1 done agent_run. Asserts a banner renders linking to
 * the agent's posted comment.
 */
import "@testing-library/jest-dom";
import { act, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi, beforeEach } from "vitest";

vi.mock("../../../api/people", () => ({
  searchPeople: vi.fn(async () => ({ items: [] })),
}));

vi.mock("../../../api/tickets", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../api/tickets")>();
  return {
    ...actual,
    getTicket: vi.fn(),
    transitionTicket: vi.fn(),
    updateTicket: vi.fn(),
    assignTicket: vi.fn(),
    listActivity: vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null, total: 0 }),
  };
});

vi.mock("../../../api/agent_runs", () => ({
  listAgentRuns: vi.fn(),
  processNext: vi.fn(),
}));

import * as ticketsApi from "../../../api/tickets";
import * as agentRunsApi from "../../../api/agent_runs";
import TicketDetail from "../index";
import { AgentRunBanner } from "../AgentRunBanner";

function renderDetail(displayId = "WEB-42") {
  return render(
    <MemoryRouter
      initialEntries={[`/tickets/${displayId}`]}
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <Routes>
        <Route path="/tickets/:displayId" element={<TicketDetail />} />
      </Routes>
    </MemoryRouter>,
  );
}

function makeAgentTicket() {
  return {
    id: "ticket-uuid",
    display_id: "WEB-42",
    title: "Fix login redirect loop",
    status: "in_progress" as const,
    priority: "high" as const,
    type: "bug",
    description: "Body.",
    project_key: "WEB",
    project_id: "proj-1",
    version: 4,
    assignee_id: "agent-uuid",
    assignee_type: "agent",
  };
}

describe("AgentRunBanner on TicketDetail", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (ticketsApi.listActivity as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [],
      next_cursor: null,
      total: 0,
    });
  });

  it("renders banner with comment link when latest agent_run is done", async () => {
    (ticketsApi.getTicket as ReturnType<typeof vi.fn>).mockResolvedValue(
      makeAgentTicket(),
    );
    (agentRunsApi.listAgentRuns as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        {
          id: "run-1",
          status: "done",
          agent_id: "agent-uuid",
          agent_handle: "alice-coder",
          ticket_id: "ticket-uuid",
          comment_id: "comment-1",
          response_body: "Found root cause: ...",
          enqueued_at: "2026-06-02T00:00:00Z",
          finished_at: "2026-06-02T00:01:00Z",
        },
      ],
      total: 1,
    });

    renderDetail();

    await waitFor(() => {
      expect(screen.getByTestId("agent-run-banner")).toBeInTheDocument();
    });

    const banner = screen.getByTestId("agent-run-banner");
    expect(banner).toHaveTextContent(/responded/i);
    const link = screen.getByTestId("agent-run-banner-link");
    expect(link).toHaveAttribute("href", "#comment-comment-1");
  });

  it("does NOT render banner when there is no done agent_run", async () => {
    (ticketsApi.getTicket as ReturnType<typeof vi.fn>).mockResolvedValue(
      makeAgentTicket(),
    );
    (agentRunsApi.listAgentRuns as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [],
      total: 0,
    });

    renderDetail();

    await waitFor(() => {
      expect(screen.getByTestId("ticket-title")).toBeInTheDocument();
    });
    expect(screen.queryByTestId("agent-run-banner")).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// v2.29 S5 — pending / running / error states + 5 s poll while in-flight.
// These render the banner directly (no full TicketDetail mount) so fake
// timers stay tractable.
// ---------------------------------------------------------------------------

function makeRun(over: Partial<Record<string, unknown>> = {}) {
  return {
    id: "run-1",
    status: "pending",
    agent_id: "agent-uuid",
    agent_handle: "alice-coder",
    ticket_id: "ticket-uuid",
    comment_id: null,
    response_body: null,
    error: null,
    enqueued_at: "2026-06-02T00:00:00Z",
    started_at: null,
    finished_at: null,
    ...over,
  };
}

describe("AgentRunBanner lifecycle states (v2.29)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  async function flush() {
    // Let the in-flight listAgentRuns promise resolve and React commit.
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
  }

  it("renders 'queued' for a pending run", async () => {
    (agentRunsApi.listAgentRuns as ReturnType<typeof vi.fn>).mockResolvedValue(
      { items: [makeRun({ status: "pending" })], total: 1 },
    );
    render(<AgentRunBanner ticketId="ticket-uuid" />);
    await flush();

    const banner = screen.getByTestId("agent-run-banner");
    expect(banner).toHaveTextContent(/queued/i);
    expect(banner).toHaveTextContent("alice-coder");
    expect(banner.className).toContain("agent-run-banner--pending");
  });

  it("renders pulsing 'working…' for a running run", async () => {
    (agentRunsApi.listAgentRuns as ReturnType<typeof vi.fn>).mockResolvedValue(
      { items: [makeRun({ status: "running" })], total: 1 },
    );
    render(<AgentRunBanner ticketId="ticket-uuid" />);
    await flush();

    const banner = screen.getByTestId("agent-run-banner");
    expect(banner).toHaveTextContent(/working/);
    expect(banner.className).toContain("agent-run-banner--running");
  });

  it("renders 'failed' with the error excerpt in title for an error run", async () => {
    (agentRunsApi.listAgentRuns as ReturnType<typeof vi.fn>).mockResolvedValue(
      {
        items: [makeRun({ status: "error", error: "provider exploded" })],
        total: 1,
      },
    );
    render(<AgentRunBanner ticketId="ticket-uuid" />);
    await flush();

    const banner = screen.getByTestId("agent-run-banner");
    expect(banner).toHaveTextContent(/failed/i);
    expect(banner).toHaveAttribute("title", "provider exploded");
  });

  it("polls every 5s while pending/running and stops once done", async () => {
    const mock = agentRunsApi.listAgentRuns as ReturnType<typeof vi.fn>;
    mock
      .mockResolvedValueOnce({
        items: [makeRun({ status: "pending" })],
        total: 1,
      })
      .mockResolvedValueOnce({
        items: [makeRun({ status: "running", started_at: "2026-06-02T00:00:30Z" })],
        total: 1,
      })
      .mockResolvedValue({
        items: [
          makeRun({
            status: "done",
            comment_id: "comment-9",
            finished_at: "2026-06-02T00:01:00Z",
          }),
        ],
        total: 1,
      });

    render(<AgentRunBanner ticketId="ticket-uuid" />);
    await flush();
    expect(mock).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("agent-run-banner")).toHaveTextContent(/queued/i);

    // +5s → second poll → running
    await act(async () => {
      vi.advanceTimersByTime(5000);
    });
    await flush();
    expect(mock).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("agent-run-banner")).toHaveTextContent(/working/);

    // +5s → third poll → done; polling must stop after this.
    await act(async () => {
      vi.advanceTimersByTime(5000);
    });
    await flush();
    expect(mock).toHaveBeenCalledTimes(3);
    expect(screen.getByTestId("agent-run-banner")).toHaveTextContent(/responded/i);

    // No further polls once terminal.
    await act(async () => {
      vi.advanceTimersByTime(15000);
    });
    await flush();
    expect(mock).toHaveBeenCalledTimes(3);
  });

  it("clears the pending poll timer on unmount", async () => {
    const mock = agentRunsApi.listAgentRuns as ReturnType<typeof vi.fn>;
    mock.mockResolvedValue({
      items: [makeRun({ status: "pending" })],
      total: 1,
    });

    const { unmount } = render(<AgentRunBanner ticketId="ticket-uuid" />);
    await flush();
    expect(mock).toHaveBeenCalledTimes(1);

    unmount();
    await act(async () => {
      vi.advanceTimersByTime(20000);
    });
    expect(mock).toHaveBeenCalledTimes(1);
  });
});
