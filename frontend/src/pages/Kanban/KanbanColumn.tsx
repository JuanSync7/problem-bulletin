import React from "react";
import { useDroppable } from "@dnd-kit/core";
import type { TicketDTO, TicketStatus } from "../../api/tickets";
import { TicketCard } from "./TicketCard";

interface KanbanColumnProps {
  status: TicketStatus;
  title: string;
  tickets: TicketDTO[];
  onCardClick?: (idOrKey: string) => void;
}

export function KanbanColumn({
  status,
  title,
  tickets,
  onCardClick,
}: KanbanColumnProps) {
  const { setNodeRef, isOver } = useDroppable({ id: `col:${status}`, data: { status } });
  return (
    <div
      ref={setNodeRef}
      className={`kanban-column${isOver ? " kanban-column--over" : ""}`}
      data-status={status}
    >
      <div className="kanban-column__header">
        <span>{title}</span>
        <span className="kanban-column__count">{tickets.length}</span>
      </div>
      <div className="kanban-column__list">
        {tickets.map((t) => (
          <TicketCard key={t.id} ticket={t} onClick={onCardClick} />
        ))}
      </div>
    </div>
  );
}
