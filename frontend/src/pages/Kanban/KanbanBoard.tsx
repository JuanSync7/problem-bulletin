import { useMemo, useState } from "react";
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
import type { SwimlaneMode } from "./FiltersBar";

const BASE_STATUSES: { status: TicketStatus; title: string }[] = [
  { status: "backlog", title: "Backlog" },
  { status: "todo", title: "To Do" },
  { status: "in_progress", title: "In Progress" },
  { status: "in_review", title: "In Review" },
  { status: "done", title: "Done" },
];

const TERMINAL_STATUSES: { status: TicketStatus; title: string }[] = [
  { status: "blocked", title: "Blocked" },
  { status: "cancelled", title: "Cancelled" },
];

interface KanbanBoardProps {
  tickets: TicketDTO[];
  onTicketsChange: (next: TicketDTO[]) => void;
  onCardClick: (idOrKey: string) => void;
  onError?: (message: string) => void;
  swimlane?: SwimlaneMode;
  showTerminal?: boolean;
  /** Map of epic_id -> ticket for header labelling under swimlane=epic. */
  epicLookup?: Record<string, TicketDTO>;
  /** Map of member_id -> label for swimlane=assignee. */
  assigneeLookup?: Record<string, string>;
  /** Map of sprint_id -> name for swimlane=sprint. */
  sprintLookup?: Record<string, string>;
  /**
   * v2.1-WP11 — authoritative per-status counts from the backend
   * ``column_counts`` aggregate. ``null`` / ``undefined`` falls back to
   * counting the loaded slice (correct for swimlane buckets and
   * org-wide listings).
   */
  columnCounts?: Partial<Record<TicketStatus, number>> | null;
  /**
   * v2.1-WP11 — per-status WIP limits from ``project.wip_limits``. Only
   * applied to the "all" swimlane (counts inside swimlane sub-groups
   * fall back to local lengths — limits are board-wide, not per-lane).
   */
  wipLimits?: Record<string, number>;
}

interface SwimlaneGroup {
  key: string;
  label: string;
  tickets: TicketDTO[];
}

function groupForSwimlane(
  tickets: TicketDTO[],
  mode: SwimlaneMode,
  epicLookup: Record<string, TicketDTO>,
  assigneeLookup: Record<string, string>,
  sprintLookup: Record<string, string>,
): SwimlaneGroup[] {
  if (mode === "none") {
    return [{ key: "__all__", label: "", tickets }];
  }
  const buckets = new Map<string, SwimlaneGroup>();
  const upsert = (key: string, label: string, t: TicketDTO) => {
    const existing = buckets.get(key);
    if (existing) existing.tickets.push(t);
    else buckets.set(key, { key, label, tickets: [t] });
  };
  for (const t of tickets) {
    if (mode === "epic") {
      const id = (t.epic_id as string | null | undefined) ?? null;
      if (!id) upsert("__none__", "No epic", t);
      else {
        const e = epicLookup[id];
        const label = e ? `${e.display_id ?? id.slice(0, 8)} — ${e.title}` : id.slice(0, 8);
        upsert(id, label, t);
      }
    } else if (mode === "assignee") {
      const id = (t.assignee_id as string | null | undefined) ?? null;
      if (!id) upsert("__none__", "Unassigned", t);
      else upsert(id, assigneeLookup[id] ?? id.slice(0, 8), t);
    } else if (mode === "sprint") {
      const id = (t.sprint_id as string | null | undefined) ?? null;
      if (!id) upsert("__none__", "No sprint", t);
      else upsert(id, sprintLookup[id] ?? id.slice(0, 8), t);
    }
  }
  // Stable order: __none__ last, otherwise alpha by label.
  return Array.from(buckets.values()).sort((a, b) => {
    if (a.key === "__none__") return 1;
    if (b.key === "__none__") return -1;
    return a.label.localeCompare(b.label);
  });
}

export function KanbanBoard({
  tickets,
  onTicketsChange,
  onCardClick,
  onError,
  swimlane = "none",
  showTerminal = false,
  epicLookup = {},
  assigneeLookup = {},
  sprintLookup = {},
  columnCounts = null,
  wipLimits = {},
}: KanbanBoardProps) {
  const [pending, setPending] = useState<Set<string>>(new Set());

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
  );

  const columns = useMemo(
    () => (showTerminal ? [...BASE_STATUSES, ...TERMINAL_STATUSES] : BASE_STATUSES),
    [showTerminal],
  );

  const swimlanes = useMemo(
    () =>
      groupForSwimlane(
        tickets ?? [],
        swimlane,
        epicLookup,
        assigneeLookup,
        sprintLookup,
      ),
    [tickets, swimlane, epicLookup, assigneeLookup, sprintLookup],
  );

  const handleDragEnd = async (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over) return;
    const overId = String(over.id);
    if (!overId.startsWith("col:")) return;
    // col id is `col:<status>` or `col:<status>:<lane>` — split on the first colon.
    const rest = overId.slice(4);
    const toStatus = rest.split(":")[0] as TicketStatus;
    const dragId = String(active.id);
    const moving = tickets.find((t) => (t.display_id || t.id) === dragId);
    if (!moving || moving.status === toStatus) return;

    const previousStatus = moving.status;
    // Optimistic
    onTicketsChange(
      tickets.map((t) =>
        (t.display_id || t.id) === dragId ? { ...t, status: toStatus } : t,
      ),
    );
    setPending((p) => new Set(p).add(dragId));
    try {
      const updated = await transitionTicket(dragId, toStatus);
      onTicketsChange(
        tickets.map((t) =>
          (t.display_id || t.id) === dragId
            ? { ...t, ...updated, status: updated.status }
            : t,
        ),
      );
    } catch (e) {
      // Roll back
      onTicketsChange(
        tickets.map((t) =>
          (t.display_id || t.id) === dragId ? { ...t, status: previousStatus } : t,
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

  const renderRow = (lane: SwimlaneGroup) => {
    const byStatus: Record<string, TicketDTO[]> = {};
    for (const col of columns) byStatus[col.status] = [];
    for (const t of lane.tickets) {
      const s = String(t.status ?? "todo");
      if (byStatus[s]) byStatus[s].push(t);
    }
    return (
      <div key={lane.key} className="kanban-swimlane">
        {swimlane !== "none" && (
          <div
            className="kanban-swimlane__header"
            data-testid={`swimlane-header-${lane.key}`}
          >
            {lane.label} ({lane.tickets.length})
          </div>
        )}
        <div className="kanban-board" data-pending={pending.size}>
          {columns.map(({ status, title }) => {
            // Backend-authoritative count only applies to the unswimlaned
            // board — swimlane sub-buckets get their local slice length.
            const backendCount =
              swimlane === "none" && columnCounts
                ? (columnCounts[status] as number | undefined)
                : undefined;
            const limit = wipLimits ? wipLimits[status] : undefined;
            return (
              <KanbanColumn
                key={status}
                status={status}
                title={title}
                tickets={byStatus[status] ?? []}
                onCardClick={onCardClick}
                // Per-swimlane droppable id keeps drops scoped visually.
                dropIdSuffix={swimlane === "none" ? undefined : lane.key}
                count={backendCount}
                wipLimit={
                  swimlane === "none" && typeof limit === "number"
                    ? limit
                    : undefined
                }
              />
            );
          })}
        </div>
      </div>
    );
  };

  return (
    <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
      <div className="kanban-swimlanes">
        {swimlanes.length === 0 ? (
          <div className="kanban-swimlane__empty">No tickets match the current filters.</div>
        ) : (
          swimlanes.map(renderRow)
        )}
      </div>
    </DndContext>
  );
}
