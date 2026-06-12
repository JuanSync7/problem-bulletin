/**
 * V3a — nav.me-space.test.tsx
 *
 * Asserts that the Sidebar exposes a "My Space" nav entry whose link
 * targets ``/me``. Positioning (above "Activity") is asserted via index
 * ordering on the rendered link list.
 */
import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { ThemeProvider } from "../theme";
import { Sidebar } from "../layouts/Sidebar";

// jsdom doesn't ship matchMedia; Sidebar's children consume it via ThemeProvider.
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
  listNotifications: vi.fn(async () => ({
    items: [],
    next_cursor: null,
    total: 0,
  })),
  markRead: vi.fn(async () => undefined),
  markAllRead: vi.fn(async () => 0),
}));

function renderSidebar() {
  return render(
    <ThemeProvider>
      <MemoryRouter
        initialEntries={["/"]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <Sidebar isOpen={true} onClose={vi.fn()} />
      </MemoryRouter>
    </ThemeProvider>,
  );
}

describe("V3a: Sidebar My Space entry", () => {
  it("renders a My Space link pointing to /me", () => {
    renderSidebar();
    const link = screen.getByRole("link", { name: /My Space/i });
    expect(link).toBeInTheDocument();
    expect(link.getAttribute("href")).toBe("/me");
  });

  it("places My Space immediately above Activity in nav order", () => {
    renderSidebar();
    const links = screen.getAllByRole("link");
    const labels = links.map((el) => el.textContent?.trim());
    const meIdx = labels.findIndex((t) => t === "My Space");
    const activityIdx = labels.findIndex((t) => t === "Activity");
    expect(meIdx).toBeGreaterThanOrEqual(0);
    expect(activityIdx).toBeGreaterThanOrEqual(0);
    expect(meIdx + 1).toBe(activityIdx);
  });
});
