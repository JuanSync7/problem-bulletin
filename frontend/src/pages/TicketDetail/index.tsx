/**
 * TicketDetail — standalone page for a single ticket at /tickets/:displayId.
 *
 * v2.3-WP21: real leaf route so deep-links open a focused view instead of
 * loading the full Kanban board. The drawer remains unchanged as the board's
 * inline inspector.
 *
 * v2.4-WP26: field grid extracted to TicketFields; activity feed added via
 * TicketActivityFeed (was deferred from WP21).
 *
 * v2.4-WP27: inline edit for status, priority, and assignee. Shape A —
 * TicketFields stays purely presentational; edit controls live in this page
 * component, mirroring the drawer's pattern exactly.
 */
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  getTicket,
  transitionTicket,
  updateTicket,
  assignTicket,
  type TicketDTO,
  type TicketStatus,
  type TicketPriority,
  ApiError,
} from "../../api/tickets";
import { TicketFields } from "../../components/TicketFields";
import { TicketActivityFeed } from "../../components/TicketActivityFeed";
import { renderMarkdown } from "../../components/MarkdownEditor";
import { PersonPicker } from "../../components/PersonPicker/index";
import type { PersonRef } from "../../api/people";
import "./TicketDetail.css";

const STATUS_LABEL: Record<string, string> = {
  backlog: "Backlog",
  todo: "To Do",
  in_progress: "In Progress",
  in_review: "In Review",
  blocked: "Blocked",
  done: "Done",
  cancelled: "Cancelled",
};

const PRIORITY_LABEL: Record<string, string> = {
  low: "Low",
  medium: "Medium",
  high: "High",
  urgent: "Urgent",
};

const STATUSES: TicketStatus[] = [
  "todo",
  "in_progress",
  "in_review",
  "blocked",
  "done",
  "cancelled",
];

const PRIORITIES: TicketPriority[] = ["low", "medium", "high", "urgent"];

export default function TicketDetail() {
  const { displayId } = useParams<{ displayId: string }>();
  const [ticket, setTicket] = useState<TicketDTO | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Mutation busy/error state — separate from the load error so the page body
  // stays rendered while a mutation is in flight.
  const [busy, setBusy] = useState(false);
  const [mutateError, setMutateError] = useState<string | null>(null);
  // assigneePerson tracks the currently-selected PersonRef for the picker.
  const [assigneePerson, setAssigneePerson] = useState<PersonRef | null>(null);
  // activityKey forces TicketActivityFeed to re-mount (and re-fetch) after a
  // successful mutation — same pattern as the drawer.
  const [activityKey, setActivityKey] = useState(0);

  useEffect(() => {
    if (!displayId) return;
    let cancelled = false;
    setLoading(true);
    setNotFound(false);
    setError(null);

    getTicket(displayId)
      .then((t) => {
        if (!cancelled) {
          setTicket(t);
          if (t.assignee_id) {
            setAssigneePerson({
              id: t.assignee_id as string,
              kind: ((t as TicketDTO & { assignee_type?: string }).assignee_type ?? "user") as "user" | "agent",
              display_name: (t.assignee_id as string).slice(0, 8),
            });
          } else {
            setAssigneePerson(null);
          }
        }
      })
      .catch((e) => {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 404) {
          setNotFound(true);
        } else {
          setError(e instanceof Error ? e.message : String(e));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [displayId]);

  const reportMutateError = (e: unknown) =>
    setMutateError(e instanceof Error ? e.message : String(e));

  const applyServerTicket = (t: TicketDTO) => {
    setTicket(t);
    if (t.assignee_id) {
      setAssigneePerson({
        id: t.assignee_id as string,
        kind: ((t as TicketDTO & { assignee_type?: string }).assignee_type ?? "user") as "user" | "agent",
        display_name: (t.assignee_id as string).slice(0, 8),
      });
    } else {
      setAssigneePerson(null);
    }
    // Bump activity feed so it re-fetches and reflects the new event.
    setActivityKey((k) => k + 1);
  };

  const onChangeStatus = async (next: TicketStatus) => {
    if (!ticket || ticket.status === next) return;
    setBusy(true);
    setMutateError(null);
    try {
      const updated = await transitionTicket(ticket.display_id || ticket.id, next);
      applyServerTicket(updated);
    } catch (e) {
      reportMutateError(e);
    } finally {
      setBusy(false);
    }
  };

  const onChangePriority = async (next: TicketPriority) => {
    if (!ticket || ticket.priority === next) return;
    setBusy(true);
    setMutateError(null);
    try {
      const updated = await updateTicket(ticket.display_id || ticket.id, {
        version: ticket.version,
        priority: next,
      });
      applyServerTicket(updated);
    } catch (e) {
      reportMutateError(e);
    } finally {
      setBusy(false);
    }
  };

  const onAssigneePick = async (person: PersonRef | null) => {
    if (!ticket) return;
    setAssigneePerson(person);
    setBusy(true);
    setMutateError(null);
    try {
      const updated = await assignTicket(ticket.display_id || ticket.id, {
        assignee_id: person?.id ?? null,
        assignee_type: person?.kind ?? null,
        expected_version: ticket.version,
      });
      applyServerTicket(updated);
    } catch (e) {
      reportMutateError(e);
      // Revert optimistic update.
      if (ticket.assignee_id) {
        setAssigneePerson({
          id: ticket.assignee_id as string,
          kind: ((ticket as TicketDTO & { assignee_type?: string }).assignee_type ?? "user") as "user" | "agent",
          display_name: (ticket.assignee_id as string).slice(0, 8),
        });
      } else {
        setAssigneePerson(null);
      }
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <div className="ticket-detail ticket-detail--loading" data-testid="ticket-detail-loading">
        <div className="ticket-detail__spinner" aria-label="Loading ticket" />
      </div>
    );
  }

  if (notFound) {
    return (
      <div className="ticket-detail ticket-detail--not-found" data-testid="ticket-detail-not-found">
        <h1>Ticket not found</h1>
        <p>
          <code>{displayId}</code> does not exist or you do not have access.
        </p>
        <Link to="/board" className="ticket-detail__back-link">
          Back to board
        </Link>
      </div>
    );
  }

  if (error) {
    return (
      <div className="ticket-detail ticket-detail--error" data-testid="ticket-detail-error">
        <h1>Something went wrong</h1>
        <p className="ticket-detail__error-msg" role="alert">{error}</p>
        <Link to="/board" className="ticket-detail__back-link">
          Back to board
        </Link>
      </div>
    );
  }

  if (!ticket) return null;

  const statusLabel = STATUS_LABEL[ticket.status] ?? ticket.status;
  const priorityLabel = ticket.priority ? (PRIORITY_LABEL[ticket.priority] ?? ticket.priority) : null;

  return (
    <div className="ticket-detail" data-testid="ticket-detail">
      <nav className="ticket-detail__breadcrumb">
        {ticket.project_key && (
          <Link to={`/board?project=${ticket.project_key}`} className="ticket-detail__back-link">
            {ticket.project_key}
          </Link>
        )}
        {!ticket.project_key && (
          <Link to="/board" className="ticket-detail__back-link">
            Board
          </Link>
        )}
        <span className="ticket-detail__breadcrumb-sep">/</span>
        <span>{ticket.display_id ?? displayId}</span>
      </nav>

      <header className="ticket-detail__header">
        <div className="ticket-detail__meta-row">
          <span
            className={`ticket-detail__status ticket-detail__status--${ticket.status}`}
            data-testid="ticket-status"
          >
            {statusLabel}
          </span>
          {priorityLabel && (
            <span
              className={`ticket-detail__priority ticket-detail__priority--${ticket.priority}`}
              data-testid="ticket-priority"
            >
              {priorityLabel}
            </span>
          )}
          {ticket.type && (
            <span className="ticket-detail__type" data-testid="ticket-type">
              {ticket.type}
            </span>
          )}
        </div>
        <h1 className="ticket-detail__title" data-testid="ticket-title">
          {ticket.title}
        </h1>
        <div className="ticket-detail__id" aria-label="Ticket ID">
          {ticket.display_id ?? displayId}
        </div>
      </header>

      {mutateError && (
        <div
          className="ticket-detail__mutate-error"
          role="alert"
          data-testid="ticket-mutate-error"
        >
          {mutateError}
        </div>
      )}

      <div className="ticket-detail__body">
        <div className="ticket-detail__main">
          {ticket.description ? (
            <section className="ticket-detail__description">
              <h2 className="ticket-detail__section-heading">Description</h2>
              {/* Rendered by TicketFields; keep the testid wrapper for existing test assertions */}
              <div
                className="ticket-detail__markdown"
                data-testid="ticket-description"
                dangerouslySetInnerHTML={{ __html: renderMarkdown(ticket.description) }}
              />
            </section>
          ) : (
            <section className="ticket-detail__description ticket-detail__description--empty">
              <p className="ticket-detail__empty-hint">No description provided.</p>
            </section>
          )}

          {/* Activity feed — added in v2.4-WP26 (was deferred from WP21) */}
          <section className="ticket-detail__activity" data-testid="ticket-detail-activity-section">
            <h2 className="ticket-detail__section-heading">Activity</h2>
            <TicketActivityFeed
              key={`${ticket.id}-${activityKey}`}
              ticketId={ticket.id}
              ticketDisplayId={ticket.display_id || ticket.id}
            />
          </section>
        </div>

        <aside className="ticket-detail__sidebar">
          {/* Read-only field grid — TicketFields stays presentational (Shape A). */}
          <TicketFields ticket={ticket} layout="page" />

          {/* Inline edit controls — mirroring the drawer's UI exactly. */}
          <div className="ticket-detail__edit-controls">
            <div className="ticket-detail__field">
              <label htmlFor="td-status-select">Status</label>
              <select
                id="td-status-select"
                data-testid="td-status-select"
                value={ticket.status}
                disabled={busy}
                onChange={(e) => onChangeStatus(e.target.value as TicketStatus)}
              >
                {STATUSES.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </div>

            <div className="ticket-detail__field">
              <label htmlFor="td-priority-select">Priority</label>
              <select
                id="td-priority-select"
                data-testid="td-priority-select"
                value={ticket.priority ?? "medium"}
                disabled={busy}
                onChange={(e) => onChangePriority(e.target.value as TicketPriority)}
              >
                {PRIORITIES.map((p) => (
                  <option key={p} value={p}>{p}</option>
                ))}
              </select>
            </div>

            <div className="ticket-detail__field">
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
          </div>
        </aside>
      </div>
    </div>
  );
}
