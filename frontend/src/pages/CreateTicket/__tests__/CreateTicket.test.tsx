/**
 * CreateTicket page tests.
 *
 * The page pulls several network resources (projects / sprints / components)
 * and uses the heavy RichEditor (TipTap). We mock all three at module level so
 * the test focuses on form-logic behaviour driven by `FIELDS_BY_TYPE`.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { ToastProvider } from "../../../contexts/ToastContext";

// Heavy editor stub — keep BEFORE the page import.
vi.mock("../../../components/RichEditor", () => ({
  default: ({
    value,
    onChange,
    placeholder,
  }: {
    value: string;
    onChange: (v: string) => void;
    placeholder?: string;
  }) =>
    React.createElement("textarea", {
      "data-testid": "rich-editor",
      value,
      placeholder,
      onChange: (e: React.ChangeEvent<HTMLTextAreaElement>) =>
        onChange(e.target.value),
    }),
}));

// API client mocks.
vi.mock("../../../api/tickets", async () => {
  const actual =
    await vi.importActual<typeof import("../../../api/tickets")>(
      "../../../api/tickets",
    );
  return {
    ...actual,
    createTicket: vi.fn(),
    searchTickets: vi.fn(async () => ({ items: [] })),
  };
});

vi.mock("../../../api/projects", () => ({
  listProjects: vi.fn(async () => ({
    items: [
      {
        id: "00000000-0000-0000-0000-000000000001",
        key: "DEF",
        name: "Default",
      },
    ],
  })),
  listComponents: vi.fn(async () => ({ items: [] })),
  listMembers: vi.fn(async () => ({ items: [] })),
}));

vi.mock("../../../api/sprints", () => ({
  listSprints: vi.fn(async () => ({ items: [] })),
}));

vi.mock("../../../api/people", () => ({
  searchPeople: vi.fn(async () => ({ items: [] })),
}));

import CreateTicket from "../CreateTicket";
import * as ticketsApi from "../../../api/tickets";
import { ApiError } from "../../../api/tickets";

function renderPage(path = "/tickets/new") {
  return render(
    <MemoryRouter initialEntries={[path]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <ToastProvider>
        <CreateTicket />
      </ToastProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("CreateTicket", () => {
  it("renders with default task type and DEF project", async () => {
    renderPage();
    expect(
      screen.getByRole("heading", { name: "Create Ticket" }),
    ).toBeInTheDocument();

    // The task pill should be active (aria-checked=true)
    const taskPill = screen.getByRole("radio", { name: /Task/ });
    expect(taskPill).toHaveAttribute("aria-checked", "true");

    // wait for projects to load
    await waitFor(() => {
      const projectSelect = screen.getByLabelText(/Project/) as HTMLSelectElement;
      expect(projectSelect.value).toBe("DEF");
    });
  });

  it("switching to subtask makes parent required + blocks submit when empty", async () => {
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(
        (screen.getByLabelText(/Project/) as HTMLSelectElement).value,
      ).toBe("DEF");
    });

    await user.click(screen.getByRole("radio", { name: /Subtask/ }));

    // parent picker becomes visible
    expect(screen.getByLabelText(/Parent ticket/)).toBeInTheDocument();

    // fill required title
    await user.type(screen.getByLabelText(/Title/), "A subtask without parent");

    // submit without parent
    await user.click(screen.getByRole("button", { name: /Create Ticket/ }));

    expect(
      await screen.findByText(/Parent ticket is required for a subtask/),
    ).toBeInTheDocument();
    expect(ticketsApi.createTicket).not.toHaveBeenCalled();
  });

  it("switching to workpackage hides Sprint and Story Points fields", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("radio", { name: /Workpackage/ }));

    expect(screen.queryByLabelText(/Sprint/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Story points/)).not.toBeInTheDocument();
    // parent picker hidden too
    expect(screen.queryByLabelText(/Parent ticket/)).not.toBeInTheDocument();
  });

  it("successful submit POSTs the correct body", async () => {
    const user = userEvent.setup();
    (ticketsApi.createTicket as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: "abc",
      display_id: "DEF-7",
      title: "x",
      status: "todo",
      version: 1,
    });

    renderPage();

    await waitFor(() => {
      expect(
        (screen.getByLabelText(/Project/) as HTMLSelectElement).value,
      ).toBe("DEF");
    });

    await user.type(screen.getByLabelText(/Title/), "My new task");
    await user.click(screen.getByRole("button", { name: /Create Ticket/ }));

    await waitFor(() => {
      expect(ticketsApi.createTicket).toHaveBeenCalledTimes(1);
    });
    const body = (ticketsApi.createTicket as ReturnType<typeof vi.fn>).mock
      .calls[0][0];
    expect(body).toMatchObject({
      title: "My new task",
      type: "task",
      project_key: "DEF",
      priority: "medium",
    });
  });

  it("WP42: renders the new shared PersonPicker for assignee", async () => {
    renderPage();
    await waitFor(() => {
      expect(
        (screen.getByLabelText(/Project/) as HTMLSelectElement).value,
      ).toBe("DEF");
    });
    // The new directory-based PersonPicker exposes data-testid="person-picker"
    // and an input with data-testid="person-picker-input".
    expect(screen.getByTestId("person-picker")).toBeInTheDocument();
    const input = screen.getByTestId("person-picker-input") as HTMLInputElement;
    expect(input).toHaveAttribute("role", "combobox");
    expect(input).toHaveAttribute("aria-autocomplete", "list");
  });

  it("WP42: picking an assignee sends assignee_id+assignee_type in the body", async () => {
    const user = userEvent.setup();
    const peopleApi = await import("../../../api/people");
    (peopleApi.searchPeople as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        {
          id: "11111111-1111-1111-1111-111111111111",
          kind: "user",
          display_name: "Alice Example",
          handle: "alice",
        },
      ],
    });
    (ticketsApi.createTicket as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: "tid",
      display_id: "DEF-8",
      title: "x",
      status: "todo",
      version: 1,
    });

    renderPage();
    await waitFor(() => {
      expect(
        (screen.getByLabelText(/Project/) as HTMLSelectElement).value,
      ).toBe("DEF");
    });
    await user.type(screen.getByLabelText(/Title/), "Has assignee");

    const input = screen.getByTestId("person-picker-input");
    await user.click(input);
    await user.type(input, "ali");
    // 250ms debounce + microtasks
    const option = await screen.findByRole("option", { name: /Alice Example/ }, { timeout: 2000 });
    await user.click(option);

    await user.click(screen.getByRole("button", { name: /Create Ticket/ }));
    await waitFor(() => {
      expect(ticketsApi.createTicket).toHaveBeenCalledTimes(1);
    });
    const body = (ticketsApi.createTicket as ReturnType<typeof vi.fn>).mock
      .calls[0][0];
    expect(body).toMatchObject({
      title: "Has assignee",
      assignee_id: "11111111-1111-1111-1111-111111111111",
      assignee_type: "user",
    });
  });

  it("v2.29: prefills title and description from query params", async () => {
    const title = "Fix the login problem";
    const description =
      "Created from problem: http://localhost/problems/p-1\n\nUsers cannot log in.";
    renderPage(
      `/tickets/new?title=${encodeURIComponent(title)}&description=${encodeURIComponent(description)}`,
    );

    await waitFor(() => {
      expect(
        (screen.getByLabelText(/Project/) as HTMLSelectElement).value,
      ).toBe("DEF");
    });

    expect(
      (screen.getByLabelText(/Title/) as HTMLInputElement).value,
    ).toBe(title);
    expect(
      (screen.getByTestId("rich-editor") as HTMLTextAreaElement).value,
    ).toBe(description);
  });

  it("surfaces cross-project parent toast on 409", async () => {
    const user = userEvent.setup();
    (ticketsApi.createTicket as ReturnType<typeof vi.fn>).mockRejectedValue(
      new ApiError(
        409,
        { code: "cross_project_parent", message: "no" },
        "no",
      ),
    );

    renderPage();
    await waitFor(() => {
      expect(
        (screen.getByLabelText(/Project/) as HTMLSelectElement).value,
      ).toBe("DEF");
    });

    await user.type(screen.getByLabelText(/Title/), "Cross-project attempt");
    await user.click(screen.getByRole("button", { name: /Create Ticket/ }));

    // toast renders into the document via ToastProvider; assert by text
    expect(
      await screen.findByText(/Parent ticket must be in the same project\./),
    ).toBeInTheDocument();
  });
});
