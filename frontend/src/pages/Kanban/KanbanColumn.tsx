import React from "react";
import { useDroppable } from "@dnd-kit/core";
import type { TicketDTO, TicketStatus } from "../../api/tickets";
import { TicketCard } from "./TicketCard";

interface KanbanColumnProps {
  status: TicketStatus;
  title: string;
  tickets: TicketDTO[];
  onCardClick?: (idOrKey: string) => void;
  /** Optional swimlane scope appended to the drop id. */
  dropIdSuffix?: string;
  /**
   * v2.1-WP11 — authoritative column count from the backend's
   * ``column_counts`` aggregate. Independent of pagination state, so the
   * WIP-limit chip stays accurate even when only the first page is
   * loaded. Falls back to ``tickets.length`` when omitted (e.g. org-wide
   * listings where the backend returns ``column_counts: null``).
   */
  count?: number;
  /**
   * v2.1-WP11 — per-status WIP limit from ``project.wip_limits``. When
   * present, the column header renders ``<count> / <limit>`` and the
   * chip + border swap colour at the threshold (amber at equality, red
   * over-limit).
   */
  wipLimit?: number;
}

export function KanbanColumn({
  status,
  title,
  tickets,
  onCardClick,
  dropIdSuffix,
  count,
  wipLimit,
}: KanbanColumnProps) {
  const id = dropIdSuffix ? `col:${status}:${dropIdSuffix}` : `col:${status}`;
  const { setNodeRef, isOver } = useDroppable({ id, data: { status } });

  // Prefer the backend aggregate; fall back to the loaded slice. The
  // local fallback is correct for swimlane sub-buckets (which the
  // backend doesn't shard counts by) and for org-wide listings.
  const effectiveCount = count ?? tickets.length;
  const hasLimit = typeof wipLimit === "number" && wipLimit > 0;
  const overLimit = hasLimit && effectiveCount > (wipLimit as number);
  const atLimit = hasLimit && effectiveCount === (wipLimit as number);

  let chipClass = "kanban-column__count";
  if (overLimit) chipClass += " kanban-column__count--over";
  else if (atLimit) chipClass += " kanban-column__count--at";

  let columnClass = "kanban-column";
  if (isOver) columnClass += " kanban-column--over";
  if (overLimit) columnClass += " kanban-column--over-limit";

  return (
    <div
      ref={setNodeRef}
      className={columnClass}
      data-status={status}
      data-over-limit={overLimit || undefined}
    >
      <div className="kanban-column__header">
        <span>{title}</span>
        <span
          className={chipClass}
          aria-label={
            hasLimit
              ? `${effectiveCount} of ${wipLimit} (WIP limit)`
              : `${effectiveCount} tickets`
          }
        >
          {hasLimit ? `${effectiveCount} / ${wipLimit}` : effectiveCount}
        </span>
      </div>
      <div className="kanban-column__list">
        {tickets.map((t) => (
          <TicketCard key={t.id} ticket={t} onClick={onCardClick} />
        ))}
      </div>
    </div>
  );
}
