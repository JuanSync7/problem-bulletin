/**
 * v2.5-WP33 — Settings Admin tab tests.
 *
 * Covers:
 *  1. Admin user sees Admin tab; non-admin does not.
 *  2. Admin tab renders audit rows from mocked API.
 *  3. Load-more button calls listAuditLog with next cursor.
 *  4. Event filter input changes the API call.
 */
import "@testing-library/jest-dom";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockFetchMe = vi.fn(async () => undefined);

// We define a mutable user fixture so individual tests can override role.
let mockUserRole = "admin";

vi.mock("../../hooks/useAuth", () => ({
  useAuth: () => ({
    user: {
      id: "u-admin",
      email: "admin@test.example",
      displayName: "Admin User",
      handle: "adminhandle",
      role: mockUserRole,
    },
    isAuthenticated: true,
    isLoading: false,
    error: null,
    fetchMe: mockFetchMe,
  }),
}));

vi.mock("../../hooks/useDarkMode", () => ({
  useDarkMode: () => ({ isDark: false, toggle: vi.fn() }),
}));

const mockShow = vi.fn();
vi.mock("../../contexts/ToastContext", () => ({
  useToast: () => ({ show: mockShow }),
}));

vi.mock("../../api/users", () => ({
  updateMyHandle: vi.fn().mockResolvedValue({}),
}));

const mockListAuditLog = vi.fn();
vi.mock("../../api/auditLog", () => ({
  listAuditLog: (...args: unknown[]) => mockListAuditLog(...args),
}));

vi.mock("../../components/PersonPicker/index", () => ({
  PersonPicker: ({
    placeholder,
    onChange,
  }: {
    placeholder?: string;
    onChange: (v: null) => void;
  }) => (
    <input
      aria-label={placeholder ?? "person picker"}
      onClick={() => onChange(null)}
    />
  ),
}));

// ---------------------------------------------------------------------------
// Import subject under test (after mocks)
// ---------------------------------------------------------------------------

import Settings from "../Settings";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeEntry(overrides: Record<string, unknown> = {}) {
  return {
    id: "entry-1",
    event: "project.created",
    actor_user_id: "u-actor",
    actor: {
      kind: "user",
      id: "u-actor",
      display_name: "Actor",
      handle: "actor_handle",
    },
    target_type: "project",
    target_id: "t-1",
    metadata: { slug: "PROJ" },
    created_at: new Date(Date.now() - 60_000).toISOString(),
    ...overrides,
  };
}

function renderSettings(initialPath = "/") {
  return render(
    <MemoryRouter initialEntries={[initialPath]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <Settings />
    </MemoryRouter>
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("Settings Admin tab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUserRole = "admin";
    mockListAuditLog.mockResolvedValue({
      items: [],
      next_cursor: null,
      total: 0,
    });
  });

  it("admin user sees Admin tab", () => {
    mockUserRole = "admin";
    renderSettings("/");
    expect(screen.getByRole("tab", { name: /admin/i })).toBeInTheDocument();
  });

  it("non-admin user does not see Admin tab", () => {
    mockUserRole = "user";
    renderSettings("/");
    expect(screen.queryByRole("tab", { name: /admin/i })).not.toBeInTheDocument();
  });

  it("non-admin with ?section=admin is silently redirected to profile", () => {
    mockUserRole = "user";
    renderSettings("/?section=admin");
    // Profile section should be shown (handle input is visible)
    expect(screen.getByRole("textbox", { name: /handle/i })).toBeInTheDocument();
    // Admin tab is hidden
    expect(screen.queryByRole("tab", { name: /admin/i })).not.toBeInTheDocument();
  });

  it("admin tab renders audit rows from mocked API", async () => {
    mockUserRole = "admin";
    mockListAuditLog.mockResolvedValue({
      items: [makeEntry()],
      next_cursor: null,
      total: 1,
    });

    renderSettings("/?section=admin");

    await waitFor(() => {
      expect(screen.getByText("project.created")).toBeInTheDocument();
    });
    expect(screen.getByText("@actor_handle")).toBeInTheDocument();
    expect(screen.getByText(/project#t-1/i)).toBeInTheDocument();
  });

  it("shows total entry count on first page", async () => {
    mockUserRole = "admin";
    mockListAuditLog.mockResolvedValue({
      items: [makeEntry()],
      next_cursor: null,
      total: 42,
    });

    renderSettings("/?section=admin");

    await waitFor(() => {
      expect(screen.getByText(/42 total entries/i)).toBeInTheDocument();
    });
  });

  it("load-more button calls listAuditLog with next cursor", async () => {
    mockUserRole = "admin";
    mockListAuditLog
      .mockResolvedValueOnce({
        items: [makeEntry({ id: "e-1" })],
        next_cursor: "cursor-abc",
        total: 2,
      })
      .mockResolvedValueOnce({
        items: [makeEntry({ id: "e-2", event: "user.handle_changed" })],
        next_cursor: null,
        total: null,
      });

    renderSettings("/?section=admin");

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /load more/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /load more/i }));

    await waitFor(() => {
      expect(mockListAuditLog).toHaveBeenCalledTimes(2);
      expect(mockListAuditLog).toHaveBeenNthCalledWith(
        2,
        expect.objectContaining({ cursor: "cursor-abc" })
      );
    });

    // Second page's event should also appear
    await waitFor(() => {
      expect(screen.getByText("user.handle_changed")).toBeInTheDocument();
    });
  });

  // v2.6-WP44: quick-filter chip for user.handle_changed_by_admin

  it("renders the Handle overrides quick-filter button (WP44)", async () => {
    mockUserRole = "admin";
    renderSettings("/?section=admin");

    await waitFor(() => {
      expect(mockListAuditLog).toHaveBeenCalledTimes(1);
    });

    const btn = screen.getByRole("button", { name: /handle overrides/i });
    expect(btn).toBeInTheDocument();
    expect(btn).toHaveAttribute("aria-pressed", "false");
  });

  it("toggles the WP44 quick-filter on/off and changes the API call", async () => {
    mockUserRole = "admin";
    renderSettings("/?section=admin");

    await waitFor(() => {
      expect(mockListAuditLog).toHaveBeenCalledTimes(1);
    });

    const btn = screen.getByRole("button", { name: /handle overrides/i });

    // Click → sets event filter to user.handle_changed_by_admin
    fireEvent.click(btn);
    await waitFor(() => {
      expect(mockListAuditLog).toHaveBeenLastCalledWith(
        expect.objectContaining({ event: "user.handle_changed_by_admin" })
      );
    });
    expect(btn).toHaveAttribute("aria-pressed", "true");

    // Click again → clears the filter (event = null/empty).
    fireEvent.click(btn);
    await waitFor(() => {
      const lastCall = mockListAuditLog.mock.calls.at(-1)?.[0] ?? {};
      // The component passes `eventFilter || null` so an empty string → null.
      expect(lastCall.event === null || lastCall.event === "").toBe(true);
    });
    expect(btn).toHaveAttribute("aria-pressed", "false");
  });

  it("event filter input changes the API call", async () => {
    mockUserRole = "admin";
    mockListAuditLog.mockResolvedValue({
      items: [],
      next_cursor: null,
      total: 0,
    });

    renderSettings("/?section=admin");

    // Wait for initial load
    await waitFor(() => {
      expect(mockListAuditLog).toHaveBeenCalledTimes(1);
    });

    const filterInput = screen.getByPlaceholderText(/filter by event/i);
    fireEvent.change(filterInput, { target: { value: "project.created" } });

    await waitFor(() => {
      expect(mockListAuditLog).toHaveBeenCalledWith(
        expect.objectContaining({ event: "project.created" })
      );
    });
  });
});
