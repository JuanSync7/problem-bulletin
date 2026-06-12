/**
 * V2a — MentionAutocomplete dropdown tests.
 *
 * The candidates endpoint is injected via the `loadCandidates` prop (test
 * seam) so we don't rely on global fetch mocking; the production wiring
 * (real `listMentionCandidates`) is still exercised via the prop default
 * in the route-bound smoke tests.
 */
import { describe, it, expect, vi } from "vitest";
import { useState } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import MentionAutocomplete from "../MentionAutocomplete";
import type { MentionCandidate } from "../../../api/projects";

const ALICE: MentionCandidate = {
  type: "user",
  id: "11111111-1111-1111-1111-111111111111",
  handle: "alice",
  display_name: "Alice",
};
const ALICE_AGENT: MentionCandidate = {
  type: "agent",
  id: "22222222-2222-2222-2222-222222222222",
  handle: "alice-coder",
  display_name: "Alice Coder",
};

function Host({
  loader,
  initial = "",
}: {
  loader: (
    projectId: string,
    prefix: string,
  ) => Promise<{ items: MentionCandidate[] }>;
  initial?: string;
}) {
  const [v, setV] = useState(initial);
  return (
    <>
      <MentionAutocomplete
        projectId="proj-xyz"
        value={v}
        onChange={setV}
        loadCandidates={loader}
        debounceMs={0}
      />
      <div data-testid="echo">{v}</div>
    </>
  );
}

describe("MentionAutocomplete", () => {
  it("opens the dropdown with alice (user) and alice-coder (agent) when typing @al", async () => {
    const loader = vi.fn(async () => ({ items: [ALICE, ALICE_AGENT] }));
    const user = userEvent.setup();
    render(<Host loader={loader} />);

    const ta = screen.getByTestId(
      "mention-autocomplete-input",
    ) as HTMLTextAreaElement;
    await user.click(ta);
    await user.type(ta, "@al");

    await waitFor(() => {
      expect(screen.getByTestId("mention-autocomplete-list")).toBeTruthy();
    });
    expect(screen.getByTestId("mention-candidate-alice")).toBeTruthy();
    expect(screen.getByTestId("mention-candidate-alice-coder")).toBeTruthy();
    // Loader was called with the typed prefix.
    expect(loader).toHaveBeenCalledWith("proj-xyz", "al");
  });

  it("Enter inserts the active candidate as @handle plus trailing space", async () => {
    const loader = vi.fn(async () => ({ items: [ALICE, ALICE_AGENT] }));
    const user = userEvent.setup();
    render(<Host loader={loader} />);

    const ta = screen.getByTestId(
      "mention-autocomplete-input",
    ) as HTMLTextAreaElement;
    await user.click(ta);
    await user.type(ta, "hey @al");

    await waitFor(() => {
      expect(screen.getByTestId("mention-autocomplete-list")).toBeTruthy();
    });
    // First item (Alice) is active by default — Enter inserts it.
    await user.keyboard("{Enter}");

    await waitFor(() => {
      expect(screen.getByTestId("echo").textContent).toBe("hey @alice ");
    });
  });

  it("ArrowDown then Enter inserts the second candidate (alice-coder agent)", async () => {
    const loader = vi.fn(async () => ({ items: [ALICE, ALICE_AGENT] }));
    const user = userEvent.setup();
    render(<Host loader={loader} />);

    const ta = screen.getByTestId(
      "mention-autocomplete-input",
    ) as HTMLTextAreaElement;
    await user.click(ta);
    await user.type(ta, "@al");

    await waitFor(() => {
      expect(screen.getByTestId("mention-autocomplete-list")).toBeTruthy();
    });
    await user.keyboard("{ArrowDown}");
    await user.keyboard("{Enter}");

    await waitFor(() => {
      expect(screen.getByTestId("echo").textContent).toBe("@alice-coder ");
    });
  });
});
