/**
 * A2b: GlobalSearchBar typeahead dropdown tests.
 *
 * Tests cover:
 *  (a) typing "Bug" calls searchTypeahead after 150ms debounce
 *  (b) dropdown renders entity-grouped rows from combined
 *  (c) direct-match row pinned top, "View all" pinned bottom
 *  (d) ↑/↓ moves highlight (wrapping at boundaries)
 *  (e) Enter on a typeahead row navigates to that entity's detail page
 *  (f) Enter on "View all" navigates to /search?q=Bug
 *  (g) Esc closes dropdown
 *  (h) keystroke during in-flight request aborts the previous fetch signal
 *
 * NOTE: Playwright (E2E) is not installed in this repo; those specs are
 * written in e2e/global-search.typeahead.spec.ts but will not execute.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

// Mock the search API before importing the component
vi.mock("../../../api/search", () => ({
  searchTypeahead: vi.fn(),
  isTypeaheadResponse: vi.fn(() => true),
}));

// Mock useAuth (required since index.tsx now uses it for recents userId)
vi.mock("../../../hooks/useAuth", () => ({
  useAuth: () => ({
    isAuthenticated: true,
    user: { id: "test-user", email: "test@example.com", displayName: "Test", role: "user" },
    isLoading: false,
    error: null,
  }),
}));

// Mock useNavigate
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
// Fixtures
// ---------------------------------------------------------------------------

const makeProblem = (n: number) => ({
  id: `prob-${n}`,
  display_id: `PROB-${n}`,
  title: `Bug Problem ${n}`,
  subtitle: "open",
  kind: "problem",
  href: `/problems/${n}`,
  rank: 10 - n,
  project_id: null,
  status: "open",
});

const makeTicket = (n: number) => ({
  id: `ticket-${n}`,
  display_id: `AION-${n}`,
  title: `Bug Ticket ${n}`,
  subtitle: "in_progress",
  kind: "ticket",
  href: `/tickets/AION-${n}`,
  rank: 9 - n,
  project_id: "proj-1",
  status: "in_progress",
});

const makeLabel = (n: number) => ({
  id: `label-${n}`,
  display_id: null,
  title: `Bug Label ${n}`,
  subtitle: "",
  kind: "label",
  href: `/labels/${n}`,
  rank: 5 - n,
  project_id: null,
  status: null,
});

const directMatchItem = {
  id: "direct-match-id",
  display_id: "AION-99",
  title: "Direct Match Ticket",
  subtitle: "Open · Project A",
  kind: "ticket",
  href: "/tickets/AION-99",
  rank: 100,
  project_id: "proj-1",
  status: "open",
};

// Combined list: 1 problem + 2 tickets + 1 label
const combinedItems = [
  makeProblem(1),
  makeTicket(1),
  makeTicket(2),
  makeLabel(1),
];

const mockTypeaheadResponse = {
  combined: combinedItems,
};

const mockTypeaheadWithDirectMatch = {
  direct_match: directMatchItem,
  combined: combinedItems,
};

const mockEmptyResponse = {};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function renderBar() {
  return render(
    <MemoryRouter>
      <GlobalSearchBar />
    </MemoryRouter>,
  );
}

function getInput(): HTMLElement {
  return (
    (screen.queryByRole("searchbox") ??
      screen.queryByPlaceholderText(/search/i)) as HTMLElement
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  (searchApi.searchTypeahead as ReturnType<typeof vi.fn>).mockResolvedValue(
    mockEmptyResponse,
  );
});

afterEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("GlobalSearchBar typeahead", () => {
  it("(a) calls searchTypeahead after debounce on typing", async () => {
    const user = userEvent.setup();
    renderBar();

    const input = getInput();
    await user.click(input);
    await user.type(input, "Bug");

    // After typing, the hook debounces — wait for the call to arrive
    // A4: signature is now (q, signal, entity) — accept any entity string
    await waitFor(
      () => {
        expect(searchApi.searchTypeahead).toHaveBeenCalledWith(
          "Bug",
          expect.anything(),
          expect.any(String),
        );
      },
      { timeout: 3000 },
    );
  });

  it("(b) dropdown renders entity-grouped rows from combined", async () => {
    const user = userEvent.setup();
    (searchApi.searchTypeahead as ReturnType<typeof vi.fn>).mockResolvedValue(
      mockTypeaheadResponse,
    );

    renderBar();

    const input = getInput();
    await user.click(input);
    await user.type(input, "Bug");

    await waitFor(
      () => {
        // Should see the problem item
        expect(screen.getByText("Bug Problem 1")).toBeInTheDocument();
      },
      { timeout: 3000 },
    );

    // Should see ticket items
    expect(screen.getByText("Bug Ticket 1")).toBeInTheDocument();
    expect(screen.getByText("Bug Ticket 2")).toBeInTheDocument();
    // Should see label item
    expect(screen.getByText("Bug Label 1")).toBeInTheDocument();
  });

  it("(c) direct-match row pinned top, 'View all' pinned bottom", async () => {
    const user = userEvent.setup();
    (searchApi.searchTypeahead as ReturnType<typeof vi.fn>).mockResolvedValue(
      mockTypeaheadWithDirectMatch,
    );

    renderBar();

    const input = getInput();
    await user.click(input);
    await user.type(input, "Bug");

    await waitFor(
      () => {
        expect(screen.getByText("Direct Match Ticket")).toBeInTheDocument();
      },
      { timeout: 3000 },
    );

    // "View all" footer should be present
    const viewAllEl =
      screen.queryByText(/view all results/i) ??
      screen.queryByText(/view all/i);
    expect(viewAllEl).toBeInTheDocument();

    // Verify order: direct match first, then results, then view all
    const allOptions = screen.getAllByRole("option");
    expect(allOptions[0]).toHaveTextContent("Direct Match Ticket");
    const lastOption = allOptions[allOptions.length - 1];
    expect(lastOption).toHaveTextContent(/view all/i);
  });

  it("(d) ArrowDown moves highlight to first item", async () => {
    const user = userEvent.setup();
    (searchApi.searchTypeahead as ReturnType<typeof vi.fn>).mockResolvedValue(
      mockTypeaheadResponse,
    );

    renderBar();

    const input = getInput();
    await user.click(input);
    await user.type(input, "Bug");

    await waitFor(
      () => {
        expect(screen.getByText("Bug Problem 1")).toBeInTheDocument();
      },
      { timeout: 3000 },
    );

    // Press ArrowDown to highlight first item
    await user.keyboard("{ArrowDown}");

    await waitFor(() => {
      // First item should be highlighted
      const highlighted = document.querySelector(
        ".gsb__result-item--highlighted, [data-highlighted='true']",
      );
      expect(highlighted).toBeTruthy();
    });
  });

  it("(e) Enter on a typeahead row navigates to that entity's detail page", async () => {
    const user = userEvent.setup();
    (searchApi.searchTypeahead as ReturnType<typeof vi.fn>).mockResolvedValue(
      mockTypeaheadResponse,
    );

    renderBar();

    const input = getInput();
    await user.click(input);
    await user.type(input, "Bug");

    await waitFor(
      () => {
        expect(screen.getByText("Bug Problem 1")).toBeInTheDocument();
      },
      { timeout: 3000 },
    );

    // Arrow down to first item, then Enter
    await user.keyboard("{ArrowDown}");
    await user.keyboard("{Enter}");

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalled();
    });

    // Should navigate to an entity page (not /search)
    const callArg = mockNavigate.mock.calls[0][0] as string;
    expect(callArg).not.toContain("/search");
  });

  it("(f) clicking 'View all' navigates to /search?q=Bug", async () => {
    const user = userEvent.setup();
    (searchApi.searchTypeahead as ReturnType<typeof vi.fn>).mockResolvedValue(
      mockTypeaheadResponse,
    );

    renderBar();

    const input = getInput();
    await user.click(input);
    await user.type(input, "Bug");

    await waitFor(
      () => {
        const viewAllEl =
          screen.queryByText(/view all results/i) ??
          screen.queryByText(/view all/i);
        expect(viewAllEl).toBeInTheDocument();
      },
      { timeout: 3000 },
    );

    // Click "View all" button
    const viewAllEl =
      screen.queryByText(/view all results/i) ??
      screen.queryByText(/view all/i);
    await user.click(viewAllEl!);

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith("/search?q=Bug");
    });
  });

  it("(f-keyboard) Enter on 'View all' (last item via ArrowDown wrap) navigates to /search?q=Bug", async () => {
    const user = userEvent.setup();
    (searchApi.searchTypeahead as ReturnType<typeof vi.fn>).mockResolvedValue(
      mockTypeaheadResponse,
    );

    renderBar();

    const input = getInput();
    await user.click(input);
    await user.type(input, "Bug");

    await waitFor(
      () => {
        const viewAllEl =
          screen.queryByText(/view all results/i) ??
          screen.queryByText(/view all/i);
        expect(viewAllEl).toBeInTheDocument();
      },
      { timeout: 3000 },
    );

    // Arrow up from "no highlight" wraps to last item (View all)
    await user.keyboard("{ArrowUp}");
    await user.keyboard("{Enter}");

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith("/search?q=Bug");
    });
  });

  it("(g) Esc closes the dropdown", async () => {
    const user = userEvent.setup();
    (searchApi.searchTypeahead as ReturnType<typeof vi.fn>).mockResolvedValue(
      mockTypeaheadResponse,
    );

    renderBar();

    const input = getInput();
    await user.click(input);
    await user.type(input, "Bug");

    await waitFor(
      () => {
        expect(screen.getByText("Bug Problem 1")).toBeInTheDocument();
      },
      { timeout: 3000 },
    );

    // Dropdown is open — press Escape
    await user.keyboard("{Escape}");

    await waitFor(() => {
      expect(screen.queryByText("Bug Problem 1")).not.toBeInTheDocument();
    });
  });

  it("(h) keystroke during in-flight request aborts the previous fetch signal", async () => {
    const user = userEvent.setup();

    const capturedSignals: AbortSignal[] = [];
    (searchApi.searchTypeahead as ReturnType<typeof vi.fn>).mockImplementation(
      (_q: string, signal: AbortSignal) => {
        capturedSignals.push(signal);
        // Return a never-resolving promise to simulate long in-flight request
        return new Promise<never>(() => {});
      },
    );

    renderBar();

    const input = getInput();
    await user.click(input);
    await user.type(input, "B");

    // Wait for first fetch
    await waitFor(
      () => {
        expect(capturedSignals.length).toBeGreaterThanOrEqual(1);
      },
      { timeout: 3000 },
    );

    // Type another character — should abort the previous request
    await user.type(input, "u");

    await waitFor(
      () => {
        expect(capturedSignals.length).toBeGreaterThanOrEqual(2);
      },
      { timeout: 3000 },
    );

    // The first signal should be aborted because the second keystroke cancelled it
    expect(capturedSignals[0].aborted).toBe(true);
  });

  it("Cmd-K still focuses the input (A1b regression)", async () => {
    const user = userEvent.setup();
    renderBar();

    const input = getInput();
    expect(document.activeElement).not.toBe(input);

    await user.keyboard("{Meta>}k{/Meta}");

    await waitFor(() => {
      expect(document.activeElement).toBe(getInput());
    });
  });
});
