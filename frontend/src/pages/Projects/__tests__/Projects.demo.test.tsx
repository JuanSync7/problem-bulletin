/**
 * V5a — Projects landing renders the seeded demo project card.
 *
 * Mocks ``listProjects`` to return a single ``ProjectDTO`` representing
 * the seeded "Problem-Bulletin" demo project and asserts the rendered
 * card links at ``/projects/<id>/hierarchy``.  This pins the contract
 * between the V5a backend seed (``app/scripts/seed_demo.py``) and the
 * frontend landing surface a developer will click after running the
 * script.
 */
import "@testing-library/jest-dom";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

const DEMO_ID = "00000000-0000-0000-0000-00000000c0de";

vi.mock("../../../api/projects", () => ({
  listProjects: vi.fn(async () => ({
    items: [
      {
        id: DEMO_ID,
        key: "PB",
        name: "Problem-Bulletin",
        description: "Seeded demo project",
      },
    ],
    total: 1,
    next_cursor: null,
  })),
}));

import ProjectsPage from "../index";

describe("V5a: Projects landing demo card", () => {
  it("renders the PB demo card with a hierarchy deep-link", async () => {
    render(
      <MemoryRouter
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <ProjectsPage />
      </MemoryRouter>,
    );

    // Wait for async fetch to resolve and the card to render.
    await waitFor(() => {
      expect(screen.getByText("Problem-Bulletin")).toBeInTheDocument();
    });

    // The whole card is wrapped in a Link to the hierarchy page.
    const link = screen.getByRole("link", { name: /Problem-Bulletin/i });
    expect(link).toHaveAttribute("href", `/projects/${DEMO_ID}/hierarchy`);

    // The project key chip is visible on the card.
    expect(screen.getByText("PB")).toBeInTheDocument();
  });
});
