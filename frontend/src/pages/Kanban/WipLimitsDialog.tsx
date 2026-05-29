/**
 * v2.1-WP11 — Per-project WIP limits editor.
 *
 * Minimal surgical UI: a small overlay with one numeric input per Kanban
 * column. Empty / 0 means "no limit" — the key is omitted from the
 * payload sent to ``PATCH /api/v1/projects/{id}``.
 *
 * OCC: the dialog carries the project's current ``version`` into the
 * PATCH. On 409 (conflict) the caller is expected to refetch and the
 * dialog reports an error so the user can retry.
 *
 * Permissions: the button is gated client-side (rendered only when
 * ``project.lead_id`` matches the current user) — UX-only gate.
 * Server-enforced as of v2.2-WP15; this is UX-only.
 * A 403 from the server surfaces an inline error message.
 */
import { useEffect, useState } from "react";
import { ApiError } from "../../api/tickets";
import { updateProject, type ProjectDTO } from "../../api/projects";
import type { TicketStatus } from "../../api/tickets";

/**
 * Column order matches ``KanbanBoard``. Keeping the list local avoids a
 * cross-module import for the seven literal statuses.
 */
const COLUMNS: { status: TicketStatus; title: string }[] = [
  { status: "backlog", title: "Backlog" },
  { status: "todo", title: "To Do" },
  { status: "in_progress", title: "In Progress" },
  { status: "in_review", title: "In Review" },
  { status: "done", title: "Done" },
  { status: "blocked", title: "Blocked" },
  { status: "cancelled", title: "Cancelled" },
];

interface WipLimitsDialogProps {
  project: ProjectDTO;
  onClose: () => void;
  /** Called after a successful save with the updated project. */
  onSaved: (updated: ProjectDTO) => void;
}

export function WipLimitsDialog({
  project,
  onClose,
  onSaved,
}: WipLimitsDialogProps) {
  // ``inputs[status]`` stores the raw string from the input so the user
  // can clear the field (empty = "no limit"). We only convert to int on
  // save.
  const [inputs, setInputs] = useState<Record<string, string>>(() => {
    const init: Record<string, string> = {};
    const wl = project.wip_limits ?? {};
    for (const col of COLUMNS) {
      const v = wl[col.status];
      init[col.status] = typeof v === "number" && v > 0 ? String(v) : "";
    }
    return init;
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Keep inputs in sync when the user refetches (e.g. after a 409).
  useEffect(() => {
    const next: Record<string, string> = {};
    const wl = project.wip_limits ?? {};
    for (const col of COLUMNS) {
      const v = wl[col.status];
      next[col.status] = typeof v === "number" && v > 0 ? String(v) : "";
    }
    setInputs(next);
  }, [project]);

  const handleSave = async () => {
    setError(null);
    // Build payload: empty / 0 / non-int drops the key entirely.
    const payload: Record<string, number> = {};
    for (const col of COLUMNS) {
      const raw = (inputs[col.status] ?? "").trim();
      if (!raw) continue;
      const n = Number(raw);
      if (!Number.isFinite(n) || !Number.isInteger(n) || n <= 0) continue;
      payload[col.status] = n;
    }
    setSaving(true);
    try {
      const updated = await updateProject(
        project.id,
        { wip_limits: payload },
        project.version ?? 1,
      );
      onSaved(updated);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setError(
          "Project changed since you opened this dialog. Please retry.",
        );
      } else if (e instanceof ApiError && e.status === 403) {
        setError("You don't have permission to edit this project.");
      } else if (e instanceof Error) {
        setError(e.message);
      } else {
        setError("Save failed");
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="wip-limits-overlay"
      role="dialog"
      aria-modal="true"
      aria-label="Edit WIP limits"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="wip-limits-dialog">
        <div className="wip-limits-dialog__header">
          <span>WIP Limits — {project.key}</span>
          <button
            type="button"
            className="wip-limits-dialog__close"
            onClick={onClose}
            aria-label="Close"
          >
            ×
          </button>
        </div>
        <div className="wip-limits-dialog__body">
          <p className="wip-limits-dialog__hint">
            Leave a field empty (or 0) to remove the limit for that column.
          </p>
          {COLUMNS.map((col) => (
            <label
              key={col.status}
              className="wip-limits-dialog__field"
              htmlFor={`wip-${col.status}`}
            >
              <span>{col.title}</span>
              <input
                id={`wip-${col.status}`}
                type="number"
                min={0}
                step={1}
                value={inputs[col.status] ?? ""}
                onChange={(e) =>
                  setInputs((s) => ({ ...s, [col.status]: e.target.value }))
                }
              />
            </label>
          ))}
          {error && (
            <div className="wip-limits-dialog__error" role="alert">
              {error}
            </div>
          )}
        </div>
        <div className="wip-limits-dialog__footer">
          <button
            type="button"
            className="kanban-page__btn"
            onClick={onClose}
            disabled={saving}
          >
            Cancel
          </button>
          <button
            type="button"
            className="kanban-page__btn kanban-page__btn--primary"
            onClick={handleSave}
            disabled={saving}
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
