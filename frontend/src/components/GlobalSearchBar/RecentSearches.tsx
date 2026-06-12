/**
 * A4: RecentSearches — displays recent search entries when the input is
 * focused and empty.
 *
 * Pure component: receives `recents` and `onSelect` props.
 * Renders at most 5 entries (the hook already caps at 5, but we guard here
 * too for safety).
 */

export interface RecentSearchesProps {
  recents: string[];
  onSelect: (query: string) => void;
}

export function RecentSearches({ recents, onSelect }: RecentSearchesProps) {
  const visible = recents.slice(0, 5);
  if (visible.length === 0) return null;

  return (
    <div className="gsb__recents" role="group" aria-label="Recent searches">
      <div className="gsb__section-label">Recent searches</div>
      {visible.map((q) => (
        <button
          key={q}
          className="gsb__result-item gsb__result-item--recent"
          role="option"
          aria-selected={false}
          tabIndex={-1}
          onClick={() => onSelect(q)}
        >
          <span className="gsb__recent-icon" aria-hidden="true">
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <polyline points="1 4 1 10 7 10" />
              <path d="M3.51 15a9 9 0 1 0 .49-4.95" />
            </svg>
          </span>
          <span className="gsb__recent-text">{q}</span>
        </button>
      ))}
    </div>
  );
}
