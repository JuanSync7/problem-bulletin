# Ticketing v2.2 — Lessons Learned

This file is **append-only per WP** and must be read by every subagent before it begins. Rules in "Cross-WP Rules" apply globally; "Per-WP" sections are historical context.

---

## Cross-WP Rules (apply to every WP)

1. **No big new abstractions.** v2.2 is a polish + cleanup pass on v2.0/v2.1. Reuse existing patterns:
   - `Page[T]` from `app/schemas/common.py` for any list endpoint.
   - `PersonRef`/`PeopleService` from v2.1-WP8 for any user-or-agent reference.
   - `agent_step_id_var` ContextVar + `AgentStepMiddleware` for actor plumbing.
   - `_stamp_last_activity()` on every ticket mutation (v2.1-WP6).

2. **Migrations: `a12` onward.** Heads as of v2.2 start: `a11_ticket_notifications`. Every new migration declares `down_revision = <previous a##>` and provides a working `downgrade()`.

3. **No regressions on the 306 pre-existing failing tests** (auth/health/magic-link). Baseline at v2.2 start: **597 backend passing / 56 frontend passing**. Every WP must end ≥ this baseline, with new tests adding to it.

4. **Frontend must build green.** `cd frontend && npm run build` must succeed; `npm test -- --run` must be green for everything you touched.

5. **API layering rule.** All new endpoints under `/api/v1`. Pydantic schema in `app/schemas/`, service in `app/services/`, route in `app/routes/`, registered in `app/routes/__init__.py`. No fat routes; no SQL in route handlers.

6. **Permissions live in services, not routes.** If a WP introduces auth checks, raise a dedicated exception (e.g. `PermissionDeniedError`) from the service and map it to 403 in the route. Never inline `if user.role != ...` in a handler.

7. **Lazy-load heavy frontend routes.** Any new page-level component goes through `React.lazy` + `Suspense` (match `RichEditor`/`CreateTicket` pattern). Bundle budget matters.

8. **Lessons file pattern.** At the end of each WP, append a `## WP## — <Title>` section with: Goal, What shipped, Files touched, Tests added (counts), Surprises / pitfalls, Follow-ups. Keep it scannable — bullets, not prose.

9. **Spec parity.** `docs/specs/ticketing-v2.md` is the spec source of truth. v2.2 changes get appended under a "v2.2 Addenda" section if they alter contracts; otherwise the file is unchanged.

10. **Subagent reports.** Every WP returns: summary of what changed, test counts before/after, regressions (must be zero), files touched, follow-ups for v2.3 backlog.

---

## Per-WP Sections (appended by each subagent)

<!-- WP12 onward will append here -->

## WP12 — Kanban Horizontal Scroll Fix

### Goal
Fix broken horizontal scroll on the 7-column Kanban board (Backlog → Done + Blocked + Cancelled). Symptoms: wrong ancestor scrolling, body-level horizontal scrollbar leaking, or columns overflowing the viewport instead of scrolling within a bounded container.

### Root cause
`.kanban-board` used `display: grid; grid-auto-columns: minmax(260px, 1fr)` — the `1fr` made columns elastic so the grid never actually overflowed its container (columns just grew wider). This meant no scroll was ever triggered, columns escaped beyond the viewport on wide screens, and the body gained an unintended horizontal scrollbar. Additionally, `.kanban-swimlanes` and `.kanban-swimlane` had no `min-width: 0` or `overflow-x` containment, allowing them to push the outer grid cell wider.

### What shipped
- **`Kanban.css`** (surgical CSS-only fix, no JSX changes):
  - Added `:root` block with `--kanban-column-width: 260px` and `--kanban-column-gap: 0.75rem` CSS variables.
  - Replaced `.kanban-board` from `display: grid / grid-auto-columns: minmax(260px, 1fr)` to `display: flex / flex-wrap: nowrap / overflow-x: auto / min-width: 0`. The flex row now overflows its parent correctly so the single `overflow-x: auto` creates exactly one scroll container per swimlane row.
  - Added `flex: 0 0 var(--kanban-column-width); width: var(--kanban-column-width)` to `.kanban-column` — stable fixed-width columns, no stretching.
  - Added `overflow-x: hidden; min-width: 0` to `.kanban-swimlanes` — bounds the swimlane wrapper inside its grid cell, preventing the board grid from widening the page.
  - Added `min-width: 0` to `.kanban-swimlane` — prevents individual swimlane rows from blowing out the grid cell.

### Files touched
- `frontend/src/pages/Kanban/Kanban.css` — CSS fix
- `frontend/src/pages/Kanban/__tests__/KanbanHorizontalScroll.test.tsx` — new test file

### Tests added
- 4 new RTL tests in `KanbanHorizontalScroll.test.tsx`:
  1. All 5 base column titles render inside exactly one `.kanban-board` row (no swimlane).
  2. All 7 column titles render when `showTerminal=true`.
  3. In swimlane mode each lane group gets its own `.kanban-board` row (no per-swimlane scroll drift).
  4. Every direct child of `.kanban-board` has `.kanban-column` class (fixed-width flex children).
- Frontend suite: **56 → 60 passing** (0 regressions).

### Surprises / pitfalls
- `overflow-x: hidden` on the swimlanes wrapper does NOT suppress scrolling inside `.kanban-board` children — the inner scroll container still works. The `hidden` only clips overflow from the wrapper element itself, which is the desired containment.
- `min-width: 0` is required on flex/grid items whose content overflows; without it, the item's min-content size overrides the `1fr` / flex-basis and pushes the outer grid wider even when `overflow-x: hidden` is set.
- No JSX changes were needed — the layout bug was entirely CSS.

### Follow-ups for v2.3
- Consider a `max-height` on `.kanban-swimlanes` or per-lane height cap so very long swimlane rows don't require excessive vertical scrolling.
- The `--kanban-column-width: 260px` variable can be exposed as a user preference (compact / normal / wide) via a toolbar toggle — foundation is now in place.
- On very narrow mobile viewports (<360px), a single column may still clip; a `@media (max-width: 400px) { :root { --kanban-column-width: 220px; } }` tweak may help ergonomics.

---

## WP13 — Activity Page + Nav Entry

### Goal
Create a first-class `/activity` page that is the canonical home for cross-ticket activity feeds. Remove the inline `AgentActivityFeed` from the Kanban page and replace it with a "View agent activity →" link. Add a Sidebar nav entry for Activity.

### What shipped
- **New page** `frontend/src/pages/Activity/index.tsx` — tabbed layout with 3 tabs (`agent` | `mentions` | `mine`), URL-synced via `useSearchParams`. Default tab: `agent`. Agent tab renders `AgentActivityFeed`; Mentions and My tickets are stubs with appropriate "Coming soon" copy.
- **New CSS** `frontend/src/pages/Activity/Activity.css` — page header, tab strip, tab panel styles using existing CSS variables.
- **App.tsx** — added `const ActivityPage = lazy(...)` + `<Route path="/activity" element={<ActivityPage />} />` matching the lazy-load pattern of all other routes.
- **Sidebar.tsx** — added `{ label: "Activity", to: "/activity" }` after Kanban Board entry.
- **Kanban/index.tsx** — removed `AgentActivityFeed` import + render; replaced with `<Link to="/activity?tab=agent">View agent activity →</Link>`. Added `Link` import from `react-router-dom`.

### Files touched
- `frontend/src/pages/Activity/index.tsx` — created
- `frontend/src/pages/Activity/Activity.css` — created
- `frontend/src/pages/Activity/__tests__/Activity.test.tsx` — created
- `frontend/src/App.tsx` — added lazy import + route
- `frontend/src/layouts/Sidebar.tsx` — added Activity nav entry
- `frontend/src/pages/Kanban/index.tsx` — removed AgentActivityFeed usage, added Link

### Tests added
- 4 new RTL tests in `Activity.test.tsx`:
  1. `/activity` renders agent tab active by default (no `?tab=` param).
  2. Clicking Mentions tab updates `aria-selected` and renders mentions stub with `data-tab="mentions"`.
  3. Visiting `/activity?tab=mine` directly renders mine stub with `data-tab="mine"`.
  4. Agent tab panel renders `AgentActivityFeed` (verifies `aria-label="Agent activity feed"` present in DOM).
- Frontend suite: **60 → 64 passing** (0 regressions).

### Surprises / pitfalls
- `useSearchParams` requires the component to be rendered inside a Router; tests use `MemoryRouter` with `initialEntries` to simulate both bare `/activity` and `?tab=...` variants. No issues.
- The `isValidTab` guard function ensures unknown `?tab=` values fall back to `"agent"` without throwing, keeping the page robust against stale links.
- `AgentActivityFeed.tsx` was not modified per constraint — it is imported directly from its Kanban location into the Activity page.

### Follow-ups for v2.3
- WP14: implement real Mentions API + wire up the `mentions` tab panel.
- `mine` tab (v2.3): query `listTickets({ assignee_id: "me" })` and render a compact ticket list.
- Consider adding a project-selector on the Activity page so the `AgentActivityFeed` can be scoped by project (currently renders without `projectId`, showing all projects).
- The Kanban "View agent activity →" link could carry the current `projectId` as a query param so the Activity page pre-filters to that project.

---

## WP14 — Notifications UI in /activity

### Goal
Surface the existing `ticket_notifications` rows in a first-class inbox under the Mentions tab on `/activity`. Three endpoints (list/unread_count/mark-read/mark-all) + frontend.

### What shipped
- **Service** (`app/services/ticket_notifications.py`): added `list_for_recipient` (cursor-paginated, base64-JSON `{t,i}` cursors matching the tickets endpoint), `mark_read` (per-row permission check via `PermissionDeniedError`), `mark_all_read`, `unread_count`. Cursor helpers `_encode_cursor`/`_decode_cursor` duplicated locally rather than moved — the tickets module owns the canonical pair and a refactor was rejected as too invasive for a polish WP. Cursor *wire shape* is identical so a future shared `_pagination` module is a trivial follow-up.
- **Schema** (`app/schemas/notifications.py`): `TicketNotificationRead` with embedded `PersonRef actor`, plus `UnreadCountResponse`/`MarkAllReadResponse`. Listing uses `Page[TicketNotificationRead]` (Rule #1).
- **Route** (`app/routes/notifications_v1.py`, mounted at `/api/v1/notifications`): kept separate from the legacy `/api/notifications` router which targets the bulletin-domain `notifications` table. Inbox is keyed on `recipient_type="user"` and the authenticated user UUID; agent actors get 403 at the route boundary. Batch-hydrates `actor` via single `WHERE id IN (...)` per kind to avoid N+1.
- **Exception** (`app/services/exceptions.py`): new generic `PermissionDeniedError` (distinct from `app.exceptions.ForbiddenError` which carries ticket-domain context). Route maps to 403.
- **Frontend** (`frontend/src/api/notifications.ts`): typed client (`listNotifications`, `getUnreadCount`, `markRead`, `markAllRead`); reuses `Page<T>` re-exported from `api/tickets`.
- **MentionsTab** (`frontend/src/pages/Activity/MentionsTab.tsx`): All/Unread toggle (default Unread), header chip + Mark-all-read, optimistic per-row mark-read, navigate to `/board?ticket=<display_id>`, Load-more for cursor pages. Empty/error/total UI.
- **Sidebar** unread badge: cheap one-shot `getUnreadCount` on mount; silently 0 on failure. No realtime, no polling.
- **WP13 Activity test** was updated — the Mentions panel now asserts presence of `MentionsTab` instead of the "Coming soon (WP14)" stub.

### Files touched
- New: `app/schemas/notifications.py`, `app/services/exceptions.py`, `app/routes/notifications_v1.py`, `tests/services/test_ticket_notifications.py`, `tests/routes/test_notifications.py`, `frontend/src/api/notifications.ts`, `frontend/src/pages/Activity/MentionsTab.tsx`, `frontend/src/pages/Activity/__tests__/MentionsTab.test.tsx`.
- Modified: `app/services/ticket_notifications.py` (added inbox methods + cursor helpers), `app/main.py` (registered v1 router), `frontend/src/pages/Activity/index.tsx` (replaced stub), `frontend/src/pages/Activity/Activity.css` (mentions + badge styles), `frontend/src/layouts/Sidebar.tsx` (unread badge + import), `frontend/src/pages/Activity/__tests__/Activity.test.tsx` (mock new API + updated mentions panel assertion).

### Tests added
- 7 service tests in `tests/services/test_ticket_notifications.py`: recipient isolation, cursor round-trip, only_unread filter, mark_read happy path, mark_read 403, mark_all_read count + idempotency, unread_count.
- 4 route tests in `tests/routes/test_notifications.py`: 401 unauthenticated, list with actor resolution, mark-read 204 + unread_count drop, mark-read other-recipient → 403.
- 4 frontend tests in `MentionsTab.test.tsx`: empty state, row rendering, All/Unread toggle re-fetch, click → markRead + navigate.
- Backend suite: **597 → 608 passing** (+11, 0 regressions; pre-existing 306 baseline failures intact).
- Frontend suite: **64 → 68 passing** (+4, 0 regressions).

### Surprises / pitfalls
- A `/api/notifications` router already existed (bulletin-domain `notifications` table). Resisted overloading it — both tables remain, the v1 ticket inbox is a new endpoint. Path coexistence: legacy at `/api/notifications`, ticket inbox at `/api/v1/notifications`. Consumers of the legacy endpoint are unaffected.
- `_encode_cursor`/`_decode_cursor` live in TWO modules now (`tickets`, `ticket_notifications`). Wire shape is byte-identical so cursors are interchangeable; the duplication is small and deliberate. **Follow-up** below for the consolidation.
- `Page[TicketNotificationRead]` returns `total` always (cheap — count is a single-row aggregate scoped by `(recipient_type, recipient_id)`). Differs from tickets endpoint which only sets `total` when scoped by `project_id`.
- The `WP13 Activity.test.tsx` had to be tweaked: it asserted `/coming soon.*wp14/i` inside `panel-mentions`. That assertion is now `panel.querySelector('[data-testid="mentions-tab"]')` + the new API is mocked. No other WP13 behavior changes.
- React-Router-Dom `MemoryRouter` + `useNavigate` in tests requires routing both source and destination paths under `<Routes>` to observe URL changes — solved by a tiny `<LocationProbe>` component rendered on both `/activity` and `/board`.
- Sidebar's `getUnreadCount` fires for every page on which the Sidebar is mounted. For an unauthenticated user (e.g. login page) the request 401's silently; the badge stays 0. Acceptable for v2.2.

### Follow-ups for v2.3
- Extract `_encode_cursor` / `_decode_cursor` to `app/services/_pagination.py` and re-export from both `tickets` and `ticket_notifications`. Trivial mechanical refactor; deferred because it touches `tickets.py` (a 1700-line hot module).
- Sidebar badge is a one-shot fetch; if WP-future adds realtime ticket events on websockets, the badge could subscribe and increment without polling.
- The `/activity?tab=mentions` URL is mounted but the `?tab=mentions` route can be promoted to a stand-alone `/inbox` route later if mention volume warrants it (out of scope here per the brief).
- Mentions row navigates to `/board?ticket=<display_id>`. There is no `/tickets/:id` deep-link route in v2.2 — when that ships (v2.3 candidate), update the navigation target.
- Add a `kind` filter (`ticket_mention` vs future `ticket_assigned` etc.) once new notification kinds are introduced.
- Agent recipients are supported by the service layer but rejected at the route (`_require_user_actor`). Once agents grow a UI of their own, expose `recipient_type="agent"` as a query parameter.
- Agent recipients are supported by the service layer but rejected at the route (`_require_user_actor`). Once agents grow a UI of their own, expose `recipient_type="agent"` as a query parameter.

---

## WP15 — Project PATCH permissions

### Goal
Move project-edit enforcement from cosmetic client-side gate to server. PATCH /api/v1/projects/{id} (and members/components sub-routes) must return 403 for callers who are neither admin nor the project's user-lead.

### What shipped
- **`app/services/projects.py`**: Added `_check_project_edit_permission(session, project_id, user) → Project`. Reuses `get_or_raise`; admin bypasses; `lead_type=="user" AND lead_id==user.id` allows; else raises `PermissionDeniedError`. `update()` and `update_member_role()` and `remove_member()` all take new required kwarg `acting_user` and delegate to the helper.
- **`app/services/components.py`**: `update()` and `delete()` take `acting_user` and call `project_service._check_project_edit_permission` after fetching the component. Added `await session.refresh(c)` at end of `update()` (prevents `MissingGreenlet` when to_dict() is called after inner SELECT expires the ORM object).
- **`app/main.py`**: Registered global `@app.exception_handler(PermissionDeniedError)` → 403 JSON response.
- **`app/routes/projects.py`**: Injected `current_user: CurrentUser` into PATCH project, PATCH/DELETE member, PATCH/DELETE component handlers. Each wraps service calls in try/except `PermissionDeniedError → HTTPException(403)`.
- **Frontend `WipLimitsDialog.tsx`**: Added `e.status === 403` branch → `"You don't have permission to edit this project."`. Updated doc comment: "Server-enforced as of v2.2-WP15; this is UX-only."
- **Frontend `Kanban/index.tsx`**: Updated comment on lead gate: "Server-enforced as of v2.2-WP15; this is UX-only."

### Files touched
- `app/services/projects.py` — helper + update/update_member_role/remove_member signatures
- `app/services/components.py` — update/delete signatures + session.refresh fix
- `app/main.py` — PermissionDeniedError handler
- `app/routes/projects.py` — CurrentUser injection + try/except wrappers
- `frontend/src/pages/Kanban/WipLimitsDialog.tsx` — 403 error branch + comment
- `frontend/src/pages/Kanban/index.tsx` — comment update
- `tests/routes/test_projects_permissions.py` — new (7 tests)
- `tests/services/test_project_permissions.py` — new (3 tests)
- `tests/services/test_projects_service.py` — updated 2 tests to pass acting_user=admin
- `tests/routes/test_project_wip_limits.py` — updated _build_app to override get_current_user

### Tests added
- 7 route tests in `test_projects_permissions.py`: lead→200, admin→200, random→403, no-auth→401, agent-led-user→403, component-lead→200, component-random→403.
- 3 service tests in `test_project_permissions.py`: admin bypass, PermissionDeniedError for non-lead-non-admin, user-lead allowed.
- Backend: **608 → 618 passing** (+10, 0 regressions; pre-existing 306 baseline failures intact).
- Frontend: **68 → 68 passing** (0 regressions; 403 branch covered by existing WipLimitsDialog snapshot test).

### Surprises / pitfalls
- `session.refresh(c)` required in `ComponentService.update()` after the permission-check SELECT expires the component ORM object. Without it, `to_dict()` triggers `MissingGreenlet` because SQLAlchemy tries a lazy load outside a greenlet context. Pattern now matches `ProjectService.update()`.
- Existing tests for `project_service.update()` and `remove_member()` needed `acting_user` added. Used mock admin user (`MagicMock` with `role=UserRole.admin`) — no live DB row needed for service-only permission bypass.
- `test_project_wip_limits.py` already overrode `get_actor` but not `get_current_user` (new dependency). Added `_gcu` override with a mock admin user in `_build_app`. All 5 WIP tests still green.

### Follow-ups for v2.3
- Gate POST /projects (project creation) to admin-only — per spec it is out-of-scope for WP15.
- Gate archive/unarchive/delete endpoints similarly (currently open to any authenticated user).
- The `update_member_role` / `remove_member` restriction (lead-only) may be too strict in teams where project members should be able to self-remove; reconsider in v2.3.

---

## WP16 — ActivityPage cursor retrofit

### Goal
Replace offset-based pagination on `GET /api/v1/tickets/{id_or_key}/transitions` with cursor-based pagination, reusing the same opaque `_encode_cursor`/`_decode_cursor` helpers as `GET /api/v1/tickets`.

### What shipped
- **`app/schemas/tickets.py`**: `ActivityPage` changed from a standalone `BaseModel` to `class ActivityPage(Page[ActivityItem]): pass`. Added `from app.schemas.common import Page` import. The subclass approach (vs bare alias) avoids FastAPI response_model generic-resolution issues.
- **`app/services/tickets.py`** `list_activity()`: replaced `offset: int = 0` with `cursor: str | None = None`. After Python-side UNION + sort, applies `_decode_cursor` filter to drop items at-or-newer-than the anchor. Slices to `bounded` items. Sets `next_cursor = _encode_cursor(last.created_at, last.id)` when the slice was full. `total` is set only on the first page (`cursor is None`) to avoid O(N) counts on every "load more" — returns `None` on subsequent pages.
- **`app/routes/tickets.py`**: replaced `offset: int = Query(default=0, ge=0)` with `cursor: Optional[str] = Query(default=None)`. `InvalidCursorError` (subclass of `ValidationError`) is already mapped to 400 by the existing `EXCEPTION_HANDLERS` — no new handler needed.
- **`frontend/src/api/tickets.ts`**: `ListActivityParams.offset?: number` → `cursor?: string`. `ActivityPage.total` updated to `number | null` (absent on non-first pages). `listActivity` sends `cursor` query param instead of `offset`.
- **`frontend/src/pages/Kanban/TicketDetailDrawer.tsx`**: added `activityCursor` + `activityLoadingMore` state. Initial fetch and post-comment refresh both set `activityCursor` from `page.next_cursor`. New `loadMoreActivity` handler fetches with cursor and appends rows. "Load more" button (`data-testid="activity-load-more"`) shown when `activityCursor != null`, hidden on last page.

### Files touched
- `app/schemas/tickets.py`
- `app/services/tickets.py`
- `app/routes/tickets.py`
- `frontend/src/api/tickets.ts`
- `frontend/src/pages/Kanban/TicketDetailDrawer.tsx`
- `tests/services/test_activity_service.py` — 2 new tests + updated existing
- `tests/routes/test_transitions_endpoint.py` — replaced `test_limit_and_offset_pagination` with `test_cursor_pagination_no_overlap`
- `tests/routes/test_ticket_activity_cursor.py` — new (5 tests)
- `frontend/src/pages/Kanban/__tests__/TicketDetailDrawerActivity.test.tsx` — new (2 tests)

### Tests added
- 2 service tests in `test_activity_service.py`: cursor filter returns only older items; total=count on first page, total=None on subsequent.
- 5 route tests in `test_ticket_activity_cursor.py`: first page has next_cursor, round-trip no overlap, last page null, invalid cursor → 400, cursor stable after comment insert.
- 2 frontend tests in `TicketDetailDrawerActivity.test.tsx`: first fetch shows Load more when cursor present; click appends rows and hides button when last page.
- Backend: **618 → 625 passing** (+7, 0 regressions; 306 pre-existing failures intact).
- Frontend: **68 → 70 passing** (+2, 0 regressions).

### Surprises / pitfalls
- `total` design decision: return `total` only on the first page (`cursor is None`). This avoids re-counting the full UNION on every page flip. Callers should store `total` from the first response for "X events" headers. All new tests assert this contract.
- `ActivityPage` as a subclass of `Page[ActivityItem]` (not a bare alias) is required because FastAPI needs a concrete (non-generic) class for `response_model`. A bare `Page[ActivityItem]` alias breaks schema generation.
- Cursor filter uses Python tuple comparison `(created_at, str(id)) < (anchor_ts, str(anchor_id))` — this works correctly across all three kinds (transition/comment/link) since UUIDs are comparable as strings and cross-kind ID collisions are impossible (UUIDv4 birthday paradox).
- No MCP server callers of `/transitions` exist — confirmed by grepping `app/mcp_server/`. Clean break to cursor-only; no deprecation shim needed.
- The existing `test_limit_and_offset_pagination` test used `offset=0` and `offset=2` query params. Replaced entirely with `test_cursor_pagination_no_overlap` (cursor-based). Note in case a caller was relying on `offset` param: the route no longer accepts it (silently ignored by FastAPI as an unknown query param — no error, no effect).

### Follow-ups for v2.3
- WP18 (deferred): replace Python-side UNION with SQL `UNION ALL` for large ticket feeds.
- WP19 (deferred): HMAC-sign cursors so clients cannot forge anchor values.
- The "Load more" button in `TicketDetailDrawer` reloads from the stored cursor. A future improvement could auto-scroll and trigger on intersection observer instead of a manual button.
- `total` from `ActivityPage` could be surfaced in the drawer header as "N events". Currently unused in the UI.

---

## WP17 — Real handle columns

### Goal
Materialise the `handle` field on `users` and `agent_accounts` (was Python-derived in `PeopleService`). Adds a unique index per kind, backfills existing rows with the same algorithm so @-mentions keep resolving.

### What shipped
- **Migration `alembic/versions/a12_add_handles.py`** (`revision="a12"`, `down_revision="a11_ticket_notifications"`).
  - Adds nullable `users.handle` and `agent_accounts.handle` (Text).
  - Backfills via a CTE: derive by `regex_replace(lower(source), '[^a-z0-9_]', '_', 'g')`, collapse `_+`, trim `_`. Resolve same-kind collisions with `ROW_NUMBER() OVER (PARTITION BY derived ORDER BY created_at, id)` and append `_N` for N>1.
  - Promotes column to `NOT NULL`, then creates `uq_users_handle` and `uq_agent_accounts_handle` unique indexes.
  - **BEFORE INSERT triggers** `_users_fill_handle()` / `_agents_fill_handle()` auto-derive `handle` when callers omit it (with `WHILE EXISTS ... candidate := base || '_' || n` collision loop). Backwards-compat for the 30+ raw-SQL `INSERT INTO users (...)` calls in the test suite that don't supply `handle`.
  - Roundtrip clean: `upgrade head → downgrade -1 → upgrade head` verified.

- **`app/models/user.py`**: added `handle = Column(String, unique=True, nullable=False)`.
- **`app/models/agent_account.py`**: added `handle: Mapped[str] = mapped_column(Text, nullable=False)`.

- **`app/services/people.py`**:
  - Removed `_user_handle()` and `_agent_handle()` derivation helpers.
  - `_normalize_user` / `_normalize_agent` now read `u.handle` / `a.handle` verbatim.
  - `_search_users` / `_search_agents` added `User.handle.ilike(like)` and `AgentAccount.handle.ilike(like)` to the `or_(...)` clauses — leverages new unique indexes for prefix matches.
  - `resolve_mention(handle, *, kind=None)` — new optional `kind` kwarg discriminates cross-kind handles (user `alice` + agent `alice` may coexist).

- **`app/routes/notifications_v1.py`**: dropped now-stale imports of `_user_handle`/`_agent_handle`; sources `handle` from the ORM rows directly.

- **`app/schemas/people.py`**: doc updated to reflect column-sourced handle.

### Files touched
- `alembic/versions/a12_add_handles.py` (new), `app/models/user.py`, `app/models/agent_account.py`, `app/services/people.py`, `app/routes/notifications_v1.py`, `app/schemas/people.py`.
- `tests/services/test_people_handles.py` (new, 6 tests), `tests/services/test_people_search_handles.py` (new, 5 tests), `tests/services/test_mention_fanout.py` (1 test updated for handle-shape change).
- `frontend/src/components/__tests__/PersonPicker.test.tsx` (1 new test).

### Tests added
- 6 migration/trigger tests: autofill, collision-resolution (users `alice`/`alice_2`), agent collision (`codex_sonnet`/`codex_sonnet_2`), unique-constraint enforced, NOT NULL after insert, derivation matches legacy `email-local-part` shape.
- 5 PeopleService tests: search-by-handle-prefix, `resolve_mention` strict column equality, cross-kind coexistence (user+agent `claude`), case-insensitive mention, handle-column index leverage.
- 1 PersonPicker frontend smoke: `@<handle>` subtitle rendered from API.
- Backend: **625 → 636 passing** (+11, 0 regressions; pre-existing 306 baseline failures intact).
- Frontend: **70 → 71 passing** (+1, 0 regressions). `npm run build` green.

### Surprises / pitfalls
- **Behaviour change**: pre-WP17 the agent handle replaced spaces with `-` (preserved `-`); the new algorithm normalises non-`[a-z0-9_]` to `_`. So an agent named `claude-bot` now has handle `claude_bot`. The `test_mention_fanout.py::test_agent_mention_fans_to_agent` test was updated to use `claude_bot` (a name whose derived handle round-trips identically). This is the only test affected; mention semantics for typical user-emails (`alice@x.test → alice`) are unchanged.
- **Trigger over schema-default**: `server_default` can't reference other columns, so we needed a trigger to derive `handle` from `email`/`name`. Doing this in Python (e.g. an ORM `default` callable or a `before_insert` event) would have left raw-SQL inserts (~30 test files) broken — the trigger keeps the SQL contract backward-compatible.
- **Trigger collision loop is O(N)** in the worst case (rare). For seed data with thousands of duplicates this would matter; for the live data set (single-digit collisions) it's irrelevant. If it ever bites, replace with `MAX(suffix) + 1` lookup.
- **Cross-kind handles allowed**: a user `alice` and an agent `alice` may coexist (per spec). The unique constraint is per-table. `resolve_mention(handle, *, kind=None)` returns the first match across both — callers needing strict disambiguation pass `kind`.
- **Model + DB column ordering**: SQLAlchemy ORM sends `NULL` for `handle` when the trigger handles it. The DB trigger fires `BEFORE INSERT` so the `NOT NULL` constraint is satisfied. No client-side ORM default needed.
- The `RichEditor.css` chunk warning grew slightly; unrelated to WP17.

### Follow-ups for v2.3
- Expose `PATCH /api/v1/users/me/handle` for user-editable handles (needs profanity filter + reserved-words check; out of scope here).
- Make the trigger collision loop use `MAX(suffix) + 1` once seed-data flows actually create duplicates at scale.
- Consider a `CHECK (handle ~ '^[a-z0-9_]+$')` constraint to lock the column shape at the DB level — currently enforced only by the trigger, so a raw `UPDATE handle = 'WeIrD-Casing'` would slip through.
- The legacy `bulletin` schema (`Notification`/`Watch` keyed on `users.id`) does not consume `handle`; if a future feature needs handles for bulletin entities, this WP is the model.
