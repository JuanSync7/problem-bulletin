/**
 * v2.16-WP04 (Z3) — regression: Submit surfaces fetch failures for
 * supporting hydrations (categories / domains) via toast instead of
 * silently degrading to an empty dropdown.
 *
 * Pre-WP04 the categories and domains fetches in Submit.tsx had bare
 * `catch {}` blocks. v2.16-WP04 promotes both to `catch (err) { ... }`
 * and routes `err.message` to `toast.show(..., "error")`. This test
 * pins that contract: a thrown fetch (network failure shape) surfaces
 * a toast call, not silence.
 *
 * Note: a 4xx with structured envelope does NOT throw — `fetch` only
 * rejects on network / DNS / abort failures, so this test simulates
 * that path (which was the actual swallow class).
 */
import "@testing-library/jest-dom";
import { render, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockShow = vi.fn();
vi.mock("../../contexts/ToastContext", () => ({
  useToast: () => ({ show: mockShow }),
}));

vi.mock("../../hooks/useAuth", () => ({
  useAuth: () => ({
    user: { id: "u-1", email: "t@example.com", displayName: "T", role: "user" },
    isAuthenticated: true,
    isLoading: false,
    error: null,
  }),
}));

vi.mock("../../hooks/useAnonymousMode", () => ({
  useAnonymousMode: () => ({ isAnonymous: false }),
}));

// Avoid loading RichEditor / TagAutocomplete / AttachmentDropZone heavy paths.
vi.mock("../../components/RichEditor", () => ({
  default: () => <div data-testid="rich-editor-stub" />,
}));
vi.mock("../../components/TagAutocomplete", () => ({
  default: () => <div data-testid="tag-autocomplete-stub" />,
}));
vi.mock("../../components/AttachmentDropZone", () => ({
  default: () => <div data-testid="attachment-dropzone-stub" />,
}));

import Submit from "../Submit";

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Submit — v2.16-WP04 categories/domains error surface", () => {
  it("surfaces a toast when /api/admin/categories fetch throws (network failure)", async () => {
    global.fetch = vi.fn(async (input: any) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.includes("/api/admin/categories")) {
        throw new Error("network down");
      }
      if (url.includes("/api/domains")) {
        return {
          ok: true,
          status: 200,
          json: async () => [],
        } as unknown as Response;
      }
      return {
        ok: true,
        status: 200,
        json: async () => [],
      } as unknown as Response;
    }) as unknown as typeof fetch;

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Submit />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(mockShow).toHaveBeenCalledWith(
        expect.stringContaining("network down"),
        "error",
      );
    });
  });

  it("surfaces a toast when /api/domains fetch throws (network failure)", async () => {
    global.fetch = vi.fn(async (input: any) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.includes("/api/domains")) {
        throw new Error("dns failure");
      }
      if (url.includes("/api/admin/categories")) {
        return {
          ok: true,
          status: 200,
          json: async () => [],
        } as unknown as Response;
      }
      return {
        ok: true,
        status: 200,
        json: async () => [],
      } as unknown as Response;
    }) as unknown as typeof fetch;

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Submit />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(mockShow).toHaveBeenCalledWith(
        expect.stringContaining("dns failure"),
        "error",
      );
    });
  });
});
