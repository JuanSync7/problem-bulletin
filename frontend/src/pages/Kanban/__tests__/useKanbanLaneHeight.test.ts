/**
 * WP43 — useKanbanLaneHeight unit tests.
 *
 * Covers:
 *  1. Default value is "unlimited" when nothing is stored.
 *  2. Setter writes to localStorage and updates state.
 *  3. Re-mount reads the persisted "unlimited" value.
 *  4. An invalid stored value falls back to the default "unlimited".
 *  5. laneHeightCssValue maps "unlimited" to the literal string "none".
 */
import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import {
  useKanbanLaneHeight,
  laneHeightCssValue,
} from "../useKanbanLaneHeight";

const LS_KEY = "kanban.laneHeight";

beforeEach(() => {
  localStorage.clear();
});

describe("useKanbanLaneHeight", () => {
  it("returns '70vh' by default when no stored value exists", () => {
    const { result } = renderHook(() => useKanbanLaneHeight());
    const [height] = result.current;
    expect(height).toBe("unlimited");
  });

  it("setter writes to localStorage and updates state", () => {
    const { result } = renderHook(() => useKanbanLaneHeight());

    act(() => {
      const [, setHeight] = result.current;
      setHeight("90vh");
    });

    const [height] = result.current;
    expect(height).toBe("90vh");
    expect(localStorage.getItem(LS_KEY)).toBe("90vh");
  });

  it("re-mounting reads the persisted 'unlimited' preference", () => {
    localStorage.setItem(LS_KEY, "unlimited");

    const { result } = renderHook(() => useKanbanLaneHeight());

    const [height] = result.current;
    expect(height).toBe("unlimited");
  });

  it("falls back to '70vh' when stored value is invalid", () => {
    localStorage.setItem(LS_KEY, "99vh");

    const { result } = renderHook(() => useKanbanLaneHeight());

    const [height] = result.current;
    expect(height).toBe("unlimited");
  });

  it("laneHeightCssValue maps 'unlimited' to 'none' and passes vh values through", () => {
    expect(laneHeightCssValue("unlimited")).toBe("none");
    expect(laneHeightCssValue("50vh")).toBe("50vh");
    expect(laneHeightCssValue("70vh")).toBe("70vh");
    expect(laneHeightCssValue("90vh")).toBe("90vh");
  });
});
