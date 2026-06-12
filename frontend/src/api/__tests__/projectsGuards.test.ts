/**
 * B1: synthetic-bad coverage for isProjectHierarchyResponse + isHierarchyRow
 * (rule fff: PASS → FAIL → PASS per required + typed field).
 *
 * Wire shape:
 *   ProjectHierarchyResponse: { items: HierarchyRow[] }
 *   HierarchyRow: { ticket: TicketDTO, depth: number, parent_id: string | null, ordinal: number }
 */
import { describe, it, expect } from "vitest";
import { isProjectHierarchyResponse, isHierarchyRow } from "../projects";

const validTicket = {
  id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
  seq_number: 1,
  display_id: "TST-1",
  title: "Root Epic",
  type: "epic",
  status: "todo",
  priority: "medium",
  reporter_id: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
  reporter_type: "user",
  version: 1,
  created_at: "2026-01-01T00:00:00Z",
  labels: [],
  fix_versions: [],
  custom_fields: {},
};

const validRow = {
  ticket: validTicket,
  depth: 0,
  parent_id: null,
  ordinal: 1,
};

const validResponse = {
  items: [validRow],
};

const emptyResponse = {
  items: [],
};

// ---------------------------------------------------------------------------
// isHierarchyRow tests
// ---------------------------------------------------------------------------

describe("isHierarchyRow", () => {
  it("accepts a valid row with parent_id null", () => {
    expect(isHierarchyRow(validRow)).toBe(true);
  });

  it("accepts a valid row with parent_id as string", () => {
    expect(isHierarchyRow({ ...validRow, parent_id: "cccccccc-cccc-cccc-cccc-cccccccccccc" })).toBe(true);
  });

  it("rejects null", () => {
    expect(isHierarchyRow(null)).toBe(false);
  });

  it("rejects non-object", () => {
    expect(isHierarchyRow(42)).toBe(false);
    expect(isHierarchyRow("string")).toBe(false);
  });

  it("rejects row missing depth field", () => {
    const { depth: _d, ...noDepth } = validRow;
    expect(isHierarchyRow(noDepth)).toBe(false);
  });

  it("rejects row where depth is not a number", () => {
    expect(isHierarchyRow({ ...validRow, depth: "zero" })).toBe(false);
  });

  it("rejects row missing ordinal field", () => {
    const { ordinal: _o, ...noOrdinal } = validRow;
    expect(isHierarchyRow(noOrdinal)).toBe(false);
  });

  it("rejects row where ordinal is not a number", () => {
    expect(isHierarchyRow({ ...validRow, ordinal: "first" })).toBe(false);
  });

  it("rejects row where parent_id is not null or string", () => {
    expect(isHierarchyRow({ ...validRow, parent_id: 42 })).toBe(false);
  });

  it("rejects row missing ticket field", () => {
    const { ticket: _t, ...noTicket } = validRow;
    expect(isHierarchyRow(noTicket)).toBe(false);
  });

  it("rejects row where ticket is not an object", () => {
    expect(isHierarchyRow({ ...validRow, ticket: "not-an-object" })).toBe(false);
  });

  it("rejects row where ticket is missing id", () => {
    const { id: _id, ...noId } = validTicket;
    expect(isHierarchyRow({ ...validRow, ticket: noId })).toBe(false);
  });

  it("rejects row where ticket.id is not a string", () => {
    expect(isHierarchyRow({ ...validRow, ticket: { ...validTicket, id: 99 } })).toBe(false);
  });

  it("accepts row with extra unknown fields (open interface)", () => {
    expect(isHierarchyRow({ ...validRow, extra: "allowed" })).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// isProjectHierarchyResponse tests
// ---------------------------------------------------------------------------

describe("isProjectHierarchyResponse", () => {
  it("accepts a valid response with items", () => {
    expect(isProjectHierarchyResponse(validResponse)).toBe(true);
  });

  it("accepts an empty items array", () => {
    expect(isProjectHierarchyResponse(emptyResponse)).toBe(true);
  });

  it("rejects null", () => {
    expect(isProjectHierarchyResponse(null)).toBe(false);
  });

  it("rejects undefined", () => {
    expect(isProjectHierarchyResponse(undefined)).toBe(false);
  });

  it("rejects non-object", () => {
    expect(isProjectHierarchyResponse(42)).toBe(false);
    expect(isProjectHierarchyResponse("string")).toBe(false);
  });

  it("rejects response missing items field", () => {
    expect(isProjectHierarchyResponse({})).toBe(false);
  });

  it("rejects response where items is not an array", () => {
    expect(isProjectHierarchyResponse({ items: "not-an-array" })).toBe(false);
    expect(isProjectHierarchyResponse({ items: null })).toBe(false);
    expect(isProjectHierarchyResponse({ items: {} })).toBe(false);
  });

  it("rejects response where items contains a malformed row (missing depth)", () => {
    const { depth: _d, ...noDepth } = validRow;
    expect(isProjectHierarchyResponse({ items: [noDepth] })).toBe(false);
  });

  it("rejects response where items contains a row with wrong type ticket (no id)", () => {
    const { id: _id, ...noId } = validTicket;
    expect(isProjectHierarchyResponse({ items: [{ ...validRow, ticket: noId }] })).toBe(false);
  });

  it("accepts response with multiple valid rows", () => {
    const child = {
      ...validRow,
      depth: 1,
      parent_id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
      ordinal: 2,
    };
    expect(isProjectHierarchyResponse({ items: [validRow, child] })).toBe(true);
  });
});
