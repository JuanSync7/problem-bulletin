/**
 * MentionsTab — ticket-notification inbox embedded inside /activity (WP14).
 *
 * v2.3-WP25 additions:
 *  - Per-kind rendering: ticket_mention / ticket_assigned / ticket_state_change.
 *  - Me / My agents toggle (recipient_kind param). "My agents" is disabled when
 *    no agent accounts are linked (hasAgentAccounts prop).
 *
 * Pull-based only; no realtime. Renders a list with All/Unread toggle,
 * "Mark all read" affordance, optimistic per-row mark-read on click,
 * and "Load more" for cursor pagination.
 */
import React from "react";
import { useNavigate } from "react-router-dom";
import {
  listNotifications,
  markRead,
  markAllRead,
  type TicketNotification,
} from "../../api/notifications";
import { useRealtimeNotifications } from "../../realtime/useRealtimeNotifications";
import type { RealtimePayload } from "../../realtime/useRealtimeNotifications";

type Filter = "all" | "unread";
type RecipientKind = "user" | "agent";

function relativeTime(iso: string): string {
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

/** V2b — visually-distinct chip for human_review rows. */
function HumanReviewBadge(): React.ReactElement {
  return (
    <span
      className="mentions-row__badge mentions-row__badge--human-review"
      data-testid="human-review-chip"
      aria-label="Human review"
    >
      Human review
    </span>
  );
}

/** V4c — chip for ``agent_invoked_in_comment`` rows.  Renders the
 * owner-facing label "Your agent was invoked in a comment".  The
 * surrounding row's click target navigates to the ticket
 * (``target_display_id``) so the owner can step into the thread; the
 * originating comment id lives on ``comment_id`` for future deep-link
 * upgrades.
 */
function AgentInvokedInCommentBadge(): React.ReactElement {
  return (
    <span
      className="mentions-row__badge mentions-row__badge--agent-invoked"
      data-testid="agent-invoked-chip"
      aria-label="Your agent was invoked in a comment"
    >
      Your agent was invoked in a comment
    </span>
  );
}

/** Return the human-readable verb + target fragment for a notification row. */
function renderKindLabel(n: TicketNotification): React.ReactNode {
  const displayId = n.target_display_id ?? "(ticket)";
  switch (n.kind) {
    case "human_review":
      return (
        <>
          <HumanReviewBadge />
          <span className="mentions-row__verb"> requested your review on </span>
          <span className="mentions-row__target">{displayId}</span>
          {n.excerpt && (
            <span className="mentions-row__excerpt">
              {" "}
              — <em>{n.excerpt}</em>
            </span>
          )}
        </>
      );
    case "ticket_mention":
      return (
        <>
          <span className="mentions-row__verb"> mentioned you in </span>
          <span className="mentions-row__target">{displayId}</span>
        </>
      );
    case "agent_invoked_in_comment":
      return (
        <>
          <AgentInvokedInCommentBadge />
          <span className="mentions-row__verb"> · </span>
          <span className="mentions-row__target">{displayId}</span>
        </>
      );
    case "ticket_assigned":
      return (
        <>
          <span className="mentions-row__verb"> assigned to you · </span>
          <span className="mentions-row__target">{displayId}</span>
          {n.excerpt && (
            <span className="mentions-row__excerpt">
              {" "}
              — <em>{n.excerpt}</em>
            </span>
          )}
        </>
      );
    case "ticket_state_change":
      return (
        <>
          <span className="mentions-row__verb"> status: </span>
          <span className="mentions-row__target">
            {n.excerpt ?? "changed"}
          </span>
          <span className="mentions-row__verb"> · </span>
          <span className="mentions-row__target">{displayId}</span>
        </>
      );
    case "ticket_watcher_added":
      return (
        <>
          <span className="mentions-row__badge mentions-row__badge--watcher"> Watching</span>
          <span className="mentions-row__verb"> · </span>
          <span className="mentions-row__target">{displayId}</span>
          {n.excerpt && (
            <span className="mentions-row__excerpt">
              {" "}
              — <em>{n.excerpt}</em>
            </span>
          )}
        </>
      );
    case "ticket_blocked":
      return (
        <>
          <span className="mentions-row__verb"> Blocked · </span>
          <span className="mentions-row__target">{displayId}</span>
          <span className="mentions-row__badge mentions-row__badge--blocked"> blocked</span>
        </>
      );
    case "ticket_resolved":
      return (
        <>
          <span className="mentions-row__badge mentions-row__badge--resolved"> Resolved</span>
          <span className="mentions-row__verb"> · </span>
          <span className="mentions-row__target">{displayId}</span>
          {n.excerpt && (
            <span className="mentions-row__excerpt">
              {" "}
              — <em>{n.excerpt}</em>
            </span>
          )}
        </>
      );
    case "ticket_cancelled":
      return (
        <>
          <span className="mentions-row__badge mentions-row__badge--cancelled"> Cancelled</span>
          <span className="mentions-row__verb"> · </span>
          <span className="mentions-row__target">{displayId}</span>
          {n.excerpt && (
            <span className="mentions-row__excerpt">
              {" "}
              — <em>{n.excerpt}</em>
            </span>
          )}
        </>
      );
    case "ticket_due_soon":
      return (
        <>
          <span className="mentions-row__badge mentions-row__badge--warning"> Due soon</span>
          <span className="mentions-row__verb"> · </span>
          <span className="mentions-row__target">{displayId}</span>
          {n.excerpt && (
            <span className="mentions-row__excerpt">
              {" "}
              — <em>{n.excerpt}</em>
            </span>
          )}
        </>
      );
    default:
      return (
        <>
          <span className="mentions-row__verb"> activity on </span>
          <span className="mentions-row__target">{displayId}</span>
        </>
      );
  }
}

interface MentionsTabProps {
  /** Set to true when the caller has at least one agent account. */
  hasAgentAccounts?: boolean;
}

export default function MentionsTab({ hasAgentAccounts = false }: MentionsTabProps) {
  const navigate = useNavigate();
  const [filter, setFilter] = React.useState<Filter>("unread");
  const [recipientKind, setRecipientKind] = React.useState<RecipientKind>("user");
  const [items, setItems] = React.useState<TicketNotification[]>([]);
  const [nextCursor, setNextCursor] = React.useState<string | null>(null);
  const [total, setTotal] = React.useState<number | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const unreadInList = React.useMemo(
    () => items.filter((i) => !i.is_read).length,
    [items],
  );

  // v2.4-WP31: realtime WS — prepend new notifications while tab is mounted.
  const handleRealtimePayload = React.useCallback((payload: RealtimePayload) => {
    if (payload.type !== "ticket_notification") return;
    // Only prepend when showing unread (or all) for the current recipient kind.
    // We can't fully reconstruct the row without a server fetch, so we create
    // a minimal optimistic row for prepending. The real row will be fetched on
    // the next tab visit.
    const stub: TicketNotification = {
      id: typeof payload.id === "string" ? payload.id : `rt-${Date.now()}`,
      kind: typeof payload.kind === "string" ? payload.kind : "ticket_notification",
      recipient_type: "user",
      recipient_id: "",
      actor: {
        kind: "user",
        id: "",
        display_name: "…",
        handle: null,
        email: null,
        avatar_url: null,
      },
      target_type: "ticket",
      target_id: "",
      target_display_id:
        typeof payload.target_display_id === "string"
          ? payload.target_display_id
          : null,
      comment_id: null,
      excerpt: null,
      is_read: false,
      created_at:
        typeof payload.created_at === "string"
          ? payload.created_at
          : new Date().toISOString(),
    };
    setItems((prev) => [stub, ...prev]);
    setTotal((prev) => (prev !== null ? prev + 1 : null));
  }, []);

  useRealtimeNotifications(handleRealtimePayload);

  const load = React.useCallback(
    async (mode: "initial" | "more") => {
      setLoading(true);
      setError(null);
      try {
        const page = await listNotifications({
          only_unread: filter === "unread",
          cursor: mode === "more" ? nextCursor : null,
          limit: 50,
          recipient_kind: recipientKind,
        });
        setItems((prev) => (mode === "more" ? [...prev, ...page.items] : page.items));
        setNextCursor(page.next_cursor);
        setTotal(page.total);
      } catch (e) {
        setError((e as Error).message || "Failed to load");
      } finally {
        setLoading(false);
      }
    },
    [filter, nextCursor, recipientKind],
  );

  // Reload when filter or recipient kind changes.
  React.useEffect(() => {
    setNextCursor(null);
    void load("initial");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter, recipientKind]);

  async function handleRowClick(n: TicketNotification) {
    // Optimistic flip.
    if (!n.is_read) {
      setItems((prev) =>
        prev.map((x) => (x.id === n.id ? { ...x, is_read: true } : x)),
      );
      try {
        await markRead(n.id);
      } catch {
        // Roll back on failure.
        setItems((prev) =>
          prev.map((x) => (x.id === n.id ? { ...x, is_read: false } : x)),
        );
      }
    }
    const target = n.target_display_id ?? n.target_id;
    navigate(`/tickets/${encodeURIComponent(target)}`);
  }

  async function handleMarkAll() {
    try {
      await markAllRead();
      setItems((prev) => prev.map((x) => ({ ...x, is_read: true })));
    } catch (e) {
      setError((e as Error).message || "Failed");
    }
  }

  return (
    <div className="mentions" data-testid="mentions-tab">
      <div className="mentions-header">
        <div className="mentions-header__title">
          <span>Mentions</span>
          {unreadInList > 0 && (
            <span className="mentions-chip" aria-label="unread count">
              {unreadInList}
            </span>
          )}
        </div>
        <div className="mentions-header__actions">
          {/* Me / My agents toggle */}
          <div className="mentions-toggle" role="tablist" aria-label="Recipient">
            <button
              type="button"
              role="tab"
              aria-selected={recipientKind === "user"}
              className={`mentions-toggle__btn${recipientKind === "user" ? " mentions-toggle__btn--active" : ""}`}
              onClick={() => setRecipientKind("user")}
            >
              Me
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={recipientKind === "agent"}
              disabled={!hasAgentAccounts}
              title={hasAgentAccounts ? undefined : "No agent accounts linked"}
              className={`mentions-toggle__btn${recipientKind === "agent" ? " mentions-toggle__btn--active" : ""}`}
              onClick={() => {
                if (hasAgentAccounts) setRecipientKind("agent");
              }}
            >
              My agents
            </button>
          </div>

          {/* All / Unread filter */}
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
              aria-selected={filter === "unread"}
              className={`mentions-toggle__btn${filter === "unread" ? " mentions-toggle__btn--active" : ""}`}
              onClick={() => setFilter("unread")}
            >
              Unread
            </button>
          </div>
          <button
            type="button"
            className="mentions-mark-all"
            disabled={unreadInList === 0}
            onClick={handleMarkAll}
          >
            Mark all read
          </button>
        </div>
      </div>

      {error && (
        <div className="mentions-error" role="alert">
          {error}
        </div>
      )}

      {!loading && items.length === 0 && !error && (
        <div className="mentions-empty" data-testid="mentions-empty">
          No mentions yet.
        </div>
      )}

      <ul className="mentions-list">
        {items.map((n) => (
          <li
            key={n.id}
            className={`mentions-row${n.is_read ? "" : " mentions-row--unread"}`}
            data-testid="mentions-row"
            data-id={n.id}
            data-unread={!n.is_read}
          >
            <button
              type="button"
              className="mentions-row__btn"
              onClick={() => handleRowClick(n)}
            >
              <span className="mentions-row__actor">
                {n.actor.display_name}
              </span>
              {renderKindLabel(n)}
              <span className="mentions-row__time">
                {" "}· {relativeTime(n.created_at)}
              </span>
              {n.kind === "ticket_mention" && n.excerpt && (
                <span className="mentions-row__excerpt"> — <em>{n.excerpt}</em></span>
              )}
            </button>
          </li>
        ))}
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
