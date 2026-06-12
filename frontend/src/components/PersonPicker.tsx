/**
 * @deprecated v2.6-WP42 — this is the legacy flat-file PersonPicker (v2.1-WP8).
 *   New consumers MUST use `components/PersonPicker/index.tsx` (v2.5-WP32),
 *   which has keyboard nav, 250ms debounce, and a chip mode. This file remains
 *   only because the Kanban FiltersBar still relies on the `specials`
 *   ("Unassigned" / "Me") prop, which the new picker does not yet support.
 *   Track the migration in the v2.7 plan: add `specials` to the new picker,
 *   then delete this file. Do NOT add new consumers here.
 *
 * PersonPicker — async user/agent search input (v2.1-WP8).
 *
 * Used by the Kanban filters bar (assignee filter) and the Create-Ticket form
 * (assignee picker). Wraps ``GET /api/v1/people/search`` with a 300ms debounced
 * input and renders the result list with a kind-badge + display_name +
 * optional handle subtitle.
 *
 * The value model is ``{ kind, id }`` (or ``null`` when nothing selected),
 * which the consumer passes back to the ticket API. "Specials" (Unassigned,
 * Me) are passed by the caller via the ``specials`` prop and rendered as
 * non-debounced static rows above the live results.
 *
 * No external debounce library is used (Cross-WP Rule: no new deps).
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { searchPeople, type PersonKind, type PersonRef } from "../api/people";

export interface PersonPickerValue {
  kind: PersonKind;
  id: string;
}

export interface PersonPickerSpecial {
  /** A stable, unique key used in the rendered <li>. */
  key: string;
  /** Display text. */
  label: string;
  /**
   * Value to bubble through ``onChange`` when picked. The picker is
   * agnostic to special semantics — callers (e.g. FiltersBar's "Me"
   * sentinel) interpret these.
   */
  value: PersonPickerValue | null;
}

export interface PersonPickerProps {
  value: PersonPickerValue | null;
  onChange: (v: PersonPickerValue | null) => void;
  projectId?: string | null;
  kind?: PersonKind | PersonKind[];
  placeholder?: string;
  /** "specials" rendered above live results (e.g. Unassigned, Me). */
  specials?: PersonPickerSpecial[];
  /** Optional id for testing / a11y. */
  id?: string;
  /** Used for the label/aria-label of the input. */
  ariaLabel?: string;
  /** Display label for the currently-selected value (for the chip). */
  selectedLabel?: string | null;
  disabled?: boolean;
}

const DEBOUNCE_MS = 300;

export function PersonPicker(props: PersonPickerProps) {
  const {
    value,
    onChange,
    projectId,
    kind,
    placeholder = "Search people…",
    specials = [],
    id,
    ariaLabel,
    selectedLabel,
    disabled,
  } = props;

  const [query, setQuery] = useState("");
  const [results, setResults] = useState<PersonRef[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);

  // Close on outside click.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!containerRef.current) return;
      if (!containerRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  // Debounced search.
  useEffect(() => {
    if (!open) {
      setResults([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    const timer = window.setTimeout(() => {
      searchPeople({
        q: query.trim() || undefined,
        kind,
        project_id: projectId ?? undefined,
        limit: 10,
      })
        .then((res) => {
          if (cancelled) return;
          setResults(res.items ?? []);
        })
        .catch(() => {
          if (!cancelled) setResults([]);
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, DEBOUNCE_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [query, open, projectId, kind]);

  const kindBadge = (k: PersonKind) =>
    k === "agent" ? (
      <span
        aria-label="agent"
        title="agent"
        style={{
          fontSize: "0.7em",
          background: "#7c3aed",
          color: "#fff",
          borderRadius: 3,
          padding: "1px 4px",
          marginRight: 6,
        }}
      >
        A
      </span>
    ) : (
      <span
        aria-label="user"
        title="user"
        style={{
          fontSize: "0.7em",
          background: "#0ea5e9",
          color: "#fff",
          borderRadius: 3,
          padding: "1px 4px",
          marginRight: 6,
        }}
      >
        U
      </span>
    );

  const displayChip = useMemo(() => {
    if (!value) return null;
    if (selectedLabel) return selectedLabel;
    return `${value.kind}:${value.id.slice(0, 8)}`;
  }, [value, selectedLabel]);

  return (
    <div
      className="person-picker"
      ref={containerRef}
      style={{ position: "relative" }}
    >
      {value && !open ? (
        <div
          className="person-picker__selected"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            padding: "4px 6px",
            border: "1px solid #cbd5e1",
            borderRadius: 4,
            background: "#f8fafc",
          }}
        >
          {kindBadge(value.kind)}
          <span>{displayChip}</span>
          <button
            type="button"
            onClick={() => {
              onChange(null);
              setQuery("");
            }}
            aria-label="Clear selection"
            style={{
              border: "none",
              background: "transparent",
              cursor: "pointer",
              fontSize: "1em",
            }}
            disabled={disabled}
          >
            ×
          </button>
          <button
            type="button"
            onClick={() => setOpen(true)}
            style={{
              border: "none",
              background: "transparent",
              cursor: "pointer",
              color: "#0ea5e9",
              fontSize: "0.85em",
            }}
            disabled={disabled}
          >
            change
          </button>
        </div>
      ) : (
        <input
          id={id}
          type="text"
          role="combobox"
          aria-label={ariaLabel ?? "Search people"}
          aria-expanded={open}
          aria-autocomplete="list"
          className="person-picker__input form-field__input"
          value={query}
          placeholder={placeholder}
          onFocus={() => setOpen(true)}
          onChange={(e) => setQuery(e.target.value)}
          disabled={disabled}
        />
      )}
      {open && (
        <ul
          className="person-picker__results"
          role="listbox"
          style={{
            position: "absolute",
            top: "100%",
            left: 0,
            right: 0,
            zIndex: 20,
            background: "#fff",
            border: "1px solid #cbd5e1",
            borderRadius: 4,
            margin: 0,
            padding: 0,
            listStyle: "none",
            maxHeight: 260,
            overflowY: "auto",
            boxShadow: "0 4px 12px rgba(15,23,42,0.1)",
          }}
        >
          {specials.map((s) => (
            <li
              key={`special:${s.key}`}
              role="option"
              aria-selected="false"
              className="person-picker__special"
              onClick={() => {
                onChange(s.value);
                setOpen(false);
                setQuery("");
              }}
              style={{
                padding: "6px 8px",
                cursor: "pointer",
                borderBottom: "1px dashed var(--color-border, #E3E0D6)",
                fontStyle: "italic",
              }}
            >
              {s.label}
            </li>
          ))}
          {loading && (
            <li
              className="person-picker__hint"
              style={{ padding: "6px 8px", color: "#64748b" }}
            >
              Searching…
            </li>
          )}
          {!loading && results.length === 0 && (
            <li
              className="person-picker__hint"
              style={{ padding: "6px 8px", color: "#64748b" }}
            >
              No matches
            </li>
          )}
          {results.map((p) => (
            <li
              key={`${p.kind}:${p.id}`}
              role="option"
              aria-selected={
                value !== null && value.id === p.id && value.kind === p.kind
              }
              data-kind={p.kind}
              className="person-picker__option"
              onClick={() => {
                onChange({ kind: p.kind, id: p.id });
                setOpen(false);
                setQuery("");
              }}
              style={{ padding: "6px 8px", cursor: "pointer" }}
            >
              <div style={{ display: "flex", alignItems: "center" }}>
                {kindBadge(p.kind)}
                <strong>{p.display_name}</strong>
              </div>
              {p.handle && (
                <div
                  className="person-picker__option-sub"
                  style={{ fontSize: "0.8em", color: "#64748b" }}
                >
                  @{p.handle}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
