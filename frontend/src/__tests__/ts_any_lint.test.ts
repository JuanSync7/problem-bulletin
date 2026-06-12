/**
 * v2.17-WP02 — TS `any` / `@ts-*` directive structural lint for frontend/src.
 *
 * Background
 * ----------
 * The v2.16 retrospective called out untyped escape hatches (explicit `any`,
 * `@ts-ignore`, `@ts-expect-error`, `@ts-nocheck`) as the silent gradient
 * by which a typed codebase backslides into an untyped one. They are
 * structurally invisible to `tsc --noEmit` (which honours them) and to
 * runtime tests (which never see them).
 *
 * This file is the PIN: every existing offender lives in
 * `_OFFENDER_ALLOWLIST` with a `BY-DESIGN: <reason>` or
 * `LEGACY: <reason + migration target>` justification. New offenders fail
 * loud at file:line. The SWEEP (migrating LEGACY entries off the list) is
 * a separate, future WP.
 *
 * Scope
 * -----
 * - Scans `.ts` and `.tsx` files under `frontend/src/`.
 * - Excludes test files (test.ts/test.tsx + __tests__ subdirs) — tests
 *   legitimately use `any` for mocks and `@ts-expect-error` for
 *   negative-assertion fixtures.
 * - Excludes `*.d.ts` declaration files (hand-written interop shims).
 * - Detects two offender kinds:
 *   - `any`     — any `AnyKeyword` AST node. Covers `: any`, `as any`,
 *                 `Array<any>`, `Record<string, any>`, `Foo<any>`,
 *                 `(x: any) => ...`, `(): any`, type aliases, etc.
 *                 AST matching avoids false positives on the word "any"
 *                 inside string literals, identifiers (`kind: "any"`),
 *                 or comments.
 *   - `ts-directive` — `// @ts-ignore`, `// @ts-expect-error`, or
 *                 `// @ts-nocheck` (matched textually per line; the
 *                 compiler does not expose these as nodes).
 *
 * Mirrors the v2.15-WP02 catch-block lint (this file's sibling at
 * `pages/__tests__/catch_block_lint.test.ts`): explicit allow-list,
 * file:line precision, stale-entry detection, synthetic-bad self-tests.
 *
 * Rule for adding NEW entries: don't. If a PR introduces a new offender,
 * the lint will fail at file:line — fix the type (use `unknown`, a proper
 * shape, or `as Foo` with a real `Foo`) instead of extending this list.
 * BY-DESIGN entries require a concrete reason answering WHY, not WHERE.
 */
import * as fs from "node:fs";
import * as path from "node:path";

import * as ts from "typescript";
import { describe, expect, it } from "vitest";

// Repo root: frontend/src/__tests__/ → ../../..
const REPO_ROOT = path.resolve(__dirname, "..", "..", "..");
const SRC_DIR = path.join(REPO_ROOT, "frontend", "src");

// -----------------------------------------------------------------------------
// Offender allow-list — file path (relative to repo root) + line number per
// offender. Categories:
//   BY-DESIGN: the `any` / directive is intentional and migration would not
//              improve safety (e.g. demo-mode mock fixtures whose shape
//              mirrors mock JSON literals, not real schemas).
//   LEGACY:    the offender predates the unified envelope / typed
//              responses; the type SHOULD be tightened to a real shape
//              (typically a `*Read` schema mirror or `unknown` + a
//              parser).  Future WP will sweep these.
// -----------------------------------------------------------------------------
interface OffenderEntry {
  file: string; // path relative to repo root
  line: number;
  kind: "any" | "ts-directive";
  justification: string;
}

const _OFFENDER_ALLOWLIST: OffenderEntry[] = [
  // ---------------------------------------------------------------------------
  // frontend/src/mock/data.ts — GH-Pages demo-mode mock fixtures.
  // Mock JSON literals are heterogeneous by design (the demo data covers
  // many problem shapes / solution shapes / comment shapes without being
  // bound to a single *Read schema). Tightening these to real schemas
  // would force the demo to drift every time a real schema evolves, for
  // zero safety win (the data is hand-authored, not parsed from network).
  // ---------------------------------------------------------------------------
  {
    file: "frontend/src/mock/data.ts",
    line: 136,
    kind: "any",
    justification:
      "BY-DESIGN: MOCK_SOLUTIONS is a hand-authored demo-mode fixture; heterogeneous shapes across problem ids; not parsed from network",
  },
  {
    file: "frontend/src/mock/data.ts",
    line: 197,
    kind: "any",
    justification:
      "BY-DESIGN: MOCK_COMMENTS is a hand-authored demo-mode fixture; heterogeneous shapes across problem ids; not parsed from network",
  },

  // ---------------------------------------------------------------------------
  // frontend/src/mock/api.ts — GH-Pages demo-mode mock fetch dispatcher.
  // `handleMutation` and `getMockResponse` accept arbitrary route bodies
  // and return arbitrary JSON to satisfy the multitude of routes the
  // demo intercepts. Each route's caller already narrows the shape via
  // its own parsing logic; the mock layer is the boundary between
  // network-style fetch and in-memory fixtures. `as any` casts inside
  // .map(...) parameters mirror the underlying MOCK_* fixture's `any[]`
  // shape (see mock/data.ts above).
  // ---------------------------------------------------------------------------
  {
    file: "frontend/src/mock/api.ts",
    line: 116,
    kind: "any",
    justification:
      "BY-DESIGN: demo-mode mutation dispatcher; body is the unparsed JSON request body for an arbitrary route, return is the arbitrary route response; callers narrow on their side",
  },
  {
    file: "frontend/src/mock/api.ts",
    line: 150,
    kind: "any",
    justification:
      "BY-DESIGN: demo-mode response dispatcher; return is the arbitrary route response (one of ~10 unrelated shapes); callers narrow on their side",
  },
  {
    file: "frontend/src/mock/api.ts",
    line: 199,
    kind: "any",
    justification:
      "BY-DESIGN: .map callback over MOCK_SOLUTIONS[id] which is itself any[] by design (see mock/data.ts:136)",
  },
  {
    file: "frontend/src/mock/api.ts",
    line: 243,
    kind: "any",
    justification:
      "BY-DESIGN: .filter callback over MOCK_TAGS demo fixture; t.name access is the only contract",
  },
  {
    file: "frontend/src/mock/api.ts",
    line: 288,
    kind: "any",
    justification:
      "BY-DESIGN: parsed request body in demo-mode fetch interceptor; passed through to handleMutation which is itself BY-DESIGN any",
  },

  // ---------------------------------------------------------------------------
  // v2.18-WP03 sweep: Leaderboard.tsx was migrated to a discriminated
  // LeaderboardRawEntry union + normalizeLeaderboardEntry helper. The two
  // previous allow-list entries (lines 64, 65) have been removed.
  // ---------------------------------------------------------------------------

  // ---------------------------------------------------------------------------
  // v2.18-WP02 sweep: ProblemDetail.tsx editSuggestions + attachments state
  // were migrated to EditSuggestionRead[] / AttachmentRead[] (local
  // OpenAPI-mirror interfaces). The four previous allow-list entries
  // (lines 530, 534, 1156, 1207) have been removed.
  // ---------------------------------------------------------------------------
];

// -----------------------------------------------------------------------------
// Lint helper — scan one TS/TSX source string for `any` annotations and
// `@ts-*` directive comments. Returns a list of {line, kind} offender
// records.
// -----------------------------------------------------------------------------
export interface OffenderRecord {
  line: number;
  kind: "any" | "ts-directive";
}

export function scanSource(filename: string, source: string): OffenderRecord[] {
  const sf = ts.createSourceFile(
    filename,
    source,
    ts.ScriptTarget.Latest,
    /* setParentNodes */ true,
    filename.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  );

  const offenders: OffenderRecord[] = [];
  const seen = new Set<number>(); // dedupe by line for `any` (one report per line)

  function lineOf(pos: number): number {
    const { line } = sf.getLineAndCharacterOfPosition(pos);
    return line + 1; // ts is 0-indexed; report 1-indexed for grep parity
  }

  // -------------------- AST walk for `any` (AnyKeyword) --------------------
  function visit(node: ts.Node) {
    if (node.kind === ts.SyntaxKind.AnyKeyword) {
      const ln = lineOf(node.getStart(sf));
      const key = ln;
      if (!seen.has(key)) {
        seen.add(key);
        offenders.push({ line: ln, kind: "any" });
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(sf);

  // -------------------- Textual scan for @ts-* directives ------------------
  // The compiler API does not surface these as AST nodes (they are
  // comment-pragmas processed by the type-checker out-of-band). A
  // per-line regex is sufficient and well-bounded.
  const directiveRe = /\/[\/*]\s*@ts-(ignore|expect-error|nocheck)\b/;
  const lines = source.split("\n");
  for (let i = 0; i < lines.length; i++) {
    if (directiveRe.test(lines[i])) {
      offenders.push({ line: i + 1, kind: "ts-directive" });
    }
  }

  // Sort by line for stable output.
  offenders.sort((a, b) => a.line - b.line || a.kind.localeCompare(b.kind));
  return offenders;
}

// -----------------------------------------------------------------------------
// Filesystem walk — collect every .ts/.tsx file under frontend/src/,
// excluding test files, __tests__/ dirs, and .d.ts declaration files.
// -----------------------------------------------------------------------------
function collectSrcFiles(): string[] {
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (entry.name === "__tests__") continue;
        walk(full);
      } else if (entry.isFile()) {
        const name = entry.name;
        if (name.endsWith(".d.ts")) continue;
        if (/\.test\.(ts|tsx)$/.test(name)) continue;
        if (name.endsWith(".ts") || name.endsWith(".tsx")) {
          out.push(full);
        }
      }
    }
  };
  walk(SRC_DIR);
  return out.sort();
}

function relToRoot(absPath: string): string {
  return path.relative(REPO_ROOT, absPath).split(path.sep).join("/");
}

// -----------------------------------------------------------------------------
// Tests
// -----------------------------------------------------------------------------
describe("v2.17-WP02 TS any/@ts-* structural lint", () => {
  it("detects synthetic `: any` annotation (self-test 1)", () => {
    const src = [
      "export function f(x: any) {",
      "  return x;",
      "}",
      "",
    ].join("\n");
    const hits = scanSource("synthetic_bad_param_any.ts", src);
    expect(hits).toHaveLength(1);
    expect(hits[0].kind).toBe("any");
    expect(hits[0].line).toBe(1);
  });

  it("detects synthetic `as any` cast (self-test 2)", () => {
    const src = [
      "export function f(x: unknown) {",
      "  return (x as any).foo;",
      "}",
      "",
    ].join("\n");
    const hits = scanSource("synthetic_bad_as_any.ts", src);
    expect(hits).toHaveLength(1);
    expect(hits[0].kind).toBe("any");
    expect(hits[0].line).toBe(2);
  });

  it("detects synthetic `Array<any>` / generic-arg any (self-test 3)", () => {
    const src = [
      "export const xs: Array<any> = [];",
      "",
    ].join("\n");
    const hits = scanSource("synthetic_bad_generic_any.ts", src);
    expect(hits).toHaveLength(1);
    expect(hits[0].kind).toBe("any");
    expect(hits[0].line).toBe(1);
  });

  it("detects synthetic `// @ts-ignore` directive (self-test 4)", () => {
    const src = [
      "export function f() {",
      "  // @ts-ignore",
      "  return broken();",
      "}",
      "",
    ].join("\n");
    const hits = scanSource("synthetic_bad_ts_ignore.ts", src);
    expect(hits).toHaveLength(1);
    expect(hits[0].kind).toBe("ts-directive");
    expect(hits[0].line).toBe(2);
  });

  it("detects synthetic `// @ts-expect-error` directive (self-test 5)", () => {
    const src = [
      "export function f() {",
      "  // @ts-expect-error intentional",
      "  return broken();",
      "}",
      "",
    ].join("\n");
    const hits = scanSource("synthetic_bad_ts_expect.ts", src);
    expect(hits).toHaveLength(1);
    expect(hits[0].kind).toBe("ts-directive");
  });

  it("detects synthetic `// @ts-nocheck` directive (self-test 6)", () => {
    const src = [
      "// @ts-nocheck",
      "export const x: number = 'bad';",
      "",
    ].join("\n");
    const hits = scanSource("synthetic_bad_ts_nocheck.ts", src);
    // ts-nocheck flagged. The string-vs-number mismatch is irrelevant
    // to the lint — we report the directive itself, not its effect.
    expect(hits.some((h) => h.kind === "ts-directive" && h.line === 1)).toBe(true);
  });

  it("does NOT flag `: unknown` annotation (self-test 7)", () => {
    const src = [
      "export function f(x: unknown) {",
      "  return x;",
      "}",
      "",
    ].join("\n");
    const hits = scanSource("synthetic_good_unknown.ts", src);
    expect(hits).toEqual([]);
  });

  it("does NOT flag the word 'any' inside string literals or identifiers (self-test 8)", () => {
    const src = [
      "export const kind: 'user' | 'agent' | 'any' = 'any';",
      "export function many() { return 1; }", // contains 'any' as substring
      "// comment with the word any in it should not match",
      "",
    ].join("\n");
    const hits = scanSource("synthetic_good_word_any.ts", src);
    expect(hits).toEqual([]);
  });

  it("matches the offender allow-list against current frontend/src state", () => {
    const files = collectSrcFiles();
    expect(files.length).toBeGreaterThan(0);

    const allOffenders: OffenderEntry[] = [];
    for (const abs of files) {
      const rel = relToRoot(abs);
      const src = fs.readFileSync(abs, "utf8");
      const hits = scanSource(abs, src);
      for (const h of hits) {
        allOffenders.push({
          file: rel,
          line: h.line,
          kind: h.kind,
          justification: "(detected)",
        });
      }
    }

    const allowKey = (e: { file: string; line: number; kind: string }) =>
      `${e.file}:${e.line}:${e.kind}`;
    const allowed = new Map(_OFFENDER_ALLOWLIST.map((e) => [allowKey(e), e]));
    const detected = new Map(allOffenders.map((e) => [allowKey(e), e]));

    const newOffenders: OffenderEntry[] = [];
    for (const [k, e] of detected) {
      if (!allowed.has(k)) newOffenders.push(e);
    }

    const stale: OffenderEntry[] = [];
    for (const [k, e] of allowed) {
      if (!detected.has(k)) stale.push(e);
    }

    const msgs: string[] = [];
    if (newOffenders.length > 0) {
      msgs.push(
        "New TS `any` / `@ts-*` offenders in frontend/src/** — these are " +
          "structurally invisible escape hatches from the type system. " +
          "Use `unknown` + a parser, or a real schema type, instead of " +
          "extending _OFFENDER_ALLOWLIST. If the offender is truly " +
          "intentional, add a BY-DESIGN entry with a concrete reason " +
          "(WHY not WHERE):\n" +
          newOffenders
            .map((e) => `  ${e.file}:${e.line}: ${e.kind}`)
            .join("\n"),
      );
    }
    if (stale.length > 0) {
      msgs.push(
        "Stale _OFFENDER_ALLOWLIST entries (no longer offenders — please " +
          "remove from the allow-list; the future sweep WP deletes LEGACY " +
          "entries as the migration progresses):\n" +
          stale
            .map((e) => `  ${e.file}:${e.line}: ${e.kind}`)
            .join("\n"),
      );
    }
    if (msgs.length > 0) {
      throw new Error(msgs.join("\n\n"));
    }
  });
});
