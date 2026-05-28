/**
 * useSearchV2 — encapsulates the /api/search/v2 fetch lifecycle.
 *
 * WP64: extracted from Search.tsx so the same hook can be reused by future
 * surfaces (typeahead in the global nav, embedded entity-pickers) and so the
 * abort/error/loading bookkeeping has one home.
 *
 * WP08 (v2.10): cursor-driven Next/Prev for single-arm tabs. The hook
 * maintains an internal cursor stack — `loadNext()` pushes the active arm's
 * `next_cursor`, `loadPrev()` pops back. The stack resets whenever the
 * query, entity, filter set, or page-size changes.
 *
 * Behaviour preserved from the original Search.tsx inline implementation:
 * - Empty query short-circuits to `data=null` and no request is fired.
 * - Each new input aborts the in-flight request via AbortController.
 * - Aborted requests don't flip loading off (caller has already moved on).
 * - On unmount, any in-flight request is aborted.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import {
  searchV2,
  type SearchEntity,
  type SearchV2Response,
} from "../api/search";

export interface SearchV2Filters {
  problemStatus: string;
  problemCategoryId: string;
  ticketStatus: string;
  ticketProjectId: string;
  componentProjectId: string;
}

export interface UseSearchV2Args {
  query: string;
  entity: SearchEntity;
  filters: SearchV2Filters;
  page: number;
  pageSize: number;
  allTabPreviewLimit: number;
}

export interface UseSearchV2Result {
  data: SearchV2Response | null;
  isLoading: boolean;
  error: string | null;
  hasSearched: boolean;
  /** WP08: true when the active arm has a next_cursor to follow. */
  hasNext: boolean;
  /** WP08: true when the cursor stack has a previous page to return to. */
  hasPrev: boolean;
  /** WP08: advance to the next page using the active arm's next_cursor. */
  loadNext: () => void;
  /** WP08: return to the previous page on the cursor stack. */
  loadPrev: () => void;
  /**
   * WP10 (v2.12): authority of the active arm's `total` — "snapshot" means
   * the total was pinned at cursor-mint time; "live" means it reflects a
   * fresh count. `null` when no data is available yet.
   *
   * WP06 (v2.13): for `entity="all"`, collapses the per-arm authorities
   * into a single binary: `"snapshot"` if ANY present arm reports
   * snapshot, `"live"` if EVERY present arm reports live. This is what
   * drives the All-tab "Refresh counts" banner — clicking the button
   * fires one request with `refresh_total=true` and the backend
   * broadcasts the refresh to every arm.
   *
   * The backend omits the field on older deploys; treat absent as
   * "snapshot" upstream — exposed here as the raw value.
   */
  totalAuthority: "snapshot" | "live" | null;
  /**
   * WP10 (v2.12): re-fire searchV2 with refresh_total=true on the current
   * cursor position. Preserves the cursor stack (no reset). Used by the
   * Search page's snapshot banner to force a live re-count without
   * advancing the chain.
   */
  refreshTotal: () => void;
}

type CursorStackEntry = string | undefined;

function isSingleArm(entity: SearchEntity): boolean {
  return entity !== "all";
}

export function useSearchV2(args: UseSearchV2Args): UseSearchV2Result {
  const { query, entity, filters, page, pageSize, allTabPreviewLimit } = args;

  const [data, setData] = useState<SearchV2Response | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasSearched, setHasSearched] = useState(false);

  // WP08 cursor state — kept in state (not ref) so `hasPrev` derives cleanly
  // and React re-renders correctly when loadNext/loadPrev mutate the stack.
  // Note: stack changes from the args-reset effect are coalesced with the
  // args change itself by mutating the ref synchronously *during* the render
  // path (via a sentinel), avoiding a double fetch.
  const [cursorStack, setCursorStack] = useState<CursorStackEntry[]>([undefined]);

  // WP10 (v2.12): bumping this nonce re-fires the fetch effect with
  // refresh_total=true on the current cursor position. The cursor stack is
  // intentionally NOT touched — refreshTotal() is a count-refresh, not a
  // navigation. We consume `refreshNonce > 0` in the effect body to decide
  // whether to pass refresh_total through to searchV2.
  const [refreshNonce, setRefreshNonce] = useState(0);
  const refreshPendingRef = useRef(false);

  // Snapshot of the args that produced the current stack. When args drift,
  // we reset the stack *synchronously inside the fetch effect* — that way
  // the fetch and the reset happen in one effect pass.
  const argsKeyRef = useRef<string>("");
  const argsKey = JSON.stringify({
    query,
    entity,
    filters,
    pageSize,
  });

  const abortRef = useRef<AbortController | null>(null);

  // -------------------------------------------------------------------------
  // Fetch effect — fires when args change or the cursor stack changes.
  // -------------------------------------------------------------------------
  useEffect(() => {
    if (!query) {
      setData(null);
      setHasSearched(false);
      return;
    }

    // If args have drifted since the last fetch, reset the stack first so
    // this fetch is page 1 of the new query. Detect via argsKey; mutate
    // state with a functional setter so concurrent renders see the reset.
    let stackForRequest = cursorStack;
    if (argsKeyRef.current !== argsKey) {
      argsKeyRef.current = argsKey;
      stackForRequest = [undefined];
      // Only schedule the state update if we're not already at the reset
      // value — avoids a useless re-render after loadNext/loadPrev resets.
      if (cursorStack.length !== 1 || cursorStack[0] !== undefined) {
        setCursorStack([undefined]);
        // Bail — the state update will retrigger this effect with the
        // freshly-reset stack. Avoids firing two requests in quick succession.
        return;
      }
    }

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setIsLoading(true);
    setError(null);
    setHasSearched(true);

    const cursorForRequest = stackForRequest[stackForRequest.length - 1];

    // WP10: consume the refresh-token. We check the ref (set by
    // refreshTotal()) rather than nonce-vs-prev because args-driven
    // refetches (query/cursor change) should NOT inherit refresh_total —
    // it only sticks for the one fetch the user explicitly requested.
    const wantsRefresh = refreshPendingRef.current;
    refreshPendingRef.current = false;

    (async () => {
      try {
        const result = await searchV2({
          q: query,
          entity,
          problem_status: filters.problemStatus || undefined,
          problem_category_id: filters.problemCategoryId || undefined,
          ticket_status: filters.ticketStatus || undefined,
          ticket_project_id: filters.ticketProjectId || undefined,
          component_project_id: filters.componentProjectId || undefined,
          limit: entity === "all" ? allTabPreviewLimit : pageSize,
          offset:
            entity === "all" || cursorForRequest !== undefined
              ? 0
              : page * pageSize,
          cursor: isSingleArm(entity) ? cursorForRequest : undefined,
          refresh_total: wantsRefresh ? true : undefined,
          signal: controller.signal,
        });
        if (!controller.signal.aborted) {
          setData(result);
          setIsLoading(false);
        }
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        if (!controller.signal.aborted) {
          setError(err instanceof Error ? err.message : "Search failed");
          setIsLoading(false);
        }
      }
    })();
  }, [
    query,
    entity,
    filters.problemStatus,
    filters.problemCategoryId,
    filters.ticketStatus,
    filters.ticketProjectId,
    filters.componentProjectId,
    page,
    pageSize,
    allTabPreviewLimit,
    cursorStack,
    argsKey,
    refreshNonce,
  ]);

  // Abort any in-flight request on unmount.
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  // -------------------------------------------------------------------------
  // Cursor controls
  // -------------------------------------------------------------------------
  const activeArm =
    isSingleArm(entity) && data
      ? data[entity as keyof SearchV2Response] ?? null
      : null;
  const nextCursor = activeArm?.next_cursor ?? null;

  const hasNext = isSingleArm(entity) && !!nextCursor;
  const hasPrev = isSingleArm(entity) && cursorStack.length > 1;

  const loadNext = useCallback(() => {
    if (!isSingleArm(entity) || !nextCursor) return;
    setCursorStack((stack) => [...stack, nextCursor]);
  }, [entity, nextCursor]);

  const loadPrev = useCallback(() => {
    setCursorStack((stack) => (stack.length > 1 ? stack.slice(0, -1) : stack));
  }, []);

  // WP10: refreshTotal — re-fire the same fetch with refresh_total=true
  // on the active cursor. We set the pending-ref synchronously so the
  // next effect pass sees it, then bump the nonce to trigger that pass.
  const refreshTotal = useCallback(() => {
    refreshPendingRef.current = true;
    setRefreshNonce((n) => n + 1);
  }, []);

  // WP10: derive total_authority of the active arm. For entity=all
  // (WP06 v2.13) collapse per-arm authorities into a single binary:
  // "snapshot" if any present arm is snapshot, "live" only when every
  // present arm is live. `null` only when no data has loaded yet.
  let totalAuthority: "snapshot" | "live" | null;
  if (isSingleArm(entity)) {
    totalAuthority = activeArm ? activeArm.total_authority ?? "snapshot" : null;
  } else if (data) {
    const armKeys: (keyof SearchV2Response)[] = [
      "problems",
      "tickets",
      "components",
      "labels",
      "users",
    ];
    const present = armKeys
      .map((k) => data[k])
      .filter((a): a is NonNullable<typeof a> => !!a);
    if (present.length === 0) {
      totalAuthority = null;
    } else {
      const anySnapshot = present.some(
        (arm) => (arm.total_authority ?? "snapshot") === "snapshot",
      );
      totalAuthority = anySnapshot ? "snapshot" : "live";
    }
  } else {
    totalAuthority = null;
  }

  return {
    data,
    isLoading,
    error,
    hasSearched,
    hasNext,
    hasPrev,
    loadNext,
    loadPrev,
    totalAuthority,
    refreshTotal,
  };
}
