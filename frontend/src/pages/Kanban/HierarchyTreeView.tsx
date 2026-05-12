import React, { useEffect, useState } from "react";
import { getSubtree, type SubtreeRow } from "../../api/tickets";

interface HierarchyTreeViewProps {
  rootKey: string | null;
  onSelect?: (idOrKey: string) => void;
}

export function HierarchyTreeView({
  rootKey,
  onSelect,
}: HierarchyTreeViewProps) {
  const [rows, setRows] = useState<SubtreeRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!rootKey) {
      setRows([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    (async () => {
      try {
        const res = await getSubtree(rootKey, 8);
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
  }, [rootKey]);

  if (!rootKey) {
    return (
      <div className="hierarchy-tree">
        <em>Select an epic key to view its hierarchy.</em>
      </div>
    );
  }

  return (
    <div className="hierarchy-tree" role="tree" aria-label="Ticket hierarchy">
      {loading && <div>Loading…</div>}
      {error && <div className="ticket-drawer__error">{error}</div>}
      {!loading && rows.length === 0 && !error && <em>No tickets found.</em>}
      {rows.map((row) => (
        <div
          key={row.ticket.id}
          className="hierarchy-tree__row"
          style={{ paddingLeft: `${row.depth * 16}px` }}
          role="treeitem"
          aria-level={row.depth + 1}
          onClick={() => onSelect?.(row.ticket.key || row.ticket.id)}
        >
          <span className="hierarchy-tree__key">
            {row.ticket.key ?? row.ticket.id.slice(0, 8)}
          </span>
          <span style={{ flex: 1 }}>{row.ticket.title}</span>
          <span className="status-badge">{row.ticket.status}</span>
        </div>
      ))}
    </div>
  );
}
