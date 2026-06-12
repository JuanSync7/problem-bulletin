/**
 * PersonPicker tests (v2.1-WP8).
 *
 * Covers:
 *  - results render from mocked ``searchPeople`` API
 *  - 300ms debounce coalesces typed input into a single network call
 *  - onChange bubbles ``{kind, id}``
 *  - specials (Unassigned / Me) render and are pickable
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("../../api/people", () => ({
  searchPeople: vi.fn(async () => ({
    items: [
      {
        kind: "user",
        id: "11111111-1111-1111-1111-111111111111",
        display_name: "Alice",
        handle: "alice",
        email: null,
      },
      {
        kind: "agent",
        id: "22222222-2222-2222-2222-222222222222",
        display_name: "claude-bot",
        handle: "claude-bot",
        email: null,
      },
    ],
  })),
}));

import { PersonPicker, type PersonPickerSpecial } from "../PersonPicker";
import * as peopleApi from "../../api/people";

beforeEach(() => {
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe("PersonPicker", () => {
  it("renders results from the mocked API after opening", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<PersonPicker value={null} onChange={onChange} />);

    await user.click(screen.getByRole("combobox"));

    await waitFor(() => {
      expect(screen.getByText("Alice")).toBeInTheDocument();
      expect(screen.getByText("claude-bot")).toBeInTheDocument();
    });
  });

  it("calls onChange with {kind,id} when a result is picked", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<PersonPicker value={null} onChange={onChange} />);

    await user.click(screen.getByRole("combobox"));
    await waitFor(() => screen.getByText("Alice"));
    await user.click(screen.getByText("Alice"));

    expect(onChange).toHaveBeenCalledWith({
      kind: "user",
      id: "11111111-1111-1111-1111-111111111111",
    });
  });

  it("debounces typed input — multiple keystrokes within 300ms coalesce", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({
      advanceTimers: vi.advanceTimersByTime.bind(vi),
    });
    const onChange = vi.fn();
    render(<PersonPicker value={null} onChange={onChange} />);

    const input = screen.getByRole("combobox");
    await user.click(input);

    // Initial open triggers one search (empty q).
    await act(async () => {
      vi.advanceTimersByTime(310);
    });
    const callsAfterOpen = (peopleApi.searchPeople as any).mock.calls.length;

    await user.type(input, "ali");
    // Within debounce window — no additional call.
    await act(async () => {
      vi.advanceTimersByTime(100);
    });
    expect((peopleApi.searchPeople as any).mock.calls.length).toBe(
      callsAfterOpen,
    );

    // Fire the debounce.
    await act(async () => {
      vi.advanceTimersByTime(310);
    });
    expect(
      (peopleApi.searchPeople as any).mock.calls.length,
    ).toBeGreaterThan(callsAfterOpen);
    vi.useRealTimers();
  });

  it("renders special options above results and bubbles their value", async () => {
    const user = userEvent.setup();
    const specials: PersonPickerSpecial[] = [
      { key: "unassigned", label: "Unassigned", value: { kind: "user", id: "__unassigned__" } },
      { key: "me", label: "Me", value: { kind: "user", id: "current-user-uuid" } },
    ];
    const onChange = vi.fn();
    render(
      <PersonPicker value={null} onChange={onChange} specials={specials} />,
    );

    await user.click(screen.getByRole("combobox"));
    expect(screen.getByText("Unassigned")).toBeInTheDocument();
    expect(screen.getByText("Me")).toBeInTheDocument();

    await user.click(screen.getByText("Unassigned"));
    expect(onChange).toHaveBeenCalledWith({ kind: "user", id: "__unassigned__" });
  });

  it("renders the @handle subtitle from the API response (v2.2-WP17)", async () => {
    // After WP17 the ``handle`` field on PersonRef is sourced from the
    // real DB column (was Python-derived pre-WP17). The picker contract is
    // unchanged — verify the value renders as ``@<handle>`` subtitle.
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<PersonPicker value={null} onChange={onChange} />);
    await user.click(screen.getByRole("combobox"));
    await waitFor(() => screen.getByText("Alice"));
    expect(screen.getByText("@alice")).toBeInTheDocument();
    expect(screen.getByText("@claude-bot")).toBeInTheDocument();
  });

  it("passes projectId and kind to the API", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <PersonPicker
        value={null}
        onChange={onChange}
        projectId="proj-abc"
        kind="user"
      />,
    );

    await user.click(screen.getByRole("combobox"));
    await waitFor(() =>
      expect(peopleApi.searchPeople).toHaveBeenCalled(),
    );
    const args = (peopleApi.searchPeople as any).mock.calls.at(-1)[0];
    expect(args.project_id).toBe("proj-abc");
    expect(args.kind).toBe("user");
  });
});
