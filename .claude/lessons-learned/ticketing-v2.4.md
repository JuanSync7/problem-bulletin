# Ticketing v2.4 — Lessons Learned

Companion to `ticketing-v2.3.md`. Same TDD-loop / ralph-loop / one-subagent-at-a-time process.

## Cross-WP Rules (carry-forward + new)

1. **No new big abstractions** unless three call sites exist. WP26 is the documented extraction this cycle — two call sites today (drawer + page) with a third (inline-edit context in WP27) explicitly imminent.
2. **Migrations land as `a13+`**. `a12_add_handles` was v2.2's last head. One migration per WP that needs DB change. Always include `down_revision` + working downgrade.
3. **No regressions on the 306 baseline failures** (Postgres-only tests skipped on sqlite). New tests target new behavior; existing failures stay at 306.
4. **Frontend build (`npm run build`) and tests (`npm test -- --run`) must end green.** Red builds get reverted.
5. **All new endpoints under `/api/v1` with Pydantic Page[T] envelope** where lists are involved.
6. **Permissions live in services**, raise `PermissionDeniedError`, mapped 403 at routes by the global handler in `app/main.py`.
7. **Routes that are heavy stay lazy** (`React.lazy`).
8. **Each subagent appends `## WPnn — <title>` with Spec / Files touched / Tests / Lessons / Follow-ups for v2.5.**
9. **Spec parity**: subagent prompt is the contract. If the spec is wrong, document deviation and report before changing scope.
10. **Subagent reports include**: (a) what changed, (b) tests added/passing, (c) commands run to verify, (d) follow-ups for v2.5.
11. **NEW for v2.4**: Real-time work (WP31) must degrade gracefully — if WS is unavailable, the existing polling/one-shot fetch paths keep working. Don't make WS a hard dependency.
12. **NEW for v2.4**: Audit log writes are best-effort. They must NOT fail the parent transaction. Use SAVEPOINT or post-commit hook.

## v2.5 backlog seed (preserve)

Carried over + new items found this cycle:

- WP18 (deferred) — SQL UNION ALL for activity merge (trigger: >10k events/ticket).
- WP19 (deferred) — HMAC-signed cursors (trigger: public-facing pagination API ships).
- Per-status quotas on `GET /tickets` — alternative to last_activity_at; revisit if a hot project still starves.
- Per-lane height cap in Kanban swimlanes.
- Column width preference toggle (compact/normal/wide) over `--kanban-column-width`.
- Activity `total` on subsequent pages — currently null past page 1.
- Coalescing window for `ticket_state_change` as project config (today: hardcoded 60s).
- Profanity filter library for handles (today: reserved-words set only).
- Admin handle-override endpoint (moderation).
- Notification kinds beyond v2.4's set (e.g. `ticket_due_soon`, `ticket_resolved`).

---

## WP26 — Extract TicketFields + TicketActivityFeed

### Spec

Extract a read-only `TicketFields` presentational component (field grid, layout prop) and a `TicketActivityFeed` component (cursor-paginated activity timeline) so `TicketDetailDrawer` and `TicketDetail` page share them. Add the activity feed to the page (deferred from WP21).

### Files touched

**New:**
- `frontend/src/components/TicketFields/index.tsx` — presentational field grid; `layout="drawer"` renders stacked `div` rows; `layout="page"` renders a `<dl>` grid. Displays status badge, priority badge, assignee (with "Unassigned" fallback), reporter, project, story points, due date, labels, created/updated timestamps, version, and markdown description via existing `renderMarkdown`.
- `frontend/src/components/TicketFields/TicketFields.css` — co-located CSS; drawer variant is flex-column, page variant is 2-col grid. All CSS variables from existing design tokens.
- `frontend/src/components/TicketActivityFeed/index.tsx` — self-contained feed component. Calls `listActivity` with `include=["comments","links"]`. Initial-load + load-more cursor pattern matching MentionsTab. Separate loading/error/empty states. Renders transition, comment, and link rows with actor badge, step-id chip, and relative timestamp — identical markup to the former inline drawer feed (CSS class names preserved).
- `frontend/src/components/TicketFields/__tests__/TicketFields.test.tsx` — 17 tests.
- `frontend/src/components/TicketActivityFeed/__tests__/TicketActivityFeed.test.tsx` — 11 tests.

**Modified:**
- `frontend/src/pages/Kanban/TicketDetailDrawer.tsx` — removed inline field rendering (title, description static view) and inline activity state/fetch/render; replaced with `<TicketFields layout="drawer" />` and `<TicketActivityFeed />`. Activity feed is re-mounted (via `activityKey` counter) after a new comment is posted so it reflects the fresh item. Edit controls (status select, priority select, assignee input) and children subtree remain drawer-only, as specified.
- `frontend/src/pages/TicketDetail/index.tsx` — sidebar `<dl>` replaced with `<TicketFields layout="page" />`. Activity feed section added below description (was missing — WP21 deferred item). `renderMarkdown` import kept in the page for the description section (data-testid `ticket-description` preserved for WP21 test).
- `frontend/src/pages/TicketDetail/__tests__/TicketDetail.test.tsx` — added `listActivity` stub to the mock (needed since page now renders `TicketActivityFeed`); updated `ticket-project` → `tf-project` assertion (testid relocated to `TicketFields`).

### Tests

- **New tests:** 28 (17 TicketFields + 11 TicketActivityFeed).
- **Total passing:** 114 across 18 test files. Zero failures.
- Commands verified: `npm test -- --run` (all green), `npm run build` (clean, 3.35s).

### Lessons

1. **Re-mount pattern for feed refresh**: Rather than threading a `refresh()` callback into `TicketActivityFeed`, incrementing a `key` on the parent mount point causes React to unmount+remount the child — triggering a clean re-fetch. Simple and avoids prop-drilling a callback.
2. **listActivity mock gap**: The `TicketDetail` test suite only mocked `getTicket`. Adding `TicketActivityFeed` to the page meant `listActivity` was called without a mock, hitting jsdom with a real fetch attempt and silently dirtying the test environment. Always audit existing test mocks when adding new API-calling children.
3. **Testid migration policy**: `ticket-project` testid (in the old `TicketDetail` sidebar `<dl>`) moved to `tf-project` inside `TicketFields`. Updated the one assertion in the existing test per the spec's "update assertions only if text relocated" rule. All other existing testids (`ticket-title`, `ticket-status`, `ticket-priority`, `ticket-description`) remain in the page header/main section and were unaffected.
4. **CSS class names preserved**: Activity row classes (`ticket-drawer__activity-row`, `ticket-drawer__comment-meta`, `ticket-drawer__step-id`, `actor-badge`) are reused verbatim inside `TicketActivityFeed`. The drawer tests that assert on `activity-transition`, `activity-comment`, `activity-link`, `activity-step-id` continue to pass unchanged.

### Follow-ups for v2.5

- **WP27**: Inline edit affordances (title, status, priority, assignee) on the `TicketDetail` page — `TicketFields` is already structured to accept an `onSave` prop pattern without the read-only layout changing.
- Feed refresh in the drawer on status/priority/assignee change (currently the feed only re-fetches after a comment post). A WebSocket push (WP31) would solve this more cleanly than manual invalidation.
- `activity total` on subsequent pages is `null` past page 1 (backend limitation; tracked in v2.5 backlog).

## WP27 — Inline edit on /tickets/:displayId

### Spec

Add inline edit controls for status, priority, and assignee to the `/tickets/:displayId` standalone page. `TicketFields` stays purely presentational (Shape A). Edit controls live in the page component, mirroring the drawer's pattern exactly. After a successful mutation, bump an `activityKey` counter to re-mount `TicketActivityFeed` so it re-fetches. On mutation failure, render an error banner. No optimistic updates (the drawer does not use them).

### Files touched

**Modified:**
- `frontend/src/pages/TicketDetail/index.tsx` — added `transitionTicket`, `updateTicket`, `assignTicket` imports from the tickets API. Added `busy`, `mutateError`, `assigneeInput`, `activityKey` state variables. Added `onChangeStatus`, `onChangePriority`, `onSaveAssignee` handlers, each following the drawer's try/catch/finally pattern exactly. `applyServerTicket` sets ticket state, resets `assigneeInput`, and bumps `activityKey`. Edit controls (status select, priority select, assignee input + Save button) rendered in a `.ticket-detail__edit-controls` div below `<TicketFields>` in the sidebar. `TicketActivityFeed` now keyed on `${ticket.id}-${activityKey}` (matching the drawer). Mutation error banner with `data-testid="ticket-mutate-error"` shown below the header when `mutateError` is set.
- `frontend/src/pages/TicketDetail/TicketDetail.css` — added `.ticket-detail__mutate-error` error banner, `.ticket-detail__edit-controls` flex column container, `.ticket-detail__field` label+input row, `.ticket-detail__field-row` for the assignee input+button pair, and `.ticket-detail__btn` button. All styling uses existing CSS variables; control widths match the sidebar.
- `frontend/src/pages/TicketDetail/__tests__/TicketDetail.test.tsx` — added stubs for `transitionTicket`, `updateTicket`, `assignTicket` to the vi.mock block. Added 5 new WP27 tests (status change, priority change, assignee save, activity feed re-fetch after mutation, error banner on failure). `beforeEach` re-applies the `listActivity` stub after `vi.clearAllMocks()`.

### Tests

- **New WP27 tests:** 5.
- **TicketDetail suite total:** 10 (5 original + 5 new).
- **All tests:** 119 across 18 test files — zero failures.
- Commands verified: `npm test -- --run` (all green), `npm run build` (clean, 3.19s).

### Lessons

1. **Shape A is the right call here**: The drawer's edit controls already lived outside `TicketFields`. Mirroring that pattern on the page required zero changes to `TicketFields` and zero prop threading — the spec's shape A guidance was correct.
2. **`vi.clearAllMocks()` wipes `mockResolvedValue` stubs**: After adding `listActivity` to the mock in WP26, `beforeEach(() => vi.clearAllMocks())` strips its resolved value, causing the feed to hang. Fix: re-apply the `listActivity` stub at the top of `beforeEach`. Pattern to carry forward for any mock that must survive between tests.
3. **Activity feed re-fetch signal via key counter**: The same `activityKey` pattern from the drawer works identically on the page. No additional plumbing needed — bumping the key causes React to unmount+remount the feed, triggering a fresh `listActivity` call. Asserting `callsBefore < callsAfter` in the test is a clean, non-brittle way to verify this.
4. **No optimistic update rollback needed**: The drawer does not optimistically update state before the API responds; it only calls `setTicket` on success. WP27 follows the same pattern, so there is nothing to roll back on failure — the ticket state in React simply stays as-is and the error banner appears.

### Follow-ups for v2.5

- Feed refresh on status/priority/assignee change in the drawer itself (currently only re-fetches after comment post) — WebSocket push (WP31) is the cleaner fix.
- Title inline edit on the page (omitted per spec scope; `TicketFields` description row would need a contenteditable or a modal edit form).
- Keyboard accessibility for the edit controls (label/select association is done; need focus management after mutation success/failure).
- Consider a `PersonPicker` typeahead for assignee instead of a raw text input (drawer uses plain text today; upgrade both surfaces together in a later WP).

## WP28 — Expression index + audit log foundation

### Spec

Part A: Expression index on `tickets (COALESCE(last_activity_at, created_at) DESC, id DESC)` to support the WP22-introduced ordering without full-table scan. Part B: `activity_audit_log` table + `audit_log` service for admin-gated operations; wired into `project.create` and `users.update_handle` as best-effort call sites.

### Files touched

**New migrations:**
- `alembic/versions/a13_ticket_activity_index.py` (revision `a13`, down `a12`) — `CREATE INDEX CONCURRENTLY ix_tickets_activity_order` using `autocommit_block` (alembic 1.18.4 supports it).
- `alembic/versions/a14_audit_log.py` (revision `a14`, down `a13`) — `CREATE TABLE activity_audit_log` with 3 supporting indexes.

**New model:**
- `app/models/activity_audit_log.py` — `ActivityAuditLog` ORM class. Column attribute renamed `event_metadata` (DB column `metadata`) to avoid SQLAlchemy reserved name conflict.

**New service:**
- `app/services/audit_log.py` — `async def record(...)` using `session.begin_nested()` (SAVEPOINT) + broad `try/except Exception` to swallow failures without rolling back the parent TX.

**Modified:**
- `app/models/__init__.py` — registers `ActivityAuditLog`.
- `app/services/projects.py` — imports `audit_log`; calls `record(event="project.created", ...)` after successful flush + refresh.
- `app/services/users.py` — imports `audit_log`; captures old handle before update; calls `record(event="user.handle_changed", ...)` after successful update.

**New tests:**
- `tests/services/test_audit_log.py` — 3 tests: happy path insert, nullable-fields path, FK-violation failure isolation.
- Added `test_post_project_writes_audit_log` to `tests/routes/test_projects_permissions.py`.
- Added `test_patch_handle_writes_audit_log` to `tests/routes/test_users_handle.py`.

### Tests

- Targeted run: 34 passed, 0 failed.
- Full suite: 696 passed, 306 failed (unchanged baseline), 5 skipped, 14 xfailed.

### Lessons

1. **`metadata` is reserved in SQLAlchemy Declarative API.** Any model column named `metadata` will raise `InvalidRequestError` at class definition time. Fix: use an attribute alias (`event_metadata = mapped_column("metadata", ...)`). The DB column stays `metadata`; only the Python attribute name changes.
2. **`autocommit_block` is available in alembic 1.18.4.** `CONCURRENTLY` succeeded without fallback.
3. **`audit_log` table name was already taken** by `a2_agent_kanban`'s kanban event journal (`AuditLogEvent`). Named the new table `activity_audit_log` to avoid collision. The service and spec both refer to it conceptually as "audit log" — just the DB table name differs.
4. **SAVEPOINT isolation for best-effort writes:** `session.begin_nested()` creates a PG SAVEPOINT. On exception, SQLAlchemy rolls back to the savepoint but leaves the outer transaction intact. This is the correct pattern for "swallow and continue" audit writes inside an active async session.

### Follow-ups for v2.5

- Expose `GET /api/v1/admin/audit-log` with pagination (read access deliberately deferred from WP28).
- Backfill an index concurrently in a maintenance window if `CONCURRENTLY` was not used (not needed — it ran successfully here).
- Wire audit recording to additional admin-gated paths (e.g. `archive_project`, `remove_member`, handle admin-override).
- Add a `CREATE INDEX CONCURRENTLY` for the `activity_audit_log.created_at` column once table grows (today's regular index is fine at small scale).

## WP29 — Handle edit UI + rate limit

### Spec

Part A: server-side 24-hour rate limit on handle changes via a new `handle_changed_at TIMESTAMPTZ` column. Idempotent no-ops (same handle re-submitted) bypass both the cooldown check and the timestamp bump. Part B: Settings page Profile section with an `@`-prefixed handle input, client-side validation, and API call to `PATCH /api/v1/users/me/handle`. Responses: 200 success toast, 422 inline error, 409 "taken", 429 cooldown with `next_allowed_at`.

### Files touched

**New migrations:**
- `alembic/versions/a15_user_handle_changed_at.py` (revision `a15`, down `a14`) — adds `handle_changed_at TIMESTAMPTZ NULL` to `users`.

**Backend:**
- `app/models/user.py` — added `handle_changed_at` column (nullable DateTime with timezone).
- `app/services/exceptions.py` — added `HandleChangeTooSoonError` with `next_allowed_at` attribute.
- `app/services/users.py` — rewrote to: (1) fetch `current_handle + handle_changed_at` in one `SELECT`, (2) short-circuit on idempotent no-op, (3) enforce `HANDLE_CHANGE_COOLDOWN_SECONDS = 24 * 3600` cooldown, (4) bump `handle_changed_at = NOW()` in the same `UPDATE` as the handle change.
- `app/main.py` — added global `HandleChangeTooSoonError → 429` handler; body includes `next_allowed_at` ISO timestamp.

**Frontend:**
- `frontend/src/api/users.ts` — new file; `updateMyHandle(newHandle)` calling `PATCH /api/v1/users/me/handle`; throws typed `UpdateHandleError` with `status`, `detail`, `next_allowed_at?`.
- `frontend/src/pages/Settings.tsx` — added Profile section with `@`-prefixed handle input, client-side validation (`^[a-z0-9_]+$`, 3–32 chars, no leading `_`/digit), Save button disabled when unchanged/invalid/cooldown/saving. On 409 → "already taken" inline error. On 429 → cooldown message + Save disabled until timer expires. On 200 → success inline message, `fetchMe()` called to refresh auth context.
- `frontend/src/pages/Settings.css` — added profile field, handle prefix, message, and coming-soon styles.
- `frontend/src/pages/__tests__/Settings.test.tsx` — 5 new tests.

### Tests

**Backend (`tests/routes/test_users_handle.py`):**
- 3 new WP29 tests (429 on second change within 24h, second change after simulated 25h gap succeeds, idempotent no-op within 24h does not bump timestamp).
- Total in file: 24 passed (16 original + 1 WP28 audit + 3 WP29 rate limit).
- Time simulation: no freezegun (not installed); instead use `UPDATE users SET handle_changed_at = NOW() - INTERVAL '25 hours'` within the test transaction to simulate elapsed time.

**Frontend (`frontend/src/pages/__tests__/Settings.test.tsx`):**
- 5 tests: renders current handle, valid change calls API + shows success, 409 → taken message, 429 → cooldown message, invalid input disables Save.
- All 124 frontend tests pass.

**Full backend suite:** 699 passed, 306 failed (unchanged baseline).

**Build:** `npm run build` clean in 3.17s.

### Lessons

1. **`userEvent.type` appends, not replaces.** When an input starts with a value from `useEffect`, `userEvent.type("new")` appends to the existing value. `fireEvent.change(input, { target: { value: "new" } })` is the reliable replacement for tests where the initial value matters.
2. **Idempotent no-op must be detected before the rate-limit check.** The spec explicitly says "skip the cooldown check entirely when `new_handle == current_handle`". The current handle must be fetched from the DB before the comparison — the `user_mock` in tests is a mock, not the DB row, so its handle must be inserted into the actual DB row to test correctly.
3. **Time simulation without freezegun.** The test suite doesn't include freezegun. Rather than patching SQLAlchemy's `func.now()` (fragile), directly back-dating `handle_changed_at` via a raw SQL `UPDATE` inside the test transaction is cleaner and matches how the production code reads the value.
4. **`handle_changed_at` must be timezone-aware in the service.** The DB returns a timezone-aware datetime. The comparison with `datetime.now(tz=timezone.utc)` requires stripping or normalising naive datetimes — guard with `replace(tzinfo=timezone.utc)` when `tzinfo is None`.
5. **Settings page was already flat, not in a subdirectory.** `frontend/src/App.tsx` imports `./pages/Settings` which resolves to the flat `Settings.tsx`. No directory restructuring was needed; tests were placed in `frontend/src/pages/__tests__/Settings.test.tsx` to stay alongside the component.

### Follow-ups for v2.5

- Admin handle-override endpoint bypassing the cooldown (for moderation).
- Expose `handle_changed_at` in `/api/auth/me` or `/api/v1/users/me` so the frontend can pre-populate the cooldown timer on page load (currently the UI only knows the cooldown after a 429).
- Profanity/banned-words library for handles (deferred from v2.3).
- `GET /api/v1/admin/audit-log` with pagination (deferred from WP28).

## WP30 — Notification kinds expansion + agent-kind reads

### Spec

Three parallel tracks:

**A.** `mark_read` / `mark_all_read` in `TicketNotificationService` now accept `recipient_kind: Literal["user","agent"]` + `acting_user_id`. When `"agent"`, the service looks up `agent_accounts.created_by == acting_user_id` via `_resolve_owned_agent_ids()` helper and enforces ownership before UPDATE. Cross-owner attempts raise `PermissionDeniedError` → HTTP 403. Route `notifications_v1.py` passes `recipient_kind` and `acting_user_id=actor.id` through.

**B.** Two new notification kinds:
- `ticket_watcher_added` — emitted from `TicketService.add_watcher()` when a new watcher row is inserted. `add_watcher` gained an optional `actor` kwarg; callers that don't pass it see no change. Self-watch (actor == watcher) is silently skipped.
- `ticket_blocked` — emitted from `TicketService.transition()` when `to_status == TicketStatus.blocked`, in ADDITION to `ticket_state_change`. No coalescing; every block is independently interesting. Frontend `MentionsTab.tsx` renders "Watching · display_id" and "Blocked · display_id" with a `.mentions-row__badge--blocked` badge element.

**C.** Migration `a16_agent_account_created_by_backfill.py` (down_revision=a15). Uses a PL/pgSQL `DO $$ BEGIN IF EXISTS (...) THEN UPDATE ... END IF; END $$` block guarded on `users.role = 'admin'` (not `is_admin` — that column does not exist; role is a `varchar` with value `'admin'`). Test DB had no admin users — zero rows updated; migration still succeeded. Downgrade is no-op.

### Files touched

- `app/services/ticket_notifications.py` — `Literal` import; `_resolve_owned_agent_ids` static helper; `mark_read` / `mark_all_read` extended; `fanout_watcher_added` and `fanout_blocked` new methods.
- `app/routes/notifications_v1.py` — `mark_read` and `mark_all_read` routes accept `recipient_kind` query param.
- `app/services/tickets.py` — `transition()` emits `fanout_blocked` when `target == TicketStatus.blocked`; `add_watcher()` gains optional `actor` kwarg + `fanout_watcher_added` call.
- `frontend/src/pages/Activity/MentionsTab.tsx` — two new `case` branches in `renderKindLabel`.
- `frontend/src/pages/Activity/__tests__/MentionsTab.test.tsx` — 2 new test cases.
- `alembic/versions/a16_agent_account_created_by_backfill.py` — best-effort backfill.
- `tests/services/test_ticket_notifications_wp30.py` — 7 new service tests.
- `tests/routes/test_notifications_wp30.py` — 3 new route tests.

### Tests

- **Backend:** 75 tests across notification + ticket suites, all passing. 10 new WP30 service+route tests.
- **Frontend:** 126 tests across 19 files, all passing (was 115/18 before; MentionsTab suite grew from 9 to 11 tests).
- **Full suite baseline:** 710 passed, 306 failed (baseline unchanged), 5 skipped, 14 xfailed.

### Lessons

- `users.is_admin` does not exist — the `role` column holds `'admin'` as a string value. Always check the actual model before writing SQL in migrations. The guard pattern (DO $$...IF EXISTS...END IF...END $$) correctly makes the UPDATE optional.
- `fanout_watcher_added` wraps the INSERT in a SAVEPOINT (same pattern as `_coalesce_or_insert_state_change`) so any concurrent race does not abort the parent TX.
- `add_watcher` is idempotent (returns existing row when watcher already present). The notification is only emitted on the newly-inserted path — existing watcher rows short-circuit before the fanout.
- When adding `recipient_kind` to route params, remember to pass `acting_user_id` so the service has the right ownership anchor; do not re-use `recipient_id` for this purpose.

### Follow-ups for v2.5

- **NOT NULL on `agent_accounts.created_by`** — deferred. Once all environments have been migrated and confirmed to have no NULL rows, a follow-up migration can add the constraint (with a guard: only apply if no NULLs remain).
- `mark_all_read?recipient_kind=agent` could also accept explicit `agent_id` filter for UIs that display a single-agent inbox.
- Frontend `markAllRead` / `markRead` API calls do not yet pass `recipient_kind` for the agent tab — the current UI always calls with default `"user"`. WP31 realtime work should wire this through.
- `ticket_watcher_added` could also notify existing watchers ("someone else is now watching this ticket") — lower-priority, deferred.

## WP31 — WebSocket realtime notifications

### Spec

Added in-process pub/sub hub, per-user WS endpoint, and frontend reconnect hook. Publish best-effort after every notification write; no new deps.

### Files Touched

**Backend**
- `app/services/realtime.py` — new `Hub` singleton with `asyncio.Queue`-per-subscriber, bounded at 32, drop-on-full, `subscribe()` context manager.
- `app/services/ticket_notifications.py` — `_publish_notification()` helper called after every notification flush; `mark_read`/`mark_all_read` publish `notification_read`/`notification_read_all` payloads.
- `app/routes/realtime_ws.py` — new `@router.websocket("/v1/realtime/ws")` accepting JWT via `?token=` query param OR `access_token` cookie (HttpOnly cookie sent automatically on same-origin WS). Subscribes to `(user, user.id)` + `(agent, aid)` for each owned agent. Sends `{"type":"ready"}` on accept, heartbeat `{"type":"ping"}` every 25s.
- `app/main.py` — mounted `realtime_ws_router` under `/api`.

**Frontend**
- `frontend/src/realtime/useRealtimeNotifications.ts` — new hook: native WebSocket, auto-reconnect exponential backoff (1s→30s), visibility-aware pause/resume, SSR/test graceful degradation.
- `frontend/src/layouts/Sidebar.tsx` — wires `useRealtimeNotifications`; increments/decrements unread badge on `ticket_notification` / `notification_read` / `notification_read_all` payloads.
- `frontend/src/pages/Activity/MentionsTab.tsx` — wires `useRealtimeNotifications`; prepends optimistic stub row on `ticket_notification` payload while tab is mounted.

### Tests

**Backend** — `tests/routes/test_realtime_ws.py`: 7 tests.
- connect + ready frame
- publish received by connected client (queue injection)
- bad/missing token → 4401 close
- two clients same user both receive
- cross-user isolation
- agent subscription relays to owner

**Frontend** — 3 new suites:
- `frontend/src/realtime/__tests__/useRealtimeNotifications.test.tsx`: 7 tests (handshake, callback, ping no-op, status, reconnect backoff, hidden no-reconnect, SSR graceful degradation).
- `frontend/src/layouts/__tests__/Sidebar.test.tsx`: 4 tests (initial badge, increment, decrement, read-all).
- `frontend/src/pages/Activity/__tests__/MentionsTab.test.tsx`: 1 WP31 test appended (row prepend on WS payload). Total in file: 12.

### Test Counts

- Backend before: 710 passed / 306 failed. After: 717 passed / 306 failed (7 new, baseline unchanged).
- Frontend before: 19 files / 126 tests. After: 21 files / 139 tests (7 + 4 + 1 + 1 = 13 new tests split across new and extended files).
- Build: clean (`✓ built in ~3s`).

### Lessons

- `asyncio.Queue` as the per-subscriber buffer is the right primitive for in-process pub/sub. `put_nowait` + drop-on-full avoids ever blocking the publish path.
- `asyncio.create_task()` to schedule hub publishes ensures they run after the current coroutine yields (post-flush). The task fires in the same event loop as the session commit, so the WS payload's id is already persisted.
- For WS routes that use SAVEPOINTs (`_coalesce_or_insert_state_change`, `fanout_blocked`), we publish directly from the known parameters rather than re-fetching the row, since the statement has no `RETURNING` clause. The `id` field is `None` in those payloads — acceptable because the frontend only uses `target_display_id` for the badge increment.
- WS auth: browser HttpOnly cookie is sent automatically on same-origin WS connections — no JS token exposure required. `?token=` query param remains the primary path for agent/API clients that do have token access.
- Frontend WS mock pattern: define `MockWebSocket` class with `open()`/`triggerMessage()`/`triggerClose()` methods and capture instances in a static array; replace `globalThis.WebSocket` in `beforeEach`. This gives full control without a real network.
- `vi.mock()` for `useRealtimeNotifications` — capture the callback argument and expose it as `capturedCallback` for triggering payloads in tests. Much simpler than threading a real WS.

### Follow-ups for v2.5

- **Redis pub/sub** for multi-process/multi-worker scaling. The `Hub` interface (`publish` + `subscribe`) is stable — swap the implementation behind it.
- **`?token=` fetch endpoint**: provide a short-lived WS token via a `/api/v1/realtime/token` endpoint so agent/API clients that don't have cookie access get a well-scoped token (not the full 8h access JWT).
- **`notification_read` for agent-kind**: `mark_read(recipient_kind="agent")` only publishes to `recipient_type/recipient_id` of the row, not to the owning user's WS. A follow-up should also publish to `(user, acting_user_id)`.
- `mark_all_read?recipient_kind=agent` publishes to `recipient_type=user, recipient_id=acting_user_id` but the payload type is `notification_read_all` — frontend should decrement by count. Wire this through in the UI.
- MentionsTab prepend uses an optimistic stub (actor display_name = "…"). A follow-up could refetch the specific row by `id` to fill in the full actor object.
