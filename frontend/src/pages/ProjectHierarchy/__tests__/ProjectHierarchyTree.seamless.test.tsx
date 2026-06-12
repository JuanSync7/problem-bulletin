/**
 * B2: ProjectHierarchyTree seamless (no card chrome) UX-regression guard.
 *
 * Asserts computed styles on the tree container:
 *  - background: transparent
 *  - no border
 *  - no box-shadow
 *
 * This is a LOAD-BEARING test — a passing functional test does NOT make
 * B2 green if this test fails.
 */
import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { HierarchyRow } from "../../../api/projects";

vi.mock("../../../api/projects", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../api/projects")>();
  return {
    ...actual,
    getProjectHierarchy: vi.fn().mockResolvedValue({ items: [] }),
    listProjects: vi.fn().mockResolvedValue({ items: [], next_cursor: null, total: 0 }),
  };
});

vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return {
    ...actual,
    useNavigate: () => vi.fn(),
    useParams: () => ({ projectId: "p-test" }),
    useSearchParams: () => [new URLSearchParams(), vi.fn()],
  };
});

import { ProjectHierarchyTree } from "../ProjectHierarchyTree";

const emptyRows: HierarchyRow[] = [];

describe("ProjectHierarchyTree — seamless background (no card chrome)", () => {
  it("tree container has transparent background", () => {
    const { container } = render(
      <MemoryRouter>
        <ProjectHierarchyTree rows={emptyRows} hiddenTypes={[]} projectId="p-test" />
      </MemoryRouter>,
    );
    const tree = container.querySelector("[data-testid='hierarchy-tree-container']") as HTMLElement;
    expect(tree).toBeTruthy();
    const style = getComputedStyle(tree);
    // jsdom returns "" or "rgba(0, 0, 0, 0)" or "transparent" for unset background
    const bg = style.background ?? style.backgroundColor ?? "";
    expect(bg).toMatch(/transparent|rgba\(0,\s*0,\s*0,\s*0\)|^$/);
  });

  it("tree container has no border", () => {
    const { container } = render(
      <MemoryRouter>
        <ProjectHierarchyTree rows={emptyRows} hiddenTypes={[]} projectId="p-test" />
      </MemoryRouter>,
    );
    const tree = container.querySelector("[data-testid='hierarchy-tree-container']") as HTMLElement;
    expect(tree).toBeTruthy();
    const style = getComputedStyle(tree);
    const border = style.border ?? "";
    // Accept none, 0px, empty string
    expect(border).toMatch(/^(none|0px.*|)$/);
  });

  it("tree container has no box-shadow", () => {
    const { container } = render(
      <MemoryRouter>
        <ProjectHierarchyTree rows={emptyRows} hiddenTypes={[]} projectId="p-test" />
      </MemoryRouter>,
    );
    const tree = container.querySelector("[data-testid='hierarchy-tree-container']") as HTMLElement;
    expect(tree).toBeTruthy();
    const style = getComputedStyle(tree);
    const shadow = style.boxShadow ?? "";
    expect(shadow).toMatch(/^(none|)$/);
  });
});
