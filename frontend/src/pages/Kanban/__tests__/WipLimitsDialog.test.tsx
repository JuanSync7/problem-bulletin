/**
 * v2.1-WP11 — WipLimitsDialog tests.
 *
 * Verifies:
 *   - Inputs prefill from ``project.wip_limits``.
 *   - Save calls ``updateProject`` with the parsed limit map.
 *   - An emptied input drops the key from the payload (means "no limit").
 */
import "@testing-library/jest-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const { updateProjectMock } = vi.hoisted(() => ({
  updateProjectMock: vi.fn(),
}));

vi.mock("../../../api/projects", async () => {
  const actual = await vi.importActual<typeof import("../../../api/projects")>(
    "../../../api/projects",
  );
  return {
    ...actual,
    updateProject: updateProjectMock,
  };
});

import { WipLimitsDialog } from "../WipLimitsDialog";

const sampleProject: any = {
  id: "p-def",
  key: "DEF",
  name: "Default",
  version: 7,
  wip_limits: { todo: 5, in_progress: 3 },
  lead_id: null,
};

beforeEach(() => {
  updateProjectMock.mockReset();
  updateProjectMock.mockResolvedValue({
    ...sampleProject,
    version: 8,
    wip_limits: { todo: 4 },
  });
});

describe("WipLimitsDialog", () => {
  it("opens with current limits prefilled", () => {
    render(
      <WipLimitsDialog
        project={sampleProject}
        onClose={() => {}}
        onSaved={() => {}}
      />,
    );
    const todo = screen.getByLabelText("To Do") as HTMLInputElement;
    const inProgress = screen.getByLabelText("In Progress") as HTMLInputElement;
    const backlog = screen.getByLabelText("Backlog") as HTMLInputElement;
    expect(todo.value).toBe("5");
    expect(inProgress.value).toBe("3");
    expect(backlog.value).toBe("");
  });

  it("Save calls updateProject with the new map and current version", async () => {
    const onSaved = vi.fn();
    const user = userEvent.setup();
    render(
      <WipLimitsDialog
        project={sampleProject}
        onClose={() => {}}
        onSaved={onSaved}
      />,
    );
    const todo = screen.getByLabelText("To Do");
    await user.clear(todo);
    await user.type(todo, "8");

    await user.click(screen.getByRole("button", { name: /Save/ }));

    await waitFor(() => expect(updateProjectMock).toHaveBeenCalledTimes(1));
    const args = updateProjectMock.mock.calls[0];
    expect(args[0]).toBe("p-def");
    expect(args[1]).toEqual({
      wip_limits: { todo: 8, in_progress: 3 },
    });
    expect(args[2]).toBe(7);
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
  });

  it("emptying an input deletes that key from the payload", async () => {
    const user = userEvent.setup();
    render(
      <WipLimitsDialog
        project={sampleProject}
        onClose={() => {}}
        onSaved={() => {}}
      />,
    );
    await user.clear(screen.getByLabelText("In Progress"));
    await user.click(screen.getByRole("button", { name: /Save/ }));

    await waitFor(() => expect(updateProjectMock).toHaveBeenCalled());
    const sentPayload = updateProjectMock.mock.calls[0][1];
    expect(sentPayload).toEqual({ wip_limits: { todo: 5 } });
    expect("in_progress" in sentPayload.wip_limits).toBe(false);
  });
});
