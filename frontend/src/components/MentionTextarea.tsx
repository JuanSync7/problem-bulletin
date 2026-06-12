/**
 * MentionTextarea — comment composer with inline ``@``-autocomplete.
 *
 * v2.1-WP9. A plain ``<textarea>`` plus an absolutely-positioned
 * suggestion list. On typing ``@`` followed by a partial handle, calls
 * ``searchPeople`` (300ms debounced, matching the WP8 ``PersonPicker``
 * idiom). Selection inserts ``@<handle> `` and replaces the partial
 * token in-place.
 *
 * Why not TipTap mentions? Out-of-scope for v2.1-WP9 — too heavy for a
 * 2-line comment composer (Cross-WP Rule: "no new big abstractions").
 *
 * Keyboard:
 *  - ``Tab`` / ``ArrowDown`` cycle forward through suggestions
 *  - ``ArrowUp`` cycles back
 *  - ``Enter`` accepts the highlighted suggestion
 *  - ``Esc`` dismisses the suggestion list (textarea retains focus)
 */
import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { searchPeople, type PersonRef } from "../api/people";

const DEBOUNCE_MS = 300;
// Mirror the server-side regex (``app/services/tickets.py``). Allows
// handles 1–32 chars of ``[A-Za-z0-9_-]``.
const MENTION_TOKEN_RE = /@([A-Za-z0-9_-]{0,32})$/;

export interface MentionTextareaProps {
  value: string;
  onChange: (v: string) => void;
  projectId?: string | null;
  placeholder?: string;
  rows?: number;
  disabled?: boolean;
  /** Override of the textarea ``id``/aria for tests + a11y. */
  id?: string;
  ariaLabel?: string;
}

export function MentionTextarea(props: MentionTextareaProps) {
  const {
    value,
    onChange,
    projectId,
    placeholder,
    rows = 2,
    disabled,
    id,
    ariaLabel,
  } = props;

  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);

  // Active partial token (text after the most recent ``@`` before the
  // caret). ``null`` means no active mention context.
  const [partial, setPartial] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<PersonRef[]>([]);
  const [highlight, setHighlight] = useState(0);
  const [loading, setLoading] = useState(false);
  // Snapshot of value at the point the user pressed Esc — used to
  // suppress the suggestion list until the body actually changes.
  const dismissedValueRef = useRef<string | null>(null);

  const open = partial !== null;

  // Recompute the partial mention token whenever the caret OR value
  // changes. We scan back from the caret until we hit whitespace or a
  // newline; if the run starts with ``@`` and contains only
  // mention-handle characters, it's an active mention.
  const recomputePartial = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    // Suppress while the user has explicitly dismissed for this value.
    if (dismissedValueRef.current === value) {
      setPartial(null);
      return;
    }
    const caret = el.selectionStart ?? value.length;
    const before = value.slice(0, caret);
    const m = before.match(MENTION_TOKEN_RE);
    if (m) {
      setPartial(m[1] ?? "");
      setHighlight(0);
    } else {
      setPartial(null);
    }
  }, [value]);

  useEffect(() => {
    recomputePartial();
    // recomputePartial is the only effect-causing change we want; the
    // useCallback above tracks value so this re-runs on input.
  }, [recomputePartial]);

  // Debounced search whenever the partial changes.
  useEffect(() => {
    if (partial === null) {
      setSuggestions([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    const timer = window.setTimeout(() => {
      searchPeople({
        q: partial || undefined,
        project_id: projectId ?? undefined,
        limit: 8,
      })
        .then((res) => {
          if (cancelled) return;
          setSuggestions(res.items ?? []);
        })
        .catch(() => {
          if (!cancelled) setSuggestions([]);
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, DEBOUNCE_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [partial, projectId]);

  const insertMention = useCallback(
    (handle: string) => {
      const el = textareaRef.current;
      if (!el) return;
      const caret = el.selectionStart ?? value.length;
      const before = value.slice(0, caret);
      const after = value.slice(caret);
      // Replace the trailing ``@<partial>`` with ``@<handle> ``.
      const replaced = before.replace(MENTION_TOKEN_RE, `@${handle} `);
      const next = replaced + after;
      onChange(next);
      // Re-focus + place caret right after the inserted space.
      const newCaret = replaced.length;
      window.setTimeout(() => {
        if (!textareaRef.current) return;
        textareaRef.current.focus();
        try {
          textareaRef.current.setSelectionRange(newCaret, newCaret);
        } catch {
          /* jsdom may not support setSelectionRange on hidden els */
        }
      }, 0);
      setPartial(null);
    },
    [value, onChange],
  );

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (!open) return;
      if (suggestions.length === 0 && e.key !== "Escape") return;
      if (e.key === "Escape") {
        e.preventDefault();
        dismissedValueRef.current = value;
        setPartial(null);
        return;
      }
      if (e.key === "ArrowDown" || (e.key === "Tab" && !e.shiftKey)) {
        e.preventDefault();
        setHighlight((h) =>
          suggestions.length ? (h + 1) % suggestions.length : 0,
        );
        return;
      }
      if (e.key === "ArrowUp" || (e.key === "Tab" && e.shiftKey)) {
        e.preventDefault();
        setHighlight((h) =>
          suggestions.length
            ? (h - 1 + suggestions.length) % suggestions.length
            : 0,
        );
        return;
      }
      if (e.key === "Enter") {
        const pick = suggestions[highlight];
        if (pick && pick.handle) {
          e.preventDefault();
          insertMention(pick.handle);
        }
      }
    },
    [open, suggestions, highlight, insertMention, value],
  );

  const onTextChange = useCallback(
    (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      onChange(e.target.value);
    },
    [onChange],
  );

  // After the value updates from a parent, recompute partial against
  // the (new) caret position. ``onTextChange`` runs synchronously so
  // React batches the re-render; we recompute in the useEffect above.

  const containerStyle = useMemo<React.CSSProperties>(
    () => ({ position: "relative" }),
    [],
  );

  return (
    <div
      ref={containerRef}
      className="mention-textarea"
      style={containerStyle}
    >
      <textarea
        ref={textareaRef}
        id={id}
        aria-label={ariaLabel}
        rows={rows}
        placeholder={placeholder}
        value={value}
        disabled={disabled}
        onChange={onTextChange}
        onKeyDown={onKeyDown}
        onKeyUp={recomputePartial}
        onClick={recomputePartial}
        data-testid="mention-textarea-input"
        style={{ width: "100%", boxSizing: "border-box" }}
      />
      {open && (suggestions.length > 0 || loading) && (
        <ul
          role="listbox"
          aria-label="Mention suggestions"
          data-testid="mention-suggestions"
          style={{
            position: "absolute",
            top: "100%",
            left: 0,
            right: 0,
            zIndex: 30,
            margin: 0,
            padding: 0,
            listStyle: "none",
            background: "#fff",
            border: "1px solid #cbd5e1",
            borderRadius: 4,
            maxHeight: 220,
            overflowY: "auto",
            boxShadow: "0 4px 12px rgba(15,23,42,0.1)",
          }}
        >
          {loading && (
            <li
              style={{ padding: "6px 8px", color: "#64748b" }}
              data-testid="mention-loading"
            >
              Searching…
            </li>
          )}
          {!loading &&
            suggestions.map((s, i) => (
              <li
                key={`${s.kind}:${s.id}`}
                role="option"
                aria-selected={i === highlight}
                data-testid={`mention-suggestion-${s.handle ?? s.id}`}
                onMouseDown={(ev) => {
                  // ``onMouseDown`` (not click) so the textarea
                  // doesn't blur before we read selection state.
                  ev.preventDefault();
                  if (s.handle) insertMention(s.handle);
                }}
                style={{
                  padding: "6px 8px",
                  cursor: "pointer",
                  background:
                    i === highlight ? "#e0f2fe" : "transparent",
                  display: "flex",
                  gap: 6,
                  alignItems: "center",
                }}
              >
                <span
                  aria-label={s.kind}
                  style={{
                    fontSize: "0.7em",
                    background: s.kind === "agent" ? "#7c3aed" : "#0ea5e9",
                    color: "#fff",
                    borderRadius: 3,
                    padding: "1px 4px",
                  }}
                >
                  {s.kind === "agent" ? "A" : "U"}
                </span>
                <span>{s.display_name}</span>
                {s.handle && (
                  <span style={{ color: "#64748b", fontSize: "0.85em" }}>
                    @{s.handle}
                  </span>
                )}
              </li>
            ))}
        </ul>
      )}
    </div>
  );
}
