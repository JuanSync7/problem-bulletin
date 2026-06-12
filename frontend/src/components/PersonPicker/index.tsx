/**
 * PersonPicker — combobox typeahead for user/agent assignment (v2.5-WP32).
 *
 * Replaces the plain-text assignee input in TicketDetailDrawer and
 * TicketDetail. Fires a 250ms-debounced search against
 * ``GET /api/v1/people/search`` and renders a listbox with keyboard
 * navigation (ArrowUp/ArrowDown/Enter/Escape).
 *
 * Props
 * -----
 * value       - The currently selected PersonRef or null.
 * onChange    - Called with a PersonRef when the user picks one, or null when
 *               cleared.
 * kind        - "user" | "agent" | "any" (default "any" — both kinds).
 * placeholder - Input placeholder text.
 * disabled    - Disables input and clear button.
 * allowClear  - Show the x button when a value is selected.
 *
 * Accessibility
 * -------------
 * role="combobox" on the input; role="listbox" on the dropdown;
 * role="option" on each row; aria-expanded / aria-activedescendant wired.
 * Full ARIA combobox 1.1 pattern is overkill for this WP — essentials only.
 *
 * No external deps — no react-select, no downshift.
 */
import React, {
  useEffect,
  useId,
  useRef,
  useState,
} from "react";
import { searchPeople, type PersonRef } from "../../api/people";
import "./PersonPicker.css";

const DEBOUNCE_MS = 250;

export interface PersonPickerProps {
  value: PersonRef | null;
  onChange: (p: PersonRef | null) => void;
  kind?: "user" | "agent" | "any";
  placeholder?: string;
  disabled?: boolean;
  allowClear?: boolean;
}

function KindBadge({ kind }: { kind: string }) {
  return (
    <span
      className={`pp__badge pp__badge--${kind}`}
      aria-label={kind}
      title={kind}
    >
      {kind === "agent" ? "A" : "U"}
    </span>
  );
}

export function PersonPicker({
  value,
  onChange,
  kind = "any",
  placeholder = "Search people…",
  disabled = false,
  allowClear = false,
}: PersonPickerProps) {
  const uid = useId();
  const listboxId = `${uid}-listbox`;

  const [query, setQuery] = useState("");
  const [results, setResults] = useState<PersonRef[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  // activeIndex tracks the keyboard-focused option (-1 = none).
  const [activeIndex, setActiveIndex] = useState(-1);

  const containerRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  // Close on outside click.
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (!containerRef.current) return;
      if (!containerRef.current.contains(e.target as Node)) {
        setOpen(false);
        setActiveIndex(-1);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  // Debounced search — only fires when open and query is non-empty.
  useEffect(() => {
    if (!open || query.trim() === "") {
      setResults([]);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    const timer = window.setTimeout(() => {
      const apiKind: string | undefined =
        kind === "any" ? undefined : kind;
      searchPeople({ q: query.trim(), kind: apiKind as "user" | "agent" | undefined, limit: 10 })
        .then((res) => {
          if (cancelled) return;
          setResults(res.items ?? []);
          setActiveIndex(-1);
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
  }, [query, open, kind]);

  const pick = (person: PersonRef) => {
    onChange(person);
    setOpen(false);
    setQuery("");
    setResults([]);
    setActiveIndex(-1);
  };

  const clear = () => {
    onChange(null);
    setQuery("");
    setResults([]);
    setActiveIndex(-1);
    // Re-focus input after clearing.
    inputRef.current?.focus();
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!open) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        setOpen(true);
        return;
      }
    }
    if (e.key === "Escape") {
      setOpen(false);
      setActiveIndex(-1);
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, results.length - 1));
      return;
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, -1));
      return;
    }
    if (e.key === "Enter") {
      if (activeIndex >= 0 && activeIndex < results.length) {
        e.preventDefault();
        pick(results[activeIndex]);
      }
      return;
    }
    if (e.key === "Backspace" && query === "" && value) {
      clear();
    }
  };

  const activeOptionId =
    activeIndex >= 0 ? `${uid}-option-${activeIndex}` : undefined;

  const chipLabel = value
    ? value.display_name || `@${value.handle}` || value.id.slice(0, 8)
    : null;

  // Show chip when a value is selected and the dropdown is not open.
  if (value && !open) {
    return (
      <div
        ref={containerRef}
        className="pp"
        data-testid="person-picker"
      >
        <div className="pp__chip">
          <KindBadge kind={value.kind} />
          <span className="pp__chip-label">
            {chipLabel}
            {value.handle && (
              <span className="pp__chip-handle"> @{value.handle}</span>
            )}
          </span>
          {value.kind === "agent" && (
            <span
              className="person-picker-chip__type-badge"
              aria-label="agent"
            >
              agent
            </span>
          )}
          {allowClear && (
            <button
              type="button"
              className="pp__chip-clear"
              aria-label="Clear selection"
              disabled={disabled}
              onClick={clear}
              data-testid="person-picker-clear"
            >
              x
            </button>
          )}
          <button
            type="button"
            className="pp__chip-clear"
            aria-label="Change assignee"
            disabled={disabled}
            onClick={() => setOpen(true)}
            data-testid="person-picker-change"
            style={{ fontSize: "0.8em", color: "var(--color-accent, #0ea5e9)" }}
          >
            change
          </button>
        </div>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className="pp"
      data-testid="person-picker"
    >
      <input
        ref={inputRef}
        type="text"
        role="combobox"
        aria-expanded={open}
        aria-autocomplete="list"
        aria-controls={open ? listboxId : undefined}
        aria-activedescendant={activeOptionId}
        className="pp__input"
        data-testid="person-picker-input"
        placeholder={placeholder}
        value={query}
        disabled={disabled}
        onFocus={() => setOpen(true)}
        onChange={(e) => {
          setQuery(e.target.value);
          if (!open) setOpen(true);
        }}
        onKeyDown={onKeyDown}
      />

      {open && (
        <ul
          id={listboxId}
          className="pp__listbox"
          role="listbox"
        >
          {loading && (
            <li className="pp__hint" role="presentation">
              <span className="pp__loading-dots" aria-label="Searching">
                <span />
                <span />
                <span />
              </span>
            </li>
          )}
          {!loading && query.trim() === "" && (
            <li className="pp__hint" role="presentation">
              Type to search…
            </li>
          )}
          {!loading && query.trim() !== "" && results.length === 0 && (
            <li className="pp__hint" role="presentation">
              No matches
            </li>
          )}
          {results.map((person, idx) => (
            <li
              key={`${person.kind}:${person.id}`}
              id={`${uid}-option-${idx}`}
              role="option"
              aria-selected={
                value !== null &&
                value.id === person.id &&
                value.kind === person.kind
              }
              className={`pp__option${activeIndex === idx ? " pp__option--active" : ""}`}
              data-kind={person.kind}
              onMouseDown={(e) => {
                // Prevent blur on input before click registers.
                e.preventDefault();
                pick(person);
              }}
            >
              <div className="pp__option-main">
                <KindBadge kind={person.kind} />
                <span className="pp__option-name">{person.display_name}</span>
              </div>
              {person.handle && (
                <div className="pp__option-sub">@{person.handle}</div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
