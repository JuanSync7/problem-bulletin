# Ticketing v2.3 — Lessons Learned

Companion to `ticketing-v2.2.md`. Same TDD-loop / ralph-loop / one-subagent-at-a-time process.

## Cross-WP Rules (carry-forward from v2.2 — re-read before each WP)

1. **No new big abstractions** unless three call sites already exist. WP20 is the *one* exception this cycle — it's a documented consolidation, not speculative.
2. **Migrations land as `a13+`**. `a12` is the last v2.2 head (`add_handles`). One migration per WP that needs DB change. Always include `down_revision` + working downgrade.
3. **No regressions on the 306 baseline failures** (Postgres-only tests skipped on sqlite). New tests target the new behavior; existing failures stay at 306.
4. **Frontend build (`npm run build`) and tests (`npm test -- --run`) must end green.** Subagents that leave red builds get reverted.
5. **All new endpoints under `/api/v1` with Pydantic Page[T] envelope** (`items`, `next_cursor`, `total`). Lists with `total=null` on subsequent pages are fine — keep that contract.
6. **Permissions live in services**, raise `PermissionDeniedError`, mapped 403 at routes by the global handler.
7. **Routes that are heavy stay lazy** (`React.lazy`) — WP21's `/tickets/:id` route follows this.
8. **Each subagent appends a `## WPnn — <title>` section** with: spec, files touched, test counts, lessons.
9. **Spec parity**: subagent prompt is the contract. If the subagent finds the spec wrong, it documents the deviation in its lessons section and asks before changing scope.
10. **Subagent reports include**: (a) what changed, (b) tests added/passing, (c) commands run to verify, (d) any deferred/follow-up items for v2.4.

## v2.4 backlog seed (preserve)

Carried from v2.2 leftover + new items found this cycle. Anything not actively worked in v2.3 lives here so it does not get lost:

- WP18 (deferred) — SQL UNION ALL for activity merge (trigger: any ticket exceeds ~10k events).
- WP19 (deferred) — HMAC-signed cursors (trigger: public-facing pagination API ships).
- Sidebar unread-badge realtime — websocket once ticket-event stream lands.
- Per-status quotas on `GET /tickets` (e.g. `?per_status_limit=50`) — alternative shape to WP22 if last_activity_at proves insufficient.
- Per-lane height cap in Kanban swimlanes (WP12 follow-up).
- Column width preference toggle — `--kanban-column-width` is a CSS var; expose compact/normal/wide.
- Activity `total` on subsequent pages — currently null past page 1; expose `?count=true` if a consumer needs it.
- Profanity/reserved-words list for handles is minimal in WP24 — expand if abuse appears.
- Notification kinds beyond v2.3's set (e.g. `ticket_watcher_added`, `ticket_blocked`).
- Audit log for project admin gates added in WP24.

---

## WP20 — Consolidate cursor helpers

### Spec
Created `app/services/_pagination.py` as the single home for `encode_cursor` and `decode_cursor`. The shared `decode_cursor` now returns `None` on any bad input (narrowly catching `binascii.Error`, `ValueError`, `KeyError`, `json.JSONDecodeError`) instead of raising, so callers that need an exception (both service wrappers) convert `None` to their own domain error. Both `tickets.py` and `ticket_notifications.py` now delegate to the shared helpers via thin private wrappers (`_encode_cursor`/`_decode_cursor`) that preserve the existing raise-on-invalid contract seen by their call sites. Wire format is identical — no client cursors break.

### Files touched
- `app/services/_pagination.py` — new module: `encode_cursor`, `decode_cursor`, module docstring
- `app/services/tickets.py` — lines 222-264: replaced inline helpers with imports from `_pagination`; private wrapper `_decode_cursor` now converts `None` to `InvalidCursorError`
- `app/services/ticket_notifications.py` — lines 16-70: removed duplicate `base64`/`json` imports and helper implementations; thin wrappers delegate to `_pagination`
- `tests/services/test_pagination.py` — new file: 11 unit tests (no DB required)

### Tests
- 11 new tests in `tests/services/test_pagination.py` — all passing
- Backend baseline: 306/306 failures (no regression)
- Frontend build: green

### Lessons
- The spec says `app/tests/services/test_pagination.py` but the project's test tree lives under `tests/` (no `app/` prefix). Placed tests at `tests/services/test_pagination.py` to match the existing convention; no test-runner config changes needed.
- Existing tests that import `_encode_cursor`/`_decode_cursor` from `app.services.tickets` continue to work because the private wrappers are retained in `tickets.py` — zero churn to those test files.

### Follow-ups for v2.4
- WP19 (deferred): HMAC-sign the cursor in `_pagination.py` when a public-facing API ships — the consolidation makes that a one-file change now.

## WP21 — Real /tickets/:id route + deep-link migration

### Spec

Introduced a leaf route `/tickets/:displayId` so deep-links open a focused ticket
view instead of the full Kanban board. The board's `TicketDetailDrawer` is left
unchanged — it continues as the board's inline inspector. Deep-links from
`MentionsTab` and `CreateTicket` now point to the new route. The legacy
`/board?ticket=<id>` param path is preserved for existing bookmarks.

### Files touched

- `frontend/src/App.tsx` — lazy-import `TicketDetail` + `<Route path="/tickets/:displayId">` inserted after `/tickets/new` (ordering matters: `/tickets/new` must precede the param route)
- `frontend/src/pages/TicketDetail/index.tsx` — new page; fetches via existing `getTicket(displayId)` (already handles display_id on the backend); renders title, status badge, priority, type, description (via `renderMarkdown` from `MarkdownEditor`), and sidebar fields (project, assignee, reporter, story points, due date, labels, version); 404 state with back link; 500/generic error state; loading spinner
- `frontend/src/pages/TicketDetail/TicketDetail.css` — scoped styles for the page; CSS vars for dark-mode compatibility; responsive two-column layout
- `frontend/src/pages/Activity/MentionsTab.tsx` — `handleRowClick` migrated from `navigate('/board?ticket=...')` to `navigate('/tickets/...')`
- `frontend/src/pages/CreateTicket/CreateTicket.tsx` — post-create redirect migrated from `/board?ticket=...` to `/tickets/...`
- `frontend/src/pages/Activity/__tests__/MentionsTab.test.tsx` — added `/tickets/:displayId` route to test render helper; updated navigation assertion and description from `/board?ticket=TKT-42` to `/tickets/TKT-42`
- `frontend/src/pages/TicketDetail/__tests__/TicketDetail.test.tsx` — new: 5 tests (title+status on success, markdown rendering, 404 not-found, 500 error, loading spinner)

### Tests

- 5 new tests in `TicketDetail.test.tsx` — all passing
- 4 existing MentionsTab tests updated for new nav target — all passing
- Full suite: 76/76 tests pass across 15 files
- Frontend build: clean (`✓ built in 3.00s`)

### Lessons

- `getTicket(idOrKey)` already handles display_id on the backend (`app/services/tickets.py` line 278-285 resolves display_id → UUID). No new API function was needed; `getTicketByDisplayId` would be redundant.
- The `/tickets/new` route must precede `/tickets/:displayId` in the Routes tree, otherwise `new` would match as a `displayId` param. The existing ordering (`:new` before `:displayId`) is correct and was maintained.
- `renderMarkdown` is exported from `MarkdownEditor.tsx` as a named export — easy to reuse in the new page without extracting a separate component.
- `TicketDetailDrawer` is not extracted into a shared component yet; the drawer is heavily stateful (edit actions, comment posting, subtree loading) and would require significant interface surgery to make safe as a shared leaf. This is left as a follow-up.
- The `ActivityPage` "My Tickets" stub in `/activity?tab=mine` references "coming soon v2.3" — that will be addressed in WP23.

### Follow-ups for v2.4

- **Drawer/page duplication**: `TicketDetail` and `TicketDetailDrawer` render the same core fields independently. A shared `<TicketFields>` presentational component would reduce drift (tracked in WP23 context).
- **Activity feed on the detail page**: `TicketDetail` renders no activity feed yet. The drawer's feed code is too tightly coupled to its own state machine to extract cleanly right now. Add a `<TicketActivityFeed ticketKey={displayId} />` component in v2.4.
- **Edit actions**: the standalone page is read-only. Inline status/priority/assignee edits (as in the drawer) are a v2.4 enhancement once the page stabilises.

## WP22 — Backend order_by=last_activity_at for tickets

### Spec

Added `order_by: Literal["created_at", "last_activity_at"] = "created_at"` to
`GET /api/v1/tickets` and the underlying `TicketService.list()`.  When
`order_by="last_activity_at"` the query sorts by
`COALESCE(last_activity_at, created_at) DESC, id DESC`.  Cursor encoding uses
the effective sort timestamp (post-COALESCE) of the last row so the cursor stays
correct across pages.  The v2.2 Kanban secondary `status=["done"]` fetch and
`Promise.all` merge are removed; the Kanban now issues a single fetch with
`order_by: "last_activity_at"`, which surfaces done/cancelled tickets regardless
of creation age.

### Files touched

- `app/services/tickets.py` — `TicketService.list()`: added `order_by` kwarg
  (`Literal["created_at", "last_activity_at"]`, default `"created_at"`);
  `sort_expr` computed as `COALESCE(last_activity_at, created_at)` or
  `created_at`; cursor keyset WHERE and `ORDER BY` use `sort_expr`; cursor
  encodes `last_activity_at or created_at` when ordering by activity; added
  `Literal` to `typing` imports.
- `app/routes/tickets.py` — `list_tickets()` route: added `order_by` `Query`
  param with `Literal["created_at", "last_activity_at"]` (FastAPI validates and
  returns 422 on unknown values); threaded through to `svc.list()`; added
  `Literal` to `typing` imports.
- `frontend/src/api/tickets.ts` — `ListTicketsParams`: added
  `order_by?: "created_at" | "last_activity_at"`; `listTickets` appends it to
  the query string when set.
- `frontend/src/pages/Kanban/index.tsx` — `refresh` callback: replaced
  `Promise.all([listTickets(…), listTickets({…, status:["done"], limit:100})])`
  with a single `listTickets({…, order_by:"last_activity_at"})` call; kept
  cheap dedup-by-id guard; updated comment block; `loadMore` also passes
  `order_by:"last_activity_at"` for cursor consistency.
- `tests/services/test_tickets_ordering.py` — 5 new service-layer tests (DB
  required, skip if unreachable).
- `tests/routes/test_tickets_ordering.py` — 5 new route-level tests (DB
  required, skip if unreachable).

### Tests

- 10 new tests: 5 service-layer + 5 route-level — all passing against live DB.
- Backend baseline: 306 failures before → 306 after (no regression).
  Passing count: 647 → 657 (+10).
- Frontend: 76/76 tests pass, `npm run build` clean (3.00s).

### `last_activity_at` status

Already exists on the `tickets` table (migration `a10_ticket_last_actor.py`).
Stamped on every write path (create, update, transition, assign, claim, comment,
link, watcher). `Mapped[datetime | None]` — nullable to accommodate pre-WP6
rows.  COALESCE applied defensively in the sort expression; no backfill or
migration needed.

### Lessons

- FastAPI's `Literal["a", "b"]` as a `Query` default automatically returns 422
  on unknown values without any manual validation — the route test for `?order_by=bogus`
  passes without any extra exception handler.
- SQLAlchemy's `func.coalesce(col_a, col_b)` returns a labelled expression;
  calling `.desc()` on it works as expected and the keyset WHERE can reuse
  the same `sort_expr` reference.
- Cursor semantic contract (documented in `tickets.py` docstring): `t` field
  in the opaque cursor encodes the *effective* sort timestamp — `created_at`
  under the default mode, `COALESCE(last_activity_at, created_at)` under the
  activity mode.  Clients MUST NOT mix cursors across `order_by` modes; this
  is documented in the route description.

### Follow-ups for v2.4

- Per-status quota: `?per_status_limit=50` (alternative/complement to
  `last_activity_at` ordering for extremely busy projects with thousands of
  done tickets).
- Index: `CREATE INDEX ON tickets (COALESCE(last_activity_at, created_at) DESC, id DESC)`
  would make the `last_activity_at` ordering O(log N) rather than seq-scan.
  Not added in this WP (needs a migration); add if query latency surfaces.

## WP23 — Wire Mine tab in /activity

### Spec
Replace the "Coming soon (v2.3)" stub in `/activity?tab=mine` with a real `<MineTab>` that lists tickets assigned to the current user with All/Open-only toggle, cursor pagination, row-click navigation to `/tickets/<display_id>`, and proper empty/loading states.

### Files touched
- **Created** `frontend/src/pages/Activity/MineTab.tsx` — full implementation mirroring MentionsTab structure
- **Created** `frontend/src/pages/Activity/__tests__/MineTab.test.tsx` — 5 tests
- **Modified** `frontend/src/pages/Activity/index.tsx` — import MineTab, replace stub div with `<MineTab />`
- **Modified** `frontend/src/pages/Activity/__tests__/Activity.test.tsx` — add `listTickets` and `useAuth` mocks; update mine-tab assertion from stub text to `data-testid="mine-tab"` presence

### Tests
5 new tests in `MineTab.test.tsx`:
1. Empty state renders when API returns no items
2. Ticket rows render with display_id + title
3. Row click navigates to `/tickets/<display_id>`
4. Open-only toggle (default) calls `listTickets` with status array excluding terminal statuses
5. All toggle calls `listTickets` with no status filter

All 16 test files passed (81 tests total). Build clean.

### Auth hook
Used existing `useAuth` from `frontend/src/hooks/useAuth.ts`. Since the backend supports `assignee_id: "me"` as a first-class filter (resolves to the authenticated user server-side), no UUID extraction from the hook was needed — `"me"` is passed directly to `listTickets`.

### Terminal statuses (Open-only filter)
`done` and `cancelled` — confirmed from `app/enums.py: TERMINAL_STATUSES = frozenset({TicketStatus.done, TicketStatus.cancelled})`. The Open-only filter passes `OPEN_STATUSES = ["backlog", "todo", "in_progress", "in_review", "blocked"]` explicitly.

### Lessons
- Smart/curly quotes in JSX string literals cause esbuild parse errors — use plain single-quoted strings or escape properly.
- The `"me"` assignee sentinel was already landed in WP10 (`AssigneeFilter` type in `tickets.ts`, backend resolves it), so no new backend work was required.
- The Activity.test.tsx mine-tab test was asserting stub text — tests that assert placeholder copy need to be proactively updated when the stub is replaced.
- `useAuth.isLoading` guard in MineTab prevents a spurious API call before auth resolves; the `authLoading` dependency in the useEffect prevents the initial fetch from firing until the user state is known.

### Follow-ups for v2.4
- MineTab could benefit from a project-name column once the list endpoint returns a `project_name` field (currently only `project_key` is serialized).
- Consider extracting a shared `<TicketRow>` component to avoid divergence between MineTab and any future ticket list surfaces.
- Add real-time update via WebSocket stream when a ticket assigned to the current user changes status or gets updated.

## WP24 — POST /projects admin-only + PATCH /users/me/handle

*(filled by subagent)*

## WP25 — Notification kinds + minimal agent inbox

*(filled by subagent)*
