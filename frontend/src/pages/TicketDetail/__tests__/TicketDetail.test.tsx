/**
 * TicketDetail page — v2.3-WP21 + v2.4-WP27
 *
 * Covers:
 *  1. Renders title and status badge when the API returns a ticket.
 *  2. Renders "Ticket not found" message when the API returns 404.
 *  3. Renders an error message when the API returns a 500.
 *  4. (WP27) Changing status calls transitionTicket with the new value.
 *  5. (WP27) Changing priority calls updateTicket with the new value.
 *  6. (WP27) Saving assignee calls assignTicket with the new value.
 *  7. (WP27) After a successful mutation, TicketActivityFeed re-fetches
 *     (asserted by listActivity being called again).
 *  8. (WP27) On mutation failure the error message renders.
 *
 * API module is mocked the same way Activity.test.tsx mocks its API modules.
 */
import "@testing-library/jest-dom";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi, beforeEach } from "vitest";

import { ApiError } from "../../../api/tickets";

// PersonPicker fires searchPeople — stub to avoid jsdom fetch errors.
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
    // TicketActivityFeed (added in WP26) also calls listActivity; stub it so
    // jsdom doesn't attempt a real fetch in unit tests.
    listActivity: vi.fn().mockResolvedValue({ items: [], next_cursor: null, total: 0 }),
  };
});

import * as ticketsApi from "../../../api/tickets";
import * as peopleApi from "../../../api/people";
import TicketDetail from "../index";

function renderDetail(displayId = "WEB-42") {
  return render(
    <MemoryRouter initialEntries={[`/tickets/${displayId}`]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <Routes>
        <Route path="/tickets/:displayId" element={<TicketDetail />} />
      </Routes>
    </MemoryRouter>,
  );
}

function makeTicket(overrides: Partial<import("../../../api/tickets").TicketDTO> = {}): import("../../../api/tickets").TicketDTO {
  return {
    id: "uuid-1",
    display_id: "WEB-42",
    title: "Fix login redirect loop",
    status: "in_progress",
    priority: "high",
    type: "bug",
    description: "Users get stuck in a redirect loop on logout.",
    project_key: "WEB",
    project_id: "proj-1",
    version: 3,
    ...overrides,
  };
}

describe("TicketDetail", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Reset listActivity to the default stub after clearAllMocks wipes it.
    (ticketsApi.listActivity as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [],
      next_cursor: null,
      total: 0,
    });
  });

  it("renders title and status badge when API returns a ticket", async () => {
    (ticketsApi.getTicket as ReturnType<typeof vi.fn>).mockResolvedValue(makeTicket());
    renderDetail();

    await waitFor(() => {
      expect(screen.getByTestId("ticket-title")).toBeInTheDocument();
    });

    expect(screen.getByTestId("ticket-title")).toHaveTextContent("Fix login redirect loop");
    expect(screen.getByTestId("ticket-status")).toHaveTextContent(/in progress/i);
    expect(screen.getByTestId("ticket-priority")).toHaveTextContent(/high/i);
    // project rendered by TicketFields (WP26) — testid moved to tf-project
    expect(screen.getByTestId("tf-project")).toHaveTextContent("WEB");
  });

  it("renders description as markdown", async () => {
    (ticketsApi.getTicket as ReturnType<typeof vi.fn>).mockResolvedValue(
      makeTicket({ description: "**Bold** text" }),
    );
    renderDetail();

    await waitFor(() => {
      expect(screen.getByTestId("ticket-description")).toBeInTheDocument();
    });

    // renderMarkdown wraps bold in <strong>
    const desc = screen.getByTestId("ticket-description");
    expect(desc.innerHTML).toContain("<strong>Bold</strong>");
  });

  it("renders Ticket not found on 404", async () => {
    (ticketsApi.getTicket as ReturnType<typeof vi.fn>).mockRejectedValue(
      new ApiError(404, { code: "not_found", message: "ticket not found" }),
    );
    renderDetail("GHOST-99");

    await waitFor(() => {
      expect(screen.getByTestId("ticket-detail-not-found")).toBeInTheDocument();
    });

    expect(screen.getByText(/ticket not found/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /back to board/i })).toBeInTheDocument();
  });

  it("renders error message on 500", async () => {
    (ticketsApi.getTicket as ReturnType<typeof vi.fn>).mockRejectedValue(
      new ApiError(500, { code: "internal", message: "internal server error" }),
    );
    renderDetail();

    await waitFor(() => {
      expect(screen.getByTestId("ticket-detail-error")).toBeInTheDocument();
    });

    expect(screen.getByRole("alert")).toHaveTextContent(/internal server error/i);
    expect(screen.getByRole("link", { name: /back to board/i })).toBeInTheDocument();
  });

  it("renders loading spinner initially", () => {
    // Never resolves so we can observe the loading state.
    (ticketsApi.getTicket as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}));
    renderDetail();
    expect(screen.getByTestId("ticket-detail-loading")).toBeInTheDocument();
  });

  // ---------------------------------------------------------------------------
  // WP27 — inline edit controls
  // ---------------------------------------------------------------------------

  it("WP27: changing status calls transitionTicket with the new value", async () => {
    const ticket = makeTicket();
    const updated = { ...ticket, status: "done" as const, version: 4 };
    (ticketsApi.getTicket as ReturnType<typeof vi.fn>).mockResolvedValue(ticket);
    (ticketsApi.transitionTicket as ReturnType<typeof vi.fn>).mockResolvedValue(updated);

    renderDetail();
    await waitFor(() => expect(screen.getByTestId("td-status-select")).toBeInTheDocument());

    fireEvent.change(screen.getByTestId("td-status-select"), { target: { value: "done" } });

    await waitFor(() => {
      expect(ticketsApi.transitionTicket).toHaveBeenCalledWith("WEB-42", "done");
    });
  });

  it("WP27: changing priority calls updateTicket with the new value", async () => {
    const ticket = makeTicket();
    const updated = { ...ticket, priority: "low" as const, version: 4 };
    (ticketsApi.getTicket as ReturnType<typeof vi.fn>).mockResolvedValue(ticket);
    (ticketsApi.updateTicket as ReturnType<typeof vi.fn>).mockResolvedValue(updated);

    renderDetail();
    await waitFor(() => expect(screen.getByTestId("td-priority-select")).toBeInTheDocument());

    fireEvent.change(screen.getByTestId("td-priority-select"), { target: { value: "low" } });

    await waitFor(() => {
      expect(ticketsApi.updateTicket).toHaveBeenCalledWith(
        "WEB-42",
        expect.objectContaining({ priority: "low", version: ticket.version }),
      );
    });
  });

  it("WP27/WP32: selecting a person via PersonPicker calls assignTicket", async () => {
    const user = userEvent.setup();
    const ticket = makeTicket({ assignee_id: null });
    const updated = { ...ticket, assignee_id: "11111111-1111-1111-1111-111111111111", version: 4 };
    (ticketsApi.getTicket as ReturnType<typeof vi.fn>).mockResolvedValue(ticket);
    (ticketsApi.assignTicket as ReturnType<typeof vi.fn>).mockResolvedValue(updated);
    (peopleApi.searchPeople as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        {
          kind: "user",
          id: "11111111-1111-1111-1111-111111111111",
          display_name: "Alice",
          handle: "alice",
        },
      ],
    });

    renderDetail();
    await waitFor(() =>
      expect(screen.getByTestId("person-picker-input")).toBeInTheDocument(),
    );

    // Type into the picker to fire a search.
    await user.type(screen.getByTestId("person-picker-input"), "ali");

    // Wait for the result to appear.
    await waitFor(() => expect(screen.getByText("Alice")).toBeInTheDocument());

    // Click the result.
    await user.click(screen.getByText("Alice"));

    await waitFor(() => {
      expect(ticketsApi.assignTicket).toHaveBeenCalledWith(
        "WEB-42",
        expect.objectContaining({
          assignee_id: "11111111-1111-1111-1111-111111111111",
          assignee_type: "user",
        }),
      );
    });
  });

  it("WP27: after a successful mutation, activity feed re-fetches (listActivity called again)", async () => {
    const ticket = makeTicket();
    const updated = { ...ticket, status: "done" as const, version: 4 };
    (ticketsApi.getTicket as ReturnType<typeof vi.fn>).mockResolvedValue(ticket);
    (ticketsApi.transitionTicket as ReturnType<typeof vi.fn>).mockResolvedValue(updated);

    renderDetail();
    await waitFor(() => expect(screen.getByTestId("td-status-select")).toBeInTheDocument());

    // Record the call count before the mutation.
    const callsBefore = (ticketsApi.listActivity as ReturnType<typeof vi.fn>).mock.calls.length;

    fireEvent.change(screen.getByTestId("td-status-select"), { target: { value: "done" } });

    await waitFor(() => {
      const callsAfter = (ticketsApi.listActivity as ReturnType<typeof vi.fn>).mock.calls.length;
      expect(callsAfter).toBeGreaterThan(callsBefore);
    });
  });

  // ---------------------------------------------------------------------------
  // WP49 — inline assignee distinguishes human vs agent
  // ---------------------------------------------------------------------------

  it("WP49: assignee_type='agent' renders an inline agent badge", async () => {
    (ticketsApi.getTicket as ReturnType<typeof vi.fn>).mockResolvedValue(
      makeTicket({
        assignee_id: "22222222-2222-2222-2222-222222222222",
        assignee_type: "agent",
      }),
    );
    renderDetail();

    await waitFor(() => expect(screen.getByTestId("tf-assignee")).toBeInTheDocument());

    const cell = screen.getByTestId("tf-assignee");
    const badge = cell.querySelector(".ticket-detail__assignee-badge--agent");
    expect(badge).not.toBeNull();
    expect(badge).toHaveTextContent(/^agent$/);
    expect(badge).toHaveAttribute("aria-label", "agent");
  });

  it("WP49: assignee_type='user' renders no agent badge", async () => {
    (ticketsApi.getTicket as ReturnType<typeof vi.fn>).mockResolvedValue(
      makeTicket({
        assignee_id: "11111111-1111-1111-1111-111111111111",
        assignee_type: "user",
      }),
    );
    renderDetail();

    await waitFor(() => expect(screen.getByTestId("tf-assignee")).toBeInTheDocument());

    const cell = screen.getByTestId("tf-assignee");
    expect(cell.querySelector(".ticket-detail__assignee-badge--agent")).toBeNull();
  });

  it("WP49: assignee_id=null renders 'Unassigned' and no agent badge", async () => {
    (ticketsApi.getTicket as ReturnType<typeof vi.fn>).mockResolvedValue(
      makeTicket({ assignee_id: null, assignee_type: null }),
    );
    renderDetail();

    await waitFor(() => expect(screen.getByTestId("tf-assignee")).toBeInTheDocument());

    const cell = screen.getByTestId("tf-assignee");
    expect(cell).toHaveTextContent(/unassigned/i);
    expect(cell.querySelector(".ticket-detail__assignee-badge--agent")).toBeNull();
  });

  it("WP27: on mutation failure, an error message renders", async () => {
    const ticket = makeTicket();
    (ticketsApi.getTicket as ReturnType<typeof vi.fn>).mockResolvedValue(ticket);
    (ticketsApi.transitionTicket as ReturnType<typeof vi.fn>).mockRejectedValue(
      new ApiError(409, { code: "conflict", message: "version conflict" }),
    );

    renderDetail();
    await waitFor(() => expect(screen.getByTestId("td-status-select")).toBeInTheDocument());

    fireEvent.change(screen.getByTestId("td-status-select"), { target: { value: "done" } });

    await waitFor(() => {
      expect(screen.getByTestId("ticket-mutate-error")).toBeInTheDocument();
    });
    expect(screen.getByTestId("ticket-mutate-error")).toHaveTextContent(/version conflict/i);
  });
});
