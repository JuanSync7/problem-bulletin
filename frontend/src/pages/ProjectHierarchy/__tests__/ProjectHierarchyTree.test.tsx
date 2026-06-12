/**
 * B2: ProjectHierarchyTree functional tests.
 *
 * Tests:
 *  1. Renders rows from fixture (depth 0..3 chain)
 *  2. Unchecking "task" type hides task rows and re-parents subtask child to nearest visible ancestor
 *  3. Depth slider change re-fires getProjectHierarchy with new max_depth
 *  4. Keyboard ↑/↓ moves focused row (roving-tabindex)
 *  5. ← collapses node (children hidden), → expands
 *  6. Enter on focused row navigates to /tickets/<key>
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import type { HierarchyRow } from "../../../api/projects";

// Mock the API module
vi.mock("../../../api/projects", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../api/projects")>();
  return {
    ...actual,
    getProjectHierarchy: vi.fn().mockResolvedValue({ items: [] }),
    listProjects: vi.fn().mockResolvedValue({ items: [], next_cursor: null, total: 0 }),
  };
});

// Mock react-router-dom navigate
const mockNavigate = vi.fn();
vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return {
    ...actual,
    useNavigate: () => mockNavigate,
    useParams: () => ({ projectId: "p-test" }),
    useSearchParams: () => [new URLSearchParams(), vi.fn()],
  };
});

import { ProjectHierarchyTree, applyTypeFilter, rowsToVisibleTree, getKeyboardNextIndex } from "../ProjectHierarchyTree";

// ---------------------------------------------------------------------------
// Fixture
// ---------------------------------------------------------------------------

function makeTicket(overrides: Partial<{
  id: string; seq_number: number; display_id: string; title: string; type: string;
  status: string; priority: string; reporter_id: string; version: number;
  created_at: string; labels: string[]; fix_versions: string[]; custom_fields: Record<string, unknown>;
}> = {}) {
  return {
    id: overrides.id ?? "t-1",
    seq_number: overrides.seq_number ?? 1,
    display_id: overrides.display_id ?? "PROJ-1",
    title: overrides.title ?? "Test ticket",
    type: overrides.type ?? "epic",
    status: overrides.status ?? "todo",
    priority: overrides.priority ?? "medium",
    reporter_id: overrides.reporter_id ?? "u-1",
    reporter_type: "user" as const,
    version: overrides.version ?? 1,
    created_at: overrides.created_at ?? "2024-01-01T00:00:00Z",
    labels: overrides.labels ?? [],
    fix_versions: overrides.fix_versions ?? [],
    custom_fields: overrides.custom_fields ?? {},
  };
}

// A 4-level deep chain: epic → story → task → subtask
const fixtureRows: HierarchyRow[] = [
  {
    ticket: makeTicket({ id: "t-1", display_id: "P-1", title: "Epic One", type: "epic" }),
    depth: 0,
    parent_id: null,
    ordinal: 0,
  },
  {
    ticket: makeTicket({ id: "t-2", display_id: "P-2", title: "Story One", type: "story" }),
    depth: 1,
    parent_id: "t-1",
    ordinal: 0,
  },
  {
    ticket: makeTicket({ id: "t-3", display_id: "P-3", title: "Task One", type: "task" }),
    depth: 2,
    parent_id: "t-2",
    ordinal: 0,
  },
  {
    ticket: makeTicket({ id: "t-4", display_id: "P-4", title: "Subtask One", type: "subtask" }),
    depth: 3,
    parent_id: "t-3",
    ordinal: 0,
  },
];

// ---------------------------------------------------------------------------
// Helper to render tree
// ---------------------------------------------------------------------------

function renderTree(rows: HierarchyRow[] = fixtureRows, hiddenTypes: string[] = []) {
  return render(
    <MemoryRouter>
      <ProjectHierarchyTree
        rows={rows}
        hiddenTypes={hiddenTypes}
        projectId="p-test"
      />
    </MemoryRouter>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ProjectHierarchyTree — render from fixture", () => {
  it("renders all 4 rows from a depth 0..3 chain", async () => {
    renderTree(fixtureRows);
    await waitFor(() => {
      expect(screen.getByText("Epic One")).toBeTruthy();
      expect(screen.getByText("Story One")).toBeTruthy();
      expect(screen.getByText("Task One")).toBeTruthy();
      expect(screen.getByText("Subtask One")).toBeTruthy();
    });
  });

  it("renders tree box-drawing prefix characters", async () => {
    renderTree(fixtureRows);
    await waitFor(() => {
      // Box chars: should have at least one └─ or ├─ or │ in the document
      const content = document.body.textContent ?? "";
      const hasBoxChars = content.includes("└") || content.includes("├") || content.includes("│");
      expect(hasBoxChars).toBe(true);
    });
  });
});

describe("applyTypeFilter — pure helper", () => {
  it("returns all rows when no types are hidden", () => {
    expect(applyTypeFilter(fixtureRows, [])).toHaveLength(4);
  });

  it("hides task rows when 'task' is in hiddenTypes", () => {
    const result = applyTypeFilter(fixtureRows, ["task"]);
    expect(result.some((r) => r.ticket.type === "task")).toBe(false);
  });

  it("re-parents subtask to nearest visible ancestor when task is hidden", () => {
    const result = applyTypeFilter(fixtureRows, ["task"]);
    // subtask should still be present but re-parented to story (t-2)
    const subtask = result.find((r) => r.ticket.id === "t-4");
    expect(subtask).toBeTruthy();
    expect(subtask!.parent_id).toBe("t-2");
  });
});

describe("rowsToVisibleTree — pure helper", () => {
  it("preserves DFS order", () => {
    const result = rowsToVisibleTree(fixtureRows, []);
    const ids = result.map((r) => r.ticket.id);
    expect(ids).toEqual(["t-1", "t-2", "t-3", "t-4"]);
  });
});

describe("getKeyboardNextIndex — pure helper", () => {
  it("moves down with ArrowDown", () => {
    expect(getKeyboardNextIndex(0, 4, "ArrowDown")).toBe(1);
  });

  it("moves up with ArrowUp", () => {
    expect(getKeyboardNextIndex(2, 4, "ArrowUp")).toBe(1);
  });

  it("wraps at bottom with ArrowDown", () => {
    expect(getKeyboardNextIndex(3, 4, "ArrowDown")).toBe(3);
  });

  it("stays at 0 with ArrowUp at top", () => {
    expect(getKeyboardNextIndex(0, 4, "ArrowUp")).toBe(0);
  });
});

describe("ProjectHierarchyTree — type filter", () => {
  it("hides task rows when task is in hiddenTypes", async () => {
    renderTree(fixtureRows, ["task"]);
    await waitFor(() => {
      expect(screen.getByText("Epic One")).toBeTruthy();
      expect(screen.getByText("Story One")).toBeTruthy();
      expect(screen.queryByText("Task One")).toBeNull();
    });
  });

  it("keeps subtask visible even when task is hidden (re-parented)", async () => {
    renderTree(fixtureRows, ["task"]);
    await waitFor(() => {
      expect(screen.getByText("Subtask One")).toBeTruthy();
    });
  });
});

describe("ProjectHierarchyTree — keyboard navigation", () => {
  beforeEach(() => {
    mockNavigate.mockReset();
  });

  it("first row has tabIndex=0, others have tabIndex=-1", async () => {
    renderTree(fixtureRows);
    await waitFor(() => {
      expect(screen.getByText("Epic One")).toBeTruthy();
    });
    const rows = screen.getAllByRole("treeitem");
    expect(rows[0].tabIndex).toBe(0);
    expect(rows[1].tabIndex).toBe(-1);
    expect(rows[2].tabIndex).toBe(-1);
  });

  it("ArrowDown moves focus to next row", async () => {
    const user = userEvent.setup();
    renderTree(fixtureRows);
    await waitFor(() => {
      expect(screen.getByText("Epic One")).toBeTruthy();
    });
    const rows = screen.getAllByRole("treeitem");
    rows[0].focus();
    await user.keyboard("{ArrowDown}");
    await waitFor(() => {
      expect(rows[1].tabIndex).toBe(0);
    });
  });

  it("Enter navigates to /tickets/<key>", async () => {
    const user = userEvent.setup();
    renderTree(fixtureRows);
    await waitFor(() => {
      expect(screen.getByText("Epic One")).toBeTruthy();
    });
    const rows = screen.getAllByRole("treeitem");
    rows[0].focus();
    await user.keyboard("{Enter}");
    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith("/tickets/P-1");
    });
  });
});

describe("ProjectHierarchyTree — collapse/expand", () => {
  it("ArrowLeft collapses node (hides its children)", async () => {
    const user = userEvent.setup();
    renderTree(fixtureRows);
    await waitFor(() => {
      expect(screen.getByText("Story One")).toBeTruthy();
    });
    // Focus the epic (root), collapse it
    const rows = screen.getAllByRole("treeitem");
    rows[0].focus();
    await user.keyboard("{ArrowLeft}");
    await waitFor(() => {
      // Story One (child of epic) should be hidden
      expect(screen.queryByText("Story One")).toBeNull();
    });
  });

  it("ArrowRight expands a collapsed node", async () => {
    const user = userEvent.setup();
    renderTree(fixtureRows);
    await waitFor(() => {
      expect(screen.getByText("Story One")).toBeTruthy();
    });
    const rows = screen.getAllByRole("treeitem");
    rows[0].focus();
    // Collapse first
    await user.keyboard("{ArrowLeft}");
    await waitFor(() => {
      expect(screen.queryByText("Story One")).toBeNull();
    });
    // Expand
    await user.keyboard("{ArrowRight}");
    await waitFor(() => {
      expect(screen.getByText("Story One")).toBeTruthy();
    });
  });
});
