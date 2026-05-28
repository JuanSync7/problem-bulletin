import React from "react";
import { useDraggable } from "@dnd-kit/core";
import type { TicketDTO } from "../../api/tickets";
import {
  TICKET_TYPE_BADGE,
  TICKET_TYPE_LABEL,
  type TicketTypeV2,
} from "../CreateTicket/fieldsByType";

interface TicketCardProps {
  ticket: TicketDTO;
  onClick?: (idOrKey: string) => void;
  /** When provided, the card links to this epic via a clickable chip. */
  epicLookup?: Record<string, TicketDTO>;
  /** When provided, displays the active sprint name on the card. */
  activeSprintLookup?: Record<string, string>;
  onEpicClick?: (epicId: string) => void;
}

function initials(s?: string | null): string {
  if (!s) return "?";
  const trimmed = s.trim();
  if (!trimmed) return "?";
  const parts = trimmed.split(/[\s\-_]+/).filter(Boolean);
  if (parts.length === 0) return trimmed.slice(0, 2).toUpperCase();
  if (parts.length === 1) return parts[0]!.slice(0, 2).toUpperCase();
  return (parts[0]![0]! + parts[1]![0]!).toUpperCase();
}

export function TicketCard({
  ticket,
  onClick,
  epicLookup = {},
  activeSprintLookup = {},
  onEpicClick,
}: TicketCardProps) {
  const dragId = ticket.display_id || ticket.id;
  const { attributes, listeners, setNodeRef, isDragging, transform } =
    useDraggable({ id: dragId, data: { ticket } });

  const style: React.CSSProperties = transform
    ? {
        transform: `translate3d(${transform.x}px, ${transform.y}px, 0)`,
      }
    : {};

  const priority = ticket.priority ?? "medium";
  // v2.7-WP48: assignee avatar variant is driven by `assignee_type` (the DTO
  // source of truth narrowed in v2.6-WP45). It must NOT consult
  // `last_actor_type` — that heuristic miscategorises tickets where an agent
  // assigns to a human (and vice versa).
  const assigneeId = (ticket.assignee_id as string | undefined) ?? null;
  const assigneeLabel = assigneeId;
  const isAgentAssignee =
    assigneeId != null && ticket.assignee_type === "agent";

  const type = (ticket.type ?? "task") as TicketTypeV2;
  const typeBadge = TICKET_TYPE_BADGE[type] ?? TICKET_TYPE_BADGE.task;
  const typeLabel = TICKET_TYPE_LABEL[type] ?? type;

  // Agent activity badge: v2.1 WP6 added the first-class `last_actor_type`
  // aggregate on tickets. The badge reads it exclusively — no fallback to
  // `reporter_type` (that only caught agent-created tickets, not subsequent
  // agent activity).
  const isAgent = ticket.last_actor_type === "agent";

  const epicId = (ticket.epic_id as string | null | undefined) ?? null;
  const epic = epicId ? epicLookup[epicId] : null;

  const sprintId = (ticket.sprint_id as string | null | undefined) ?? null;
  const sprintLabel = sprintId ? activeSprintLookup[sprintId] : null;

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`ticket-card${isDragging ? " ticket-card--dragging" : ""}`}
      {...listeners}
      {...attributes}
      onClick={(e) => {
        // dnd-kit listeners swallow pointer-down; click still fires unless we drag.
        if (isDragging) return;
        e.stopPropagation();
        onClick?.(dragId);
      }}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClick?.(dragId);
        }
      }}
      data-ticket-id={ticket.id}
    >
      <div className="ticket-card__top">
        <span
          className="ticket-card__type-badge"
          style={{ background: typeBadge.color }}
          title={typeLabel}
          aria-label={`Type: ${typeLabel}`}
          data-testid="ticket-type-badge"
        >
          {typeBadge.letter}
        </span>
        <span className="ticket-card__key">
          {ticket.display_id ?? ticket.id.slice(0, 8)}
        </span>
        <span style={{ flex: 1 }} />
        {isAgent && (
          <span
            className="ticket-card__agent-badge"
            title="Last write by an agent"
            aria-label="Agent activity"
            data-testid="ticket-agent-badge"
          >
            🤖
          </span>
        )}
        {ticket.story_points != null && (
          <span className="ticket-card__points" data-testid="ticket-story-points">
            {ticket.story_points}
          </span>
        )}
      </div>
      <div className="ticket-card__title">{ticket.title}</div>
      <div className="ticket-card__chips">
        {epicId && (
          <button
            type="button"
            className="ticket-card__chip ticket-card__chip--epic"
            data-testid="ticket-epic-chip"
            onClick={(e) => {
              e.stopPropagation();
              onEpicClick?.(epicId);
            }}
            title={epic ? `Epic: ${epic.title}` : "Epic"}
          >
            {epic?.display_id ?? "EPIC"}
          </button>
        )}
        {sprintLabel && (
          <span
            className="ticket-card__chip ticket-card__chip--sprint"
            data-testid="ticket-sprint-chip"
            title={`Sprint: ${sprintLabel}`}
          >
            {sprintLabel}
          </span>
        )}
      </div>
      <div className="ticket-card__bottom">
        <span className={`priority-badge priority-badge--${priority}`}>
          {priority}
        </span>
        {assigneeLabel && (
          <span
            className={
              isAgentAssignee
                ? "ticket-card__avatar ticket-card__avatar--agent"
                : "ticket-card__avatar"
            }
            title={assigneeLabel}
            aria-label={
              isAgentAssignee
                ? `Agent: ${assigneeLabel}`
                : `Assignee ${assigneeLabel}`
            }
            data-testid={
              isAgentAssignee ? "ticket-avatar-agent" : "ticket-avatar-user"
            }
          >
            {initials(assigneeLabel)}
          </span>
        )}
      </div>
    </div>
  );
}
