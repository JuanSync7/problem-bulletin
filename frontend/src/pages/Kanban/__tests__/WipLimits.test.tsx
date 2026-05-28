/**
 * v2.1-WP11 — WIP-limit chip display on Kanban columns.
 *
 * Verifies that ``KanbanColumn`` honours the backend ``column_counts``
 * aggregate and per-status ``wip_limits`` to render the right chip /
 * border state:
 *   - Under limit: ``<count> / <limit>`` neutral chip.
 *   - At limit: amber chip class.
 *   - Over limit: red chip + red border on the column.
 *   - No limit: bare ``<count>`` (no slash).
 *   - Falls back to ``tickets.length`` when ``count`` is omitted.
 */
import "@testing-library/jest-dom";
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { DndContext } from "@dnd-kit/core";
import { KanbanColumn } from "../KanbanColumn";

// ``TicketCard`` pulls in image/api dependencies that we don't care about
// for these unit-level chip tests. Stub it to a marker.
vi.mock("../TicketCard", () => ({
  TicketCard: ({ ticket }: any) => (
    <div data-testid="card">{ticket.title}</div>
  ),
}));

function renderColumn(props: Parameters<typeof KanbanColumn>[0]) {
  return render(
    <DndContext>
      <KanbanColumn {...props} />
    </DndContext>,
  );
}

describe("KanbanColumn WIP limits", () => {
  it("renders '<count> / <limit>' under-limit (neutral)", () => {
    renderColumn({
      status: "todo",
      title: "To Do",
      tickets: [],
      count: 3,
      wipLimit: 5,
    });
    expect(screen.getByText("3 / 5")).toBeInTheDocument();
    const chip = screen.getByText("3 / 5");
    expect(chip.className).not.toMatch(/--over/);
    expect(chip.className).not.toMatch(/--at/);
  });

  it("amber chip class when count === limit", () => {
    renderColumn({
      status: "todo",
      title: "To Do",
      tickets: [],
      count: 5,
      wipLimit: 5,
    });
    const chip = screen.getByText("5 / 5");
    expect(chip.className).toMatch(/kanban-column__count--at/);
  });

  it("red chip + red border when count > limit", () => {
    const { container } = renderColumn({
      status: "todo",
      title: "To Do",
      tickets: [],
      count: 6,
      wipLimit: 5,
    });
    const chip = screen.getByText("6 / 5");
    expect(chip.className).toMatch(/kanban-column__count--over/);
    const col = container.querySelector(".kanban-column");
    expect(col?.className).toMatch(/kanban-column--over-limit/);
    expect(col?.getAttribute("data-over-limit")).toBe("true");
  });

  it("renders bare count when no limit is set", () => {
    renderColumn({
      status: "todo",
      title: "To Do",
      tickets: [],
      count: 3,
    });
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.queryByText("3 / 0")).not.toBeInTheDocument();
  });

  it("falls back to tickets.length when count is omitted", () => {
    renderColumn({
      status: "todo",
      title: "To Do",
      tickets: [
        { id: "t1", title: "a" } as any,
        { id: "t2", title: "b" } as any,
      ],
      wipLimit: 5,
    });
    // Two cards rendered; chip shows local length / limit.
    expect(screen.getByText("2 / 5")).toBeInTheDocument();
  });
});
