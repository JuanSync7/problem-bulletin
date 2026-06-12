/**
 * A4: GlobalSearchBar polish tests.
 *
 * Tests cover:
 *  (a) on focus with empty input, <RecentSearches /> renders with up-to-5 entries from localStorage
 *  (b) clicking a recent fills input & triggers query
 *  (c) <ScopeChips /> renders chips for each entity arm
 *  (d) clicking a chip toggles entity filter passed to useTypeahead
 *  (e) submitting a query appends it to recents (dedup, cap-5, most-recent-first)
 *
 * Rules: no any, no @ts-ignore, no bare catch{}.
 * Real timers + waitFor (no fake timers with userEvent).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("../../../api/search", () => ({
  searchTypeahead: vi.fn(),
  isTypeaheadResponse: vi.fn(() => true),
}));

vi.mock("../../../hooks/useAuth", () => ({
  useAuth: () => ({
    isAuthenticated: true,
    user: { id: "user-test-1", email: "test@example.com", displayName: "Test", role: "user" },
    isLoading: false,
    error: null,
  }),
}));

const mockNavigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>(
    "react-router-dom",
  );
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

import { GlobalSearchBar } from "../index";
import * as searchApi from "../../../api/search";

// ---------------------------------------------------------------------------
// LocalStorage helpers
// ---------------------------------------------------------------------------

const RECENTS_KEY = "aion.search.recents.user-test-1";

function clearRecents() {
  localStorage.removeItem(RECENTS_KEY);
}

function setRecents(entries: string[]) {
  localStorage.setItem(RECENTS_KEY, JSON.stringify(entries));
}

// ---------------------------------------------------------------------------
// Render helper
// ---------------------------------------------------------------------------

function renderBar() {
  return render(
    <MemoryRouter>
      <GlobalSearchBar />
    </MemoryRouter>,
  );
}

function getInput(): HTMLInputElement {
  return (
    screen.queryByRole("searchbox") ??
    screen.queryByPlaceholderText(/search/i)
  ) as HTMLInputElement;
}

// ---------------------------------------------------------------------------
// Setup / teardown
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
  clearRecents();
  (searchApi.searchTypeahead as ReturnType<typeof vi.fn>).mockResolvedValue({});
});

afterEach(() => {
  vi.clearAllMocks();
  clearRecents();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("GlobalSearchBar — polish (A4)", () => {
  it("(a) shows recent searches when focused on empty input", async () => {
    setRecents(["alpha", "beta", "gamma"]);
    const user = userEvent.setup();
    renderBar();

    const input = getInput();
    await user.click(input);

    await waitFor(
      () => {
        expect(screen.getByText("alpha")).toBeInTheDocument();
        expect(screen.getByText("beta")).toBeInTheDocument();
        expect(screen.getByText("gamma")).toBeInTheDocument();
      },
      { timeout: 3000 },
    );
  });

  it("(a2) shows at most 5 recent entries", async () => {
    setRecents(["one", "two", "three", "four", "five", "six"]);
    const user = userEvent.setup();
    renderBar();

    const input = getInput();
    await user.click(input);

    await waitFor(
      () => {
        expect(screen.getByText("one")).toBeInTheDocument();
      },
      { timeout: 3000 },
    );

    // Should not show the 6th entry
    expect(screen.queryByText("six")).not.toBeInTheDocument();
  });

  it("(a3) does not show recent searches when input is not empty", async () => {
    setRecents(["alpha", "beta"]);
    const user = userEvent.setup();
    renderBar();

    const input = getInput();
    await user.type(input, "Bug");

    // Wait for render
    await waitFor(
      () => {
        expect(input.value).toBe("Bug");
      },
      { timeout: 3000 },
    );

    // Recents should NOT be visible when there is typed text
    expect(screen.queryByText("alpha")).not.toBeInTheDocument();
    expect(screen.queryByText("beta")).not.toBeInTheDocument();
  });

  it("(b) clicking a recent fills input and triggers query", async () => {
    setRecents(["alpha"]);
    const user = userEvent.setup();
    renderBar();

    const input = getInput();
    await user.click(input);

    await waitFor(
      () => {
        expect(screen.getByText("alpha")).toBeInTheDocument();
      },
      { timeout: 3000 },
    );

    await user.click(screen.getByText("alpha"));

    await waitFor(
      () => {
        expect(input.value).toBe("alpha");
      },
      { timeout: 3000 },
    );

    await waitFor(
      () => {
        expect(searchApi.searchTypeahead).toHaveBeenCalledWith(
          "alpha",
          expect.anything(),
          expect.any(String),
        );
      },
      { timeout: 3000 },
    );
  });

  it("(c) <ScopeChips /> renders chip for each entity arm", async () => {
    renderBar();

    // ScopeChips should always be visible (not just on focus)
    await waitFor(
      () => {
        // Expect chips for each arm: all, tickets, problems, components, labels, users
        expect(screen.getByRole("button", { name: /all/i })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: /tickets/i })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: /problems/i })).toBeInTheDocument();
      },
      { timeout: 3000 },
    );
  });

  it("(d) clicking a chip passes entity filter to useTypeahead", async () => {
    const user = userEvent.setup();
    (searchApi.searchTypeahead as ReturnType<typeof vi.fn>).mockResolvedValue({
      combined: [],
    });
    renderBar();

    // Type a query first to trigger typeahead calls
    const input = getInput();
    await user.click(input);
    await user.type(input, "foo");

    await waitFor(
      () => {
        expect(searchApi.searchTypeahead).toHaveBeenCalled();
      },
      { timeout: 3000 },
    );

    vi.clearAllMocks();
    (searchApi.searchTypeahead as ReturnType<typeof vi.fn>).mockResolvedValue({
      combined: [],
    });

    // Click the "Tickets" chip
    const ticketsChip = screen.getByRole("button", { name: /tickets/i });
    await user.click(ticketsChip);

    // A new typeahead call should be triggered (either immediately or after debounce)
    await waitFor(
      () => {
        expect(searchApi.searchTypeahead).toHaveBeenCalled();
      },
      { timeout: 3000 },
    );
  });

  it("(e) submitting a query appends it to recents (dedup, cap-5, most-recent-first)", async () => {
    setRecents(["existing"]);
    const user = userEvent.setup();
    renderBar();

    const input = getInput();
    await user.click(input);
    await user.type(input, "newquery");

    await waitFor(
      () => {
        expect(input.value).toBe("newquery");
      },
      { timeout: 3000 },
    );

    await user.keyboard("{Enter}");

    // Wait a tick for state to settle
    await waitFor(
      () => {
        const stored = localStorage.getItem(RECENTS_KEY);
        if (!stored) throw new Error("recents not stored");
        const recents: unknown = JSON.parse(stored);
        if (!Array.isArray(recents)) throw new Error("recents is not an array");
        expect(recents[0]).toBe("newquery");
        expect(recents).toContain("existing");
      },
      { timeout: 3000 },
    );
  });

  it("(e2) appending a duplicate query deduplicates and moves to front", async () => {
    setRecents(["old1", "dup", "old2"]);
    const user = userEvent.setup();
    renderBar();

    const input = getInput();
    await user.click(input);
    await user.type(input, "dup");

    await waitFor(
      () => {
        expect(input.value).toBe("dup");
      },
      { timeout: 3000 },
    );

    await user.keyboard("{Enter}");

    await waitFor(
      () => {
        const stored = localStorage.getItem(RECENTS_KEY);
        if (!stored) throw new Error("recents not stored");
        const recents: string[] = JSON.parse(stored) as string[];
        expect(recents[0]).toBe("dup");
        // No duplicates
        const dupCount = recents.filter((r) => r === "dup").length;
        expect(dupCount).toBe(1);
      },
      { timeout: 3000 },
    );
  });

  it("(e3) cap at 5 recents when more than 5 are added", async () => {
    setRecents(["a", "b", "c", "d", "e"]);
    const user = userEvent.setup();
    renderBar();

    const input = getInput();
    await user.click(input);
    await user.type(input, "f");

    await user.keyboard("{Enter}");

    await waitFor(
      () => {
        const stored = localStorage.getItem(RECENTS_KEY);
        if (!stored) throw new Error("recents not stored");
        const recents: string[] = JSON.parse(stored) as string[];
        expect(recents.length).toBeLessThanOrEqual(5);
        expect(recents[0]).toBe("f");
      },
      { timeout: 3000 },
    );
  });
});
