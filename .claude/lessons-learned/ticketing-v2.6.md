# Ticketing v2.6 — Lessons Learned

Companion to `ticketing-v2.5.md`. Same TDD-loop / ralph-loop / one-subagent-at-a-time process.

## Cross-WP Rules (carry-forward + new)

1. **No new big abstractions** unless 3+ call sites exist or are imminent.
2. **Migrations land as `a19+`**. v2.5's last head was `a18_project_coalesce_seconds`. One migration per WP that touches DB.
3. **Baseline before v2.6 = 327 failures / 753 passed / 5 skipped / 14 xfailed** (from v2.5 tail). WP38 explicitly *reduces* this baseline by fixing the long-known `tests/auth/test_jwt.py` SecretStr mismatch. **Post-WP38 baseline (2026-05-19) = 313 failures / 767 passed / 5 skipped / 14 xfailed.** All subsequent v2.6 WPs gate against this post-WP38 number.
4. **Frontend (`npm run build`, `npm test -- --run`) must end green.** v2.5 ended at 172/172 frontend.
5. **All new endpoints under `/api/v1` with Pydantic `Page[T]` envelope** for lists.
6. **Permissions in services**, mapped to HTTP at global handlers in `app/main.py`. Use `require_admin(user)` from `app/services/_admin.py` for admin-only paths.
7. **Routes that are heavy stay lazy** (`React.lazy`).
8. **Each subagent appends `## WPnn — <title>` with Spec / Files touched / Tests / Lessons / Follow-ups for v2.7.**
9. **Spec parity**: subagent prompt is the contract. Deviations get documented in lessons.
10. **Subagent report contract**: (a) what changed, (b) tests added/passing, (c) commands run to verify, (d) follow-ups for v2.7.
11. **Realtime is additive** — fetch-based paths must keep working without WS/Hub.
12. **Audit log writes are best-effort** (WP28). New admin-gated mutations write via `audit_log.record(...)`.
13. **Admin discriminator is `users.role == 'admin'`** — never `is_admin`. Use the `require_admin` helper.
14. **Background work uses FastAPI lifespan + asyncio**. No new schedulers. Single-process coordinator pattern (advisory locks) lands in WP39.

## v2.7 backlog seed (carry-forward what doesn't land)

Will be expanded as v2.6 WPs report. Starting carry-forward:

- Redis pub/sub for multi-process WS scaling (trigger: multi-process deploy)
- WP18 (deferred) — SQL UNION ALL for activity merge
- WP19 (deferred) — HMAC-signed cursors
- Per-status quotas on `GET /tickets`
- Inline status/priority/assignee error rollback policy on TicketDetail
- Audit-log retention/archival policy (may land in v2.6-WP44)
- Avatar support in PersonPicker chip
- Recently-used / "Me" shortcut in PersonPicker
- Fuzzy match for `/api/v1/people/search`
- Proper profanity lib (better-profanity) with word-boundary matching
- User-facing "request review" flow for blocked handles
- DB-driven blocklist management API
- Sidebar agent-kind `notification_read` publish for current user
- NOT NULL on `agent_accounts.created_by` once envs are clean
- Per-project column-width persistence key `kanban.columnWidth.<projectKey>`
- CSS var written to `document.documentElement` instead of wrapper div
- Keyboard navigation for segmented control
- Scanner Prometheus metrics
- `state_change_coalesce_seconds` default from site config
- Ultra-wide 400px column preset
- WP36's column-width toggle is dead UI after Kanban grid switch (candidate for removal or repurpose for lane height)
- Extract more shared form primitives to `src/styles/` (tag-autocomplete, attachment-dropzone)
- Document `cssCodeSplit: false` rationale in frontend README

## v2.6 WP plan

- **WP38** — Hygiene: fix pre-existing `tests/auth/test_jwt.py` SecretStr/mock mismatch; re-baseline.
- **WP39** — Scanner multi-process coordinator (`pg_try_advisory_lock`) + configurable scan interval/lookahead via env.
- **WP40** — `ticket_cancelled` notification kind (parallel to `ticket_resolved`).
- **WP41** — Watcher-added notification (WP30 follow-up).
- **WP42** — CreateTicket form adopts the new `PersonPicker`; retire old `PersonPicker.tsx`.
- **WP43** — Kanban lane-height preference (50/70/90vh/unlimited) replacing the now-dead column-width toggle.
- **WP44** — Audit-log retention policy + admin quick-filter for `user.handle_changed_by_admin`.
- **WP45** — Activity `total` on subsequent pages + `assignee_type` in TicketDTO.

---

## WP38 — JWT test SecretStr fix

**Spec.** Resolve the long-standing failure cluster in `tests/auth/test_jwt.py` rooted in a mock/production contract mismatch: production reads `settings.JWT_SECRET.get_secret_value()` (Pydantic `SecretStr`), but the test's `_make_settings` helper installed a plain `str`, raising `AttributeError` across every JWT code-path test. Tests are wrong; production contract stays.

**Files touched.**
- `tests/auth/test_jwt.py` — imported `pydantic.SecretStr`; wrapped `s.JWT_SECRET` assignment in `_make_settings` so the mock matches the production contract. No production code changed. No new tests.

**Tests (new totals).**
- `tests/auth/test_jwt.py`: 22 passed (previously ~14 of 22 failing on the SecretStr path).
- Full backend suite: **313 failed / 767 passed / 5 skipped / 14 xfailed** (was 327 / 753 / 5 / 14). Net delta: +14 passing, -14 failing. No regressions.
- Frontend: `npm run build` clean; `npm test -- --run` 172/172 passing.

**Lessons.**
- When production wraps a value in a typed envelope (`SecretStr`, `HttpUrl`, custom `BaseModel`), mocks that pretend to be `Settings` must mirror the envelope, not the inner primitive. `MagicMock` won't save you here because we explicitly *assign* a real `str` over the auto-generated attribute, killing duck typing.
- A single mock-helper bug can dominate suite failure counts for multiple versions (v2.3 → v2.6). High-yield hygiene WPs are worth scheduling explicitly rather than waiting for a "real" feature to bundle them.
- Cross-WP Rule #3 baseline is now post-WP38; v2.6 gating commands should reference 313/767.

**Follow-ups for v2.7.**
- Audit the remaining 313 failures — likely clusters around fixtures (`make_user`, `client` setup) and config mocking. Worth one more hygiene WP early in v2.7 to drive the floor below 100.
- Consider a shared `_mock_settings()` fixture in `tests/conftest.py` that returns a `Settings`-shaped object with all SecretStr/typed fields already wrapped, so future test files don't reinvent this trap.
- Consider a typed `SettingsProtocol` (Protocol or pydantic stub) the JWT module accepts, to make mock contracts explicit in tests.


## WP39 — Scanner coordinator + configurable timing

**Spec.** Harden the v2.5-WP37 `due_soon_scanner` for multi-process deployment (Postgres advisory lock) and lift its hardcoded 10-min interval / 24-h lookahead into configurable settings. No new deps, no migration — advisory locks are runtime-only.

**Files touched.**
- `app/services/due_soon_scanner.py` — refactored: `scan_once` now wraps body in `pg_try_advisory_lock(:k)`; on contention returns 0 with a log; on success/exception `pg_advisory_unlock(:k)` fires in `finally`. Body extracted to `_scan_body` (testable; supports `lookahead_hours` override). Lock key derived once via `hashlib.md5(b"due_soon_scanner")[:8] & 0x7FFFFFFFFFFFFFFF` (deterministic signed-bigint). `run_loop` now reads `DUE_SOON_SCAN_INTERVAL_SECONDS` from settings. Module docstring updated.
- `app/config.py` — added `DUE_SOON_SCAN_INTERVAL_SECONDS: int = 600` (min 60, clamped) and `DUE_SOON_LOOKAHEAD_HOURS: int = 24` (1..168, clamped) with Pydantic field validators. Defaults match WP37 behavior; out-of-range envs clamp rather than crash boot.
- `tests/services/test_due_soon_scanner.py` — +4 tests: advisory-lock contention returns 0 + writes nothing (uses `session_factory` to hold lock on a second connection); lock released on success; lock released on exception (`monkeypatch` of `_scan_body` to raise); `lookahead_hours=48` override picks up a 36h-out ticket the default 24h skips.

**Tests (new totals).**
- `tests/services/test_due_soon_scanner.py`: 10 passed (was 6).
- Full backend: **313 failed / 771 passed / 5 skipped / 14 xfailed** (was 313 / 767 / 5 / 14). Net: +4 passing, 0 new failures.
- Frontend: `npm test -- --run` 172/172; `npm run build` clean.

**Lessons.**
- Postgres advisory locks are *session-scoped*: lock and unlock MUST run on the same backend connection. Async SQLAlchemy `AsyncSession` pins a single connection for its lifetime, so issuing both via the same `session.execute(text(...))` is correct. If you accept an `AsyncSession` and don't pop a new one mid-scan, you're safe.
- `pg_try_advisory_unlock` failure is non-fatal — Postgres releases all session-scoped advisory locks automatically when the backend disconnects. We log-and-swallow rather than letting an unlock error mask the real exception from the body.
- Pydantic field validators that *clamp* rather than *raise* are the right call for ops-touched env vars: a typo'd `DUE_SOON_SCAN_INTERVAL_SECONDS=5` should not crash boot during a 3am rollback.
- Extracting `_scan_body` as a separate function turned out to be the cleanest way to test "unlock fires on exception" — `monkeypatch` of one symbol, no real DB error injection needed.

**Follow-ups for v2.7.**
- Prometheus metrics on the scanner: counters for `scan_attempts_total`, `scan_skipped_locked_total`, `scan_succeeded_total`, `notifications_written_total`; histogram for scan duration. Wire via the existing OTEL meter provider.
- Advisory-lock key collision audit: today only `due_soon_scanner` uses an MD5-derived bigint. If we add more (e.g. a future cleanup loop, a sweep job), register all keys in a central `app/services/_advisory_keys.py` and assert uniqueness at import time.
- Redis-backed coordinator alternative: for deployments where Postgres is a bottleneck or where the scanner needs a leader-election pattern across services, evaluate `redis.set(nx=True, ex=...)` with a fencing token. Lower latency but adds a dep — only justify if metrics show advisory-lock contention waste.
- The `run_loop` interval is read once at startup. If we want hot-reload (SIGHUP-style) for ops, refactor to read `get_settings()` inside the loop body. Not needed today.

## WP40 — ticket_cancelled notification kind

**Spec.** Mirror WP37's `ticket_resolved` for the other terminal state: a new
`ticket_cancelled` notification kind emitted when a ticket transitions to
`cancelled`. Fanout = assignee + reporter + watchers, actor excluded. Excerpt
`"<from_status> → cancelled"`. No coalescing. SAVEPOINT-isolated per recipient
so a recipient-level failure (e.g. unique-key race, FK glitch) never aborts
the parent transaction. Realtime publish to each recipient's WS channel —
best-effort, same shape as `ticket_resolved`. Frontend renders a grey
"Cancelled" badge to distinguish cancellation from red error states (blocked)
and green resolution states (resolved).

**Files touched.**
- `app/services/ticket_notifications.py` — added `fanout_cancelled` (mirrors
  `fanout_resolved`).
- `app/services/tickets.py::transition` — added `if target == TicketStatus.cancelled:`
  branch after the existing `done` branch.
- `frontend/src/pages/Activity/MentionsTab.tsx::renderKindLabel` — added
  `case "ticket_cancelled":`.
- `frontend/src/pages/Activity/Activity.css` — added
  `.mentions-row__badge--cancelled` with a neutral slate palette
  (`#f1f5f9` / `#475569` / `#cbd5e1`).
- `tests/services/test_ticket_notifications_wp40.py` — new file, 4 tests.
- `tests/routes/test_transitions_endpoint.py` — added one route test that
  drives `POST /api/v1/tickets/{id}/transition` to `cancelled` and asserts a
  `ticket_cancelled` row lands for the assignee with the right excerpt.
- `frontend/src/pages/Activity/__tests__/MentionsTab.test.tsx` — added one
  render test.

**Tests.** Backend new: 4 unit + 1 route = 5. Frontend new: 1. Backend
totals went from baseline 313 failed / 771 passed to 313 failed / 776
passed (+5, no regressions). Frontend 172 → 173.

**Lessons.**
- The `kind` column on `ticket_notifications` is a free-form string in both
  the SQLAlchemy model and the Pydantic `TicketNotificationRead` schema —
  there is no central enum to update. The WP37 brief implies the same.
  This makes "add a new notification kind" a 3-site change (service +
  transition wire-up + frontend switch case) instead of an enum-coupled
  refactor.
- `pg_insert` is imported at module scope in `app.services.ticket_notifications`,
  so the savepoint-failure test can monkeypatch it with a `boom()` wrapper
  that only raises for the `TicketNotification.__table__` insert — the
  parent transaction stays alive because the nested SAVEPOINT rolls back
  in the `except Exception:` arm.
- The route test uses `POST /tickets/{id}/assign` (not `PATCH`) to set the
  assignee before transitioning — the `TicketAssignBody` schema needs
  `assignee_id`, `assignee_type`, and `expected_version`.
- Cancellation badge colour: slate-grey, not red. Cancelled is a deliberate
  terminal state, not an error condition; the existing red `--blocked` and
  `--warning` badges convey alarm, which would mis-signal here.

**Follow-ups for v2.7.**
- Optional cancellation reason: add a `reason` column / payload field on the
  transition body so the cancelled-notification excerpt can carry context
  (`"in_progress → cancelled (duplicate of WP40-5)"`) instead of the bare
  status pair. Requires a small migration + schema bump.
- Filter chip in the Mentions tab for `kind=ticket_cancelled` (and the
  other resolution-class kinds) so users can sort their inbox by intent.
- Dedicated icon for the cancelled row — today only the badge text
  distinguishes it from `ticket_state_change`. A subtle icon (e.g. an
  `x-circle` glyph) before the badge would improve scannability.
- Audit whether `done → cancelled` is a valid transition; today the
  workflow table only allows `cancelled` from active states. If a user
  resolves then cancels (rare but possible — wrong-ticket close), they get
  a `ticket_resolved` then a state_change but never a `ticket_cancelled`.
  Probably fine, but worth confirming with product.

## WP41 — Watcher-added notification

**Goal.** Close the loop on the v2.4-WP30 `ticket_watcher_added` kind: the
service-layer fanout was already in place but the route was *not* passing
the actor through, so adding someone as a watcher via HTTP never produced
a notification. WP41 wires the actor end-to-end, replaces the ad-hoc
"You're now watching {display_id} {title}" excerpt with the stable
recipient-centric sentence `"You were added as a watcher"`, and adds a
neutral/info badge so the row reads as informational — distinct from
red (`--blocked`) and green (`--resolved`).

**Files modified.**
- `app/services/ticket_notifications.py` — excerpt is now the constant
  `"You were added as a watcher"`; `ticket_title` kwarg is accepted but
  no longer spliced into the excerpt (kept for backwards-compat callers).
- `app/routes/tickets.py` — `POST /api/v1/tickets/{id}/watchers` now
  threads `actor=actor` into `TicketService.add_watcher`, matching the
  WP30 signature that's been waiting for a caller.
- `frontend/src/pages/Activity/MentionsTab.tsx` — `ticket_watcher_added`
  row renders a `mentions-row__badge--watcher` badge plus excerpt
  fragment, matching the visual rhythm of `ticket_resolved` /
  `ticket_cancelled`.
- `frontend/src/pages/Activity/Activity.css` — new
  `.mentions-row__badge--watcher` rule using a blue/info palette
  (`#eff6ff` + `var(--color-primary-start)` text).
- `tests/services/test_watcher_notifications_wp41.py` — 4 tests covering
  the happy path, self-watch skip, excerpt shape, and SAVEPOINT isolation
  on forced INSERT failure.
- `tests/routes/test_watchers_wp41.py` — 1 test exercising the FastAPI
  route end-to-end and asserting the notification row gets the right
  recipient + actor + excerpt.
- `tests/services/test_ticket_notifications_wp30.py` — updated the
  inherited WP30 excerpt assertion (`"watching" in excerpt`) to the new
  stable shape, since WP41 owns this excerpt now.
- `frontend/src/pages/Activity/__tests__/MentionsTab.test.tsx` — added a
  test that asserts the `--watcher` badge is present and the red/green
  badges are absent.

**Decisions.**
- *Excerpt is a constant.* The display_id and title both live on the
  notification row already (`target_display_id`, and the UI re-fetches
  the ticket on click). Splicing them into the excerpt mixes concerns
  and makes the column harder to test deterministically. A recipient-
  centric sentence — "You were added as a watcher" — also reads better
  in inbox listings ("alice — You were added as a watcher · TKT-42")
  than the verb-less "alice — You're now watching TKT-42".
- *Badge colour is info-blue, not green or grey.* Adding a watcher is
  neither a resolution (green) nor a cancellation/neutral terminal
  (slate); it's an opt-in informational event. Reused `#eff6ff` + the
  existing `--color-primary-start` token to avoid burning a new CSS
  variable.
- *Idempotent add stays silent on no-op.* `TicketService.add_watcher`
  short-circuits when the (ticket, watcher) row already exists. We did
  NOT change that: re-adding the same watcher is a no-op, no second
  notification, no surprise.
- *Bulk-add not in scope.* The current endpoint shape is
  `POST /tickets/{id}/watchers` with a single `{watcher_id, watcher_type}`
  body — no bulk variant. If one is introduced in v2.7, the
  per-recipient loop should reuse `fanout_watcher_added` and rely on its
  SAVEPOINT isolation so a single bad INSERT doesn't poison the batch.
- *Stayed scoped — no watcher-removed kind.* The spec was explicit:
  `ticket_watcher_removed` is v2.7. Removing yourself silently is fine
  (we never created a notification in the first place); removing
  someone else from a ticket they're watching is the interesting
  question, and product hasn't weighed in yet.

**Watcher-add route shape (for reference).**
- `POST /api/v1/tickets/{id_or_key}/watchers`
- Body: `{ "watcher_id": "<uuid>", "watcher_type": "user" | "agent" }`
- 201 → returns the `TicketWatcher` row as JSON.
- Self-watch (auth'd actor adds themselves) is allowed by the API but
  emits zero notifications by design.

**Results.**
- New tests: 5 backend (4 service + 1 route) + 1 frontend = 6.
- Backend suite: 313 failed / 781 passed / 5 skipped / 14 xfailed
  (baseline 313/776 — no regression; +5 from new tests).
- Frontend suite: 174 / 174 (baseline 173 + 1 new).
- `npm run build` clean.

**Follow-ups for v2.7.**
- `ticket_watcher_removed` kind, with the symmetric "You were removed
  as a watcher" excerpt. Open question: do we notify *only* the removed
  watcher, or also the actor + assignee that the watcher list shrank?
  Defaulting to only-the-removed-watcher is safest.
- In-app "Follow ticket" button on `/tickets/:displayId` — today
  watcher management is discoverable only via the API. A simple
  bell-icon toggle in the ticket header would let users self-subscribe
  without admin help (and the no-notification self-watch path already
  supports it gracefully).
- Bulk-add UX in the assignment / mention flows: when someone @-mentions
  three handles in a comment, optionally offer to add all three as
  watchers in one click. Backend would need a bulk `POST /watchers`
  body shape (`{watchers: [{watcher_id, watcher_type}, ...]}`) and the
  fanout loop must skip the actor in the loop body, not the call site.
- Watcher-list realtime updates — today the notification is best-effort
  published to the recipient's user channel, but the *ticket* channel
  isn't updated, so other watchers viewing the ticket don't see the
  list grow until refresh. Probably a `ws_tickets` publish addition.

## WP42 — CreateTicket adopts new PersonPicker

### Spec

Migrate the assignee picker in `pages/CreateTicket/CreateTicket.tsx` from the
legacy flat-file `components/PersonPicker.tsx` (v2.1-WP8) to the new
directory-based `components/PersonPicker/index.tsx` (v2.5-WP32 — keyboard
nav, 250ms debounce, chip mode, `allowClear`). Drop-in replacement — same
field label, same submit payload (`assignee_id` + `assignee_type`).

CreateTicket has no watchers field, so this is a single-field migration.

### Files touched

- `frontend/src/pages/CreateTicket/CreateTicket.tsx` — swap import to
  `"../../components/PersonPicker/index"`, state type
  `PersonPickerValue → PersonRef`, drop unsupported `id`/`ariaLabel`/`projectId`
  props on the new picker, add `allowClear`, drop dangling `htmlFor="ct-assignee"`
  since the new picker does not expose an `id` prop.
- `frontend/src/pages/CreateTicket/__tests__/CreateTicket.test.tsx` — two new
  tests:
  - "WP42: renders the new shared PersonPicker for assignee" — asserts the
    `data-testid="person-picker"` + combobox/aria-autocomplete on the input.
  - "WP42: picking an assignee sends assignee_id+assignee_type in the body" —
    mocks `searchPeople`, drives the typeahead through to a click on the
    rendered option, asserts the `createTicket` body.
- `frontend/src/components/PersonPicker.tsx` — added a `@deprecated` header.
  NOT deleted: `pages/Kanban/FiltersBar.tsx` still uses the legacy picker's
  `specials` prop ("Unassigned" / "Me" sentinels), which the new picker has
  not yet absorbed.

### Tests

- CreateTicket suite: 5 → 7 (both new tests pass).
- Frontend full suite: 174 → 176, all green.
- `npm run build` clean, no module-resolution warnings, no unused-import
  warnings.
- Backend pytest unchanged: 313 failed / 781 passed / 5 skipped / 14 xfailed.

### Lessons

- The v2.5 trap ("TypeScript file beats directory index") still bites. Both
  the new picker and the old one are named `PersonPicker` — a bare
  `import "../../components/PersonPicker"` resolves to the legacy `.tsx`, so
  the explicit `/index` suffix on the new import is load-bearing. Worth
  documenting in CLAUDE.md for the v2.7 picker-consolidation WP.
- The two pickers have *incompatible* value shapes. Legacy is the minimal
  `{ kind, id }` (`PersonPickerValue`); new is the full `PersonRef` record
  (`{ id, kind, display_name, handle, ... }`). Submission code that reads
  `.id` + `.kind` is fine either way, but anything storing/restoring the
  selected value (e.g. drafts) needs to be aware.
- The new picker has no `id`/`ariaLabel`/`projectId` props. Dropping the
  `htmlFor` association on the assignee `<label>` is the cheap fix; the
  input still has `role="combobox"` for screen readers. Long-term, the new
  picker should accept an optional `id` so `<label htmlFor>` works.
- The legacy picker's `projectId` prop scoped the search to project
  members. The new picker does not currently support that scoping. For
  CreateTicket, allowing cross-project search is acceptable (the backend
  validates assignee on create anyway), but worth noting.

### Follow-ups (v2.7)

- Add `specials` ("Unassigned" / "Me") to `PersonPicker/index.tsx`, migrate
  `Kanban/FiltersBar.tsx`, then *delete* the legacy `components/PersonPicker.tsx`
  and its WP8 test file. Track as a single WP.
- Add `id` (and optional `ariaLabel`) prop to the new picker so consumers can
  keep `<label htmlFor>` accessibility wiring.
- Add `projectId` scoping to the new picker (so member-only search matches
  the legacy behaviour for the Kanban filter use case).
- Avatar rendering, recently-used shortcut, and bulk-paste of @handles —
  flagged in the WP42 brief, still open.

## WP43 — Kanban lane-height preference

### Spec

Replace the now-dead WP36 column-width segmented toggle (Compact 220 /
Normal 260 / Wide 320 px) with a useful **lane-height** preference
(`50vh` / `70vh` / `90vh` / `Unlimited`).

Why the old toggle was dead: post-v2.5 the Kanban board switched from
fixed-width flex columns to a CSS grid (`grid-auto-columns: minmax(0, 1fr)`),
so the `--kanban-column-width` CSS var the toggle wrote was no longer
consumed by `.kanban-column`. The toolbar control had no visible effect.

The lane-height cap on `.kanban-column__list` (`max-height: 70vh`),
introduced in the same WP36 polish, IS still in use. v2.6 exposes it as
a user preference: storage key `kanban.laneHeight`, allowed values
`"50vh" | "70vh" | "90vh" | "unlimited"`, default `"70vh"`. The literal
string `"unlimited"` maps to the CSS value `"none"` so `max-height: var(--kanban-lane-height, 70vh)` becomes `max-height: none` and removes the cap entirely.

### Files touched

- Added `frontend/src/pages/Kanban/useKanbanLaneHeight.ts` — hook with
  signature `[LaneHeight, (next: LaneHeight) => void]` plus a
  `laneHeightCssValue()` helper that handles the `unlimited` → `none`
  mapping.
- Added `frontend/src/pages/Kanban/__tests__/useKanbanLaneHeight.test.ts`
  (5 tests).
- Added `frontend/src/pages/Kanban/__tests__/KanbanLaneHeightToggle.test.tsx`
  (4 tests).
- Deleted `frontend/src/pages/Kanban/useKanbanColumnWidth.ts`.
- Deleted `frontend/src/pages/Kanban/__tests__/useKanbanColumnWidth.test.ts`.
- Deleted `frontend/src/pages/Kanban/__tests__/KanbanWidthToggle.test.tsx`.
- Modified `frontend/src/pages/Kanban/index.tsx` — swap hook + toolbar
  control; the existing `.kanban-board-root` wrapper now carries
  `--kanban-lane-height` instead of `--kanban-column-width`.
- Modified `frontend/src/pages/Kanban/Kanban.css` — rename
  `.kanban-width-toggle*` rules to `.kanban-lane-height-toggle*`; drop
  the dead `--kanban-column-width` declaration on `:root`; change
  `.kanban-column__list { max-height: 70vh }` to
  `max-height: var(--kanban-lane-height, 70vh)`. `overflow-y: auto`,
  `scrollbar-width: thin`, and the `::-webkit-scrollbar*` rules are
  preserved.

### Tests

- Baseline (post-WP42): 176 / 176 across 25 files.
- Removed: 5 (useKanbanColumnWidth) + 4 (KanbanWidthToggle) = 9.
- Added: 5 (useKanbanLaneHeight) + 4 (KanbanLaneHeightToggle) = 9.
- Final: 176 / 176 across 25 files (net 0 by design — same coverage
  shape, new feature).
- `npm run build` clean.

### Lessons

- When a UI control silently stops doing anything (because the underlying
  CSS contract moved out from under it), the cheapest fix is to repurpose
  the slot for an *adjacent* preference that uses the same toolbar widget
  pattern. Same JSX shape (segmented `role="radiogroup"` + `role="radio"`
  buttons), same persistence pattern (`localStorage` + try/catch), same
  CSS-var-on-wrapper plumbing — the rest of the file barely shifts.
- The `"unlimited"` → `"none"` mapping is the only non-obvious bit. Keep
  the user-facing label ("Unlimited") and the storage value
  (`"unlimited"`) decoupled from the CSS value (`"none"`) — three names
  for one concept, but each name belongs to a different layer. Centralize
  the mapping in a single helper (`laneHeightCssValue`) so the
  toggle component and any future consumer (settings page, keyboard
  shortcut) cannot drift.
- `display: contents` on the wrapper is still the right call: the wrapper
  exists only to scope the CSS custom property to the board subtree, and
  must not introduce a new flex/grid item between the page body grid and
  the `.kanban-board` grid. Inheritance of custom properties through a
  `display: contents` node works correctly in all modern browsers (and
  in jsdom, which is what the integration test relies on).

### Follow-ups (v2.7)

- **Per-project lane-height key.** Some projects are dense
  (operations-heavy, hundreds of open tickets) and need the cap; others
  benefit from `unlimited`. Migrate to `kanban.laneHeight.<projectKey>`
  with a fallback chain to the global key.
- **Keyboard navigation on the segmented control.** Today the buttons
  are `role="radio"` but arrow-key navigation between them is not wired.
  Add `ArrowLeft` / `ArrowRight` handling and roving `tabindex` to match
  the WAI-ARIA radiogroup pattern.
- **Expose as a settings-page preference.** The toolbar control is
  discoverable but eats horizontal space. Once a `/settings` Kanban
  section exists (slated for v2.7), move the toggle there and replace
  the toolbar widget with a single icon button that opens the settings
  pane.
- **"Compact mode" preset.** Bundle `laneHeight=50vh` with future
  density toggles (card spacing, font scale) into a single one-click
  "Compact" preset. Store the bundle under `kanban.density.preset` and
  let advanced users override individual axes.

## WP44 — Audit-log retention + admin filter

### Scope

Hard-delete retention sweep for `activity_audit_log` running in the
FastAPI lifespan (no APScheduler, mirrors the WP39 due-soon scanner) +
a one-click "Handle overrides" admin filter chip for the
`user.handle_changed_by_admin` event added in WP35.

### What we built

- **Settings (`app/config.py`)**: `AUDIT_LOG_RETENTION_DAYS=365`
  (clamp 30..3650 → default), `AUDIT_LOG_RETENTION_SCAN_INTERVAL_SECONDS=86400`
  (min 3600), `AUDIT_LOG_RETENTION_ENABLED=True`. Pydantic v2 validators
  silently clamp invalid env to the default rather than raising — keeps
  bad env vars from crashing prod boot.
- **Service (`app/services/audit_log_retention.py`)**: `prune_once(session)` +
  `run_loop(session_factory)`. Single `DELETE FROM activity_audit_log
  WHERE created_at < :cutoff` with `synchronize_session=False`. Wraps the
  delete in `pg_try_advisory_lock` / `pg_advisory_unlock` exactly as WP39
  does, but with a *different* lock key derived from MD5 of the literal
  `"audit_log_retention"` — so the two scanners never contend with each
  other.
- **Lifespan wiring (`app/main.py`)**: started next to the due-soon
  scanner, cancelled in `finally`. Both tasks live behind the same
  `try/except` so a startup failure in one does not kill the app.
- **Backend filter**: the WP33 read API already had `?event=<name>`. No
  new query param was needed — the frontend simply drives that existing
  parameter.
- **Frontend (`Settings.tsx`)**: a stable `<button aria-pressed>` chip
  next to the existing event-filter input. Click sets `eventFilter` to
  `user.handle_changed_by_admin` and re-fetches; click again clears the
  filter. The existing `useEffect` reload-on-filter-change reuses the
  WP33 fetch path verbatim — no new state machine.

### Gotchas

- `prune_once` issues its own `await session.commit()` because the
  enclosing test fixture (`db`) rolls back. Tests that need to observe
  the delete must therefore use `session_factory` (not `db`) and clean
  up inserted fixture rows manually in a `finally`-block.
- The `Settings` instance returned by `get_settings()` is `@lru_cache`d
  *and* Pydantic-frozen at instantiation, so monkeypatching attributes
  on the cached object is fragile. The retention tests use a small
  `_Proxy` class that delegates unknown attrs to the real settings and
  overrides only the two fields the test cares about. Cheaper than
  fully rebuilding `Settings` (which would re-read env).
- Advisory-lock key choice: MD5 hash + 63-bit mask is overkill for two
  keys but matches the WP39 idiom exactly, so a future hash-collision
  audit (v2.7 follow-up) only has to look at one pattern, not two.

### Test count

- Backend: **+4 new tests** in
  `tests/services/test_audit_log_retention_wp44.py`
  (old-vs-new delete, exact count, contention-returns-zero, disabled
  setting → noop + `run_loop` exits). Suite totals went from
  313F/781P to 313F/**785P** — no regressions.
- Frontend: **+2 new tests** in `SettingsAdmin.test.tsx` (chip renders
  with `aria-pressed=false`; click toggles event filter and
  `aria-pressed`). Suite went from 176/176 to **178/178** in 25 files.

### Follow-ups (v2.7)

- **Cold-storage archival.** Today's `prune_once` is a hard delete. Add
  an "archive then delete" mode that streams rows to object storage
  (S3 / Azure Blob / GCS) before deleting — required for SOC2 audit
  trails that must outlive operational DB retention.
- **Per-event-type retention.** Some events (e.g. `auth.login_failed`)
  can churn fast and don't need 1y retention; others (e.g.
  `user.handle_changed_by_admin`) deserve longer. Move retention into
  a per-event config map.
- **Time-bucketed reads.** The audit-log read API is keyset-paginated
  by `created_at DESC` but offers no "between X and Y" window. Add a
  `?since=` / `?until=` pair and an index, especially once retention
  ages out the oldest rows and "last 30 days" becomes the common case.
- **Indexed timestamp.** If prune scans get slow at large row counts,
  add `CREATE INDEX CONCURRENTLY ON activity_audit_log (created_at)`.
  Not adding it in WP44 because the table is small enough today and
  Postgres' seq-scan-then-delete is faster at this size; revisit when
  table > 1M rows.
- **"Select all event types" filter UX.** The current quick-filter is
  binary (one event). For future filters (e.g. "all auth events"),
  consider a multi-select chip group or an event-category dropdown
  instead of stacking individual buttons.

## WP45 — Activity total + assignee_type DTO

Two small surface fixes that close the final v2.6 follow-ups.

### Decisions

- **Activity `total` now populated on every page.** v2.2-WP16 returned
  `total` only on the first page (`cursor is None`) on the theory that
  a full scan per "load more" would be wasteful. In practice the
  current implementation already materialises the entire in-memory
  union before slicing — `len(rows)` is free — so the previous nulling
  was a premature optimisation that complicated frontend bookkeeping
  for zero runtime saving. Flipped to always-compute.
- **Filter parity preserved.** The "filter" on this endpoint is the
  `include` set (`comments`, `links`). `total` is computed against the
  fully-included union *before* cursor slicing — same predicate as the
  items, count form.
- **Documented the v2.7 escape hatch.** When v2.7 moves the union to a
  SQL `UNION ALL` (the long-deferred WP18), the count should remain a
  single `COUNT(*)` over the same `WHERE`. If that gets expensive on
  huge tickets (>10k transitions) the answer is a denormalised counter
  or window function — not a return to per-page nulling.
- **`assignee_type` was already on `TicketDTO`** as `string | null`.
  Narrowed to `"user" | "agent" | null` so PersonPicker / Kanban
  avatar / inline-assignee consumers can branch without a type assert.
  Kept optional (`?:`) per the WP brief to avoid surfacing latent TS
  errors across the codebase.
- **No consumers refactored.** Per scope: just expose the narrowed
  type. A v2.7 WP can teach PersonPicker chips and Kanban avatars to
  branch on it.

### Test count

- Backend: replaced one outdated test, added two new ones in
  `tests/services/test_activity_service.py`
  (`test_total_populated_on_every_page`,
  `test_total_reflects_include_filter`) and one in
  `tests/routes/test_tickets_routes.py`
  (`test_assignee_type_in_response_json`). Also updated the
  page-2-total assertion in `tests/routes/test_transitions_endpoint.py`.
  Suite went from 313F/785P to **313F/787P** — no regressions.
- Frontend: **+1 new test file** `src/api/__tests__/ticketDto.test.ts`
  covering the narrowed union (`user` / `agent` / `null` / omitted).
  Suite went from 178/178 in 25 files to **179/179 in 26 files**.

### Files touched

- `app/services/tickets.py` — `list_activity` always returns `total`.
- `frontend/src/api/tickets.ts` — `assignee_type` narrowed.
- Tests as listed above.

### Follow-ups (v2.7)

- **Wire `assignee_type` into the UI.** PersonPicker chips, Kanban
  avatars, and inline-assignee display should branch on it (agent
  badge, different default avatar, scoped autocomplete).
- **SQL `UNION ALL` for activity feed (WP18).** Still deferred.
  Pair with this WP if the in-memory union starts dominating
  ticket-detail load time on hot tickets.

## v2.6 retrospective

### Final baselines

- Backend: **313F / 787P / 5 skipped / 14 xfailed**. The 313F count
  has been carried since pre-v2.6 — these are problem-bulletin v1
  legacy tests waiting on the v1→v2 schema bridge. v2.6 added a net
  **+39 passing tests** (from 748P at the start of WP38) without
  touching the failure bucket.
- Frontend: **179 / 179 in 26 files**. v2.6 added a net **+18
  passing tests / +5 files** (from 161 in 21 files at WP38 start).

### Net WP count

8 work packages: **WP38–WP45**.

- WP38 JWT test SecretStr fix (hygiene unlock)
- WP39 Scanner coordinator + configurable timing (concurrency hygiene)
- WP40 ticket_cancelled notification kind
- WP41 Watcher-added notification
- WP42 CreateTicket adopts new PersonPicker
- WP43 Kanban lane-height preference
- WP44 Audit-log retention + admin filter
- WP45 Activity total + assignee_type DTO

### Three themes that emerged across v2.6

1. **Hygiene WPs unlock measurement.** WP38 (JWT/SecretStr fix) and
   WP39 (scanner coordinator) didn't ship user-visible features, but
   they took the suite from "flaky enough to mask regressions" to
   "tight enough to lean on." Every subsequent WP got a clean
   before/after delta because of them. Pattern: don't skip the
   plumbing WP — its ROI is the *next* five WPs.
2. **Advisory-lock pattern is reusable.** WP39's scanner coordinator
   and WP44's prune-loop both converged on the same idiom (MD5 →
   63-bit mask, `pg_try_advisory_lock`, contention-returns-zero
   semantics). v2.7 should extract this into a single helper —
   `app/services/_advisory.py` with a `with_advisory_lock(key_str)`
   context manager — before the third copy lands.
3. **Frontend shared primitives compound.** PersonPicker (v2.5-WP32)
   paid off again in WP42 (CreateTicket adopts it) and is queued to
   pay off a third time in v2.7 (assignee_type-aware rendering, this
   WP). The Kanban lane-height hook (WP43) is similarly poised to be
   reused for column-width persistence. Pattern: when you build a
   reusable hook/component, the test cost is one-shot but the
   downstream WPs each get a discount.

### v2.7 starting prompt seed

Lead the next cycle with these (in priority order — they unlock the
rest):

1. **Wire `assignee_type` into the UI.** PersonPicker chips show an
   agent badge; Kanban card avatars resolve from `assignee_type +
   assignee_id` instead of `last_actor_type` heuristic; inline
   assignee display in `/tickets/:displayId` distinguishes human vs
   agent.
2. **Extract `with_advisory_lock` helper.** Both WP39 (scanner) and
   WP44 (prune loop) duplicate the MD5-hash + advisory-lock idiom.
   Consolidate into `app/services/_advisory.py` before a third caller
   lands.
3. **SQL `UNION ALL` for activity feed (long-deferred WP18).** The
   in-memory union in `TicketService.list_activity` is starting to
   show on hot tickets. Move to SQL, keep the same `COUNT(*)` shape
   for `total`. Pairs naturally with HMAC-signed cursors (WP19).
4. **Cold-storage archival for audit log.** WP44 hard-deletes; SOC2
   wants archive-then-delete. Stream to S3/GCS before prune.
5. **Per-event-type retention policy.** Today's retention is a single
   global window. Move to a per-`event_type` config map so high-churn
   events (`auth.login_failed`) can age out faster than rare admin
   actions (`user.handle_changed_by_admin`).
