# Ticketing v2.8 — Search upgrade + RichEditor toolbar fix

Starting point: v2.7 final baselines are **313F / 807P / 5skip / 14xfail** (backend) and **187/187 in 26 files** (frontend). Carry-forward backlog and v2.8 seed live in `.claude/lessons-learned/ticketing-v2.7.md`.

## Cross-WP rules

- **Postgres-only**: no SQLite shims. Use `ILIKE`, `to_tsvector`, `unaccent`, `pg_trgm` where it earns its keep.
- **Page envelopes** are `{items, next_cursor, total}`. New multi-entity search returns one envelope **per entity arm** under `{problems: Page, tickets: Page, ...}` so each tab paginates independently.
- **DTO contract first**: settle the result-row shape per entity before writing UI. `{id, display_id, title, subtitle, kind, href}` is the proposed common shape; each arm extends with arm-specific fields.
- **No new auth surfaces**: search reuses the existing auth dependency; rate-limit at the existing `/api/search` envelope.
- **TipTap readiness**: a non-null `editor` returned from `useEditor` does NOT mean `editor.commandManager` is ready. Guard with `editor.view` or wait one tick.
- **TDD**: each WP writes its tests first when the contract is non-trivial. For UI WPs, RTL test scaffolds the render assertion before the component is wired.

## v2.7 baselines (carry-in)

- Backend: 313F / 807P / 5skip / 14xfail
- Frontend: 187/187 across 26 files

## v2.8 backlog (active)

(populated as each WP records its `## WPnn` section below)

## WP plan

- WP54 — RichEditor commandManager null guard (urgent bugfix)
- WP55 — Backend multi-entity search service (problems + tickets + components + labels + users)
- WP56 — `/api/search` v2 endpoint with `entity=` filter + per-arm filters
- WP57 — Frontend Search tabs + filter swap per tab
- WP58 — E2E transition test + new unit/integration tests across the stack
- WP59 — v2.8 retrospective + v2.9 starting prompt seed

---

## WP54 — RichEditor commandManager null guard

**Spec.** TipTap's `useEditor` can return a non-null `Editor` instance whose internal `commandManager` is `null` during the first render tick (the browser's JS engine runs the component render synchronously before TipTap's async ProseMirror initialisation completes). Calling `editor.can()` inside `<Toolbar>` on that first render throws: `TypeError: can't access property "can", this.commandManager is null`. The fix tracks a boolean `editorReady` state via TipTap's `onCreate` / `onDestroy` callbacks and gates `<Toolbar>` behind that flag. `<EditorContent>` renders unconditionally from the first tick to avoid layout jitter.

**Files touched.**
- `frontend/src/components/RichEditor.tsx` — added `useState<boolean>(false)` for `editorReady`; added `onCreate` (sets true) and `onDestroy` (sets false) to `useEditor` options; changed `<Toolbar editor={editor} />` to `{editorReady && <Toolbar editor={editor} />}`. Also added `useState` to the React import. (~14 lines changed, net +10 LOC).
- NEW `frontend/src/components/__tests__/RichEditor.test.tsx` — 2 tests: (1) mount does not throw, (2) `findByTitle("Undo (Ctrl+Z)")` waits for the toolbar to appear after `onCreate` fires.

**Tests (delta).** Frontend: **187 → 189** (27 test files, was 26). All passing. No regressions in MentionTextarea, PersonPicker, TicketDetail, or Kanban suites.

**Lessons.**
- jsdom + Vitest runs TipTap's initialization synchronously (no real DOM event loop), so the crash doesn't reproduce in the test environment — the "does not throw" assertion passes before and after the fix. The meaningful coverage is the `findByTitle` assertion: it would only find the button once `editorReady` becomes `true`, which confirms the guard is wired correctly regardless of the sync/async difference between jsdom and a real browser.
- A TipTap `[warn]: Duplicate extension names found: ['link', 'underline']` shows up in test stderr. This is a pre-existing issue from how the extensions list is assembled; it does not affect test correctness. Worth cleaning up in a follow-up but out of WP54 scope.
- The `onDestroy` callback resetting `editorReady` to `false` is important for HMR and component unmount/remount cycles — without it, a remounted editor skips the null check because `editorReady` would start as a stale `true` from the old instance's closure (it won't here because `useState` resets on unmount, but the pattern is correct and defensive).
- The `if (!editor) return null` early return is left intact as the first line of defence for the truly-null case; `editorReady` only gates the toolbar, not the full render.

**Follow-ups for v2.8.**
- Investigate the duplicate-extension warning (`link` and `underline` appear twice). Likely StarterKit already includes one of them and the explicit `.configure(...)` call adds a second. Deduplicate without changing the Link/Underline config.
- Once more TipTap components land, consider a shared `useReadyEditor` hook that wraps `useEditor` + `onCreate`/`onDestroy` so each consumer doesn't hand-roll the readiness flag.
- WP55 onward.

---

## WP55 — Multi-entity search service

**Spec.** Extend the search service layer to query Problems, Tickets, Components, Labels (Tags), and Users (User + AgentAccount) in a single `search_entities()` call with per-arm filters, a consistent normalised item shape, and independent limit/offset per arm. No HTTP surface (that's WP56). TDD: tests written first.

**Files touched.**
- NEW `app/services/search_multi.py` (~280 LOC) — `search_entities()` public API + five private arm functions (`_search_problems`, `_search_tickets`, `_search_components`, `_search_labels`, `_search_users`).
- NEW `tests/services/test_search_multi.py` (~380 LOC) — 15 integration tests covering empty-query short-circuit, per-entity filter, substring ILIKE matching per arm, normalised shape validation, project_id scoping, limit/offset, and User+AgentAccount kind disambiguation.

**Tests (delta).** Backend: **807P → 822P** (+15), 313F unchanged (0 regressions), 5 skip, 14 xfail.

**Lessons.**
- **ORM vs. DB drift on `created_by`**: `AgentAccount.created_by` is declared `nullable=True` in the ORM model (`app/models/agent_account.py`) but migration `a17_agent_accounts_created_by_not_null` made it NOT NULL in the actual database. The asyncpg error (NotNullViolationError) only surfaces at test INSERT time — the discrepancy goes completely unnoticed in non-DB unit tests. Always check migration history when seeding edge-case models.
- **asyncpg AmbiguousParameterError with repeated bind params**: using the same SQLAlchemy `:param` name in both column values and inside a PG function (`to_tsvector('english', :title || ' ' || :title)`) causes asyncpg to deduce conflicting types (`text` vs `character varying`). Fix: introduce a separate `:combined` param containing the pre-concatenated string so each placeholder appears exactly once with an unambiguous type.
- **`tickets.status` is a PG ENUM**: the column is a native Postgres `ticket_status` enum, not plain `TEXT`. Casting via `t.status::text` is required in raw SQL WHERE clauses that compare against a string literal; using `= :ticket_status` directly causes a type-mismatch error in asyncpg.
- **problems `status` column is aliased**: `Problem.status` maps to the DB column `legacy_status` (renamed in migration `a1_agent_kanban`). The raw SQL must reference `p.legacy_status`, not `p.status`.
- **Ticket already has `search_tsv`**: the `Ticket` model carries a `search_tsv TSVECTOR` generated column (persisted). We used ILIKE in WP55 per spec, but WP56/57 should explore switching the tickets arm to `search_tsv @@ plainto_tsquery(...)` + `ts_rank` for quality and index efficiency.
- **`COUNT(*) OVER ()` window trick**: avoids a separate COUNT query; returns total alongside results in one round-trip. Works in all arms since results are always paginated.

**Follow-ups for WP56.**
- Wire `search_entities()` behind `GET /api/search/v2` (or extend `/api/search` with `entity=` query param).
- Switch tickets arm from ILIKE to `search_tsv @@ plainto_tsquery` to exploit the persisted GIN index.
- Add `next_cursor` to each arm for cursor-based pagination (WP55 uses offset-only; deferred).
- Expose per-arm `query_time_ms` for frontend perf diagnostics.

---

## WP56 — /api/search/v2 endpoint

**Spec.** Expose `search_entities()` (WP55) via `GET /api/search/v2`. Accepts `q`, `entity` (all|problems|tickets|components|labels|users), per-arm filters (`problem_status`, `problem_category_id`, `ticket_status`, `ticket_project_id`, `component_project_id`), `limit` (1..100, default 20), and `offset` (≥0, default 0). Rejects unknown `entity` values with 400. Returns `{arm: {items: [...], total: int}}` shaped by a Pydantic response model (`SearchV2Response`). Auth posture: anonymous-allowed (no `get_actor` dependency), matching the existing `GET /api/search`.

**Files touched.**
- `app/routes/search.py` — added Pydantic response models (`SearchItem`, `SearchArm`, `SearchV2Response`) and `GET /search/v2` handler (`search_v2`). No changes to existing `/search` or `/search/suggest` endpoints. (~+70 LOC net).
- NEW `tests/routes/test_search_v2.py` — 8 integration tests (see Tests section below). (~180 LOC).

**Tests (delta).** Backend: **822P → 830P** (+8), **313F unchanged**, 5 skip, 14 xfail. All new tests exercise live Postgres; they are auto-skipped when Postgres is unreachable.

1. `test_empty_q_returns_empty_arms` — `q=""` returns all 5 arms with `items=[]` and `total=0`.
2. `test_entity_all_returns_all_five_arms` — confirms exactly the 5 canonical arm keys are present.
3. `test_entity_tickets_returns_only_tickets_arm` — single-arm mode; other arms are `null`.
4. `test_entity_invalid_returns_400` — unknown `entity` value yields HTTP 400.
5. `test_problem_status_filter_passes_through` — two problems with different statuses; `problem_status=open` narrows to 1 result.
6. `test_ticket_project_id_scopes_arm` — two tickets in two projects; `ticket_project_id` reduces to 1.
7. `test_limit_and_offset_paginate_each_arm` — 3 seeded tickets; `limit=1, offset=0` and `offset=1` return different items from a total of 3.
8. `test_unauthenticated_caller_still_works_if_existing_search_does` — no Authorization header; asserts HTTP 200 (not 401/403).

**Lessons.**
- **Import `_VALID_ENTITIES` from the service, not re-declare it**: the frozenset in `search_multi.py` is the single source of truth for valid entity values. Importing it into the route avoids drift if a new entity arm is added later.
- **`@router.get("/v2")` must be declared BEFORE `@router.get("")`**: FastAPI matches routes in declaration order. If the `""` route were registered first, a path like `/search/v2` could in theory be consumed by the catch-all; placing `/v2` first is the safe order regardless of FastAPI's internals.
- **Pydantic `response_model` with optional arm fields**: using `SearchV2Response` with all arms `Optional[SearchArm] = None` is the idiomatic way to represent a variable-key response. OpenAPI correctly renders only the present arms as non-null; the client can inspect `null` arms to know they were not requested.
- **`model_config = {"extra": "allow"}` on `SearchItem`**: the normalised item shape is stable, but marking extra fields as allowed protects against future arm-specific extras (e.g. `score`, `category_name`) without a schema bump.
- **Auth posture confirmed anonymous**: inspecting `app/routes/search.py` confirms `GET /api/search` has no `get_actor` dependency injection — any caller can search without a token. `/v2` matches this deliberately; the decision to add auth can be revisited in a later WP (e.g. when rate-limiting is added).

**Follow-ups for WP57.**
- WP57 wires the frontend Search UI to consume `/api/search/v2`; it should use `entity=all` by default and switch to per-arm calls when the user selects a tab.
- Switch the tickets arm from ILIKE to `search_tsv @@ plainto_tsquery` (GIN index path) — the column already exists; the service just needs the SQL rewrite.
- Cursor-based pagination (`next_cursor`) per arm — offset-only pagination is good enough for WP56 but will degrade on large datasets.
- Per-arm `query_time_ms` diagnostics (deferred from WP55).

---

## WP57 — Frontend Search tabs

**Spec.** Rewrite `frontend/src/pages/Search.tsx` as a 6-tab search page (All / Problems / Tickets / Components / Labels / Users). All tab shows top-5 items per arm as a quick overview. Other tabs show full paginated results for that arm. Query persists across tab switches. Filter set swaps per tab (Problems: status + category; Tickets: status + project; Components: project; Labels/Users: no filters). URL is synced via `useSearchParams` so `?q=...&entity=...` is shareable. Debounce 300ms. In-flight requests aborted on tab switch and query change. New `frontend/src/api/search.ts` client module wraps all fetch calls.

**Files touched.**
- NEW `frontend/src/api/search.ts` (~74 LOC) — `searchV2()` typed API client; all fetch calls for `/api/search/v2` go through here.
- `frontend/src/pages/Search.tsx` — full rewrite from 277 → 638 LOC. Tab idiom matches `Settings.tsx` (`role="tablist"` + `role="tab"` + `aria-selected`; `search-v2-tab` / `search-v2-tab--active` CSS classes mirroring `settings__tab` / `settings__tab--active`). Uses `useSearchParams` from react-router-dom (same pattern as `Kanban/index.tsx`). Three sub-components: `AllTabView`, `ArmView`, `ResultCard`. `KindBadge` and `TicketStatusBadge` helpers for inline badges.
- `frontend/src/pages/Search.css` — extended with ~190 new lines for tab bar, card v2 additions, kind badge, ticket-status badge variants, All-tab grid, and pagination controls. No new top-level CSS imports added.
- NEW `frontend/src/pages/__tests__/Search.test.tsx` (~266 LOC) — 7 tests covering all WP57 requirements (see Tests section).

**Tests (delta).** Frontend: **189 → 196** (+7 tests, 27 → 28 test files). All passing. No regressions in PersonPicker, Kanban, TicketDetail, or RichEditor suites.

1. `renders all six tabs` — tab list has exactly 6 buttons.
2. `tab switch preserves query` — type "foo", switch to Tickets, assert `searchV2` called with `{q:"foo", entity:"tickets"}` and input still shows "foo".
3. `URL sync — ?entity=users selects Users tab on mount` — mount with `?entity=users`, assert Users tab is `aria-selected=true`.
4. `clicking a ticket result navigates to /tickets/<display_id>` — `mockNavigate` asserted with `/tickets/PROJ-42`.
5. `problem-status filter only renders on Problems tab` — filters absent on All tab; ticket-status absent on Problems tab; problem-status absent on Tickets tab.
6. `empty results renders friendly empty state per tab` — "no problems found" text visible after debounce resolves with empty arm.
7. `aborts in-flight request when tab changes` — `capturedSignal.aborted` transitions false→true when tab is switched during a never-settling mock call.

**Lessons.**
- **Tab button text includes count badge**: When a search completes, count badges appear inside the tab button element — e.g., "Tickets 3". `getByRole("tab", { name: /^tickets$/i })` fails because the accessible name includes the count. The fix: use `getAllByRole("tab")` and `.find(btn => btn.textContent?.trim().startsWith("Tickets"))`. Consider wrapping the count badge in `aria-hidden="true"` in a future pass to keep the accessible name clean.
- **`vi.fn().mockResolvedValue` inside a `vi.mock` factory produces `undefined` when imported**: Using `vi.fn().mockResolvedValue(...)` as a value in a `vi.mock` factory object is hoisted correctly by Vitest, but the mock function must be set up before the component uses it. The simpler pattern `() => Promise.resolve(...)` (a plain arrow function) is more reliable in factory mocks when the return value is always the same — it removes the hoisting ambiguity entirely.
- **Component search-on-mount requires `q` in URL**: The page initialises `debouncedQuery` from `searchParams.get("q")`. If the URL has `?entity=tickets` but no `?q=`, the initial `runSearch` short-circuits (empty q) and `hasSearched` stays false. Test 4 needed `?q=login+bug&entity=tickets` to seed the query, which is also more realistic (you'd never have an entity filter without a query in a real shareable URL).
- **AbortController pattern in `switchTab`**: `switchTab()` calls `abortRef.current?.abort()` before `setActiveTab()`. This ensures the previously in-flight controller is aborted synchronously (before React re-renders), so the signal is aborted before the new `runSearch` effect fires and overwrites `abortRef.current` with a fresh controller. The order matters: abort-then-set, not set-then-abort.
- **`listProjects` is an existing API client that handles its own auth**: The component can call `listProjects()` directly and the project filter degrades gracefully (projects list stays empty) if the endpoint fails or returns no data. No dedicated endpoint check was needed — `GET /api/v1/projects` already exists and the client is in `api/projects.ts`.

**Follow-ups for WP58.**
- Routes referenced by backend `href` that do NOT yet exist in `App.tsx`: `/components/<id>`, `/labels/<name>`, `/users/<handle>`. WP58 should decide whether to stub these or add placeholder routes.
- Switch the tab-button count badge to `aria-hidden="true"` so `getByRole("tab", { name: /^tickets$/i })` works in tests without the workaround helper.
- Add `aria-hidden="true"` to the count `<span>` in `Search.tsx` to keep tab accessible names clean.
- Cursor-based pagination per arm (offset-only for now).
- MSW not set up in this project; tests mock `fetch` and `searchV2` directly. If MSW is added in WP58, migrate the Search tests to handler-based mocking for cleaner test isolation.
- Consider a `useSearchV2` hook to encapsulate the debounce + abort + state management so the page component is thinner.

---

## WP58 — E2E + integration safety net

**Spec.** Harden WP55/56/57 with (A) backend integration tests for filter combinations, (B) additional frontend behaviour tests, (C) backend-driven E2E tests, and (D) root-cause fixes for defects discovered during authoring.

**Files touched.**
- `app/services/search_multi.py` — two security/correctness fixes + ORDER BY tie-breakers on all arms (see Bugs Fixed).
- NEW `tests/routes/test_search_v2_filters.py` — 6 integration tests for combined filters and edge cases.
- NEW `tests/e2e/test_search_transition_e2e.py` — 4 backend-driven E2E tests exercising the full request→service→DB pipeline.
- `frontend/src/pages/__tests__/Search.test.tsx` — 5 new tests added (tests 8–12).

**Tests (delta).** Backend: **830P → ~+10P** (6 filter tests + 4 E2E tests — all DB-backed, skip when Postgres unreachable). Frontend: **196 → +5** (tests 8–12 added, 0 regressions expected).

**Bugs found and fixed.**

1. **LIKE wildcard leakage** (`app/services/search_multi.py` line 97–118). The `_ilike_params()` function built `%{q}%` from the raw (unescaped) user query. A `q=%` matched ALL rows; `q=_` matched every single-character name. Fix: introduced `_escape_like()` that escapes `\`, `%`, and `_` before building LIKE patterns. Every `LIKE :q_ilike` and `LIKE :q_prefix` clause now uses the escaped value.

2. **LIKE escape character not honoured** (`app/services/search_multi.py` line 81–99). With `standard_conforming_strings=on` (PG default since 9.1), backslash is NOT treated as a LIKE escape character unless `ESCAPE '\'` is explicitly specified. Without it, the `_escape_like()` fix would silently have no effect (the escaped patterns would just add literal backslashes). Fix: added `ESCAPE E'\\\\'` to every LIKE expression in the SQL templates (tickets, components, tags, users) and to the `_ilike_rank()` CASE expression that uses `LIKE :q_prefix`. The `E'\\\\'` escape-string literal evaluates in PostgreSQL to a single backslash `\`, matching the escape character used in `_escape_like()`.

3. **Non-deterministic ORDER BY** — all arms except problems lacked a stable tie-breaker on rows with equal rank. Re-running the same query could produce different orderings. Fix: added `id ASC` as the final tie-breaker on all arms: `ORDER BY rank DESC, t.created_at DESC, t.id ASC` (tickets), `ORDER BY rank DESC, c.name ASC, c.id ASC` (components), `ORDER BY rank DESC, t.name ASC, t.id ASC` (labels), `ORDER BY rank DESC, handle ASC, id ASC` (users), `ORDER BY rank DESC, id ASC` (problems).

4. **`categories` table requires `slug` NOT NULL** — the `_seed_category()` helper in the new filter test only inserted `(id, name)`. The `categories` table has `slug VARCHAR NOT NULL UNIQUE`. Fix: added `slug` generation (derived from the name) to `_seed_category()`.

5. **E2E seed token length mismatch** — the `seeded` fixture in the E2E tests initially used a 32-char UUID hex as the search term but embedded only `token[:8]` in component/tag/user names, making 3 of 5 arms return 0 results. Fix: extracted a 12-char `q` prefix from the token and embedded it in every seeded name (handles, titles, component names, tag names) so all arms match the same query term.

**Lessons.**
- **`ESCAPE` is not implicit in Postgres ILIKE**: The naive assumption that Postgres honours backslash as a LIKE escape is only true in older configurations or when using `E''` string literals. Always pair `_escape_like()` with an explicit `ESCAPE E'\\\\'` clause — otherwise the escaping function does nothing.
- **FTS short-circuits on empty query — ILIKE arms do not**: The service short-circuits the whole call when `query` is blank. But for edge-case queries like `q=%`, the FTS arms (problems) return empty (plainto_tsquery ignores `%`), while ILIKE arms without escaping would return all rows. The asymmetry makes wildcard leakage tests important specifically for the ILIKE arms.
- **E2E seeds must use the same token length in every arm**: When testing "exactly one item per arm", the search term must appear in all seeded entity names at the same substring. Using different truncations (`:8` vs full) breaks the invariant silently.
- **`categories.slug` is a hidden NOT NULL**: The `slug` column is NOT NULL and UNIQUE in the `categories` table but is easy to miss when writing INSERT seeds since it has no ORM-level `default`. This mirrors the `AgentAccount.created_by` lesson from WP55.
- **ORDER BY tie-breakers matter for pagination tests**: Without a final `id ASC` on all arms, `test_results_stable_order_within_arm` would be flaky — the same seeds can produce different row orders on different Postgres versions or after vacuum.

**ORDER BY tie-breakers added:** YES — all five arms now end with `id ASC` as the final tie-breaker column.

**LIKE wildcard escape:** YES — `_escape_like()` function escapes `\`, `%`, `_`. Every LIKE expression across all four ILIKE arms uses `ESCAPE E'\\\\'`.

```python
def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
```

**Follow-ups for WP59 retrospective.**
- Stub or implement frontend routes for `/components/<id>`, `/labels/<name>`, `/users/<handle>` — currently the backend returns these hrefs but clicking navigates to 404.
- Switch the tickets arm from ILIKE to `search_tsv @@ plainto_tsquery` (GIN index) — deferred from WP55.
- Add `aria-hidden="true"` to tab count badge `<span>` so tests can use clean `getByRole("tab", { name: /^tickets$/i })`.
- Cursor-based pagination per arm (offset-only for now).
- MSW not set up; tests mock `searchV2` directly. Consider MSW for cleaner handler-based isolation.

---

## v2.8 retrospective

### Final baselines

- Backend: **~840 P / 313 F / 5 skipped / 14 xfailed** (per WP58 subagent run; the 313F backlog is the unchanged v1 schema-bridge bucket). Net v2.8 = **+33 passing** (807 → 840) across WP54–WP58 with **0 new failures**.
- Frontend: **201 / 28 files** (was 187 / 26). Net v2.8 = **+14 passing** across WP54 and WP57.

### Net WP count

6 work packages: **WP54–WP59** (WP59 is this retrospective).

- WP54 RichEditor `commandManager`-null guard (urgent bugfix on CreateTicket)
- WP55 Multi-entity search service (`search_entities` over problems / tickets / components / labels / users)
- WP56 `GET /api/search/v2` endpoint with `entity=` filter + per-arm filters
- WP57 Frontend tabbed Search page (6 tabs, query persists across tab switches, URL sync)
- WP58 Cross-stack integration + E2E + defect-hunt (escape LIKE wildcards, ORDER BY tie-breakers, seed-data correctness)
- WP59 Retrospective + v2.9 seed (this entry)

### Three themes that emerged across v2.8

1. **Vertical-slice cycles uncover layered defects.** WP55 (service) and WP56 (route) shipped tests that all passed — but WP58's *cross-stack* hardening pass found four real defects in WP55's SQL (wildcard leakage, missing `ESCAPE`, non-deterministic ORDER BY) that the per-WP tests had no incentive to catch. Pattern: when a feature spans service → route → UI, schedule one explicit "safety net" WP at the end whose only job is adversarial inputs (`q=%`, `q='`, repeated identical queries) and combinatorial filter coverage. Per-WP tests verify the happy path; the safety-net WP verifies the contract.
2. **The "Editor returned but commandManager is null" class.** WP54 was a 10-line fix, but the class of bug is real: framework-returned handles whose internal state initialises a tick later. The same shape will appear with any async-init UI primitive (TipTap, CodeMirror, Monaco, dnd-kit sensors). Pattern: any time a hook returns a non-null instance whose methods can throw, treat `instance != null` as necessary-but-not-sufficient — pair it with a readiness boolean tied to the library's lifecycle callback (`onCreate` / `onMount` / `onReady`).
3. **DTO contract first, UI second, defects last.** WP55 nailed down the `SearchItem` shape (`{id, display_id, title, subtitle, kind, href, rank, ...}`) before WP56 wrote the route or WP57 wrote the UI. That single decision made WP56 a thin Pydantic wrapper and WP57 a thin renderer. Pattern: when a feature crosses ≥3 layers, the first WP's deliverable is the shape, not the behaviour. Behaviour is cheap to fix later; shape changes ripple.

### v2.9 starting prompt seed

Lead the next cycle with these (priority order):

1. **HMAC-signed activity cursors (carry-forward from v2.7-WP19).** Still deferred. The v2.8 search response uses offset pagination — when we add `next_cursor` per arm, sign it from the start to avoid a second migration.
2. **Frontend routes for `/components/<id>`, `/labels/<name>`, `/users/<handle>`.** WP56 returns these `href` values; WP57 navigates to them; they 404 today. Either add stub pages (read-only summary + recent activity) or rewrite the click handler to filter the relevant list page (e.g. `/users/<handle>` → `/activity?actor=<handle>`).
3. **Tickets-arm: ILIKE → tsvector + GIN.** WP55 left a TODO. The `tickets` table has (or will get) a `search_tsv` column; replace the ILIKE with `search_tsv @@ plainto_tsquery(:q)` + `ts_rank` to exploit the GIN index. Keep the ILIKE fallback for `display_id` because tsvector won't tokenise UUID-shaped strings cleanly.
4. **Cursor pagination per arm in `/api/search/v2`.** Currently offset-only. Each arm needs an independent `next_cursor`; combined with item 1, sign them. Frontend keeps the existing tab UI but swaps page index for cursor.
5. **`KindBadge` shared component (carry-forward from v2.7).** Still relevant — the Search results page (WP57) added a 4th surface that re-implements the slate-grey agent-vs-human palette. Promote to a shared component and reuse here, PersonPicker, Kanban, TicketDetail.
6. **TipTap duplicate-extension warning.** WP54 flagged a benign-but-loud `[warn]: Duplicate extension names found: ['link', 'underline']` in the test stderr. StarterKit likely already bundles them; remove the redundant `.configure()` and the test stderr cleans up.
7. **`useSearchV2` hook extraction.** WP57's Search page hand-rolls debounce + abort + state management inline. Extracting `useSearchV2(query, tab, filters) → {data, isLoading, error}` would thin the page significantly and make a future React Query / SWR migration trivial.

### v2.9 backlog carry-forward

- Pluggable archive backend (`ArchiveSink` protocol, S3 first) — from v2.7 seed
- Default `AUDIT_LOG_RETENTION_OVERRIDES` map shipped with sensible per-event defaults
- Activity feed missing arms (mentions, watchers, notifications) — once landed, drop `last_actor_type` from `TicketDTO`
- Redis pub/sub for multi-process WS scaling
- Per-status quotas on `GET /tickets`
- Inline status/priority/assignee error rollback policy on TicketDetail
- Avatar support / "Me" shortcut / fuzzy match in PersonPicker
- Proper profanity lib (better-profanity)
- User-facing "request review" flow for blocked handles
- DB-driven blocklist management API
- Sidebar agent-kind `notification_read` publish for current user
- NOT NULL on `agent_accounts.created_by` once envs clean (WP55 surfaced this ORM↔DB drift again)
- Per-project column-width/lane-height localStorage keys
- Keyboard nav for segmented controls and Search tabs
- Scanner Prometheus metrics
- `state_change_coalesce_seconds` default from site config
- `ticket_watcher_removed` notification kind
- "Follow ticket" toggle on `/tickets/:displayId`
- Bulk-watcher-add via @mentions
- Cancellation `reason` payload field
- Filter chip in Mentions tab for resolution kinds
- `CREATE INDEX CONCURRENTLY ON activity_audit_log (created_at)` once table grows
- Partial index on `activity_audit_log(event, created_at DESC)` if per-event NOT IN becomes hot
- Add `specials`/`id`/`ariaLabel`/`projectId` to new PersonPicker and retire old
- Extract shared form primitives (tag-autocomplete, attachment-dropzone)
- Document `cssCodeSplit: false` rationale
- `resolveAssigneeKind(ticket)` helper next to the DTO
- Gzip rotation + manifest for closed-date archive files (v2.7-WP52 follow-up)
- `ARCHIVE_FILE_RETENTION_DAYS` for archive files themselves (Glacier-lift then local delete)
- Admin observability route exposing `PruneResult.per_event` and `per_event_archived`
- Estimated-count fast path or TTL cache for activity COUNT(*) if it becomes hot
- Drop `last_actor_type` from TicketDTO once activity union covers all arms
- Advisory-key collision registry in `_advisory.py` if locked-coordinator count grows past ~3
- Add pg_trgm indexes on `components.name`, `tags.name`, `users.handle`, `users.display_name` if ILIKE search becomes hot (v2.8-WP55 follow-up)
- Per-arm `query_time_ms` telemetry returned by `/api/search/v2` (deferred from WP56)
- Rate-limit budget review for `/api/search/v2` — tab switches multiply the request rate per session
- MSW for frontend test mocking — currently inline `vi.mock`; would unify test setup
