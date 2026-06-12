/**
 * WP64 — useSearchV2 hook unit tests.
 *
 * Covers the lifecycle invariants that previously lived inline in Search.tsx:
 * - Empty query short-circuits: no fetch is fired, data stays null, hasSearched=false.
 * - A real query triggers searchV2 and sets data/hasSearched.
 * - Rapid input changes abort the in-flight request (only the latest result wins).
 * - Unmount aborts any pending request.
 */
/* eslint-disable @typescript-eslint/no-explicit-any */
import { renderHook, waitFor, act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useSearchV2 } from "../useSearchV2";

const mockSearchV2 = vi.fn();

vi.mock("../../api/search", () => ({
  searchV2: (...args: unknown[]) => mockSearchV2(...args),
}));

const baseFilters = {
  problemStatus: "",
  problemCategoryId: "",
  ticketStatus: "",
  ticketProjectId: "",
  componentProjectId: "",
};

const baseArgs = {
  query: "",
  entity: "all" as const,
  filters: baseFilters,
  page: 0,
  pageSize: 25,
  allTabPreviewLimit: 5,
};

const fakeResponse = {
  problems: { items: [], total: 0, next_cursor: null },
  tickets: { items: [], total: 0, next_cursor: null },
  components: { items: [], total: 0, next_cursor: null },
  labels: { items: [], total: 0, next_cursor: null },
  users: { items: [], total: 0, next_cursor: null },
};

describe("useSearchV2", () => {
  beforeEach(() => {
    mockSearchV2.mockReset();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("does not fire a request when query is empty", () => {
    renderHook(() => useSearchV2(baseArgs));
    expect(mockSearchV2).not.toHaveBeenCalled();
  });

  it("fires searchV2 and stores data when query is non-empty", async () => {
    mockSearchV2.mockResolvedValueOnce(fakeResponse);
    const { result } = renderHook(() =>
      useSearchV2({ ...baseArgs, query: "hello" }),
    );

    await waitFor(() => expect(result.current.data).toEqual(fakeResponse));
    expect(result.current.hasSearched).toBe(true);
    expect(result.current.isLoading).toBe(false);
    expect(mockSearchV2).toHaveBeenCalledTimes(1);
    expect(mockSearchV2).toHaveBeenCalledWith(
      expect.objectContaining({ q: "hello", entity: "all" }),
    );
  });

  it("aborts the previous request when args change mid-flight", async () => {
    // First call never resolves; second call resolves.
    let firstAbort: AbortSignal | undefined;
    mockSearchV2.mockImplementationOnce((args: { signal?: AbortSignal }) => {
      firstAbort = args.signal;
      return new Promise(() => {}); // never resolves
    });
    mockSearchV2.mockResolvedValueOnce(fakeResponse);

    const { result, rerender } = renderHook(
      (args: typeof baseArgs) => useSearchV2(args),
      { initialProps: { ...baseArgs, query: "first" } },
    );

    // Swap to a new query — must abort the first call.
    rerender({ ...baseArgs, query: "second" });

    await waitFor(() => expect(result.current.data).toEqual(fakeResponse));
    expect(firstAbort?.aborted).toBe(true);
    expect(mockSearchV2).toHaveBeenCalledTimes(2);
  });

  it("does not surface AbortError as an error state", async () => {
    mockSearchV2.mockImplementationOnce(() => {
      throw new DOMException("aborted", "AbortError");
    });
    const { result } = renderHook(() =>
      useSearchV2({ ...baseArgs, query: "x" }),
    );
    // Give the hook a microtask to settle.
    await act(async () => {
      await Promise.resolve();
    });
    expect(result.current.error).toBeNull();
  });

  // -------------------------------------------------------------------------
  // WP08 — cursor stack behaviour
  // -------------------------------------------------------------------------

  it("WP08: loadNext() re-fires searchV2 with the active arm's next_cursor", async () => {
    mockSearchV2.mockResolvedValueOnce({
      tickets: { items: [{ id: "t1" } as any], total: 50, next_cursor: "CUR-2" },
    });
    mockSearchV2.mockResolvedValueOnce({
      tickets: { items: [{ id: "t2" } as any], total: 50, next_cursor: "CUR-3" },
    });

    const { result } = renderHook(() =>
      useSearchV2({ ...baseArgs, query: "x", entity: "tickets" as any }),
    );

    await waitFor(() => expect(result.current.hasNext).toBe(true));
    expect(result.current.hasPrev).toBe(false);

    act(() => {
      result.current.loadNext();
    });

    await waitFor(() => expect(mockSearchV2).toHaveBeenCalledTimes(2));
    expect(mockSearchV2.mock.calls[1][0]).toEqual(
      expect.objectContaining({ entity: "tickets", cursor: "CUR-2" }),
    );
    await waitFor(() => expect(result.current.hasPrev).toBe(true));
  });

  it("WP08: loadPrev() pops the cursor stack and re-fetches the previous page", async () => {
    mockSearchV2.mockResolvedValueOnce({
      tickets: { items: [{ id: "t1" } as any], total: 50, next_cursor: "CUR-2" },
    });
    mockSearchV2.mockResolvedValueOnce({
      tickets: { items: [{ id: "t2" } as any], total: 50, next_cursor: "CUR-3" },
    });
    mockSearchV2.mockResolvedValueOnce({
      tickets: { items: [{ id: "t1" } as any], total: 50, next_cursor: "CUR-2" },
    });

    const { result } = renderHook(() =>
      useSearchV2({ ...baseArgs, query: "x", entity: "tickets" as any }),
    );

    await waitFor(() => expect(result.current.hasNext).toBe(true));
    act(() => result.current.loadNext());
    await waitFor(() => expect(mockSearchV2).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(result.current.hasPrev).toBe(true));

    act(() => result.current.loadPrev());

    await waitFor(() => expect(mockSearchV2).toHaveBeenCalledTimes(3));
    // Page-1 refetch must omit `cursor`.
    const call3 = mockSearchV2.mock.calls[2][0];
    expect(call3).toEqual(expect.objectContaining({ entity: "tickets" }));
    expect(call3.cursor).toBeUndefined();

    await waitFor(() => expect(result.current.hasPrev).toBe(false));
  });

  it("WP08: changing query resets the cursor stack", async () => {
    mockSearchV2.mockResolvedValue({
      tickets: { items: [], total: 0, next_cursor: "CUR-2" },
    });

    const { result, rerender } = renderHook(
      (args: typeof baseArgs) => useSearchV2(args),
      { initialProps: { ...baseArgs, query: "first", entity: "tickets" as any } },
    );

    await waitFor(() => expect(result.current.hasNext).toBe(true));
    act(() => result.current.loadNext());
    await waitFor(() => expect(result.current.hasPrev).toBe(true));

    // Change the query — stack must reset, hasPrev returns to false.
    rerender({ ...baseArgs, query: "second", entity: "tickets" as any });

    await waitFor(() => expect(result.current.hasPrev).toBe(false));
  });

  // -------------------------------------------------------------------------
  // WP10 (v2.12) — refreshTotal + totalAuthority
  // -------------------------------------------------------------------------

  it("WP10: refreshTotal preserves the cursor and re-fires with refresh_total=true", async () => {
    // Page 1: snapshot total, has next_cursor.
    mockSearchV2.mockResolvedValueOnce({
      tickets: {
        items: [{ id: "t1" } as any],
        total: 50,
        next_cursor: "CUR-2",
        total_authority: "snapshot",
      },
    });
    // Page 2 (after loadNext): snapshot total, has next_cursor.
    mockSearchV2.mockResolvedValueOnce({
      tickets: {
        items: [{ id: "t2" } as any],
        total: 50,
        next_cursor: "CUR-3",
        total_authority: "snapshot",
      },
    });
    // Page 2 (after refreshTotal): live total, SAME cursor.
    mockSearchV2.mockResolvedValueOnce({
      tickets: {
        items: [{ id: "t2" } as any],
        total: 47,
        next_cursor: "CUR-3",
        total_authority: "live",
      },
    });

    const { result } = renderHook(() =>
      useSearchV2({ ...baseArgs, query: "x", entity: "tickets" as any }),
    );

    await waitFor(() => expect(result.current.hasNext).toBe(true));
    expect(result.current.totalAuthority).toBe("snapshot");

    act(() => result.current.loadNext());
    await waitFor(() => expect(mockSearchV2).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(result.current.hasPrev).toBe(true));

    // Snapshot the cursor used by the page-2 fetch.
    const page2Cursor = mockSearchV2.mock.calls[1][0].cursor;
    expect(page2Cursor).toBe("CUR-2");

    act(() => result.current.refreshTotal());

    await waitFor(() => expect(mockSearchV2).toHaveBeenCalledTimes(3));
    const refreshCall = mockSearchV2.mock.calls[2][0];
    expect(refreshCall.refresh_total).toBe(true);
    // Cursor unchanged — refresh does NOT advance the chain.
    expect(refreshCall.cursor).toBe("CUR-2");
    // Cursor stack still has the previous page available.
    expect(result.current.hasPrev).toBe(true);

    await waitFor(() => expect(result.current.totalAuthority).toBe("live"));
  });

  it("WP10/WP06: totalAuthority reflects the active arm's value and collapses across arms for entity=all", async () => {
    mockSearchV2.mockResolvedValueOnce({
      problems: { items: [], total: 1, next_cursor: null, total_authority: "live" },
      tickets: { items: [], total: 2, next_cursor: null, total_authority: "snapshot" },
      components: { items: [], total: 0, next_cursor: null, total_authority: "live" },
      labels: { items: [], total: 0, next_cursor: null, total_authority: "live" },
      users: { items: [], total: 0, next_cursor: null, total_authority: "live" },
    });
    const allHook = renderHook(() =>
      useSearchV2({ ...baseArgs, query: "x" }),
    );
    await waitFor(() => expect(allHook.result.current.data).not.toBeNull());
    // WP06: entity=all → "snapshot" when ANY arm is snapshot (tickets here).
    expect(allHook.result.current.totalAuthority).toBe("snapshot");
    allHook.unmount();

    mockSearchV2.mockResolvedValueOnce({
      tickets: {
        items: [{ id: "t1" } as any],
        total: 10,
        next_cursor: null,
        total_authority: "live",
      },
    });
    const ticketsHook = renderHook(() =>
      useSearchV2({ ...baseArgs, query: "x", entity: "tickets" as any }),
    );
    await waitFor(() =>
      expect(ticketsHook.result.current.totalAuthority).toBe("live"),
    );

    // Missing total_authority on arm → defaults to "snapshot".
    mockSearchV2.mockResolvedValueOnce({
      problems: { items: [{ id: "p1" } as any], total: 3, next_cursor: null },
    });
    const problemsHook = renderHook(() =>
      useSearchV2({ ...baseArgs, query: "y", entity: "problems" as any }),
    );
    await waitFor(() =>
      expect(problemsHook.result.current.totalAuthority).toBe("snapshot"),
    );
  });

  it("WP06: entity=all totalAuthority is 'live' only when every arm reports live, and refreshTotal broadcasts refresh_total=true", async () => {
    // Page 1 — every arm snapshot.
    mockSearchV2.mockResolvedValueOnce({
      problems: { items: [], total: 1, next_cursor: null, total_authority: "snapshot" },
      tickets: { items: [], total: 2, next_cursor: null, total_authority: "snapshot" },
      components: { items: [], total: 3, next_cursor: null, total_authority: "snapshot" },
      labels: { items: [], total: 4, next_cursor: null, total_authority: "snapshot" },
      users: { items: [], total: 5, next_cursor: null, total_authority: "snapshot" },
    });
    // Page 2 (after refreshTotal) — every arm live, refreshed counts.
    mockSearchV2.mockResolvedValueOnce({
      problems: { items: [], total: 0, next_cursor: null, total_authority: "live" },
      tickets: { items: [], total: 1, next_cursor: null, total_authority: "live" },
      components: { items: [], total: 2, next_cursor: null, total_authority: "live" },
      labels: { items: [], total: 3, next_cursor: null, total_authority: "live" },
      users: { items: [], total: 4, next_cursor: null, total_authority: "live" },
    });

    const { result } = renderHook(() =>
      useSearchV2({ ...baseArgs, query: "x" }),
    );
    await waitFor(() => expect(result.current.data).not.toBeNull());
    expect(result.current.totalAuthority).toBe("snapshot");

    act(() => result.current.refreshTotal());
    await waitFor(() => expect(mockSearchV2).toHaveBeenCalledTimes(2));
    const refreshCall = mockSearchV2.mock.calls[1][0];
    expect(refreshCall.refresh_total).toBe(true);
    expect(refreshCall.entity).toBe("all");

    await waitFor(() => expect(result.current.totalAuthority).toBe("live"));
  });

  it("aborts the in-flight request on unmount", () => {
    let signal: AbortSignal | undefined;
    mockSearchV2.mockImplementationOnce((args: { signal?: AbortSignal }) => {
      signal = args.signal;
      return new Promise(() => {});
    });
    const { unmount } = renderHook(() =>
      useSearchV2({ ...baseArgs, query: "x" }),
    );
    unmount();
    expect(signal?.aborted).toBe(true);
  });
});
