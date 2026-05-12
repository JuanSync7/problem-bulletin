import React, { useMemo, useState } from "react";
import {
  DndContext,
  DragEndEvent,
  PointerSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import type { TicketDTO, TicketStatus } from "../../api/tickets";
import { transitionTicket } from "../../api/tickets";
import { KanbanColumn } from "./KanbanColumn";

const VISIBLE_STATUSES: { status: TicketStatus; title: string }[] = [
  { status: "todo", title: "To Do" },
  { status: "in_progress", title: "In Progress" },
  { status: "in_review", title: "In Review" },
  { status: "done", title: "Done" },
];

interface KanbanBoardProps {
  tickets: TicketDTO[];
  onTicketsChange: (next: TicketDTO[]) => void;
  onCardClick: (idOrKey: string) => void;
  onError?: (message: string) => void;
}

export function KanbanBoard({
  tickets,
  onTicketsChange,
  onCardClick,
  onError,
}: KanbanBoardProps) {
  const [pending, setPending] = useState<Set<string>>(new Set());

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
  );

  const byStatus = useMemo(() => {
    const groups: Record<TicketStatus, TicketDTO[]> = {
      todo: [],
      in_progress: [],
      in_review: [],
      blocked: [],
      done: [],
      cancelled: [],
    };
    for (const t of tickets) {
      const s = (t.status ?? "todo") as TicketStatus;
      (groups[s] ?? groups.todo).push(t);
    }
    return groups;
  }, [tickets]);

  const handleDragEnd = async (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over) return;
    const overId = String(over.id);
    if (!overId.startsWith("col:")) return;
    const toStatus = overId.slice(4) as TicketStatus;
    const dragId = String(active.id);
    const moving = tickets.find((t) => (t.key || t.id) === dragId);
    if (!moving || moving.status === toStatus) return;

    const previousStatus = moving.status;
    // Optimistic
    onTicketsChange(
      tickets.map((t) =>
        (t.key || t.id) === dragId ? { ...t, status: toStatus } : t,
      ),
    );
    setPending((p) => new Set(p).add(dragId));
    try {
      const updated = await transitionTicket(dragId, toStatus);
      onTicketsChange(
        tickets.map((t) =>
          (t.key || t.id) === dragId
            ? { ...t, ...updated, status: updated.status }
            : t,
        ),
      );
    } catch (e) {
      // Roll back
      onTicketsChange(
        tickets.map((t) =>
          (t.key || t.id) === dragId ? { ...t, status: previousStatus } : t,
        ),
      );
      const msg = e instanceof Error ? e.message : "Transition failed";
      onError?.(msg);
    } finally {
      setPending((p) => {
        const n = new Set(p);
        n.delete(dragId);
        return n;
      });
    }
  };

  return (
    <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
      <div className="kanban-board" data-pending={pending.size}>
        {VISIBLE_STATUSES.map(({ status, title }) => (
          <KanbanColumn
            key={status}
            status={status}
            title={title}
            tickets={byStatus[status]}
            onCardClick={onCardClick}
          />
        ))}
      </div>
    </DndContext>
  );
}
