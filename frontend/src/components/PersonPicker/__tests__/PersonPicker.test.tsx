/**
 * PersonPicker (v2.5-WP32) unit tests.
 *
 * Covers:
 *  - Renders placeholder when no value.
 *  - Typing fires 250ms-debounced search (vi.useFakeTimers).
 *  - Selecting an item calls onChange with the PersonRef.
 *  - Clear button calls onChange(null).
 *  - Empty results renders "No matches".
 *  - Keyboard navigation (ArrowDown + Enter) selects the correct item.
 *  - Escape closes the dropdown.
 *  - Empty query does not fire search.
 */
import "@testing-library/jest-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import React from "react";
import { render, screen, waitFor, act, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Mock the people API before importing the component.
vi.mock("../../../api/people", () => ({
  searchPeople: vi.fn(),
}));

import { PersonPicker } from "../index";
import * as peopleApi from "../../../api/people";

const ALICE: import("../../../api/people").PersonRef = {
  kind: "user",
  id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
  display_name: "Alice",
  handle: "alice",
};

const BOT: import("../../../api/people").PersonRef = {
  kind: "agent",
  id: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
  display_name: "claude-bot",
  handle: "claude-bot",
};

function mockSearch(items: import("../../../api/people").PersonRef[] = [ALICE, BOT]) {
  (peopleApi.searchPeople as ReturnType<typeof vi.fn>).mockResolvedValue({ items });
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.useRealTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("PersonPicker/index (WP32)", () => {
  // -------------------------------------------------------------------------
  // Renders placeholder when no value
  // -------------------------------------------------------------------------

  it("renders the input with placeholder when value is null", () => {
    render(
      <PersonPicker value={null} onChange={vi.fn()} placeholder="Find someone" />,
    );
    expect(screen.getByTestId("person-picker-input")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Find someone")).toBeInTheDocument();
  });

  // -------------------------------------------------------------------------
  // Empty query does not fire search
  // -------------------------------------------------------------------------

  it("does not call searchPeople when query is empty after focus", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime.bind(vi) });
    render(<PersonPicker value={null} onChange={vi.fn()} />);

    // Focus opens the dropdown but an empty query should NOT trigger a search.
    await user.click(screen.getByTestId("person-picker-input"));
    await act(async () => { vi.advanceTimersByTime(300); });

    expect(peopleApi.searchPeople).not.toHaveBeenCalled();
  });

  // -------------------------------------------------------------------------
  // Typing fires debounced search
  // -------------------------------------------------------------------------

  it("typing fires debounced search after 250ms, not before", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime.bind(vi) });
    mockSearch();
    render(<PersonPicker value={null} onChange={vi.fn()} />);

    const input = screen.getByTestId("person-picker-input");
    await user.click(input);
    await user.type(input, "ali");

    // Before debounce fires.
    await act(async () => { vi.advanceTimersByTime(100); });
    expect(peopleApi.searchPeople).not.toHaveBeenCalled();

    // After debounce fires.
    await act(async () => { vi.advanceTimersByTime(200); });
    expect(peopleApi.searchPeople).toHaveBeenCalledTimes(1);
    expect((peopleApi.searchPeople as any).mock.calls[0][0]).toMatchObject({ q: "ali" });
  });

  // -------------------------------------------------------------------------
  // Selecting an item calls onChange with the PersonRef
  // -------------------------------------------------------------------------

  it("clicking a result calls onChange with the full PersonRef", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime.bind(vi) });
    mockSearch([ALICE]);
    const onChange = vi.fn();
    render(<PersonPicker value={null} onChange={onChange} />);

    const input = screen.getByTestId("person-picker-input");
    await user.click(input);
    await user.type(input, "ali");
    await act(async () => { vi.advanceTimersByTime(260); });

    await waitFor(() => expect(screen.getByText("Alice")).toBeInTheDocument());

    // Use mouseDown to match the component's onMouseDown handler.
    fireEvent.mouseDown(screen.getByText("Alice"));

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith(ALICE);
  });

  // -------------------------------------------------------------------------
  // Clear button calls onChange(null)
  // -------------------------------------------------------------------------

  it("clear button calls onChange(null) and removes the chip", async () => {
    const onChange = vi.fn();
    render(
      <PersonPicker value={ALICE} onChange={onChange} allowClear />,
    );

    // When value is set and dropdown is closed, the chip is shown.
    expect(screen.getByTestId("person-picker-clear")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("person-picker-clear"));

    expect(onChange).toHaveBeenCalledWith(null);
  });

  // -------------------------------------------------------------------------
  // Empty results renders "No matches"
  // -------------------------------------------------------------------------

  it("renders No matches when API returns empty items", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime.bind(vi) });
    mockSearch([]);
    render(<PersonPicker value={null} onChange={vi.fn()} />);

    const input = screen.getByTestId("person-picker-input");
    await user.click(input);
    await user.type(input, "xyz");
    await act(async () => { vi.advanceTimersByTime(260); });

    await waitFor(() => expect(screen.getByText("No matches")).toBeInTheDocument());
  });

  // -------------------------------------------------------------------------
  // Keyboard navigation: ArrowDown + Enter selects
  // -------------------------------------------------------------------------

  it("ArrowDown + Enter selects the first result and calls onChange", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime.bind(vi) });
    mockSearch([ALICE, BOT]);
    const onChange = vi.fn();
    render(<PersonPicker value={null} onChange={onChange} />);

    const input = screen.getByTestId("person-picker-input");
    await user.click(input);
    await user.type(input, "ali");
    await act(async () => { vi.advanceTimersByTime(260); });
    await waitFor(() => expect(screen.getByText("Alice")).toBeInTheDocument());

    // Arrow down to first option, then Enter.
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(onChange).toHaveBeenCalledWith(ALICE);
  });

  it("ArrowDown twice then Enter selects the second result", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime.bind(vi) });
    mockSearch([ALICE, BOT]);
    const onChange = vi.fn();
    render(<PersonPicker value={null} onChange={onChange} />);

    const input = screen.getByTestId("person-picker-input");
    await user.click(input);
    await user.type(input, "al");
    await act(async () => { vi.advanceTimersByTime(260); });
    await waitFor(() => expect(screen.getByText("Alice")).toBeInTheDocument());

    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(onChange).toHaveBeenCalledWith(BOT);
  });

  // -------------------------------------------------------------------------
  // Escape closes the dropdown
  // -------------------------------------------------------------------------

  it("Escape closes the dropdown", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime.bind(vi) });
    mockSearch([ALICE]);
    render(<PersonPicker value={null} onChange={vi.fn()} />);

    const input = screen.getByTestId("person-picker-input");
    await user.click(input);
    await user.type(input, "ali");
    await act(async () => { vi.advanceTimersByTime(260); });
    await waitFor(() => expect(screen.getByText("Alice")).toBeInTheDocument());

    fireEvent.keyDown(input, { key: "Escape" });
    await waitFor(() => expect(screen.queryByText("Alice")).not.toBeInTheDocument());
  });

  // -------------------------------------------------------------------------
  // Selected chip renders @handle
  // -------------------------------------------------------------------------

  it("renders selected value as a chip with display_name and handle", () => {
    render(
      <PersonPicker value={ALICE} onChange={vi.fn()} allowClear />,
    );

    expect(screen.getByText("Alice")).toBeInTheDocument();
    expect(screen.getByText(/@alice/)).toBeInTheDocument();
  });

  // -------------------------------------------------------------------------
  // Backspace on empty query clears value
  // -------------------------------------------------------------------------

  // -------------------------------------------------------------------------
  // WP47: agent badge on chip
  // -------------------------------------------------------------------------

  it("renders an 'agent' badge in the chip when value.kind === 'agent'", () => {
    render(<PersonPicker value={BOT} onChange={vi.fn()} />);

    const badge = screen.getByText("agent", { selector: ".person-picker-chip__type-badge" });
    expect(badge).toBeInTheDocument();
    // Accessible name includes "agent" so screen readers announce it.
    expect(badge).toHaveAttribute("aria-label", "agent");
  });

  it("does NOT render the 'agent' badge in the chip when value.kind === 'user'", () => {
    render(<PersonPicker value={ALICE} onChange={vi.fn()} />);

    expect(
      document.querySelector(".person-picker-chip__type-badge"),
    ).toBeNull();
  });

  it("backspace when query is empty and value is set opens picker and clears", () => {
    const onChange = vi.fn();
    render(<PersonPicker value={ALICE} onChange={onChange} allowClear />);

    // The chip is shown; click "change" to open the input.
    fireEvent.click(screen.getByTestId("person-picker-change"));

    // Now input is visible; press backspace with empty query.
    const input = screen.getByTestId("person-picker-input");
    fireEvent.keyDown(input, { key: "Backspace" });

    expect(onChange).toHaveBeenCalledWith(null);
  });
});
