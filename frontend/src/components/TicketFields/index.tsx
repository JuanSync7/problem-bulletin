/**
 * TicketFields — presentational read-only field grid for a single ticket.
 *
 * v2.4-WP26: extracted from TicketDetailDrawer and TicketDetail page so both
 * surfaces share a single field renderer.
 *
 * Props:
 *   ticket  — the TicketDTO to display.
 *   layout  — "drawer" renders a vertical list; "page" renders a 2-column
 *             definition-list grid (matches the TicketDetail sidebar).
 *
 * No edit affordances — WP27 adds those.
 */
import React from "react";
import { renderMarkdown } from "../MarkdownEditor";
import type { TicketDTO } from "../../api/tickets";
import "./TicketFields.css";

const PRIORITY_LABEL: Record<string, string> = {
  low: "Low",
  medium: "Medium",
  high: "High",
  urgent: "Urgent",
};

const STATUS_LABEL: Record<string, string> = {
  backlog: "Backlog",
  todo: "To Do",
  in_progress: "In Progress",
  in_review: "In Review",
  blocked: "Blocked",
  done: "Done",
  cancelled: "Cancelled",
};

function fmt(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso ?? "";
  return d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export interface TicketFieldsProps {
  ticket: TicketDTO;
  layout?: "drawer" | "page";
}

/**
 * Row wrapper — adapts to drawer vs page layout automatically.
 *
 * In drawer mode it renders as a `div.ticket-fields__row` with stacked label/value.
 * In page mode it renders as a `<dt>` + `<dd>` pair (caller wraps in `<dl>`).
 */
function Row({
  label,
  children,
  layout,
  testId,
}: {
  label: string;
  children: React.ReactNode;
  layout: "drawer" | "page";
  testId?: string;
}) {
  if (layout === "drawer") {
    return (
      <div className="ticket-fields__row">
        <span className="ticket-fields__label">{label}</span>
        <span className="ticket-fields__value" data-testid={testId}>
          {children}
        </span>
      </div>
    );
  }
  return (
    <>
      <dt className="ticket-fields__label">{label}</dt>
      <dd className="ticket-fields__value" data-testid={testId}>
        {children}
      </dd>
    </>
  );
}

export function TicketFields({ ticket, layout = "page" }: TicketFieldsProps) {
  const statusLabel = STATUS_LABEL[ticket.status] ?? ticket.status;
  const priorityLabel = ticket.priority
    ? (PRIORITY_LABEL[ticket.priority] ?? ticket.priority)
    : null;

  const fields = (
    <>
      <Row label="Status" layout={layout} testId="tf-status">
        <span
          className={`ticket-fields__status ticket-fields__status--${ticket.status}`}
        >
          {statusLabel}
        </span>
      </Row>

      {priorityLabel && (
        <Row label="Priority" layout={layout} testId="tf-priority">
          <span
            className={`ticket-fields__priority ticket-fields__priority--${ticket.priority}`}
          >
            {priorityLabel}
          </span>
        </Row>
      )}

      <Row label="Assignee" layout={layout} testId="tf-assignee">
        {ticket.assignee_id ? (
          <>
            {String(ticket.assignee_id)}
            {ticket.assignee_type === "agent" && (
              <>
                {" "}
                <span
                  className="ticket-detail__assignee-badge--agent"
                  aria-label="agent"
                >
                  agent
                </span>
              </>
            )}
          </>
        ) : (
          <span className="ticket-fields__unset">Unassigned</span>
        )}
      </Row>

      {ticket.reporter_id && (
        <Row label="Reporter" layout={layout} testId="tf-reporter">
          {String(ticket.reporter_id)}
        </Row>
      )}

      {ticket.project_key && (
        <Row label="Project" layout={layout} testId="tf-project">
          {ticket.project_key}
        </Row>
      )}

      {ticket.story_points != null && (
        <Row label="Story points" layout={layout} testId="tf-story-points">
          {ticket.story_points}
        </Row>
      )}

      {ticket.due_date && (
        <Row label="Due date" layout={layout} testId="tf-due-date">
          {ticket.due_date}
        </Row>
      )}

      {ticket.labels && ticket.labels.length > 0 && (
        <Row label="Labels" layout={layout} testId="tf-labels">
          <ul className="ticket-fields__labels">
            {ticket.labels.map((l) => (
              <li key={l} className="ticket-fields__label-chip">
                {l}
              </li>
            ))}
          </ul>
        </Row>
      )}

      {ticket.created_at && (
        <Row label="Created" layout={layout} testId="tf-created">
          {fmt(ticket.created_at)}
        </Row>
      )}

      {ticket.updated_at && (
        <Row label="Updated" layout={layout} testId="tf-updated">
          {fmt(ticket.updated_at)}
        </Row>
      )}

      <Row label="Version" layout={layout} testId="tf-version">
        {ticket.version}
      </Row>

      {ticket.description && (
        <Row label="Description" layout={layout} testId="tf-description">
          <div
            className="ticket-fields__description"
            dangerouslySetInnerHTML={{ __html: renderMarkdown(ticket.description) }}
          />
        </Row>
      )}
    </>
  );

  if (layout === "drawer") {
    return (
      <div className="ticket-fields ticket-fields--drawer" data-testid="ticket-fields">
        {fields}
      </div>
    );
  }

  return (
    <dl className="ticket-fields ticket-fields--page" data-testid="ticket-fields">
      {fields}
    </dl>
  );
}
