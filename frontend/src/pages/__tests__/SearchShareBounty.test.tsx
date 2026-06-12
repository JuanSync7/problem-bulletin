/**
 * v2.29-S6 — Search page: Share / Bounties tabs + recent-search chips.
 *
 * Same harness as Search.test.tsx (searchV2 mocked via vi.mock; no MSW).
 *
 * Tests:
 *  1. Share tab fires searchV2 with entity=share_posts
 *  2. Bounties tab fires searchV2 with entity=bounties
 *  3. share_post / bounty results render with KindPill labels
 *  4. (audit P2#17) recent-search chips render from the GlobalSearchBar
 *     localStorage store on the pre-query empty state
 *  5. clicking a chip runs that search
 */

import "@testing-library/jest-dom";
import {
  render,
  screen,
  waitFor,
  fireEvent,
  act,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";

// ---------------------------------------------------------------------------
// Mocks — declared BEFORE the component import; vi.mock is hoisted.
// ---------------------------------------------------------------------------

const mockNavigate = vi.fn();
vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

const mockSearchV2 = vi.fn();
vi.mock("../../api/search", () => ({
  searchV2: (...args: unknown[]) => mockSearchV2(...args),
}));

vi.mock("../../api/projects", () => ({
  listProjects: () => Promise.resolve({ items: [], next_cursor: null, total: 0 }),
}));

vi.mock("../../hooks/useAuth", () => ({
  useAuth: () => ({
    isAuthenticated: true,
    user: { id: "user-s6", email: "s6@example.com", displayName: "S6", role: "user" },
    isLoading: false,
    error: null,
  }),
}));

import Search from "../Search";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const RECENTS_KEY = "aion.search.recents.user-s6";

function renderSearch(initialEntries: string[] = ["/search"]) {
  return render(
    <MemoryRouter
      initialEntries={initialEntries}
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <Search />
    </MemoryRouter>,
  );
}

function getTab(label: string) {
  return screen.getByRole("tab", { name: new RegExp(`^${label}$`, "i") });
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.removeItem(RECENTS_KEY);
  mockSearchV2.mockResolvedValue({});
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: () => Promise.resolve([]),
  } as unknown as Response);
});

afterEach(() => {
  localStorage.removeItem(RECENTS_KEY);
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("Search (v2.29-S6) — Share / Bounties tabs", () => {
  it("Share tab fires searchV2 with entity=share_posts", async () => {
    mockSearchV2.mockResolvedValue({ share_posts: { items: [], total: 0 } });
    renderSearch(["/search?q=prompt"]);

    fireEvent.click(getTab("Share"));

    await waitFor(() => {
      expect(mockSearchV2).toHaveBeenCalledWith(
        expect.objectContaining({ q: "prompt", entity: "share_posts" }),
      );
    });
    expect(getTab("Share")).toHaveAttribute("aria-selected", "true");
  });

  it("Bounties tab fires searchV2 with entity=bounties", async () => {
    mockSearchV2.mockResolvedValue({ bounties: { items: [], total: 0 } });
    renderSearch(["/search?q=flaky"]);

    fireEvent.click(getTab("Bounties"));

    await waitFor(() => {
      expect(mockSearchV2).toHaveBeenCalledWith(
        expect.objectContaining({ q: "flaky", entity: "bounties" }),
      );
    });
    expect(getTab("Bounties")).toHaveAttribute("aria-selected", "true");
  });

  it("URL sync — ?entity=share_posts selects the Share tab on mount", async () => {
    mockSearchV2.mockResolvedValue({ share_posts: { items: [], total: 0 } });
    renderSearch(["/search?entity=share_posts"]);

    await waitFor(() => {
      expect(getTab("Share")).toHaveAttribute("aria-selected", "true");
    });
  });

  it("renders share_post and bounty results with their kind pills", async () => {
    mockSearchV2.mockResolvedValue({
      share_posts: {
        items: [
          {
            id: "sp-1",
            display_id: null,
            title: "Prompting tips",
            subtitle: "How we prompt agents...",
            kind: "share_post",
            href: "/share#sp-1",
            rank: 1.0,
            project_id: null,
            status: null,
          },
        ],
        total: 1,
      },
    });

    renderSearch(["/search?q=prompt&entity=share_posts"]);

    await screen.findByText("Prompting tips");
    // KindPill renders the "share" display label for share_post.
    expect(screen.getByText("share")).toBeInTheDocument();
  });

  it("clicking a share_post result navigates to its href", async () => {
    mockSearchV2.mockResolvedValue({
      bounties: {
        items: [
          {
            id: "b-1",
            display_id: null,
            title: "Fix the flaky test",
            subtitle: "50 points",
            kind: "bounty",
            href: "/bounties#b-1",
            rank: 1.0,
            project_id: null,
            status: "open",
          },
        ],
        total: 1,
      },
    });

    renderSearch(["/search?q=flaky&entity=bounties"]);

    const title = await screen.findByText("Fix the flaky test");
    fireEvent.click(title.closest("article")!);
    expect(mockNavigate).toHaveBeenCalledWith("/bounties#b-1");
  });
});

describe("Search (v2.29-S6, audit P2#17) — recent-search chips", () => {
  it("renders recent-search chips from localStorage on the pre-query empty state", () => {
    localStorage.setItem(
      RECENTS_KEY,
      JSON.stringify(["kanban bug", "agent runs"]),
    );

    renderSearch(["/search"]);

    const group = screen.getByRole("group", { name: /recent searches/i });
    expect(group).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "kanban bug" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "agent runs" })).toBeInTheDocument();
  });

  it("does not render the chips section when there are no recents", () => {
    renderSearch(["/search"]);
    expect(
      screen.queryByRole("group", { name: /recent searches/i }),
    ).not.toBeInTheDocument();
  });

  it("clicking a chip runs that search", async () => {
    localStorage.setItem(RECENTS_KEY, JSON.stringify(["kanban bug"]));
    mockSearchV2.mockResolvedValue({
      problems: { items: [], total: 0 },
      tickets: { items: [], total: 0 },
      components: { items: [], total: 0 },
      labels: { items: [], total: 0 },
      users: { items: [], total: 0 },
      share_posts: { items: [], total: 0 },
      bounties: { items: [], total: 0 },
    });

    renderSearch(["/search"]);

    vi.useFakeTimers();
    fireEvent.click(screen.getByRole("button", { name: "kanban bug" }));
    act(() => {
      vi.advanceTimersByTime(350);
    });
    vi.useRealTimers();

    await waitFor(() => {
      expect(mockSearchV2).toHaveBeenCalledWith(
        expect.objectContaining({ q: "kanban bug", entity: "all" }),
      );
    });
    // Input reflects the chip's query.
    expect(screen.getByRole("textbox")).toHaveValue("kanban bug");
  });
});
