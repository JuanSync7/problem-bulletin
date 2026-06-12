/**
 * V6a — Project Hierarchy "Lessons" tab.
 *
 * Mounts the page with mocked `listProjectLessons` + `createProjectLesson`,
 * switches to the Lessons tab, submits the inline form, and asserts the
 * new lesson appears at the top.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { ProjectLessonDTO } from "../../../api/projects";

const listProjectLessons = vi.fn();
const createProjectLesson = vi.fn();

vi.mock("../../../api/projects", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../api/projects")>();
  return {
    ...actual,
    getProjectHierarchy: vi.fn().mockResolvedValue({ items: [] }),
    listProjects: vi.fn().mockResolvedValue({
      items: [],
      next_cursor: null,
      total: 0,
    }),
    listProjectLessons: (...args: unknown[]) =>
      listProjectLessons(...args),
    createProjectLesson: (...args: unknown[]) =>
      createProjectLesson(...args),
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

import ProjectHierarchyPage from "../index";

const SEED_LESSON: ProjectLessonDTO = {
  id: "lesson-1",
  project_id: "p-test",
  author_user_id: "alice-id",
  author_agent_id: null,
  source: "user",
  title: "Validate at the boundary",
  body: "Always use parseJson<T> with a guard.",
  created_at: "2026-06-02T10:00:00Z",
};

describe("ProjectHierarchy → Lessons tab", () => {
  beforeEach(() => {
    listProjectLessons.mockReset();
    createProjectLesson.mockReset();
  });

  it("switching to Lessons tab loads + lists lessons", async () => {
    listProjectLessons.mockResolvedValue({
      items: [SEED_LESSON],
      next_cursor: null,
      total: 1,
    });
    render(
      <MemoryRouter>
        <ProjectHierarchyPage />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole("tab", { name: /lessons/i }));
    await waitFor(() => {
      expect(listProjectLessons).toHaveBeenCalled();
    });
    expect(await screen.findByText(/Validate at the boundary/i)).toBeTruthy();
  });

  it("posting via inline form prepends the new lesson", async () => {
    listProjectLessons.mockResolvedValue({
      items: [SEED_LESSON],
      next_cursor: null,
      total: 1,
    });
    const created: ProjectLessonDTO = {
      id: "lesson-2",
      project_id: "p-test",
      author_user_id: "alice-id",
      author_agent_id: null,
      source: "user",
      title: "New insight",
      body: "Body of insight.",
      created_at: "2026-06-02T11:00:00Z",
    };
    createProjectLesson.mockResolvedValue(created);

    render(
      <MemoryRouter>
        <ProjectHierarchyPage />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole("tab", { name: /lessons/i }));
    await waitFor(() => {
      expect(listProjectLessons).toHaveBeenCalled();
    });

    const titleInput = await screen.findByLabelText(/title/i);
    const bodyInput = screen.getByLabelText(/body/i);
    fireEvent.change(titleInput, { target: { value: "New insight" } });
    fireEvent.change(bodyInput, { target: { value: "Body of insight." } });

    fireEvent.click(screen.getByRole("button", { name: /add lesson/i }));

    await waitFor(() => {
      // v2.29: body now carries a `meta:{...}` JSON prefix so we can persist
      // category/severity/tags without a schema migration. Assert the
      // structural shape rather than verbatim equality.
      expect(createProjectLesson).toHaveBeenCalledTimes(1);
      const [projectArg, payloadArg] = createProjectLesson.mock.calls[0] as [
        string,
        { title: string; body: string },
      ];
      expect(projectArg).toBe("p-test");
      expect(payloadArg.title).toBe("New insight");
      expect(payloadArg.body).toMatch(/Body of insight\./);
    });

    // The new lesson should appear above the existing one — first item.
    const items = await screen.findAllByTestId("lesson-item");
    expect(items.length).toBe(2);
    expect(items[0].textContent).toContain("New insight");
    expect(items[1].textContent).toContain("Validate at the boundary");
  });
});
