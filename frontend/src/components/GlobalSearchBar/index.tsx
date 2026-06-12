/**
 * A2b: GlobalSearchBar — chrome-level search with Cmd/Ctrl-K focus shortcut
 * and full typeahead dropdown UX.
 *
 * A4 additions:
 *  - <ScopeChips /> always rendered above the dropdown for entity filtering.
 *  - <RecentSearches /> shown when focused + empty input.
 *  - useRecentSearches stores/retrieves last-5 queries from localStorage.
 *  - Submitting (Enter with query) appends to recents.
 *
 * Renders a text input that:
 *  - Accepts Cmd-K (Mac) / Ctrl-K (Windows/Linux) to grab focus from anywhere.
 *  - Debounces keystrokes (150ms) and calls searchTypeahead() via useTypeahead.
 *  - Shows a dropdown with:
 *      • Optional direct-match row pinned at top.
 *      • Entity-grouped rows from `combined` (grouped by kind).
 *      • "View all results for «q»" row pinned at bottom.
 *  - ↑/↓ moves the keyboard highlight (wrapping at boundaries).
 *  - Enter on a highlighted row navigates to that entity's page.
 *  - Enter on "View all" navigates to /search?q=«q».
 *  - Enter with no highlight but a direct_match navigates to the direct match.
 *  - Esc closes the dropdown.
 */
import React, { useRef, useEffect, useCallback, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTypeahead } from "./useTypeahead";
import { useRecentSearches } from "./useRecentSearches";
import { RecentSearches } from "./RecentSearches";
import { ScopeChips } from "./ScopeChips";
import type { ScopeChipValue } from "./ScopeChips";
import { Dropdown, dropdownRowCount, resolveHrefAtIndex } from "./Dropdown";
import { useAuth } from "../../hooks/useAuth";
import "./GlobalSearchBar.css";

export function GlobalSearchBar() {
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const { user } = useAuth();
  const userId = user?.id ?? "anon";

  const [scopeEntity, setScopeEntity] = useState<ScopeChipValue>("all");

  const { query, setQuery, directMatch, combined, isLoading, error, clear } =
    useTypeahead({ entity: scopeEntity });

  const { recents, push: pushRecent } = useRecentSearches(userId);

  const [isOpen, setIsOpen] = useState(false);
  const [highlightedIndex, setHighlightedIndex] = useState(-1);
  const [isFocused, setIsFocused] = useState(false);

  // Total selectable rows (used for wrap-around arithmetic).
  const rowCount = dropdownRowCount(directMatch, combined);

  // Reset highlight whenever the query changes (new results arrived).
  useEffect(() => {
    setHighlightedIndex(-1);
  }, [query, directMatch, combined]);

  // Global Cmd/Ctrl-K shortcut to focus input.
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        inputRef.current?.focus();
        inputRef.current?.select();
        setIsOpen(true);
      }
      if (e.key === "Escape") {
        inputRef.current?.blur();
        setIsOpen(false);
        setIsFocused(false);
        setHighlightedIndex(-1);
        clear();
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [clear]);

  // When entity scope changes and a query is in progress, re-trigger.
  useEffect(() => {
    if (query.length > 0) {
      setIsOpen(true);
    }
  }, [scopeEntity, query]);

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const val = e.target.value;
      setQuery(val);
      setIsOpen(val.length > 0);
      setHighlightedIndex(-1);
    },
    [setQuery],
  );

  const handleFocus = useCallback(() => {
    setIsFocused(true);
    if (query.length > 0) setIsOpen(true);
  }, [query]);

  const handleBlur = useCallback(() => {
    // Delay close so that click events on dropdown items or recents fire first.
    setTimeout(() => {
      setIsOpen(false);
      setIsFocused(false);
    }, 150);
  }, []);

  const navigateToItem = useCallback(
    (href: string) => {
      navigate(href);
      setIsOpen(false);
      setHighlightedIndex(-1);
      clear();
    },
    [navigate, clear],
  );

  const handleRecentSelect = useCallback(
    (q: string) => {
      setQuery(q);
      setIsOpen(true);
      setHighlightedIndex(-1);
      inputRef.current?.focus();
    },
    [setQuery],
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      const showDropdown = isOpen && query.length > 0;

      if (e.key === "ArrowDown") {
        e.preventDefault();
        if (!showDropdown) return;
        setHighlightedIndex((prev) => {
          if (prev < 0) return 0;
          return (prev + 1) % rowCount;
        });
        return;
      }

      if (e.key === "ArrowUp") {
        e.preventDefault();
        if (!showDropdown) return;
        setHighlightedIndex((prev) => {
          if (prev < 0) return rowCount - 1;
          return (prev - 1 + rowCount) % rowCount;
        });
        return;
      }

      if (e.key === "Enter") {
        if (query.length > 0) {
          // Always push to recents on Enter with a non-empty query.
          pushRecent(query);
        }

        if (showDropdown && highlightedIndex >= 0) {
          // Navigate to the highlighted row.
          const href = resolveHrefAtIndex(
            highlightedIndex,
            directMatch,
            combined,
            query,
          );
          if (href) navigateToItem(href);
          return;
        }
        // Fallback: navigate to direct match if present (A1b behaviour).
        if (directMatch) {
          navigateToItem(directMatch.href);
        }
      }

      if (e.key === "Escape") {
        setIsOpen(false);
        setHighlightedIndex(-1);
        clear();
      }
    },
    [
      isOpen,
      query,
      highlightedIndex,
      rowCount,
      directMatch,
      combined,
      navigateToItem,
      clear,
      pushRecent,
    ],
  );

  const isMac =
    typeof navigator !== "undefined" &&
    navigator.platform.toUpperCase().includes("MAC");

  const showDropdown = isOpen && query.length > 0;
  const showRecents = isFocused && query.length === 0 && recents.length > 0;

  return (
    <div className="gsb">
      {/* A4: ScopeChips — always visible above input area */}
      <ScopeChips selected={scopeEntity} onChange={setScopeEntity} />

      <div className="gsb__input-wrapper">
        <span className="gsb__icon" aria-hidden="true">
          <svg
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
        </span>
        <input
          ref={inputRef}
          role="searchbox"
          aria-label="Search tickets and problems"
          type="search"
          placeholder="Search…"
          title="Search (Ctrl+K or ⌘K)"
          className="gsb__input"
          value={query}
          onChange={handleChange}
          onFocus={handleFocus}
          onBlur={handleBlur}
          onKeyDown={handleKeyDown}
          autoComplete="off"
          spellCheck={false}
        />
        {!query && (
          <span className="gsb__kbd-hint" aria-hidden="true">
            <kbd className="gsb__kbd">{isMac ? "⌘" : "Ctrl"}</kbd>
            <kbd className="gsb__kbd">K</kbd>
          </span>
        )}
      </div>

      {/* A4: Recent searches panel (focused + empty) */}
      {showRecents && (
        <div className="gsb__dropdown" role="listbox">
          <RecentSearches recents={recents} onSelect={handleRecentSelect} />
        </div>
      )}

      {/* Typeahead dropdown (when query is present) */}
      {showDropdown && (
        <Dropdown
          query={query}
          directMatch={directMatch}
          combined={combined}
          isLoading={isLoading}
          error={error}
          highlightedIndex={highlightedIndex}
          onSelect={navigateToItem}
        />
      )}
    </div>
  );
}
