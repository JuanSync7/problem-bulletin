/**
 * A1b: synthetic-bad coverage for isTypeaheadResponse
 * (rule yy: PASS → FAIL → PASS per required + typed field).
 *
 * Wire shape: direct_match may be absent OR null (backend model_serializer
 * omits the key when null). Both must pass the guard.
 */
import { describe, it, expect } from "vitest";
import { isTypeaheadResponse } from "../search";

const validItem = {
  id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
  display_id: "AION-1",
  title: "Fix login bug",
  subtitle: "Open · Project A",
  kind: "ticket",
  href: "/tickets/AION-1",
  rank: 1.0,
  project_id: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
  status: "open",
};

const validResponseWithMatch = {
  direct_match: validItem,
};

const validResponseNoMatchNull = {
  direct_match: null,
};

const validResponseNoMatchAbsent = {};

describe("isTypeaheadResponse", () => {
  it("accepts a response with a valid direct_match SearchItem", () => {
    expect(isTypeaheadResponse(validResponseWithMatch)).toBe(true);
  });

  it("accepts a response where direct_match is null (backend may send null)", () => {
    expect(isTypeaheadResponse(validResponseNoMatchNull)).toBe(true);
  });

  it("accepts a response where direct_match key is absent (backend omits when null)", () => {
    expect(isTypeaheadResponse(validResponseNoMatchAbsent)).toBe(true);
  });

  it("rejects null / undefined / non-object", () => {
    expect(isTypeaheadResponse(null)).toBe(false);
    expect(isTypeaheadResponse(undefined)).toBe(false);
    expect(isTypeaheadResponse(42)).toBe(false);
    expect(isTypeaheadResponse("string")).toBe(false);
  });

  it("rejects direct_match that is not null and not a valid SearchItem (missing id)", () => {
    expect(
      isTypeaheadResponse({ direct_match: { title: "Missing id" } }),
    ).toBe(false);
  });

  it("rejects direct_match where id is not a string", () => {
    expect(
      isTypeaheadResponse({ direct_match: { ...validItem, id: 42 } }),
    ).toBe(false);
  });

  it("rejects direct_match where title is not a string", () => {
    expect(
      isTypeaheadResponse({ direct_match: { ...validItem, title: null } }),
    ).toBe(false);
  });

  it("rejects direct_match where kind is not a string", () => {
    expect(
      isTypeaheadResponse({ direct_match: { ...validItem, kind: 99 } }),
    ).toBe(false);
  });

  it("rejects direct_match where href is not a string", () => {
    expect(
      isTypeaheadResponse({ direct_match: { ...validItem, href: false } }),
    ).toBe(false);
  });

  it("accepts direct_match with display_id as null (optional nullable field)", () => {
    expect(
      isTypeaheadResponse({ direct_match: { ...validItem, display_id: null } }),
    ).toBe(true);
  });

  it("accepts direct_match with extra unknown fields (open interface)", () => {
    expect(
      isTypeaheadResponse({
        direct_match: { ...validItem, extra_field: "allowed" },
      }),
    ).toBe(true);
  });

  it("accepts a full response with arm data alongside direct_match", () => {
    expect(
      isTypeaheadResponse({
        direct_match: validItem,
        tickets: { items: [], total: 0 },
        problems: null,
      }),
    ).toBe(true);
  });
});
