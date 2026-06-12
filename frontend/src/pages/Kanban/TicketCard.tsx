import React, { useEffect, useState } from "react";
import { useDraggable } from "@dnd-kit/core";
import type { TicketDTO } from "../../api/tickets";
import { assignTicket } from "../../api/tickets";
import { PersonPicker } from "../../components/PersonPicker/index";
import type { PersonRef } from "../../api/people";
import {
  TICKET_TYPE_BADGE,
  TICKET_TYPE_LABEL,
  type TicketTypeV2,
} from "../CreateTicket/fieldsByType";

/** v2.29 S5 — agent-run lifecycle status, supplied by the board. */
export type AgentRunChipStatus = "pending" | "running" | "done" | "error";

const RUN_CHIP_LABEL: Record<AgentRunChipStatus, string> = {
  pending: "queued",
  running: "working…",
  done: "done",
  error: "failed",
};

interface TicketCardProps {
  ticket: TicketDTO;
  onClick?: (idOrKey: string) => void;
  /** When provided, the card links to this epic via a clickable chip. */
  epicLookup?: Record<string, TicketDTO>;
  /** When provided, displays the active sprint name on the card. */
  activeSprintLookup?: Record<string, string>;
  onEpicClick?: (epicId: string) => void;
  /**
   * v2.29 S5 — latest agent-run status for agent-assigned tickets. The
   * BOARD fetches runs (once per refresh, agent-assigned tickets only);
   * the card itself never calls the agent-runs API.
   */
  agentRunStatus?: AgentRunChipStatus | null;
  /** v2.29 S5 — called after a successful inline (re)assign. */
  onAssigned?: () => void;
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
  agentRunStatus = null,
  onAssigned,
}: TicketCardProps) {
  const dragId = ticket.display_id || ticket.id;
  // v2.29 S5 — inline assign popover state.
  const [assignOpen, setAssignOpen] = useState(false);
  const [assigning, setAssigning] = useState(false);
  const [assignError, setAssignError] = useState<string | null>(null);

  // Escape closes the popover regardless of inner focus.
  useEffect(() => {
    if (!assignOpen) {
      setAssignError(null);
      return;
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setAssignOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [assignOpen]);

  const handleAssign = async (person: PersonRef | null) => {
    if (!person) {
      setAssignOpen(false);
      return;
    }
    setAssigning(true);
    setAssignError(null);
    try {
      await assignTicket(dragId, {
        assignee_id: person.id,
        assignee_type: person.kind,
        expected_version: ticket.version,
      });
      setAssignOpen(false);
      onAssigned?.();
    } catch (err) {
      // Keep the popover open and surface the reason inline so the user
      // can retry (e.g. a version conflict after a concurrent edit).
      setAssignError(err instanceof Error ? err.message : "Failed to assign");
    } finally {
      setAssigning(false);
    }
  };
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
      onDoubleClick={(e) => {
        if (isDragging) return;
        e.stopPropagation();
        // Full navigation to avoid a Router-context dependency on this
        // leaf card (the kanban renders TicketCard outside the standard
        // Router boundary in some test harnesses).
        window.location.assign(`/tickets/${encodeURIComponent(dragId)}`);
      }}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        // Only react to keys on the card itself — typing inside nested
        // interactive children (e.g. the assign popover's input) must
        // not open the drawer.
        if (e.target !== e.currentTarget) return;
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
        {isAgentAssignee && agentRunStatus && (
          <span
            className={`kanban-card__run-chip kanban-card__run-chip--${agentRunStatus}`}
            data-testid="ticket-run-chip"
            title={`Agent run: ${RUN_CHIP_LABEL[agentRunStatus]}`}
          >
            {RUN_CHIP_LABEL[agentRunStatus]}
          </span>
        )}
      </div>
      <div className="ticket-card__bottom">
        <span className={`priority-badge priority-badge--${priority}`}>
          {priority}
        </span>
        {assigneeLabel ? (
          <button
            type="button"
            className={
              isAgentAssignee
                ? "ticket-card__avatar ticket-card__avatar--agent ticket-card__avatar--btn"
                : "ticket-card__avatar ticket-card__avatar--btn"
            }
            title={`${assigneeLabel} — click to reassign`}
            aria-label={
              isAgentAssignee
                ? `Agent: ${assigneeLabel}`
                : `Assignee ${assigneeLabel}`
            }
            aria-haspopup="dialog"
            aria-expanded={assignOpen}
            data-testid={
              isAgentAssignee ? "ticket-avatar-agent" : "ticket-avatar-user"
            }
            onPointerDown={(e) => e.stopPropagation()}
            onClick={(e) => {
              e.stopPropagation();
              setAssignOpen((o) => !o);
            }}
          >
            {initials(assigneeLabel)}
          </button>
        ) : (
          <button
            type="button"
            className="ticket-card__assign-btn"
            data-testid="ticket-assign-btn"
            aria-haspopup="dialog"
            aria-expanded={assignOpen}
            onPointerDown={(e) => e.stopPropagation()}
            onClick={(e) => {
              e.stopPropagation();
              setAssignOpen((o) => !o);
            }}
          >
            Assign
          </button>
        )}
      </div>
      {assignOpen && (
        <div
          className="kanban-card__assign-pop"
          data-testid="ticket-assign-pop"
          role="dialog"
          aria-label="Assign ticket"
          onPointerDown={(e) => e.stopPropagation()}
          onClick={(e) => e.stopPropagation()}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.stopPropagation();
              setAssignOpen(false);
            }
          }}
        >
          <PersonPicker
            value={null}
            onChange={(p) => void handleAssign(p)}
            kind="any"
            placeholder="Assign to…"
            disabled={assigning}
          />
          {assignError && (
            <p className="kanban-card__assign-error" role="alert">
              {assignError}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
