/**
 * A2b: Typeahead Dropdown component for GlobalSearchBar.
 *
 * Renders a listbox with:
 *  - Optional pinned direct-match row at the top.
 *  - Combined entity rows grouped by entity weight order
 *    (tickets > problems > components > labels > users).
 *  - A pinned "View all results for «q»" row at the bottom.
 *
 * Navigation:
 *  - Each row is a `role="option"` button.
 *  - `highlightedIndex` controls which row has `aria-selected="true"` and
 *    the `.gsb__result-item--highlighted` class.
 *  - `onSelect(href)` fires on click or Enter.
 */
import React from "react";
import type { SearchItem } from "../../api/search";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface DropdownRow {
  /** Stable key for React reconciliation. */
  key: string;
  item: SearchItem;
  /** For the "View all" sentinel row, use kind="__view_all__". */
}

export interface DropdownProps {
  query: string;
  directMatch: SearchItem | null;
  combined: SearchItem[];
  isLoading: boolean;
  error: string | null;
  highlightedIndex: number;
  onSelect: (href: string) => void;
}

// ---------------------------------------------------------------------------
// Group label map — maps kind to human display name
// ---------------------------------------------------------------------------

const KIND_LABEL: Record<string, string> = {
  ticket: "Tickets",
  problem: "Problems",
  component: "Components",
  label: "Labels",
  user: "Users",
  agent: "Agents",
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Group `combined` items by their `kind` field, preserving insertion order
 * within each group. Groups appear in SEARCH_ENTITY_WEIGHTS order (the
 * backend returns them already ranked, so we just split on kind boundaries).
 *
 * We collect unique kinds in first-seen order rather than using a fixed
 * order list so that groups absent from the backend result don't show up
 * as empty headers.
 */
function groupByKind(items: SearchItem[]): { kind: string; items: SearchItem[] }[] {
  const kindOrder: string[] = [];
  const kindMap: Record<string, SearchItem[]> = {};
  for (const item of items) {
    if (!kindMap[item.kind]) {
      kindOrder.push(item.kind);
      kindMap[item.kind] = [];
    }
    kindMap[item.kind].push(item);
  }
  return kindOrder.map((kind) => ({ kind, items: kindMap[kind] }));
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function Dropdown({
  query,
  directMatch,
  combined,
  isLoading,
  error,
  highlightedIndex,
  onSelect,
}: DropdownProps) {
  const groups = groupByKind(combined);

  // Build the ordered flat list of selectable rows for highlight accounting.
  // Index 0 = directMatch (if present), then combined items in order,
  // then the "View all" row at the end.
  let rowIndex = 0;

  // directMatch occupies index 0 when present
  const directMatchIndex = directMatch ? rowIndex++ : -1;

  // Combined item rows
  const groupsWithIndex: {
    kind: string;
    items: { item: SearchItem; index: number }[];
  }[] = groups.map((g) => ({
    kind: g.kind,
    items: g.items.map((item) => ({ item, index: rowIndex++ })),
  }));

  // "View all" is always last
  const viewAllIndex = rowIndex;

  return (
    <div className="gsb__dropdown" role="listbox">
      {isLoading && <div className="gsb__loading">Searching…</div>}
      {error && <div className="gsb__error">{error}</div>}

      {/* Direct-match row — pinned top */}
      {directMatch && (
        <>
          <div className="gsb__section-label">Direct match</div>
          <button
            className={[
              "gsb__result-item",
              "gsb__result-item--direct-match",
              highlightedIndex === directMatchIndex
                ? "gsb__result-item--highlighted"
                : "",
            ]
              .filter(Boolean)
              .join(" ")}
            role="option"
            aria-selected={highlightedIndex === directMatchIndex}
            onClick={() => onSelect(directMatch.href)}
            tabIndex={-1}
            data-highlighted={
              highlightedIndex === directMatchIndex ? "true" : undefined
            }
          >
            <div className="gsb__result-info">
              <div className="gsb__result-title">{directMatch.title}</div>
              {directMatch.subtitle && (
                <div className="gsb__result-subtitle">{directMatch.subtitle}</div>
              )}
            </div>
            {directMatch.display_id && (
              <span className="gsb__result-badge">{directMatch.display_id}</span>
            )}
          </button>
        </>
      )}

      {/* Entity-grouped rows from combined */}
      {groupsWithIndex.map((group) => (
        <React.Fragment key={group.kind}>
          <div className="gsb__section-label">
            {KIND_LABEL[group.kind] ?? group.kind}
          </div>
          {group.items.map(({ item, index }) => {
            const isHighlighted = highlightedIndex === index;
            return (
              <button
                key={item.id}
                className={[
                  "gsb__result-item",
                  isHighlighted ? "gsb__result-item--highlighted" : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
                role="option"
                aria-selected={isHighlighted}
                onClick={() => onSelect(item.href)}
                tabIndex={-1}
                data-highlighted={isHighlighted ? "true" : undefined}
              >
                <div className="gsb__result-info">
                  <div className="gsb__result-title">{item.title}</div>
                  {item.subtitle && (
                    <div className="gsb__result-subtitle">{item.subtitle}</div>
                  )}
                </div>
                {item.display_id && (
                  <span className="gsb__result-badge">{item.display_id}</span>
                )}
              </button>
            );
          })}
        </React.Fragment>
      ))}

      {/* "View all" row — pinned bottom */}
      <button
        className={[
          "gsb__result-item",
          "gsb__result-item--view-all",
          highlightedIndex === viewAllIndex
            ? "gsb__result-item--highlighted"
            : "",
        ]
          .filter(Boolean)
          .join(" ")}
        role="option"
        aria-selected={highlightedIndex === viewAllIndex}
        onClick={() => onSelect(`/search?q=${encodeURIComponent(query)}`)}
        tabIndex={-1}
        data-highlighted={
          highlightedIndex === viewAllIndex ? "true" : undefined
        }
      >
        <span className="gsb__view-all-label">
          View all results for <strong>{query}</strong>
        </span>
      </button>
    </div>
  );
}

/**
 * Helper used by the parent component to compute total number of
 * selectable rows in the dropdown, for keyboard navigation bounds.
 *
 * Count = (1 if directMatch) + combined.length + 1 (View all).
 */
export function dropdownRowCount(
  directMatch: SearchItem | null,
  combined: SearchItem[],
): number {
  return (directMatch ? 1 : 0) + combined.length + 1;
}

/**
 * Helper used by the parent component to resolve the href for the
 * currently highlighted index.
 */
export function resolveHrefAtIndex(
  index: number,
  directMatch: SearchItem | null,
  combined: SearchItem[],
  query: string,
): string | null {
  let cursor = 0;
  if (directMatch) {
    if (index === cursor) return directMatch.href;
    cursor++;
  }
  for (const item of combined) {
    if (index === cursor) return item.href;
    cursor++;
  }
  // View all is the last row
  if (index === cursor) return `/search?q=${encodeURIComponent(query)}`;
  return null;
}
