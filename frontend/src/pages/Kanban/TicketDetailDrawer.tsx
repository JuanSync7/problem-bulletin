import { useEffect, useState } from "react";
import {
  addComment,
  assignTicket,
  getSubtree,
  getTicket,
  transitionTicket,
  updateTicket,
  type CommentDTO,
  type SubtreeRow,
  type TicketDTO,
  type TicketPriority,
  type TicketStatus,
} from "../../api/tickets";
import { MentionTextarea } from "../../components/MentionTextarea";
import { TicketFields } from "../../components/TicketFields";
import { TicketActivityFeed } from "../../components/TicketActivityFeed";
import { PersonPicker } from "../../components/PersonPicker/index";
import type { PersonRef } from "../../api/people";

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

interface TicketDetailDrawerProps {
  ticketKey: string | null;
  onClose: () => void;
  onChanged?: (ticket: TicketDTO) => void;
}

const STATUSES: TicketStatus[] = [
  "todo",
  "in_progress",
  "in_review",
  "blocked",
  "done",
  "cancelled",
];
const PRIORITIES: TicketPriority[] = ["low", "medium", "high", "urgent"];

export function TicketDetailDrawer({
  ticketKey,
  onClose,
  onChanged,
}: TicketDetailDrawerProps) {
  const [ticket, setTicket] = useState<TicketDTO | null>(null);
  const [children, setChildren] = useState<SubtreeRow[]>([]);
  const [childrenOpen, setChildrenOpen] = useState(false);
  const [comments, setComments] = useState<CommentDTO[]>([]);
  const [newComment, setNewComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [assigneePerson, setAssigneePerson] = useState<PersonRef | null>(null);
  // activityKey forces TicketActivityFeed to re-mount (and re-fetch) when we
  // post a new comment so the feed reflects the freshly added item.
  const [activityKey, setActivityKey] = useState(0);

  useEffect(() => {
    if (!ticketKey) {
      setTicket(null);
      setChildren([]);
      setComments([]);
      setError(null);
      return;
    }
    let cancelled = false;
    setBusy(true);
    setError(null);
    (async () => {
      try {
        const t = await getTicket(ticketKey);
        if (cancelled) return;
        setTicket(t);
        // Reconstruct a minimal PersonRef from the ticket DTO so the chip
        // shows immediately after load. Full display_name is not in the DTO —
        // we show the raw id until the user opens the picker.
        if (t.assignee_id) {
          setAssigneePerson({
            id: t.assignee_id as string,
            kind: ((t as TicketDTO & { assignee_type?: string }).assignee_type ?? "user") as "user" | "agent",
            display_name: (t.assignee_id as string).slice(0, 8),
          });
        } else {
          setAssigneePerson(null);
        }
        const maybeComments = (t.comments as CommentDTO[] | undefined) ?? [];
        setComments(maybeComments);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled) setBusy(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ticketKey]);

  const loadChildren = async () => {
    if (!ticket) return;
    setChildrenOpen((v) => !v);
    if (!childrenOpen && children.length === 0) {
      try {
        const res = await getSubtree(ticket.display_id || ticket.id, 3);
        // Drop the root itself (depth 0)
        setChildren(res.items.filter((r) => r.depth > 0));
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load children");
      }
    }
  };

  const reportError = (e: unknown) =>
    setError(e instanceof Error ? e.message : String(e));

  const applyServerTicket = (t: TicketDTO) => {
    setTicket(t);
    onChanged?.(t);
  };

  const onChangeStatus = async (next: TicketStatus) => {
    if (!ticket || ticket.status === next) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await transitionTicket(ticket.display_id || ticket.id, next);
      applyServerTicket(updated);
    } catch (e) {
      reportError(e);
    } finally {
      setBusy(false);
    }
  };

  const onChangePriority = async (next: TicketPriority) => {
    if (!ticket || ticket.priority === next) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await updateTicket(ticket.display_id || ticket.id, {
        version: ticket.version,
        priority: next,
      });
      applyServerTicket(updated);
    } catch (e) {
      reportError(e);
    } finally {
      setBusy(false);
    }
  };

  const onAssigneePick = async (person: PersonRef | null) => {
    if (!ticket) return;
    setAssigneePerson(person);
    setBusy(true);
    setError(null);
    try {
      const updated = await assignTicket(ticket.display_id || ticket.id, {
        assignee_id: person?.id ?? null,
        assignee_type: person?.kind ?? null,
        expected_version: ticket.version,
      });
      applyServerTicket(updated);
    } catch (e) {
      reportError(e);
      // Revert optimistic update.
      setAssigneePerson(
        ticket.assignee_id
          ? {
              id: ticket.assignee_id as string,
              kind: ((ticket as TicketDTO & { assignee_type?: string }).assignee_type ?? "user") as "user" | "agent",
              display_name: (ticket.assignee_id as string).slice(0, 8),
            }
          : null,
      );
    } finally {
      setBusy(false);
    }
  };

  const onAddComment = async () => {
    if (!ticket || !newComment.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const c = await addComment(ticket.display_id || ticket.id, newComment.trim());
      setComments((cs) => [...cs, c]);
      setNewComment("");
      // Re-mount TicketActivityFeed so it re-fetches and includes the new comment.
      setActivityKey((k) => k + 1);
    } catch (e) {
      reportError(e);
    } finally {
      setBusy(false);
    }
  };

  const open = ticketKey != null;

  return (
    <aside
      className={`ticket-drawer${open ? "" : " ticket-drawer--closed"}`}
      aria-hidden={!open}
    >
      <header className="ticket-drawer__header">
        <strong>{ticket?.display_id ?? ticketKey ?? ""}</strong>
        {ticket?.last_activity_at && (
          <span
            className="ticket-drawer__last-touched"
            data-testid="ticket-last-touched"
            title={ticket.last_activity_at}
            style={{ marginLeft: "0.5rem", opacity: 0.7, fontSize: "0.85em" }}
          >
            Last touched {_relative(ticket.last_activity_at)}
          </span>
        )}
        <button
          type="button"
          className="ticket-drawer__close"
          onClick={onClose}
          aria-label="Close drawer"
        >
          ×
        </button>
      </header>
      <div className="ticket-drawer__body">
        {error && <div className="ticket-drawer__error">{error}</div>}
        {!ticket && busy && <div>Loading…</div>}
        {ticket && (
          <>
            {/* Read-only field grid */}
            <TicketFields ticket={ticket} layout="drawer" />

            {/* Drawer-specific edit controls (status, priority, assignee, children) */}
            <div className="ticket-drawer__field">
              <label>Status</label>
              <select
                value={ticket.status}
                disabled={busy}
                onChange={(e) => onChangeStatus(e.target.value as TicketStatus)}
              >
                {STATUSES.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </div>

            <div className="ticket-drawer__field">
              <label>Priority</label>
              <select
                value={ticket.priority ?? "medium"}
                disabled={busy}
                onChange={(e) =>
                  onChangePriority(e.target.value as TicketPriority)
                }
              >
                {PRIORITIES.map((p) => (
                  <option key={p} value={p}>{p}</option>
                ))}
              </select>
            </div>

            <div className="ticket-drawer__field">
              <label>Assignee</label>
              <PersonPicker
                value={assigneePerson}
                onChange={onAssigneePick}
                kind="any"
                allowClear
                disabled={busy}
                placeholder="(unassigned)"
              />
            </div>

            <div className="ticket-drawer__field">
              <button
                type="button"
                className="kanban-page__btn"
                onClick={loadChildren}
              >
                {childrenOpen ? "Hide" : "Show"} children
              </button>
              {childrenOpen && (
                <ul style={{ listStyle: "none", padding: 0, margin: "0.5rem 0" }}>
                  {children.length === 0 && (
                    <li className="ticket-drawer__comment-meta">
                      No child tickets.
                    </li>
                  )}
                  {children.map((row) => (
                    <li
                      key={row.ticket.id}
                      style={{ paddingLeft: `${(row.depth - 1) * 12}px` }}
                    >
                      <span className="hierarchy-tree__key">
                        {row.ticket.display_id ?? row.ticket.id.slice(0, 8)}
                      </span>{" "}
                      {row.ticket.title}{" "}
                      <span className="status-badge">{row.ticket.status}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {/* Activity feed — extracted component */}
            <div className="ticket-drawer__field">
              <label>Activity</label>
              <div className="ticket-drawer__activity">
                <TicketActivityFeed
                  key={`${ticket.id}-${activityKey}`}
                  ticketId={ticket.id}
                  ticketDisplayId={ticket.display_id || ticket.id}
                />
              </div>
            </div>

            {/* Comments */}
            <div className="ticket-drawer__field">
              <label>Comments</label>
              <div className="ticket-drawer__comments">
                {comments.length === 0 && (
                  <div className="ticket-drawer__comment-meta">No comments yet.</div>
                )}
                {comments.map((c) => {
                  const agent = c.author_type === "agent";
                  const stepId = (c as { agent_step_id?: string | null })
                    .agent_step_id;
                  return (
                    <div key={c.id} className="ticket-drawer__comment">
                      <div className="ticket-drawer__comment-meta">
                        <span
                          className={`actor-badge actor-badge--${agent ? "agent" : "user"}`}
                          data-testid="comment-actor-badge"
                        >
                          {agent ? "🤖 agent" : "👤 user"}
                        </span>
                        {" "}
                        {c.author_id?.slice(0, 8)}
                        {stepId && (
                          <code
                            className="ticket-drawer__step-id"
                            title="agent_step_id"
                          >
                            {stepId}
                          </code>
                        )}
                        {" · "}
                        {c.created_at ?? ""}
                      </div>
                      <div style={{ whiteSpace: "pre-wrap" }}>{c.body}</div>
                    </div>
                  );
                })}
              </div>
              <MentionTextarea
                rows={2}
                placeholder="Add a comment…"
                value={newComment}
                onChange={setNewComment}
                projectId={ticket.project_id ?? null}
                ariaLabel="Add a comment"
              />
              <button
                type="button"
                className="kanban-page__btn kanban-page__btn--primary"
                onClick={onAddComment}
                disabled={busy || !newComment.trim()}
                style={{ alignSelf: "flex-start", marginTop: "0.25rem" }}
              >
                Post comment
              </button>
            </div>
          </>
        )}
      </div>
    </aside>
  );
}
