import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import type { TicketDTO } from "../../api/tickets";
import {
  useProjects,
  useSprintsByProject,
  useMembersByProject,
} from "../../hooks/useProjectResources";
import { useTicketStream, type WSEvent } from "../../hooks/useTicketStream";
import { useAuth } from "../../hooks/useAuth";
import { KanbanBoard } from "./KanbanBoard";
import { TicketDetailDrawer } from "./TicketDetailDrawer";
import { WipLimitsDialog } from "./WipLimitsDialog";
import { flattenHierarchyForKanban, getProjectHierarchy, type ProjectDTO } from "../../api/projects";
import { listAgentRuns } from "../../api/agent_runs";
import type { AgentRunChipStatus } from "./TicketCard";
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

const LS_PROJECT_KEY = "kanban.project";

// --- localStorage helpers (best-effort; quota / private-mode safe) ---------
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

/** v2.29 S5 — cap on per-refresh agent-run lookups. The agent-runs API is
 *  per-ticket only, so the board fans out one GET per *visible
 *  agent-assigned* ticket, bounded to this many requests per refresh. */
const AGENT_RUN_FETCH_CAP = 20;

/** V5b — kanban now sources from the recursive-CTE hierarchy endpoint.
 *  Depth 8 covers any conceivable parent_id chain the schema permits
 *  (epic→story→task→subtask is 4; the extra headroom is cheap). */
const HIERARCHY_MAX_DEPTH = 8;

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

  // Resolve once projects load. V5b: prefer the seeded "PB" demo project,
  // falling back to DEF, then to the first available project.
  useEffect(() => {
    if (projects.loading || projects.data.length === 0) return;
    if (projectKey && projects.data.some((p) => p.key === projectKey)) return;
    const pb = projects.data.find((p) => p.key === "PB");
    const def = projects.data.find((p) => p.key === "DEF");
    const next = pb?.key ?? def?.key ?? projects.data[0]!.key;
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

  // ----- Filters / swimlanes -------------------------------------------------
  const [filters, setFilters] = useState<KanbanFilters>(EMPTY_FILTERS);
  const [swimlane, setSwimlane] = useState<SwimlaneMode>("none");
  const [showTerminal, setShowTerminal] = useState(false);

  // ----- Ticket data ---------------------------------------------------------
  // V5b — the kanban is fed by the project-hierarchy endpoint, the same
  // source-of-truth the /projects/:id/hierarchy page reads. ``tickets``
  // is the depth-first flatten of that tree, with each descendant
  // tagged with its root-epic's id so the existing ``epic_id`` chip
  // path on TicketCard lights up without extra API calls.
  const [tickets, setTickets] = useState<TicketDTO[]>([]);
  const [hierarchyEpicLookup, setHierarchyEpicLookup] = useState<
    Record<string, TicketDTO>
  >({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTicket, setActiveTicket] = useState<string | null>(null);
  const [wipDialogOpen, setWipDialogOpen] = useState(false);

  const refresh = useCallback(() => {
    if (!projectId) return;
    setLoading(true);
    setError(null);
    getProjectHierarchy(projectId, { max_depth: HIERARCHY_MAX_DEPTH })
      .then((res) => {
        const flat = flattenHierarchyForKanban(res);
        const epicLookup: Record<string, TicketDTO> = {};
        // First pass: capture epics as TicketDTOs so descendant cards
        // can resolve `epic_id -> display_id` for the chip.
        for (const row of flat) {
          if (row.ticket.type === "epic") {
            epicLookup[row.ticket.id] = row.ticket as unknown as TicketDTO;
          }
        }
        // Second pass: build the flat ticket list, patching `epic_id`
        // on descendants so the existing chip-render path in
        // TicketCard picks up the root epic id.
        const flatTickets: TicketDTO[] = flat.map((row) => {
          const base = row.ticket as unknown as TicketDTO;
          if (row.epic_id !== null) {
            return { ...base, epic_id: row.epic_id };
          }
          return base;
        });
        setTickets(flatTickets);
        setHierarchyEpicLookup(epicLookup);
      })
      .catch((e) =>
        setError(e instanceof Error ? e.message : "Failed to load tickets"),
      )
      .finally(() => setLoading(false));
  }, [projectId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Apply local filters (sprint/component/epic/assignee/types) over the
  // hierarchy-derived ticket list. The hierarchy endpoint already
  // scopes to the project, so we only need the per-ticket predicate
  // filters here. Defensive project guard preserved for WS drift.
  const visibleTickets = useMemo(() => {
    return tickets.filter((t) => {
      // v2.1-WP10 sentinel semantics — see FiltersBar.tsx:
      //   * filter value ``null``  → "All" (no filter applied)
      //   * filter value ``"null"`` → match tickets where the column IS NULL
      //   * filter value ``"me"``  → match the current user's id (assignee only)
      //   * anything else → exact id match
      if (projectId && t.project_id && t.project_id !== projectId) return false;
      if (filters.sprintId !== null) {
        const want = filters.sprintId === "null" ? null : filters.sprintId;
        const have = (t.sprint_id as string | null | undefined) ?? null;
        if (have !== want) return false;
      }
      if (filters.componentId !== null) {
        const want = filters.componentId === "null" ? null : filters.componentId;
        const have = (t.component_id as string | null | undefined) ?? null;
        if (have !== want) return false;
      }
      if (filters.epicId !== null) {
        const want = filters.epicId === "null" ? null : filters.epicId;
        const have = (t.epic_id as string | null | undefined) ?? null;
        if (have !== want) return false;
      }
      if (filters.assigneeId !== null) {
        const have = (t.assignee_id as string | null | undefined) ?? null;
        let want: string | null;
        if (filters.assigneeId === "null") want = null;
        else if (filters.assigneeId === "me") want = user?.id ?? null;
        else want = filters.assigneeId;
        if (have !== want) return false;
      }
      if (filters.types.length > 0) {
        const ttype = (t.type ?? "task") as TicketTypeV2;
        if (!filters.types.includes(ttype)) return false;
      }
      return true;
    });
  }, [tickets, projectId, filters, user?.id]);

  // ----- Agent-run chip aggregate (v2.29 S5) ---------------------------------
  // One batch of lookups per board refresh — NOT one listAgentRuns call per
  // card render. Only visible agent-assigned tickets are queried (max
  // AGENT_RUN_FETCH_CAP, Promise.allSettled so one failure doesn't sink the
  // rest); the resulting map is keyed by ticket id and handed down to
  // TicketCard via KanbanBoard.
  const [agentRunLookup, setAgentRunLookup] = useState<
    Record<string, AgentRunChipStatus>
  >({});

  const agentTicketIds = useMemo(
    () =>
      visibleTickets
        .filter(
          (t) =>
            (t as TicketDTO & { assignee_type?: string }).assignee_type ===
            "agent",
        )
        .map((t) => t.id)
        .slice(0, AGENT_RUN_FETCH_CAP),
    [visibleTickets],
  );
  // Stable key so the effect re-runs only when the *set* of agent-assigned
  // tickets changes (cached per refresh), not on unrelated ticket updates.
  const agentTicketKey = agentTicketIds.join(",");

  useEffect(() => {
    if (agentTicketIds.length === 0) {
      setAgentRunLookup({});
      return;
    }
    let cancelled = false;
    void Promise.allSettled(
      agentTicketIds.map((id) => listAgentRuns(id)),
    ).then((results) => {
      if (cancelled) return;
      const next: Record<string, AgentRunChipStatus> = {};
      results.forEach((res, i) => {
        if (res.status !== "fulfilled") return;
        const latest = res.value.items[0]; // newest first
        if (latest) next[agentTicketIds[i]!] = latest.status;
      });
      setAgentRunLookup(next);
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentTicketKey]);

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
    // Merge the hierarchy-derived lookup (covers epics even when they
    // would otherwise be filtered out of the rendered slice) with the
    // currently-rendered epics. Hierarchy wins on overlap so the chip
    // always points at the freshest epic title.
    const m: Record<string, TicketDTO> = {};
    for (const t of epicsInBoard) m[t.id] = t;
    for (const [k, v] of Object.entries(hierarchyEpicLookup)) m[k] = v;
    return m;
  }, [epicsInBoard, hierarchyEpicLookup]);

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
          {/* v2.29 IA: create action lives in board context, not the sidebar */}
          <Link to="/tickets/new" className="kanban-page__btn kanban-page__btn--primary">
            + New Ticket
          </Link>
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
          {projectId && (
            <Link
              to={`/projects/${projectId}/hierarchy`}
              className="kanban-page__btn"
            >
              View full hierarchy
            </Link>
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
          {/*
            v2.1-WP11: WIP limits editor. Gated client-side on
            ``project.lead_id === currentUser.id`` (or when there is no
            lead set yet, so a fresh project can configure limits).
            Server-enforced as of v2.2-WP15; this is UX-only.
          */}
          {project &&
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

      {error && <div className="ticket-drawer__error">{error}</div>}

      <div className="kanban-page__body">
        {/* WP43 — apply lane-height CSS var; .kanban-column__list consumes
          * it via max-height: var(--kanban-lane-height, 70vh). The wrapper
          * uses display: contents to keep the grid layout undisturbed.
          * "unlimited" maps to the literal string "none" so the cap is
          * removed entirely. */}
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
            columnCounts={null}
            wipLimits={(project?.wip_limits ?? {}) as Record<string, number>}
            agentRunLookup={agentRunLookup}
            onAssigned={refresh}
          />
        </div>
      </div>

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
            // V5b — refresh project list (picks up new wip_limits on
            // the next project switch) and re-pull the hierarchy. The
            // hierarchy fetch doesn't carry wip_limits — those live on
            // the project payload — so we rely on projects.refresh()
            // to surface the change.
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
