/**
 * v2.27-WP02: synthetic-bad coverage for isUpdateHandleResponse
 * (rule yy: PASS → FAIL → PASS per required + typed field).
 */
import { describe, it, expect } from "vitest";
import { isUpdateHandleResponse } from "../users";

const valid = {
  id: "u1",
  email: "u@example.com",
  display_name: "Alice",
  handle: "alice",
  role: "member",
  is_active: true,
};

describe("isUpdateHandleResponse", () => {
  it("accepts a valid payload", () => {
    expect(isUpdateHandleResponse(valid)).toBe(true);
  });

  it("accepts handle === null (backend allows Optional[str])", () => {
    expect(isUpdateHandleResponse({ ...valid, handle: null })).toBe(true);
  });

  it("rejects null / undefined / non-object", () => {
    expect(isUpdateHandleResponse(null)).toBe(false);
    expect(isUpdateHandleResponse(undefined)).toBe(false);
    expect(isUpdateHandleResponse(7)).toBe(false);
  });

  it.each(["id", "email", "display_name", "handle", "role", "is_active"])(
    "rejects missing required field: %s",
    (field) => {
      const bad = { ...valid } as Record<string, unknown>;
      delete bad[field];
      expect(isUpdateHandleResponse(bad)).toBe(false);
    },
  );

  it("rejects wrong type on handle (number)", () => {
    expect(isUpdateHandleResponse({ ...valid, handle: 42 })).toBe(false);
  });

  it("rejects wrong type on is_active (string)", () => {
    expect(isUpdateHandleResponse({ ...valid, is_active: "yes" })).toBe(false);
  });
});
