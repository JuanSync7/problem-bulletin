/**
 * A2b: useTypeahead hook for GlobalSearchBar.
 *
 * Manages debounced fetch against /api/search/v2 via searchTypeahead().
 * Cancels in-flight requests on new keystroke or unmount.
 *
 * Mirrors useSearchV2.ts (v2.27) cancel/abort pattern:
 * - AbortController per request, aborted before spawning the next.
 * - AbortError silently ignored; any other error surfaces as error string.
 * - Empty query short-circuits — no request fired.
 *
 * Changes from A1b stub:
 * - Debounce lowered to 150ms (required by A2b spec).
 * - Returns `combined` in addition to `directMatch`.
 * - Returns `abortRef` so callers can inspect the current AbortController.
 */
import { useState, useEffect, useRef, useCallback } from "react";
import { searchTypeahead } from "../../api/search";
import type { SearchItem, SearchArmKey } from "../../api/search";

const DEBOUNCE_MS = 150;

/** A4: entity filter value — "all" means no filter applied. */
export type TypeaheadEntityFilter = SearchArmKey | "all";

export interface UseTypeaheadOptions {
  /** A4: optional entity scope filter passed to the backend. Defaults to "all". */
  entity?: TypeaheadEntityFilter;
}

export interface UseTypeaheadResult {
  query: string;
  setQuery: (q: string) => void;
  directMatch: SearchItem | null;
  /** A2b: merged globally-ranked list from the backend (mode=typeahead). */
  combined: SearchItem[];
  isLoading: boolean;
  error: string | null;
  clear: () => void;
  /** Exposed so tests can assert signal.aborted on previous in-flight calls. */
  abortRef: React.MutableRefObject<AbortController | null>;
}

export function useTypeahead(options: UseTypeaheadOptions = {}): UseTypeaheadResult {
  const { entity = "all" } = options;
  const [query, setQueryState] = useState("");
  const [directMatch, setDirectMatch] = useState<SearchItem | null>(null);
  const [combined, setCombined] = useState<SearchItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const runFetch = useCallback((q: string) => {
    // Cancel previous in-flight request.
    if (abortRef.current) {
      abortRef.current.abort();
    }
    const controller = new AbortController();
    abortRef.current = controller;

    if (!q.trim()) {
      setDirectMatch(null);
      setCombined([]);
      setIsLoading(false);
      setError(null);
      return;
    }

    setIsLoading(true);
    setError(null);

    searchTypeahead(q, controller.signal, entity)
      .then((res) => {
        if (controller.signal.aborted) return;
        setDirectMatch(res.direct_match ?? null);
        setCombined(res.combined ?? []);
        setIsLoading(false);
      })
      .catch((err: unknown) => {
        if (
          err instanceof DOMException &&
          (err as DOMException).name === "AbortError"
        ) {
          // Silently ignore aborted requests — a newer request superseded this one.
          return;
        }
        if (controller.signal.aborted) return;
        setError(err instanceof Error ? err.message : "Search failed");
        setIsLoading(false);
      });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entity]);

  const setQuery = useCallback(
    (q: string) => {
      setQueryState(q);

      if (debounceRef.current !== null) {
        clearTimeout(debounceRef.current);
      }

      debounceRef.current = setTimeout(() => {
        runFetch(q);
      }, DEBOUNCE_MS);
    },
    [runFetch],
  );

  const clear = useCallback(() => {
    setQueryState("");
    setDirectMatch(null);
    setCombined([]);
    setIsLoading(false);
    setError(null);
    if (debounceRef.current !== null) {
      clearTimeout(debounceRef.current);
    }
    if (abortRef.current) {
      abortRef.current.abort();
    }
  }, []);

  // A4: When entity filter changes, re-run the current query immediately
  // (no debounce — entity change is an intentional UI action, not a keystroke).
  const queryRef = useRef(query);
  queryRef.current = query;

  useEffect(() => {
    const currentQ = queryRef.current;
    if (currentQ.trim()) {
      runFetch(currentQ);
    }
    // Only re-run when entity changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entity]);

  // Cancel on unmount.
  useEffect(() => {
    return () => {
      if (debounceRef.current !== null) clearTimeout(debounceRef.current);
      if (abortRef.current) abortRef.current.abort();
    };
  }, []);

  return { query, setQuery, directMatch, combined, isLoading, error, clear, abortRef };
}
