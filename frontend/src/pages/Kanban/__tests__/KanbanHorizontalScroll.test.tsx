/**
 * WP12 — Kanban horizontal scroll layout tests.
 *
 * Verifies that the board renders all column titles inside a single
 * `.kanban-board` container so there is exactly one horizontal scroll
 * ancestor per swimlane row.
 *
 * Specifically:
 *   - All 5 base column titles appear inside one `.kanban-board` div.
 *   - All 7 column titles (base + terminal) appear when showTerminal=true.
 *   - In swimlane mode each swimlane gets its own `.kanban-board` row (not
 *     a shared one), meaning the columns-row is self-contained per lane.
 *   - The `.kanban-board` container renders its direct column children with
 *     the `.kanban-column` class (fixed-width flex children).
 */
import { describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen, within } from "@testing-library/react";
import { DndContext } from "@dnd-kit/core";
import { KanbanBoard } from "../KanbanBoard";
import type { TicketDTO } from "../../../api/tickets";

// Stub transitionTicket — not needed for layout tests.
vi.mock("../../../api/tickets", async () => {
  const actual = await vi.importActual<typeof import("../../../api/tickets")>(
    "../../../api/tickets",
  );
  return { ...actual, transitionTicket: vi.fn() };
});

// Stub TicketCard to a lightweight marker.
vi.mock("../TicketCard", () => ({
  TicketCard: ({ ticket }: any) => (
    <div data-testid="card">{ticket.title}</div>
  ),
}));

const BASE_COLUMN_TITLES = ["Backlog", "To Do", "In Progress", "In Review", "Done"];
const TERMINAL_COLUMN_TITLES = ["Blocked", "Cancelled"];
const ALL_COLUMN_TITLES = [...BASE_COLUMN_TITLES, ...TERMINAL_COLUMN_TITLES];

const SAMPLE_TICKETS: TicketDTO[] = [
  {
    id: "t-1",
    display_id: "TST-1",
    title: "Alpha",
    status: "backlog",
    type: "story",
    priority: "medium",
    version: 1,
    project_id: "p-1",
    sprint_id: "sp-1",
    epic_id: "e-1",
  } as TicketDTO,
  {
    id: "t-2",
    display_id: "TST-2",
    title: "Beta",
    status: "in_progress",
    type: "task",
    priority: "high",
    version: 1,
    project_id: "p-1",
    sprint_id: null,
    epic_id: null,
  } as TicketDTO,
];

function renderBoard(props: Partial<React.ComponentProps<typeof KanbanBoard>> = {}) {
  return render(
    <DndContext>
      <KanbanBoard
        tickets={SAMPLE_TICKETS}
        onTicketsChange={vi.fn()}
        onCardClick={vi.fn()}
        {...props}
      />
    </DndContext>,
  );
}

describe("WP12 — Kanban horizontal scroll layout", () => {
  it("renders all 5 base column titles inside exactly one .kanban-board row (no swimlane)", () => {
    const { container } = renderBoard({ swimlane: "none" });
    const boards = container.querySelectorAll(".kanban-board");
    // swimlane=none → one synthetic __all__ group → one .kanban-board row
    expect(boards).toHaveLength(1);
    const [board] = boards;
    for (const title of BASE_COLUMN_TITLES) {
      expect(within(board as HTMLElement).getByText(title)).toBeInTheDocument();
    }
  });

  it("renders all 7 column titles when showTerminal=true", () => {
    const { container } = renderBoard({ swimlane: "none", showTerminal: true });
    const boards = container.querySelectorAll(".kanban-board");
    expect(boards).toHaveLength(1);
    const [board] = boards;
    for (const title of ALL_COLUMN_TITLES) {
      expect(within(board as HTMLElement).getByText(title)).toBeInTheDocument();
    }
  });

  it("each swimlane group gets its own .kanban-board row (no per-swimlane scroll drift)", () => {
    // Two tickets in different sprints → two swimlane groups → two .kanban-board rows.
    const { container } = renderBoard({
      swimlane: "sprint",
      sprintLookup: { "sp-1": "Sprint 1" },
    });
    const boards = container.querySelectorAll(".kanban-board");
    // t-1 is in sp-1, t-2 has no sprint → 2 groups
    expect(boards).toHaveLength(2);
    // Every board row contains all base column titles.
    for (const board of boards) {
      for (const title of BASE_COLUMN_TITLES) {
        expect(
          within(board as HTMLElement).getByText(title),
        ).toBeInTheDocument();
      }
    }
  });

  it("every .kanban-board child column has the .kanban-column class (fixed-width flex children)", () => {
    const { container } = renderBoard({ swimlane: "none" });
    const board = container.querySelector(".kanban-board")!;
    // Direct children of the flex row must be .kanban-column elements.
    const columns = board.querySelectorAll(":scope > .kanban-column");
    expect(columns).toHaveLength(BASE_COLUMN_TITLES.length);
  });
});
