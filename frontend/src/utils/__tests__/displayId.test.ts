import { describe, it, expect } from "vitest";
import { parseDisplayId, isDisplayId, formatDisplayId } from "../displayId";

describe("parseDisplayId", () => {
  it("parses DEF-42 into key and n", () => {
    expect(parseDisplayId("DEF-42")).toEqual({ key: "DEF", n: 42 });
  });

  it("accepts longer keys with digits", () => {
    expect(parseDisplayId("AION99-1")).toEqual({ key: "AION99", n: 1 });
  });

  it("returns null on invalid input", () => {
    expect(parseDisplayId("def-1")).toBeNull(); // lowercase
    expect(parseDisplayId("D-1")).toBeNull(); // key too short
    expect(parseDisplayId("DEF-0")).toBeNull(); // zero
    expect(parseDisplayId("DEF")).toBeNull(); // no number
    expect(parseDisplayId("")).toBeNull();
    expect(parseDisplayId("TKT-abc")).toBeNull();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect(parseDisplayId(undefined as any)).toBeNull();
  });

  it("trims whitespace", () => {
    expect(parseDisplayId("  DEF-7  ")).toEqual({ key: "DEF", n: 7 });
  });
});

describe("isDisplayId / formatDisplayId", () => {
  it("isDisplayId mirrors parseDisplayId", () => {
    expect(isDisplayId("DEF-1")).toBe(true);
    expect(isDisplayId("bogus")).toBe(false);
  });
  it("formats key + n round-trip", () => {
    const s = formatDisplayId("DEF", 12);
    expect(s).toBe("DEF-12");
    expect(parseDisplayId(s)).toEqual({ key: "DEF", n: 12 });
  });
});
