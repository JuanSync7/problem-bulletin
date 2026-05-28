/**
 * v2.4-WP29 — Settings page: handle edit UI tests.
 *
 * Covers:
 *  1. Renders current handle from useAuth.
 *  2. Valid change calls updateMyHandle and shows success message.
 *  3. 409 response renders "already taken" message.
 *  4. 429 response renders cooldown message with next_allowed_at.
 *  5. Invalid client-side input → Save disabled / inline validation error.
 */
import "@testing-library/jest-dom";
import {
  render,
  screen,
  waitFor,
  fireEvent,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockFetchMe = vi.fn(async () => undefined);

vi.mock("../../hooks/useAuth", () => ({
  useAuth: () => ({
    user: { id: "u-1", email: "test@example.com", displayName: "Test", handle: "myhandle", role: "user" },
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

const mockUpdateMyHandle = vi.fn();
vi.mock("../../api/users", () => ({
  updateMyHandle: (...args: unknown[]) => mockUpdateMyHandle(...args),
}));

// ---------------------------------------------------------------------------
// Import subject under test (after mocks)
// ---------------------------------------------------------------------------

import Settings from "../Settings";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// Also mock auditLog so Admin tab fetch doesn't leak into profile tests
vi.mock("../../api/auditLog", () => ({
  listAuditLog: vi.fn().mockResolvedValue({ items: [], next_cursor: null, total: 0 }),
}));

// Mock PersonPicker to avoid fetch in tests
vi.mock("../../components/PersonPicker/index", () => ({
  PersonPicker: ({ placeholder }: { placeholder?: string }) => (
    <input aria-label={placeholder ?? "person picker"} />
  ),
}));

function renderSettings(initialEntries: string[] = ["/"]) {
  return render(
    <MemoryRouter initialEntries={initialEntries} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <Settings />
    </MemoryRouter>
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("Settings page — handle edit", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the current handle in the input", () => {
    renderSettings(["/?section=profile"]);
    const input = screen.getByRole("textbox", { name: /handle/i });
    expect(input).toHaveValue("myhandle");
  });

  it("valid change calls updateMyHandle and shows success message", async () => {
    mockUpdateMyHandle.mockResolvedValueOnce({
      id: "u-1",
      email: "test@example.com",
      display_name: "Test",
      handle: "newhandle",
      role: "user",
      is_active: true,
    });

    renderSettings();
    const input = screen.getByRole("textbox", { name: /handle/i });

    // Use fireEvent.change for reliable value replacement (userEvent.type appends).
    fireEvent.change(input, { target: { value: "newhandle" } });

    const saveBtn = screen.getByRole("button", { name: /^save$/i });
    expect(saveBtn).not.toBeDisabled();
    await userEvent.click(saveBtn);

    await waitFor(() => {
      expect(mockUpdateMyHandle).toHaveBeenCalledWith("newhandle");
    });

    await waitFor(() => {
      expect(screen.getByText(/handle updated/i)).toBeInTheDocument();
    });

    expect(mockFetchMe).toHaveBeenCalled();
  });

  it("409 response renders 'already taken' message", async () => {
    mockUpdateMyHandle.mockRejectedValueOnce({
      status: 409,
      detail: "handle already taken: 'newhandle'",
    });

    renderSettings();
    const input = screen.getByRole("textbox", { name: /handle/i });

    fireEvent.change(input, { target: { value: "newhandle" } });

    const saveBtn = screen.getByRole("button", { name: /^save$/i });
    await userEvent.click(saveBtn);

    await waitFor(() => {
      expect(
        screen.getByText(/that handle is already taken/i)
      ).toBeInTheDocument();
    });
  });

  it("429 response renders cooldown message with next_allowed_at", async () => {
    const nextAllowed = new Date(Date.now() + 23 * 3600 * 1000).toISOString();
    mockUpdateMyHandle.mockRejectedValueOnce({
      status: 429,
      detail: `handle can next be changed at ${nextAllowed}`,
      next_allowed_at: nextAllowed,
    });

    renderSettings();
    const input = screen.getByRole("textbox", { name: /handle/i });

    fireEvent.change(input, { target: { value: "newhandle" } });

    const saveBtn = screen.getByRole("button", { name: /^save$/i });
    await userEvent.click(saveBtn);

    await waitFor(() => {
      expect(
        screen.getByText(/you can change your handle again at/i)
      ).toBeInTheDocument();
    });
  });

  it("invalid client-side input disables Save and shows inline validation", async () => {
    renderSettings();
    const input = screen.getByRole("textbox", { name: /handle/i });

    // Set too-short value (2 chars) directly — triggers client validation.
    fireEvent.change(input, { target: { value: "ab" } });

    const saveBtn = screen.getByRole("button", { name: /^save$/i });
    expect(saveBtn).toBeDisabled();

    expect(
      screen.getByText(/3.{1,5}32 characters/i)
    ).toBeInTheDocument();
  });

  it("422 response with 'That handle is not allowed.' renders that message", async () => {
    // WP35: profanity filter returns 422 with a generic detail string.
    mockUpdateMyHandle.mockRejectedValueOnce({
      status: 422,
      detail: "That handle is not allowed.",
    });

    renderSettings();
    const input = screen.getByRole("textbox", { name: /handle/i });

    fireEvent.change(input, { target: { value: "wanker" } });

    const saveBtn = screen.getByRole("button", { name: /^save$/i });
    await userEvent.click(saveBtn);

    await waitFor(() => {
      expect(
        screen.getByText("That handle is not allowed.")
      ).toBeInTheDocument();
    });
  });
});
