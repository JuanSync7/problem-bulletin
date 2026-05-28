/**
 * WP43 — Kanban lane-height preference hook.
 *
 * Replaces the WP36 column-width preference (which became dead UI when the
 * board switched from fixed-width flex columns to a CSS grid). The lane-
 * height cap on ``.kanban-column__list`` IS still in use — this hook exposes
 * it as a user-controllable preference, persisted to localStorage under the
 * key ``kanban.laneHeight``.
 *
 * Allowed values: ``"50vh" | "70vh" | "90vh" | "unlimited"``.
 * Default: ``"70vh"`` (matches the previous hardcoded behavior).
 *
 * The CSS-variable value for ``"unlimited"`` is the literal string ``"none"``
 * so ``max-height: var(--kanban-lane-height, 70vh)`` resolves to
 * ``max-height: none`` and removes the cap entirely.
 *
 * All localStorage access is wrapped in try/catch so environments that
 * disable storage (e.g. private browsing, SSR) degrade silently.
 */

import { useCallback, useState } from "react";

export type LaneHeight = "50vh" | "70vh" | "90vh" | "unlimited";

const LS_KEY = "kanban.laneHeight";
const DEFAULT: LaneHeight = "70vh";

const VALID = new Set<string>(["50vh", "70vh", "90vh", "unlimited"]);

function readPref(): LaneHeight {
  try {
    if (typeof window === "undefined") return DEFAULT;
    const stored = window.localStorage.getItem(LS_KEY);
    if (stored && VALID.has(stored)) return stored as LaneHeight;
  } catch {
    /* storage disabled */
  }
  return DEFAULT;
}

function writePref(value: LaneHeight): void {
  try {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(LS_KEY, value);
  } catch {
    /* storage disabled */
  }
}

/**
 * Map a {@link LaneHeight} preference to the literal CSS value that should
 * be written to the ``--kanban-lane-height`` custom property. ``"unlimited"``
 * becomes ``"none"`` so the ``max-height`` rule short-circuits.
 */
export function laneHeightCssValue(pref: LaneHeight): string {
  return pref === "unlimited" ? "none" : pref;
}

export function useKanbanLaneHeight(): [LaneHeight, (next: LaneHeight) => void] {
  const [height, setHeightState] = useState<LaneHeight>(readPref);

  const setHeight = useCallback((next: LaneHeight) => {
    writePref(next);
    setHeightState(next);
  }, []);

  return [height, setHeight];
}
