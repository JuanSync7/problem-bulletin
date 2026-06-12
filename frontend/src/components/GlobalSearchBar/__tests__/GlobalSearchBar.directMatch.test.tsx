/**
 * A1b: GlobalSearchBar component tests.
 *
 * Validates:
 *  - Cmd-K (Meta+K) focuses the search input
 *  - Ctrl-K focuses the search input
 *  - Typing AION-1 and pressing Enter on a direct_match navigates to /tickets/AION-1
 *  - Direct-match row renders in the dropdown
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

// Mock the search API module before importing the component
vi.mock("../../../api/search", () => ({
  searchTypeahead: vi.fn(),
  isTypeaheadResponse: vi.fn(() => true),
}));

// Mock useAuth (A4: index.tsx now uses useAuth for recents localStorage key)
vi.mock("../../../hooks/useAuth", () => ({
  useAuth: () => ({
    isAuthenticated: true,
    user: { id: "test-user", email: "test@example.com", displayName: "Test", role: "user" },
    isLoading: false,
    error: null,
  }),
}));

// mock useNavigate from react-router-dom
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

const directMatchItem = {
  id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
  display_id: "AION-1",
  title: "Fix login bug",
  subtitle: "Open · Project A",
  kind: "ticket",
  href: "/tickets/AION-1",
  rank: 1.0,
  project_id: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
  status: "open",
};

const mockDirectMatchResponse = {
  direct_match: directMatchItem,
};

const mockNoMatchResponse = {
  // direct_match absent (backend omits when null)
};

beforeEach(() => {
  vi.clearAllMocks();
  (searchApi.searchTypeahead as ReturnType<typeof vi.fn>).mockResolvedValue(
    mockNoMatchResponse,
  );
});

afterEach(() => {
  vi.clearAllMocks();
});

function renderBar() {
  return render(
    <MemoryRouter>
      <GlobalSearchBar />
    </MemoryRouter>,
  );
}

describe("GlobalSearchBar", () => {
  it("renders a search input", () => {
    renderBar();
    expect(
      screen.getByRole("searchbox", { name: /search/i }) ||
        screen.getByPlaceholderText(/search/i),
    ).toBeTruthy();
  });

  it("focuses the input on Cmd-K (Meta+K)", async () => {
    const user = userEvent.setup();
    renderBar();

    // Input should not be focused initially
    const input =
      screen.queryByRole("searchbox") ??
      (screen.queryByPlaceholderText(/search/i) as HTMLElement);
    expect(document.activeElement).not.toBe(input);

    await user.keyboard("{Meta>}k{/Meta}");

    await waitFor(() => {
      expect(document.activeElement).toBe(
        screen.queryByRole("searchbox") ??
          screen.queryByPlaceholderText(/search/i),
      );
    });
  });

  it("focuses the input on Ctrl-K", async () => {
    const user = userEvent.setup();
    renderBar();

    const input =
      screen.queryByRole("searchbox") ??
      (screen.queryByPlaceholderText(/search/i) as HTMLElement);
    expect(document.activeElement).not.toBe(input);

    await user.keyboard("{Control>}k{/Control}");

    await waitFor(() => {
      expect(document.activeElement).toBe(
        screen.queryByRole("searchbox") ??
          screen.queryByPlaceholderText(/search/i),
      );
    });
  });

  it("calls searchTypeahead when input changes", async () => {
    const user = userEvent.setup();
    renderBar();

    const input =
      screen.getByRole("searchbox") ??
      screen.getByPlaceholderText(/search/i);

    await user.click(input);
    await user.type(input, "AION-1");

    // A4: searchTypeahead now takes (q, signal, entity) — accept any entity string
    await waitFor(() => {
      expect(searchApi.searchTypeahead).toHaveBeenCalledWith(
        "AION-1",
        expect.anything(),
        expect.any(String),
      );
    });
  });

  it("shows the direct-match row when response has direct_match", async () => {
    (searchApi.searchTypeahead as ReturnType<typeof vi.fn>).mockResolvedValue(
      mockDirectMatchResponse,
    );

    const user = userEvent.setup();
    renderBar();

    const input =
      screen.getByRole("searchbox") ??
      screen.getByPlaceholderText(/search/i);
    await user.click(input);
    await user.type(input, "AION-1");

    await waitFor(() => {
      expect(screen.getByText("Fix login bug")).toBeInTheDocument();
    });
  });

  it("navigates to /tickets/AION-1 on Enter when direct_match is present", async () => {
    (searchApi.searchTypeahead as ReturnType<typeof vi.fn>).mockResolvedValue(
      mockDirectMatchResponse,
    );

    const user = userEvent.setup();
    renderBar();

    const input =
      screen.getByRole("searchbox") ??
      screen.getByPlaceholderText(/search/i);
    await user.click(input);
    await user.type(input, "AION-1");

    await waitFor(() => {
      expect(screen.getByText("Fix login bug")).toBeInTheDocument();
    });

    await user.keyboard("{Enter}");

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith("/tickets/AION-1");
    });
  });

  it("does not navigate on Enter when there is no direct_match", async () => {
    (searchApi.searchTypeahead as ReturnType<typeof vi.fn>).mockResolvedValue(
      mockNoMatchResponse,
    );

    const user = userEvent.setup();
    renderBar();

    const input =
      screen.getByRole("searchbox") ??
      screen.getByPlaceholderText(/search/i);
    await user.click(input);
    await user.type(input, "AION-1");

    await waitFor(() => {
      expect(searchApi.searchTypeahead).toHaveBeenCalled();
    });

    await user.keyboard("{Enter}");
    // navigate should not have been called
    expect(mockNavigate).not.toHaveBeenCalled();
  });
});
