/**
 * Ticketing v2 Kanban board: filtered ticket list hook.
 *
 * Composes the v2 filter surface (`project_id`, `sprint_id`, `type[]`,
 * `assignee_id`, `component_id`, `epic_id`) into a single
 * `listTickets(...)` call. Returns the same `{data, loading, error, refresh}`
 * shape as `useProjectResources` hooks. Stable filter identity (the filters
 * object can be re-created each render) is achieved by JSON-stringifying the
 * filter set as the effect dependency.
 */
import { useCallback, useEffect, useState } from "react";
import {
  listTickets,
  type ListTicketsParams,
  type TicketDTO,
} from "../api/tickets";

export interface UseTicketsResult {
  data: TicketDTO[];
  loading: boolean;
  error: Error | null;
  refresh: () => void;
}

export function useTickets(
  filters: ListTicketsParams,
  options: { enabled?: boolean } = {},
): UseTicketsResult {
  const { enabled = true } = options;
  const [data, setData] = useState<TicketDTO[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [tick, setTick] = useState(0);

  // JSON-stringify for a stable dep without forcing the caller to memoise.
  const key = JSON.stringify(filters ?? {});

  useEffect(() => {
    if (!enabled) {
      setData([]);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    listTickets(filters)
      .then((res) => {
        if (!cancelled) setData(Array.isArray(res?.items) ? res.items : []);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e : new Error(String(e)));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // filters tracked via stable JSON key
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, enabled, tick]);

  const refresh = useCallback(() => setTick((t) => t + 1), []);

  // Allow the parent to mutate the in-memory list (used by WS reconciliation
  // and drag-and-drop optimistic updates).
  return { data, loading, error, refresh };
}
