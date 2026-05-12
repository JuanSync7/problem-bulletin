import React, { useEffect, useState } from "react";
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
const PRIORITIES: TicketPriority[] = ["lowest", "low", "medium", "high", "highest"];

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
  const [assigneeInput, setAssigneeInput] = useState("");

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
        setAssigneeInput((t.assignee_id as string) ?? "");
        // Comments + transition history are exposed via ticket detail in
        // future iterations; for now pull them off the dict if present.
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
        const res = await getSubtree(ticket.key || ticket.id, 3);
        // Drop the root itself (depth 0)
        setChildren(res.items.filter((r) => r.depth > 0));
      } catch {
        /* ignore */
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
      const updated = await transitionTicket(ticket.key || ticket.id, next);
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
      const updated = await updateTicket(ticket.key || ticket.id, {
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

  const onSaveAssignee = async () => {
    if (!ticket) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await assignTicket(ticket.key || ticket.id, {
        assignee_id: assigneeInput || null,
        assignee_type: assigneeInput ? "user" : null,
        expected_version: ticket.version,
      });
      applyServerTicket(updated);
    } catch (e) {
      reportError(e);
    } finally {
      setBusy(false);
    }
  };

  const onAddComment = async () => {
    if (!ticket || !newComment.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const c = await addComment(ticket.key || ticket.id, newComment.trim());
      setComments((cs) => [...cs, c]);
      setNewComment("");
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
        <strong>{ticket?.key ?? ticketKey ?? ""}</strong>
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
            <div className="ticket-drawer__field">
              <label>Title</label>
              <div>{ticket.title}</div>
            </div>
            {ticket.description && (
              <div className="ticket-drawer__field">
                <label>Description</label>
                <div style={{ whiteSpace: "pre-wrap" }}>{ticket.description}</div>
              </div>
            )}

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
              <label>Assignee (user id)</label>
              <div style={{ display: "flex", gap: "0.5rem" }}>
                <input
                  type="text"
                  value={assigneeInput}
                  onChange={(e) => setAssigneeInput(e.target.value)}
                  placeholder="(unassigned)"
                  style={{ flex: 1 }}
                />
                <button
                  type="button"
                  className="kanban-page__btn"
                  onClick={onSaveAssignee}
                  disabled={busy}
                >
                  Save
                </button>
              </div>
            </div>

            <div className="ticket-drawer__field">
              <label>Story points</label>
              <div>{ticket.story_points ?? "—"}</div>
            </div>

            <div className="ticket-drawer__field">
              <label>Version</label>
              <div>{ticket.version}</div>
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
                        {row.ticket.key ?? row.ticket.id.slice(0, 8)}
                      </span>{" "}
                      {row.ticket.title}{" "}
                      <span className="status-badge">{row.ticket.status}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className="ticket-drawer__field">
              <label>Comments</label>
              <div className="ticket-drawer__comments">
                {comments.length === 0 && (
                  <div className="ticket-drawer__comment-meta">No comments yet.</div>
                )}
                {comments.map((c) => (
                  <div key={c.id} className="ticket-drawer__comment">
                    <div className="ticket-drawer__comment-meta">
                      {c.author_type}:{c.author_id?.slice(0, 8)} ·{" "}
                      {c.created_at ?? ""}
                    </div>
                    <div style={{ whiteSpace: "pre-wrap" }}>{c.body}</div>
                  </div>
                ))}
              </div>
              <textarea
                rows={2}
                placeholder="Add a comment…"
                value={newComment}
                onChange={(e) => setNewComment(e.target.value)}
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
