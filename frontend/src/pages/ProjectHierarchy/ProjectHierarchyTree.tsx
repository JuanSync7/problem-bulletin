/**
 * B2: ProjectHierarchyTree
 *
 * Renders a flat DFS list of HierarchyRow items with Unicode box-drawing
 * prefix chars (└─ ├─ │). Supports:
 *  - Type filtering (client-side): unchecked types hidden, children re-parented
 *    to nearest visible ancestor.
 *  - Roving-tabindex keyboard navigation (↑/↓ move, ← collapse, → expand,
 *    Enter opens /tickets/<key>).
 *  - Collapse/expand individual nodes.
 *
 * Pure helpers exported for testability:
 *  - applyTypeFilter(rows, hiddenTypes) → HierarchyRow[]
 *  - rowsToVisibleTree(rows, hiddenTypes) → HierarchyRow[]
 *  - getKeyboardNextIndex(current, total, key) → number
 *
 * The container element carries data-testid="hierarchy-tree-container" and
 * has NO card chrome (background: transparent; border: none; box-shadow: none)
 * — enforced by ProjectHierarchy.css and guarded by the seamless test.
 */
import { useRef, useState, useCallback } from "react";
import type { HierarchyRow } from "../../api/projects";
import { TreeNode } from "./TreeNode";
import "./ProjectHierarchy.css";

// ---------------------------------------------------------------------------
// Pure helpers (exported for testability)
// ---------------------------------------------------------------------------

/**
 * Filter out rows whose ticket.type is in hiddenTypes.
 * Children of hidden rows are re-parented to the nearest visible ancestor.
 *
 * Algorithm:
 *  1. Walk the rows in DFS order (they're already DFS-stable from backend).
 *  2. Maintain a stack of visible ancestor IDs keyed by depth.
 *  3. For each row:
 *     - If hidden: record its id→nearest-visible-parent mapping for child re-parenting.
 *     - If visible: rewrite parent_id through the mapping chain, emit.
 */
export function applyTypeFilter(rows: HierarchyRow[], hiddenTypes: string[]): HierarchyRow[] {
  if (hiddenTypes.length === 0) return rows;

  // Map from hidden ticket id → nearest visible ancestor id (or null)
  const remapParent = new Map<string, string | null>();
  const result: HierarchyRow[] = [];

  for (const row of rows) {
    const isHidden = hiddenTypes.includes(row.ticket.type);

    if (isHidden) {
      // Find nearest visible ancestor for this row's children
      const nearestVisible = row.parent_id !== null
        ? (remapParent.has(row.parent_id) ? remapParent.get(row.parent_id) ?? null : row.parent_id)
        : null;
      remapParent.set(row.ticket.id, nearestVisible);
    } else {
      // Re-parent if needed
      let effectiveParentId = row.parent_id;
      if (effectiveParentId !== null && remapParent.has(effectiveParentId)) {
        effectiveParentId = remapParent.get(effectiveParentId) ?? null;
      }
      result.push({ ...row, parent_id: effectiveParentId });
    }
  }

  return result;
}

/**
 * Apply type filter and return the visible tree in DFS order.
 * (Currently same as applyTypeFilter — separate export for clarity.)
 */
export function rowsToVisibleTree(rows: HierarchyRow[], hiddenTypes: string[]): HierarchyRow[] {
  return applyTypeFilter(rows, hiddenTypes);
}

/**
 * Compute next focused index for keyboard navigation.
 * Clamps at boundaries (does not wrap).
 */
export function getKeyboardNextIndex(
  current: number,
  total: number,
  key: "ArrowDown" | "ArrowUp" | string,
): number {
  if (key === "ArrowDown") return Math.min(current + 1, total - 1);
  if (key === "ArrowUp") return Math.max(current - 1, 0);
  return current;
}

// ---------------------------------------------------------------------------
// Unicode box-drawing prefix computation
// ---------------------------------------------------------------------------

interface PrefixInfo {
  prefix: string;
  isLastSibling: boolean;
}

/**
 * Compute Unicode box-drawing prefix for a row given its depth and
 * whether it is the last sibling at its level.
 *
 * Depth 0: no prefix (root)
 * Depth 1: "└─ " or "├─ "
 * Deeper:  "│  " repeated for ancestor levels + "└─ " or "├─ "
 */
function computePrefix(depth: number, isLast: boolean, ancestorLasts: boolean[]): string {
  if (depth === 0) return "";
  const parts: string[] = [];
  // tree(1)-style 4-char indent rails so each level is visually distinct,
  // matching the spacing a developer expects when reading an `.md` file tree.
  for (let i = 0; i < depth - 1; i++) {
    parts.push(ancestorLasts[i] ? "    " : "│   ");
  }
  parts.push(isLast ? "└── " : "├── ");
  return parts.join("");
}

/**
 * Build prefix info for each visible row.
 * We need to know for each (depth, position) whether it's the last child.
 */
function buildPrefixMap(rows: HierarchyRow[]): Map<string, PrefixInfo> {
  const result = new Map<string, PrefixInfo>();

  // Group children by parent_id
  const childrenByParent = new Map<string | null, string[]>();
  for (const row of rows) {
    const pid = row.parent_id;
    if (!childrenByParent.has(pid)) childrenByParent.set(pid, []);
    childrenByParent.get(pid)!.push(row.ticket.id);
  }

  // Track ancestor isLast stack
  const ancestorLasts: boolean[] = [];
  const parentLastMap = new Map<string, boolean>();

  for (const row of rows) {
    const siblings = childrenByParent.get(row.parent_id) ?? [];
    const isLast = siblings[siblings.length - 1] === row.ticket.id;

    // Build ancestor isLast array from depth
    const anc = ancestorLasts.slice(0, row.depth - 1);
    const prefix = computePrefix(row.depth, isLast, anc);

    result.set(row.ticket.id, { prefix, isLastSibling: isLast });
    parentLastMap.set(row.ticket.id, isLast);

    // Update ancestorLasts for next row
    if (row.depth >= ancestorLasts.length) {
      ancestorLasts.push(isLast);
    } else {
      ancestorLasts[row.depth - 1] = isLast;
    }
  }

  return result;
}

// ---------------------------------------------------------------------------
// Component props & main component
// ---------------------------------------------------------------------------

export interface ProjectHierarchyTreeProps {
  rows: HierarchyRow[];
  hiddenTypes: string[];
  projectId: string;
}

export function ProjectHierarchyTree({
  rows,
  hiddenTypes,
  projectId: _projectId,
}: ProjectHierarchyTreeProps) {
  const [focusedIndex, setFocusedIndex] = useState(0);
  // collapsedIds: set of ticket IDs whose subtrees are collapsed
  const [collapsedIds, setCollapsedIds] = useState<Set<string>>(new Set());

  const nodeRefs = useRef<Map<number, HTMLDivElement | null>>(new Map());

  // Apply type filter
  const filteredRows = rowsToVisibleTree(rows, hiddenTypes);

  // Apply collapse filter: remove rows whose ancestors are collapsed
  const visibleRows = filteredRows.filter((row) => {
    // Walk up the parent chain; if any ancestor is collapsed, hide this row
    let current = row.parent_id;
    while (current !== null) {
      if (collapsedIds.has(current)) return false;
      // Find the parent's parent
      const parentRow = filteredRows.find((r) => r.ticket.id === current);
      current = parentRow?.parent_id ?? null;
    }
    return true;
  });

  // Compute prefix map
  const prefixMap = buildPrefixMap(visibleRows);

  // Determine which rows have children (in the TYPE-filtered set, NOT the
  // collapse-filtered set — so collapsed nodes still show the expand indicator).
  const hasChildrenSet = new Set<string>();
  for (const row of filteredRows) {
    if (row.parent_id !== null) hasChildrenSet.add(row.parent_id);
  }

  function focusRow(index: number) {
    setFocusedIndex(index);
    nodeRefs.current.get(index)?.focus();
  }

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>, index: number) => {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        const next = getKeyboardNextIndex(index, visibleRows.length, e.key);
        focusRow(next);
      }
    },
    [visibleRows.length],
  );

  function toggleCollapse(ticketId: string) {
    setCollapsedIds((prev) => {
      const next = new Set(prev);
      if (next.has(ticketId)) {
        next.delete(ticketId);
      } else {
        next.add(ticketId);
      }
      return next;
    });
  }

  return (
    <div
      data-testid="hierarchy-tree-container"
      className="hierarchy-tree-container"
      role="tree"
      aria-label="Project ticket hierarchy"
    >
      {visibleRows.length === 0 && (
        <em style={{ color: "var(--color-text-secondary, #888)", padding: "0.5rem" }}>
          No tickets found.
        </em>
      )}
      {visibleRows.map((row, index) => {
        const info = prefixMap.get(row.ticket.id) ?? { prefix: "", isLastSibling: true };
        const hasChildren = hasChildrenSet.has(row.ticket.id);
        const isExpanded = !collapsedIds.has(row.ticket.id);

        return (
          <TreeNode
            key={row.ticket.id}
            row={{
              ticketId: row.ticket.id,
              displayId: row.ticket.display_id,
              title: row.ticket.title,
              type: row.ticket.type,
              status: row.ticket.status,
              depth: row.depth,
              prefix: info.prefix,
              isLastSibling: info.isLastSibling,
              hasChildren,
              isExpanded,
            }}
            tabIndex={index === focusedIndex ? 0 : -1}
            onFocus={() => setFocusedIndex(index)}
            onKeyDown={(e) => handleKeyDown(e, index)}
            onToggleExpand={() => toggleCollapse(row.ticket.id)}
            nodeRef={(el) => nodeRefs.current.set(index, el)}
          />
        );
      })}
    </div>
  );
}
