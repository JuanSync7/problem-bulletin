/**
 * v2.15-WP02 (C2) — bare `catch {}` / swallowing `catch (err) {}` structural
 * lint for tsx files under `frontend/src/pages/`.
 *
 * Background
 * ----------
 * v2.14-WP04 fixed twelve frontend silent-swallow bugs by promoting bare
 * `catch {}` blocks to `catch (err)` and threading `err.message` through to
 * the UI. The retrospective in `.claude/lessons-learned/ticketing-v2.14.md`
 * (lesson "catch {} is structurally invisible to the polarity audit") called
 * for a structural regression net so a future PR cannot reintroduce the
 * class. This file is that net.
 *
 * Scope
 * -----
 * - Scans tsx files under `frontend/src/pages/` (excluding `__tests__/`).
 * - Detects two offender kinds:
 *   - `bare`    — `catch {}` with no binding at all.
 *   - `swallow` — `catch (err) { ... }` where the catch body has zero
 *                 `Identifier` references to the binding name (the error
 *                 object is bound but silently dropped). `catch (err) {
 *                 throw err; }` — i.e. a rethrow that mentions `err` —
 *                 is NOT a swallow (the binding is consumed).
 * - Mirrors the v2.11-WP09 Python lint (`tests/test_create_app_factory_lint_wp09.py`):
 *   explicit `_OFFENDER_ALLOWLIST`, file:line precision, stale-entry
 *   detection. The allow-list captures today's offenders so v2.15-WP03
 *   can delete entries as it migrates files (the SWEEP); WP02 is the PIN.
 *
 * Implementation notes
 * --------------------
 * - Uses the `typescript` compiler API (already a frontend dep). Custom
 *   regex over JSX is too fragile.
 * - `ts.createSourceFile` + `ts.forEachChild` walk, matching `CatchClause`
 *   nodes. The `variableDeclaration` slot is absent for bare catches and
 *   present for bound ones.
 * - For swallow detection: capture the binding name (Identifier or
 *   ObjectBindingPattern), then walk the catch block looking for any
 *   `Identifier` node whose `.text` matches the binding name. Zero matches
 *   = swallow. `catch (err: unknown)` typed bindings still walk via the
 *   identifier slot — the type annotation is ignored.
 * - Try-catch-finally: only the `catchClause` is examined; the `finallyBlock`
 *   is irrelevant. Nested catches are handled because `ts.forEachChild`
 *   recurses.
 */
import * as fs from "node:fs";
import * as path from "node:path";

import * as ts from "typescript";
import { describe, expect, it } from "vitest";

// Repo root: frontend/src/pages/__tests__/ → ../../../..
const REPO_ROOT = path.resolve(__dirname, "..", "..", "..", "..");
const PAGES_DIR = path.join(REPO_ROOT, "frontend", "src", "pages");

// -----------------------------------------------------------------------------
// Offender allow-list — file path (relative to repo root) + line number per
// offender. Mirrors the v2.11-WP09 `_ALLOWLIST` pattern: every entry
// documents a known offender that v2.15-WP03 will sweep as it migrates
// category-c silent-on-non-2xx pages. Entries here are NOT a TODO list of
// "files we have given up on" — they are the closed inventory of pre-WP03
// state. WP03 deletes entries as it fixes sites; new entries require a
// paired justification.
//
// Rule for adding NEW entries: don't. If a PR introduces a new bare
// `catch {}` or swallowing `catch (err) {}` in a `pages/**` file, the lint
// will fail loud at file:line — fix the catch (promote to `catch (err)` and
// thread `err.message` through to the UI, or rethrow / log) instead of
// extending this list.
// -----------------------------------------------------------------------------
interface OffenderEntry {
  file: string; // path relative to repo root
  line: number;
  kind: "bare" | "swallow";
  justification: string;
}

const _OFFENDER_ALLOWLIST: OffenderEntry[] = [
  // Submit.tsx — per-attachment upload failure (v2.16-WP04 left as
  // by-design: aggregates per-file failure into `failedFiles[]` and
  // surfaces a single combined toast outside the loop, so a single
  // hostile file does not abort the whole upload batch).
  {
    file: "frontend/src/pages/Submit.tsx",
    line: 200,
    kind: "bare",
    justification:
      "BY-DESIGN: inner per-attachment upload loop; aggregates per-file failure into outer failedFiles[] + toast batch surface (mirrors ProblemDetail:965 pattern)",
  },
  // ComponentDetail.tsx — inner per-project loop catch; intentionally
  // silent so the outer scan keeps going. Outer try/catch handles the
  // user-visible error surface (`setState({ kind: "error", message })`).
  {
    file: "frontend/src/pages/ComponentDetail.tsx",
    line: 53,
    kind: "bare",
    justification:
      "BY-DESIGN: inner per-project failure during component scan; keep iterating sibling projects so a single broken project does not abort the search; outer catch surfaces top-level failure",
  },
  // Search.tsx — categories fetch for the problems-tab filter.
  // Categories are a soft-degrade: the filter dropdown shows nothing
  // and the user can still execute searches. No error surface exists
  // on the Search page that would not be visually noisy on every
  // page-load failure.
  {
    file: "frontend/src/pages/Search.tsx",
    line: 354,
    kind: "bare",
    justification:
      "BY-DESIGN: categories filter is best-effort enrichment of Search UI; failure leaves dropdown empty; surfacing a toast on every search page-load failure would be noisy and the user can still execute searches",
  },
  // Activity/MentionsTab.tsx — optimistic-update rollback path; the
  // catch body uses setItems to revert the optimistic flip but not
  // the error binding (the swap is the point — UI already reflects
  // failure intent before any user-visible error message would).
  {
    file: "frontend/src/pages/Activity/MentionsTab.tsx",
    line: 246,
    kind: "bare",
    justification:
      "BY-DESIGN: optimistic mark-as-read rollback; UI is reverted via setItems so the user sees the failure inline (row stays unread); no separate error surface needed",
  },
  // Kanban/index.tsx — two localStorage helpers (read pref / write pref).
  // localStorage failures are environment-level (private mode, quota)
  // not user-actionable; both helpers degrade to in-memory defaults.
  {
    file: "frontend/src/pages/Kanban/index.tsx",
    line: 39,
    kind: "bare",
    justification:
      "BY-DESIGN: localStorage read; falls back to in-memory defaults; failure modes (private mode / disabled storage) are environment-level not user-actionable",
  },
  {
    file: "frontend/src/pages/Kanban/index.tsx",
    line: 46,
    kind: "bare",
    justification:
      "BY-DESIGN: localStorage write is best-effort persistence; failure is environment-level (quota / private mode) not user-actionable",
  },
  // Settings.tsx — two date-parse helpers; the catch body returns the
  // unformatted ISO string on `new Date()` / `toLocaleString()` failure.
  // Idiomatic JS fallback, not a silent-swallow class.
  {
    file: "frontend/src/pages/Settings.tsx",
    line: 40,
    kind: "bare",
    justification:
      "BY-DESIGN: date format helper; returns raw ISO string on parse failure as a graceful display fallback; no I/O involved",
  },
  {
    file: "frontend/src/pages/Settings.tsx",
    line: 56,
    kind: "bare",
    justification:
      "BY-DESIGN: relative-time helper; same pattern as line 40 — returns raw ISO string on parse failure",
  },
  // ProblemDetail.tsx — v2.15-WP03 swept 23 of the original 24 sites:
  // every action / hydration / status-transition catch is now
  // `catch (err) { setActionError(...) }` and routes the unified
  // envelope's `message` to the inline `problem-detail__action-error`
  // banner. The single remaining bare catch is the inner per-file
  // upload loop, which is intentionally category-c-by-design: it
  // aggregates per-file failures into a `failed[]` list and
  // surfaces a combined `setActionError("Failed to upload: ...")`
  // outside the loop. Keeping the bare catch there means a single
  // hostile file (e.g. network blip) does not abort the whole
  // upload batch.
  {
    file: "frontend/src/pages/ProblemDetail.tsx",
    line: 965,
    kind: "bare",
    justification:
      "BY-DESIGN: inner per-file upload loop; aggregates per-file failure into outer failed[] + setActionError batch surface (a single hostile file does not abort the whole upload batch)",
  },
];

// -----------------------------------------------------------------------------
// Lint helper — scan one TS/TSX source string for bare/swallow catch
// clauses. Returns a list of {line, kind} offender records.
// -----------------------------------------------------------------------------
export interface OffenderRecord {
  line: number;
  kind: "bare" | "swallow";
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

  function lineOf(node: ts.Node): number {
    const { line } = sf.getLineAndCharacterOfPosition(node.getStart(sf));
    return line + 1; // ts is 0-indexed; report 1-indexed for grep parity
  }

  function visit(node: ts.Node) {
    if (ts.isCatchClause(node)) {
      const decl = node.variableDeclaration;
      const block = node.block;
      if (!decl) {
        // `catch {}` — no binding at all.
        offenders.push({ line: lineOf(node), kind: "bare" });
      } else {
        // `catch (err) { ... }` — check whether the binding name is
        // referenced anywhere in the catch block.
        const bindingNames = collectBindingNames(decl.name);
        if (bindingNames.length === 0) {
          // Defensive: unusual binding shape; treat as swallow so it
          // surfaces.
          offenders.push({ line: lineOf(node), kind: "swallow" });
        } else if (!blockReferencesAny(block, bindingNames)) {
          offenders.push({ line: lineOf(node), kind: "swallow" });
        }
      }
    }
    ts.forEachChild(node, visit);
  }

  visit(sf);
  return offenders;
}

function collectBindingNames(name: ts.BindingName): string[] {
  if (ts.isIdentifier(name)) {
    return [name.text];
  }
  // ObjectBindingPattern / ArrayBindingPattern — collect all bound names.
  const out: string[] = [];
  const walk = (n: ts.Node) => {
    if (ts.isBindingElement(n) && ts.isIdentifier(n.name)) {
      out.push(n.name.text);
    }
    ts.forEachChild(n, walk);
  };
  walk(name);
  return out;
}

function blockReferencesAny(block: ts.Block, names: string[]): boolean {
  const targets = new Set(names);
  let found = false;
  const walk = (n: ts.Node) => {
    if (found) return;
    if (ts.isIdentifier(n) && targets.has(n.text)) {
      found = true;
      return;
    }
    ts.forEachChild(n, walk);
  };
  walk(block);
  return found;
}

// -----------------------------------------------------------------------------
// Filesystem walk — collect every .tsx file under frontend/src/pages/,
// excluding any __tests__/ subdir.
// -----------------------------------------------------------------------------
function collectPageTsxFiles(): string[] {
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (entry.name === "__tests__") continue;
        walk(full);
      } else if (entry.isFile() && entry.name.endsWith(".tsx")) {
        out.push(full);
      }
    }
  };
  walk(PAGES_DIR);
  return out.sort();
}

function relToRoot(absPath: string): string {
  return path.relative(REPO_ROOT, absPath).split(path.sep).join("/");
}

// -----------------------------------------------------------------------------
// Tests
// -----------------------------------------------------------------------------
describe("v2.15-WP02 catch-block structural lint", () => {
  it("detects synthetic bare `catch {}` (self-test 1)", () => {
    const src = [
      "export function f() {",
      "  try { doThing(); } catch { /* swallow */ }",
      "}",
      "",
    ].join("\n");
    const hits = scanSource("synthetic_bad_bare.tsx", src);
    expect(hits).toHaveLength(1);
    expect(hits[0].kind).toBe("bare");
  });

  it("detects synthetic swallowing `catch (err) {}` (self-test 2)", () => {
    const src = [
      "export function f() {",
      "  try { doThing(); } catch (err) { setError('oops'); }",
      "}",
      "",
    ].join("\n");
    const hits = scanSource("synthetic_bad_swallow.tsx", src);
    expect(hits).toHaveLength(1);
    expect(hits[0].kind).toBe("swallow");
  });

  it("does NOT flag `catch (err) { console.error(err) }` (self-test 3)", () => {
    const src = [
      "export function f() {",
      "  try { doThing(); } catch (err) { console.error(err); }",
      "}",
      "",
    ].join("\n");
    const hits = scanSource("synthetic_good_consumed.tsx", src);
    expect(hits).toEqual([]);
  });

  it("does NOT flag `catch (err) { throw err }` rethrow (self-test 4)", () => {
    const src = [
      "export function f() {",
      "  try { doThing(); } catch (err) { throw err; }",
      "}",
      "",
    ].join("\n");
    const hits = scanSource("synthetic_good_rethrow.tsx", src);
    expect(hits).toEqual([]);
  });

  it("does NOT flag `catch (err: unknown) { setError((err as Error).message) }` typed binding (self-test 5)", () => {
    const src = [
      "export function f() {",
      "  try { doThing(); } catch (err: unknown) { setError((err as Error).message); }",
      "}",
      "",
    ].join("\n");
    const hits = scanSource("synthetic_good_typed.tsx", src);
    expect(hits).toEqual([]);
  });

  it("handles try/catch/finally and nested catches (self-test 6)", () => {
    const src = [
      "export function f() {",
      "  try {",
      "    try { inner(); } catch { /* nested bare */ }",
      "  } catch (e) {",
      "    setError(e);",
      "  } finally {",
      "    cleanup();",
      "  }",
      "}",
      "",
    ].join("\n");
    const hits = scanSource("synthetic_nested.tsx", src);
    // Inner bare flagged; outer consumed; finally irrelevant.
    expect(hits).toHaveLength(1);
    expect(hits[0].kind).toBe("bare");
  });

  it("matches the offender allow-list against current `pages/**\\/*.tsx` state", () => {
    const files = collectPageTsxFiles();
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
        "New bare/swallow catch sites in frontend/src/pages/** — these " +
          "discard the structured error envelope. Promote `catch {}` to " +
          "`catch (err)` and thread `err.message` to the UI (toast/inline) " +
          "instead of extending _OFFENDER_ALLOWLIST:\n" +
          newOffenders
            .map((e) => `  ${e.file}:${e.line}: ${e.kind}`)
            .join("\n"),
      );
    }
    if (stale.length > 0) {
      msgs.push(
        "Stale _OFFENDER_ALLOWLIST entries (no longer offenders — please " +
          "remove from the allow-list; v2.15-WP03 sweep progress):\n" +
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
