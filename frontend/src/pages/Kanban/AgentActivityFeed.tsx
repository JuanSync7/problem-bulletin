import React, { useEffect, useState } from "react";
import { listAgentActivity, type ActivityEntry } from "../../api/audit";
import { useTicketStream, type WSEvent } from "../../hooks/useTicketStream";

interface AgentActivityFeedProps {
  projectId?: string;
}

const MAX_ITEMS = 50;

function summarize(entry: ActivityEntry): string {
  const who = entry.actor_name || `${entry.actor_type}:${entry.actor_id.slice(0, 8)}`;
  const what = entry.action;
  const target = entry.ticket_key || entry.entity_id.slice(0, 8);
  return `${who} ${what} ${target}`;
}

function fromWSEvent(evt: WSEvent): ActivityEntry | null {
  if (!evt.event.startsWith("agent.activity") && !evt.event.startsWith("ticket.")) {
    return null;
  }
  const payload = (evt.payload ?? {}) as Record<string, unknown>;
  const actor =
    (payload.actor as { id?: string; name?: string; type?: string } | undefined) ??
    {};
  const ticketKey =
    (payload.ticket_key as string | undefined) ??
    (payload as { ticket?: { key?: string } }).ticket?.key ??
    null;
  return {
    id: `${evt.occurred_at ?? Date.now()}-${actor.id ?? "anon"}-${evt.event}`,
    occurred_at: evt.occurred_at ?? new Date().toISOString(),
    actor_id: actor.id ?? "",
    actor_type: actor.type ?? "agent",
    actor_name: actor.name ?? null,
    action: evt.event.replace(/^ticket\./, "").replace(/^agent\./, ""),
    entity_type: "ticket",
    entity_id: (evt.ticket_id ?? "") as string,
    ticket_key: ticketKey,
    correlation_id: evt.correlation_id ?? null,
  };
}

export function AgentActivityFeed({ projectId }: AgentActivityFeedProps) {
  const [items, setItems] = useState<ActivityEntry[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    listAgentActivity({ project_id: projectId, actor_type: "agent", limit: MAX_ITEMS })
      .then((rows) => {
        if (!cancelled) setItems(rows);
      })
      .catch(() => {
        if (!cancelled) setItems([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  useTicketStream({
    projectId,
    onEvent: (evt) => {
      const entry = fromWSEvent(evt);
      if (!entry) return;
      setItems((prev) => [entry, ...prev].slice(0, MAX_ITEMS));
    },
  });

  return (
    <section className="activity-feed" aria-label="Agent activity feed">
      <header className="activity-feed__header">
        <span>Agent Activity</span>
        <span className="kanban-column__count">{items.length}</span>
      </header>
      <div className="activity-feed__list">
        {loading && <div className="activity-feed__empty">Loading…</div>}
        {!loading && items.length === 0 && (
          <div className="activity-feed__empty">No recent activity.</div>
        )}
        {items.map((entry) => (
          <div key={entry.id} className="activity-feed__item">
            <span>{summarize(entry)}</span>
            <span className="activity-feed__item-meta">
              {entry.occurred_at}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}
