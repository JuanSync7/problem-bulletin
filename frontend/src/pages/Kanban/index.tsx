import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { listTickets, type TicketDTO } from "../../api/tickets";
import {
  useProjects,
  useSprintsByProject,
  useMembersByProject,
} from "../../hooks/useProjectResources";
import { useTicketStream, type WSEvent } from "../../hooks/useTicketStream";
import { useAuth } from "../../hooks/useAuth";
import { KanbanBoard } from "./KanbanBoard";
import { TicketDetailDrawer } from "./TicketDetailDrawer";
import { HierarchyTreeView } from "./HierarchyTreeView";
import { WipLimitsDialog } from "./WipLimitsDialog";
import type { TicketStatus } from "../../api/tickets";
import type { ProjectDTO } from "../../api/projects";
import {
  FiltersBar,
  EMPTY_FILTERS,
  type KanbanFilters,
  type SwimlaneMode,
} from "./FiltersBar";
import type { TicketTypeV2 } from "../CreateTicket/fieldsByType";
import {
  useKanbanLaneHeight,
  laneHeightCssValue,
  type LaneHeight,
} from "./useKanbanLaneHeight";
import "./Kanban.css";

type ViewMode = "board" | "tree";

const LS_PROJECT_KEY = "kanban.project";
const LS_VIEW_KEY = "kanban.view";

function readLS(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}
function writeLS(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* ignore */
  }
}

export default function KanbanPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const projects = useProjects();
  const { user } = useAuth();

  // WP43 — lane-height preference (50vh / 70vh / 90vh / unlimited). Replaces
  // the now-dead WP36 column-width toggle (the board switched to a CSS grid
  // post-v2.5 so --kanban-column-width is no longer consumed).
  const [laneHeight, setLaneHeight] = useKanbanLaneHeight();

  // ----- Project selection ---------------------------------------------------
  const urlProjectKey = searchParams.get("project");
  const [projectKey, setProjectKeyState] = useState<string | null>(
    urlProjectKey || readLS(LS_PROJECT_KEY) || null,
  );

  // Resolve once projects load: default DEF -> first project if no selection.
  useEffect(() => {
    if (projects.loading || projects.data.length === 0) return;
    if (projectKey && projects.data.some((p) => p.key === projectKey)) return;
    const def = projects.data.find((p) => p.key === "DEF");
    const next = def?.key ?? projects.data[0]!.key;
    setProjectKeyState(next);
  }, [projects.loading, projects.data, projectKey]);

  // Sync project to URL + localStorage.
  useEffect(() => {
    if (!projectKey) return;
    writeLS(LS_PROJECT_KEY, projectKey);
    const current = searchParams.get("project");
    if (current !== projectKey) {
      const next = new URLSearchParams(searchParams);
      next.set("project", projectKey);
      setSearchParams(next, { replace: true });
    }
  }, [projectKey, searchParams, setSearchParams]);

  const project = useMemo(
    () => projects.data.find((p) => p.key === projectKey) ?? null,
    [projects.data, projectKey],
  );
  const projectId = project?.id ?? null;

  const setProjectKey = useCallback((nextKey: string) => {
    setProjectKeyState(nextKey);
    setFilters(EMPTY_FILTERS); // Clear filters on project switch
  }, []);

  // ----- View toggle ---------------------------------------------------------
  const [view, setView] = useState<ViewMode>(
    (readLS(LS_VIEW_KEY) as ViewMode | null) === "tree" ? "tree" : "board",
  );
  useEffect(() => {
    writeLS(LS_VIEW_KEY, view);
  }, [view]);

  // ----- Filters / swimlanes -------------------------------------------------
  const [filters, setFilters] = useState<KanbanFilters>(EMPTY_FILTERS);
  const [swimlane, setSwimlane] = useState<SwimlaneMode>("none");
  const [showTerminal, setShowTerminal] = useState(false);

  // ----- Ticket data ---------------------------------------------------------
  const [tickets, setTickets] = useState<TicketDTO[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTicket, setActiveTicket] = useState<string | null>(null);
  const [rootKey, setRootKey] = useState<string>("");

  // v2.1-WP10: sentinels are now first-class backend syntax. The
  // Kanban no longer translates `__none__` / `__unassigned__` at the
  // edge — it passes `"null"` / `"me"` straight through.
  const apiFilters = useMemo(() => {
    const out: Parameters<typeof listTickets>[0] = { limit: 500 };
    if (projectId) out.project_id = projectId;
    if (filters.sprintId !== null) out.sprint_id = filters.sprintId;
    if (filters.componentId !== null) out.component_id = filters.componentId;
    if (filters.epicId !== null) out.epic_id = filters.epicId;
    if (filters.assigneeId !== null) out.assignee_id = filters.assigneeId;
    if (filters.types.length > 0) {
      out.type = filters.types;
    }
    return out;
  }, [projectId, filters]);

  // v2.1-WP10: pagination state. The server returns a cursor envelope
  // ``{items, next_cursor, total}`` with a 500-row hard cap per page.
  // For now we expose a "Load more" button when the server flags more
  // pages; the swimlane / column counts already operate on the loaded
  // slice so partial loads degrade gracefully.
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [totalCount, setTotalCount] = useState<number | null>(null);
  // v2.1-WP11: per-column counts (backend aggregate) for WIP-limit chips.
  const [columnCounts, setColumnCounts] = useState<Partial<
    Record<TicketStatus, number>
  > | null>(null);
  const [wipDialogOpen, setWipDialogOpen] = useState(false);

  const refresh = useCallback(() => {
    if (!projectId) return;
    setLoading(true);
    setError(null);
    // v2.3-WP22: backend now orders by COALESCE(last_activity_at,
    // created_at) DESC so recently-active tickets (including done/
    // cancelled) surface first regardless of creation order. The v2.2
    // secondary status=["done"] fetch and Promise.all merge are removed
    // — a single request is sufficient. A cheap dedup-by-id guard is
    // kept below to protect against any future cursor-overlap edge cases.
    listTickets({ ...apiFilters, order_by: "last_activity_at" })
      .then((res) => {
        const items = Array.isArray(res?.items) ? res.items : [];
        const seen = new Set<string>();
        const deduped: TicketDTO[] = [];
        for (const t of items) {
          if (seen.has(t.id)) continue;
          seen.add(t.id);
          deduped.push(t);
        }
        setTickets(deduped);
        setNextCursor(res?.next_cursor ?? null);
        setTotalCount(res?.total ?? null);
        setColumnCounts(res?.column_counts ?? null);
      })
      .catch((e) =>
        setError(e instanceof Error ? e.message : "Failed to load tickets"),
      )
      .finally(() => setLoading(false));
  }, [apiFilters, projectId]);

  const loadMore = useCallback(() => {
    if (!projectId || !nextCursor) return;
    setLoading(true);
    listTickets({ ...apiFilters, cursor: nextCursor, order_by: "last_activity_at" })
      .then((res) => {
        setTickets((prev) => [
          ...prev,
          ...(Array.isArray(res?.items) ? res.items : []),
        ]);
        setNextCursor(res?.next_cursor ?? null);
      })
      .catch((e) =>
        setError(e instanceof Error ? e.message : "Failed to load more"),
      )
      .finally(() => setLoading(false));
  }, [apiFilters, projectId, nextCursor]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Defensive project guard for WS reconciliation drift. All other
  // filter compensation moved to the backend in v2.1-WP10.
  const visibleTickets = useMemo(() => {
    if (!projectId) return tickets;
    return tickets.filter(
      (t) => !t.project_id || t.project_id === projectId,
    );
  }, [tickets, projectId]);

  // ----- WS reconciliation ---------------------------------------------------
  useTicketStream({
    projectId: projectId ?? undefined,
    onEvent: (evt: WSEvent) => {
      if (evt.event === "ticket.created" || evt.event === "ticket.linked") {
        refresh();
        return;
      }
      const payload = (evt.payload ?? {}) as Record<string, unknown>;
      const incoming =
        ((payload as { ticket?: TicketDTO }).ticket as TicketDTO | undefined) ??
        null;
      if (incoming) {
        // Respect current project filter — drop foreign-project tickets.
        if (
          projectId &&
          incoming.project_id &&
          incoming.project_id !== projectId
        ) {
          return;
        }
        setTickets((prev) => {
          const exists = prev.some((t) => t.id === incoming.id);
          if (!exists) return [...prev, incoming];
          return prev.map((t) => (t.id === incoming.id ? incoming : t));
        });
        return;
      }
      const ticketId =
        (payload.ticket_id as string | undefined) ??
        (evt.ticket_id as string | undefined);
      if (ticketId) {
        setTickets((prev) =>
          prev.map((t) =>
            t.id === ticketId
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

  // ----- Lookups for card chips / swimlane headers ---------------------------
  const epicsInBoard = useMemo(
    () => tickets.filter((t) => (t.type as TicketTypeV2) === "epic"),
    [tickets],
  );
  const epicLookup = useMemo(() => {
    const m: Record<string, TicketDTO> = {};
    for (const t of epicsInBoard) m[t.id] = t;
    return m;
  }, [epicsInBoard]);

  const members = useMembersByProject(projectId);
  const assigneeLookup = useMemo(() => {
    const m: Record<string, string> = {};
    for (const x of members.data)
      m[x.member_id] = `${x.member_type}:${x.member_id.slice(0, 8)}`;
    return m;
  }, [members.data]);

  const sprints = useSprintsByProject(projectId, ["planned", "active"]);
  const sprintLookup = useMemo(() => {
    const m: Record<string, string> = {};
    for (const s of sprints.data) m[s.id] = s.name;
    return m;
  }, [sprints.data]);

  // ----- Render --------------------------------------------------------------
  return (
    <div className="kanban-page">
      <header className="kanban-page__header">
        <h1 className="kanban-page__title">Kanban Board</h1>
        <div className="kanban-page__toolbar">
          <label className="kanban-filters__field">
            <span>Project</span>
            <select
              aria-label="Project"
              value={projectKey ?? ""}
              onChange={(e) => setProjectKey(e.target.value)}
            >
              {projects.data.length === 0 && (
                <option value="">(no projects)</option>
              )}
              {projects.data
                .filter((p) => !p.archived_at)
                .map((p) => (
                  <option key={p.id} value={p.key}>
                    {p.key} — {p.name}
                  </option>
                ))}
            </select>
          </label>
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
              placeholder={`epic key e.g. ${projectKey ?? "DEF"}-1`}
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
            disabled={loading || !projectId}
          >
            Refresh
          </button>
          {/* WP43 — lane-height segmented control */}
          {view === "board" && (
            <div
              className="kanban-lane-height-toggle"
              role="radiogroup"
              aria-label="Lane height"
              data-testid="lane-height-toggle"
            >
              {(["50vh", "70vh", "90vh", "unlimited"] as LaneHeight[]).map(
                (pref) => (
                  <button
                    key={pref}
                    type="button"
                    role="radio"
                    aria-checked={laneHeight === pref}
                    className={`kanban-lane-height-toggle__btn${laneHeight === pref ? " kanban-lane-height-toggle__btn--active" : ""}`}
                    onClick={() => setLaneHeight(pref)}
                    data-testid={`lane-height-btn-${pref}`}
                  >
                    {pref === "unlimited" ? "Unlimited" : pref}
                  </button>
                ),
              )}
            </div>
          )}
          {/*
            v2.1-WP11: WIP limits editor. Gated client-side on
            ``project.lead_id === currentUser.id`` (or when there is no
            lead set yet, so a fresh project can configure limits).
            Server-enforced as of v2.2-WP15; this is UX-only.
          */}
          {project &&
            view === "board" &&
            (!project.lead_id || project.lead_id === user?.id) && (
              <button
                type="button"
                className="kanban-page__btn"
                onClick={() => setWipDialogOpen(true)}
                aria-label="Edit WIP limits"
                title="Edit WIP limits"
              >
                ⚙ Limits
              </button>
            )}
        </div>
      </header>

      {view === "board" && (
        <FiltersBar
          projectId={projectId}
          filters={filters}
          onChange={setFilters}
          swimlane={swimlane}
          onSwimlaneChange={setSwimlane}
          showTerminal={showTerminal}
          onShowTerminalChange={setShowTerminal}
          epicsInBoard={epicsInBoard}
          currentUserId={user?.id ?? null}
        />
      )}

      {error && <div className="ticket-drawer__error">{error}</div>}

      <div className="kanban-page__body">
        {view === "board" ? (
          /* WP43 — apply lane-height CSS var; .kanban-column__list consumes
           * it via max-height: var(--kanban-lane-height, 70vh). The wrapper
           * uses display: contents to keep the grid layout undisturbed.
           * "unlimited" maps to the literal string "none" so the cap is
           * removed entirely. */
          <div
            className="kanban-board-root"
            style={{ "--kanban-lane-height": laneHeightCssValue(laneHeight) } as React.CSSProperties}
          >
            <KanbanBoard
              tickets={visibleTickets}
              onTicketsChange={setTickets}
              onCardClick={setActiveTicket}
              onError={setError}
              swimlane={swimlane}
              showTerminal={showTerminal}
              epicLookup={epicLookup}
              assigneeLookup={assigneeLookup}
              sprintLookup={sprintLookup}
              columnCounts={columnCounts}
              wipLimits={(project?.wip_limits ?? {}) as Record<string, number>}
            />
          </div>
        ) : (
          <HierarchyTreeView
            rootKey={rootKey.trim() || null}
            projectId={projectId}
            onSelect={setActiveTicket}
          />
        )}
      </div>

      {view === "board" && nextCursor && (
        <div className="kanban-page__loadmore">
          <button
            type="button"
            className="kanban-page__btn"
            onClick={loadMore}
            disabled={loading}
            aria-label="Load more tickets"
          >
            {loading
              ? "Loading…"
              : `Load more${totalCount != null ? ` (${visibleTickets.length}/${totalCount})` : ""}`}
          </button>
        </div>
      )}

      <TicketDetailDrawer
        ticketKey={activeTicket}
        onClose={() => setActiveTicket(null)}
        onChanged={(t) =>
          setTickets((prev) => prev.map((p) => (p.id === t.id ? t : p)))
        }
      />

      {wipDialogOpen && project && (
        <WipLimitsDialog
          project={project as ProjectDTO}
          onClose={() => setWipDialogOpen(false)}
          onSaved={(updated) => {
            // Refresh the projects hook by triggering its reload; the
            // simplest path is to refetch tickets (which gives us new
            // column_counts) and close the dialog. The projects hook
            // owns its own cache; the next refetch (on filter / project
            // switch) will pick up the new wip_limits. For an
            // immediate visual update we also mutate the project on
            // the hook's data array by re-fetching via refresh().
            projects.refresh?.();
            setWipDialogOpen(false);
            refresh();
            void updated;
          }}
        />
      )}
    </div>
  );
}
