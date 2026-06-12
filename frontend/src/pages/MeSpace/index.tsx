/**
 * MeSpacePage — /me 4-tab personal dashboard (V3a).
 *
 * Tabs: Assigned tickets · Assigned problems · Mentions · My agent runs.
 * One on-mount fetch via ``getMyInbox()`` populates all four panes plus
 * the count badges. Tab switching is purely client-side — no re-fetch.
 */
import React from "react";
import { Link } from "react-router-dom";
import {
  getMyInbox,
  type MyInbox,
  type AssignedTicket,
  type AssignedProblem,
  type MentionItem,
  type AgentRunItem,
} from "../../api/me";
import "./MeSpace.css";

type TabKey =
  | "assigned_tickets"
  | "assigned_problems"
  | "mentions"
  | "my_agent_runs";

const TABS: { key: TabKey; label: string }[] = [
  { key: "assigned_tickets", label: "Assigned tickets" },
  { key: "assigned_problems", label: "Assigned problems" },
  { key: "mentions", label: "Mentions" },
  { key: "my_agent_runs", label: "My agent runs" },
];

function TicketsList({ items }: { items: AssignedTicket[] }) {
  if (items.length === 0) {
    return <div className="mespace-empty">No tickets assigned to you.</div>;
  }
  return (
    <ul className="mespace-list" data-testid="list-assigned_tickets">
      {items.map((t) => (
        <li key={t.id} className="mespace-list__row" data-id={t.id}>
          <Link to={`/tickets/${encodeURIComponent(t.display_id)}`}>
            <strong>{t.display_id}</strong> {t.title}
          </Link>
          <span> · {t.status}</span>
        </li>
      ))}
    </ul>
  );
}

function ProblemsList({ items }: { items: AssignedProblem[] }) {
  if (items.length === 0) {
    return <div className="mespace-empty">No problems assigned to you.</div>;
  }
  return (
    <ul className="mespace-list" data-testid="list-assigned_problems">
      {items.map((p) => (
        <li key={p.id} className="mespace-list__row" data-id={p.id}>
          <Link to={`/problems/${encodeURIComponent(p.id)}`}>{p.title}</Link>
          <span> · {p.status}</span>
        </li>
      ))}
    </ul>
  );
}

function MentionsList({ items }: { items: MentionItem[] }) {
  if (items.length === 0) {
    return <div className="mespace-empty">No mentions.</div>;
  }
  return (
    <ul className="mespace-list" data-testid="list-mentions">
      {items.map((m) => (
        <li key={m.id} className="mespace-list__row" data-id={m.id}>
          {m.target_display_id ? (
            <Link to={`/tickets/${encodeURIComponent(m.target_display_id)}`}>
              {m.target_display_id}
            </Link>
          ) : (
            <span>{m.target_id}</span>
          )}
          <span> · {m.kind}</span>
          {m.excerpt && <span> · {m.excerpt}</span>}
        </li>
      ))}
    </ul>
  );
}

function AgentRunsList({ items }: { items: AgentRunItem[] }) {
  if (items.length === 0) {
    return (
      <div className="mespace-empty">
        No agent runs yet. When an agent you own processes a ticket it'll show
        up here with a short summary.
      </div>
    );
  }
  return (
    <ul className="mespace-list mespace-list--agent-runs" data-testid="list-my_agent_runs">
      {items.map((r) => (
        <li key={r.id} className="mespace-list__row mespace-list__row--agent-run" data-id={r.id}>
          <div className="mespace-agent-run__head">
            <span className={`mespace-agent-run__status mespace-agent-run__status--${r.status}`}>
              {r.status}
            </span>
            <span className="mespace-agent-run__id">{r.id.slice(0, 8)}</span>
            <Link
              to={`/tickets/${encodeURIComponent(r.ticket_id)}`}
              className="mespace-agent-run__ticket-link"
            >
              ticket →
            </Link>
          </div>
          {r.prompt_preview && (
            <div className="mespace-agent-run__prompt" title="Prompt">
              <span className="mespace-agent-run__label">prompt:</span>{" "}
              {r.prompt_preview}
            </div>
          )}
          {r.summary && (
            <div className="mespace-agent-run__summary" title="Response summary">
              {r.summary}
            </div>
          )}
          {r.error && (
            <div className="mespace-agent-run__error" title="Error">
              {r.error}
            </div>
          )}
          {!r.summary && !r.error && r.status === "done" && (
            <div className="mespace-agent-run__summary mespace-agent-run__summary--empty">
              (no response body)
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}

export default function MeSpacePage() {
  const [data, setData] = React.useState<MyInbox | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [active, setActive] = React.useState<TabKey>("assigned_tickets");

  React.useEffect(() => {
    let cancelled = false;
    getMyInbox()
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          const msg = e instanceof Error ? e.message : "Failed to load";
          setError(msg);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="mespace" data-testid="mespace-page">
      <h1 className="mespace__title">My Space</h1>
      <p className="mespace__subtitle">
        Personal queue — items pinned <em>to you</em>: tickets/problems
        you've been assigned, mentions targeted at your handle, and runs
        from agents you own. For the global feed across the workspace,
        see <Link to="/activity">Activity</Link>.
      </p>

      <nav className="mespace-tabs" aria-label="My Space tabs">
        {TABS.map(({ key, label }) => {
          const count = data?.counts?.[key] ?? 0;
          return (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={active === key}
              data-tab={key}
              className={`mespace-tab${active === key ? " mespace-tab--active" : ""}`}
              onClick={() => setActive(key)}
            >
              {label}
              <span className="mespace-tab__count" data-testid={`count-${key}`}>
                {count}
              </span>
            </button>
          );
        })}
      </nav>

      {error && (
        <div className="mespace-empty" role="alert">
          {error}
        </div>
      )}

      {!data && !error && (
        <div className="mespace-empty">Loading…</div>
      )}

      {data && (
        <div className="mespace-panel" data-testid={`panel-${active}`}>
          {active === "assigned_tickets" && (
            <TicketsList items={data.assigned_tickets?.items ?? []} />
          )}
          {active === "assigned_problems" && (
            <ProblemsList items={data.assigned_problems?.items ?? []} />
          )}
          {active === "mentions" && (
            <MentionsList items={data.mentions?.items ?? []} />
          )}
          {active === "my_agent_runs" && (
            <AgentRunsList items={data.my_agent_runs?.items ?? []} />
          )}
        </div>
      )}
    </div>
  );
}
