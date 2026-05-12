import React from "react";
import { useDraggable } from "@dnd-kit/core";
import type { TicketDTO } from "../../api/tickets";

interface TicketCardProps {
  ticket: TicketDTO;
  onClick?: (idOrKey: string) => void;
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

export function TicketCard({ ticket, onClick }: TicketCardProps) {
  const dragId = ticket.key || ticket.id;
  const { attributes, listeners, setNodeRef, isDragging, transform } =
    useDraggable({ id: dragId, data: { ticket } });

  const style: React.CSSProperties = transform
    ? {
        transform: `translate3d(${transform.x}px, ${transform.y}px, 0)`,
      }
    : {};

  const priority = ticket.priority ?? "medium";
  const assigneeLabel =
    (ticket.assignee_id as string | undefined) ??
    (ticket.assignee_type as string | undefined) ??
    null;

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
    >
      <div className="ticket-card__top">
        <span>{ticket.key ?? ticket.id.slice(0, 8)}</span>
        {ticket.story_points != null && (
          <span className="ticket-card__points">{ticket.story_points}</span>
        )}
      </div>
      <div className="ticket-card__title">{ticket.title}</div>
      <div className="ticket-card__bottom">
        <span className={`priority-badge priority-badge--${priority}`}>
          {priority}
        </span>
        {assigneeLabel && (
          <span
            className="ticket-card__avatar"
            title={assigneeLabel}
            aria-label={`Assignee ${assigneeLabel}`}
          >
            {initials(assigneeLabel)}
          </span>
        )}
      </div>
    </div>
  );
}
