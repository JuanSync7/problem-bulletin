/**
 * A4: useRecentSearches — localStorage-backed recent-search history.
 *
 * Key: `aion.search.recents.<userId>` (falls back to "anon" when no user).
 * Cap: 5 entries, dedup by value, most-recent-first.
 *
 * Exposes:
 *   recents  — current list (up to 5)
 *   push(q)  — prepend q, dedup, cap to 5, persist
 *   clear()  — wipe the list
 */
import { useState, useCallback } from "react";

const CAP = 5;
const STORAGE_PREFIX = "aion.search.recents.";

function storageKey(userId: string): string {
  return `${STORAGE_PREFIX}${userId}`;
}

function readRecents(userId: string): string[] {
  try {
    const raw = localStorage.getItem(storageKey(userId));
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((x): x is string => typeof x === "string").slice(0, CAP);
  } catch {
    return [];
  }
}

function writeRecents(userId: string, recents: string[]): void {
  try {
    localStorage.setItem(storageKey(userId), JSON.stringify(recents));
  } catch {
    // Ignore storage errors (private browsing, quota exceeded, etc.)
  }
}

export interface UseRecentSearchesResult {
  recents: string[];
  push: (q: string) => void;
  clear: () => void;
}

export function useRecentSearches(userId: string): UseRecentSearchesResult {
  const [recents, setRecents] = useState<string[]>(() => readRecents(userId));

  const push = useCallback(
    (q: string) => {
      const trimmed = q.trim();
      if (!trimmed) return;

      setRecents((prev) => {
        // Remove existing entry (dedup), prepend, cap at CAP.
        const filtered = prev.filter((r) => r !== trimmed);
        const next = [trimmed, ...filtered].slice(0, CAP);
        writeRecents(userId, next);
        return next;
      });
    },
    [userId],
  );

  const clear = useCallback(() => {
    setRecents([]);
    writeRecents(userId, []);
  }, [userId]);

  return { recents, push, clear };
}
