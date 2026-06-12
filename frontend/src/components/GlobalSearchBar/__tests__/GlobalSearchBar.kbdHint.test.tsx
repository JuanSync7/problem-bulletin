/**
 * v2.29-S6 (audit P1#7) — keyboard-shortcut discoverability.
 *
 * Tests:
 *  (a) the ⌘K / Ctrl-K kbd hint is visible at rest (no focus required)
 *  (b) the hint is hidden while the user is typing (non-empty query)
 *  (c) the input carries the title="Search (Ctrl+K or ⌘K)" tooltip
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

// ---------------------------------------------------------------------------
// Mocks (same harness as GlobalSearchBar.polish.test.tsx)
// ---------------------------------------------------------------------------

vi.mock("../../../api/search", () => ({
  searchTypeahead: vi.fn().mockResolvedValue({ combined: [] }),
  isTypeaheadResponse: vi.fn(() => true),
}));

vi.mock("../../../hooks/useAuth", () => ({
  useAuth: () => ({
    isAuthenticated: true,
    user: { id: "user-kbd-1", email: "kbd@example.com", displayName: "Kbd", role: "user" },
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

function renderBar() {
  return render(
    <MemoryRouter>
      <GlobalSearchBar />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("GlobalSearchBar — kbd hint discoverability (audit P1#7)", () => {
  it("shows the kbd hint at rest, without focusing the input", () => {
    const { container } = renderBar();

    const hint = container.querySelector(".gsb__kbd-hint");
    expect(hint).not.toBeNull();
    // jsdom navigator.platform is non-Mac → "Ctrl" + "K" keys.
    const keys = Array.from(hint!.querySelectorAll("kbd")).map(
      (el) => el.textContent,
    );
    expect(keys).toHaveLength(2);
    expect(keys[1]).toBe("K");
    expect(["Ctrl", "⌘"]).toContain(keys[0]);
  });

  it("hides the kbd hint while typing and restores it when cleared", async () => {
    const user = userEvent.setup();
    const { container } = renderBar();

    const input = screen.getByRole("searchbox");
    await user.type(input, "abc");
    expect(container.querySelector(".gsb__kbd-hint")).toBeNull();

    await user.clear(input);
    expect(container.querySelector(".gsb__kbd-hint")).not.toBeNull();
  });

  it('input carries title="Search (Ctrl+K or ⌘K)"', () => {
    renderBar();
    expect(screen.getByRole("searchbox")).toHaveAttribute(
      "title",
      "Search (Ctrl+K or ⌘K)",
    );
  });
});
