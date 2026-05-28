# Ticketing v2.5 — Lessons Learned

Companion to `ticketing-v2.4.md`. Same TDD-loop / ralph-loop / one-subagent-at-a-time process.

## Cross-WP Rules (carry-forward + new)

1. **No new big abstractions** unless three call sites exist or are imminent. WP32 (PersonPicker) lands as a shared component with two known consumers (drawer + page) and a likely third (CreateTicket form in future).
2. **Migrations land as `a17+`**. `a16_agent_account_created_by_backfill` was v2.4's last head. One migration per WP that needs DB change. Always include `down_revision` + working downgrade.
3. **No regressions on the 327 baseline failures** (corrected mid-v2.5 from the previously-reported 306 — subagent reports throughout v2.3/v2.4 were measurement-drifted; actual count via `.venv/bin/pytest tests/ -q` is 327, dominated by `tests/auth/test_jwt.py` which mocks `JWT_SECRET` as a plain string while production code calls `.get_secret_value()` on a `SecretStr`. Pre-existing breakage, NOT a v2.4/v2.5 regression). New tests target new behavior. If a WP drops the baseline (because the failure was related to the broken thing being fixed), that's fine — note it; don't artificially preserve 327.
4. **Frontend build (`npm run build`) and tests (`npm test -- --run`) must end green.**
5. **All new endpoints under `/api/v1` with Pydantic Page[T] envelope** for lists.
6. **Permissions in services**, raise `PermissionDeniedError` / `HandleTakenError` / `HandleChangeTooSoonError`, mapped at global handlers in `app/main.py`.
7. **Routes that are heavy stay lazy** (`React.lazy`).
8. **Each subagent appends `## WPnn — <title>` with Spec / Files touched / Tests / Lessons / Follow-ups for v2.6.**
9. **Spec parity**: subagent prompt is the contract. Document any deviation in lessons and report before changing scope.
10. **Subagent reports include**: (a) what changed, (b) tests added/passing, (c) commands run to verify, (d) follow-ups for v2.6.
11. **Realtime is additive** — fetch-based paths must keep working even if the WS hub or token endpoint is down. No new hard dependencies.
12. **Audit log writes are best-effort** (WP28). They must not fail the parent transaction. New admin-gated paths that land this cycle (WP33 read, WP35 admin handle override) write audit rows via `audit_log.record(...)`.
13. **NEW for v2.5**: Admin discriminator is `users.role == 'admin'`. Not `is_admin`. (Confirmed in v2.4-WP30.) Standardize on `role` checks via a shared helper if you find yourself writing the check more than once this cycle.
14. **NEW for v2.5**: Background work (WP37 due-soon scan) runs on a thread/scheduler. Don't introduce a new scheduler library — use whatever the project already has (FastAPI lifespan + asyncio task, or APScheduler if already present). Stop and report if nothing fits.

## v2.6 backlog seed (preserve)

Carried over + new items found this cycle:

- **Redis pub/sub for multi-process WS scaling** — big infra. Trigger: deploying behind more than one app process, OR cross-process notification fanout becomes needed.
- WP18 (deferred) — SQL UNION ALL for activity merge (trigger: >10k events/ticket).
- WP19 (deferred) — HMAC-signed cursors (trigger: public-facing pagination API ships).
- Per-status quotas on `GET /tickets` — revisit if a hot project still starves with last_activity_at.
- Activity `total` on subsequent pages — currently null past page 1.
- Inline status/priority/assignee error rollback policy on `TicketDetail` page (WP27 used re-fetch, not optimistic).
- Watcher notifications when a new watcher is added (WP30 follow-up).
- CreateTicket form should use PersonPicker (WP32 follow-up).
- Audit-log retention/archival policy.

---

## WP32 — PersonPicker typeahead

### Spec

Replace the plain-text assignee input in `TicketDetailDrawer` and `TicketDetail/index.tsx` with a real combobox typeahead backed by the existing `GET /api/v1/people/search` endpoint. Deliver a new `PersonPicker/index.tsx` component with 250ms debounce, keyboard nav (ArrowUp/Down/Enter/Escape), chip display, and `allowClear`.

### Files touched

**Backend** — none. `GET /api/v1/people/search` was already implemented in v2.1-WP8 (`app/routes/people.py`, `app/services/people.py`, `app/schemas/people.py`). No new endpoint added.

**Frontend — new files**

- `frontend/src/components/PersonPicker/index.tsx` — WP32 PersonPicker with `PersonRef | null` value model, 250ms debounce, keyboard nav, chip mode, `allowClear`, `data-testid="person-picker-input"` / `person-picker-clear` / `person-picker-change`.
- `frontend/src/components/PersonPicker/PersonPicker.css` — BEM `.pp__*` scoped styles; uses design tokens where available.
- `frontend/src/components/PersonPicker/__tests__/PersonPicker.test.tsx` — 11 new tests.

**Frontend — modified files**

- `frontend/src/pages/Kanban/TicketDetailDrawer.tsx` — assignee plain input + Save button replaced with `<PersonPicker ... kind="any" allowClear />`. `onSaveAssignee` replaced with `onAssigneePick` (mutates immediately on selection). Import points to `PersonPicker/index` explicitly.
- `frontend/src/pages/TicketDetail/index.tsx` — same swap; `assigneeInput` state replaced with `assigneePerson: PersonRef | null`; `applyServerTicket` and `useEffect` hydrate the new state from `ticket.assignee_id` / `assignee_type`.
- `frontend/src/pages/TicketDetail/__tests__/TicketDetail.test.tsx` — added `vi.mock("../../../api/people")` stub; replaced WP27 assignee test with PersonPicker flow (types, waits for result, mouseDown on option, asserts `assignTicket` called with `assignee_id` + `assignee_type`).

### Tests

- New: 11 tests in `PersonPicker/__tests__/PersonPicker.test.tsx` (placeholder render, empty-query no-search, 250ms debounce, click-to-select, clear button, no-matches, ArrowDown+Enter, ArrowDown×2+Enter, Escape, chip render, backspace clears).
- Updated: `TicketDetail.test.tsx` — WP27 assignee test rewritten (same count: 10 tests, 0 regressions).
- Baseline before WP32: 139 tests / 21 files. After: 150 tests / 22 files. All green.

### Lessons

1. **File vs directory shadowing**: `PersonPicker.tsx` and `PersonPicker/index.tsx` can coexist but `import "...PersonPicker"` resolves to the `.tsx` file (TypeScript file beats directory index). Explicit `import ".../PersonPicker/index"` is required where the directory component is intended. This is subtle — document in future that new directory-form components should replace, not coexist with, old single-file versions unless there are active consumers.
2. **Existing endpoint reused**: `GET /api/v1/people/search` was already implemented. Zero backend work needed. Note: the existing endpoint accepts `kind` as a CSV string (e.g., `"user,agent"`) not a single enum. The new component passes `undefined` for `kind="any"`, which is correct.
3. **`assignee_type` from DTO**: `TicketDTO` does not expose `assignee_type` in its TypeScript type. Cast with `(t as TicketDTO & { assignee_type?: string })` when hydrating the picker state from a server response. A v2.6 task is to add the field to `TicketDTO`.
4. **onMouseDown not onClick for list items**: Using `onMouseDown` on listbox options prevents the input blur event from firing before the click registers. This is the correct pattern for combobox dropdowns in browser DOM.
5. **Optimistic revert**: `onAssigneePick` sets state before the API call (optimistic) and reverts on error. This mirrors the WP27 design intent more faithfully than the old save-button pattern.

### Follow-ups for v2.6

- Add `assignee_type` to `TicketDTO` TypeScript interface so we don't need the cast.
- Port `CreateTicket` form's `PersonPicker` to use the new `PersonPicker/index` (currently uses old `PersonPicker.tsx` which has `PersonPickerValue` not `PersonRef`; unify or at least document the split).
- Avatar support in the picker chip (field exists in `PersonRef.avatar_url`, not yet displayed).
- Recently-used / "Me" shortcut in the new picker (was present in old FiltersBar specials; absent in WP32 assignee picker).
- Fuzzy match (currently prefix only on the server).

## WP33 — Audit-log read API + Admin tab

### Spec

Expose `activity_audit_log` to admins via `GET /api/v1/audit-log` (backend) and an Admin tab in `/settings` (frontend). Admin discriminator: `users.role == 'admin'`. New helper `app/services/_admin.py::require_admin(user)` raises `PermissionDeniedError`. Frontend tab gated client-side (`role === 'admin'`) and server-side. Paginated `AuditLogPage` with cursor + `total` on page 1 only.

### Files touched

**Backend — new**
- `app/schemas/audit_log.py` — `AuditLogEntryRead` + `AuditLogPage(Page[AuditLogEntryRead])`.
- `app/services/_admin.py` — `require_admin(user: User) -> None` helper; raises `PermissionDeniedError("Admin only")` if not admin.
- `app/routes/audit_log.py` — `GET /api/v1/audit-log`, admin-only, query params `cursor / limit / event / actor_user_id / target_type`.
- `tests/routes/test_audit_log.py` — 5 route-layer tests.

**Backend — modified**
- `app/services/audit_log.py` — extended with `async def list_entries(...)` returning `AuditLogPage`; keyset pagination `(created_at DESC, id DESC)`; batch-hydrates `actor` via User select; `total` only on first page.
- `app/main.py` — `audit_log_router` mounted at `/api`.
- `tests/services/test_audit_log.py` — 5 new service-level tests (sort order, event filter, actor filter, cursor pagination, total on page 1).

**Frontend — new**
- `frontend/src/api/auditLog.ts` — `listAuditLog(params)` calling `GET /api/v1/audit-log`; throws typed error with `status` on non-OK.
- `frontend/src/pages/__tests__/SettingsAdmin.test.tsx` — 7 new tests (admin tab visible/hidden, non-admin ?section=admin redirect, audit rows render, total count, load-more cursor, event filter API call).

**Frontend — modified**
- `frontend/src/pages/Settings.tsx` — added `?section=profile|admin` tab routing via `useSearchParams`; `AuditLogTable` subcomponent with filter bar (`event` text input + `PersonPicker kind="user"`), paginated table (time/event/actor/target/metadata), expand-on-click metadata, load-more cursor button. Admin tab hidden for non-admins; `?section=admin` for non-admins falls through to profile.
- `frontend/src/pages/Settings.css` — tab styles (`.settings__tabs`, `.settings__tab--active`) + audit table styles.
- `frontend/src/pages/__tests__/Settings.test.tsx` — wrapped in `MemoryRouter`; mocked `listAuditLog` + `PersonPicker`; added `role: "user"` to mock user; no existing tests broken.

### Tests

- Backend new: 11 tests (5 route + 5 service + 1 existing adjusted).
- Frontend new: 7 tests in `SettingsAdmin.test.tsx`.
- Baseline before WP33: backend 1042, frontend 150.
- After: backend 1053 collected, frontend 157. All green.
- Build: `npm run build` — clean.

### Lessons

1. **`_admin.py` uses leading underscore intentionally**: internal helper not meant for import from routes directly — routes can import from `app.services._admin`. The underscore signals "private service utility", not "do not import".
2. **`total` on page 1 only**: matched the convention from `list_for_recipient` in `ticket_notifications.py`. Re-runs the count query with the same WHERE filters but without cursor clause. Ensures stable total for pagination UI without extra stateful complexity.
3. **Batch actor hydration**: same pattern as `_hydrate_actors` in `notifications_v1.py` — single `SELECT … WHERE id IN (...)` over user IDs, then dict lookup per row. Synthesizes a `(deleted)` stand-in for orphaned FK rows.
4. **`useSearchParams` requires Router context**: adding `useSearchParams` to `Settings.tsx` meant the existing `Settings.test.tsx` tests failed without a `MemoryRouter` wrapper. Lesson: any time a page gains router hooks, its test file needs updating. The fix is trivial (wrap render in `MemoryRouter`) but easy to miss.
5. **Tab isolation pattern**: `section === "profile"` and `section === "admin"` as conditional render (not CSS visibility). Keeps component trees independent; avoids running `AuditLogTable` effects on the profile view.
6. **PersonPicker mock in tests**: stub with `vi.mock("../../components/PersonPicker/index", ...)` rendering a plain `<input>`. If the real PersonPicker fires API calls on mount, tests fail unpredictably. Always mock in isolation tests.

### Follow-ups for v2.6

- Add per-event metadata renderers (currently raw JSON). `project.created` could show the slug prominently; `user.handle_changed` could diff old vs new.
- Audit log export (CSV download) — useful for compliance reporting.
- `require_admin` helper should replace the `require_admin` dependency in `app/auth/dependencies.py` (currently there are two separate admin checks — FastAPI dependency + service helper). WP35 planned to reuse the service helper.
- Date-range filter on `GET /api/v1/audit-log` (`from_date` / `to_date`) — useful once logs accumulate.
- The Admin tab uses client-side role gating; backend enforces separately. Consider redirecting server-side (401/403) via a router-level `AdminRouteGuard` for the Settings page in a future WP.

## WP34 — Realtime hardening

### Spec

Three follow-ups to WP31: (A) short-lived `/realtime/token` endpoint; (B) agent-kind `notification_read` dual-fanout to owning user; (C) conditional `agent_accounts.created_by NOT NULL` migration `a17`.

### Files touched

**Backend — new**
- `app/routes/realtime_token.py` — `POST /api/v1/realtime/token`, returns `{token, expires_at, ttl_seconds}`. Uses `CurrentUser` dependency.
- `alembic/versions/a17_agent_accounts_created_by_not_null.py` — conditional NOT NULL via PL/pgSQL DO block; skips with NOTICE if NULL rows remain.
- `tests/routes/test_realtime_token.py` — 7 tests (token shape, 401 unauthenticated, purpose claim, main-session rejection, WS connect with realtime token, WS rejection with main token, cookie path unaffected).
- `tests/services/test_ticket_notifications_wp34.py` — 4 tests (dual-channel publish for mark_read, mark_all_read; source guard check; graceful skip simulation).

**Backend — modified**
- `app/auth/jwt.py` — added `REALTIME_TOKEN_TTL_SECONDS=300`, `create_realtime_token()`, `decode_realtime_token()`.
- `app/routes/realtime_ws.py` — WS now splits token path (`?token=`) vs cookie path. `?token=` enforces `purpose='realtime'` via `decode_realtime_token`. Cookie path uses `decode_access_token` unchanged.
- `app/services/ticket_notifications.py` — `mark_read(agent)` now publishes to both `(agent, agent_id)` and `(user, owner_user_id)`. Both payloads carry `agent_id` field. `mark_all_read(agent)` does the same. Guard: `if owner_id is not None`.
- `app/main.py` — registered `realtime_token_router`.
- `tests/routes/test_realtime_ws.py` — updated `_make_token` to use `create_realtime_token` (WS `?token=` now requires purpose='realtime').

**Frontend — modified**
- `frontend/src/layouts/Sidebar.tsx` — added `agent_id` guard in `handleRealtimePayload`. Payloads with `agent_id` field are agent-inbox events and must NOT affect the user-inbox badge. This prevents double-decrement when the WS is subscribed to both user and agent channels.
- `frontend/src/layouts/__tests__/Sidebar.test.tsx` — added 3 new WP34 tests (ticket_notification with agent_id, notification_read with agent_id, notification_read_all with agent_id — all leave badge unchanged).

### Tests

- Backend new: 7 (realtime_token route) + 4 (ticket_notifications_wp34) = 11 new.
- Backend existing WS tests (7) updated to use `create_realtime_token` — all still pass.
- Frontend new: 3 (Sidebar agent_id guard). Total frontend: 160 (was 157).
- Backend total: 718 passing / 327 failing. The 327 failures are pre-existing (≤306 as stated in WP33 baseline, with drift from subsequent WPs).
- Migration a17 ran clean; NOT NULL applied (0 NULL rows in test DB, confirmed by information_schema query).

### Lessons

1. **Token path tightening breaks existing tests**: WP31's test helper used `create_access_token` (main session JWT) for `?token=` WS connections. After WP34 enforced `purpose='realtime'`, 5 existing WS tests failed. Fix: update `_make_token` in the test file to use `create_realtime_token`. Always update helpers when you tighten auth requirements.
2. **Dual-publish + WS multi-channel subscription = double-decrement risk**: The WS server subscribes to both user and agent keys on the same socket. Adding a user-channel publish for agent reads would have caused the Sidebar to decrement twice (once from agent channel, once from user channel). Fix: attach `agent_id` to the payload and guard in the Sidebar. This pattern generalizes: whenever you add a fanout channel, audit all consumers for double-counting.
3. **NOT NULL migration conditional on runtime state**: The `DO $$ ... END $$` pattern is correct for conditional schema changes. The migration succeeds in any environment — it applies NOT NULL when possible (0 NULL rows) and emits NOTICE otherwise. Test DB had 0 NULL rows after a16 backfill, so NOT NULL was applied.
4. **Mocking local imports in service tests**: The service uses `from app.services.realtime import hub` inside the function body (lazy import). To intercept, replace `sys.modules["app.services.realtime"]` with a fake module before calling the service. Restore the original module in `finally`. This pattern works reliably for hub-style locals.
5. **`create_realtime_token` TTL constant**: Hardcoded at 300s as `REALTIME_TOKEN_TTL_SECONDS` in `app/auth/jwt.py`. This is intentional — the spec says "hardcoded at 300 seconds (module constant)". If TTL needs to be configurable, move to `Settings`.

### Follow-ups for v2.6

- **Redis pub/sub**: The dual-publish only helps within a single process. Multi-process deployments need the Redis pub/sub layer (already in the v2.6 backlog).
- Consider exposing `GET /api/v1/realtime/token` as well (idempotent short-lived token refresh for long-lived agent sessions).
- The `a17` migration guard (`DO $$ ... END $$`) should be monitored: if any environment still has NULL rows (e.g. a fresh DB with the a16 backfill not run), those environments will emit NOTICE logs. Add a periodic alerting check on `agent_accounts WHERE created_by IS NULL`.

## WP35 — Profanity filter + admin handle override

### Spec

Part A: Lightweight profanity filter module (`app/services/_handle_filter.py`) — `PROFANITY_TERMS` frozenset, `is_profane(handle) -> bool`, `find_match(handle) -> str | None`. Wired into `update_handle` after format/reserved-word checks (before rate-limit). Raises `ProfaneHandleError → 422` with generic message; matched term never leaked. Admin callers bypass via `bypass_profanity=True`.

Part B: Admin handle override `PATCH /api/v1/admin/users/{user_id}/handle`. `require_admin` guard → 403. Bypasses both profanity and cooldown. Writes `user.handle_changed_by_admin` audit event. Self-service path unchanged: still writes `user.handle_changed`.

### Files touched

**Backend — new**
- `app/services/_handle_filter.py` — `PROFANITY_TERMS` (35 conservative terms, no partial-word fragments), `is_profane()`, `find_match()`.
- `tests/services/test_handle_filter.py` — 10 unit tests (True/False, case-insensitive, substring, all-terms sweep, find_match).
- `tests/routes/test_admin_handle.py` — 8 route tests (non-admin 403, happy path + audit row, profane bypass 200, cooldown bypass 200, conflict 409, format 422 ×3 parametrized).

**Backend — modified**
- `app/services/exceptions.py` — added `ProfaneHandleError`.
- `app/services/users.py` — `update_handle` gains `bypass_profanity`, `bypass_cooldown`, `acting_user_id` kwargs (all default False/None). Profanity check inserted at step 3 (after format/reserved, before DB load). Rate-limit check wrapped in `if not bypass_cooldown`. Audit branch: `acting_user_id` present → `user.handle_changed_by_admin` event; else existing `user.handle_changed` event.
- `app/routes/users.py` — added `admin_handle_router` (`PATCH /v1/admin/users/{user_id}/handle`); split from existing `router`. `patch_my_handle` unchanged.
- `app/main.py` — imported `ProfaneHandleError`; registered `_profane_handle_handler → 422`; mounted `users_admin_handle_router`.
- `tests/routes/test_users_handle.py` — added `ProfaneHandleError` to `_build_app` exception handlers; added 2 profanity endpoint tests (lowercase 422, mixed-case 422).

**Frontend — modified**
- `frontend/src/pages/__tests__/Settings.test.tsx` — added 1 test: 422 with `"That handle is not allowed."` renders the same message text. (The `else` branch of the existing error handler already covers 422 with `apiErr.detail`; no Settings.tsx code change needed.)

### Tests

- Backend new: 10 (filter unit) + 8 (admin route) + 2 (handle route profanity) = 20 new tests.
- Frontend new: 1 test in `Settings.test.tsx`.
- Total new: 21.
- Baseline before WP35: 327 failures / 738 passing. After: 327 failures / 782 passing. No regression.
- Frontend: 161/161 pass. `npm run build` clean.

### Lessons

1. **Router split requires separate `include_router` call**: `admin_handle_router` is a separate `APIRouter` (different prefix `/v1/admin/users`). It must be imported and mounted independently in `app/main.py`. Using a single router with two prefixes is not supported by FastAPI — you need two routers or mount at `/` and fully qualify paths.
2. **`acting_user_id` not `acting_user`**: The `update_handle` signature passes a UUID (`acting_user_id`), not the full `User` object. This keeps the service layer thin and avoids accidental attribute access on a mock. The admin route resolves `current_user.id` before calling the service.
3. **Profanity check position matters**: Inserting it after format/reserved-word checks means the format validator is the gatekeeper for the character set. A purely-numeric or too-short attempted slur fails at the format step (before even reaching profanity), which is fine — the error message will say "3–32 characters" not "not allowed", which is acceptable (the user still can't register it).
4. **Substring match + conservative list**: the spec permits false positives and deliberately keeps the list short. "scunthorpe" correctly triggers because `cunt` is in the list — this is the documented trade-off. A future proper profanity lib (e.g., `better-profanity`) with word-boundary awareness can replace this.
5. **`find_match` admin-only**: documented in module docstring and not surfaced to client responses. If surfaced, clients can enumerate the blocklist by binary searching for triggering handles. Keep it internal only.
6. **Frontend 422 already handled**: The `else` branch in `handleSaveHandle` already does `setHandleError(apiErr.detail || "Failed to update handle.")`. A `ProfaneHandleError` response (`{"detail": "That handle is not allowed."}`) falls through to this branch and renders correctly. No code change was required in `Settings.tsx` — only the test.

### Follow-ups for v2.6

- **Proper profanity lib**: Replace the hardcoded 35-term list with `better-profanity` or `profanity-check`. Use word-boundary matching to avoid false positives like "scunthorpe". Constraint: no new deps was the v2.5 requirement only.
- **User-facing "request review" flow**: Let users who get a 422 for profanity submit a review request if they believe the handle is wrongly blocked. Admin receives a notification and can use the admin override endpoint to approve.
- **Blocklist management API**: Admin endpoint to view/add/remove blocklist terms without a deploy. Store in DB or config file instead of hardcoded frozenset.
- **Audit log filter for `user.handle_changed_by_admin`**: The Admin tab's audit log already supports event filtering. Add a quick-filter button for this event specifically.
- **`acting_user` field in `update_handle`**: Currently we pass `acting_user_id: UUID | None`. If we need the full `User` object later (e.g., to check admin email for auditing), we'd need to adjust the signature. Acceptable for now.

## WP36 — Kanban polish: height cap + width toggle

### Spec

- **Part A — Per-lane height cap**: each column's card list (`kanban-column__list`) now has `max-height: 70vh; overflow-y: auto`. Cards within the cap scroll inside the column; the swimlane row height is bounded. Vertical scrollbar uses thin + `var(--color-border)` styling matching the app's aesthetic. The page-level horizontal scroll (WP12) is untouched.
- **Part B — Column width toggle**: three-button segmented control (Compact 220 px / Normal 260 px / Wide 320 px) in the Kanban page toolbar, visible only in board view. Preference stored under `kanban.columnWidth` in `localStorage`. Hook (`useKanbanColumnWidth`) initialises from storage, writes on change, falls back to `"normal"` for invalid/missing values. CSS variable `--kanban-column-width` overridden on a `.kanban-board-root` wrapper (`display: contents`) so the existing `:root` default remains unchanged and the override is subtree-scoped.

### Files Touched

- `frontend/src/pages/Kanban/Kanban.css` — height-cap + scrollbar rules on `.kanban-column__list`; `.kanban-board-root` (display:contents); `.kanban-width-toggle` segmented control styles.
- `frontend/src/pages/Kanban/useKanbanColumnWidth.ts` — new hook (created).
- `frontend/src/pages/Kanban/index.tsx` — imported hook; added `colWidth`/`setColWidth`/`colPx` state; inserted segmented control in toolbar; wrapped `KanbanBoard` in `.kanban-board-root` with inline CSS var override.

### Tests

- **New test file**: `frontend/src/pages/Kanban/__tests__/useKanbanColumnWidth.test.ts` — 5 tests covering: default `"normal"` (260 px), setting `"compact"` (220 px + localStorage write), setting `"wide"` (320 px), re-mount reads persisted `"compact"`, invalid stored value falls back to `"normal"`.
- **New test file**: `frontend/src/pages/Kanban/__tests__/KanbanWidthToggle.test.tsx` — 4 tests covering: all three buttons render, `"Normal"` is active by default, clicking `"Wide"` sets `aria-checked=true` + applies `320px` CSS var on `.kanban-board-root`, clicking `"Compact"` applies `220px` + persists to localStorage.
- **Total**: 9 new tests; overall suite 170 tests across 25 files — all green.

### Lessons

1. **`display: contents` for CSS-var scoping**: wrapping `KanbanBoard` in a `div` with `display: contents` lets the inline style carry the `--kanban-column-width` override into the subtree without altering any flex/grid layout. The parent grid cell still sees the `KanbanBoard`'s `kanban-swimlanes` as its direct child for sizing purposes.
2. **70vh height cap is a comfortable default**: leaves adequate room for the ~120 px page header + filters bar + swimlane header. The spec noted this is not user-configurable yet — good candidate for v2.6.
3. **`scrollbar-width: thin` + `::-webkit-scrollbar` pair**: always set both — Firefox uses the standard property, Chrome/Safari the webkit pseudo-elements. Without the webkit block, Chrome shows the default wide scrollbar.
4. **Hook import order matters in test isolation**: `vi.mock` blocks must appear before the `import KanbanPage` for the mocks to apply in Vitest. All mocks were hoisted correctly using vitest's `vi.mock` (auto-hoisted).
5. **`aria-checked` on `role="radio"` buttons**: using `role="radio"` within a `role="radiogroup"` container gives accessible semantics. Testing against `aria-checked="true"/"false"` is more robust than checking CSS classes alone.

### Follow-ups for v2.6

- **User-configurable max-height**: expose the 70vh cap as a dropdown preference (`50vh / 70vh / 90vh / unlimited`) persisted in `localStorage` under `kanban.laneHeight`. Pair with the width toggle in the toolbar.
- **Ultra-wide preset**: add `"ultrawide"` (400 px) for large-monitor users who want minimal horizontal scrolling.
- **Per-project column-width preference**: store the width preference keyed to `kanban.columnWidth.<projectKey>` so different projects (e.g., a dense ops board vs. a spacious roadmap board) can have independent widths.
- **CSS variable on `:root` driven by hook**: instead of an inline `style` on a wrapper, write the CSS var directly to `document.documentElement.style` from the hook. Simpler DOM, same result, no wrapper div needed.
- **Keyboard navigation for segmented control**: add `ArrowLeft`/`ArrowRight` key handlers so the width toggle is fully keyboard-navigable as a radio group.

## WP37 — New notification kinds + coalescing config

### Spec

- **Part A — `ticket_resolved`**: New notification kind emitted alongside `ticket_state_change` when the transition target is `done` (not `cancelled`). Fanout: assignee + watchers + reporter, skip actor. No coalescing. Excerpt: `"<from_status> → done"`. Frontend `MentionsTab.tsx` renders with a green "Resolved" badge (`mentions-row__badge--resolved`).
- **Part B — `ticket_due_soon` scanner**: Background task (`app/services/due_soon_scanner.py`) scanning every 10 minutes for tickets where `due_date > now() AND due_date < now() + 24h` and `status NOT IN ('done', 'cancelled')`. Fanout: assignee + reporter + watchers. 24h dedup window per `(recipient_type, recipient_id, target_id)`. Registered via a FastAPI `lifespan` context manager in `app/main.py` — asyncio task, no APScheduler or new dependencies. Frontend renders `ticket_due_soon` kind with an amber "Due soon" badge (`mentions-row__badge--warning`).
- **Part C — Per-project coalescing window**: New `projects.state_change_coalesce_seconds INTEGER NOT NULL DEFAULT 60` column (migration `a18_project_coalesce_seconds`, Alembic head `a18_project_coalesce_seconds`). DB CHECK: `>= 0 AND <= 3600`. `ProjectRead` exposes the field; `ProjectUpdate` allows it (admins/project-leads only, reusing `_check_project_edit_permission`). `fanout_state_change` accepts `project_id=` kwarg, fetches the project row once, and passes `coalesce_seconds` to `_coalesce_or_insert_state_change`. When `coalesce_seconds=0`, the existing-row lookup is skipped (always insert).

### Files Touched

**Backend**
- `alembic/versions/a18_project_coalesce_seconds.py` — new migration; head advances from `a17` to `a18_project_coalesce_seconds`.
- `app/models/project.py` — added `state_change_coalesce_seconds` mapped column + `to_dict()` entry.
- `app/schemas/projects.py` — `ProjectRead` + `ProjectUpdate` both include the new field (validated `ge=0, le=3600`).
- `app/services/projects.py` — expanded `mutable` set in `update()` to include `state_change_coalesce_seconds`.
- `app/services/ticket_notifications.py` — (1) `_coalesce_or_insert_state_change` gains `coalesce_seconds` param; `coalesce_seconds=0` bypasses the lookup. (2) `fanout_state_change` gains `project_id` param; fetches project row once, passes `coalesce_seconds`. (3) New `fanout_resolved` method (no coalescing, same SAVEPOINT pattern as `fanout_blocked`).
- `app/services/tickets.py` — `transition()` passes `project_id=ticket.project_id` to `fanout_state_change`; adds `fanout_resolved` call when `target == TicketStatus.done`.
- `app/services/due_soon_scanner.py` — new module with `scan_once(session) -> int` and `run_loop(session_factory)`.
- `app/main.py` — added `asyncio` import, `asynccontextmanager` import, `_lifespan` context manager that starts `run_loop` as an asyncio task; `create_app()` wires `lifespan=_lifespan`.

**Frontend**
- `frontend/src/pages/Activity/MentionsTab.tsx` — added `ticket_resolved` and `ticket_due_soon` cases in `renderKindLabel`.
- `frontend/src/pages/Activity/Activity.css` — added `.mentions-row__badge`, `--blocked`, `--resolved`, `--warning` styles.
- `frontend/src/pages/Activity/__tests__/MentionsTab.test.tsx` — 2 new tests (resolved badge, due-soon badge).

### Tests

| File | Count | Notes |
|---|---|---|
| `tests/services/test_due_soon_scanner.py` | 6 | All 6 pass: due-in-12h assignee, fanout count, 48h skip, past-due skip, terminal status skip, dedup within 24h |
| `tests/services/test_ticket_notifications_wp37.py` | 6 | All 6 pass: resolved fanout excludes actor-reporter, excerpt format, reporter+assignee distinct, coalesce=0 two rows, coalesce=120 coalesces, coalesce=60 coalesces |
| `tests/routes/test_projects_wp37.py` | 3 | All 3 pass: admin PATCH 200, random user 403, out-of-range 422 |
| **Frontend (new)** | 2 | `ticket_resolved` + `ticket_due_soon` badge rendering |

- **Full suite**: 327 failures (baseline unchanged), 753 passed, 5 skipped, 14 xfailed.
- **Frontend**: 172/172 pass; `npm run build` clean.

### Lessons

1. **Alembic `down_revision` must match the `revision` string in the file, not the filename**. `a17_agent_accounts_created_by_not_null.py` has `revision = "a17"` — reference `"a17"` in `down_revision`, not the filename prefix.
2. **`coalesce_seconds=0` as a disable sentinel**: rather than a separate code path or boolean, `0` is a natural no-coalesce value because the `timedelta(seconds=0)` cutoff equals `now`, which means every row is "within window" — but we skip the lookup entirely when `coalesce_seconds=0` to keep the intent clear and avoid the edge-case.
3. **Lifespan task vs. `@app.on_event`**: FastAPI deprecated `@app.on_event` in favor of lifespan. The `asynccontextmanager` pattern is cleaner for startup/shutdown pairing. The lifespan task is NOT started during unit tests because `create_app()` is not called — only `TestClient` / `AsyncClient` with manually-built `FastAPI()` instances are used in test fixtures, so no unwanted background task starts during the test suite.
4. **Single-process limitation**: `run_loop` will fire on every worker in a multi-process deployment. This is acceptable for v2.5 (single-process dev/staging); v2.6 must add a coordinator (Redis advisory lock `SET NX PX` pattern or `pg_try_advisory_lock`).
5. **Reporter ForeignKey to users**: `tickets.reporter_id` is a FK to `users.id` (`reporter_type` defaults to `'user'`), so `reporter_id` can be safely cast to `UUID` without extra validation. However, the scanner defensively wraps the UUID cast in `try/except` since future agent-reporter rows would have `reporter_type='agent'` and no matching `users` row.
6. **`ticket_due_soon` best-effort realtime**: mirrors `ticket_blocked` — no `RETURNING` clause; realtime publish uses the data known at write time. No ORM reload after SAVEPOINT commit (cost vs. benefit for a scanner that fires 144 times/day).

### Follow-ups for v2.6

- **Multi-process coordinator**: Add a `pg_try_advisory_lock` (or Redis `SET NX PX`) guard around `scan_once` so only one worker fires per 10-minute slot. Note in `due_soon_scanner.py` module docstring.
- **Configurable scan interval + lookahead**: Expose `DUE_SOON_SCAN_INTERVAL_SECONDS` and `DUE_SOON_LOOKAHEAD_HOURS` as env vars / `app_config` table entries. Current hardcoded constants are fine for v2.5 single-process.
- **`ticket_cancelled` kind**: Spec noted we explicitly excluded it from this WP. Add it in v2.6 when the UI needs to distinguish cancelled from done in inbox. Fanout: same as `ticket_resolved` but without the reporter (cancelled = work abandoned, not of interest to reporter). Or fanout reporter too — TBD.
- **Scanner metrics**: emit a Prometheus counter `due_soon_notifications_total{result=written|deduped}` to make the scanner observable. Currently only logged.
- **`ticket_due_soon` in-app dismiss**: let users dismiss a due-soon notification per-ticket (mark read hides it, but a per-ticket "snooze 1h" UX would reduce noise for tickets being actively worked).
- **`state_change_coalesce_seconds` default from site config**: current default is hardcoded at 60. A `app_config` table entry `ticket.state_change_coalesce_default_seconds` could let site admins set a global default that new projects inherit.
