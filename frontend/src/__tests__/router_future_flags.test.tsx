import { describe, it, expect, vi, afterEach } from "vitest";
import { render } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";

/**
 * Regression test for v2.16-WP03: confirm React Router v7 future-flag warnings
 * are not emitted when the `future` prop is supplied to MemoryRouter (and by
 * extension BrowserRouter in App.tsx). RR emits these via console.warn, but we
 * also spy console.error to be safe against version drift.
 */
describe("React Router v7 future-flag opt-in", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("does not emit v7 future-flag warnings with future prop set", () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    render(
      <MemoryRouter
        initialEntries={["/"]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <Routes>
          <Route path="/" element={<div>home</div>} />
          <Route path="*" element={<div>nf</div>} />
        </Routes>
      </MemoryRouter>,
    );

    const futurePattern = /v7_|future flag|React Router Future/i;
    const warnCalls = warnSpy.mock.calls.flat().filter((arg) =>
      typeof arg === "string" && futurePattern.test(arg),
    );
    const errorCalls = errorSpy.mock.calls.flat().filter((arg) =>
      typeof arg === "string" && futurePattern.test(arg),
    );
    expect(warnCalls).toEqual([]);
    expect(errorCalls).toEqual([]);
  });

  it("emits v7 future-flag warnings WITHOUT future prop (sanity check)", () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    render(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={<div>home</div>} />
          <Route path="*" element={<div>nf</div>} />
        </Routes>
      </MemoryRouter>,
    );

    const futurePattern = /v7_|future flag|React Router Future/i;
    const matched = warnSpy.mock.calls.flat().some((arg) =>
      typeof arg === "string" && futurePattern.test(arg),
    );
    // This proves the warnings DO appear without the flag — guarantees our
    // positive test above is meaningfully different.
    expect(matched).toBe(true);
  });
});
