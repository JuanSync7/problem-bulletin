/**
 * TicketCard unit tests — WP5.
 *
 * Covers per-type badge rendering, agent activity badge visibility, and the
 * epic / sprint chips. Drag-and-drop wiring is exercised indirectly by the
 * KanbanBoard integration test.
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { DndContext } from "@dnd-kit/core";
import { TicketCard } from "../TicketCard";
import { ALL_TICKET_TYPES } from "../../CreateTicket/fieldsByType";
import type { TicketDTO } from "../../../api/tickets";

function makeTicket(over: Partial<TicketDTO> = {}): TicketDTO {
  return {
    id: "00000000-0000-0000-0000-000000000001",
    display_id: "DEF-1",
    title: "Sample ticket",
    status: "todo",
    version: 1,
    type: "task",
    priority: "medium",
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

describe("TicketCard", () => {
  it.each(ALL_TICKET_TYPES)("renders the type badge for %s", (type) => {
    renderCard(makeTicket({ type }));
    expect(screen.getByTestId("ticket-type-badge")).toBeInTheDocument();
  });

  it("shows the agent activity badge when last_actor_type is agent", () => {
    renderCard(makeTicket({ last_actor_type: "agent" }));
    expect(screen.getByTestId("ticket-agent-badge")).toBeInTheDocument();
  });

  it("hides the agent activity badge when last_actor_type is user", () => {
    renderCard(makeTicket({ last_actor_type: "user" }));
    expect(screen.queryByTestId("ticket-agent-badge")).not.toBeInTheDocument();
  });

  it("hides the badge when last_actor_type=user even if reporter_type=agent (no fallback)", () => {
    // v2.1 WP6: badge reads last_actor_type exclusively — `reporter_type`
    // is NOT consulted as a fallback anymore.
    renderCard(
      makeTicket({ last_actor_type: "user", reporter_type: "agent" }),
    );
    expect(screen.queryByTestId("ticket-agent-badge")).not.toBeInTheDocument();
  });

  it("hides the badge when last_actor_type is missing (no reporter_type fallback)", () => {
    renderCard(makeTicket({ reporter_type: "agent" }));
    expect(screen.queryByTestId("ticket-agent-badge")).not.toBeInTheDocument();
  });

  it("renders the epic chip when epic_id is set", () => {
    const epicId = "00000000-0000-0000-0000-0000000000aa";
    const epic = makeTicket({
      id: epicId,
      display_id: "DEF-10",
      type: "epic",
      title: "An epic",
    });
    renderCard(makeTicket({ epic_id: epicId }), {
      epicLookup: { [epicId]: epic },
    });
    expect(screen.getByTestId("ticket-epic-chip")).toHaveTextContent("DEF-10");
  });

  it("renders the sprint chip when sprint_id matches the active lookup", () => {
    renderCard(makeTicket({ sprint_id: "sp-1" }), {
      activeSprintLookup: { "sp-1": "Sprint 12" },
    });
    expect(screen.getByTestId("ticket-sprint-chip")).toHaveTextContent("Sprint 12");
  });

  it("renders the story-points chip when story_points is non-null", () => {
    renderCard(makeTicket({ story_points: 5 }));
    expect(screen.getByTestId("ticket-story-points")).toHaveTextContent("5");
  });

  it("hides the story-points chip when null", () => {
    renderCard(makeTicket({ story_points: null }));
    expect(screen.queryByTestId("ticket-story-points")).not.toBeInTheDocument();
  });

  // v2.7-WP48: assignee avatar variant is driven by `assignee_type` (DTO
  // truth) and NOT `last_actor_type`.
  it("WP48: renders an agent-styled avatar when assignee_type=agent", () => {
    renderCard(
      makeTicket({ assignee_id: "agent-bot-1", assignee_type: "agent" }),
    );
    const avatar = screen.getByTestId("ticket-avatar-agent");
    expect(avatar).toBeInTheDocument();
    expect(avatar.getAttribute("aria-label") ?? "").toMatch(/agent/i);
  });

  it("WP48: renders a human-styled avatar when assignee_type=user", () => {
    renderCard(
      makeTicket({ assignee_id: "user-jane", assignee_type: "user" }),
    );
    expect(screen.getByTestId("ticket-avatar-user")).toBeInTheDocument();
    expect(screen.queryByTestId("ticket-avatar-agent")).not.toBeInTheDocument();
  });

  it("WP48: renders no avatar variant when assignee_id is null", () => {
    renderCard(makeTicket({ assignee_id: null, assignee_type: null }));
    expect(screen.queryByTestId("ticket-avatar-user")).not.toBeInTheDocument();
    expect(screen.queryByTestId("ticket-avatar-agent")).not.toBeInTheDocument();
  });

  it("renders the v2 display_id verbatim (not legacy TKT-)", () => {
    renderCard(makeTicket({ display_id: "WP5-42" }));
    expect(screen.getByText("WP5-42")).toBeInTheDocument();
  });
});
