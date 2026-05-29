import { useEffect, useMemo, useState } from "react";
import { getSubtree, listTickets, type SubtreeRow, type TicketDTO } from "../../api/tickets";
import {
  TICKET_TYPE_BADGE,
  type TicketTypeV2,
} from "../CreateTicket/fieldsByType";

interface HierarchyTreeViewProps {
  rootKey: string | null;
  projectId?: string | null;
  onSelect?: (idOrKey: string) => void;
}

export function HierarchyTreeView({
  rootKey,
  projectId,
  onSelect,
}: HierarchyTreeViewProps) {
  const [rows, setRows] = useState<SubtreeRow[]>([]);
  const [roots, setRoots] = useState<TicketDTO[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pickedKey, setPickedKey] = useState<string | null>(null);

  const effectiveRoot = (rootKey ?? "").trim() || pickedKey;

  // If no explicit root, list project epics/workpackages and let the user pick.
  useEffect(() => {
    if (effectiveRoot) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    listTickets({
      project_id: projectId ?? undefined,
      type: ["epic", "workpackage"],
      limit: 100,
    })
      .then((res) => {
        if (!cancelled) setRoots(res.items ?? []);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, effectiveRoot]);

  useEffect(() => {
    if (!effectiveRoot) {
      setRows([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    (async () => {
      try {
        const res = await getSubtree(effectiveRoot, 8);
        if (!cancelled) setRows(res.items);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [effectiveRoot]);

  const filteredRows = useMemo(() => {
    if (!projectId) return rows;
    // Defensive client-side filter: subtree should already be in-project but
    // belt-and-braces against cross-project drift if backend leaks one through.
    return rows.filter(
      (r) => !r.ticket.project_id || r.ticket.project_id === projectId,
    );
  }, [rows, projectId]);

  if (!effectiveRoot) {
    return (
      <div className="hierarchy-tree">
        {loading && <div>Loading roots…</div>}
        {error && <div className="ticket-drawer__error">{error}</div>}
        {!loading && roots.length === 0 && !error && (
          <em>No epics or workpackages in this project.</em>
        )}
        {!loading && roots.length > 0 && (
          <div>
            <em>Pick an epic / workpackage to view its hierarchy:</em>
            <ul style={{ listStyle: "none", padding: 0, margin: "0.5rem 0" }}>
              {roots.map((r) => {
                const type = (r.type ?? "epic") as TicketTypeV2;
                const badge = TICKET_TYPE_BADGE[type] ?? TICKET_TYPE_BADGE.epic;
                return (
                  <li key={r.id}>
                    <button
                      type="button"
                      className="kanban-page__btn"
                      style={{ margin: "2px", display: "inline-flex", gap: 6 }}
                      onClick={() => setPickedKey(r.display_id || r.id)}
                    >
                      <span
                        className="ticket-card__type-badge"
                        style={{ background: badge.color }}
                      >
                        {badge.letter}
                      </span>
                      {r.display_id ?? r.id.slice(0, 8)} — {r.title}
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="hierarchy-tree" role="tree" aria-label="Ticket hierarchy">
      {loading && <div>Loading…</div>}
      {error && <div className="ticket-drawer__error">{error}</div>}
      {!loading && filteredRows.length === 0 && !error && <em>No tickets found.</em>}
      {filteredRows.map((row) => {
        const type = (row.ticket.type ?? "task") as TicketTypeV2;
        const badge = TICKET_TYPE_BADGE[type] ?? TICKET_TYPE_BADGE.task;
        return (
          <div
            key={row.ticket.id}
            className="hierarchy-tree__row"
            style={{ paddingLeft: `${row.depth * 16}px` }}
            role="treeitem"
            aria-level={row.depth + 1}
            onClick={() => onSelect?.(row.ticket.display_id || row.ticket.id)}
          >
            <span
              className="ticket-card__type-badge"
              style={{ background: badge.color, marginRight: 6 }}
              aria-hidden="true"
            >
              {badge.letter}
            </span>
            <span className="hierarchy-tree__key">
              {row.ticket.display_id ?? row.ticket.id.slice(0, 8)}
            </span>
            <span style={{ flex: 1 }}>{row.ticket.title}</span>
            <span className="status-badge">{row.ticket.status}</span>
          </div>
        );
      })}
    </div>
  );
}
