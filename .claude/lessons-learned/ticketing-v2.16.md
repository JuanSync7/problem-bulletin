# v2.16 ticketing — lessons learned

Companion to `ticketing-v2.15.md`. Each WP records (a) what shipped,
(b) the cost surface, (c) lessons that survive the WP, and (d)
deferred follow-ups feeding the v2.17 backlog.

v2.16 was the **cosmetic cleanup version**. v2.15 closed the last
identified structural-debt class (category-c silent-on-non-2xx) and
pinned the bare-catch lint regression net. With no structural debt
queued, v2.16 picked up the three Bucket-Z cosmetic items that had
been bundled at the foot of the v2.15 retrospective — `search_multi.py`
SyntaxWarning (Z1), React Router v7 future-flag warnings (Z2), and the
remaining 13 bare-catch allow-list entries (Z3) — plus the standard
baseline + closure WPs. Three small cleanup WPs in a single version;
nothing structural; the residue from v2.15's structural sweep is now
gone.

**Closing baselines:** backend **1430 → 1433 P / 0 F / 5 skipped /
14 xfailed** (+3, all from WP02's SyntaxWarning regression suite).
Frontend **256 → 260 P / 0 F** (+2 from WP03's RR future-flag
regression, +2 from WP04's SubmitCategoriesErrorEnvelope).

---

## v2.16-WP01 (G0) — baseline verify

Backend: **1430 P / 0 F / 5 skipped / 14 xfailed**. Frontend:
**256 P / 0 F**. Confirmed as the regression anchor for WP02+.

v2.15-WP04's OTel `InMemoryMetricReader` swap under
`PYTEST_CURRENT_TEST` held cleanly — zero `Connection refused`
matches against stderr, zero `I/O operation on closed file` matches.
The Bucket-Z items called out at the foot of the v2.15 retrospective
re-confirmed against a clean baseline:

- **`app/services/search_multi.py:119` SyntaxWarning** — still
  emitting `\)` invalid-escape warning at module import.
- **React Router v7 future-flag warnings** — still emitting
  `v7_startTransition` + `v7_relativeSplatPath` on every test render
  that mounts a Router.
- **13 remaining bare-catch entries** — still parked in the WP02
  allow-list, awaiting honest disposition.

No code or test changes in WP01.

---

## v2.16-WP02 (Z1) — SyntaxWarning fix + docstring escape audit

**Pre-state.** `app/services/search_multi.py:119` had a docstring
`"""Escape LIKE metacharacters (%, _, \) in user input..."""` whose
literal `\)` is not a recognised Python escape. Python emits
`SyntaxWarning: invalid escape sequence '\)'` at module import. On
Python 3.13+ this becomes the default behaviour; under `python -W
error::SyntaxWarning` it is already promoted to `SyntaxError` and
fails the import. Stderr noise on every test run that imports the
search-multi module.

**Fix shape.** `r`-string prefix on the `_escape_like` docstring:

```python
def _escape_like(value: str) -> str:
    r"""Escape LIKE metacharacters (%, _, \) in user input ..."""
```

Raw-string keeps the rendered docstring honest (`\)` in `__doc__`,
not `\\)`). Escape-only — zero behavioural change. `r"""..."""` is a
docstring in every way that `"""..."""` is; Sphinx and `help()` see
identical output. The alternative — `\\)` — was rejected because the
docstring is documenting LIKE metacharacters and a reader expects to
see `\)`, not the escaped form.

**Audit — was this the only offender?** The interesting question
was not "fix the one site" but "are there others?" The audit
primitive was a `pkgutil.walk_packages` sweep under
`warnings.simplefilter('error', SyntaxWarning)`:

```python
import warnings, pkgutil, importlib, app
warnings.simplefilter("error", SyntaxWarning)
for mod in pkgutil.walk_packages(app.__path__, prefix="app."):
    importlib.import_module(mod.name)
```

The walker covers EVERY submodule under `app/` including the
lazily-imported leaves that `import app` alone never reaches.
Critically, `app.services.search_multi` is one of those — `import
app` does not touch it, so a `python -W error -c "import app"`
check alone would have green-passed despite the offender. The
walker is what guarantees full coverage.

Post-fix, the walker returned zero offenders. This is the only
SyntaxWarning in `app/`.

**Regression test — `tests/test_no_syntax_warnings_wp02_v216.py`,
3 cases.**

1. `test_app_import_under_werror` — subprocess
   `python -W error::SyntaxWarning -c "import app"` exits 0. Catches
   any escape issue on the eager-import path.
2. `test_all_app_submodules_import_under_werror` — walks every
   submodule under `app.` via `pkgutil.walk_packages`, imports each,
   asserts no `SyntaxWarning` escapes. Filters genuine `ImportError`
   from optional-dep gaps but FAILS loud on any escape issue. This
   is the test that catches lazily-imported leaves.
3. `test_helper_catches_synthetic_bad_module` — self-test: writes
   `\)` into a tmp module, runs the same recipe, asserts the helper
   catches it. Guards against the regression test silently
   green-passing if the recipe itself regresses.

RED→GREEN verified before merge: pre-fix, case 2 reported three
failure chains (`app.main`, `app.routes.search`,
`app.services.search_multi`, all pointing at `search_multi.py:119`).
Post-fix, all 3 cases pass.

**Numbers.**

- Backend net delta: 1430 → **1433** (+3 — SyntaxWarning regression
  cases).
- Frontend untouched at 256.
- Files modified: `app/services/search_multi.py` (single docstring,
  `r` prefix).
- Files added: 1 test module + 1 diagnosis doc.

**Lessons surviving WP02.**

1. **`pkgutil.walk_packages` + `warnings.simplefilter('error', ...)`
   is the audit primitive for compile-time warnings.** Five lines
   of code cover every submodule under a package, including
   lazily-imported leaves that `import <pkg>` alone never reaches.
   `search_multi.py` is exactly such a leaf — it would have evaded a
   surface-level `import app` werror check. The pattern generalises
   to any warning class (DeprecationWarning, SyntaxWarning,
   PendingDeprecationWarning, ResourceWarning): walk imports under
   `-W error`, capture stderr, assert empty.
2. **Self-test the audit helper.** Case 3 writes a synthetic bad
   module and verifies the helper catches it. Without this, the
   audit could silently regress (e.g. a stderr-capture bug, an
   exception class change) and start green-passing on a broken
   recipe. Every meta-test should include a known-bad input that
   exercises the failure path.
3. **r-string > backslash-escape for docstrings documenting
   metacharacters.** When the docstring's subject IS the literal
   `\`-character (LIKE metacharacters, regex patterns, shell
   escapes), `r"""..."""` keeps the rendered docstring honest. The
   alternative (`\\)`) makes the help output read wrong to a human.

---

## v2.16-WP03 (Z2) — React Router v7 future-flag opt-in

**Pre-state.** React Router v6.23 emits forward-compat warnings on
every render that mounts a Router unless the consuming app opts into
the v7 behaviour change. Two flags were warning in this codebase:

- `v7_startTransition` — RR v7 will wrap internal state updates in
  `React.startTransition`.
- `v7_relativeSplatPath` — splat-route relative resolution changes.

`grep -ciE "v7_|future flag|React Router Future"` against vitest
stderr returned a non-zero count (many tens of repeats — once per
test-file render).

**RR API in use — fixed the scope.** The codebase uses
`<BrowserRouter>` (production, `frontend/src/App.tsx`) and
`<MemoryRouter>` (tests, 16 files). NO `createBrowserRouter` /
`RouterProvider` / data-router APIs. This matters because the other
four `v7_*` flags (`v7_fetcherPersist`, `v7_normalizeFormMethod`,
`v7_partialHydration`, `v7_skipActionErrorRevalidation`) only apply
to data routers — they never warned and don't need to be set. Only
the two non-data-router flags above are in scope.

**Path chosen — per-file `future={...}` opt-in.** The alternative
was a global `vi.mock("react-router-dom", ...)` shim in
`src/test/setup.ts` that auto-injects the future prop into every
`MemoryRouter`. Rejected because:

- A global mock obscures the source of truth — a reader of a test
  wouldn't see the flag and wouldn't know it's set.
- Risk of subtle drift between mocked and real router behaviour.
- The mechanical edit was small and 100% local — every call site
  literally shows the flags it opts into.

**Changes shipped.**

- `frontend/src/App.tsx` — added `future={{ v7_startTransition:
  true, v7_relativeSplatPath: true }}` to the single
  `<BrowserRouter>`.
- 16 test files — same `future` prop added to every `<MemoryRouter>`
  opening tag via a regex pass (existing props like `initialEntries`
  preserved).

**Forward-compat verification.** No test asserts on
`startTransition`-specific timing or splat-relative navigation
behaviour. All 256 prior tests passed unchanged after the opt-in —
confirming the v7 behaviour is behaviourally inert for THIS
codebase. This is not a general guarantee: any consumer that
depends on synchronous-navigation timing (e.g. a `useNavigate` call
followed immediately by reading the new URL synchronously) would
need to audit before flipping `v7_startTransition`. The diagnosis
records the audit-and-pass result for the v2.16 codebase
specifically.

**Regression test —
`frontend/src/__tests__/router_future_flags.test.tsx`, 2 cases.**

1. With `future={...}` set, neither `console.warn` nor
   `console.error` is called with any string matching
   `/v7_|future flag|React Router Future/i`.
2. Sanity check: without the `future` prop, the warning IS emitted.
   Proves the positive assertion isn't a no-op against an
   already-silent system.

**Numbers.**

- Frontend net delta: 256 → **258** (+2 regression cases).
- Backend untouched at 1433.
- Frontend warning count (`v7_|future flag|React Router Future`):
  many → **0**.
- `npm run build` exits 0 — production build unaffected.
- Files modified: `App.tsx` + 16 test files.
- Files added: 1 regression test + 1 diagnosis doc.

**Lessons surviving WP03.**

1. **Per-file opt-in beats global mock shims for forward-compat
   flags.** A global `vi.mock` would have been DRY but invisible;
   per-site config keeps the opt-in legible at every call site. The
   trade-off is LOC (17 call sites vs 1 setup file) for clarity —
   the clarity wins because mocks drift, explicit per-site config
   doesn't. Pattern: when a framework offers a forward-compat
   opt-in, plumb it through every call site explicitly even at LOC
   cost.
2. **Forward-compat flags are forgiving but not free.**
   `v7_startTransition`'s only behaviour change is wrapping internal
   navigation updates in `React.startTransition` — free if no
   component depends on synchronous-navigation timing. The diagnosis
   records WHY this was safe (no `useNavigate`-followed-by-sync-read
   in the codebase). Lesson: NOT all forward-compat flags are free.
   Audit the semantics before flipping, even when the framework
   advertises the opt-in as additive.
3. **Scope the flags by the API in use.** Four of the six `v7_*`
   flags are data-router-only (`createBrowserRouter` / loaders /
   actions). They never warned and didn't need to be set. Reading
   `console.warn` output is faster than reading the RR migration
   guide — let the warnings tell you which flags actually apply.

---

## v2.16-WP04 (Z3) — bare-catch allow-list shrink

**Pre-state.** v2.15-WP03 swept 23 of the original 36 bare-catch
sites, leaving 13 entries in
`frontend/src/pages/__tests__/catch_block_lint.test.ts`'s
`_OFFENDER_ALLOWLIST`. The WP02 lockstep test was happy (every live
offender allow-listed; every allow-list entry still live), but the
comments on each entry read like deferred TODOs ("pre-WP03; UX TBD")
rather than disposition decisions. Z3's job was to revisit the 13,
migrate where migration improved UX, and re-label survivors as
explicitly BY-DESIGN with a reader-friendly rationale.

**Stretch target was N ≤ 6.** The honest count was N = 9. The
diagnosis documents why each survivor would degrade UX if forced —
and the WP shipped at N = 9 rather than gaming the metric.

**The migrations — 3 sites.**

| File:line | Migration | Reasoning |
|---|---|---|
| `Submit.tsx:94` | `catch {}` → `catch (err) { toast.show(err.message) }` | categories fetch — failure is user-visible (selector missing); toast surfaces the envelope `message` |
| `Submit.tsx:105` | same pattern | domains fetch — same shape |
| `Kanban/TicketDetailDrawer.tsx:115` | `catch {}` → `catch (err) { setError(err.message) }` | `loadChildren` — the drawer already has an `error` state UI; the catch was bypassing it |

**The survivors — 9 sites, classified.**

Four genuine by-design buckets:

1. **Per-file/per-item aggregation loops** (`Submit.tsx:200`,
   `ProblemDetail.tsx:931`). The catch is intentionally silent
   because the outer caller aggregates per-iteration failures into
   a single user-facing list (`failedFiles[]` + outer toast).
   Promoting the inner catch to `setError(err.message)` would
   clobber the aggregated message on every iteration.
2. **localStorage helpers** (`Kanban/index.tsx:39`, `:46`).
   Environment-level failures (private mode, disabled storage,
   quota). The helper's contract is "return null / fall back to
   defaults"; surfacing a toast from a helper called during render
   would be noise.
3. **Pure parse/format helpers** (`Settings.tsx:40`, `:56`). `new
   Date(iso)` throws on malformed input; returning the raw ISO
   string is the idiomatic JS graceful-degradation pattern. No I/O,
   no envelope, nothing to thread.
4. **Best-effort optimistic / scanning sub-paths**
   (`Activity/MentionsTab.tsx:246` optimistic mark-as-read rollback,
   `ComponentDetail.tsx:53` per-project scan loop, `Search.tsx:354`
   categories filter enrichment). UI already communicates the
   failure mode (un-flipped row stays unread, missing state shown,
   empty filter dropdown), or the outer catch handles the
   user-visible error, or a 404 IS the empty-state.

The `Search.tsx:354` case is the most instructive: a 404 on
`/api/admin/categories` from a non-admin user is the EMPTY state,
not a bug. Migrating it to a toast would fire on every Search page
load for non-admins — degrading UX in service of a lint metric.

**Allow-list comment style — answer WHY, not WHERE.** All 9
surviving entries now start with `BY-DESIGN:` and include a one-line
rationale a future reader can grep / cite. The old comments said
"pre-WP03; UX TBD" — making every survivor look like a deferred
TODO. The new comments make clear these are intentional and explain
the reasoning. A future contributor hitting the lint can now
distinguish bug-rot (new offender) from intentional silent path
(allow-listed BY-DESIGN) without opening every file.

**Regression test —
`frontend/src/pages/__tests__/SubmitCategoriesErrorEnvelope.test.tsx`,
2 cases.**

1. `/api/admin/categories` throws → toast surfaces `err.message`
   from the envelope.
2. `/api/domains` throws → toast surfaces `err.message` from the
   envelope.

Both mock `useToast`, `useAuth`, `useAnonymousMode`, and the three
heavy components (RichEditor, TagAutocomplete, AttachmentDropZone)
to keep the test focused on the fetch error path.

**Numbers.**

- Frontend net delta: 258 → **260** (+2 SubmitCategoriesErrorEnvelope).
- Backend untouched at 1433.
- Allow-list: 13 → **9** (−4 — 3 migrated, 1 line-shift accounting
  under the re-labeled ProblemDetail entry).
- Files modified: `Submit.tsx`, `TicketDetailDrawer.tsx`,
  `catch_block_lint.test.ts` (allow-list comments rewritten).
- Files added: 1 regression test + 1 diagnosis doc.

**Lessons surviving WP04.**

1. **`BY-DESIGN:` comments belong in allow-lists, not on the
   offending line.** Promoting allow-list comments from "exists at
   this line" to "exists FOR THIS REASON" lets a future reader
   distinguish bug-rot from intentional silent paths without opening
   every file. Pattern: allow-list entries should answer WHY, not
   just WHERE. The shape is `BY-DESIGN: <one-line rationale>` — grep
   on `BY-DESIGN:` to enumerate all intentional exceptions.
2. **Honest classification beats stretch target.** N ≤ 6 was a
   stretch goal; the honest answer was N = 9. Migrating `Search:354`
   would have degraded UX (404 IS the empty state). Forcing the
   metric would have created a worse product. Pattern: when stretch
   targets are arbitrary numbers, give honest answers — the
   diagnosis doc is where you make the case for each survivor.
3. **Aggregation-loop catches are a recognisable class.** Per-file
   upload loops (Submit:200, ProblemDetail:931) share the shape:
   outer toast aggregates per-iteration failures via a `failedFiles`
   list; inner catch is silent. The pattern is general — any
   batch-API consumer over a per-item loop will look like this.
   Worth flagging the SHAPE in the allow-list so future readers can
   recognise it.

---

## v2.16-WP05 (closure) — retrospective + v2.17 seed

This document. Zero code touched.

---

## v2.16 retrospective

### Headline numbers

- **Backend baseline:** 1430 P / 0 F / 5 skipped / 14 xfailed
  (v2.15 close).
- **Backend final:** **1433 P / 0 F / 5 skipped / 14 xfailed**.
- **Net delta:** +3 backend (WP02 SyntaxWarning regression suite).
- **Frontend baseline:** 256 P / 0 F (v2.15 close).
- **Frontend final:** **260 P / 0 F**.
- **Net delta:** +4 frontend (WP03 +2 RR future-flag, WP04 +2
  SubmitCategoriesErrorEnvelope).
- **Bare-catch allow-list:** 13 → **9** (−4; 3 migrated, 1 re-labeled
  BY-DESIGN with line shift accounted).
- **SyntaxWarning offenders in `app/`:** 1 → **0**.
- **RR future-flag warnings (vitest stderr):** many → **0**.
- **Production bugs caught and fixed:** zero. All three WPs were
  cosmetic — no behavioural surface touched.
- **Production regressions introduced:** zero. Every WP held the
  green-suite invariant.

### WPs shipped

| WP | Bucket | Summary | Test delta |
|---|---|---|---|
| WP01 | G0 | Baseline verify (1430 P backend / 256 P frontend). v2.15-WP04 OTel fix re-confirmed clean. Bucket-Z items re-confirmed. | ±0 |
| WP02 | Z1 | `search_multi.py:119` `_escape_like` docstring `r`-prefix. `pkgutil.walk_packages` + `warnings.simplefilter('error', SyntaxWarning)` audit confirmed exactly one offender in `app/`. 3 regression cases (eager-import werror, walk_packages submodule sweep, synthetic-bad self-test). | +3 (1430→1433 backend) |
| WP03 | Z2 | RR v7 future-flag opt-in via per-file `future={...}` on `<BrowserRouter>` (prod) + `<MemoryRouter>` (16 test files). Only `v7_startTransition` + `v7_relativeSplatPath` were warning; the other 4 v7_* flags are data-router-only. Global vi.mock shim considered + rejected. 2 regression cases (positive + sanity-check without). | +2 (256→258 frontend) |
| WP04 | Z3 | Bare-catch allow-list 13 → 9. 3 migrated (Submit:94 categories, Submit:105 domains, TicketDetailDrawer:115 loadChildren). 9 kept with `BY-DESIGN:` rationale comments. Honest N=9 vs stretch N≤6 — Search:354 would have degraded UX. 2 SubmitCategoriesErrorEnvelope regression cases. | +2 (258→260 frontend) |
| WP05 | closure | Retrospective + v2.17 seed (this doc). | ±0 |

### Cross-cutting lessons

1. **`pkgutil.walk_packages` + `warnings.simplefilter('error', ...)`
   is the audit primitive for compile-time warnings.** WP02 covered
   the entire `app/` package surface with one helper. `import app`
   alone never reaches lazily-imported leaves like
   `app.services.search_multi` — the walker is what guarantees full
   coverage. The pattern generalises to any warning class
   (DeprecationWarning, SyntaxWarning, PendingDeprecationWarning,
   ResourceWarning): walk imports under `-W error`, capture stderr,
   assert empty. Five lines of code, full-surface coverage.

2. **Per-file opt-in beats global mock shims for forward-compat
   flags.** WP03 considered a global `vi.mock("react-router-dom",
   ...)` shim in `setup.ts` but rejected — call-site visibility
   outweighs the DRY appeal. A reader of a single test should see
   exactly which flags are set without grepping the test
   infrastructure. Mocks drift; explicit per-site config doesn't.
   Pattern: when a framework offers a forward-compat opt-in, plumb
   it through every call site explicitly even at LOC cost.

3. **`BY-DESIGN:` comments belong in allow-lists, not on the
   offending line.** WP04 promoted lint allow-list comments from
   "exists at this line" to "exists FOR THIS REASON". A future
   reader hitting the lint can now distinguish bug-rot (new
   offender) from intentional silent paths (allow-listed
   `BY-DESIGN`) without opening every file. Pattern: allow-list
   entries should answer WHY, not just WHERE. Grep on `BY-DESIGN:`
   enumerates intentional exceptions; everything else is a real
   regression.

4. **Honest classification beats stretch target.** WP04 was given
   N ≤ 6 as a stretch goal; the honest answer was N = 9. Migrating
   `Search:354`'s best-effort categories enrichment would have
   degraded UX — a 404 on `/api/admin/categories` from a non-admin
   user is the EMPTY state, not a bug, and a toast would fire on
   every Search page load for non-admins. Forcing the metric would
   have created a worse product. Pattern: when stretch targets are
   arbitrary numbers, give honest answers — the diagnosis doc is
   where you make the case for each survivor.

5. **Forward-compat flags are forgiving but not free.** RR's
   `v7_startTransition` opt-in took one codebase-level decision
   (wrap navigation updates in `React.startTransition`); we got it
   free because no component depends on synchronous-navigation
   timing. The diagnosis records WHY this was safe (no `useNavigate`
   -followed-by-sync-read in the codebase). Lesson: NOT all
   forward-compat flags are free. Audit the semantics — particularly
   any timing/synchrony assumptions — before flipping, even when the
   framework advertises the opt-in as additive. Use the warning
   output itself to scope: flags that aren't warning don't need
   setting.

6. **Three Bucket-Z items shipped in one version is the soft
   ceiling.** v2.16 bundled three cosmetic WPs (SyntaxWarning + RR
   future-flag + bare-catch shrink) successfully. Adding a fourth
   would have stretched the version — the closure retrospective
   itself would start to drag (cross-cutting lessons repeating
   themselves, "what stayed deferred" growing harder to enumerate
   honestly). Pattern: cosmetic cleanups batch well in pairs and
   threes, but past three the version starts to lose narrative
   cohesion. If a fourth cosmetic surfaces, defer it to the next
   cosmetic cycle.

7. **Cosmetic version closes structural-debt residue.** v2.15
   closed the structural class (category-c bug class); v2.16's job
   was the residue (compile-time SyntaxWarning, framework-deprecation
   warnings, allow-list honesty). The pattern is sequential: after
   a structural-debt version, schedule a cosmetic version to mop up
   compile-time/test-time noise BEFORE opening new initiatives. The
   payoff is a noise-free baseline for the next version — every new
   warning is a real signal, not background hum. v2.17 starts on
   the cleanest baseline since v2.10.

### What stayed deferred (carry to v2.17)

- **Bucket A (C7, E3, E4, F3)** — still conditional v2.11
  carry-forwards (`decode_email_body` helper, KindPill 7th surface,
  `useSearchV2` ergonomic follow-ups, TipTap second-consumer
  extraction). No triggering need fired in v2.16.
- **B1 — per-arm `refresh_total` opt-in syntax** — still
  conditional. Wire-shape change only (`refresh_total: boolean |
  string[]`); pick up only on a real user need.
- **B2 — WP05 OpenAPI↔TS parser expansion** — nested generics,
  intersection types, multi-param generics, generic type aliases,
  mapped/conditional, default generic params. Parser-rejected with
  explicit self-tests; pick up when the first
  `frontend/src/api/*.ts` consumer needs one.
- **9 by-design bare-catch entries** — PERMANENTLY documented in
  WP04 with `BY-DESIGN:` rationale per entry. NOT a carry-forward
  (they will not be re-evaluated) — but the comment-style rule
  (`BY-DESIGN:` answers WHY) IS a forward-pointing rule for any
  future allow-list.
- **With cosmetic residue cleared, v2.17 has zero scoped backlog.**
  Truly user-driven from this point — opportunistic Bucket-A/B
  carry-forwards if a triggering need surfaces, OR new product
  surface (whatever the user brings).

### Files touched (rough stats)

- **Production code (`app/`):**
  - 1 file: `app/services/search_multi.py` (WP02 — `r`-prefix on
    one docstring, escape-only).
- **Alembic (`alembic/versions/`):** 0 files.
- **Test code (`tests/`):**
  - 1 new file: `tests/test_no_syntax_warnings_wp02_v216.py` (WP02,
    3 cases).
- **Frontend (`frontend/`):**
  - 3 pages modified (WP04): `Submit.tsx` (2 catch migrations +
    cancelled-flag honoured), `Kanban/TicketDetailDrawer.tsx`
    (loadChildren catch migration).
  - 1 file modified (WP03): `App.tsx` (BrowserRouter `future` prop).
  - 16 test files modified (WP03): `<MemoryRouter>` `future` prop
    added mechanically.
  - 1 test file modified (WP04): `catch_block_lint.test.ts`
    (allow-list shrink + `BY-DESIGN:` rewrites).
  - 2 new test files:
    `frontend/src/__tests__/router_future_flags.test.tsx` (WP03, 2
    cases), `frontend/src/pages/__tests__/SubmitCategoriesErrorEnvelope.test.tsx`
    (WP04, 2 cases).
- **Docs (`.claude/lessons-learned/`):** 3 per-WP diagnosis files
  (`v2.16-wp02-diagnosis.md`, `v2.16-wp03-diagnosis.md`,
  `v2.16-wp04-diagnosis.md`) + this retrospective.

---

## v2.17 starting prompt seed

v2.16 closed the three Bucket-Z cosmetic items carried forward from
v2.15 (Z1 SyntaxWarning, Z2 RR v7 future-flag warnings, Z3
bare-catch allow-list shrink). v2.15 had already closed the last
identified structural-debt class (category-c silent-on-non-2xx). With
both the structural class AND the cosmetic residue cleared, **v2.17
has zero scoped backlog**. Bucket A items (C7, E3, E4, F3 — v2.11
carry-forwards) and Bucket B items (B1 per-arm `refresh_total`, B2
WP05 parser expansion) remain conditional — act only on triggering
second-consumer need.

v2.17 is opportunistic-only from the start: act on Bucket A/B
triggers if they surface, OR new product surface (user-driven).

### v2.17 backlog

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

### v2.17 prompt seed (paste-ready)

> Proceed with v2.17 of the problem-bulletin ticketing system.
> v2.16 retrospective + carry-forward backlog live at the bottom of
> `.claude/lessons-learned/ticketing-v2.16.md`. Baselines: backend
> **1433 P / 0 F / 5 skipped / 14 xfailed**, frontend **260 P / 0
> F**. Bucket A items (C7, E3, E4, F3) are conditional carry-
> forwards from v2.11 — act ONLY on a triggering second-consumer
> need. Bucket B items (B1 per-arm refresh_total opt-in, B2 WP05
> parser expansion) are conditional carry-forwards from v2.13 —
> same rule. **v2.16 was the cosmetic cleanup version; v2.15 closed
> the last identified structural-debt class. v2.17 has zero scoped
> backlog — opportunistic only (Bucket A/B if a triggering consumer
> surfaces) or user-driven new product surface.** Cosmetic residue
> is cleared: SyntaxWarning offenders in `app/` are at 0, RR v7
> future-flag warnings in vitest stderr are at 0, bare-catch
> allow-list has 9 permanently-documented `BY-DESIGN:` survivors
> (not a carry-forward — they will not be re-evaluated unless the
> file is touched for product reasons). Follow the sequential
> subagent loop pattern, TDD-first, one diagnosis doc per WP under
> `.claude/lessons-learned/v2.17-wpNN-diagnosis.md`. Append lessons
> to `.claude/lessons-learned/ticketing-v2.17.md`. **Forward rules
> carried from v2.15:** (a) lint-before-sweep when a class has
> known shape; (b) by-design enumeration at FIRST surfacing of any
> mixed-population class; (c) two state slots for pages with both
> load-failure and action-failure UX; (d) `PYTEST_CURRENT_TEST` is
> the canonical no-config test-mode sentinel — prefer over
> inventing a project-local flag; (e) audit metric exporters first
> when OTel noise surfaces. **Forward rules new from v2.16:** (f)
> `pkgutil.walk_packages` + `warnings.simplefilter('error', ...)`
> is the audit primitive for any compile-time warning class — walk
> imports under `-W error`, assert empty; covers lazily-imported
> leaves that `import <pkg>` alone misses; (g) per-file opt-in
> beats global mock shims for forward-compat flags — call-site
> visibility outweighs the DRY appeal, mocks drift; (h) `BY-DESIGN:`
> comments in allow-lists answer WHY, not WHERE — grep on
> `BY-DESIGN:` enumerates intentional exceptions, everything else
> is a real regression; (i) honest classification beats stretch
> target — when the metric forces UX degradation, ship the honest
> number and make the case in the diagnosis; (j) forward-compat
> flags are forgiving but not free — audit semantics (particularly
> timing/synchrony) before flipping; use warning output itself to
> scope; (k) three Bucket-Z items is the soft ceiling per cosmetic
> version — past three the closure retrospective drags; (l) after
> a structural-debt version, schedule a cosmetic version to mop up
> compile-time/test-time noise before opening new initiatives.
> Pre-flight any rename WP with `grep -rn` across `app/` AND
> `alembic/` before scoping. Encode numeric decision gates into
> perf-pass WP prompts. Do NOT reintroduce the `_v1_deferred.py`
> skip-hook — per-test deferral uses plain pytest markers.
