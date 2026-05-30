/**
 * v2.27-WP02: synthetic-bad coverage for isActivityEntry / isActivityPage
 * (rule yy: PASS → FAIL → PASS per required + typed field).
 */
import { describe, it, expect } from "vitest";
import { isActivityEntry, isActivityPage } from "../audit";

const valid = {
  id: "a1",
  occurred_at: "2026-01-01T00:00:00Z",
  actor_id: "u1",
  actor_type: "user",
  action: "create",
  entity_type: "ticket",
  entity_id: "t1",
};

describe("isActivityEntry", () => {
  it("accepts a valid entry", () => {
    expect(isActivityEntry(valid)).toBe(true);
  });

  it("rejects null / undefined / non-object", () => {
    expect(isActivityEntry(null)).toBe(false);
    expect(isActivityEntry(undefined)).toBe(false);
    expect(isActivityEntry("nope")).toBe(false);
  });

  it.each([
    "id",
    "occurred_at",
    "actor_id",
    "actor_type",
    "action",
    "entity_type",
    "entity_id",
  ])("rejects missing required field: %s", (field) => {
    const bad = { ...valid } as Record<string, unknown>;
    delete bad[field];
    expect(isActivityEntry(bad)).toBe(false);
  });

  it("rejects wrong type on a string field", () => {
    expect(isActivityEntry({ ...valid, action: 42 })).toBe(false);
  });
});

describe("isActivityPage", () => {
  it("accepts canonical {items:[...]}", () => {
    expect(isActivityPage({ items: [valid] })).toBe(true);
  });

  it("accepts legacy bare array", () => {
    expect(isActivityPage([valid])).toBe(true);
  });

  it("rejects items containing a malformed entry", () => {
    expect(isActivityPage({ items: [valid, { id: 1 }] })).toBe(false);
  });

  it("rejects null / non-object / missing items", () => {
    expect(isActivityPage(null)).toBe(false);
    expect(isActivityPage({})).toBe(false);
    expect(isActivityPage({ items: "no" })).toBe(false);
  });
});
