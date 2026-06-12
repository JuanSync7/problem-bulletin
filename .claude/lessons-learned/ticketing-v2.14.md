# v2.14 ticketing — lessons learned

Companion to `ticketing-v2.13.md`. Each WP records (a) what shipped,
(b) the cost surface (LOC, files touched), (c) lessons that survive
the WP (i.e. that should still be true in v2.15), and (d) deferred
follow-ups feeding the next backlog.

v2.14 was a Bucket-B sweep: three new initiatives carried forward
from the v2.13 backlog (B3 request-side `*Body` pins, B4 parity-lint
performance pass, B5 page-level `parseApiError` migration) plus the
baseline + closure WPs. No Bucket-A trigger fired; all four
conditional v2.11 carry-forwards (C7, E3, E4, F3) remain pending.

---

## v2.14-WP01 (G0) — baseline verify

Backend: **1422 P / 0 F / 5 skipped / 14 xfailed**. Frontend:
**243 P / 0 F**. Confirmed as the regression anchor for WP02+.

`pytest --durations=20` profile findings:

- Migration-roundtrip tests dominate per-test wall (5.9s + 1.72s +
  …). Acceptable on the merge gate; no consolidation work needed.
- OTel gRPC export errors visible in stderr (no collector at
  `localhost:4317`). Log spam, no functional impact. Backlogged as
  a v2.15 candidate — quiet the export when no collector configured.

No code or test changes.

---

## v2.14-WP02 (B3) — request-side `*Body` schema contract pins

**Pre-state.** v2.13-WP04 pinned 17 `*Create` / `*Update` request
schemas via AST-walk against the consumer module
(`schema.model_fields − consumer_referenced_names ⊆ excluded`). It
explicitly deferred the seven `*Body` / one-shot action-payload
schemas the frontend POSTs to endpoints like
`/tickets/{id}/transition`, `/assign`, `/comments`, `/links`,
`/watchers`, `/attachments` and `/auth/magic-link`. B3 closes that
deferral.

**What shipped.**

`tests/test_body_schema_contract_pins_wp02_v214.py` — 7 parametrized
pair tests, one per `(schema, consumer)` pair. The walker is inlined
verbatim from WP04 (the WP04 helper `_referenced_names_in_module` is
module-private; re-exporting it for one sibling would bend that
abstraction). Uses `tests/helpers/source_lint.py::parse_module`
(v2.12-WP02) — no new helper added.

| # | Schema | Consumer pattern | Consumer path | Excluded | Polarity |
|---|---|---|---|---|---|
| 1 | `TicketTransitionBody` | kwarg fan-out | `app/routes/tickets.py` | – | closed |
| 2 | `TicketAssignBody` | kwarg fan-out (`expected_version=…`) | `app/routes/tickets.py` | – | closed |
| 3 | `TicketCommentBody` | kwarg fan-out | `app/routes/tickets.py` | – | closed |
| 4 | `TicketLinkBody` | kwarg fan-out | `app/routes/tickets.py` | – | closed |
| 5 | `TicketWatcherBody` | kwarg fan-out | `app/routes/tickets.py` | – | closed |
| 6 | `TicketAttachmentBody` | kwarg fan-out | `app/routes/tickets.py` | – | closed |
| 7 | `MagicLinkRequest` | direct `.email` attribute access | `app/routes/auth.py` | – | closed |

All 7 schemas closed (no `extra="allow"`). No `excluded` rows
needed.

**The `TicketAssignBody.expected_version` decision.** This was the
only OCC-flavoured field and could have been a candidate for
`excluded={"expected_version"}` by analogy with WP04's PATCH-schema
`version` token. It does NOT need exclusion here because the assign
route uses kwarg fan-out (not the `exclude={"version"}` + `setattr`
loop pattern) and forwards the field explicitly to
`svc.assign(..., expected_version=…)`. The kwarg-name walk picks it
up; it's consumed, not stripped. Lesson surviving this WP: a field
is "excluded" ONLY if the route deletes/transforms it before
fan-out — pass-through forwarding is consumption.

**No synthetic self-tests added in WP02's file.** WP04 already
provides `test_synthetic_drift_fires_red` and
`test_synthetic_good_passes` for the identical walk shape. Adding
duplicates in WP02 would be redundant noise.

**Drift findings.** Zero drift. All 7 pairs pass green on first
run. Unsurprising: every endpoint uses kwarg fan-out, so a missing
field would surface at code-review time as "schema has N+1 fields
but the route only references N kwargs". The lint formalises what
was already enforced by code-review convention.

**Numbers.**

- Net pytest delta: 1422 → **1429** (+7 — one pair test per schema).
- Frontend untouched at 243.
- Files added: 1 test module + 1 diagnosis doc.
- Files touched: 0 (no production code, no consumer edits, no
  xfails).

**Lessons surviving WP02.**

1. **Closed schemas remain the common case on the request side.**
   Both WP04 (17 pairs) and WP02 (7 pairs) found every request
   schema closed — no `extra="allow"` in any `*Create` / `*Update`
   / `*Body`. The polarity flip remains a forward-door rule, not an
   active concern. The first PR that introduces `extra="allow"` on
   a request schema must flip per-pair polarity to
   "consumer-required ⊆ schema.model_fields".
2. **OCC tokens kwarg-forwarded count as consumed, not excluded.**
   `expected_version` on the assign route taught the polarity rule
   explicitly: excluded means "the route deletes/transforms the
   field before fan-out" (the PATCH `mutable = {...}` +
   `exclude={"version"}` shape from WP04). Pass-through forwarding
   is consumption — the walker picks it up via the kwarg name.
3. **Inline the walker rather than re-export a private helper for
   one sibling.** WP02's walker is ~25 lines of AST traversal
   duplicated verbatim from WP04. The duplication is cheaper than
   the abstraction tax of widening WP04's module-private helper to
   public surface. Same lesson as v2.13-WP05's "sibling test
   modules beat bloating one canonical file".

---

## v2.14-WP03 (B4) — parity-lint performance pass

**Pre-state.** v2.13-WP05 expanded the OpenAPI↔TS parity lint to
generics + unions, landing in a new sibling file
(`test_openapi_ts_parity_wp05_v213.py`) alongside the original
`test_openapi_ts_parity_wp11.py`. v2.13-WP05's deferred follow-up
B4 was: profile the cluster and, if wall >2s or any individual test
multi-second, consolidate the boot/parse fixtures into session
scope.

**Decision gate.** The prompt explicitly allowed a no-op outcome
(defer if cluster ≤1s OR no individual test/setup >0.3s). The
profile said otherwise:

```
$ pytest tests/test_openapi_ts_parity_*.py --durations=0 -v
27 passed in 2.01s

1.31s setup    tests/test_openapi_ts_parity_wp05_v213.py::…
0.44s setup    tests/test_openapi_ts_parity_wp11.py::…
```

Two independent `build_test_app()` boots + two `app.openapi()`
schema builds — once per module-scoped fixture. Total setup ≈
1.75s, dominating the 2.01s wall. Both above the 0.3s defer
ceiling; cluster above the 2s threshold. Path: **CONSOLIDATE.**

**What shipped.**

Three session-scoped fixtures added to `tests/conftest.py`
(additive only — no existing fixture modified):

- `parity_lint_app` — single `build_test_app()` call per session.
- `parity_lint_openapi_spec` — single `app.openapi()` per session.
- `parity_lint_ts_sources` — pre-read dict of frontend TS sources
  (`tickets.ts`, `projects.ts`, `sprints.ts`, `notifications.ts`,
  `search.ts`, `people.ts`, `users.ts`, `comments.ts`). Reserved
  for future use; not yet consumed by either parity-lint file (the
  existing `_read_ts` helpers are sub-millisecond — keeping them
  in-module avoids touching surface area that isn't on the
  perf-critical path).

Both parity-lint modules migrated to thin pass-through module-scoped
fixtures:

```python
@pytest.fixture(scope="module")
def app(parity_lint_app) -> FastAPI:
    return parity_lint_app

@pytest.fixture(scope="module")
def openapi_spec(parity_lint_openapi_spec) -> dict[str, Any]:
    return parity_lint_openapi_spec
```

Every test's existing parameter signature (`app`, `openapi_spec`) is
preserved — zero call-site changes. The `build_test_app` import is
intentionally left in both files to make the pattern's origin
obvious to readers.

**Post-pass timings.**

```
27 passed in 1.61s   # was 2.01s — -0.40s, -20%

1.33s setup    tests/test_openapi_ts_parity_wp05_v213.py::…
```

Exactly one setup line remains; the second module's boot cost is
gone. The 1.33s ≈ the 1.31s baseline (run-to-run noise); the
saved 0.40s ≈ the 0.44s second-boot cost.

**Numbers.**

- Cluster wall: 2.01s → **1.61s** (-20%).
- Full backend: **1429 P** unchanged. No tests added, no tests
  removed, no test logic modified.
- Frontend untouched at 243.
- Files touched: `tests/conftest.py` (additive), the two parity-lint
  modules (re-export fixtures). No production code changes.

**Lessons surviving WP03.**

1. **Defer was a valid path until the profile said otherwise.** The
   WP went in prepared to no-op; the durations profile justified
   consolidation. The decision gate prevented speculative refactor
   while still capturing the real win. Lesson: write decision gates
   into WP prompts; don't pre-commit to outcome.
2. **Pass-through module fixtures preserve every call site.** The
   re-export pattern (`@pytest.fixture(scope="module") def app(...
   parity_lint_app): return parity_lint_app`) costs ~6 lines per
   migrated file but means zero test bodies move. For lint clusters
   that share boot cost, this is the cheapest consolidation shape.
3. **Reserve future-use fixtures alongside the active ones.**
   `parity_lint_ts_sources` is unused today but pre-shaped for the
   `_read_ts` helpers if they ever become a perf bottleneck. The
   cost of adding a stub is one dict comprehension; the cost of
   re-doing the session-scope plumbing later is a second migration.
4. **The next consolidation pass threshold is ~2.5s.** One more
   parity-lint module's boot cost would push the cluster back into
   2.5s territory. Recipe + threshold are documented in the
   diagnosis for the next WP to follow.

---

## v2.14-WP04 (B5) — page-level `parseApiError` sweep

**Pre-state.** v2.13-WP03 ported the 9 `frontend/src/api/*.ts` files
to `parseApiError`. The ~52 inline `fetch()` call sites under
`frontend/src/pages/**` remained on hand-rolled error handling. A
handful surfaced synthesised `Failed to load X (NNN)` / `Save
failed (NNN)` strings to the user, silently dropping the backend's
structured envelope (`code` / `correlation_id` / real `message`).

**Inventory taxonomy.** Per the WP prompt:

- (a) Already on `parseApiError` — 0 sites.
- (b) Bare `throw new Error("HTTP ..." / "Failed to load ...")`
  losing structured envelope — **silent-swallow class.**
- (c) No error branch at all (`if (res.ok) { ... }` with no else /
  silent `catch {}`) — different bug class; **out of scope.**
- (d) Custom handling surfaced via toast/UI — migrated so the
  backend's `message` reaches the toast.

**What shipped.**

24 sites migrated across 12 files. 12 silent-swallow bugs found
and fixed in-place. All `catch {}` promoted to `catch (err)` so
`err.message` (now the backend envelope's `message`) reaches the UI.

| File | Sites | Pattern |
|---|---|---|
| `Feed.tsx` | 1 | single-throw + regression test |
| `Leaderboard.tsx` | 1 | single-throw + regression test |
| `ProblemDetail.tsx:519` | 1 | single-throw |
| `Settings.tsx` | 1 | single-throw |
| `Submit.tsx:150` | 1 | single-throw (POST `/api/problems`) |
| `LabelDetail.tsx` | 1 | single-throw |
| `UserDetail.tsx` | 1 | single-throw |
| `admin/Dashboard.tsx` | 1 | single-throw |
| `admin/Categories.tsx` | 5 | file-local `throwParsed` helper |
| `admin/Tags.tsx` | 4 | file-local `throwParsed` helper |
| `admin/Moderation.tsx` | 3 | file-local `throwParsed` helper |
| `admin/Users.tsx` | 3 | file-local `throwParsed` helper |

**Convergent patterns.** Two pattern shapes recur:

1. **Single-throw page** — inline `parseApiError(res, body)` then
   `throw new Error(parsed.message)` or `setState({...message:
   parsed.message})`. Single call site per file; no shared helper
   warranted.
2. **Multi-throw admin page** — file-local helper

   ```ts
   async function throwParsed(res: Response, fallback: string): Promise<never> {
     const body = await res.json().catch(() => null);
     const parsed = parseApiError(res, body);
     throw new Error(parsed.message || fallback);
   }
   ```

   used at every non-2xx branch. The helper is file-local on
   purpose — promoting it to a shared module would create a
   circular-dep risk (`api/errors.ts` is already the bottom of the
   stack) and would re-open the design question about whether the
   wrapper should throw `Error` or `ApiError`. The file-level
   duplication (4 × ~5 lines) is far cheaper than the abstraction.

**Regression tests.** Two added for the publicly-reachable,
auth-free, low-mock-cost surfaces:

- `frontend/src/pages/__tests__/FeedErrorEnvelope.test.tsx` — mocks
  `fetch` to return `429` with the unified envelope, asserts the
  envelope's `message` is rendered in `role="alert"`,
  negative-asserts the legacy synthetic `Failed to load problems
  (429)` is NOT present.
- `frontend/src/pages/__tests__/LeaderboardErrorEnvelope.test.tsx`
  — same shape for `503` / `service_unavailable`.

Both tests would FAIL against the pre-WP04 code. The other 10
silent-swallow sites are either guarded by `AdminRouteGuard` (cost-
of-mock far beyond WP scope) or nested deep in `ProblemDetail`
(>1300-LOC component). The migration pattern is mechanically
identical to the two tested sites; the contract is "non-2xx →
`res.json().catch(() => null)` → `parseApiError(res, body).message`
→ throw / setError". The `parseApiError` adapter itself is pinned
by the `errors.ts` unit tests from v2.12-WP09 — the new tests cover
that the adapter is *wired* at the page boundary.

**Out-of-scope skips (28 category-c sites).** All in
`ProblemDetail.tsx` (23), `Submit.tsx` (3), `Search.tsx` (1),
`ProblemDetail` watch DELETE (1). These have `if (res.ok) { ... }`
with no else — non-2xx silently ignored. Different bug class (no
error UX at all, vs. wrong error UX) and out of scope here.
Recorded as v2.15 carry-forward.

**Numbers.**

- Frontend net delta: 243 → **245** (+2 — 1 Feed regression, 1
  Leaderboard regression).
- Backend untouched at 1429.
- Sites inventoried: **52**.
- Sites migrated: **24** across **12** files.
- Silent-swallows found: **12** (6 strict err.message-to-user; 6
  catch-block-swallowed structured fields in admin pages).
- Sites skipped (category c, recorded): **28**.

**Lessons surviving WP04.**

1. **Page-level error UI is shallow.** Most pages do `setError(string
   | null)` and render `{error && <div>{error}</div>}`. The cheapest
   plumbing is to keep that string shape and only swap the source
   from `"Failed to load X (NNN)"` to `parsed.message`. No
   `ApiError` plumbing required at the UI layer — the API-client
   layer (v2.13-WP03) already exposes `ApiError` for callers that
   want the structured envelope; pages that just render a message
   keep their thin shape.
2. **`catch {}` → `catch (err)` is the bigger code-smell.** Four
   admin files were swallowing the thrown `Error("Failed to update
   X")` and showing a hardcoded toast. Promoting to `catch (err)`
   and threading `err.message` is what actually surfaces the
   envelope's message — the `parseApiError` upstream is necessary
   but not sufficient. A linter pass for bare `catch {}` in `.tsx`
   pages would catch this class structurally; backlogged for v2.15.
3. **`throwParsed(res, fallback)` is a file-local convergence
   pattern.** When ≥3 sites in a file share an error-handling
   shape, introduce a file-local helper before reaching for a
   cross-file extraction. WP04 hit the "5 admin pages × ~3
   endpoints each = 15 mostly-identical migrations" shape; the
   file-local helper kept the migration uniform without
   crystallising a premature shared abstraction.
4. **Category-c sites are a real carry-forward.** 28 skipped sites
   (mostly in `ProblemDetail.tsx`) silently drop non-2xx into a
   no-op. Different bug class than silent-swallow; needs product
   input on intended UX (toast? inline error? page-level error?).
5. **`global.IntersectionObserver` is not provided by jsdom.**
   Tests that mount components with `useEffect` infinite-scroll
   observers need a per-test stub. (Cost: 6 lines per test file.
   Recorded in case a future WP adds more `Feed`-style tests.)

---

## v2.14-WP05 (closure) — retrospective + v2.15 seed

This document. Zero code touched.

---

## v2.14 retrospective

### Headline numbers

- **Backend baseline:** 1422 P / 0 F / 5 skipped / 14 xfailed
  (v2.13 close).
- **Backend final:** **1429 P / 0 F / 5 skipped / 14 xfailed**.
- **Net delta:** +7 across 3 working WPs. WP02 contributed +7
  request-side `*Body` contract pins. WP03 was a perf consolidation
  (zero test add/remove). WP04 was frontend-only.
- **Frontend:** 243 → **245 P / 0 F**. +2 from WP04 (Feed +
  Leaderboard silent-swallow regression tests).
- **Performance:** parity-lint cluster 2.01s → **1.61s** (-20%).
- **Production bugs caught and fixed:** **12 silent-swallow sites**
  across 12 frontend files (Feed, Leaderboard, ProblemDetail:519,
  Settings, Submit:150, LabelDetail, UserDetail, admin/Dashboard,
  admin/Categories ×5, admin/Tags ×4, admin/Moderation ×3,
  admin/Users ×3).
- **Production regressions introduced:** zero. Every WP held the
  green-suite invariant across its merge gate.

### WPs shipped

| WP | Bucket | Summary | Test delta |
|---|---|---|---|
| WP01 | G0 | Baseline verify (1422 P backend / 243 P frontend). Noted migration-roundtrip duration hotspots + OTel gRPC export noise. | ±0 |
| WP02 | B3 | Request-side contract pins for 7 `*Body` schemas (TicketTransition/Assign/Comment/Link/Watcher/Attachment + MagicLinkRequest). All closed-polarity, kwarg fan-out idiom; zero exclusions. Walker re-inlined from WP04 verbatim (no helper widened). Zero drift caught. | +7 (1422→1429) |
| WP03 | B4 | Parity-lint perf consolidation. 2 module-scoped `build_test_app()` boots → 1 session-scoped via 3 new fixtures in `tests/conftest.py`. Pass-through module fixtures preserved every test signature. Cluster 2.01s → 1.61s (-20%). | ±0 (perf only) |
| WP04 | B5 | Page-level `parseApiError` sweep. 52 sites inventoried; 24 migrated across 12 files; 12 silent-swallow bugs fixed. File-local `throwParsed` helper convergence pattern for multi-site admin pages. 28 category-c sites recorded as v2.15 carry. | +0 backend / +2 frontend (243→245) |
| WP05 | closure | Retrospective + v2.15 seed (this doc). | ±0 |

### Production bugs caught

1. **WP04 — 12 frontend silent-swallows.** Every one had the same
   structural shape: a non-2xx branch that either threw
   `new Error("HTTP NNN")` / `"Failed to load X (NNN)"` (losing the
   backend envelope) or had a bare `catch {}` block swallowing the
   structured `err.message` before it reached the toast. Fix
   pattern: `res.json().catch(() => null)` → `parseApiError(res,
   body).message` → throw / setError / show. 6 of the 12 are admin
   pages that share a file-local `throwParsed(res, fallback)`
   helper; 6 are single-throw pages that inline the parse.
2. **WP04 — adapter porting found a HIGHER rate per LOC than the
   first encounter.** v2.13-WP03 found 2 silent-swallows in 7
   `frontend/src/api/*.ts` files (~29% rate). v2.14-WP04 found 12
   silent-swallows in 52 page-level sites (~23% rate). Pages are
   NOT cleaner than `/api` — they're WORSE because hand-rolled
   per-route. The adapter sweep IS the regression net for this
   entire class of bug.
3. **WP03 — duplicate FastAPI boot in the parity-lint cluster.**
   Two parity-lint modules each ran their own `build_test_app()`
   and `app.openapi()` in module-scoped fixtures, costing ~0.44s
   of redundant setup per CI run. Not a correctness bug, but a
   perf bug fixed via session-scoped consolidation (-20% cluster
   wall).

### Cross-cutting lessons

1. **Adapter-porting catches silent-swallows at a high rate per
   LOC.** v2.13-WP03 hit ~29% (2 of 7 api files). v2.14-WP04 hit
   ~23% (12 of 52 page sites). Page-level error handling is
   structurally hand-rolled per route and contains the same bug
   class as the api layer — only the surface count is larger. The
   adapter sweep IS the regression net. When a future surface
   introduces inline `fetch()`, the budget for porting it should
   include "expect ~25% silent-swallow rate, fix in place".
2. **Decision gates in WP prompts prevent speculative refactor.**
   WP03 went in prepared to no-op; the durations profile justified
   the consolidation, and the perf delta (-20%) was deterministic
   rather than estimated. The seed cautioned against speculative
   work and the gate honoured that caution. Future perf-pass WPs
   should encode a numeric defer threshold (here: cluster ≤1s OR
   no setup >0.3s) in the prompt.
3. **`throwParsed(res, fallback)` is a file-local convergence
   pattern.** When ≥3 sites in a file share an error-handling
   shape, introduce a file-local helper before reaching for a
   cross-file extraction. WP04 hit the "5 admin pages × ~3
   endpoints each" shape; the file-local helper kept the migration
   uniform without crystallising a premature shared abstraction.
   v2.13-WP03's "permissive parser + thin convergent wrapper is
   the cheapest sweep shape" carries directly — the difference is
   that the wrapper is file-scoped, not module-scoped, because the
   admin pages do not import each other.
4. **OCC tokens kwarg-forwarded count as consumed for contract
   polarity.** WP02 confirmed `TicketAssignBody.expected_version`
   is forwarded as a kwarg by the assign route — therefore
   consumed, not stripped. The polarity rule: a field is
   "excluded" ONLY if the route deletes/transforms it before
   fan-out (the `mutable = {...}` + `exclude={"version"}` shape
   from WP04). Pass-through forwarding is consumption.
5. **`catch {}` is structurally invisible to the polarity audit.**
   WP04 had to promote every bare `catch {}` to `catch (err)` THEN
   thread `err.message` to the UI. The `parseApiError` upstream is
   necessary but not sufficient — if the catch block discards the
   thrown Error, no envelope reaches the user. A linter pass for
   bare `catch {}` in `.tsx` pages would surface this class
   structurally; backlogged as v2.15 candidate.
6. **Pass-through module fixtures preserve every call site.** WP03
   migrated 27 parity-lint tests to session-scoped fixtures via a
   ~6-line re-export shim per module — zero test bodies moved.
   For lint clusters that share boot cost, this is the cheapest
   consolidation shape. The pattern is now documented in
   WP03's diagnosis as the canonical recipe.
7. **Closed-schema polarity remains the common case on the request
   side.** WP02's 7 `*Body` pairs were all closed; combined with
   WP04's 17 `*Create`/`*Update` pairs (also all closed), the
   codebase has 24 request-side schemas pinned, zero
   `extra="allow"`. The polarity-flip rule is still a forward-door
   invariant — the first PR to introduce `extra="allow"` on a
   request schema must add per-pair documentation flipping
   direction to "consumer-required ⊆ schema.model_fields".
8. **Reserve future-use session-scoped fixtures alongside active
   ones.** WP03 added `parity_lint_ts_sources` to `conftest.py`
   pre-shaped for `_read_ts` helpers if they become a perf
   bottleneck. The cost of adding a stub is one dict comprehension;
   the cost of re-doing session-scope plumbing later is a second
   migration. Defer the work, not the data path.

### What stayed deferred (carry to v2.15)

- **Category-c silent-on-non-2xx pages** (28 sites in
  `ProblemDetail.tsx`, `Submit.tsx`, `Search.tsx`) — `if (res.ok)
  {...}` with no else branch. Different bug class than
  silent-swallow; needs product input on intended UX (toast?
  inline error? page-level error?). The 28 sites are recorded
  per-file:line in v2.14-WP04 diagnosis. **NEW v2.15 candidate.**
- **`catch {}` lint** — a structural lint for bare `catch {}` in
  `.tsx` pages would catch the WP04 admin-page class of bug
  without requiring an adapter port. **NEW v2.15 candidate from
  WP04 lessons.**
- **OTel gRPC export noise in stderr** — backend logs
  `Connection refused` to `localhost:4317` continuously when no
  collector configured. Functional impact zero; log spam
  non-zero. **NEW v2.15 candidate from WP01.**
- **B1 — per-arm `refresh_total` opt-in syntax** — still
  conditional. Wire-shape change only (`refresh_total: boolean |
  string[]`); per-arm `total_authority` already on the wire. Pick
  up if a real user need surfaces.
- **B2 — WP05 OpenAPI↔TS parser expansion** — nested generics,
  intersection types, multi-param generics, generic type aliases,
  mapped/conditional, default generic params. Parser-rejected with
  explicit self-tests; pick up when the first
  `frontend/src/api/*.ts` consumer uses one of these shapes.
- **Bucket A — C7, E3, E4, F3** — still conditional v2.11
  carry-forwards (decode_email_body helper, KindPill 7th surface,
  useSearchV2 ergonomic follow-ups, TipTap second-consumer
  extraction). No triggering need fired in v2.14.

### Files touched (rough stats)

- **Production code (`app/`):** 0 files. v2.14 was a contracts +
  perf + frontend-error-handling sweep — zero backend production
  code touched.
- **Alembic (`alembic/versions/`):** 0 files.
- **Test code (`tests/`):**
  - 1 new file: `tests/test_body_schema_contract_pins_wp02_v214.py`
    (WP02, 7 tests).
  - 3 modified files: `tests/conftest.py` (WP03 — 3 session-scoped
    fixtures, additive), `tests/test_openapi_ts_parity_wp11.py`
    (WP03 — re-export fixtures),
    `tests/test_openapi_ts_parity_wp05_v213.py` (WP03 — re-export
    fixtures).
- **Frontend (`frontend/`):**
  - 12 pages modified (WP04 — silent-swallow fixes + adapter
    wiring): `Feed.tsx`, `Leaderboard.tsx`, `ProblemDetail.tsx`
    (one site at line 519), `Settings.tsx`, `Submit.tsx` (POST
    `/api/problems` at line 150), `LabelDetail.tsx`,
    `UserDetail.tsx`, `admin/Dashboard.tsx`,
    `admin/Categories.tsx`, `admin/Tags.tsx`,
    `admin/Moderation.tsx`, `admin/Users.tsx`.
  - 2 new test files: `frontend/src/pages/__tests__/FeedErrorEnvelope.test.tsx`,
    `frontend/src/pages/__tests__/LeaderboardErrorEnvelope.test.tsx`.
- **Docs (`.claude/lessons-learned/`):** 3 per-WP diagnosis files
  (`v2.14-wp02-diagnosis.md`, `v2.14-wp03-diagnosis.md`,
  `v2.14-wp04-diagnosis.md`) + this retrospective.

---

## v2.15 starting prompt seed

v2.14 closed 3 of the 5 Bucket-B candidates from the v2.13 backlog
(B3 request-side `*Body` pins, B4 parity-lint perf, B5 page-level
`parseApiError`). B1 (per-arm `refresh_total` opt-in) and B2 (WP05
parser expansion) remain conditional — no triggering need fired.
The four conditional v2.11 carry-forwards (C7, E3, E4, F3) remain
pending. v2.14 also surfaced three NEW candidates for v2.15:
category-c silent-on-non-2xx page sites, a `catch {}` lint, and
OTel gRPC export noise.

### v2.15 backlog

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
    string[]`. Pick up if a real user need surfaces (e.g. an arm
    with a heavy `COUNT(*) OVER ()` cost). Forward door open via
    per-arm `total_authority`.
B2. **WP05 OpenAPI↔TS parser expansion** — nested generics,
    intersection types, multi-param generics, generic type
    aliases, mapped/conditional, default generic params. Currently
    parser-rejected with explicit self-tests; pick up when the
    first `frontend/src/api/*.ts` consumer needs one.

#### Bucket C — New v2.15 candidates (from v2.14 WPs)

C1. **Category-c silent-on-non-2xx page sites** — 28 sites in
    `ProblemDetail.tsx` (23), `Submit.tsx` (3), `Search.tsx` (1),
    `ProblemDetail` watch DELETE (1). All have `if (res.ok) {...}`
    with no else branch — non-2xx silently dropped. Different bug
    class than v2.14-WP04's silent-swallows. Needs product input
    on intended UX before scoping (toast? inline error? page-level
    error?). Per-file:line list lives in
    `.claude/lessons-learned/v2.14-wp04-diagnosis.md`.
C2. **`catch {}` lint** — a structural test that walks `.tsx`
    files under `frontend/src/pages/` and asserts no bare
    `catch {}` (bare catch swallows `err.message` and discards the
    backend envelope). v2.14-WP04 fixed every existing instance in
    admin pages; the lint is the regression net so a future PR
    can't re-introduce the class.
C3. **OTel gRPC export noise.** Backend logs `Connection refused`
    to `localhost:4317` continuously when no collector configured.
    Quiet the export when no collector is available (env-gated, or
    swap to a no-op exporter on `OTEL_EXPORTER_OTLP_ENDPOINT`
    unset).

### v2.15 prompt seed (paste-ready)

> Proceed with v2.15 of the problem-bulletin ticketing system.
> v2.14 retrospective + carry-forward backlog live at the bottom of
> `.claude/lessons-learned/ticketing-v2.14.md`. Baselines: backend
> **1429 P / 0 F / 5 skipped / 14 xfailed**, frontend **245 P / 0
> F**. Bucket A items (C7, E3, E4, F3) are conditional carry-
> forwards from v2.11 — act ONLY on a triggering second-consumer
> need. Bucket B items (B1 per-arm refresh_total opt-in, B2 WP05
> parser expansion) are conditional carry-forwards from v2.13 —
> same rule. Default work order: Bucket C (new v2.14-surfaced
> candidates — category-c silent-on-non-2xx page sites, `catch {}`
> structural lint, OTel gRPC export quieting) → opportunistic
> Bucket B if a triggering consumer surfaces. Follow the sequential
> subagent loop pattern, TDD-first, one diagnosis doc per WP under
> `.claude/lessons-learned/v2.15-wpNN-diagnosis.md`. Append lessons
> to `.claude/lessons-learned/ticketing-v2.15.md`. For C1, get
> product input on intended UX before scoping (28 sites span 4
> files — toast/inline/page-level error are all viable, and each
> implies a different UX surface). For C2, write the lint as a
> structural test under `frontend/src/__tests__/` and pin the
> regression net before any further page migration. Pre-flight any
> rename WP with `grep -rn` across `app/` AND `alembic/` before
> scoping (v2.12-WP08 / v2.13-WP02 precedent: prefer `conv()` over
> live RENAME for SQLAlchemy convention adoption). Encode numeric
> decision gates into perf-pass WP prompts (v2.14-WP03 precedent:
> defer if cluster ≤1s OR no setup >0.3s). Do NOT reintroduce the
> `_v1_deferred.py` skip-hook — per-test deferral uses plain
> pytest markers.
