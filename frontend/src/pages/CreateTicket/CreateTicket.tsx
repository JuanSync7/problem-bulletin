/**
 * Create Ticket page — Ticketing v2 (WP4).
 *
 * Route: /tickets/new (optional ?type=story&project=DEF query pre-fills).
 *
 * The form is driven entirely by `FIELDS_BY_TYPE` (see `./fieldsByType.ts`).
 * Changing the type re-renders visible fields and re-evaluates required-ness.
 * Parent-picker filters tickets to the same project and only the parent types
 * allowed for the selected child type (mirrors the service-layer matrix).
 */

import React, { Suspense, lazy, useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  ApiError,
  createTicket,
  searchTickets,
  type CreateTicketBody,
  type TicketDTO,
  type TicketPriority,
} from "../../api/tickets";
import { useToast } from "../../contexts/ToastContext";
import {
  useProjects,
  useSprintsByProject,
  useComponentsByProject,
} from "../../hooks/useProjectResources";
import { parseDisplayId } from "../../utils/displayId";
import {
  ALL_TICKET_TYPES,
  FIELDS_BY_TYPE,
  TICKET_TYPE_BADGE,
  TICKET_TYPE_LABEL,
  type TicketTypeV2,
} from "./fieldsByType";
import { PersonPicker } from "../../components/PersonPicker/index";
import type { PersonRef } from "../../api/people";
import "../../styles/form-field.css";
import "./CreateTicket.css";

// Lazy-load the rich editor to keep this route's initial bundle small.
const RichEditor = lazy(() => import("../../components/RichEditor"));

const PRIORITIES: TicketPriority[] = ["low", "medium", "high", "urgent"];

type FieldErrors = Partial<Record<string, string>>;

function parseChips(s: string): string[] {
  return s
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);
}

export default function CreateTicket() {
  const navigate = useNavigate();
  const toast = useToast();
  const [search] = useSearchParams();

  const initialType = ((search.get("type") as TicketTypeV2) ?? "task") as TicketTypeV2;
  const safeInitialType: TicketTypeV2 = ALL_TICKET_TYPES.includes(initialType)
    ? initialType
    : "task";
  const initialProjectKey = search.get("project") ?? "DEF";

  // --- type + project ------------------------------------------------------
  const [type, setType] = useState<TicketTypeV2>(safeInitialType);
  const spec = FIELDS_BY_TYPE[type];

  const projectsState = useProjects(false);
  const [projectKey, setProjectKey] = useState<string>(initialProjectKey);

  // pick a sensible default project once projects have loaded
  useEffect(() => {
    if (projectsState.loading || projectsState.data.length === 0) return;
    const hasCurrent = projectsState.data.some((p) => p.key === projectKey);
    if (hasCurrent) return;
    const def = projectsState.data.find((p) => p.key === "DEF");
    setProjectKey(def?.key ?? projectsState.data[0].key);
  }, [projectsState.loading, projectsState.data, projectKey]);

  const currentProject = useMemo(
    () => projectsState.data.find((p) => p.key === projectKey) ?? null,
    [projectsState.data, projectKey],
  );
  const currentProjectId = currentProject?.id ?? null;

  const sprintsState = useSprintsByProject(currentProjectId, ["planned", "active"]);
  const componentsState = useComponentsByProject(currentProjectId);

  // --- form state ----------------------------------------------------------
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [parent, setParent] = useState<TicketDTO | null>(null);
  const [parentSearch, setParentSearch] = useState("");
  const [parentResults, setParentResults] = useState<TicketDTO[]>([]);
  const [parentSearching, setParentSearching] = useState(false);
  const [sprintId, setSprintId] = useState<string>("");
  const [componentId, setComponentId] = useState<string>("");
  const [assignee, setAssignee] = useState<PersonRef | null>(null);
  const [priority, setPriority] = useState<TicketPriority>("medium");
  const [storyPoints, setStoryPoints] = useState<string>("");
  const [labelsInput, setLabelsInput] = useState("");
  const [fixVersionsInput, setFixVersionsInput] = useState("");
  const [dueDate, setDueDate] = useState("");

  const [errors, setErrors] = useState<FieldErrors>({});
  const [submitting, setSubmitting] = useState(false);

  // --- parent search effect ------------------------------------------------
  useEffect(() => {
    if (!spec.parent.visible) {
      setParentResults([]);
      return;
    }
    const q = parentSearch.trim();
    if (q.length < 2) {
      setParentResults([]);
      return;
    }
    let cancelled = false;
    setParentSearching(true);
    const timer = window.setTimeout(() => {
      searchTickets(q, { limit: 10 })
        .then((res) => {
          if (cancelled) return;
          const allowed = new Set(spec.parentAllowedTypes);
          const filtered = (res.items ?? []).filter((t) => {
            if (currentProjectId && t.project_id && t.project_id !== currentProjectId) {
              return false;
            }
            if (!t.type) return true;
            return allowed.has(t.type as TicketTypeV2);
          });
          setParentResults(filtered);
        })
        .catch(() => {
          if (!cancelled) setParentResults([]);
        })
        .finally(() => {
          if (!cancelled) setParentSearching(false);
        });
    }, 200);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [parentSearch, spec.parent.visible, spec.parentAllowedTypes, currentProjectId]);

  // when the type changes, clear parent if no longer allowed
  useEffect(() => {
    if (!spec.parent.visible) {
      setParent(null);
      setParentSearch("");
    } else if (parent && parent.type) {
      const allowed = new Set(spec.parentAllowedTypes);
      if (!allowed.has(parent.type as TicketTypeV2)) {
        setParent(null);
        setParentSearch("");
      }
    }
    // when type changes hide story points etc, clear them so they don't leak
    if (!spec.storyPoints.visible) setStoryPoints("");
    if (!spec.sprint.visible) setSprintId("");
  }, [type, spec, parent]);

  // --- validation ----------------------------------------------------------
  const validate = useCallback((): FieldErrors => {
    const e: FieldErrors = {};
    if (spec.title.required && !title.trim()) e.title = "Title is required";
    else if (title.trim().length > 200) e.title = "Title must be 200 characters or fewer";

    if (spec.description.required && !description.trim()) {
      e.description = "Description is required";
    }

    if (spec.project.required && !projectKey) e.project = "Project is required";

    if (spec.parent.required && !parent) {
      e.parent = "Parent ticket is required for a subtask";
    }
    if (parent && parent.type) {
      const allowed = new Set(spec.parentAllowedTypes);
      if (!allowed.has(parent.type as TicketTypeV2)) {
        e.parent = `Parent must be one of: ${spec.parentAllowedTypes.join(", ")}`;
      }
    }

    if (storyPoints && spec.storyPoints.visible) {
      const n = Number(storyPoints);
      if (!Number.isFinite(n) || n < 0) e.storyPoints = "Must be a non-negative number";
    }

    // Assignee comes from PersonPicker — already shape-validated.

    return e;
  }, [
    spec,
    title,
    description,
    projectKey,
    parent,
    storyPoints,
  ]);

  const handleSubmit = useCallback(
    async (ev: React.FormEvent) => {
      ev.preventDefault();
      const fieldErrors = validate();
      if (Object.keys(fieldErrors).length > 0) {
        setErrors(fieldErrors);
        return;
      }
      setErrors({});
      setSubmitting(true);

      const body: CreateTicketBody = {
        title: title.trim(),
        type,
        priority: spec.priority.visible ? priority : undefined,
        project_key: projectKey || undefined,
      };
      if (description.trim()) body.description = description.trim();
      if (parent) body.parent_id = parent.id;
      if (spec.sprint.visible && sprintId) body.sprint_id = sprintId;
      if (spec.component.visible && componentId) body.component_id = componentId;
      if (assignee) {
        body.assignee_id = assignee.id;
        body.assignee_type = assignee.kind;
      }
      if (spec.storyPoints.visible && storyPoints) {
        body.story_points = Number(storyPoints);
      }
      const labels = parseChips(labelsInput);
      if (labels.length > 0) body.labels = labels;
      const fixVersions = parseChips(fixVersionsInput);
      if (fixVersions.length > 0) body.fix_versions = fixVersions;
      if (dueDate) body.due_date = dueDate;

      try {
        const ticket = await createTicket(body);
        toast.show(
          `Created ${ticket.display_id ?? ticket.id}`,
          "success",
        );
        const key = ticket.display_id ?? ticket.id;
        // v2.3-WP21: navigate to the real ticket detail route.
        navigate(`/tickets/${encodeURIComponent(key)}`);
      } catch (err) {
        if (err instanceof ApiError) {
          if (err.status === 409) {
            toast.show("Parent ticket must be in the same project.", "error");
            setErrors((e) => ({ ...e, parent: "Parent must be in the same project" }));
          } else if (err.status === 400 && err.envelope?.details) {
            const details = err.envelope.details as {
              fields?: { name: string; message: string }[];
            };
            const fieldMap: FieldErrors = {};
            for (const f of details.fields ?? []) {
              fieldMap[f.name === "parent_id" ? "parent" : f.name] = f.message;
            }
            if (Object.keys(fieldMap).length > 0) setErrors(fieldMap);
            else toast.show(err.envelope?.message ?? "Failed to create ticket", "error");
          } else {
            toast.show(err.envelope?.message ?? err.message, "error");
          }
        } else {
          toast.show(err instanceof Error ? err.message : "Failed to create ticket", "error");
        }
      } finally {
        setSubmitting(false);
      }
    },
    [
      validate,
      title,
      type,
      spec,
      priority,
      projectKey,
      description,
      parent,
      sprintId,
      componentId,
      assignee,
      storyPoints,
      labelsInput,
      fixVersionsInput,
      dueDate,
      toast,
      navigate,
    ],
  );

  // --- render --------------------------------------------------------------

  return (
    <div className="create-ticket-page">
      <h1 className="create-ticket-page__title">Create Ticket</h1>

      <form className="create-ticket-form" onSubmit={handleSubmit} noValidate>
        {/* Type picker */}
        <div
          className="create-ticket-type-picker"
          role="radiogroup"
          aria-label="Ticket type"
        >
          {ALL_TICKET_TYPES.map((t) => {
            const badge = TICKET_TYPE_BADGE[t];
            const active = t === type;
            return (
              <button
                key={t}
                type="button"
                role="radio"
                aria-checked={active}
                className={`create-ticket-type-pill${
                  active ? " create-ticket-type-pill--active" : ""
                }`}
                onClick={() => setType(t)}
              >
                <span
                  className="create-ticket-type-pill__badge"
                  style={{ background: badge.color }}
                  aria-hidden="true"
                >
                  {badge.letter}
                </span>
                {TICKET_TYPE_LABEL[t]}
              </button>
            );
          })}
        </div>

        {/* Project */}
        <div className="form-field">
          <label className="form-field__label" htmlFor="ct-project">
            Project<span className="form-field__required">*</span>
          </label>
          <select
            id="ct-project"
            className="form-field__select"
            value={projectKey}
            onChange={(e) => setProjectKey(e.target.value)}
            disabled={projectsState.loading}
          >
            {projectsState.data.length === 0 && (
              <option value={projectKey}>{projectKey}</option>
            )}
            {projectsState.data.map((p) => (
              <option key={p.id} value={p.key}>
                {p.key} — {p.name}
              </option>
            ))}
          </select>
          {errors.project && (
            <span className="form-field__error">{errors.project}</span>
          )}
        </div>

        {/* Title */}
        <div className="form-field">
          <label className="form-field__label" htmlFor="ct-title">
            Title
            {spec.title.required && <span className="form-field__required">*</span>}
          </label>
          <input
            id="ct-title"
            type="text"
            className={`form-field__input${
              errors.title ? " form-field__input--error" : ""
            }`}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            maxLength={200}
            placeholder="Short summary"
            autoFocus
          />
          {errors.title && <span className="form-field__error">{errors.title}</span>}
          <span className="form-field__hint">{title.length} / 200</span>
        </div>

        {/* Description */}
        {spec.description.visible && (
          <div className="form-field">
            <label className="form-field__label">
              Description
              {spec.description.required && (
                <span className="form-field__required">*</span>
              )}
            </label>
            <Suspense fallback={<div className="form-field__hint">Loading editor…</div>}>
              <RichEditor
                value={description}
                onChange={setDescription}
                placeholder="Describe the work. Markdown supported."
                minHeight="160px"
              />
            </Suspense>
            {errors.description && (
              <span className="form-field__error">{errors.description}</span>
            )}
          </div>
        )}

        {/* Parent picker */}
        {spec.parent.visible && (
          <div className="form-field create-ticket-parent">
            <label className="form-field__label" htmlFor="ct-parent">
              Parent ticket
              {spec.parent.required && (
                <span className="form-field__required">*</span>
              )}
            </label>
            {parent ? (
              <div className="create-ticket-parent__selected">
                <span className="create-ticket-parent__option-key">
                  {parent.display_id ?? parent.id.slice(0, 8)}
                </span>
                <span>{parent.title}</span>
                <button
                  type="button"
                  className="create-ticket-parent__clear"
                  onClick={() => {
                    setParent(null);
                    setParentSearch("");
                  }}
                  aria-label="Clear parent"
                >
                  ×
                </button>
              </div>
            ) : (
              <input
                id="ct-parent"
                type="text"
                className={`form-field__input${
                  errors.parent ? " form-field__input--error" : ""
                }`}
                value={parentSearch}
                onChange={(e) => setParentSearch(e.target.value)}
                placeholder={
                  spec.parentAllowedTypes.length > 0
                    ? `Search ${spec.parentAllowedTypes.join("/")}…`
                    : "Search tickets…"
                }
              />
            )}
            {!parent && parentResults.length > 0 && (
              <ul className="create-ticket-parent__results" role="listbox">
                {parentResults.map((t) => {
                  const parsed = t.display_id ? parseDisplayId(t.display_id) : null;
                  const label = parsed ? t.display_id! : t.id.slice(0, 8);
                  return (
                    <li
                      key={t.id}
                      role="option"
                      aria-selected="false"
                      className="create-ticket-parent__option"
                      onClick={() => {
                        setParent(t);
                        setParentSearch("");
                        setParentResults([]);
                      }}
                    >
                      <span className="create-ticket-parent__option-key">{label}</span>
                      <span>{t.title}</span>
                    </li>
                  );
                })}
              </ul>
            )}
            {!parent && parentSearching && (
              <span className="form-field__hint">Searching…</span>
            )}
            {errors.parent && (
              <span className="form-field__error">{errors.parent}</span>
            )}
          </div>
        )}

        <div className="create-ticket-row">
          {/* Sprint */}
          {spec.sprint.visible && (
            <div className="form-field">
              <label className="form-field__label" htmlFor="ct-sprint">
                Sprint
              </label>
              <select
                id="ct-sprint"
                className="form-field__select"
                value={sprintId}
                onChange={(e) => setSprintId(e.target.value)}
                disabled={sprintsState.loading}
              >
                <option value="">None</option>
                {sprintsState.data.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name} ({s.state})
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* Component */}
          {spec.component.visible && (
            <div className="form-field">
              <label className="form-field__label" htmlFor="ct-component">
                Component
              </label>
              <select
                id="ct-component"
                className="form-field__select"
                value={componentId}
                onChange={(e) => setComponentId(e.target.value)}
                disabled={componentsState.loading}
              >
                <option value="">None</option>
                {componentsState.data.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>

        <div className="create-ticket-row">
          {/* Assignee */}
          {spec.assignee.visible && (
            <div className="form-field">
              <label className="form-field__label">Assignee</label>
              <PersonPicker
                value={assignee}
                onChange={setAssignee}
                placeholder="Search for a user or agent…"
                allowClear
              />
              {errors.assignee && (
                <span className="form-field__error">{errors.assignee}</span>
              )}
            </div>
          )}

          {/* Priority */}
          {spec.priority.visible && (
            <div className="form-field">
              <label className="form-field__label">Priority</label>
              <div className="create-ticket-priority" role="radiogroup">
                {PRIORITIES.map((p) => (
                  <button
                    key={p}
                    type="button"
                    role="radio"
                    aria-checked={priority === p}
                    className={`create-ticket-priority__btn${
                      priority === p ? " create-ticket-priority__btn--active" : ""
                    }`}
                    onClick={() => setPriority(p)}
                  >
                    {p}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="create-ticket-row">
          {/* Story points */}
          {spec.storyPoints.visible && (
            <div className="form-field">
              <label className="form-field__label" htmlFor="ct-story-points">
                Story points
              </label>
              <input
                id="ct-story-points"
                type="number"
                min={0}
                step={1}
                className={`form-field__input${
                  errors.storyPoints ? " form-field__input--error" : ""
                }`}
                value={storyPoints}
                onChange={(e) => setStoryPoints(e.target.value)}
                style={{ maxWidth: 140 }}
              />
              {errors.storyPoints && (
                <span className="form-field__error">{errors.storyPoints}</span>
              )}
            </div>
          )}

          {/* Due date */}
          {spec.dueDate.visible && (
            <div className="form-field">
              <label className="form-field__label" htmlFor="ct-due">
                Due date
              </label>
              <input
                id="ct-due"
                type="date"
                className="form-field__input"
                value={dueDate}
                onChange={(e) => setDueDate(e.target.value)}
                style={{ maxWidth: 220 }}
              />
            </div>
          )}
        </div>

        {/* Labels */}
        {spec.labels.visible && (
          <div className="form-field">
            <label className="form-field__label" htmlFor="ct-labels">
              Labels
            </label>
            <input
              id="ct-labels"
              type="text"
              className="form-field__input"
              value={labelsInput}
              onChange={(e) => setLabelsInput(e.target.value)}
              placeholder="comma,separated,labels"
            />
          </div>
        )}

        {/* Fix versions */}
        {spec.fixVersions.visible && (
          <div className="form-field">
            <label className="form-field__label" htmlFor="ct-fix-versions">
              Fix versions
            </label>
            <input
              id="ct-fix-versions"
              type="text"
              className="form-field__input"
              value={fixVersionsInput}
              onChange={(e) => setFixVersionsInput(e.target.value)}
              placeholder="1.0,1.1"
            />
          </div>
        )}

        <div className="create-ticket-actions">
          <button
            type="button"
            className="create-ticket-btn"
            onClick={() => navigate(-1)}
            disabled={submitting}
          >
            Cancel
          </button>
          <button
            type="submit"
            className="create-ticket-btn create-ticket-btn--primary"
            disabled={submitting}
          >
            {submitting ? "Creating…" : "Create Ticket"}
          </button>
        </div>
      </form>
    </div>
  );
}
