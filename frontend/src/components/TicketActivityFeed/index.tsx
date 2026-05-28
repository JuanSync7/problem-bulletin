/**
 * TicketActivityFeed — merged activity timeline for a ticket.
 *
 * v2.4-WP26: extracted from TicketDetailDrawer so the TicketDetail page can
 * share the same feed without duplicating the fetch / pagination logic.
 *
 * Props:
 *   ticketId        — UUID of the ticket (used only as a stable React key).
 *   ticketDisplayId — display id (e.g. "DEF-7") passed to listActivity.
 *
 * Renders: transitions, comments, link events in chronological order.
 * Supports cursor-based "Load more" (same pattern as MentionsTab).
 */
import React, { useEffect, useState, useCallback } from "react";
import {
  listActivity,
  type ActivityItem,
} from "../../api/tickets";

function _relative(iso: string | null | undefined): string {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return iso ?? "";
  const dsec = Math.max(0, (Date.now() - t) / 1000);
  if (dsec < 60) return `${Math.floor(dsec)}s ago`;
  if (dsec < 3600) return `${Math.floor(dsec / 60)}m ago`;
  if (dsec < 86400) return `${Math.floor(dsec / 3600)}h ago`;
  return `${Math.floor(dsec / 86400)}d ago`;
}

export interface TicketActivityFeedProps {
  /** UUID of the ticket — used as a stable key so the feed resets on navigation. */
  ticketId: string;
  /** Display id (e.g. "DEF-7") passed as idOrKey to listActivity. */
  ticketDisplayId: string;
}

export function TicketActivityFeed({
  ticketId,
  ticketDisplayId,
}: TicketActivityFeedProps) {
  const [items, setItems] = useState<ActivityItem[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchPage = useCallback(
    async (cursor?: string) => {
      const isMore = cursor != null;
      if (isMore) {
        setLoadingMore(true);
      } else {
        setLoading(true);
        setError(null);
      }
      try {
        const page = await listActivity(ticketDisplayId || ticketId, {
          include: ["comments", "links"],
          limit: 100,
          ...(cursor != null ? { cursor } : {}),
        });
        setItems((prev) => (isMore ? [...prev, ...page.items] : page.items));
        setNextCursor(page.next_cursor);
      } catch (e) {
        if (!isMore) {
          setError(e instanceof Error ? e.message : String(e));
        }
        // load-more failures are silent (non-blocking, same as drawer)
      } finally {
        if (isMore) {
          setLoadingMore(false);
        } else {
          setLoading(false);
        }
      }
    },
    // ticketDisplayId changes when a different ticket is opened
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [ticketDisplayId, ticketId],
  );

  useEffect(() => {
    setItems([]);
    setNextCursor(null);
    void fetchPage();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticketDisplayId, ticketId]);

  const handleLoadMore = () => {
    if (nextCursor && !loadingMore) {
      void fetchPage(nextCursor);
    }
  };

  if (loading) {
    return (
      <div
        className="ticket-activity-feed ticket-activity-feed--loading"
        data-testid="activity-feed-loading"
      >
        Loading activity…
      </div>
    );
  }

  if (error) {
    return (
      <div
        className="ticket-activity-feed ticket-activity-feed--error"
        data-testid="activity-feed-error"
        role="alert"
      >
        {error}
      </div>
    );
  }

  return (
    <div className="ticket-activity-feed" data-testid="ticket-activity">
      {items.length === 0 && (
        <div
          className="ticket-drawer__comment-meta"
          data-testid="activity-feed-empty"
        >
          No activity yet.
        </div>
      )}

      {items.map((row) => {
        const isAgent = row.actor_type === "agent";
        const actorBadge = (
          <span
            className={`actor-badge actor-badge--${isAgent ? "agent" : "user"}`}
          >
            {isAgent ? "🤖 agent" : "👤 user"}
          </span>
        );
        const stepChip = row.agent_step_id ? (
          <code
            className="ticket-drawer__step-id"
            data-testid="activity-step-id"
            title="agent_step_id"
          >
            {row.agent_step_id}
          </code>
        ) : null;
        const when = (
          <span title={row.created_at}>{_relative(row.created_at)}</span>
        );

        if (row.kind === "transition") {
          return (
            <div
              key={`tr-${row.id}`}
              className="ticket-drawer__activity-row"
              data-testid="activity-transition"
            >
              <div className="ticket-drawer__comment-meta">
                {actorBadge}
                {" moved this from "}
                <em>{row.from_status ?? "—"}</em>
                {" to "}
                <em>{row.to_status}</em>
                {stepChip}
                {" · "}
                {when}
              </div>
              {row.reason && (
                <div style={{ whiteSpace: "pre-wrap" }}>{row.reason}</div>
              )}
            </div>
          );
        }

        if (row.kind === "comment") {
          return (
            <div
              key={`c-${row.id}`}
              className="ticket-drawer__activity-row"
              data-testid="activity-comment"
            >
              <div className="ticket-drawer__comment-meta">
                {actorBadge}
                {" "}
                {row.actor_id?.slice(0, 8)}
                {stepChip}
                {" · "}
                {when}
              </div>
              <div style={{ whiteSpace: "pre-wrap" }}>{row.body}</div>
            </div>
          );
        }

        // link row
        return (
          <div
            key={`l-${row.id}`}
            className="ticket-drawer__activity-row"
            data-testid="activity-link"
          >
            <div className="ticket-drawer__comment-meta">
              {actorBadge}
              {" linked to "}
              <code>{row.target_ticket_id.slice(0, 8)}</code>
              {" as "}
              <em>{row.link_type}</em>
              {stepChip}
              {" · "}
              {when}
            </div>
          </div>
        );
      })}

      {nextCursor && (
        <button
          type="button"
          className="kanban-page__btn"
          onClick={handleLoadMore}
          disabled={loadingMore}
          data-testid="activity-load-more"
          style={{ marginTop: "0.5rem" }}
        >
          {loadingMore ? "Loading…" : "Load more"}
        </button>
      )}
    </div>
  );
}
