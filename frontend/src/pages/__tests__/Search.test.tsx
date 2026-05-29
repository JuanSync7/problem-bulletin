/**
 * WP57 — Tabbed multi-entity search page tests.
 * WP58 — Additional behaviour tests (tests 8–12).
 *
 * MSW is not configured in this project; the search API client is mocked via
 * vi.mock() per the existing Settings / SettingsAdmin pattern.
 *
 * Tests:
 *  1. renders all six tabs
 *  2. tab switch preserves query
 *  3. URL sync — ?entity=users selects users tab on mount
 *  4. clicking a ticket result navigates to /tickets/<display_id>
 *  5. problem-status filter only renders on Problems tab
 *  6. empty results renders friendly empty state per tab
 *  7. aborts in-flight request when tab changes
 *  8. (WP58) category filter only renders on Problems tab
 *  9. (WP58) typing query updates ?q= in the URL
 * 10. (WP58) back/forward navigation restores tab and query
 * 11. (WP58) clicking a problem result navigates to /problems/<id>
 * 12. (WP58) users tab renders both user and agent kinds
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

// ---------------------------------------------------------------------------
// Import subject under test (after vi.mock declarations).
// ---------------------------------------------------------------------------

import Search from "../Search";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function emptyAllResponse() {
  return {
    problems: { items: [], total: 0 },
    tickets: { items: [], total: 0 },
    components: { items: [], total: 0 },
    labels: { items: [], total: 0 },
    users: { items: [], total: 0 },
  };
}

function makeTicketItem(overrides: object = {}) {
  return {
    id: "t-uuid-1",
    display_id: "PROJ-42",
    title: "Fix login bug",
    subtitle: "PROJ | todo",
    kind: "ticket",
    href: "/tickets/PROJ-42",
    rank: 0.8,
    project_id: "proj-1",
    status: "todo",
    ...overrides,
  };
}

function renderSearch(initialEntries: string[] = ["/search"]) {
  return render(
    <MemoryRouter initialEntries={initialEntries} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <Search />
    </MemoryRouter>,
  );
}

/**
 * Find a tab button by label prefix. The count badge is aria-hidden so the
 * accessible name is just the label text (e.g. "Tickets" not "Tickets 3").
 */
function getTab(label: string) {
  return screen.getByRole("tab", { name: new RegExp(`^${label}$`, "i") });
}

// ---------------------------------------------------------------------------
// Setup / Teardown
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
  mockSearchV2.mockResolvedValue(emptyAllResponse());
  // Stub the /api/admin/categories fetch used inside the component.
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: () => Promise.resolve([]),
  } as unknown as Response);
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("Search (WP57) — tabbed search page", () => {
  // 1. Renders all six tabs
  it("renders all six tabs", () => {
    renderSearch();
    expect(screen.getAllByRole("tab")).toHaveLength(6);
    // Count badge is aria-hidden, so accessible names are clean labels only.
    expect(screen.getByRole("tab", { name: "All" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Problems" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Tickets" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Components" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Labels" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Users" })).toBeInTheDocument();
  });

  // 2. Tab switch preserves query
  it("tab switch preserves query — calls searchV2 with entity=tickets after switch", async () => {
    renderSearch();

    const input = screen.getByRole("textbox");

    // Type query and advance debounce.
    vi.useFakeTimers();
    fireEvent.change(input, { target: { value: "foo" } });
    act(() => { vi.advanceTimersByTime(350); });
    vi.useRealTimers();

    await waitFor(() => {
      expect(mockSearchV2).toHaveBeenCalledWith(
        expect.objectContaining({ q: "foo", entity: "all" }),
      );
    });

    mockSearchV2.mockClear();
    mockSearchV2.mockResolvedValue({ tickets: { items: [], total: 0 } });

    fireEvent.click(getTab("Tickets"));

    await waitFor(() => {
      expect(mockSearchV2).toHaveBeenCalledWith(
        expect.objectContaining({ q: "foo", entity: "tickets" }),
      );
    });

    // Input still holds the original value.
    expect(screen.getByRole("textbox")).toHaveValue("foo");
  });

  // 3. URL sync — ?entity=users selects users tab on mount
  it("URL sync — ?entity=users selects Users tab on mount", async () => {
    mockSearchV2.mockResolvedValue({ users: { items: [], total: 0 } });
    renderSearch(["/search?entity=users"]);

    await waitFor(() => {
      const usersTab = getTab("Users");
      expect(usersTab).toHaveAttribute("aria-selected", "true");
    });
  });

  // 4. Clicking a ticket result navigates to /tickets/<display_id>
  it("clicking a ticket result navigates to /tickets/<display_id>", async () => {
    const ticketItem = makeTicketItem();
    mockSearchV2.mockResolvedValue({ tickets: { items: [ticketItem], total: 1 } });

    renderSearch(["/search?q=login+bug&entity=tickets"]);

    const resultTitle = await screen.findByText("Fix login bug");
    // Click the article card that wraps the title.
    fireEvent.click(resultTitle.closest("article")!);

    expect(mockNavigate).toHaveBeenCalledWith("/tickets/PROJ-42");
  });

  // 5. Problem-status filter only renders on Problems tab; ticket-status only on Tickets tab
  it("problem-status filter only renders on Problems tab", async () => {
    renderSearch();

    // "All" tab is default — no per-arm filters.
    expect(screen.queryByLabelText("Problem status")).toBeNull();
    expect(screen.queryByLabelText("Ticket status")).toBeNull();

    // Switch to Tickets — ticket-status appears; problem-status absent.
    fireEvent.click(getTab("Tickets"));
    expect(screen.queryByLabelText("Problem status")).toBeNull();
    expect(screen.getByLabelText("Ticket status")).toBeInTheDocument();

    // Switch to Problems — problem-status appears; ticket-status absent.
    fireEvent.click(getTab("Problems"));
    expect(screen.getByLabelText("Problem status")).toBeInTheDocument();
    expect(screen.queryByLabelText("Ticket status")).toBeNull();
  });

  // 6. Empty results renders friendly empty state per tab
  it("empty results renders friendly empty state per tab", async () => {
    mockSearchV2.mockResolvedValue({ problems: { items: [], total: 0 } });
    renderSearch(["/search?entity=problems"]);

    const input = screen.getByRole("textbox");
    vi.useFakeTimers();
    fireEvent.change(input, { target: { value: "xyzzy" } });
    act(() => { vi.advanceTimersByTime(350); });
    vi.useRealTimers();

    await waitFor(() => {
      expect(screen.getByText(/no problems found/i)).toBeInTheDocument();
    });
  });

  // 7. Aborts in-flight request when tab changes
  it("aborts in-flight request when tab changes", async () => {
    let capturedSignal: AbortSignal | undefined;

    // First call: never resolves (simulates in-flight).
    mockSearchV2.mockImplementationOnce(({ signal }: { signal?: AbortSignal }) => {
      capturedSignal = signal;
      return new Promise(() => {});
    });
    // Subsequent calls: return empty so the component doesn't get stuck.
    mockSearchV2.mockResolvedValue(emptyAllResponse());

    renderSearch();

    const input = screen.getByRole("textbox");
    vi.useFakeTimers();
    fireEvent.change(input, { target: { value: "slow-query" } });
    act(() => { vi.advanceTimersByTime(350); });
    vi.useRealTimers();

    await waitFor(() => {
      expect(mockSearchV2).toHaveBeenCalled();
      expect(capturedSignal).toBeDefined();
    });

    expect(capturedSignal!.aborted).toBe(false);

    // Switching the tab aborts the in-flight controller.
    fireEvent.click(getTab("Tickets"));

    expect(capturedSignal!.aborted).toBe(true);
  });

  // ---------------------------------------------------------------------------
  // WP58 additional tests
  // ---------------------------------------------------------------------------

  // 8. category filter only renders on Problems tab
  it("category filter only renders on Problems tab", async () => {
    renderSearch();

    // All tab: no category filter
    expect(screen.queryByLabelText("Problem category")).toBeNull();

    // Tickets tab: no category filter
    fireEvent.click(getTab("Tickets"));
    expect(screen.queryByLabelText("Problem category")).toBeNull();

    // Components tab: no category filter
    fireEvent.click(getTab("Components"));
    expect(screen.queryByLabelText("Problem category")).toBeNull();

    // Problems tab: category filter appears alongside status filter
    fireEvent.click(getTab("Problems"));
    expect(screen.getByLabelText("Problem category")).toBeInTheDocument();
    expect(screen.getByLabelText("Problem status")).toBeInTheDocument();

    // Switch away: category filter disappears
    fireEvent.click(getTab("Labels"));
    expect(screen.queryByLabelText("Problem category")).toBeNull();
  });

  // 9. URL sync — typing query updates ?q=... in the URL
  it("URL sync — typing query updates ?q= in the URL", async () => {
    // We verify URL sync by checking that searchV2 is called with the typed query,
    // which only happens when the debounced query (derived from URL state) updates.
    renderSearch();

    const input = screen.getByRole("textbox");
    vi.useFakeTimers();
    fireEvent.change(input, { target: { value: "urlsync" } });
    act(() => { vi.advanceTimersByTime(350); });
    vi.useRealTimers();

    await waitFor(() => {
      expect(mockSearchV2).toHaveBeenCalledWith(
        expect.objectContaining({ q: "urlsync" }),
      );
    });

    // The input still shows the typed value (state is consistent with URL q param).
    expect(screen.getByRole("textbox")).toHaveValue("urlsync");
  });

  // 10. back/forward navigation restores tab + query
  it("back/forward navigation — ?entity=labels&q=nav mounts on Labels tab with query", async () => {
    // Simulate a URL that encodes both entity and q, as a user would arrive
    // at after using browser back/forward to a previously-visited search URL.
    mockSearchV2.mockResolvedValue({ labels: { items: [], total: 0 } });
    renderSearch(["/search?entity=labels&q=nav"]);

    await waitFor(() => {
      const labelsTab = getTab("Labels");
      expect(labelsTab).toHaveAttribute("aria-selected", "true");
    });

    // The query input is pre-populated with "nav" from the URL
    expect(screen.getByRole("textbox")).toHaveValue("nav");

    // The search was fired with the correct entity and query
    await waitFor(() => {
      expect(mockSearchV2).toHaveBeenCalledWith(
        expect.objectContaining({ q: "nav", entity: "labels" }),
      );
    });
  });

  // 11. clicking a problem result navigates to /problems/<id>
  it("clicking a problem result navigates to /problems/<id>", async () => {
    const problemItem = {
      id: "prob-uuid-99",
      display_id: null,
      title: "Database crashes under load",
      subtitle: "A critical issue",
      kind: "problem",
      href: "/problems/prob-uuid-99",
      rank: 0.9,
      project_id: null,
      status: "open",
    };
    mockSearchV2.mockResolvedValue({ problems: { items: [problemItem], total: 1 } });

    renderSearch(["/search?q=database+crash&entity=problems"]);

    const resultTitle = await screen.findByText("Database crashes under load");
    fireEvent.click(resultTitle.closest("article")!);

    expect(mockNavigate).toHaveBeenCalledWith("/problems/prob-uuid-99");
  });

  // ---------------------------------------------------------------------------
  // WP08 — cursor-driven pagination
  // ---------------------------------------------------------------------------

  it("WP08: clicking Next forwards the active arm's next_cursor to searchV2", async () => {
    const ticketItem = makeTicketItem();
    mockSearchV2.mockResolvedValueOnce({
      tickets: { items: [ticketItem], total: 50, next_cursor: "CUR-2" },
    });
    mockSearchV2.mockResolvedValueOnce({
      tickets: {
        items: [makeTicketItem({ id: "t-uuid-2", display_id: "PROJ-43" })],
        total: 50,
        next_cursor: "CUR-3",
      },
    });

    renderSearch(["/search?q=login&entity=tickets"]);

    const nextBtn = await screen.findByRole("button", { name: /next page/i });
    await waitFor(() => expect(nextBtn).not.toBeDisabled());

    fireEvent.click(nextBtn);

    await waitFor(() => {
      expect(mockSearchV2).toHaveBeenCalledWith(
        expect.objectContaining({ entity: "tickets", cursor: "CUR-2" }),
      );
    });
  });

  it("WP08: Prev is disabled on first page and enabled after Next", async () => {
    const ticketItem = makeTicketItem();
    mockSearchV2.mockResolvedValueOnce({
      tickets: { items: [ticketItem], total: 50, next_cursor: "CUR-2" },
    });
    mockSearchV2.mockResolvedValueOnce({
      tickets: {
        items: [makeTicketItem({ id: "t-uuid-2", display_id: "PROJ-43" })],
        total: 50,
        next_cursor: "CUR-3",
      },
    });

    renderSearch(["/search?q=login&entity=tickets"]);

    const prevBtn = await screen.findByRole("button", { name: /previous page/i });
    const nextBtn = await screen.findByRole("button", { name: /next page/i });

    await waitFor(() => expect(nextBtn).not.toBeDisabled());
    expect(prevBtn).toBeDisabled();

    fireEvent.click(nextBtn);

    await waitFor(() => expect(mockSearchV2).toHaveBeenCalledTimes(2));
    await waitFor(() => {
      const p = screen.getByRole("button", { name: /previous page/i });
      expect(p).not.toBeDisabled();
    });
  });

  it("WP08: pagination row is hidden when there is no next_cursor and no prev", async () => {
    mockSearchV2.mockResolvedValue({
      tickets: { items: [makeTicketItem()], total: 1, next_cursor: null },
    });

    renderSearch(["/search?q=initial&entity=tickets"]);

    // Result card renders.
    await screen.findByText("Fix login bug");
    // No pagination controls because both hasPrev and hasNext are false.
    expect(screen.queryByRole("button", { name: /next page/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /previous page/i })).toBeNull();
  });

  it("WP08: new query resets the cursor stack — Next reflects only the latest response", async () => {
    // First (initial mount) response: has next_cursor.
    mockSearchV2.mockResolvedValueOnce({
      tickets: { items: [makeTicketItem()], total: 50, next_cursor: "CUR-2" },
    });
    // Second response (after debounced query input change): no next_cursor.
    mockSearchV2.mockResolvedValue({
      tickets: { items: [makeTicketItem({ id: "t-uuid-9", display_id: "PROJ-99" })], total: 1, next_cursor: null },
    });

    renderSearch(["/search?q=foo&entity=tickets"]);

    await waitFor(() => {
      const nextBtn = screen.getByRole("button", { name: /next page/i });
      expect(nextBtn).not.toBeDisabled();
    });

    // Type a new query; advance debounce.
    const input = screen.getByRole("textbox");
    vi.useFakeTimers();
    fireEvent.change(input, { target: { value: "freshquery" } });
    act(() => { vi.advanceTimersByTime(350); });
    vi.useRealTimers();

    // After the new fetch, no next_cursor means pagination row gone.
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: /next page/i })).toBeNull();
    });
  });

  // 12. users tab renders both user and agent kinds
  it("users tab renders both user and agent kinds in results", async () => {
    const userItem = {
      id: "user-uuid-1",
      display_id: "alice_dev",
      title: "Alice Dev",
      subtitle: "@alice_dev",
      kind: "user",
      href: "/users/alice_dev",
      rank: 1.0,
      project_id: null,
      status: null,
    };
    const agentItem = {
      id: "agent-uuid-1",
      display_id: "claude_bot",
      title: "Claude Bot",
      subtitle: "@claude_bot",
      kind: "agent",
      href: "/users/claude_bot",
      rank: 1.0,
      project_id: null,
      status: null,
    };
    mockSearchV2.mockResolvedValue({
      users: { items: [userItem, agentItem], total: 2 },
    });

    renderSearch(["/search?q=dev&entity=users"]);

    // Both items appear
    await screen.findByText("Alice Dev");
    await screen.findByText("Claude Bot");

    // The kind badges are rendered — check via text content inside the badge spans
    const badges = await screen.findAllByText(/^(user|agent)$/i);
    const kinds = badges.map((el) => el.textContent?.toLowerCase());
    expect(kinds).toContain("user");
    expect(kinds).toContain("agent");
  });

  // ---------------------------------------------------------------------------
  // WP11 — URL filter sync (all filters, not just q + entity)
  // ---------------------------------------------------------------------------

  // WP11.1 — mount with full filter URL → ticket_status seeded and forwarded
  it("WP11: mount with ?q=&entity=tickets&ticket_status=todo seeds ticket_status filter", async () => {
    mockSearchV2.mockResolvedValue({ tickets: { items: [], total: 0 } });
    renderSearch(["/search?q=hello&entity=tickets&ticket_status=todo"]);

    await waitFor(() => {
      expect(mockSearchV2).toHaveBeenCalledWith(
        expect.objectContaining({
          q: "hello",
          entity: "tickets",
          ticket_status: "todo",
        }),
      );
    });

    // Dropdown is pre-populated.
    const dropdown = screen.getByLabelText("Ticket status") as HTMLSelectElement;
    expect(dropdown.value).toBe("todo");
  });

  // WP11.2 — mount with ?entity=problems&problem_status=open seeds problem_status
  it("WP11: mount with ?entity=problems&problem_status=open seeds problem_status filter", async () => {
    mockSearchV2.mockResolvedValue({ problems: { items: [], total: 0 } });
    renderSearch(["/search?q=any&entity=problems&problem_status=open"]);

    await waitFor(() => {
      expect(mockSearchV2).toHaveBeenCalledWith(
        expect.objectContaining({
          q: "any",
          entity: "problems",
          problem_status: "open",
        }),
      );
    });

    const dropdown = screen.getByLabelText("Problem status") as HTMLSelectElement;
    expect(dropdown.value).toBe("open");
  });

  // WP11.3 — invalid entity in URL falls back to "all" (no crash)
  it("WP11: invalid entity in URL falls back to 'all' without crashing", async () => {
    renderSearch(["/search?entity=pizza"]);

    // "All" tab is selected.
    const allTab = getTab("All");
    expect(allTab).toHaveAttribute("aria-selected", "true");
  });

  // WP11.4 — invalid problem_status in URL is ignored, dropdown remains empty
  it("WP11: invalid problem_status in URL is ignored", async () => {
    mockSearchV2.mockResolvedValue({ problems: { items: [], total: 0 } });
    renderSearch(["/search?q=any&entity=problems&problem_status=banana"]);

    const dropdown = screen.getByLabelText("Problem status") as HTMLSelectElement;
    // Either "" or any-other-empty default; the "banana" must NOT be selected.
    expect(dropdown.value).toBe("");

    // And the fetch is not given the bogus value.
    await waitFor(() => {
      const lastCall = mockSearchV2.mock.calls.at(-1);
      expect(lastCall).toBeDefined();
      expect(lastCall![0]).toEqual(
        expect.objectContaining({ entity: "problems" }),
      );
      expect(lastCall![0]).not.toEqual(
        expect.objectContaining({ problem_status: "banana" }),
      );
    });
  });

  // WP11.5 — changing problem_status writes problem_status to URL via searchV2 call
  it("WP11: changing ticket_status updates fetch with new ticket_status", async () => {
    mockSearchV2.mockResolvedValue({ tickets: { items: [], total: 0 } });
    renderSearch(["/search?q=foo&entity=tickets"]);

    // Wait for the initial fetch.
    await waitFor(() => {
      expect(mockSearchV2).toHaveBeenCalledWith(
        expect.objectContaining({ q: "foo", entity: "tickets" }),
      );
    });

    mockSearchV2.mockClear();
    const dropdown = screen.getByLabelText("Ticket status") as HTMLSelectElement;
    fireEvent.change(dropdown, { target: { value: "in_progress" } });

    await waitFor(() => {
      expect(mockSearchV2).toHaveBeenCalledWith(
        expect.objectContaining({
          q: "foo",
          entity: "tickets",
          ticket_status: "in_progress",
        }),
      );
    });
  });

  // WP11.6 — clearing the query input clears q from search params (fetch no longer fires with q)
  it("WP11: clearing query input results in no fetch (empty q short-circuits)", async () => {
    mockSearchV2.mockResolvedValue({ problems: { items: [], total: 0 } });
    renderSearch(["/search?q=hello&entity=problems"]);

    await waitFor(() => {
      expect(mockSearchV2).toHaveBeenCalledWith(
        expect.objectContaining({ q: "hello" }),
      );
    });

    mockSearchV2.mockClear();

    const input = screen.getByRole("textbox");
    vi.useFakeTimers();
    fireEvent.change(input, { target: { value: "" } });
    act(() => { vi.advanceTimersByTime(350); });
    vi.useRealTimers();

    // No fetch fires with an empty q (the hook short-circuits).
    await waitFor(() => {
      const calledWithNonEmptyQ = mockSearchV2.mock.calls.some(
        (c) => (c[0] as { q: string }).q !== "",
      );
      expect(calledWithNonEmptyQ).toBe(false);
    });
  });

  // -------------------------------------------------------------------------
  // WP10 (v2.12) — snapshot-total banner + Refresh count button
  // -------------------------------------------------------------------------

  it("WP10: snapshot banner renders after advancing past page 1 on a single-arm tab", async () => {
    // Page 1 — snapshot, has next.
    mockSearchV2.mockResolvedValueOnce({
      tickets: {
        items: [makeTicketItem({ id: "t1", display_id: "P-1", title: "T1" })],
        total: 100,
        next_cursor: "CUR-2",
        total_authority: "snapshot",
      },
    });
    // Page 2 — still snapshot, has prev.
    mockSearchV2.mockResolvedValueOnce({
      tickets: {
        items: [makeTicketItem({ id: "t2", display_id: "P-2", title: "T2" })],
        total: 100,
        next_cursor: "CUR-3",
        total_authority: "snapshot",
      },
    });

    renderSearch(["/search?q=foo&entity=tickets"]);

    // Wait for page 1 to render.
    await screen.findByText("T1");
    // Banner not shown on page 1 (hasPrev=false).
    expect(screen.queryByText(/snapshot count/i)).not.toBeInTheDocument();

    // Advance to page 2.
    fireEvent.click(screen.getByRole("button", { name: /next page/i }));
    await screen.findByText("T2");

    // Banner now visible with the refresh button.
    expect(screen.getByText(/snapshot count/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /refresh count/i }),
    ).toBeInTheDocument();
  });

  it("WP10: clicking Refresh count fires searchV2 with refresh_total=true and banner clears on live response", async () => {
    mockSearchV2.mockResolvedValueOnce({
      tickets: {
        items: [makeTicketItem({ id: "t1", display_id: "P-1", title: "T1" })],
        total: 100,
        next_cursor: "CUR-2",
        total_authority: "snapshot",
      },
    });
    mockSearchV2.mockResolvedValueOnce({
      tickets: {
        items: [makeTicketItem({ id: "t2", display_id: "P-2", title: "T2" })],
        total: 100,
        next_cursor: "CUR-3",
        total_authority: "snapshot",
      },
    });
    // After refresh — live authority, same cursor.
    mockSearchV2.mockResolvedValueOnce({
      tickets: {
        items: [makeTicketItem({ id: "t2", display_id: "P-2", title: "T2" })],
        total: 97,
        next_cursor: "CUR-3",
        total_authority: "live",
      },
    });

    renderSearch(["/search?q=foo&entity=tickets"]);

    await screen.findByText("T1");
    fireEvent.click(screen.getByRole("button", { name: /next page/i }));
    await screen.findByText("T2");

    const refreshBtn = await screen.findByRole("button", {
      name: /refresh count/i,
    });
    fireEvent.click(refreshBtn);

    await waitFor(() => {
      const lastCall = mockSearchV2.mock.calls[mockSearchV2.mock.calls.length - 1][0];
      expect(lastCall.refresh_total).toBe(true);
      expect(lastCall.cursor).toBe("CUR-2");
    });

    // Banner disappears once authority flips to live.
    await waitFor(() =>
      expect(screen.queryByText(/snapshot count/i)).not.toBeInTheDocument(),
    );
  });

  it("WP10: snapshot banner is hidden on the All tab when every arm is live", async () => {
    // WP06 (v2.13): All-tab banner triggers when ANY arm is snapshot.
    // Conversely it stays hidden when every present arm reports live.
    mockSearchV2.mockResolvedValue({
      problems: { items: [], total: 5, total_authority: "live" },
      tickets: { items: [], total: 5, total_authority: "live" },
      components: { items: [], total: 0, total_authority: "live" },
      labels: { items: [], total: 0, total_authority: "live" },
      users: { items: [], total: 0, total_authority: "live" },
    });

    renderSearch(["/search?q=foo"]);

    await waitFor(() => expect(mockSearchV2).toHaveBeenCalled());
    expect(screen.queryByText(/snapshot count/i)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /refresh counts?/i }),
    ).not.toBeInTheDocument();
  });

  // -------------------------------------------------------------------------
  // WP06 (v2.13) — All tab snapshot banner + broadcast refresh
  // -------------------------------------------------------------------------

  it("WP06: snapshot banner renders on the All tab when any arm reports snapshot and Refresh counts broadcasts refresh_total=true", async () => {
    // Initial — mixed authorities; any-snapshot triggers the banner.
    mockSearchV2.mockResolvedValueOnce({
      problems: { items: [], total: 5, total_authority: "snapshot" },
      tickets: { items: [], total: 5, total_authority: "live" },
      components: { items: [], total: 0, total_authority: "live" },
      labels: { items: [], total: 0, total_authority: "live" },
      users: { items: [], total: 0, total_authority: "live" },
    });
    // After refresh — every arm live, banner disappears.
    mockSearchV2.mockResolvedValueOnce({
      problems: { items: [], total: 3, total_authority: "live" },
      tickets: { items: [], total: 5, total_authority: "live" },
      components: { items: [], total: 0, total_authority: "live" },
      labels: { items: [], total: 0, total_authority: "live" },
      users: { items: [], total: 0, total_authority: "live" },
    });

    renderSearch(["/search?q=foo"]);

    // Banner with plural "counts" copy is visible because at least one arm
    // (problems) reports snapshot — no hasPrev predicate on entity=all.
    expect(await screen.findByText(/snapshot counts/i)).toBeInTheDocument();
    const refreshBtn = await screen.findByRole("button", {
      name: /refresh counts/i,
    });

    fireEvent.click(refreshBtn);

    await waitFor(() => {
      const lastCall = mockSearchV2.mock.calls[mockSearchV2.mock.calls.length - 1][0];
      expect(lastCall.refresh_total).toBe(true);
      expect(lastCall.entity).toBe("all");
    });

    // Banner clears once every arm comes back live.
    await waitFor(() =>
      expect(screen.queryByText(/snapshot counts/i)).not.toBeInTheDocument(),
    );
  });
});
