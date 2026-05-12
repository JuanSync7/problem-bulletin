import React, { useCallback, useEffect, useState } from "react";
import { listTickets, type TicketDTO } from "../../api/tickets";
import { useTicketStream, type WSEvent } from "../../hooks/useTicketStream";
import { KanbanBoard } from "./KanbanBoard";
import { TicketDetailDrawer } from "./TicketDetailDrawer";
import { HierarchyTreeView } from "./HierarchyTreeView";
import { AgentActivityFeed } from "./AgentActivityFeed";
import "./Kanban.css";

type ViewMode = "board" | "tree";

export default function KanbanPage() {
  const [tickets, setTickets] = useState<TicketDTO[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTicket, setActiveTicket] = useState<string | null>(null);
  const [view, setView] = useState<ViewMode>("board");
  const [rootKey, setRootKey] = useState<string>("");

  const refresh = useCallback(() => {
    setLoading(true);
    setError(null);
    listTickets({ limit: 200 })
      .then((res) => setTickets(res.items))
      .catch((e) =>
        setError(e instanceof Error ? e.message : "Failed to load tickets"),
      )
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useTicketStream({
    onEvent: (evt: WSEvent) => {
      // Server-state-wins reconciliation: any ticket.* envelope refreshes the
      // affected ticket (or the whole board for create/link).
      if (
        evt.event === "ticket.created" ||
        evt.event === "ticket.linked"
      ) {
        refresh();
        return;
      }
      const payload = (evt.payload ?? {}) as Record<string, unknown>;
      const incoming =
        ((payload as { ticket?: TicketDTO }).ticket as TicketDTO | undefined) ??
        null;
      if (incoming) {
        setTickets((prev) => {
          const exists = prev.some((t) => t.id === incoming.id);
          if (!exists) return [...prev, incoming];
          return prev.map((t) => (t.id === incoming.id ? incoming : t));
        });
        return;
      }
      // For transition/assign envelopes that carry only key + status, patch in place.
      const key = payload.ticket_key as string | undefined;
      if (key) {
        setTickets((prev) =>
          prev.map((t) =>
            t.key === key
              ? {
                  ...t,
                  status: (payload.to_status as TicketDTO["status"]) ?? t.status,
                  version: (payload.version as number) ?? t.version,
                }
              : t,
          ),
        );
      }
    },
  });

  return (
    <div className="kanban-page">
      <header className="kanban-page__header">
        <h1 className="kanban-page__title">Kanban Board</h1>
        <div className="kanban-page__toolbar">
          <button
            type="button"
            className={`kanban-page__btn${view === "board" ? " kanban-page__btn--primary" : ""}`}
            onClick={() => setView("board")}
          >
            Board
          </button>
          <button
            type="button"
            className={`kanban-page__btn${view === "tree" ? " kanban-page__btn--primary" : ""}`}
            onClick={() => setView("tree")}
          >
            Hierarchy
          </button>
          {view === "tree" && (
            <input
              type="text"
              placeholder="epic key e.g. TKT-1"
              value={rootKey}
              onChange={(e) => setRootKey(e.target.value)}
              className="kanban-page__btn"
              style={{ minWidth: 160 }}
            />
          )}
          <button
            type="button"
            className="kanban-page__btn"
            onClick={refresh}
            disabled={loading}
          >
            Refresh
          </button>
        </div>
      </header>

      {error && <div className="ticket-drawer__error">{error}</div>}

      <div className="kanban-page__body">
        {view === "board" ? (
          <KanbanBoard
            tickets={tickets}
            onTicketsChange={setTickets}
            onCardClick={setActiveTicket}
            onError={setError}
          />
        ) : (
          <HierarchyTreeView
            rootKey={rootKey.trim() || null}
            onSelect={setActiveTicket}
          />
        )}
        <AgentActivityFeed />
      </div>

      <TicketDetailDrawer
        ticketKey={activeTicket}
        onClose={() => setActiveTicket(null)}
        onChanged={(t) =>
          setTickets((prev) => prev.map((p) => (p.id === t.id ? t : p)))
        }
      />
    </div>
  );
}
