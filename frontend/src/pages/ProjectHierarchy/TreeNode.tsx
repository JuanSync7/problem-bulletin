/**
 * B2: TreeNode — renders a single row in the ProjectHierarchyTree.
 *
 * Displays:
 *  - Unicode box-drawing prefix (└─ / ├─ / │)
 *  - Ticket key (display_id)
 *  - Ticket title
 *  - Type badge + status
 *
 * Click or Enter navigates to /tickets/<key>.
 * Roving-tabindex: tabIndex is 0 for focused row, -1 for all others.
 */
import { useNavigate } from "react-router-dom";

export interface TreeNodeRow {
  ticketId: string;
  displayId: string;
  title: string;
  type: string;
  status: string;
  depth: number;
  /** Unicode prefix string computed by parent */
  prefix: string;
  isLastSibling: boolean;
  hasChildren: boolean;
  isExpanded: boolean;
}

interface TreeNodeProps {
  row: TreeNodeRow;
  tabIndex: number;
  onFocus: () => void;
  onKeyDown: (e: React.KeyboardEvent<HTMLDivElement>) => void;
  onToggleExpand: () => void;
  nodeRef: (el: HTMLDivElement | null) => void;
}

const TYPE_COLORS: Record<string, string> = {
  epic: "#7c3aed",
  story: "#2563eb",
  task: "#16a34a",
  subtask: "#0891b2",
  bug: "#dc2626",
  workpackage: "#b45309",
};

export function TreeNode({
  row,
  tabIndex,
  onFocus,
  onKeyDown,
  onToggleExpand,
  nodeRef,
}: TreeNodeProps) {
  const navigate = useNavigate();

  function handleClick() {
    navigate(`/tickets/${row.displayId}`);
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      navigate(`/tickets/${row.displayId}`);
      return;
    }
    if ((e.key === "ArrowLeft" || e.key === "ArrowRight") && row.hasChildren) {
      e.preventDefault();
      onToggleExpand();
      return;
    }
    onKeyDown(e);
  }

  const badgeColor = TYPE_COLORS[row.type] ?? "#6b7280";

  return (
    <div
      ref={nodeRef}
      role="treeitem"
      aria-level={row.depth + 1}
      aria-expanded={row.hasChildren ? row.isExpanded : undefined}
      tabIndex={tabIndex}
      className="hierarchy-tree-row"
      onClick={handleClick}
      onFocus={onFocus}
      onKeyDown={handleKeyDown}
      data-ticket-id={row.ticketId}
    >
      <span className="hierarchy-tree-row__prefix" aria-hidden="true">
        {row.prefix}
      </span>
      <span className="hierarchy-tree-row__key">{row.displayId}</span>
      <span className="hierarchy-tree-row__title">{row.title}</span>
      <span
        className="hierarchy-tree-row__type-badge"
        style={{ background: badgeColor }}
        aria-label={`type: ${row.type}`}
      >
        {row.type.slice(0, 1).toUpperCase()}
      </span>
      <span className="hierarchy-tree-row__status">{row.status}</span>
    </div>
  );
}
