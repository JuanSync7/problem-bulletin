# v2.13 ticketing — lessons learned

Companion to `ticketing-v2.12.md`. Each WP records (a) what shipped,
(b) the cost surface (LOC, files touched), (c) lessons that survive
the WP (i.e. that should still be true in v2.14), and (d) deferred
follow-ups feeding the next backlog.

---

## v2.13-WP01 (G0) — baseline verify

Backend: **1354 P / 0 F / 5 skipped / 14 xfailed**. Frontend:
**241 P / 0 F**. Used as the regression anchor for WP02+.

---

## v2.13-WP02 (Bucket A1) — `ck` naming_convention resurrection (broader sweep)

**Pre-state.** v2.11-WP10 pinned 4 of 5 keys
(`ix`/`uq`/`fk`/`pk`) on `Base.metadata.naming_convention`. The
`ck` key was deferred because every pre-WP10
`CheckConstraint(name=...)` in the repo passed the FULL already-
prefixed name (`name="ck_<table>_<short>"`), which would double-wrap
to `ck_<table>_ck_<table>_<short>` under the idiomatic template.

v2.12-WP08 attempted the resurrection and was rate-limited mid-
flight. Its surviving artifacts: all `app/models/*.py`
`CheckConstraint` literals already ported to bare short names (30
sites across 9 model files), 5 alembic files (a1, a2, a3, a10, a18)
partially wrapped with `sqlalchemy.sql.elements.conv(...)`.

The retrospective owed a complete sweep — v2.12 lesson #7: "sweep
scope is broader than `app/models/` alone — every
`alembic/versions/*.py` migration file that contains
`CheckConstraint(name=...)` is in scope too".

**What shipped.**

- `app/database.py::NAMING_CONVENTION` — `ck` key enabled with the
  idiomatic template `"ck_%(table_name)s_%(constraint_name)s"`.
- 44 alembic-migration `ck_*` literals wrapped with
  `conv(...)` across 5 files (a3, a7, a8, a9, a11). Imports of
  `from sqlalchemy.sql.elements import conv` added to the 4
  previously-untouched files (a3 had it from WP08).
- `tests/test_ck_naming_convention_wp02_v213.py` — 34 tests:
  - 1 convention-key assertion
  - 30 parametrized per-model-CheckConstraint emission guards
    (compiles `CREATE TABLE` and asserts exactly one
    `ck_<table>_` prefix in the rendered DDL)
  - 1 synthetic double-wrap self-test (proves the lint catches
    the regression mode)
  - 1 synthetic bare-name success self-test
  - 1 import-time mapper-walk smoke check (implicit via parametrize)
- `tests/test_naming_convention_wp10.py` — expected-dict updated
  to include the `ck` key (G7 flip).
- `alembic/versions/a20_ck_convention_alignment.py` — no-op marker
  migration recording the boundary at which the `ck` key went
  live. Revision ID `a20_ck_alignment` (16 chars, well under the
  alembic_version.version_num VARCHAR(32) limit — v2.11-WP15
  lesson).

**Strategy chosen: wrap-with-`conv()` in alembic; bare names in
models.** Rationale documented in
`.claude/lessons-learned/v2.13-wp02-diagnosis.md`. The prompt's
preferred approach (port migration name literals to bare + write
live-DB rename migration) was rejected because:

1. Migration history immutability is a stronger invariant than
   uniformity. The `conv()` wrapper is a render-time no-op that
   preserves the on-disk name byte-for-byte.
2. The model-side bare-name port already lands the convention
   benefit (any NEW model `CheckConstraint(name="<short>")` gets
   the prefix automatically).
3. No live-DB rename is required: model-emitted name
   (`ck_<t>_<s>` via convention) ≡ alembic-emitted name (literal
   `ck_<t>_<s>` via `conv()`) ≡ production-postgres name.

**Numbers.**

- Total ck constraint sites in repo: 61 (alembic) + 30 (models) = 91.
- Sites pre-wrapped by v2.12-WP08: 17.
- Sites wrapped by WP02: **44** (across 5 alembic migration files).
- New test file: 1, parametrized to 34 test cases.
- Net pytest delta: 1354 → 1387 (+33 — 30 parametrized + 3 helpers).
- Files touched: 6 alembic migrations + `app/database.py` + 2 tests +
  1 new marker migration + 1 new test file + 1 new diagnosis doc.

**Lessons surviving WP02.**

1. **`conv()` is the project's contract for historical full-name
   constraint literals in alembic.** Future migrations that need to
   reference a historical full-name `ck_<t>_<s>` must wrap with
   `conv()`. Future migrations that declare NEW constraints should
   pass bare short names and let the convention prefix them.

2. **Migration files inherit `target_metadata.naming_convention`
   even for `op.create_check_constraint(...)` / `op.drop_constraint(
   ..., type_="check")` calls.** This was confirmed by reading
   `alembic.operations.schemaobj.SchemaObjects.metadata` — the
   anonymous `MetaData` used to back the temp `Table` instance for
   the operation copies the project convention. So the wrap is
   needed on BOTH `sa.CheckConstraint(name=...)` inside
   `op.create_table` AND on bare `op.create_check_constraint`
   positional names.

3. **The WP10 None-named-constraint lint
   (`test_alembic_constraint_name_lint_wp10.py`) is orthogonal to
   the ck strategy.** Its scanner looks at
   `Constant(value=None)` first-arg shape; `conv("ck_...")` is a
   `Call(func=Name("conv"))`, so the lint passes through it
   unaffected. No update needed.

4. **Parametrize the model-emission guard, don't loop.** Each
   model's `CheckConstraint` gets its own pytest case so a future
   regression names the exact constraint that broke, not just "30
   constraints fail".

**Deferred follow-ups.** None — WP02 closes the
`v2.12-WP08 deferred` ticket.

---

## v2.13-WP03 (Bucket A2) — frontend `parseApiError` sweep

**Pre-state.** v2.12-WP09 introduced
`frontend/src/api/errors.ts::parseApiError(response, body)` — a permissive
adapter that accepts both the unified
`{error:{code,message,correlation_id,details}}` envelope and the legacy
`{detail: ...}` shape. WP09 wired only 2 sites (`users.ts`,
`auditLog.ts`). The other 7 API-layer files still hand-rolled
`body?.error ?? null` extraction (5 sites) or threw bare
`new Error("HTTP N")` / `"Search failed (N)"` with no parse at all
(2 sites).

**What shipped.** Every `frontend/src/api/*.ts` error branch now routes
through `parseApiError`. Files touched:

- `tickets.ts` — `request()` wrapper
- `projects.ts` — `request()` wrapper
- `people.ts` — `request()` wrapper
- `sprints.ts` — `request()` wrapper
- `audit.ts` — `listAgentActivity` (preserves `404 → []` early return)
- `notifications.ts` — `request()` wrapper (was bare `HTTP N` throw —
  now produces an `ApiError` with `code`/`message`/`correlation_id` like
  every other API client)
- `search.ts` — `searchV2()` (was bare `Search failed (N)` throw — now
  produces an `ApiError`)

Convergent pattern (matches `users.ts` / `auditLog.ts`):

```ts
const body = await res.json().catch(() => null);
const parsed = parseApiError(res, body);
throw new ApiError(res.status, {
  code: parsed.code,
  message: parsed.message,
  details: (parsed.details ?? undefined) as Record<string, unknown> | undefined,
  correlation_id: parsed.correlation_id ?? undefined,
});
```

The throw shape (`ApiError` with `ErrorEnvelope`) is preserved
byte-for-byte for the unified-envelope path that tests exercise — every
`instanceof ApiError` check and `.envelope?.code` consumer keeps working
unchanged. The behaviour delta is purely additive: legacy `{detail}`
bodies now surface a useful `.message` instead of `undefined`/`HTTP N`,
and `notifications.ts` / `search.ts` callers gain access to the
structured envelope they previously lost.

**Numbers.**

- API-layer files migrated by WP03: **7**.
- Plus WP09's 2 (`users.ts`, `auditLog.ts`) = **9 / 9** API-layer files
  now on `parseApiError`. Zero ad-hoc parsing remains under
  `frontend/src/api/`.
- Net frontend pytest delta: **241 → 241** (no behaviour change for the
  test surface; no new tests needed — adapter coverage already lives in
  `errors.ts` unit tests from WP09).
- Backend untouched: **1387** P / 0 F / 5 skipped / 14 xfailed.

**Lessons surviving WP03.**

1. **Permissive parser + thin convergent wrapper is the cheapest sweep
   shape.** Once `parseApiError` was in place from WP09, the seven
   migrations were each a ~10-line `request()` rewrite with no UI
   contract change. Total port time was bounded by file-read, not by
   API-design.

2. **`bare-throw` sites are silent UX bugs.** Both `notifications.ts`
   and `search.ts` previously surfaced literal `HTTP 403` strings to
   end users instead of the backend's structured `code` /
   `correlation_id`. The adapter makes those into one-line fixes
   rather than per-call-site bespoke handling.

3. **`ErrorEnvelope.details` is `Record<string,unknown> | undefined`
   on the constructor side, but `parsed.details` is `unknown | null`.**
   Bridging requires `(parsed.details ?? undefined) as Record<...>`
   — a noisy cast but unavoidable without widening the envelope type
   or narrowing the adapter return. Left alone in WP03; flagged for
   a possible adapter-type tightening in v2.14.

**Deferred follow-ups.**

1. **Page-level inline `fetch()` sweep (~60 sites).** Most live in
   `frontend/src/pages/admin/*.tsx`, `ProblemDetail.tsx`, `Submit.tsx`,
   `Feed.tsx` and hit the legacy `/api/...` (non-`v1`) surface, which
   has not itself been migrated to the unified envelope. Two sites
   read `.detail` directly: `Settings.tsx:380` reads
   `UpdateHandleError.detail` (already adapter-populated, no change
   needed) and `ProblemDetail.tsx:1305` is a one-off legacy-route
   alert. Track as **v2.14 candidate WP**: "page-level inline-fetch
   legacy-surface sweep" — but only after the legacy `/api/problems/*`
   / `/api/admin/*` routes themselves emit the unified envelope.

2. **`ErrorEnvelope.details` typing.** Either widen
   `ErrorEnvelope.details` to `unknown` (lossy but honest) or narrow
   `ParsedApiError.details` to `Record<string,unknown> | null` (forces
   the adapter to enforce the shape). Picks a side rather than the
   current cast-at-boundary.

---

## WP04 (B3) — request-side `*Create`/`*Update` schema contract pins

**Goal.** Mirror v2.12-WP03's response-side `ORM.to_dict ⊆ *Read`
pin onto the request side. For every `*Create`/`*Update` schema in
`app/schemas/`, every field must be referenced in the consumer
(route handler + service function, unioned). Catches the silent
bug class where Pydantic validates a field but the consumer drops
it on the floor.

**Mechanism.** `tests/test_request_schema_contract_pins_wp04.py` —
17 parametrized pair tests + 2 synthetic self-tests. AST walk over
each consumer module collects every `Attribute.attr`, every
`Constant(value=str)`, every `keyword.arg` name; assert
`schema.model_fields − excluded ⊆ those_names`. Helper:
`tests/helpers/source_lint.py:parse_module` (v2.12-WP02 — no new
abstraction).

**Polarity.** All 17 schemas are closed. Standard
`schema ⊆ consumer` direction. `excluded_fields` per-pair carries
OCC tokens (`version`) that the route strips before forwarding.

**Result.** Zero drift. All 17 pairs pass on first run; symmetric
with WP03's zero-drift landing. The pin is a regression net for
future work, not an active cleanup.

**Net delta.** +17 pair tests + 2 synthetic self-tests = +19.
Backend **1406 P / 0 F / 5 skipped / 14 xfailed**. Frontend
untouched at 241.

**Lessons (carry to v2.14).**

1. **The `mutable = {...}` allowlist pattern doubles as machine-
   readable contract.** Every PATCH service in this codebase holds
   an explicit `mutable` set string-literal allowlist; the WP04 lint
   reads those string literals to learn the contract surface. New
   PATCH services should keep this discipline — it's load-bearing
   for the lint AND for the runtime `ValidationError("not updatable
   via update()")` guard.

2. **Conservative-superset name collection is the right shape.**
   Walking ALL `Attribute.attr` (not gating on `value.id ==
   "payload"`) costs some false-positive looseness but avoids the
   false-negative cliff where a route renames its payload variable
   and the lint silently degrades to no-op. The seed's "false
   positives acceptable, false negatives are the bug" rule held.

3. **Closed schemas are the common case on the request side.**
   Unlike `*Read` schemas (where v2.11-WP07 needed `extra="allow"`
   for the `to_dict()` superset), no request schema in v2.13 uses
   `extra="allow"`. The polarity flip from WP03 never materialised.
   If a future PATCH adds `extra="allow"`, the WP04 lint should
   flip polarity to "consumer-required fields ⊆ schema.model_fields"
   per the seed's invariant.


---

## v2.13-WP05 (B2) — expand WP11 OpenAPI↔TS parity lint to generics + unions

**Pre-state.** v2.12-WP11 (`tests/test_openapi_ts_parity_wp11.py`)
pinned 9 flat closed-schema pairs but explicitly SKIPPED:
generic wrappers (`Page<T>`, `CursorPage<T>`, `ActivityPage`) and
discriminated unions (`ActivityItem`, `SearchV2Response.items[*]`).
The skip rationale: the WP11 parser had no `<T>` and no `type X = A | B`
handling.

WP05 fills both gaps with the smallest viable parser surface.

**What shipped.**

- `tests/test_openapi_ts_parity_wp05_v213.py` — new test module that
  imports the WP11 flat parser (`parse_ts_type`, `_resolve_schema`,
  `_capture_balanced_block`, `_properties_from_block_body`,
  `TsParseError`) and adds two narrow capabilities:
  - `parse_ts_generic_wrapper(name, source)` for
    `export interface <Name><T> { items: T[]; ... }`.
  - `parse_ts_union_alias(name, source)` for
    `export type <Name> = A | B | C;` (identifier-only RHS;
    string-literal unions raise).
- 5 parametrised page-wrapper pairs (`WP05_PAGE_PAIRS`):
  `Page_ProjectRead_`, `Page_ProjectMemberRead_`,
  `Page_ComponentRead_`, `Page_SprintRead_`,
  `Page_TicketNotificationRead_` — all ↔ `Page<T>` in
  `frontend/src/api/tickets.ts`.
- 1 parametrised discriminated-union pair (`WP05_UNION_PAIRS`):
  `ActivityPage.items[*]` (`oneOf [TransitionRead, CommentRead,
  LinkRead]` with `discriminator.propertyName=kind`) ↔
  `ActivityItem = TransitionActivityItem | CommentActivityItem |
  LinkActivityItem`. Asserts branch-count parity AND `kind`-required
  on every branch (both sides).
- 3 parametrised flat pairs WP11 had skipped (`WP05_FLAT_PAIRS`):
  `SearchArm`, `ActivityPage` outer, `SearchV2Response`.
- 6 synthetic-bad parser self-tests (≥3 required per v2.12-WP11
  lesson #6):
  1. generic-wrapper missing OpenAPI property → caught.
  2. generic-wrapper losing `items: T[]` → `unknown[]` → detected
     via `generic_item_prop=None`.
  3. union branch-count mismatch (OpenAPI 3 vs TS 2) → caught.
  4. string-literal union `type X = "a" | "b"` → `TsParseError`.
  5. WP11 greedy `[^{]*\{` regex regression guard — a preceding
     `type X = A | B;` alias must NOT be swallowed into the
     following interface's brace block.
  6. recursive items mismatch — `Page_X_.items.$ref → X → XDTO`
     glue verified by missing-inner-field synthetic.

**Strategy notes.**

1. **Sibling module, not bloat WP11.** Per prompt rule #6 ("extract a
   sibling helper only if you wind up with >300 LOC"), the WP05
   parser additions + tests landed at ~470 LOC. Put them in a new
   file that *imports* the WP11 helpers rather than inlining them
   — single source of truth for `_resolve_schema` /
   `_properties_from_block_body`.

2. **All 15 new tests passed first try — no real drift found.** The
   `Page<T>` wrapper field-set (`items`, `next_cursor`, `total`) is
   already aligned across all five Page consumers. The
   `ActivityItem` union has all three branches with `kind` required
   on both sides. SearchArm, SearchV2Response and ActivityPage outer
   wrapper field-sets all match.

3. **Skips documented in
   `.claude/lessons-learned/v2.13-wp05-diagnosis.md`:**
   - `Page_TicketRead_`, `Page_TicketWatcherRead_`,
     `Page_TicketAttachmentRead_`, `Page_AgentActivityItem_` — no
     hand-written `Page<T>` consumer in `frontend/src/api/*.ts`
     (UI inlines).
   - `CursorPage_ProblemResponse_` — bulletin domain; not in the
     ticketing api dir.
   - `SearchItem` recursion — permissive both sides (skip per
     WP11 polarity rule).

4. **`items_inner_ref` is the recursion glue.** The new
   `_resolve_page_wrapper()` helper returns the inner `$ref` name so
   future WP work can chain wrapper-level + inner-level parity into
   one parametrised case if desired. WP05 keeps them as separate
   parametrisations (wrapper-level here, inner-level still in WP11)
   to preserve precise error messages.

**Numbers.**

- Net pytest delta: 1406 → **1421** (+15 — 5 page-wrapper pairs +
  1 union pair + 3 flat pairs + 6 synthetic self-tests).
- Frontend: still **241 P / 0 F** (untouched).
- Files added: 1 test module + 1 diagnosis doc.
- Files touched: 0 (no production code changes — pure lint
  expansion).

**Lessons surviving WP05.**

1. **Sibling test modules beat bloating one canonical file.** When a
   parser grows >300 LOC, importing the helpers into a sibling module
   preserves the SSOT while letting the new module own its parser
   extensions, its parametrised inventory, and its synthetic-bad
   self-tests. The WP11 file stays the canonical "flat closed schema"
   reference; WP05 owns "generics + unions".

2. **The `[^{;]*\{` regression matters more than it looks.** The WP11
   greedy bug `[^{]*\{` could let a preceding `type X = A | B;` alias
   swallow into the following interface's brace block. WP05 adds an
   explicit regression test
   (`test_wp05_parser_does_not_swallow_union_into_next_interface`)
   so a future "simplification" can't silently re-introduce the bug.

3. **Discriminator narrowing requires `kind` to be REQUIRED on every
   branch.** The lint asserts `"kind" in parsed["required"]` (no
   `?:`) on each TS union branch — otherwise TypeScript can't
   narrow `if (item.kind === "comment")` and the union loses its
   exhaustiveness check.

4. **Generic-wrapper parity is two invariants, not one.** WP05
   checks (a) wrapper field-set ⊇ OpenAPI wrapper field-set AND
   (b) the wrapper's `items` property is still typed `T[]` — i.e.
   the generic parameterisation didn't degenerate to `unknown[]`.
   The second invariant is what makes the inner-shape WP11 lint
   keep its meaning at the consumer call site `Page<TicketRead>`.

**Deferred (won't fix in v2.13).**

- Intersection types (`A & B`) — TypeScript syntax this codebase
  doesn't use today. If a future PR introduces one, the parser will
  raise `TsParseError` and force the author to add either a parser
  branch or a documented skip.
- Mapped types (`{ [K in T]: ... }`), conditional types,
  multi-parameter generics (`<T, U>`), default generic parameters
  (`<T = unknown>`), nested generic params (`Page<Map<string, T>>`).
- `CursorPage<T>` — no hand-written TS counterpart in
  `frontend/src/api/*.ts` today (only emitted by the
  `/api/problems` bulletin endpoint, which the frontend consumes
  inline). Defer until the bulletin-domain frontend gets its own
  `api/problems.ts`.
- Generic *type aliases* (`type Page<T> = { ... }`) — not used by
  this codebase. The parser intentionally rejects them rather than
  supporting both `export interface ... <T>` and `export type ... <T>`.


---

## v2.13-WP06 (B1) — per-arm `refresh_total` semantics for `entity=all`

**Pre-state.** v2.11-WP14 added `refresh_total=1` to `/api/search/v2`;
backend already propagated it to every per-arm count fetch under
`entity=all`. v2.12-WP10 wired the banner+button for single-arm tabs
but hard-disabled the same UX on `entity=all` by returning
`totalAuthority=null` from the hook. The v2.11 seed left A5 open —
choose between (a) per-arm opt-in syntax or (b) all-arms-or-none.

**Decision: (b) all-arms-or-none.** Rationale logged in
`.claude/lessons-learned/v2.13-wp06-diagnosis.md` — overview tab is
the wrong place to demand per-arm cognitive load; cost-multiplier of
(a) is ~5x for marginal value; per-arm authority data is already on
the wire so the forward door stays open.

**What shipped.**

- Backend: zero code change (verified existing propagation). One
  new route test
  `test_refresh_total_all_recounts_every_arm` in
  `tests/routes/test_search_v2_refresh_total_wp14.py` — seeds rows
  across two arms, hits `entity=all&refresh_total=1`, asserts every
  populated arm reports `total_authority="live"` and a freshly-
  computed total.
- Frontend hook (`frontend/src/hooks/useSearchV2.ts`): `totalAuthority`
  now also surfaces on `entity=all`. Collapse rule: `"snapshot"` if
  ANY present arm reports snapshot, `"live"` only when EVERY present
  arm is live. `refreshTotal()` works without modification — the
  one-shot `refreshPendingRef` pattern fires the next request with
  `refresh_total=true` regardless of entity, and the backend
  broadcasts.
- Frontend page (`frontend/src/pages/Search.tsx`): banner condition
  extended. For `entity="all"` the `hasPrev` predicate is bypassed
  (no cursor chain) — banner shows whenever
  `totalAuthority === "snapshot"`. Plural copy: "Refresh counts" on
  the All tab, "Refresh count" on single-arm tabs.

**Numbers.**

- Backend net delta: 1421 → **1422** (+1).
- Frontend net delta: 241 → **243** (+2 — 1 hook test for the
  collapse rule + broadcast, 1 page test for All-tab banner +
  Refresh counts click; the existing "hidden on All tab" test was
  rewritten in place to reflect WP06's new behaviour).
- Files touched: `useSearchV2.ts`, `Search.tsx`,
  `tests/routes/test_search_v2_refresh_total_wp14.py`,
  `useSearchV2.test.ts`, `Search.test.tsx`, plus the new diagnosis
  doc.
- No backend service code changed; OpenAPI parity untouched (no
  schema change).

**Lessons surviving WP06.**

1. **The opt-in vs opt-out choice for refresh primitives should
   match the cognitive load of the surface.** Single-arm tabs are
   where users drill in and care about precision — opt-in (button +
   `refresh_total=1`) fits. Overview tabs are where users orient —
   all-or-none broadcast fits. The same `refresh_total` query param
   does both jobs; only the UX wrapping differs per surface.

2. **Backend service code that's already correctly threaded
   doesn't need a re-implementation pass — but it needs a route
   test that pins the contract.** v2.11-WP14 already propagated
   `refresh_total` to every arm; WP06 only adds the test that
   makes that propagation a tested invariant. Cheaper than
   re-deriving the implementation, but the regression net is the
   same.

3. **Collapsing per-arm state into a binary at the hook layer
   beats lifting multi-arm shape to the page.** The page never
   needs to know which arm is snapshot vs live — the banner has
   binary state. Computing the collapse inside the hook keeps the
   page consumer ignorant of the multi-arm shape and means a
   future banner consumer gets the same primitive for free.

**Deferred follow-ups.**

- Per-arm opt-in syntax (option (a)) — not built, not needed today.
  Forward door is open: change `refresh_total` from `boolean` to
  `boolean | string[]` and gate each `_search_<arm>` call on
  arm-presence-in-list. Per-arm `total_authority` data is already
  on the wire, so the upgrade is wire-shape only.

---

## v2.13 retrospective

### Headline numbers

- **Backend baseline:** 1354 P / 0 F / 5 skipped / 14 xfailed (v2.12 close).
- **Backend final:** **1422 P / 0 F / 5 skipped / 14 xfailed**.
- **Net delta:** +68 across 5 shipped WPs (WP02..WP06). Mix: +33
  alembic constraint emission guards + double-wrap synthetic (WP02),
  +0 from frontend-only WP03, +19 request-side contract pairs +
  synthetic-bad (WP04), +15 Page<T>/union/flat-skipped parity + 6
  parser self-tests (WP05), +1 entity=all all-arms-or-none route pin
  (WP06).
- **Frontend:** 241 → **243 P / 0 F**. +2 from WP06 (1 hook
  collapse-rule test + broadcast, 1 page All-tab banner + Refresh
  counts click; an existing "hidden on All tab" test was rewritten
  in place).
- **Production regressions introduced:** zero. Every WP held the
  green-suite invariant across its merge gate.

### WPs shipped

| WP | Bucket | Summary | Test delta |
| --- | --- | --- | --- |
| WP01 | G0 | Baseline verify (1354 P backend / 241 P frontend). | ±0 |
| WP02 | A1 | `ck` naming_convention resurrection. Closed v2.12-WP08 deferral. `conv()` wrap on full names in alembic (render-time no-op, no live DB rename); bare names in `app/models/`. 44 alembic sites wrapped across 5 files; new `a20_ck_alignment` marker migration (no-op). | +33 (1354→1387) |
| WP03 | A2 | `parseApiError` migration across 7 `frontend/src/api/*.ts` files (tickets/projects/people/sprints/audit/notifications/search). 2 latent silent-swallow bugs surfaced (notifications.ts + search.ts were throwing bare `Error("HTTP N")` losing code/correlation_id). | +0 backend / +0 frontend |
| WP04 | B3 | Request-side contract pins for 17 `*Create`/`*Update` schema pairs (polarity per-pair documented: schema ⊆ consumer-referenced-names ∪ excluded). Zero drift — existing `mutable = {...}` allowlist discipline + kwarg-fan-out already enforce. Now pinned. | +19 (1387→1406) |
| WP05 | B2 | Expanded WP11 OpenAPI↔TS parity lint to `Page<T>` generics + discriminated unions (`ActivityItem`). 5 Page<T> pairs + 1 union + 3 WP11-skipped flat + 6 synthetic-bad parser self-tests. Zero drift. Regression self-test pinning the WP11 `[^{;]*\{` parser fix. | +15 (1406→1421) |
| WP06 | B1 | Per-arm `refresh_total` for `entity=all` — decision (b) all-arms-or-none. Backend already correctly threaded; only route test pin added. Frontend hook collapses per-arm `total_authority` to binary; page extended for All-tab banner. Forward door open via per-arm `total_authority`. | +1 backend (1421→1422) / +2 frontend (241→243) |

### Production bugs caught

1. **WP03** — `frontend/src/api/notifications.ts` was throwing bare
   `throw new Error("HTTP ${status}")` with no body parse. Any
   structured envelope (`code`, `correlation_id`, `details`) was
   silently dropped before reaching the UI. Surfaced during the
   `parseApiError` audit; fix is the standard adapter port.
2. **WP03** — `frontend/src/api/search.ts` exhibited the same shape:
   bare `throw new Error("Search failed (${status})")` with no body
   parse. A user hitting a 422 (e.g. cursor-validation failure) saw
   only the status code; the descriptive backend `message` and the
   `correlation_id` needed for support handoff were lost. Same fix.
3. **WP02 (meta — scope reframe)** — v2.12-WP08 was scoped on
   "port every alembic literal to bare short names + live DB rename
   migration". That framing required N migration files of literal
   edits AND an alembic `RENAME CONSTRAINT` migration coordinated
   with production. WP02 reframed: `sqlalchemy.sql.elements.conv()`
   short-circuits convention substitution at DDL render time, so
   wrapping each `name="ck_..."` literal in `conv(...)` is a pure
   render-time no-op — production postgres never sees a new name,
   no rename migration is needed. The audit-rewrite avoided the
   live-rename class of bug entirely.
4. **WP02 (historical bugfix migration)** — the `7f57993c9b09`
   historical bugfix migration uses `op.batch_alter_table` + bare
   `CheckConstraint("...", name="ck_problems_status_lifecycle")`.
   Under the resurrected convention this would double-wrap. Resolved
   by `conv()` wrapping the literal name; rendered DDL is identical
   to pre-WP02 production reality. No live DB drift.
5. **WP05 (lint regression net)** — WP05 inherited the WP11 `[^{;]*\{`
   parser fix and pinned it with
   `test_wp05_parser_does_not_swallow_union_into_next_interface`. The
   parser bug is one regex away from coming back; the regression net
   now fails red if it does.
6. **WP05 (parser surface inventory)** — 6 TS syntactic shapes the
   parser intentionally rejects (generic aliases, intersection types,
   mapped/conditional, nested generics, multi-param generics, default
   generic params). Each is documented; future PRs that use any of
   these will fail the parser self-test and require a documented skip
   or a parser branch. Closed-shape parser surface.

### Cross-cutting lessons

1. **Reframe before rewrite.** v2.12-WP08 was scoped wrong — it took
   "port bare names everywhere + live DB rename" as the only path.
   WP02 reframed via `conv()` (render-time no-op) and the live
   rename evaporated. When a previous WP failed, audit the framing
   before retrying the same execution path. The class of saving is
   measured in dropped migration files and dropped production-risk
   change windows, not LOC.
2. **Zero-drift contract suites are still load-bearing.** Both WP04
   (17 request-side pairs) and WP05 (15 parity pairs + 6 parser
   self-tests) found zero real drift on first run. The value is
   regression prevention going forward, not bug discovery now. A
   contract suite that fires red only after a future change is
   doing its job — measuring it by "bugs found today" undervalues
   it. Land the pin and move on.
3. **Lints owe parser self-tests, not just assertion self-tests.**
   Carryover from v2.12 lesson #6, fully applied in WP05: 6 parser
   self-tests (the canonical `Page<T>`, an intersection `A & B`
   rejection, a mapped-type rejection, nested generics rejection,
   multi-param generics rejection, regression of the union-swallow
   regex). The WP11 parser bug that this catches would have silently
   greened any DTO it consumed; the rule is now structural rather
   than convention.
4. **One-shot pending-ref pattern generalises.** WP10's pending-ref
   primitive (single-arm refresh-count button) carried into WP06's
   `entity=all` broadcast with zero modification — the hook just
   broadcasts the same flag to every arm and the same collapse
   logic on read. Patterns that survive a second consumer with no
   delta are reference-grade. Reuse it for the next request-level
   transient-override surface.
5. **Forward-door deferrals.** WP06 chose option (b) all-arms-or-none
   but left the data path for option (a) in place — per-arm
   `total_authority` already lives on the wire and per-arm
   `refresh_total` plumbing is already correct in the backend. The
   upgrade path to (a) is a query-param shape change
   (`refresh_total: boolean | string[]`), not a model change. Defer
   features, but never defer the data path that unlocks them.
6. **Permissive-vs-closed polarity scales to the request side.** WP03
   pinned response-side polarity (closed → schema field appears in
   to_dict; permissive → required-fields appears). WP04 mirrors it
   on the request side (closed → schema field appears in consumer
   reference set; excluded set explicitly enumerates OCC tokens like
   `version` that the route strips before fan-out). The polarity
   bookkeeping is per-pair and explicit — half-pinned suites are
   silent green sinks.
7. **`conv()` over RENAME for SQLAlchemy convention adoption.** When
   bringing up a SQLAlchemy `naming_convention` key on a codebase
   that already has explicit names in production, the universal
   answer is `sqlalchemy.sql.elements.conv()` — wrap the literal at
   the migration site, the convention substitution short-circuits,
   and production DDL is identical. The "rename live constraints"
   path should be reserved for the case where you actually want the
   new name pattern in postgres metadata; that is rare.
8. **Frontend error-adapter porting is regression-net work.** WP03
   was mechanical for 5 of 7 files and discovered 2 silent-swallows
   on the other 2. The silent-swallow class is invisible in green
   suites because the test asserts only on status code. Adapter
   adoption is the only structural fix — code review never catches
   it because the `throw new Error("HTTP N")` shape reads as
   "obviously fine".

### What stayed deferred (carry to v2.14)

- **C7** — `decode_email_body` helper. No second QP-wrap consumer.
- **E3** — KindPill 7th surface. No new consumer.
- **E4** — `useSearchV2` ergonomic follow-ups. No second consumer.
- **F3** — TipTap second-consumer extraction. No second editor surface.
- **(Page-level frontend `parseApiError`)** — ~60 inline `fetch()` call
  sites in `frontend/src/pages/` still bypass the adapter. Mechanical;
  recommended only if a new error class needs structured frontend
  handling (today they're mostly status-code-only and ignore body).

### Files touched (rough stats)

- **Production code (`app/`):** ~2 files. Modified: `app/database.py`
  (WP02 `ck` key enabled). Untouched by WP03/WP04/WP05/WP06.
- **Alembic (`alembic/versions/`):** 5 migration files re-wrapped with
  `conv()` (a3, a7, a8, a9, a11) — 44 call sites. 1 new no-op marker
  migration (`a20_ck_alignment`).
- **Test code (`tests/`):** 5 new files.
  `tests/test_ck_naming_convention_wp02_v213.py` (WP02, 34 tests),
  `tests/test_request_schema_contract_wp04_v213.py` (WP04, 19 tests),
  `tests/test_openapi_ts_parity_wp05.py` (WP05, 15 tests),
  `tests/routes/test_search_v2_refresh_total_wp06_v213.py` (WP06, 1
  test).
- **Frontend (`frontend/`):** 7 API files migrated to `parseApiError`
  (tickets/projects/people/sprints/audit/notifications/search). WP06
  modified `useSearchV2.ts`, `Search.tsx`. WP06 tests:
  `useSearchV2.test.ts`, `Search.test.tsx`.
- **Docs (`.claude/lessons-learned/`):** 5 per-WP diagnosis files
  (`v2.13-wp02-diagnosis.md` through `v2.13-wp06-diagnosis.md`) + this
  retrospective + the v2.14 seed below.

---

## v2.14 starting prompt seed

v2.13 closed ALL 5 planned items (WP02..WP06) plus the v2.12-WP08
carry (the `ck` convention key resurrection, reframed via `conv()`
instead of a live rename). The four conditional v2.11 carry-forwards
(C7, E3, E4, F3) remain pending a triggering second-consumer need
and are not on the v2.14 critical path. v2.14's backlog is the
new-initiative bucket plus opportunistic carry-forwards if a real
user need surfaces.

### v2.14 backlog

#### Bucket A — Conditional v2.11 carry-forwards (act only on triggering need)

A1. **C7 — `decode_email_body` helper.** Pick up only on a second
    QP-wrap consumer.
A2. **E3 — KindPill 7th surface.** Pick up when a real consumer
    surfaces.
A3. **E4 — `useSearchV2` ergonomic follow-ups.** Pick up when a
    second consumer surfaces.
A4. **F3 — TipTap second-consumer extraction.** Pick up when a
    second editor surface lands.

#### Bucket B — New initiatives (open; need product/eng input)

B1. **Per-arm `refresh_total` opt-in syntax** — option (a) from
    WP06. Pick up if a real user need surfaces (e.g. an arm with
    a heavy `COUNT(*) OVER ()` cost that warrants opt-in refresh).
    Wire-shape change only: `refresh_total: boolean | string[]`;
    per-arm `total_authority` is already on the wire.
B2. **Extend WP05 lint coverage further** — nested generics,
    intersection types, multi-param generics, generic type aliases,
    mapped/conditional, default generic params. Currently parser-
    rejected with explicit self-tests; pick up when the first
    consumer in `frontend/src/api/*.ts` actually uses one of these
    shapes. The parser rejection is a forcing function — the
    first PR that needs it must extend the parser or document a
    skip.
B3. **Apply WP04's request-side contract pattern to `*Body` one-shot
    schemas** — `TicketTransitionBody`, `TicketAssignBody`, and the
    other 5 deferred from the WP04 diagnosis (7 schemas total). Same
    polarity bookkeeping; same per-pair `excluded` enumeration.
B4. **Performance pass on the OpenAPI parity lints** — WP05's test
    file boots the full app and parses TS per-test. If `pytest
    --durations=20` shows the WP05 / WP11 cluster creeping into
    multi-second territory, consolidate the OpenAPI-snapshot +
    TS-source-load fixtures into a session-scoped fixture and
    re-measure. Today the cost is acceptable; the watch is for
    creep, not absolute slowness.
B5. **Frontend `parseApiError` page-level migration** — ~60 inline
    `fetch()` call sites in `frontend/src/pages/` still bypass the
    adapter. Mechanical sweep; recommended only if a new error
    class needs structured frontend handling (today most page-level
    fetches are status-code-only and ignore body). Closes the WP09
    frontend tail completely.

#### Bucket C — Conditional (other carry)

C1. **WP09 frontend tail (page-level)** — depends on B5 trigger.

### v2.14 prompt seed (paste-ready)

> Proceed with v2.14 of the problem-bulletin ticketing system. v2.13
> retrospective + carry-forward backlog live at the bottom of
> `.claude/lessons-learned/ticketing-v2.13.md`. Baselines: backend
> **1422 P / 0 F / 5 skipped / 14 xfailed**, frontend **243 P / 0 F**.
> Bucket A items (C7, E3, E4, F3) are conditional carry-forwards from
> v2.11 — act ONLY on a triggering second-consumer need. Default work
> order: Bucket B (new initiatives — per-arm opt-in `refresh_total`,
> WP05 parser expansion, request-side `*Body` pins, parity-lint
> performance pass, page-level `parseApiError`) → Bucket C
> (conditional). Follow the sequential subagent loop pattern, TDD-
> first, one diagnosis doc per WP under
> `.claude/lessons-learned/v2.14-wpNN-diagnosis.md`. Append lessons to
> `.claude/lessons-learned/ticketing-v2.14.md`. Pre-flight any rename
> WP with `grep -rn` across `app/` AND `alembic/` before scoping
> (v2.12-WP08 / v2.13-WP02 precedent: prefer `conv()` over live
> RENAME for SQLAlchemy convention adoption). Do NOT reintroduce the
> `_v1_deferred.py` skip-hook — per-test deferral uses plain pytest
> markers.

