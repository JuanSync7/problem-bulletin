/**
 * v2.29 S5 — TicketCard run-status chip.
 *
 * The chip renders only for agent-assigned tickets and only when the board
 * supplies an `agentRunStatus` (the board fetches runs once per refresh for
 * visible agent-assigned tickets — the card itself makes NO api calls).
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { DndContext } from "@dnd-kit/core";
import { TicketCard } from "../TicketCard";
import type { TicketDTO } from "../../../api/tickets";

function makeTicket(over: Partial<TicketDTO> = {}): TicketDTO {
  return {
    id: "00000000-0000-0000-0000-000000000001",
    display_id: "DEF-1",
    title: "Sample ticket",
    status: "in_progress",
    version: 1,
    type: "task",
    priority: "medium",
    assignee_id: "agent-bot-1",
    assignee_type: "agent",
    ...over,
  } as TicketDTO;
}

function renderCard(t: TicketDTO, extra: Record<string, unknown> = {}) {
  return render(
    <DndContext>
      <TicketCard ticket={t} {...extra} />
    </DndContext>,
  );
}

describe("TicketCard run-status chip (v2.29)", () => {
  it("renders a muted 'queued' chip for pending", () => {
    renderCard(makeTicket(), { agentRunStatus: "pending" });
    const chip = screen.getByTestId("ticket-run-chip");
    expect(chip).toHaveTextContent("queued");
    expect(chip.className).toContain("kanban-card__run-chip--pending");
  });

  it("renders an animated 'working…' chip for running", () => {
    renderCard(makeTicket(), { agentRunStatus: "running" });
    const chip = screen.getByTestId("ticket-run-chip");
    expect(chip).toHaveTextContent(/working/);
    expect(chip.className).toContain("kanban-card__run-chip--running");
  });

  it("renders a success 'done' chip for done", () => {
    renderCard(makeTicket(), { agentRunStatus: "done" });
    const chip = screen.getByTestId("ticket-run-chip");
    expect(chip).toHaveTextContent("done");
    expect(chip.className).toContain("kanban-card__run-chip--done");
  });

  it("renders an error 'failed' chip for error", () => {
    renderCard(makeTicket(), { agentRunStatus: "error" });
    const chip = screen.getByTestId("ticket-run-chip");
    expect(chip).toHaveTextContent("failed");
    expect(chip.className).toContain("kanban-card__run-chip--error");
  });

  it("renders no chip when agentRunStatus is absent", () => {
    renderCard(makeTicket());
    expect(screen.queryByTestId("ticket-run-chip")).not.toBeInTheDocument();
  });

  it("renders no chip for a human-assigned ticket even with a status", () => {
    renderCard(
      makeTicket({ assignee_id: "user-jane", assignee_type: "user" }),
      { agentRunStatus: "done" },
    );
    expect(screen.queryByTestId("ticket-run-chip")).not.toBeInTheDocument();
  });
});
