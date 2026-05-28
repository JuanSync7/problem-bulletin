/**
 * MentionTextarea tests (v2.1-WP9).
 *
 * Covers:
 *  - typing ``@al`` triggers a debounced searchPeople call + renders results
 *  - selecting a suggestion inserts ``@alice `` (with trailing space)
 *  - Esc dismisses the suggestion list
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
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
        kind: "user",
        id: "22222222-2222-2222-2222-222222222222",
        display_name: "Albert",
        handle: "albert",
        email: null,
      },
    ],
  })),
}));

import { MentionTextarea } from "../MentionTextarea";
import * as peopleApi from "../../api/people";

beforeEach(() => {
  vi.clearAllMocks();
});

function ControlledHost({ initial = "" }: { initial?: string }) {
  const [v, setV] = React.useState(initial);
  return (
    <>
      <MentionTextarea value={v} onChange={setV} ariaLabel="composer" />
      <div data-testid="echo">{v}</div>
    </>
  );
}

describe("MentionTextarea", () => {
  it("shows suggestions after typing @al (debounced)", async () => {
    const user = userEvent.setup();
    render(<ControlledHost />);
    const ta = screen.getByLabelText("composer");
    await user.click(ta);
    await user.type(ta, "@al");

    await waitFor(
      () => {
        expect(screen.getByTestId("mention-suggestions")).toBeInTheDocument();
        expect(screen.getByText("Alice")).toBeInTheDocument();
      },
      { timeout: 2000 },
    );
    expect(peopleApi.searchPeople).toHaveBeenCalled();
  });

  it("inserts @alice + trailing space when a suggestion is clicked", async () => {
    const user = userEvent.setup();
    render(<ControlledHost />);
    const ta = screen.getByLabelText("composer") as HTMLTextAreaElement;
    await user.click(ta);
    await user.type(ta, "hi @al");

    await waitFor(() => {
      expect(screen.getByText("Alice")).toBeInTheDocument();
    });
    // mousedown is used so the textarea doesn't blur first.
    fireEvent.mouseDown(screen.getByTestId("mention-suggestion-alice"));

    await waitFor(() => {
      expect(screen.getByTestId("echo").textContent).toBe("hi @alice ");
    });
  });

  it("Esc dismisses the suggestion list", async () => {
    const user = userEvent.setup();
    render(<ControlledHost />);
    const ta = screen.getByLabelText("composer");
    await user.click(ta);
    await user.type(ta, "@al");

    await waitFor(() => {
      expect(screen.getByTestId("mention-suggestions")).toBeInTheDocument();
    });
    await user.keyboard("{Escape}");
    await waitFor(() => {
      expect(screen.queryByTestId("mention-suggestions")).not.toBeInTheDocument();
    });
  });
});
