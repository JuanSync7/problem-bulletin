/**
 * V3a — MeSpace.test.tsx
 *
 * Mounts <MeSpacePage> with a mocked ``getMyInbox`` that returns a
 * fully-seeded inbox. Asserts:
 *   (a) all four tab labels render with their counts;
 *   (b) clicking each tab swaps the visible panel to the matching list.
 */
import "@testing-library/jest-dom";
import {
  render,
  screen,
  waitFor,
  fireEvent,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../api/me", () => ({
  getMyInbox: vi.fn(),
}));

import { getMyInbox } from "../../../api/me";
import MeSpacePage from "../index";

const MOCK_INBOX = {
  counts: {
    assigned_tickets: 2,
    assigned_problems: 0,
    mentions: 1,
    my_agent_runs: 1,
  },
  assigned_tickets: {
    items: [
      {
        id: "11111111-1111-1111-1111-111111111111",
        display_id: "DEMO-1",
        title: "first",
        status: "todo",
        priority: "medium",
        project_id: "00000000-0000-0000-0000-000000000001",
        last_activity_at: null,
        created_at: "2026-06-01T00:00:00Z",
      },
      {
        id: "22222222-2222-2222-2222-222222222222",
        display_id: "DEMO-2",
        title: "second",
        status: "in_progress",
        priority: "high",
        project_id: "00000000-0000-0000-0000-000000000001",
        last_activity_at: null,
        created_at: "2026-06-01T00:00:00Z",
      },
    ],
    next_cursor: null,
    total: 2,
  },
  assigned_problems: {
    items: [],
    next_cursor: null,
    total: 0,
  },
  mentions: {
    items: [
      {
        id: "33333333-3333-3333-3333-333333333333",
        kind: "ticket_mention",
        target_type: "ticket" as const,
        target_id: "11111111-1111-1111-1111-111111111111",
        target_display_id: "DEMO-1",
        excerpt: "hello @me",
        is_read: false,
        created_at: "2026-06-01T00:00:00Z",
      },
    ],
    next_cursor: null,
    total: 1,
  },
  my_agent_runs: {
    items: [
      {
        id: "44444444-4444-4444-4444-444444444444",
        agent_id: "55555555-5555-5555-5555-555555555555",
        ticket_id: "11111111-1111-1111-1111-111111111111",
        status: "done",
        enqueued_at: "2026-06-01T00:00:00Z",
        started_at: "2026-06-01T00:00:00Z",
        finished_at: "2026-06-01T00:00:00Z",
      },
    ],
    next_cursor: null,
    total: 1,
  },
};

function renderPage() {
  return render(
    <MemoryRouter
      initialEntries={["/me"]}
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <MeSpacePage />
    </MemoryRouter>,
  );
}

describe("MeSpacePage", () => {
  beforeEach(() => {
    vi.mocked(getMyInbox).mockResolvedValue(MOCK_INBOX);
  });

  it("renders all four tab labels with their counts", async () => {
    renderPage();

    await waitFor(() =>
      expect(screen.getByTestId("count-assigned_tickets")).toHaveTextContent(
        "2",
      ),
    );

    expect(
      screen.getByRole("tab", { name: /Assigned tickets/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("tab", { name: /Assigned problems/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Mentions/i })).toBeInTheDocument();
    expect(
      screen.getByRole("tab", { name: /My agent runs/i }),
    ).toBeInTheDocument();

    expect(
      screen.getByTestId("count-assigned_problems"),
    ).toHaveTextContent("0");
    expect(screen.getByTestId("count-mentions")).toHaveTextContent("1");
    expect(screen.getByTestId("count-my_agent_runs")).toHaveTextContent("1");
  });

  it("clicking each tab swaps the rendered list", async () => {
    renderPage();

    // Default tab — assigned_tickets — should be visible after fetch settles.
    await waitFor(() =>
      expect(screen.getByTestId("list-assigned_tickets")).toBeInTheDocument(),
    );

    // Mentions.
    fireEvent.click(screen.getByRole("tab", { name: /Mentions/i }));
    expect(screen.getByTestId("list-mentions")).toBeInTheDocument();
    expect(screen.queryByTestId("list-assigned_tickets")).toBeNull();

    // My agent runs.
    fireEvent.click(screen.getByRole("tab", { name: /My agent runs/i }));
    expect(screen.getByTestId("list-my_agent_runs")).toBeInTheDocument();
    expect(screen.queryByTestId("list-mentions")).toBeNull();

    // Assigned problems — empty state.
    fireEvent.click(
      screen.getByRole("tab", { name: /Assigned problems/i }),
    );
    expect(
      screen.getByText("No problems assigned to you."),
    ).toBeInTheDocument();
  });
});
