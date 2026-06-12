/**
 * v2.29 S5 — TicketCard inline assign affordance.
 *
 * Clicking the assignee avatar (or the "Assign" ghost button when
 * unassigned) opens the shared PersonPicker in an inline popover; picking
 * a person calls the same assign API the drawer uses, then notifies the
 * board via `onAssigned`. Escape closes the popover.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DndContext } from "@dnd-kit/core";

vi.mock("../../../api/tickets", async () => {
  const actual =
    await vi.importActual<typeof import("../../../api/tickets")>(
      "../../../api/tickets",
    );
  return {
    ...actual,
    assignTicket: vi.fn(),
  };
});

vi.mock("../../../api/people", () => ({
  searchPeople: vi.fn(async () => ({ items: [] })),
}));

import { TicketCard } from "../TicketCard";
import * as ticketsApi from "../../../api/tickets";
import * as peopleApi from "../../../api/people";
import type { TicketDTO } from "../../../api/tickets";

function makeTicket(over: Partial<TicketDTO> = {}): TicketDTO {
  return {
    id: "00000000-0000-0000-0000-000000000001",
    display_id: "DEF-1",
    title: "Sample ticket",
    status: "todo",
    version: 3,
    type: "task",
    priority: "medium",
    assignee_id: null,
    assignee_type: null,
    ...over,
  } as TicketDTO;
}

function renderCard(t: TicketDTO, extra: Record<string, unknown> = {}) {
  return render(
    <DndContext>
      <TicketCard ticket={t} {...extra} />
    </DndContext>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  (peopleApi.searchPeople as ReturnType<typeof vi.fn>).mockResolvedValue({
    items: [],
  });
});

describe("TicketCard assign affordance (v2.29)", () => {
  it("shows an Assign ghost button when unassigned and opens the picker", async () => {
    const user = userEvent.setup();
    renderCard(makeTicket());

    const btn = screen.getByTestId("ticket-assign-btn");
    expect(btn).toHaveTextContent(/assign/i);
    await user.click(btn);

    expect(screen.getByTestId("ticket-assign-pop")).toBeInTheDocument();
    expect(screen.getByTestId("person-picker-input")).toBeInTheDocument();
  });

  it("opens the picker from the assignee avatar when assigned", async () => {
    const user = userEvent.setup();
    renderCard(makeTicket({ assignee_id: "user-jane", assignee_type: "user" }));

    const avatarBtn = screen.getByTestId("ticket-avatar-user");
    expect(avatarBtn.tagName).toBe("BUTTON");
    await user.click(avatarBtn);

    expect(screen.getByTestId("ticket-assign-pop")).toBeInTheDocument();
  });

  it("picking a person calls assignTicket and onAssigned, then closes", async () => {
    const user = userEvent.setup();
    (peopleApi.searchPeople as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        {
          id: "22222222-2222-2222-2222-222222222222",
          kind: "agent",
          display_name: "Codey Bot",
          handle: "codey",
        },
      ],
    });
    (ticketsApi.assignTicket as ReturnType<typeof vi.fn>).mockResolvedValue(
      makeTicket({ assignee_id: "22222222-2222-2222-2222-222222222222" }),
    );
    const onAssigned = vi.fn();

    renderCard(makeTicket(), { onAssigned });

    await user.click(screen.getByTestId("ticket-assign-btn"));
    const input = screen.getByTestId("person-picker-input");
    await user.click(input);
    await user.type(input, "cod");
    const option = await screen.findByRole(
      "option",
      { name: /Codey Bot/ },
      { timeout: 2000 },
    );
    await user.click(option);

    await waitFor(() => {
      expect(ticketsApi.assignTicket).toHaveBeenCalledTimes(1);
    });
    expect(ticketsApi.assignTicket).toHaveBeenCalledWith("DEF-1", {
      assignee_id: "22222222-2222-2222-2222-222222222222",
      assignee_type: "agent",
      expected_version: 3,
    });
    await waitFor(() => {
      expect(onAssigned).toHaveBeenCalledTimes(1);
    });
    expect(screen.queryByTestId("ticket-assign-pop")).not.toBeInTheDocument();
  });

  it("Escape closes the popover without calling the API", async () => {
    const user = userEvent.setup();
    renderCard(makeTicket());

    await user.click(screen.getByTestId("ticket-assign-btn"));
    expect(screen.getByTestId("ticket-assign-pop")).toBeInTheDocument();

    await user.keyboard("{Escape}");

    await waitFor(() => {
      expect(
        screen.queryByTestId("ticket-assign-pop"),
      ).not.toBeInTheDocument();
    });
    expect(ticketsApi.assignTicket).not.toHaveBeenCalled();
  });
});
