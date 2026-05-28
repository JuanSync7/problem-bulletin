/**
 * MineTab — list of tickets assigned to the current user, inside /activity (WP23).
 *
 * Pull-based only; no realtime. Renders a list with All/Open-only toggle
 * (default: Open only — excludes terminal statuses "done" and "cancelled"),
 * "Load more" for cursor pagination, and row-click navigation to the ticket
 * detail page.
 *
 * Uses `assignee_id: "me"` which the backend resolves to the authenticated
 * user's UUID — no need to pass a raw UUID from useAuth.
 *
 * Order: last_activity_at (most-recently-touched first, per WP22).
 */
import React from "react";
import { useNavigate } from "react-router-dom";
import {
  listTickets,
  type TicketDTO,
  type TicketStatus,
} from "../../api/tickets";
import { useAuth } from "../../hooks/useAuth";

type ViewFilter = "open" | "all";

/** Terminal statuses — must match app/enums.py TERMINAL_STATUSES. */
const TERMINAL_STATUSES: TicketStatus[] = ["done", "cancelled"];

/** All non-terminal statuses — used for the "Open only" filter. */
const OPEN_STATUSES: TicketStatus[] = [
  "backlog",
  "todo",
  "in_progress",
  "in_review",
  "blocked",
];

function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const diff = (Date.now() - t) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  const days = Math.floor(diff / 86400);
  if (days < 30) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

function statusLabel(s: TicketStatus): string {
  return s.replace(/_/g, " ");
}

export default function MineTab() {
  const navigate = useNavigate();
  const { user, isLoading: authLoading } = useAuth();

  const [filter, setFilter] = React.useState<ViewFilter>("open");
  const [items, setItems] = React.useState<TicketDTO[]>([]);
  const [nextCursor, setNextCursor] = React.useState<string | null>(null);
  const [total, setTotal] = React.useState<number | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const load = React.useCallback(
    async (mode: "initial" | "more") => {
      setLoading(true);
      setError(null);
      try {
        const page = await listTickets({
          assignee_id: "me",
          status: filter === "open" ? OPEN_STATUSES : undefined,
          order_by: "last_activity_at",
          limit: 50,
          cursor: mode === "more" ? nextCursor : null,
        });
        setItems((prev) =>
          mode === "more" ? [...prev, ...page.items] : page.items,
        );
        setNextCursor(page.next_cursor);
        setTotal(page.total);
      } catch (e) {
        setError((e as Error).message || "Failed to load");
      } finally {
        setLoading(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [filter, nextCursor],
  );

  // Reload when filter changes.
  React.useEffect(() => {
    if (authLoading) return;
    setNextCursor(null);
    void load("initial");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter, authLoading]);

  if (authLoading) {
    return (
      <div className="mine" data-testid="mine-tab">
        <div className="mine-loading" aria-live="polite">
          Loading…
        </div>
      </div>
    );
  }

  function handleRowClick(ticket: TicketDTO) {
    const target = ticket.display_id ?? ticket.id;
    navigate(`/tickets/${encodeURIComponent(target)}`);
  }

  return (
    <div className="mine" data-testid="mine-tab">
      <div className="mentions-header">
        <div className="mentions-header__title">
          <span>My tickets</span>
          {total !== null && total > 0 && (
            <span className="mentions-chip" aria-label="ticket count">
              {total}
            </span>
          )}
        </div>
        <div className="mentions-header__actions">
          <div className="mentions-toggle" role="tablist" aria-label="Filter">
            <button
              type="button"
              role="tab"
              aria-selected={filter === "all"}
              className={`mentions-toggle__btn${filter === "all" ? " mentions-toggle__btn--active" : ""}`}
              onClick={() => setFilter("all")}
            >
              All
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={filter === "open"}
              className={`mentions-toggle__btn${filter === "open" ? " mentions-toggle__btn--active" : ""}`}
              onClick={() => setFilter("open")}
            >
              Open only
            </button>
          </div>
        </div>
      </div>

      {error && (
        <div className="mentions-error" role="alert">
          {error}
        </div>
      )}

      {!loading && items.length === 0 && !error && (
        <div className="mentions-empty" data-testid="mine-empty">
          <p>No tickets assigned to you.</p>
          <p className="mentions-empty__help">
            {filter === "open"
              ? 'Switch to "All" to see closed tickets too.'
              : "Ask your team lead to assign you a ticket."}
          </p>
        </div>
      )}

      <ul className="mentions-list">
        {items.map((ticket) => {
          const timestamp =
            ticket.last_activity_at ?? ticket.created_at ?? null;
          const isTerminal = TERMINAL_STATUSES.includes(
            ticket.status as TicketStatus,
          );
          return (
            <li
              key={ticket.id}
              className={`mentions-row${isTerminal ? " mentions-row--terminal" : ""}`}
              data-testid="mine-row"
              data-id={ticket.id}
              data-display-id={ticket.display_id}
            >
              <button
                type="button"
                className="mentions-row__btn"
                onClick={() => handleRowClick(ticket)}
              >
                <span className="mine-row__display-id">
                  {ticket.display_id ?? ticket.id}
                </span>
                <span className="mine-row__title"> {ticket.title}</span>
                <span className={`mine-row__status mine-row__status--${ticket.status}`}>
                  {" "}· {statusLabel(ticket.status as TicketStatus)}
                </span>
                {ticket.priority && (
                  <span className={`mine-row__priority mine-row__priority--${ticket.priority}`}>
                    {" "}· {ticket.priority}
                  </span>
                )}
                {ticket.project_key && (
                  <span className="mine-row__project">
                    {" "}· {ticket.project_key}
                  </span>
                )}
                <span className="mentions-row__time">
                  {" "}· {relativeTime(timestamp)}
                </span>
              </button>
            </li>
          );
        })}
      </ul>

      {nextCursor && (
        <div className="mentions-more">
          <button
            type="button"
            onClick={() => void load("more")}
            disabled={loading}
          >
            {loading ? "Loading…" : "Load more"}
          </button>
        </div>
      )}

      {total !== null && (
        <div className="mentions-total" aria-hidden="true">
          {total} total
        </div>
      )}
    </div>
  );
}
