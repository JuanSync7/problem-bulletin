/**
 * Kanban v2 filters bar.
 *
 * Sits beneath the project selector. Composes sprint / type / assignee /
 * component / epic filters into a single state object handed back via
 * `onChange`. Hooks (`useSprintsByProject`, `useComponentsByProject`,
 * `useMembersByProject`) are the WP4 reusables — do not duplicate.
 */
import {
  useSprintsByProject,
  useComponentsByProject,
} from "../../hooks/useProjectResources";
import {
  ALL_TICKET_TYPES,
  TICKET_TYPE_BADGE,
  TICKET_TYPE_LABEL,
  type TicketTypeV2,
} from "../CreateTicket/fieldsByType";
import type { TicketDTO } from "../../api/tickets";
import { PersonPicker, type PersonPickerSpecial } from "../../components/PersonPicker";

export type SwimlaneMode = "none" | "epic" | "assignee" | "sprint";

/**
 * v2.1-WP10 sentinel encoding (matches backend query syntax):
 *   - ``null``     → omit filter (frontend null = "All")
 *   - ``"null"``   → match WHERE col IS NULL (backend literal)
 *   - ``"me"``     → backend resolves to authenticated actor (assignee only)
 *   - ``"<uuid>"`` → straight equality
 *
 * The previous client-side ``__none__`` / ``__unassigned__`` sentinels
 * were removed — see ticketing-v2.1.md "v2.1-WP10 — Lessons".
 */
export interface KanbanFilters {
  sprintId: string | null;
  /** "null" | "me" | uuid | null (null means "All") */
  assigneeId: string | null;
  componentId: string | null;
  epicId: string | null;
  types: TicketTypeV2[];
}

export const EMPTY_FILTERS: KanbanFilters = {
  sprintId: null,
  assigneeId: null,
  componentId: null,
  epicId: null,
  types: [],
};

interface FiltersBarProps {
  projectId: string | null;
  filters: KanbanFilters;
  onChange: (next: KanbanFilters) => void;
  swimlane: SwimlaneMode;
  onSwimlaneChange: (s: SwimlaneMode) => void;
  showTerminal: boolean;
  onShowTerminalChange: (v: boolean) => void;
  /** Tickets currently loaded — used to derive epic options. */
  epicsInBoard?: TicketDTO[];
  currentUserId?: string | null;
}

export function FiltersBar({
  projectId,
  filters,
  onChange,
  swimlane,
  onSwimlaneChange,
  showTerminal,
  onShowTerminalChange,
  epicsInBoard = [],
  currentUserId = null,
}: FiltersBarProps) {
  const sprints = useSprintsByProject(projectId, ["planned", "active"]);
  const components = useComponentsByProject(projectId);

  // PersonPicker specials surfaced above live people-search results.
  // v2.1-WP10: "Unassigned" now uses the literal "null" sentinel that
  // the backend understands; "Me" uses "me" so the server resolves to
  // the authenticated actor (no client-side currentUserId roundtrip).
  const assigneeSpecials: PersonPickerSpecial[] = [
    { key: "all", label: "All assignees", value: null },
    {
      key: "unassigned",
      label: "Unassigned",
      value: { kind: "user", id: "null" },
    },
    {
      key: "me",
      label: "Me",
      value: { kind: "user", id: "me" },
    },
  ];

  const assigneeValue: { kind: "user" | "agent"; id: string } | null =
    filters.assigneeId === null
      ? null
      : { kind: "user", id: filters.assigneeId };

  const assigneeLabel =
    filters.assigneeId === "null"
      ? "Unassigned"
      : filters.assigneeId === "me" || filters.assigneeId === currentUserId
        ? "Me"
        : filters.assigneeId
          ? `${filters.assigneeId.slice(0, 8)}…`
          : null;

  const toggleType = (t: TicketTypeV2) => {
    const has = filters.types.includes(t);
    onChange({
      ...filters,
      types: has ? filters.types.filter((x) => x !== t) : [...filters.types, t],
    });
  };

  const isEmpty =
    filters.sprintId === null &&
    filters.assigneeId === null &&
    filters.componentId === null &&
    filters.epicId === null &&
    filters.types.length === 0;

  return (
    <div
      className="kanban-filters"
      role="toolbar"
      aria-label="Kanban filters"
    >
      <label className="kanban-filters__field">
        <span>Sprint</span>
        <select
          aria-label="Filter by sprint"
          value={filters.sprintId ?? "__all__"}
          onChange={(e) => {
            const v = e.target.value;
            // v2.1-WP10: "null" is the backend sentinel; "__all__" stays
            // local because dropping the filter cannot be expressed in
            // the URLSearchParams the API client builds.
            onChange({
              ...filters,
              sprintId: v === "__all__" ? null : v,
            });
          }}
        >
          <option value="__all__">All sprints</option>
          <option value="null">No sprint (backlog only)</option>
          {sprints.data.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name} ({s.state})
            </option>
          ))}
        </select>
      </label>

      <fieldset className="kanban-filters__field kanban-filters__chips">
        <legend>Type</legend>
        {ALL_TICKET_TYPES.map((t) => {
          const badge = TICKET_TYPE_BADGE[t];
          const active = filters.types.includes(t);
          return (
            <button
              key={t}
              type="button"
              role="checkbox"
              aria-checked={active}
              className={`kanban-filters__chip${active ? " kanban-filters__chip--on" : ""}`}
              onClick={() => toggleType(t)}
              title={TICKET_TYPE_LABEL[t]}
              style={
                active
                  ? { borderColor: badge.color, background: badge.color, color: "#fff" }
                  : { borderColor: badge.color, color: badge.color }
              }
            >
              <span style={{ fontWeight: 700 }}>{badge.letter}</span>{" "}
              {TICKET_TYPE_LABEL[t]}
            </button>
          );
        })}
      </fieldset>

      <label className="kanban-filters__field">
        <span>Assignee</span>
        <PersonPicker
          ariaLabel="Filter by assignee"
          value={assigneeValue}
          selectedLabel={assigneeLabel}
          projectId={projectId}
          specials={assigneeSpecials}
          onChange={(v) => {
            onChange({
              ...filters,
              assigneeId: v ? v.id : null,
            });
          }}
          placeholder="Any assignee"
        />
      </label>

      <label className="kanban-filters__field">
        <span>Component</span>
        <select
          aria-label="Filter by component"
          value={filters.componentId ?? "__all__"}
          onChange={(e) => {
            const v = e.target.value;
            onChange({
              ...filters,
              componentId: v === "__all__" ? null : v,
            });
          }}
        >
          <option value="__all__">All components</option>
          {components.data.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </label>

      <label className="kanban-filters__field">
        <span>Epic</span>
        <select
          aria-label="Filter by epic"
          value={filters.epicId ?? "__all__"}
          onChange={(e) => {
            const v = e.target.value;
            onChange({
              ...filters,
              epicId: v === "__all__" ? null : v,
            });
          }}
        >
          <option value="__all__">All epics</option>
          <option value="null">No epic</option>
          {epicsInBoard.map((t) => (
            <option key={t.id} value={t.id}>
              {t.display_id ?? t.id.slice(0, 8)} — {t.title}
            </option>
          ))}
        </select>
      </label>

      <label className="kanban-filters__field">
        <span>Swimlanes</span>
        <select
          aria-label="Swimlanes mode"
          value={swimlane}
          onChange={(e) => onSwimlaneChange(e.target.value as SwimlaneMode)}
        >
          <option value="none">None</option>
          <option value="epic">By Epic</option>
          <option value="assignee">By Assignee</option>
          <option value="sprint">By Sprint</option>
        </select>
      </label>

      <label className="kanban-filters__field kanban-filters__field--inline">
        <input
          type="checkbox"
          checked={showTerminal}
          onChange={(e) => onShowTerminalChange(e.target.checked)}
        />
        <span>Show Blocked / Cancelled</span>
      </label>

      <button
        type="button"
        className="kanban-page__btn"
        onClick={() => onChange({ ...EMPTY_FILTERS })}
        disabled={isEmpty}
      >
        Clear filters
      </button>
    </div>
  );
}
