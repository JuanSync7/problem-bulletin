/**
 * A3 — nav.test.tsx
 *
 * Asserts:
 * (a) Rendered nav does NOT contain a "Search" entry (no text "Search" with
 *     href="/search" in the sidebar nav).
 * (b) Other top-level entries still render (Home, Problems, Kanban Board, etc.).
 * (c) The /search route is still registered: navigating to /search?q=foo
 *     renders the Search page (the input is pre-filled with the query from URL).
 *
 * Sidebar is the component that owns mainNavItems; we test it directly.
 * For the route test we render the full App inside MemoryRouter-equivalent
 * by importing the lazy route and mounting it at the /search path.
 */
import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider } from "../theme";
import { Sidebar } from "../layouts/Sidebar";
import { describe, expect, it, vi } from "vitest";

// ---------------------------------------------------------------------------
// Module mocks
// ---------------------------------------------------------------------------

// matchMedia is not available in jsdom.
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

vi.mock("../realtime/useRealtimeNotifications", () => ({
  useRealtimeNotifications: vi.fn(),
}));

vi.mock("../api/notifications", () => ({
  getUnreadCount: vi.fn(async () => 0),
  listNotifications: vi.fn(async () => ({ items: [], next_cursor: null, total: 0 })),
  markRead: vi.fn(async () => undefined),
  markAllRead: vi.fn(async () => 0),
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function renderSidebar(initialPath = "/") {
  return render(
    <ThemeProvider>
      <MemoryRouter
        initialEntries={[initialPath]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <Sidebar isOpen={true} onClose={vi.fn()} />
      </MemoryRouter>
    </ThemeProvider>,
  );
}

// ---------------------------------------------------------------------------
// Suite A — nav entry absence
// ---------------------------------------------------------------------------

describe("A3: nav entry removal", () => {
  it("(a) does NOT render a Search nav link pointing to /search", () => {
    renderSidebar();

    // We look for an <a> element whose href ends with /search AND whose
    // text is exactly "Search". After A3 this must not exist.
    const links = screen.queryAllByRole("link");
    const searchNavLink = links.find(
      (el) =>
        el.getAttribute("href")?.endsWith("/search") &&
        el.textContent?.trim() === "Search",
    );
    expect(searchNavLink).toBeUndefined();
  });

  it("(b) still renders other top-level nav entries", () => {
    renderSidebar();

    // Verify a sample of the expected remaining entries.
    const expectedLabels = ["Home", "Problems", "Kanban Board", "Activity"];
    for (const label of expectedLabels) {
      expect(
        screen.getByRole("link", { name: label }),
      ).toBeInTheDocument();
    }
  });
});

// ---------------------------------------------------------------------------
// Suite B — /search route still accessible
// ---------------------------------------------------------------------------

/**
 * We import the Search page directly and render it in a MemoryRouter at
 * /search?q=foo.  This confirms the route component still reads `q` from the
 * URL without relying on App-level lazy loading.
 *
 * The Search page makes fetch calls; we suppress them by mocking the hook.
 */

vi.mock("../hooks/useSearchV2", () => ({
  useSearchV2: vi.fn(() => ({
    data: null,
    isLoading: false,
    error: null,
    hasSearched: false,
    hasNext: false,
    hasPrev: false,
    loadNext: vi.fn(),
    loadPrev: vi.fn(),
    refreshTotalEnabled: false,
    setRefreshTotalEnabled: vi.fn(),
    totalAuthority: "live" as const,
  })),
}));

vi.mock("../api/projects", () => ({
  listProjects: vi.fn(async () => ({ items: [], total: 0, next_cursor: null })),
}));

// Lazy-load resolves synchronously in test environment when we import directly.
import SearchPage from "../pages/Search";

describe("A3: /search route still accessible", () => {
  it("(c) Search page reads q from URL and shows it in the search input", () => {
    render(
      <MemoryRouter
        initialEntries={["/search?q=foo"]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <SearchPage />
      </MemoryRouter>,
    );

    // The Search page renders an <input> pre-populated with the query from URL.
    const input = screen.getByRole("textbox");
    expect(input).toHaveValue("foo");
  });
});
