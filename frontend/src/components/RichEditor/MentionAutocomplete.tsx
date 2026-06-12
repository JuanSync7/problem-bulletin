/**
 * V2a — @mention autocomplete dropdown.
 *
 * Standalone TipTap-agnostic component. Renders a controlled textarea
 * plus a popup list of project-member candidates whenever the caret sits
 * inside an `@<prefix>` token. ↓/↑ moves selection; Enter inserts the
 * candidate handle (replacing the `@<prefix>` slice in-place).
 *
 * Designed to plug into the existing RichEditor (or any text surface) via
 * the same `value` / `onChange` contract the rest of the codebase uses.
 * The dropdown markup is deliberately framework-agnostic so a follow-up
 * slice can hand it to TipTap's mention extension `suggestion.render` if
 * needed.
 */
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import {
  listMentionCandidates,
  type MentionCandidate,
} from "../../api/projects";

export interface MentionAutocompleteProps {
  projectId: string;
  value: string;
  onChange: (next: string) => void;
  placeholder?: string;
  /** Debounce window for the candidates fetch. Defaults to 150ms. */
  debounceMs?: number;
  /** Test seam: replace the candidates loader (e.g. for vitest mocks). */
  loadCandidates?: (
    projectId: string,
    prefix: string,
  ) => Promise<{ items: MentionCandidate[] }>;
}

const MENTION_RE = /@([A-Za-z0-9_-]*)$/;

interface ActiveMention {
  prefix: string;
  startIdx: number;
  endIdx: number;
}

function findActiveMention(value: string, caret: number): ActiveMention | null {
  if (caret < 1) return null;
  const upTo = value.slice(0, caret);
  const m = MENTION_RE.exec(upTo);
  if (!m) return null;
  const startIdx = caret - m[0].length;
  return { prefix: m[1] ?? "", startIdx, endIdx: caret };
}

export default function MentionAutocomplete({
  projectId,
  value,
  onChange,
  placeholder,
  debounceMs = 150,
  loadCandidates,
}: MentionAutocompleteProps) {
  const [caret, setCaret] = useState<number>(value.length);
  const [items, setItems] = useState<MentionCandidate[]>([]);
  const [activeIdx, setActiveIdx] = useState<number>(0);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  const active = useMemo(
    () => findActiveMention(value, caret),
    [value, caret],
  );

  // Debounced fetch. We use a setTimeout chain pinned to the active prefix.
  useEffect(() => {
    if (active === null) {
      setItems([]);
      setActiveIdx(0);
      return;
    }
    const prefix = active.prefix;
    let cancelled = false;
    const fetcher = loadCandidates ?? listMentionCandidates;
    const handle = window.setTimeout(() => {
      void (async () => {
        try {
          const res = await fetcher(projectId, prefix);
          if (cancelled) return;
          setItems(res.items);
          setActiveIdx(0);
        } catch (err) {
          if (!cancelled) {
            // Soft-fail: dropdown stays closed; let the host surface the error.
            setItems([]);
            // eslint-disable-next-line no-console
            console.warn("MentionAutocomplete: candidates fetch failed", err);
          }
        }
      })();
    }, debounceMs);
    return () => {
      cancelled = true;
      window.clearTimeout(handle);
    };
  }, [active, projectId, debounceMs, loadCandidates]);

  const applyCandidate = useCallback(
    (cand: MentionCandidate) => {
      if (active === null) return;
      const before = value.slice(0, active.startIdx);
      const after = value.slice(active.endIdx);
      const insert = `@${cand.handle} `;
      const next = `${before}${insert}${after}`;
      onChange(next);
      // Move caret to the end of the inserted token.
      const nextCaret = before.length + insert.length;
      // Defer to next tick so the textarea has the new value first.
      window.setTimeout(() => {
        const el = inputRef.current;
        if (el) {
          el.focus();
          el.setSelectionRange(nextCaret, nextCaret);
          setCaret(nextCaret);
        }
      }, 0);
    },
    [active, value, onChange],
  );

  const onKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (active === null || items.length === 0) return;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActiveIdx((i) => (i + 1) % items.length);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setActiveIdx((i) => (i - 1 + items.length) % items.length);
        return;
      }
      if (e.key === "Enter") {
        e.preventDefault();
        const cand = items[activeIdx];
        if (cand) applyCandidate(cand);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setItems([]);
      }
    },
    [active, items, activeIdx, applyCandidate],
  );

  const open = active !== null && items.length > 0;

  return (
    <div className="mention-autocomplete" data-testid="mention-autocomplete">
      <textarea
        ref={inputRef}
        data-testid="mention-autocomplete-input"
        className="mention-autocomplete__input"
        placeholder={placeholder}
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
          setCaret(e.target.selectionStart ?? e.target.value.length);
        }}
        onKeyDown={onKeyDown}
        onSelect={(e) => {
          const t = e.target as HTMLTextAreaElement;
          setCaret(t.selectionStart ?? t.value.length);
        }}
        rows={3}
      />
      {open ? (
        <ul
          role="listbox"
          aria-label="Mention candidates"
          className="mention-autocomplete__list"
          data-testid="mention-autocomplete-list"
        >
          {items.map((cand, i) => (
            <li
              key={`${cand.type}:${cand.id}`}
              role="option"
              aria-selected={i === activeIdx}
              data-testid={`mention-candidate-${cand.handle}`}
              className={
                i === activeIdx
                  ? "mention-autocomplete__item mention-autocomplete__item--active"
                  : "mention-autocomplete__item"
              }
              onMouseDown={(e) => {
                e.preventDefault();
                applyCandidate(cand);
              }}
            >
              <span className="mention-autocomplete__handle">
                @{cand.handle}
              </span>
              <span className="mention-autocomplete__name">
                {cand.display_name}
              </span>
              <span className="mention-autocomplete__kind">
                {cand.type === "agent" ? "agent" : "user"}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
