# v2.17 ticketing — lessons learned

Companion to `ticketing-v2.16.md`. Each WP records (a) what shipped,
(b) the cost surface, (c) lessons that survive the WP, and (d)
deferred follow-ups feeding the v2.18 backlog.

v2.17 was the **preventive-hardening version**. v2.15 closed the last
identified structural-debt class (category-c silent-on-non-2xx) and
v2.16 closed the carried-forward cosmetic residue (SyntaxWarning, RR
v7 future-flag warnings, bare-catch allow-list shrink). v2.17 opened
with **zero scoped backlog** — no carried-forward structural class, no
cosmetic residue, no triggering Bucket A/B need. The work was to PIN
two new structural lints (TS `any` / `@ts-*` and Python
`# type: ignore` / `# noqa`) BEFORE these classes become debt.
Mirrors v2.15-WP02's lint-before-sweep pattern, but generalised: the
PIN alone is load-bearing even when no SWEEP is scheduled. Two
preventive-hardening WPs + baseline + closure.

**Closing baselines:** backend **1433 → 1438 P / 0 F / 5 skipped /
14 xfailed** (+5, all from WP03's Python `# type: ignore` / `# noqa`
structural-lint test module). Frontend **260 → 269 P / 0 F** (+9 from
WP02's TS `any` / `@ts-*` structural-lint test module).

---

## v2.17-WP01 (G0) — baseline verify

Backend: **1433 P / 0 F / 5 skipped / 14 xfailed**. Frontend:
**260 P / 0 F**. Confirmed as the regression anchor for WP02+.

All prior fixes from v2.15 and v2.16 hold cleanly:

- **OTel `Connection refused` noise** — zero matches against stderr
  (v2.15-WP04's `InMemoryMetricReader` swap under
  `PYTEST_CURRENT_TEST` still in force).
- **RR v7 future-flag warnings** — zero matches in vitest stderr
  (v2.16-WP03's per-file `future={...}` opt-in on `<BrowserRouter>`
  + 16 `<MemoryRouter>` callsites holds).
- **SyntaxWarning in `app/`** — zero offenders under
  `pkgutil.walk_packages` + `warnings.simplefilter('error', ...)`
  (v2.16-WP02's `_escape_like` raw-string docstring holds).

No carried-forward Bucket-Z items remain. Bucket A (C7, E3, E4, F3 —
v2.11 carry-forwards) and Bucket B (B1 per-arm `refresh_total`, B2
WP05 parser expansion) remain conditional and saw no triggering need
during v2.17.

No code or test changes in WP01.

---

## v2.17-WP02 — TS `any` / `@ts-*` structural lint (PIN)

**Pre-state.** No structural lint pinned the count of TS escape
hatches in `frontend/src/`. The codebase had a small number of `any`
sites (both intentional — demo-mode fixtures — and incidental — page
state for backend-typed lists) and zero `@ts-*` directives. Nothing
prevented a future PR from quietly adding more on either axis.

**Lint shape.** A single new test file
`frontend/src/__tests__/ts_any_lint.test.ts`. Two detection axes:

1. **Explicit `any`** — AST walk over `frontend/src/**/*.{ts,tsx}`,
   matching `SyntaxKind.AnyKeyword` nodes. Covers function params,
   return types, variable annotations, generic args
   (`Array<any>`, `Record<string, any>`), `as any` casts (via
   `AsExpression.type`), and `useState<any[]>`.
2. **`@ts-*` directives** — per-line regex
   `/[\/*]\s*@ts-(ignore|expect-error|nocheck)\b/`. The TypeScript
   compiler API does NOT expose `@ts-*` pragmas as AST nodes — they
   are comment-band annotations consumed by the type-checker, not
   the parser. Regex is the right primitive.

**Scope exclusions.** `*.d.ts` (interop shims; hand-written `any` is
expected at the typed-vs-untyped boundary), `**/*.test.{ts,tsx}`,
and any directory named `__tests__/`.

**Per-line dedupe.** When one line carries multiple `AnyKeyword`
nodes (e.g. `(x: any): any =>` triggers twice; `Record<string, any>`
inside a function signature can trigger twice), the lint emits ONE
entry per `path:line`. Implemented via `seen: Set<line>` in
`scanSource`. Without this, the allow-list grows N entries per line
and drifts on every cosmetic edit; with it, allow-list entries are
stable across whitespace and rename edits within the same line.

**Offender inventory — 13 sites across 4 files.**

| category | count | shape |
|---|---|---|
| (a) BY-DESIGN | 7 | all in `frontend/src/mock/**` — demo-mode dispatcher + fixtures |
| (b) LEGACY | 6 | `Leaderboard.tsx` (2) + `ProblemDetail.tsx` (4) |
| `@ts-*` directives | **0** | **entire frontend non-test surface clean on this axis** |

The 7 BY-DESIGN entries live in `mock/api.ts` (5 — `handleMutation`
demo-mode dispatcher, `getMockResponse` response dispatcher, `.map`
/ `.filter` over demo arrays, parsed request body) and `mock/data.ts`
(2 — `MOCK_SOLUTIONS` / `MOCK_COMMENTS` heterogeneous demo fixtures).
Demo data legitimately has heterogeneous shape — typing it would
either over-constrain the fixture (defeating its purpose as a
plug-many-shapes dispatcher) or require a discriminated union large
enough to be its own debt class.

The 6 LEGACY entries pair naturally for a future sweep:

- **Leaderboard.tsx (2 sites)** — `const raw: any[]` + paired `.map`;
  per-track backend response is one of multiple historical shapes.
  Tighten to a discriminated `LeaderboardRawEntry` union with a
  normaliser into the internal `LeaderboardEntry`.
- **ProblemDetail.tsx editSuggestions (2 sites — 530/1156)** —
  `useState<any[]>` + paired `.map`. Adopt `EditSuggestionRead[]`
  from the OpenAPI types already pinned by the v2.12-WP11 parity
  lint.
- **ProblemDetail.tsx attachments (2 sites — 534/1207)** — same
  shape; adopt `AttachmentRead[]`.

**The 0-offender axis.** WP02 found **zero** `@ts-*` directives
across the entire frontend non-test surface. Most TS codebases
accumulate at least a handful of these silently — every contributor
hits a tricky third-party type and reaches for `@ts-ignore`. This
codebase had none. The lint now LOCKS that in: any future
`@ts-ignore` / `@ts-expect-error` / `@ts-nocheck` MUST come with a
`BY-DESIGN:` justification in `_OFFENDER_ALLOWLIST`, or the lint
fails red. A 0-offender pin is the strongest regression net you can
ship — it's measuring "this stays clean", not "this gets cleaner".

**Stale-entry detection.** The lint runs both directions: every
detected offender must be allow-listed, AND every allow-list entry
must still correspond to a live offender. File deletes, line shifts,
and offender removal all fail loud. This is what makes the eventual
SWEEP per-step verifiable — deleting an entry without removing its
offender (or vice versa) fails the lint, so the maintainer can't
drift the allow-list past the code.

**Self-tests — 8 + 1 parity = +9 total.**

1. synthetic `function f(x: any)` → flagged
2. synthetic `(x as any).foo` → flagged
3. synthetic `const xs: Array<any>` → flagged
4. synthetic `// @ts-ignore` → flagged as directive
5. synthetic `// @ts-expect-error` → flagged as directive
6. synthetic `// @ts-nocheck` → flagged as directive
7. synthetic `function f(x: unknown)` → NOT flagged (negative case)
8. synthetic string literal `'any'` + identifier `many` + comment
   containing the word `any` → NOT flagged (false-positive guard;
   AST walk skips strings, identifiers, comments)
9. real-file scan: `_OFFENDER_ALLOWLIST` parity test — every detected
   offender is allow-listed AND every allow-list entry is still live

**Numbers.**

- Frontend net delta: 260 → **269** (+9).
- Backend untouched at 1433.
- Files added: 1 lint module + 1 diagnosis doc. Production code
  untouched.

**Lessons surviving WP02.**

1. **Compiler-API pragma blindspot — pragmas are NOT AST nodes.** The
   TypeScript compiler API does not expose `@ts-ignore`,
   `@ts-expect-error`, or `@ts-nocheck` as AST nodes. They are
   side-band annotations consumed by the type-checker, not the
   parser. Bounded per-line regex is the right primitive. Pattern:
   when linting for pragma comments, do NOT assume AST coverage.
2. **Per-line dedupe keeps allow-lists stable.** Multiple `AnyKeyword`
   nodes on one line (e.g. `(x: any): any =>`) without dedupe would
   create N entries per line, drifting on every cosmetic edit. One
   entry per `path:line` is the stable shape. Pattern: lints emit
   ONE entry per `path:line`, not per AST match.
3. **A 0-offender axis is its own success metric.** The `@ts-*`
   directive count was 0 going into WP02 and is 0 coming out. The
   lint locks that in. Pattern: when a class is already at 0 in your
   codebase, a PIN is the strongest regression net you can ship —
   no offender to sweep, only the invariant to preserve.
4. **Demo-mode / fixture data is a legitimate `any` axis.** The 7
   BY-DESIGN entries are all in `frontend/src/mock/**` — hand-authored
   demo dispatcher + fixtures. These are NOT debt; demo data
   legitimately has heterogeneous shape. Pattern: `mock/` and
   `fixtures/` directories are reasonable BY-DESIGN allow-list
   residents; flagging them as LEGACY would be a false positive on
   UX (or on developer ergonomics for the demo-mode subsystem).

---

## v2.17-WP03 — Python `# type: ignore` / `# noqa` structural lint (PIN)

**Pre-state.** Mirror of WP02 on the Python side. The codebase
carried a known set of `# type: ignore` and `# noqa` comment pragmas
across `app/**/*.py` — some load-bearing (SQLAlchemy registry
re-exports, local imports for circular-avoidance, broad-catch
boundary tools), some incidental. Nothing pinned the count.

**Lint shape.** A single new test file
`tests/test_type_ignore_lint_wp03_v217.py`. Two detection patterns:

- `r"#\s*type:\s*ignore\b"` — bare and `[code]`-suffixed.
- `r"#\s*noqa\b"` — bare and `: rule[, rule]`-suffixed.

Both run over `Path.read_text().splitlines()` — NOT via `ast.parse`.

**Why regex over `splitlines()`, not AST.** Same finding as WP02
(TypeScript) ported to Python: **`ast.parse` strips comments**.
`# type: ignore` and `# noqa` are both invisible to an AST walk.
`tokenize` would see them via `tokenize.COMMENT` tokens, but adds
complexity for no win — the patterns are line-level markers and
regex over `splitlines()` is sufficient. The regex-vs-tokenize
tradeoff is documented in the lint module's docstring so a future
maintainer hitting a string-literal false positive knows the
escape hatch (switch to tokenize) is one-line away.

**Scope exclusions.** `tests/**` (test-only suppression patterns
differ), `alembic/**` (lives at repo root, not under `app/`;
defensive `_EXCLUDED_PREFIXES = ("app/migrations/", "app/alembic/")`
also in place in case a refactor ever moves alembic under `app/`),
`scripts/**` (one-off utilities).

**Offender inventory — 34 sites across 12 files.**

| category | count | shape |
|---|---|---|
| (a) BY-DESIGN | 33 | structural language/framework requirements |
| (b) LEGACY | 1 | `notifications_v1.py:177` SQL-row enum narrowing |

By directive kind: 4 `# type: ignore` (incl. code suffix) + 30
`# noqa` (incl. code suffix) = 34 total. By file the heaviest
concentration is `app/models/__init__.py` with 25 entries — every
one is a `# noqa: F401` on a SQLAlchemy model re-export.

**The SQLAlchemy registry barrel — the canonical Python noqa case.**
25 of the 34 offenders sit in `app/models/__init__.py`, all
`# noqa: F401` on model re-exports. SQLAlchemy REQUIRES these
imports for metaclass registration to populate `Base.metadata`, but
pyflakes (the F401 check) can't see that side effect — from its
perspective the imports are unused. This is the textbook ORM
registry case. Pattern: any ORM / registry barrel is a BY-DESIGN
F401 site; lint should accept it explicitly with a stable
`BY-DESIGN:` rationale.

**Other BY-DESIGN clusters worth naming.**

- **Broad-catch boundaries (4 sites)** — `mcp_server/tools.py`,
  `mcp_server/server.py`, `routes/health.py` ×2. All `noqa: BLE001`
  on intentional `except Exception` blocks where uniform translation
  or "any failure is unhealthy" IS the design (health probes can't
  fail-by-class — any error means unhealthy).
- **Local imports for circular-avoidance (2 sites)** —
  `logging.py:82` (`get_correlation_id` inside a log filter to avoid
  top-level circular import), `services/tickets.py:417`
  (`User` import inside a function body). Both `noqa: WPS433`.
- **TYPE_CHECKING / forward-ref shims (2 sites)** —
  `services/exceptions.py:33` (`F821` on a string forward-ref
  `"datetime"`), `routes/admin/__init__.py:8` (`type: ignore[misc]`
  on a fallback stub for `require_admin`).
- **Runtime-assigned attributes (1 site)** —
  `routes/realtime_ws.py:55`,
  `type: ignore[attr-defined]` on `async_session_factory` which is
  assigned at runtime via `async_sessionmaker(...)`. Mypy cannot see
  the assignment.

**The single LEGACY entry.**

- **`app/routes/notifications_v1.py:177`** —
  `# type: ignore[arg-type]` narrowing `row.actor_type`
  (`Optional[str]` from a SQL row) into an enum-typed `kind` slot.
  Two natural sweep paths: (a) a typed `cast()` from `typing` at the
  callsite, or (b) tightening the row return type at the query
  boundary so `actor_type` is already enum-typed.

**Honest categorisation — 33/1, not 30/4 or 25/9.** v2.17-WP03 had
no triggering need; the subagent could have skipped, or padded the
LEGACY count to manufacture a sweep target. It honestly classified
33 as structural and 1 as actual debt. The single LEGACY entry is
the v2.18 backlog seed; everything else is permanent. Pattern:
BY-DESIGN/LEGACY split self-prioritises future work; the LEGACY
count IS the next-version sweep target, no more no less.

**Stale-entry detection.** Same shape as WP02. The allow-list keys
on `path:line`, so renaming a variable on an offender line keeps
the entry valid, but inserting a new line above shifts the line
number — the stale-detection branch then fails loud, forcing the
maintainer to re-check the shifted entry.

**SyntaxWarning hygiene on the lint itself.** The lint module's
docstring documents the regex patterns inline. The first draft
emitted `SyntaxWarning: invalid escape sequence '\s'` from the
documented regex inside the docstring (same class of issue v2.16-WP02
fixed in `search_multi.py`). The fix is identical: raw-string
docstring prefix. Pattern is now consistent across the repo —
v2.16-WP02 fixed one in production code, v2.17-WP03 caught one in
test code at write time. Worth naming as the established hygiene:
**any docstring that documents regex / shell / LIKE / escape syntax
should be `r"""..."""`**.

**Self-tests — 4 + 1 parity = +5 total.**

1. `test_scanner_flags_synthetic_bare_type_ignore` —
   `# type: ignore` (no code suffix) → flagged
2. `test_scanner_flags_synthetic_type_ignore_with_code` —
   `# type: ignore[arg-type]` → flagged
3. `test_scanner_flags_synthetic_noqa` — `# noqa: F401` → flagged
4. `test_scanner_does_not_flag_clean_line` — clean Python including
   a docstring that mentions the words "type" and "noqa" (without
   the leading `#` marker) plus an ordinary comment about "types"
   → NOT flagged (false-positive guard)
5. `test_no_type_ignore_or_noqa_outside_allowlist` — real-file
   scan: every detected offender is allow-listed AND every
   allow-list entry is still live

**Numbers.**

- Backend net delta: 1433 → **1438** (+5).
- Frontend untouched at 269.
- Files added: 1 lint module + 1 diagnosis doc. Production code
  untouched.

**Lessons surviving WP03.**

1. **Compiler-API pragma blindspot generalises across languages.**
   `ast.parse` strips comments; `tokenize` sees them but adds
   complexity. Bounded regex over source text is the right primitive
   for pragma linting in Python — identical finding to WP02's TS
   compiler-API blindspot. Pattern: any language where pragmas
   live in comments will require source-text matching, not AST.
2. **SQLAlchemy registry barrel is the canonical Python F401 case.**
   25 of 34 offenders are model re-exports in `app/models/__init__.py`.
   ORM frameworks REQUIRE these imports for metaclass registration,
   but pyflakes can't see that. Pattern: any ORM / registry barrel
   is a BY-DESIGN F401 site; lint accepts it explicitly.
3. **Honest categorisation survives the autonomous-execution test.**
   33 BY-DESIGN / 1 LEGACY is an honest split. The LEGACY entry is a
   real sweep target; the 33 are permanent structural sites.
   Pattern: when a subagent could pad either direction (skip
   entirely, or manufacture more LEGACY for a future sweep), the
   diagnostic doc is where each entry's classification is justified
   so the call is auditable.
4. **`r"""..."""` is the established hygiene for any docstring
   documenting escape / regex / LIKE syntax.** v2.16-WP02 fixed
   one in production (`search_multi.py:119`); v2.17-WP03 caught
   one at write time in the new lint test module. The pattern is
   now repo-wide and worth naming: any docstring whose subject IS
   the literal `\`-character (regex, LIKE, shell, format strings)
   should use a raw-string prefix.

---

## v2.17-WP04 (closure) — retrospective + v2.18 seed

This document. Zero code touched.

---

## v2.17 retrospective

### Headline numbers

- **Backend baseline:** 1433 P / 0 F / 5 skipped / 14 xfailed
  (v2.16 close).
- **Backend final:** **1438 P / 0 F / 5 skipped / 14 xfailed**.
- **Net delta:** +5 backend (WP03 Python `# type: ignore` / `# noqa`
  structural-lint module).
- **Frontend baseline:** 260 P / 0 F (v2.16 close).
- **Frontend final:** **269 P / 0 F**.
- **Net delta:** +9 frontend (WP02 TS `any` / `@ts-*` structural-lint
  module).
- **Production code touched:** **zero files**. Both PIN WPs are
  test-only.
- **`@ts-*` directive count in `frontend/src/` non-test surface:**
  **0** (locked in by WP02).
- **TS `any` offenders:** 13 — 7 BY-DESIGN (mock/), 6 LEGACY
  (Leaderboard + ProblemDetail).
- **Python pragma offenders:** 34 — 33 BY-DESIGN (registry barrel +
  structural language requirements), 1 LEGACY (`notifications_v1.py`
  SQL-row enum narrowing).
- **Production bugs caught and fixed:** zero. Both WPs were PIN-only
  preventive hardening.
- **Production regressions introduced:** zero.

### WPs shipped

| WP | Bucket | Summary | Test delta |
|---|---|---|---|
| WP01 | G0 | Baseline verify (1433 P backend / 260 P frontend). v2.15-WP04 OTel fix, v2.16-WP02 SyntaxWarning fix, v2.16-WP03 RR future-flag opt-in all re-confirmed clean. | ±0 |
| WP02 | preventive | TS `any` / `@ts-*` structural lint at `frontend/src/__tests__/ts_any_lint.test.ts`. AST walk for `AnyKeyword` + per-line regex for `@ts-*` directives. 13 offenders pinned (7 BY-DESIGN mock/, 6 LEGACY Leaderboard + ProblemDetail). **0** `@ts-*` directives — clean axis locked in. Per-line dedupe stable across whitespace edits. 8 self-tests + 1 parity test. | +9 (260→269 frontend) |
| WP03 | preventive | Python `# type: ignore` / `# noqa` structural lint at `tests/test_type_ignore_lint_wp03_v217.py`. Regex over `splitlines()` (not AST — comments stripped). 34 offenders pinned (33 BY-DESIGN incl. 25 SQLAlchemy registry F401s, 1 LEGACY `notifications_v1.py:177`). r-string docstring hygiene on the lint itself (consistent with v2.16-WP02). 4 self-tests + 1 parity test. | +5 (1433→1438 backend) |
| WP04 | closure | Retrospective + v2.18 seed (this doc). | ±0 |

### Cross-cutting lessons

1. **Lint-before-sweep generalises to preventive hardening — the PIN
   alone is load-bearing.** v2.15-WP02 pinned bare-catch BEFORE
   v2.15-WP03 swept it. v2.17 pinned two new lints (TS `any`, Python
   pragma) with NO sweep scheduled. The lint alone is valuable: it
   freezes the offender count at today's level. Future PRs adding a
   new `: any` or `# type: ignore` must paired-justify via the
   allow-list. Pattern: when a debt class is small enough that the
   sweep is optional, the PIN is still load-bearing as a forcing
   function — every new offender hits a paired-review gate.

2. **Compiler-API pragma blindspot — pragmas are NOT AST nodes.**
   Both WP02 (TypeScript) and WP03 (Python) independently found that
   the language's AST / compiler API does NOT expose pragma comments
   (`@ts-ignore`, `# type: ignore`, `# noqa`) as AST nodes. They are
   side-band annotations consumed by the type-checker or linter, not
   the parser. Solution: per-line regex over source text. Pattern:
   when linting for pragmas, do NOT assume AST coverage; bounded
   regex over `splitlines()` (Python) or per-line scan (TS) is the
   right primitive. The TS finding seeded the Python WP's design
   directly — pragma-lint architecture is now repo-canonical.

3. **A 0-offender axis is its own success metric.** WP02 found **0**
   `@ts-*` directives across the entire frontend non-test surface.
   Most TS codebases accumulate these silently — every contributor
   hits a tricky third-party type and reaches for `@ts-ignore`.
   This codebase had none. The lint LOCKS that in: any future
   `@ts-ignore` MUST come with a `BY-DESIGN:` justification. Pattern:
   a 0-offender pin is the strongest regression net you can ship —
   it's measuring "this stays clean", not "this gets cleaner". Worth
   actively LOOKING for 0-offender axes when designing a new lint;
   they're the highest-ROI half of any structural-lint module.

4. **Honest categorisation survives the autonomous-execution test.**
   v2.17 had no triggering need; both subagents could have either
   skipped (no work) or padded (manufactured more LEGACY entries to
   create future sweep targets). They honestly classified: 7
   BY-DESIGN + 6 LEGACY (TS), 33 BY-DESIGN + 1 LEGACY (Python). The
   single Python LEGACY is a real sweep target. Pattern: BY-DESIGN
   / LEGACY split self-prioritises future work; the LEGACY count IS
   the next-version backlog seed, no more no less. The diagnosis doc
   is where each entry's classification is justified so the call is
   auditable post-hoc.

5. **Per-line dedupe in lint emission keeps allow-lists stable.**
   WP02 noted: when one line carries multiple `AnyKeyword` nodes
   (e.g. `(x: any): any =>` or `Record<string, any>` in a function
   signature), the lint emits ONE entry per `path:line`, not per
   AST match. Without this, the allow-list grows N entries per line
   and drifts on every cosmetic edit. With it, allow-list entries
   are stable across whitespace and rename edits within the same
   line. Pattern: any structural lint with allow-list keying should
   collapse to `path:line` granularity, not `path:line:column` or
   per-match.

6. **Demo-mode / fixture / registry-barrel sites are legitimate
   BY-DESIGN allow-list residents.** WP02's `mock/` cluster (7
   entries — hand-authored demo dispatcher + fixtures with
   intentionally heterogeneous shape) and WP03's
   `app/models/__init__.py` cluster (25 entries — SQLAlchemy
   metaclass-registry F401s) are textbook BY-DESIGN sites. Demo
   data legitimately has heterogeneous shape; ORM registries
   legitimately require side-effecting imports. Pattern: when a
   directory's WHOLE PURPOSE is to host the offending pattern
   (`mock/`, `fixtures/`, `models/__init__.py`), the entries are
   structural — not debt. Flagging them as LEGACY would be a false
   positive on UX or framework requirements.

7. **`r"""..."""` is repo-canonical for docstrings documenting
   escape / regex / LIKE / shell syntax.** v2.16-WP02 fixed one in
   production (`search_multi.py:119` `_escape_like` documenting LIKE
   metacharacters). v2.17-WP03 caught one in test code at write time
   (the new pragma-lint module's regex documentation in its
   docstring). The pattern is now repo-wide. Pattern: any docstring
   whose subject IS the literal `\`-character (regex, LIKE, shell,
   format strings, `@ts-*` syntax docs) should use a raw-string
   prefix from the first draft.

### What stayed deferred (carry to v2.18)

- **TS LEGACY sweep — 6 entries.** Natural type-tightening sweep:
  - `ProblemDetail.tsx:530, 1156` — `editSuggestions` →
    `EditSuggestionRead[]` from the OpenAPI types pinned by the
    v2.12-WP11 parity lint.
  - `ProblemDetail.tsx:534, 1207` — `attachments` →
    `AttachmentRead[]` from the same OpenAPI types.
  - `Leaderboard.tsx:64, 65` — `const raw: any[]` + paired `.map`
    → discriminated `LeaderboardRawEntry` union + normaliser.
  Each sweep step deletes its allow-list entry and the stale-entry
  detection branch enforces the deletion (cannot drift past the
  code).
- **Python LEGACY sweep — 1 entry.**
  `app/routes/notifications_v1.py:177` `# type: ignore[arg-type]`
  on SQL-row enum narrowing. Two paths: (a) `typing.cast()` at the
  callsite, or (b) tighten the row return type at the query
  boundary so `actor_type` is already enum-typed.
- **Bucket A (C7, E3, E4, F3)** — still conditional v2.11
  carry-forwards (`decode_email_body` helper, KindPill 7th surface,
  `useSearchV2` ergonomic follow-ups, TipTap second-consumer
  extraction). No triggering need fired in v2.17.
- **B1 — per-arm `refresh_total` opt-in syntax** — still
  conditional. Wire-shape change only (`refresh_total: boolean |
  string[]`); pick up only on a real user need.
- **B2 — WP05 OpenAPI↔TS parser expansion** — nested generics,
  intersection types, multi-param generics, generic type aliases,
  mapped/conditional, default generic params. Parser-rejected with
  explicit self-tests; pick up when the first
  `frontend/src/api/*.ts` consumer needs one.
- **9 by-design bare-catch entries** — PERMANENTLY documented in
  v2.16-WP04 with `BY-DESIGN:` rationale per entry. Not a
  carry-forward.
- **33 by-design Python pragma entries + 7 by-design TS `any`
  entries** — PERMANENTLY documented in v2.17-WP02 / WP03
  `_OFFENDER_ALLOWLIST` with `BY-DESIGN:` rationale per entry. They
  will not be re-evaluated unless the file is touched for product
  reasons.

### Files touched (rough stats)

- **Production code (`app/`):** **0 files**. Both WPs are PIN-only.
- **Alembic (`alembic/versions/`):** 0 files.
- **Test code (`tests/`):**
  - 1 new file: `tests/test_type_ignore_lint_wp03_v217.py` (WP03,
    5 cases: 4 self-tests + 1 allow-list parity test).
- **Frontend (`frontend/`):**
  - 1 new file: `frontend/src/__tests__/ts_any_lint.test.ts` (WP02,
    9 cases: 8 self-tests + 1 allow-list parity test).
- **Docs (`.claude/lessons-learned/`):** 2 per-WP diagnosis files
  (`v2.17-wp02-diagnosis.md`, `v2.17-wp03-diagnosis.md`) + this
  retrospective.

---

## v2.18 starting prompt seed

v2.17 closed as a **preventive-hardening version**: two new
structural lints pinned (TS `any` / `@ts-*` at WP02, Python
`# type: ignore` / `# noqa` at WP03), zero production code touched,
both PIN-only. The lint allow-lists honestly classified every
offender as BY-DESIGN or LEGACY — yielding a small concrete sweep
backlog for v2.18: **7 LEGACY type-tightening targets (6 TS + 1
Python)**.

This is a different shape from v2.17's open. v2.17 opened with zero
scoped backlog and built two PINs that surfaced backlog as a side
effect. **v2.18 has a concrete, paired-with-PIN backlog from the
start.** Recommend v2.18 as a **type-tightening sweep version**,
mirroring v2.15-WP03's sweep-after-pin pattern: each LEGACY entry
gets deleted from its `_OFFENDER_ALLOWLIST` as its type is tightened;
lint stale-entry detection enforces the per-entry workflow (cannot
delete an entry without removing its offender, cannot remove an
offender without deleting its entry — both directions fail loud).

After this 7-entry sweep, v2.19 returns to opportunistic-only mode.

### v2.18 backlog

#### Bucket L — LEGACY type-tightening sweep (PRIMARY v2.18 work)

L1. **`ProblemDetail.tsx:530, 1156` — `editSuggestions` →
    `EditSuggestionRead[]`.** Adopt from OpenAPI types pinned by
    v2.12-WP11 parity lint. Delete the two paired allow-list entries
    on completion.
L2. **`ProblemDetail.tsx:534, 1207` — `attachments` →
    `AttachmentRead[]`.** Same pattern as L1. Delete the two paired
    allow-list entries on completion.
L3. **`Leaderboard.tsx:64, 65` — `raw: any[]` + paired `.map` →
    discriminated `LeaderboardRawEntry` union.** Introduce a
    per-track discriminated union matching the historical backend
    response shapes and a normaliser into the internal
    `LeaderboardEntry`. Delete the two paired allow-list entries on
    completion.
L4. **`app/routes/notifications_v1.py:177` — `type: ignore[arg-type]`
    on SQL-row enum narrowing.** Either (a) wrap with
    `typing.cast()` at the callsite, or (b) tighten the row return
    type at the query boundary. Delete the single allow-list entry
    on completion.

Suggested WP packaging: L1+L2 in one WP (both ProblemDetail,
shared OpenAPI types — natural pair), L3 in its own WP (Leaderboard
needs the discriminated-union design work), L4 in its own WP
(Python side, different file family). Three sweep WPs + baseline +
closure = ~5 WPs total for v2.18.

#### Bucket A — Conditional v2.11 carry-forwards (act only on triggering need)

A1. **C7 — `decode_email_body` helper.** Pick up only on a second
    QP-wrap consumer.
A2. **E3 — KindPill 7th surface.** Pick up when a real consumer
    surfaces.
A3. **E4 — `useSearchV2` ergonomic follow-ups.** Pick up when a
    second consumer surfaces.
A4. **F3 — TipTap second-consumer extraction.** Pick up when a
    second editor surface lands.

#### Bucket B — Conditional v2.13 carry-forwards

B1. **Per-arm `refresh_total` opt-in syntax** (option (a) from
    v2.13-WP06). Wire-shape change only: `refresh_total: boolean |
    string[]`. Pick up if a real user need surfaces.
B2. **WP05 OpenAPI↔TS parser expansion** — nested generics,
    intersection types, multi-param generics, generic type aliases,
    mapped/conditional, default generic params. Parser-rejected
    with explicit self-tests; pick up when the first
    `frontend/src/api/*.ts` consumer needs one.

### v2.18 prompt seed (paste-ready)

> Proceed with v2.18 of the problem-bulletin ticketing system.
> v2.17 retrospective + carry-forward backlog live at the bottom of
> `.claude/lessons-learned/ticketing-v2.17.md`. Baselines: backend
> **1438 P / 0 F / 5 skipped / 14 xfailed**, frontend **269 P / 0
> F**. **v2.17 was the preventive-hardening version — two new
> structural lints pinned (TS `any` / `@ts-*` at WP02, Python
> `# type: ignore` / `# noqa` at WP03) with NO production code
> touched. The PIN allow-lists honestly classified every offender,
> yielding a small concrete v2.18 backlog: 7 LEGACY type-tightening
> targets (6 TS + 1 Python). Recommend v2.18 as a type-tightening
> sweep version, mirroring v2.15-WP03's sweep-after-pin pattern.**
> Each LEGACY entry deleted from its `_OFFENDER_ALLOWLIST` as its
> type is tightened; lint stale-entry detection enforces the
> per-entry workflow (both directions fail loud). After this sweep,
> v2.19 returns to opportunistic-only mode. **Bucket L (PRIMARY):**
> L1 ProblemDetail editSuggestions → `EditSuggestionRead[]` (2
> sites); L2 ProblemDetail attachments → `AttachmentRead[]` (2
> sites); L3 Leaderboard `raw: any[]` → discriminated
> `LeaderboardRawEntry` union (2 sites); L4
> `app/routes/notifications_v1.py:177` SQL-row enum narrowing —
> `cast()` or tightened row return type. Suggested packaging:
> L1+L2 paired (shared OpenAPI types), L3 standalone, L4
> standalone — three sweep WPs + baseline + closure. **Bucket A**
> (C7, E3, E4, F3) and **Bucket B** (B1, B2) remain conditional
> carry-forwards — act ONLY on triggering second-consumer need.
> Follow the sequential subagent loop pattern, TDD-first, one
> diagnosis doc per WP under
> `.claude/lessons-learned/v2.18-wpNN-diagnosis.md`. Append lessons
> to `.claude/lessons-learned/ticketing-v2.18.md`. **Forward rules
> carried from v2.15:** (a) lint-before-sweep when a class has
> known shape; (b) by-design enumeration at FIRST surfacing of any
> mixed-population class; (c) two state slots for pages with both
> load-failure and action-failure UX; (d) `PYTEST_CURRENT_TEST` is
> the canonical no-config test-mode sentinel — prefer over
> inventing a project-local flag; (e) audit metric exporters first
> when OTel noise surfaces. **Forward rules carried from v2.16:**
> (f) `pkgutil.walk_packages` + `warnings.simplefilter('error',
> ...)` is the audit primitive for any compile-time warning class;
> (g) per-file opt-in beats global mock shims for forward-compat
> flags — call-site visibility outweighs DRY appeal, mocks drift;
> (h) `BY-DESIGN:` comments in allow-lists answer WHY, not WHERE —
> grep on `BY-DESIGN:` enumerates intentional exceptions; (i)
> honest classification beats stretch target — when a metric
> forces UX degradation, ship the honest number; (j) forward-compat
> flags are forgiving but not free — audit semantics before
> flipping; (k) three Bucket-Z items is the soft ceiling per
> cosmetic version; (l) after a structural-debt version, schedule
> a cosmetic version to mop up compile-time/test-time noise.
> **Forward rules new from v2.17:** (m) lint-before-sweep
> generalises to preventive-hardening — the PIN alone is
> load-bearing even without a scheduled sweep, acting as a
> paired-review forcing function for any new offender; (n)
> compiler-API pragma blindspot — pragmas (`@ts-ignore`,
> `# type: ignore`, `# noqa`) are NOT AST nodes in any language;
> bounded per-line regex over source text is the right primitive,
> NOT AST walks; (o) a 0-offender axis is its own success metric —
> when a class is already at 0, a PIN locks the invariant and is
> the highest-ROI half of any structural-lint module; (p)
> per-line dedupe in lint emission keeps allow-lists stable across
> cosmetic edits — collapse to `path:line` granularity, not
> `path:line:column` or per-match; (q) demo-mode / fixture /
> registry-barrel sites are legitimate BY-DESIGN allow-list
> residents — when a directory's whole purpose is to host the
> offending pattern (`mock/`, `fixtures/`, `models/__init__.py`),
> the entries are structural, not debt; (r) `r"""..."""` is
> repo-canonical for any docstring documenting escape / regex /
> LIKE / shell / pragma syntax — establish at first draft, not
> after SyntaxWarning fires. Pre-flight any rename WP with `grep
> -rn` across `app/` AND `alembic/` before scoping. Encode numeric
> decision gates into perf-pass WP prompts. Do NOT reintroduce the
> `_v1_deferred.py` skip-hook — per-test deferral uses plain
> pytest markers.
