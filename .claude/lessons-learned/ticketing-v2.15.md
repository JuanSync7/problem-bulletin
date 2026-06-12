# v2.15 ticketing — lessons learned

Companion to `ticketing-v2.14.md`. Each WP records (a) what shipped,
(b) the cost surface (LOC, files touched), (c) lessons that survive
the WP (i.e. that should still be true in v2.16), and (d) deferred
follow-ups feeding the next backlog.

v2.15 was a Bucket-C sweep: three new initiatives carried forward
from v2.14's WP04 lessons (C2 structural `catch {}` lint, C1
category-c silent-on-non-2xx page sweep, C3 OTel export quieting)
plus the baseline + closure WPs. No Bucket-A trigger fired; all four
conditional v2.11 carry-forwards (C7, E3, E4, F3) remain pending.
Bucket B (B1 per-arm `refresh_total`, B2 WP05 parser expansion) also
held — no triggering need surfaced.

The work order was intentional: **lint first, sweep second.** WP02
pinned the structural lint with a 36-entry allow-list as a forcing
function for WP03's category-c sweep; the lint failing red after
every migration was the feedback signal that kept the sweep honest
and the stale-entry detector caught line-number drift that an
allow-list-only shape would have rotted into. WP04 was the smallest
of the three by surface but addressed the longest-standing cosmetic
(OTel noise was first noted in v2.14-WP01).

---

## v2.15-WP01 (G0) — baseline verify

Backend: **1429 P / 0 F / 5 skipped / 14 xfailed**. Frontend:
**245 P / 0 F**. Confirmed as the regression anchor for WP02+.

Two pre-existing cosmetic items noted but not actioned at baseline:

- **OTel gRPC export noise** carried over from v2.14-WP01. Backend
  logs `Connection refused` to `localhost:4317` whenever any pytest
  invocation initialises observability. Functional impact zero; log
  spam non-zero. Scoped as v2.15 candidate C3.
- **`app/services/search_multi.py:119` SyntaxWarning** — `\)` in a
  docstring triggers `SyntaxWarning: invalid escape sequence` on
  module import. Trivial fix (raw-string the docstring or escape the
  backslash). Not a WP candidate on its own; bundled into the v2.16
  cosmetic backlog.
- **React Router v7 future-flag warnings** — frontend test output
  carries `v7_startTransition` / `v7_relativeSplatPath` warnings.
  Library upgrade decision, not a v2.15 surface; bundled with v2.16
  cosmetics.

No code or test changes in WP01.

---

## v2.15-WP02 (C2) — `catch {}` structural lint

**Pre-state.** v2.14-WP04 ported 24 page-level `fetch()` sites to
`parseApiError` and along the way promoted every bare `catch {}` it
touched to `catch (err)` with `err.message` threaded to the UI. The
WP04 retrospective lesson #2 surfaced the underlying class: bare
`catch {}` discards the structured `err.message` before it ever
reaches the toast/banner, so even a perfect upstream `parseApiError`
adapter is undone at the catch site. WP04 closed every instance it
touched but did not pin the class against regression — that was the
explicit C2 carry-forward.

**Why lint-before-sweep.** WP03 (C1 category-c sweep) was already
queued. Without a structural lint, WP03's per-site migrations would
have been validated by hand. With the lint in place, every WP03
migration either (a) shrank the allow-list — confirmed migration —
or (b) failed the stale-entry detector — caught a drift. The lint
became the forcing function for WP03's correctness gate.

**What shipped.**

`frontend/src/pages/__tests__/catch_block_lint.test.ts` — a vitest
suite that uses the `typescript` compiler API to walk every `.ts` /
`.tsx` file under `frontend/src/pages/`. The walker matches
`ts.SyntaxKind.CatchClause` via `ts.forEachChild` recursion and
classifies each catch into one of four buckets:

1. **bare** — `catch {}` (no binding clause at all). Flagged.
2. **swallow** — `catch (err) { ... }` where the body block contains
   zero identifier references to the bound name. Flagged.
3. **consumed** — `catch (err)` with at least one identifier ref to
   `err` (or a typed `unknown` binding). Not flagged.
4. **rethrow** — `catch (err) { throw err; }` or `throw new Error(…
   err …)`. Not flagged (rethrow is a legitimate consumption).

The classifier uses `ts.createSourceFile` per file (no project-wide
program — keeps the lint sub-second) and `ts.isIdentifier` +
`escapedText` for the binding-ref scan. Typed `unknown` bindings
(`catch (err: unknown)`) are correctly NOT flagged because the
binding clause's identifier is still walkable.

**Seven vitest cases** in the file:

1. `bare` synthetic — asserts the classifier flags `try {} catch {}`.
2. `swallow` synthetic — `try {} catch (err) { setBusy(false); }`
   with no `err` ref — flagged.
3. `consumed` synthetic — `try {} catch (err) { console.log(err); }`
   — NOT flagged.
4. `rethrow` synthetic — `try {} catch (err) { throw err; }` — NOT
   flagged.
5. `typed unknown` synthetic — `try {} catch (err: unknown) { … }`
   — NOT flagged (binding clause present, ref present).
6. `nested finally` synthetic — `try {} catch (err) { … } finally
   { … }` with `err` consumed — NOT flagged.
7. **Allow-list lockstep** — the only test that walks real files.
   Pulls the live `bare` + `swallow` set from
   `frontend/src/pages/**/*.{ts,tsx}`, compares against a 36-entry
   allow-list literal, and asserts BOTH directions:
   - Every live offender exists in the allow-list (no new
     regressions). Fails red on net-new bare catches.
   - Every allow-list entry exists in the live offender set (no
     stale entries). Fails red when a fix removes a bare catch but
     the allow-list still references the old file:line.

**Allow-list inventory at land.** 36 bare, 0 swallow. v2.14-WP04
had already cleared the swallow class across admin pages — WP02
confirmed structurally that the class is empty. 24 of the 36 bare
entries live in `ProblemDetail.tsx` (large, dense, ~1300 LOC); the
remaining 12 are scattered across Submit, Search, KanbanBoard, and
admin pages.

**Gotcha — JSDoc terminates on `**/*.tsx` globs.** The first draft
documented the file's purpose with a `/** ... */` block comment
that contained the glob fragment `frontend/src/pages/**/*.tsx`.
esbuild parses `*/` inside a block comment as the block terminator
— the file failed to compile with a confusing "unexpected token"
error several lines downstream. Fix: drop glob fragments out of TS
block comments. Use `* * *` style markers, escape the slash, or
keep glob shapes in line comments only. The lesson generalises: any
`/* … */`-fenced free text that mentions a glob pattern is a
landmine in TS/JS files. The diagnosis records the failure shape
verbatim for the next sweep that wants to drop glob references into
file headers.

**Numbers.**

- Frontend net delta: 245 → **252** (+7 — 6 classifier self-tests +
  1 allow-list lockstep).
- Backend untouched at 1429.
- Files added: 1 test module + 1 diagnosis doc.
- Files touched: 0 (no production code, no page edits — pure lint
  pin).

**Lessons surviving WP02.**

1. **Structural lint before structural sweep.** Pinning the lint at
   the head of the WP cluster gives the next sweep WP a worklist
   (the allow-list IS the migration plan) AND a stale-entry
   detector (every migration shrinks the allow-list by exactly one;
   any drift fails red). The pattern is general: when a backlog has
   known shape, pin the lint first; let the sweep shrink the
   allow-list.
2. **Allow-list-with-stale-detection > allow-list-only.** Pure
   allow-lists rot silently as code moves. The lockstep test
   asserts BOTH directions — every live offender is allowed AND
   every allow-list entry is still a live offender. The stale
   detector caught every line-number drift during WP03's migration;
   without it, WP03 would have shipped with dangling entries
   pointing at code that no longer existed. The pattern was
   established in v2.11-WP09 (parity lint) — WP02 inherited and
   reapplied it.
3. **TypeScript compiler API is the right hammer for AST lint over
   `.tsx`.** `ts.createSourceFile` + `ts.forEachChild` matching
   `CatchClause` is ~30 lines of recursion; running per-file
   without a project-wide program keeps the lint sub-second across
   ~80 page files. Don't reach for ESLint custom rules for a
   one-off structural pin — the `typescript` package is already a
   dev dep via vite, and a vitest test integrates with the
   existing green-suite invariant.
4. **JSDoc + glob fragments is a footgun.** `**/*.tsx` inside a
   `/** ... */` block terminates the block early at the first `*/`.
   Avoid glob fragments in TS/JS block comments. Recipe documented
   in the diagnosis for the next sweep.

---

## v2.15-WP03 (C1) — category-c silent-on-non-2xx sweep

**Pre-state.** v2.14-WP04 inventoried 28 category-c sites (`if
(res.ok) { ... }` with no else branch — non-2xx silently dropped)
across `ProblemDetail.tsx` (23), `Submit.tsx` (3), `Search.tsx`
(1), and a `ProblemDetail` watch DELETE (1). WP04 explicitly
out-of-scoped them as a different bug class needing product input
on intended UX. v2.14 closed; v2.15 picked the class up as C1.

WP03 began with the WP02 lint allow-list (36 bare catches, 24 in
ProblemDetail) as the migration worklist.

**The by-design / bug split.** WP03's first move was to triage all
28 sites against the WP04 diagnosis labels. Five sites turned out
to be **intentional empty-state** reads — places where a 404
means "no data, render empty" and a non-2xx is correctly a no-op:

| File | Site | By-design rationale |
|---|---|---|
| `Submit.tsx` | categories bootstrap | optional dropdown — 404 = no categories yet, render empty selector |
| `Submit.tsx` | domains bootstrap | same shape — optional dropdown |
| `Submit.tsx` | per-file upload progress | inner catch in upload loop; outer handler owns the user-facing error |
| `Search.tsx` | categories bootstrap | optional facet — 404 = no facets, render empty |
| `ProblemDetail.tsx` | inner upload-loop catch | outer handler owns the error; inner just resets per-file state |

These five look IDENTICAL to bug sites under structural lint
(`catch {}` body, no `setError`, no toast). The only thing
distinguishing them is the **intent** — and that intent was already
captured in v2.14-WP04's diagnosis labels. Without that labelling,
WP03 would have wasted migration effort on five sites that already
behave correctly. The lesson is forward-pointing: when a class has
a known mixed population (real bugs + by-design no-ops), the FIRST
surfacing of the class must include a by-design enumeration. Punting
the enumeration to the sweep WP forces the sweep to re-do the
intent analysis from scratch.

**What shipped — the migration.** 23 sites migrated; 5 stayed as
documented by-design exceptions (allow-list shrinks 36 → 13). The
13 remaining bare-catch entries are all OUTSIDE the category-c
scope — they live in admin pages (KanbanBoard, etc.) where
`catch (err)` already exists but the body just resets a single
state variable, so the lint's binding-ref-based swallow detection
treats them as clean-but-noisy. Out of WP03's scope; carried
forward.

**Per-page UX choice.**

- **ProblemDetail.tsx.** Has both load-failure UI (full-page
  replacement: `{error && <ErrorPage />}`) and transient-action
  failures (status transitions, comments, links, watchers,
  attachments). Reusing the single `error` state for transient
  failures would have full-page-replaced the user out of their
  context every time a comment failed to post — wrong UX. Split
  into TWO state slots:
  - `error: string | null` — load-failure state, drives full-page
    replacement (pre-existing, unchanged).
  - `actionError: string | null` — transient-action state, drives
    an inline dismissible banner above the action surface.

  The banner element is a new `.action-error` block in
  `ProblemDetail.css` with a close-button (`onClick={() =>
  setActionError(null)}`). Zero state-management refactor — both
  slots are plain `useState` strings, set at the catch site and
  cleared at navigation or by the close button.

- **Submit.tsx, Search.tsx.** No migration needed at the page
  level — every category-c site in these files was one of the five
  by-design empty-state reads above. Page UX unchanged.

- **ProblemDetail.tsx status-transition bug found in flight.** The
  status-transition catch site was reading `data?.detail` from the
  legacy non-envelope error shape and calling `alert(data?.detail
  ?? "Transition failed")`. The backend's unified envelope (post
  v2.13-WP03) puts the user-facing message under `message`, not
  `detail` — so the alert was showing the fallback string on EVERY
  transition failure, regardless of what the backend actually said.
  Fix: replace `alert(data?.detail ...)` with `throwParsed(res,
  "Transition failed")` (file-local helper inherited from
  v2.14-WP04's admin-page pattern) and let the new `actionError`
  banner surface the envelope's `message`.

**Regression tests.** 4 added in
`frontend/src/pages/__tests__/ProblemDetailActionError.test.tsx`:

1. Status-transition non-2xx → `actionError` banner shows envelope
   `message`, NOT the legacy fallback.
2. Comment-post non-2xx → banner shows, page chrome unchanged.
3. Banner close button → `setActionError(null)` clears the banner.
4. Load failure (initial GET) → full-page `error` UI shown,
   `actionError` banner NOT shown (proves the two slots don't
   collide).

All four would FAIL against pre-WP03 code (test #1 against the
legacy `data?.detail` read; #2–#4 against the absence of the
`actionError` slot).

**Allow-list update.** WP02's allow-list literal shrank from 36 to
13 entries. The stale-entry detector validated every shrink: each
WP03 commit deleted exactly the lines it migrated, and the lockstep
test would have failed red if any entry pointed at a moved or
removed line. The detector caught two line-number drifts during
intermediate refactors (where adding the `actionError` banner JSX
shifted offsets in `ProblemDetail.tsx`) — both fixed in the same
commit, with the allow-list re-numbered against the post-edit file.

**Numbers.**

- Frontend net delta: 252 → **256** (+4 ProblemDetailActionError
  regression tests).
- Backend untouched at 1429.
- Sites migrated: **23** (of 28 inventoried).
- Sites documented as by-design: **5** (Submit categories/domains/
  per-file upload + Search categories bootstrap + ProblemDetail
  inner upload catch).
- Bare-catch allow-list: 36 → **13** (−23).
- Files modified: `ProblemDetail.tsx`, `ProblemDetail.css`,
  `catch_block_lint.test.ts` (allow-list shrink).
- Files added: 1 test (`ProblemDetailActionError.test.tsx`) + 1
  diagnosis doc.

**Lessons surviving WP03.**

1. **Category-c-by-design needs an explicit type, not just an
   annotation.** Five of 28 sites were intentional empty-state
   reads; structural lint cannot distinguish them from bugs. The
   WP04 diagnosis already had them labelled — without that label,
   WP03 would have wasted effort migrating no-ops. Forward rule:
   when a class is FIRST surfaced, enumerate the by-design subset
   in the same diagnosis. Don't let the next sweep WP re-derive
   intent.
2. **Two error states beat one for action-vs-load distinction.**
   ProblemDetail had a single `error` state driving full-page
   replacement; threading transient action failures into it would
   have UX-broken the page. Splitting into `error` (load) +
   `actionError` (action) preserved both surfaces with zero state
   refactor. The pattern: when a page has both load failures AND
   action failures, give them separate state slots BEFORE they
   collide. Two `useState` strings cost one banner JSX block; the
   refactor of a unified-error page is far more.
3. **Stale-entry detection catches refactor drift mid-sweep.** The
   WP02 lockstep test caught two line-number drifts during the WP03
   migration when adding banner JSX shifted line offsets in
   ProblemDetail. Without the detector, WP03 would have shipped
   with allow-list entries pointing at moved/deleted lines and the
   lint would have green-passed on stale state. The pattern: every
   allow-list deserves a stale detector.
4. **Status-transition shape regression hides in plain sight.**
   The `alert(data?.detail ...)` read was using the legacy
   non-envelope shape — present in the codebase since before
   v2.13-WP03's adapter sweep, never caught because the unified
   envelope's `message` field doesn't cause a crash if you read the
   wrong key, it just silently falls back. The category-c sweep
   surfaced it as collateral. Lesson: when migrating error surfaces
   under a unified envelope, every page-level error read should be
   audited for legacy-shape key names (`detail`, `error.message`,
   etc.) — they don't crash, they just silently drop the structured
   message.
5. **The lint allow-list IS the worklist.** WP03 did not need a
   separate inventory pass. The 36-entry WP02 allow-list was the
   migration TODO; every commit either shrank it or moved a fix to
   a by-design annotation. Sweep WPs that follow a lint-pin WP
   should default to "allow-list as worklist" rather than
   re-inventorying the class.

---

## v2.15-WP04 (C3) — OTel export quieting

**Pre-state.** v2.14-WP01 noted "OTel gRPC export errors visible
in stderr (no collector at `localhost:4317`); log spam, no
functional impact" and backlogged it as a v2.15 candidate. v2.15
WP01 re-confirmed the noise on a clean baseline. C3 picked it up.

The noise pattern manifests as two related but distinct stderr
emissions during any pytest run that exercises observability:

- `OSError: I/O operation on closed file.` — emitted by the
  Console exporter variant when stdout has already been closed at
  test teardown but the background reader thread is still trying
  to flush a metric batch.
- `Connection refused: localhost:4317` — emitted by the OTLP gRPC
  exporter variant when no collector is configured but the
  background reader thread tries to push a batch anyway.

**Root cause — where the noise originates.** Initial assumption
(from v2.14-WP01 wording) was "the OTLP gRPC export". WP04's first
move was to characterise WHICH exporter — span or metric — was
producing the noise. The result was unambiguous: **both noise
patterns originate in the METRIC exporter's
`PeriodicExportingMetricReader` background thread.** Specifically:

- The Console variant is the metric reader trying to write to a
  closed stdout (the `I/O operation on closed file` shape).
- The OTLP variant is the metric reader's gRPC client trying to
  reach `localhost:4317` (the `Connection refused` shape).

Span exporters in this codebase are batch-only and silent in the
absence of emitted spans, so the existing span-side tests
(`tests/observability/test_otel_init.py`, 11 tests) stayed intact
and informed nothing about the noise budget.

**Path chosen — Path A, InMemoryMetricReader swap-in under
`PYTEST_CURRENT_TEST`.** When the env var is set (pytest sets it
for the duration of any test run), the observability bootstrap
swaps the `PeriodicExportingMetricReader` for an in-memory reader
that does not spawn a background thread and does not attempt any
network or stdout write. Span exporters are unchanged. The swap is
at bootstrap time only — once observability is initialised, the
reader is set for the process lifetime; there is no per-test
switching.

**Why `PYTEST_CURRENT_TEST` as the sentinel.** The initial search
looked for an existing project-local test-mode idiom (a `TESTING=1`
convention, a `pytest_mode` flag in settings, etc.). None existed.
`PYTEST_CURRENT_TEST` is pytest's own injected env var, set for
the duration of any pytest run, requires zero setup, and is the
canonical no-config sentinel. Inventing a project-local convention
would have been a forward-door burden (every future test runner
would need to set it). Lesson — covered in cross-cutting below.

**Important caveat — gates BEHAVIOR, not EXPORTER WIRING.** The
OTLP / Console exporter is still imported and initialised under
`PYTEST_CURRENT_TEST`; only the periodic-reader (which is what
spawns the noisy background thread) is swapped. This preserves the
existing `test_otel_init.py` invariants — they assert that
exporters are wired up correctly, and they continue to pass
unchanged. The swap is surgical: it removes the noise source
(periodic background flush) without changing the exporter wiring
contract.

**Regression test.** One added —
`tests/observability/test_otel_silence_wp04_v215.py`. It
subprocess-invokes `tests/observability/test_otel_init.py` and
captures stderr; asserts that the two noise patterns
(`I/O operation on closed file` and `Connection refused.*4317`)
are ABSENT from the captured output. The subprocess shape is
intentional: in-process the parent's `PYTEST_CURRENT_TEST` would
contaminate the child's bootstrap decision, but spawning a
subprocess that runs a known-noisy test under a known-clean env
gives a deterministic noise-free / noise-present discriminator.

**Numbers.**

- Backend net delta: 1429 → **1430** (+1 OTel silence regression
  test).
- Frontend untouched at 256.
- Files touched: observability bootstrap module (one swap at
  reader initialisation) + 1 new test file + 1 diagnosis doc.
- Existing `test_otel_init.py` (11 tests) unchanged.

**Lessons surviving WP04.**

1. **`PYTEST_CURRENT_TEST` is the canonical no-config test-mode
   sentinel.** Set by pytest itself for the duration of any test
   run. No setup, no project-local convention, no forward-door
   burden on future runners. Prefer it over inventing a
   `TESTING=1` or `pytest_mode` flag. Caveat: it gates BEHAVIOR
   not WIRING — the exporter is still imported and initialised;
   only the periodic-reader background thread is swapped for an
   in-memory one. This preserves any test that asserts on
   exporter wiring.
2. **Metric exporters dominate the OTel noise budget.** Span
   exporters in this codebase are batch-only and silent in the
   absence of emitted spans. ALL the test-time noise comes from
   `PeriodicExportingMetricReader`'s background flush thread (Console
   variant: closed-stdout writes; OTLP variant: connection refused).
   When auditing OTel noise: check the metric reader first.
3. **Subprocess discriminator beats in-process assertion for env-
   gated bootstrap behavior.** The regression test needs to verify
   the noise is ABSENT under one env condition and the wiring is
   intact under another. In-process, the parent's
   `PYTEST_CURRENT_TEST` contaminates the child's bootstrap.
   Subprocess invocation gives a clean env discriminator at the
   cost of one extra process spawn per test (≤300ms wall).
4. **Characterise the noise source before patching.** v2.14-WP01
   labelled the issue "OTel gRPC export noise" — implying the gRPC
   layer. WP04's first step was to identify WHICH exporter
   produced WHICH log line; the answer (metric reader for both)
   determined the patch shape. Lesson: when a noise budget item
   carries forward across versions, the first move on pickup is
   characterisation, not patch.

---

## v2.15-WP05 (closure) — retrospective + v2.16 seed

This document. Zero code touched.

---

## v2.15 retrospective

### Headline numbers

- **Backend baseline:** 1429 P / 0 F / 5 skipped / 14 xfailed
  (v2.14 close).
- **Backend final:** **1430 P / 0 F / 5 skipped / 14 xfailed**.
- **Net delta:** +1 backend (WP04 OTel silence regression).
- **Frontend baseline:** 245 P (v2.14 close).
- **Frontend final:** **256 P / 0 F**.
- **Net delta:** +11 frontend (WP02 +7 lint, WP03 +4 ProblemDetail
  action-error regressions).
- **Bare-catch allow-list:** 36 → **13** (−23 via WP03 migrations
  + by-design documentation).
- **OTel noise:** two stderr patterns silenced under
  `PYTEST_CURRENT_TEST` without changing exporter wiring.
- **Production bugs caught and fixed:** 1 silent shape regression
  (ProblemDetail status-transition reading legacy `data?.detail`
  under unified envelope — surfaced by WP03 sweep).
- **Production regressions introduced:** zero. Every WP held the
  green-suite invariant across its merge gate.

### WPs shipped

| WP | Bucket | Summary | Test delta |
|---|---|---|---|
| WP01 | G0 | Baseline verify (1429 P backend / 245 P frontend). Confirmed OTel noise + `search_multi.py` SyntaxWarning + RR v7 future-flag warnings as pre-existing cosmetic. | ±0 |
| WP02 | C2 | `catch {}` structural lint pinned. TS compiler API walker over `frontend/src/pages/**/*.{ts,tsx}`. Bare + swallow classification; rethrow + typed-unknown bindings correctly NOT flagged. 6 self-tests + 1 allow-list lockstep with stale-entry detection. 36 current offenders (36 bare, 0 swallow — WP04 already cleared swallow class). JSDoc-glob footgun documented. | +7 (245→252 frontend) |
| WP03 | C1 | Category-c silent-on-non-2xx sweep. 23 of 28 sites migrated; 5 documented as by-design empty-state. ProblemDetail split into `error` (load) + `actionError` (action, dismissible banner). Status-transition legacy `data?.detail` shape regression fixed in flight. 4 ProblemDetailActionError regression tests. Allow-list 36→13. | +4 (252→256 frontend) |
| WP04 | C3 | OTel quieting via InMemoryMetricReader swap under `PYTEST_CURRENT_TEST`. Both noise patterns (closed-stdout + 4317-refused) originate in `PeriodicExportingMetricReader` background thread. Subprocess-discriminator regression test. Exporter wiring contract preserved. | +1 (1429→1430 backend) |
| WP05 | closure | Retrospective + v2.16 seed (this doc). | ±0 |

### Production bugs caught

1. **WP03 — ProblemDetail status-transition legacy-shape silent
   regression.** The `alert(data?.detail ...)` read on
   transition-failure was using the legacy non-envelope error shape
   — present since before v2.13-WP03's unified envelope adapter,
   never caught because the wrong-key read doesn't crash, it
   silently falls back to the hardcoded "Transition failed" string.
   Surfaced by the category-c sweep as collateral when the catch
   block was migrated to `throwParsed`. Fix: read `parsed.message`
   from the envelope through the new `actionError` slot.

### Cross-cutting lessons

1. **Lint-before-sweep is a forcing function pattern.** WP02 (lint)
   ran before WP03 (sweep). The allow-list was both the worklist
   AND the regression gate: every WP03 migration shrank the list by
   exactly one, and the stale-entry detector failed red on any
   line-number drift. WP03 needed no separate inventory pass. The
   pattern is general: when a backlog has known shape, pin the
   lint first; let the sweep shrink the allow-list. The lint
   failing red after each migration is the feedback signal that
   keeps the sweep honest — without it, sweeps drift on undetected
   stale state.

2. **Allow-list-with-stale-detection > allow-list-only.** Pure
   allow-lists rot silently as code moves. The lockstep test
   asserts BOTH directions: every live offender is allowed AND
   every allow-list entry is still live. The stale detector caught
   every line-number drift during WP03's migration (twice during
   intermediate refactors). Without it, WP03 would have shipped
   with dangling entries. The pattern was established in
   v2.11-WP09 (parity lint) and inherited by WP02 — it remains the
   right shape for any structural allow-list.

3. **Category-c-by-design needs an explicit type, not just an
   annotation.** WP03 found that 5 of 28 "silent-on-non-2xx" sites
   were intentional empty-state (optional bootstrap reads where
   404 means "no data, render empty"). They look IDENTICAL to bug
   sites under structural lint. v2.14-WP04 had already labelled
   them; without that labelling, WP03 would have wasted effort
   migrating no-ops. Forward rule: when a class has a known mixed
   population (real bugs + by-design no-ops), the FIRST surfacing
   of the class must include a by-design enumeration in the same
   diagnosis. Punting intent analysis to the sweep WP forces the
   sweep to re-derive it from scratch.

4. **Two error states beat one for action-vs-load distinction.**
   ProblemDetail had a single `error` state driving full-page
   replacement. Reusing it for transient action failures would have
   UX-broken the page (every failed comment post would have full-
   page-replaced the user out of context). Splitting into `error`
   (load) + `actionError` (action, inline dismissible banner)
   preserved both surfaces with zero state-management refactor.
   Pattern: when a page has BOTH load failures and action failures,
   give them separate state slots BEFORE they collide. Two
   `useState` strings cost one banner JSX block; the refactor of a
   unified-error page later is far more expensive.

5. **`PYTEST_CURRENT_TEST` is the canonical no-config test-mode
   sentinel.** Set by pytest itself for the duration of any test
   run. No setup, no project-local convention, no forward-door
   burden on future runners. Prefer it over inventing a
   `TESTING=1` flag. Caveat: it gates BEHAVIOR not WIRING — the
   exporter is still imported/initialised; only the periodic-reader
   background thread is swapped. This preserves any test that
   asserts on exporter wiring (e.g. `test_otel_init.py` continued
   to pass unchanged).

6. **Metric exporters dominate the OTel noise budget.** Span
   exporters in this codebase are batch-only and silent absent
   emitted spans. ALL test-time noise comes from
   `PeriodicExportingMetricReader`'s background flush thread
   (Console variant: closed-stdout writes; OTLP variant: connection
   refused). v2.14-WP01 labelled the issue "OTel gRPC export
   noise" — implying the gRPC layer. The actual layer was the
   metric reader. When auditing OTel noise: check metric exporters
   first, characterise the source before patching.

7. **JSDoc + glob fragments is a footgun.** `**/*.tsx` inside a
   `/** ... */` block terminates the block early at the first `*/`.
   esbuild fails the file with a confusing downstream parse error.
   Avoid glob fragments in TS/JS block comments — use `* * *`
   markers, escape the slash, or keep globs in line comments only.
   General rule: any `/* … */`-fenced free text mentioning a glob
   pattern is a landmine.

8. **Legacy error-shape reads hide in plain sight under unified
   envelopes.** ProblemDetail's `data?.detail` read was reading the
   legacy non-envelope shape; the unified envelope post v2.13-WP03
   puts the user-facing string under `message`. The wrong-key read
   doesn't crash, it silently falls back to a hardcoded string.
   Lesson: when migrating error surfaces under a unified envelope,
   audit every page-level error read for legacy-shape key names
   (`detail`, `error.message`, etc.). Structural lint cannot catch
   this — it requires inspection at every catch/setError site.

### What stayed deferred (carry to v2.16)

- **Bucket A (C7, E3, E4, F3)** — still conditional v2.11
  carry-forwards (decode_email_body helper, KindPill 7th surface,
  useSearchV2 ergonomic follow-ups, TipTap second-consumer
  extraction). No triggering need fired in v2.15.
- **B1 — per-arm `refresh_total` opt-in syntax** — still
  conditional. Wire-shape change only (`refresh_total: boolean |
  string[]`); per-arm `total_authority` already on the wire. Pick
  up if a real user need surfaces.
- **B2 — WP05 OpenAPI↔TS parser expansion** — nested generics,
  intersection types, multi-param generics, generic type aliases,
  mapped/conditional, default generic params. Parser-rejected with
  explicit self-tests; pick up when the first
  `frontend/src/api/*.ts` consumer needs one.
- **13 remaining bare-catch entries** in the WP02 allow-list — all
  in pages OUTSIDE the category-c scope (e.g. admin pages where
  `catch (err)` already exists but the body just resets a single
  state variable; the lint's binding-ref-based swallow detection
  treats them as clean-but-noisy). Worth a follow-up audit when a
  class member needs migration, but no triggering need today.
- **5 category-c-by-design sites** are now PERMANENTLY documented
  in the WP03 diagnosis. NOT a carry-forward (they will not be
  re-evaluated) — but the diagnosis pattern (label by-design at
  first surfacing) IS a forward-pointing rule for future class
  inventories.
- **`app/services/search_multi.py:119` SyntaxWarning** (`\)` in
  docstring) — trivial cosmetic, ~5min fix. Not worth a dedicated
  WP; bundle into a v2.16 WP-zero cleanup if any cosmetic surface
  is touched.
- **React Router v7 future-flag warnings** — frontend cosmetic;
  library upgrade decision. Bundle into the same v2.16 WP-zero
  cleanup or pick up when RR v7 lands as a hard requirement.

### Files touched (rough stats)

- **Production code (`app/`):**
  - 1 file: observability bootstrap module (WP04 — single swap at
    metric-reader initialisation under `PYTEST_CURRENT_TEST`).
- **Alembic (`alembic/versions/`):** 0 files.
- **Test code (`tests/`):**
  - 1 new file: `tests/observability/test_otel_silence_wp04_v215.py`
    (WP04, 1 test).
- **Frontend (`frontend/`):**
  - 2 pages modified (WP03): `ProblemDetail.tsx` (action-error
    split + legacy-shape fix + 23 catch-site migrations),
    `ProblemDetail.css` (action-error banner styles).
  - 2 new test files:
    `frontend/src/pages/__tests__/catch_block_lint.test.ts` (WP02,
    7 tests),
    `frontend/src/pages/__tests__/ProblemDetailActionError.test.tsx`
    (WP03, 4 tests).
- **Docs (`.claude/lessons-learned/`):** 3 per-WP diagnosis files
  (`v2.15-wp02-diagnosis.md`, `v2.15-wp03-diagnosis.md`,
  `v2.15-wp04-diagnosis.md`) + this retrospective.

---

## v2.16 starting prompt seed

v2.15 closed all three Bucket-C candidates carried forward from
v2.14-WP04 (C2 `catch {}` lint, C1 category-c sweep, C3 OTel
quieting). Bucket A items (C7, E3, E4, F3 — v2.11 carry-forwards)
remain conditional. Bucket B items (B1 per-arm refresh_total, B2
WP05 parser expansion) remain conditional. No new structural-debt
candidates were surfaced by v2.15 WPs: the category-c sweep was
the last identified bug class in the page-level error surface; the
OTel noise was the last identified test-time stderr cosmetic; and
the catch lint pins the regression net forward.

**v2.16 has NO new structural-debt candidates queued.** It is
likely a quieter version focused on opportunistic Bucket-A or
Bucket-B carry-forwards (act only on triggering second-consumer
need) OR new product surface (whatever the user brings). The two
cosmetic items — `search_multi.py:119` SyntaxWarning and React
Router v7 future-flag warnings — neither warrants a dedicated WP
but could be bundled into a "WP-zero cleanup" at the head of
v2.16 if any cosmetic surface is touched.

### v2.16 backlog

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
    intersection types, multi-param generics, generic type
    aliases, mapped/conditional, default generic params.
    Parser-rejected with explicit self-tests; pick up when the
    first `frontend/src/api/*.ts` consumer needs one.

#### Bucket Z — Cosmetic WP-zero bundle (optional)

Z1. **`app/services/search_multi.py:119` SyntaxWarning** — `\)` in
    docstring, raw-string or escape; ~5min.
Z2. **React Router v7 future-flag warnings** — opt in to
    `v7_startTransition` / `v7_relativeSplatPath` future flags OR
    upgrade RR v7 outright. Library decision required.
Z3. **13 remaining bare-catch entries** in the WP02 allow-list —
    not a v2.16 priority, but worth re-auditing if any admin page
    in the list is touched for product reasons.

### v2.16 prompt seed (paste-ready)

> Proceed with v2.16 of the problem-bulletin ticketing system.
> v2.15 retrospective + carry-forward backlog live at the bottom of
> `.claude/lessons-learned/ticketing-v2.15.md`. Baselines: backend
> **1430 P / 0 F / 5 skipped / 14 xfailed**, frontend **256 P / 0
> F**. Bucket A items (C7, E3, E4, F3) are conditional carry-
> forwards from v2.11 — act ONLY on a triggering second-consumer
> need. Bucket B items (B1 per-arm refresh_total opt-in, B2 WP05
> parser expansion) are conditional carry-forwards from v2.13 —
> same rule. **v2.15 closed the last identified structural-debt
> class (category-c silent-on-non-2xx page sites) and pinned the
> lint regression net (`catch {}` structural lint with stale-entry
> detection). v2.16 has no new structural-debt candidates queued.**
> Default work order: opportunistic Bucket A or B if a triggering
> consumer surfaces, OR new product surface (user-driven). Cosmetic
> Bucket Z (search_multi.py SyntaxWarning, RR v7 future-flag
> warnings, 13 remaining out-of-scope bare-catch entries) is
> optional — bundle only if any cosmetic surface is touched
> incidentally. Follow the sequential subagent loop pattern, TDD-
> first, one diagnosis doc per WP under
> `.claude/lessons-learned/v2.16-wpNN-diagnosis.md`. Append lessons
> to `.claude/lessons-learned/ticketing-v2.16.md`. Forward rules
> from v2.15: (a) lint-before-sweep when a class has known shape;
> (b) by-design enumeration at FIRST surfacing of any mixed-
> population class; (c) two state slots for pages with both load-
> failure and action-failure UX; (d) `PYTEST_CURRENT_TEST` is the
> canonical no-config test-mode sentinel — prefer over inventing a
> project-local flag; (e) audit metric exporters first when OTel
> noise surfaces. Pre-flight any rename WP with `grep -rn` across
> `app/` AND `alembic/` before scoping. Encode numeric decision
> gates into perf-pass WP prompts. Do NOT reintroduce the
> `_v1_deferred.py` skip-hook — per-test deferral uses plain
> pytest markers.
