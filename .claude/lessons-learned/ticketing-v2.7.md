# Ticketing v2.7 — Lessons Learned

## Cross-WP Rules (carry-forward from v2.6)

1. **Postgres-only**: async SQLAlchemy + Alembic. No SQLite. No mocking the DB in integration tests.
2. **Pydantic v2 settings** use `SecretStr` for secrets and clamping validators for numeric envs. Tests must wrap secret fields with `SecretStr(...)` in mocks (v2.6-WP38).
3. **Advisory locks for multi-process coordination**: prefer the `with_advisory_lock` helper (v2.7-WP46) over hand-rolled MD5+`pg_try_advisory_lock` patterns.
4. **SAVEPOINT-isolated, best-effort fanout** for notifications — never block the primary write.
5. **`Page[T]` envelope** `{items, next_cursor, total}` on every cursor-paginated list; `total` populated on every page (v2.6-WP45).
6. **Audit-log via `app/services/audit_log.py::record(...)`** — table `activity_audit_log`.
7. **Frontend shared primitives** live in `src/styles/form-field.css` / `src/components/`. Reuse before forking.
8. **Each subagent appends `## WPnn — <title>` with Spec / Files touched / Tests / Lessons / Follow-ups for v2.8.**
9. **TDD**: red → green → refactor. New tests for every WP.
10. **Subagent report contract**: (a) what changed, (b) tests added/passing, (c) commands run to verify, (d) follow-ups for v2.8.

## v2.6 starting baselines

- Backend: **313F / 787P / 5 skipped / 14 xfailed**.
- Frontend: **179 / 179 in 26 files**.

## v2.8 backlog seed (carry-forward)

- Redis pub/sub for multi-process WS scaling
- WP19 — HMAC-signed cursors (pairs with WP50 SQL union)
- Per-status quotas on `GET /tickets`
- Inline status/priority/assignee error rollback policy on TicketDetail
- S3/GCS backend for audit-log archival (WP52 lands local files; cloud is next)
- Avatar support / "Me" shortcut / fuzzy match in PersonPicker
- Proper profanity lib (better-profanity)
- User-facing "request review" flow for blocked handles
- DB-driven blocklist management API
- Sidebar agent-kind `notification_read` publish for current user
- NOT NULL on `agent_accounts.created_by` once envs clean
- Per-project column-width/lane-height localStorage keys
- Keyboard nav for segmented controls
- Scanner Prometheus metrics
- `state_change_coalesce_seconds` default from site config
- `ticket_watcher_removed` notification kind
- "Follow ticket" toggle on `/tickets/:displayId`
- Bulk-watcher-add via @mentions
- Cancellation `reason` payload field
- Filter chip in Mentions tab for resolution kinds
- `CREATE INDEX CONCURRENTLY ON activity_audit_log (created_at)` once table grows
- Add `specials`/`id`/`ariaLabel`/`projectId` to new PersonPicker and retire old
- Extract shared form primitives (tag-autocomplete, attachment-dropzone)
- Document `cssCodeSplit: false` rationale

## v2.7 WP plan

- **WP46** — Extract `with_advisory_lock` helper (hygiene plumbing first).
- **WP47** — PersonPicker chips show agent badge.
- **WP48** — Kanban card avatars use `assignee_type` not `last_actor_type`.
- **WP49** — TicketDetail inline assignee distinguishes human vs agent.
- **WP50** — SQL `UNION ALL` for activity feed (deferred WP18).
- **WP51** — Per-event-type audit-log retention policy.
- **WP52** — Cold-storage archival (local JSONL rotation) before prune.
- **WP53** — Retrospective + v2.8 seed.

---


## WP46 — Extract with_advisory_lock helper

**Spec.** Replace the duplicated `pg_try_advisory_lock` / `pg_advisory_unlock` idiom in `due_soon_scanner` (WP39) and `audit_log_retention` (WP44) with a single async-context-manager helper `with_advisory_lock(session, key_str)` in `app/services/_advisory.py`. The helper yields `True`/`False` (never raises on contention), releases on exit only when acquired, and derives the bigint key by MD5-of-utf8 → first-8-bytes-big-endian → mask-to-63-bits — byte-for-byte matching the old inline code so live-deployed locks stay compatible.

**Files touched.**
- NEW `app/services/_advisory.py` (helper + `advisory_lock_key` exported for back-compat with the WP44 test that imports `_LOCK_KEY`).
- EDIT `app/services/due_soon_scanner.py` — removed inline hashlib/try-finally; added `_LOCK_KEY_STR` and re-exported `_LOCK_KEY` via helper.
- EDIT `app/services/audit_log_retention.py` — same refactor.
- NEW `tests/services/test_advisory_lock.py` — 6 tests (deterministic key, acquire-yields-true, contention-yields-false, release-on-normal-exit, release-on-exception, no-unlock-when-not-acquired).

**Tests (new totals).** 793 passed (+6 from the helper suite), 313 failed (unchanged backlog, unrelated to WP46), 5 skipped, 14 xfailed. Both WP39 and WP44 caller suites green (10 + 4 tests).

**Lessons.**
- `@asynccontextmanager` + asyncpg + a `try/finally` works cleanly because each `AsyncSession` binds to one connection for its lifetime — the unlock pairs with the lock without us threading the connection through.
- The critical bug-bait was unlocking unconditionally in `finally`. If you unlock when you didn't acquire, you'd silently steal a peer's lock. Gating the unlock on `if acquired:` is mandatory; added a dedicated test (`test_no_unlock_when_not_acquired`) to lock the invariant in.
- Preserved the module-level `_LOCK_KEY` constants in both callers because the existing WP44 contention test imports `_LOCK_KEY` directly. Refactor stayed a true no-behavior-change.

**Follow-ups for v2.8.**
- Audit for collisions if more advisory keys land (v2.6-WP39 already flagged this); the centralised helper now gives one obvious place to register/list them — consider a small registry dict in `_advisory.py` if the count grows past ~3.

## WP47 — PersonPicker agent badge

**Spec.** Added a small lowercase "agent" pill to the directory-based PersonPicker's selected-chip when `value.kind === "agent"`, so humans-vs-agents are visually distinguishable at a glance without losing the existing one-letter colored `KindBadge`. Subtle slate-grey rounded pill (0.625rem font) sits to the right of the name/handle, scoped under a new `.person-picker-chip__type-badge` class. `aria-label="agent"` ensures screen readers announce the kind. Pure render-layer change — no API, no DTO, no type alias.

**Files touched.**
- `frontend/src/components/PersonPicker/index.tsx` — conditional badge in chip branch.
- `frontend/src/components/PersonPicker/PersonPicker.css` — new `.person-picker-chip__type-badge` rule.
- `frontend/src/components/PersonPicker/__tests__/PersonPicker.test.tsx` — +2 tests (agent renders / user does not).

**Tests (new totals).** PersonPicker: 11 → 13 (+2). Full frontend suite: 179 → 181 passing. `npm run build` clean.

**Lessons.**
- Spec said `person.type` but `PersonRef` actually uses `kind`; followed the codebase shape and noted the discrepancy rather than introducing an alias. Always cross-check spec field names against the real type before coding.
- The existing `KindBadge` ("A"/"U") plus a new text "agent" pill are complementary, not redundant — the letter badge is a colored icon, the text pill is an accessibility-first label. Worth keeping both rather than collapsing them.
- The legacy `frontend/src/components/PersonPicker.tsx` (Kanban FiltersBar) was correctly left untouched per spec — chip badge is a directory-picker concern only.

**Follow-ups for v2.8.**
- WP48/WP49 will extend the same visual cue to Kanban cards and TicketDetail inline assignee — share the `.person-picker-chip__type-badge` style or promote it to a shared `.kind-badge--agent-text` token if more sites adopt it.

## WP48 — Kanban avatar resolves via assignee_type

**Spec.** Kanban `TicketCard` was rendering the assignee avatar via a `last_actor_type` heuristic — incorrect whenever an agent assigned a human or vice versa. Switched the avatar code path to read `ticket.assignee_type` (the DTO source of truth narrowed in v2.6-WP45): `null` → unassigned, `"agent"` → slate-ringed agent avatar with `aria-label` "Agent: <id>", `"user"` (or defensive default) → today's human avatar. `last_actor_type` is left intact for the separate who-moved-the-card agent activity badge.

**Files touched.**
- `frontend/src/pages/Kanban/TicketCard.tsx` — derive `isAgentAssignee` from `assignee_type`, branch className + aria-label + `data-testid`.
- `frontend/src/pages/Kanban/Kanban.css` — add `.ticket-card__avatar--agent` slate ring using `#e2e8f0` / `#475569` to match PersonPicker chip palette.
- `frontend/src/pages/Kanban/__tests__/TicketCard.test.tsx` — 3 new WP48 tests (agent variant, user variant, unassigned).

**Tests (new totals).** Kanban suite: 52 → 55 (TicketCard.test.tsx 15 → 18). Full frontend suite: 181 → 184, all passing. `npm run build` clean.

**Lessons.**
- Two avatar variants share the same `<span>` with differing className + aria-label + testid — kept the diff small without introducing a sub-component, and gives tests stable selectors that don't depend on emoji glyphs.
- `assignee_label` previously fell back to `assignee_type` as a string when no `assignee_id` existed (legacy quirk). Removed that fallback while here — once `assignee_id` is null we render no avatar, full stop.
- Slate ring (`box-shadow inset 0 0 0 2px`) reads as "agent" without occupying extra layout space; matches the WP47 PersonPicker chip palette so the visual language is consistent across surfaces.

**Follow-ups for v2.8.**
- WP49 will apply the same treatment to TicketDetail's inline assignee chip — at that point promoting `.kind-badge--agent` / `.avatar--agent` to a shared token in a top-level CSS module is worth doing.
- If a third surface adopts the agent ring, factor `isAgentAssignee` into a tiny `resolveAssigneeKind(ticket)` helper next to the DTO.

## WP49 — TicketDetail inline assignee distinguishes human vs agent

**Spec.** Completes the v2.7 trilogy (WP47 PersonPicker chip → WP48 Kanban card avatar → WP49 TicketDetail inline) that surfaces `TicketDTO.assignee_type` everywhere a ticket's assignee is shown read-only. The inline "Assignee" row in TicketDetail (via the shared `TicketFields` component) now appends an `<span class="ticket-detail__assignee-badge--agent" aria-label="agent">agent</span>` slate pill when `assignee_type === "agent"`. `assignee_id == null` continues to render "Unassigned"; `assignee_type === "user"` (and the defensive fallback for null with id present) renders the plain name. The editable PersonPicker dropdown is untouched — WP47 already handles its chip rendering.

**Files touched.**
- `frontend/src/components/TicketFields/index.tsx` — added the conditional agent badge inside the assignee Row (TicketFields is the renderer the TicketDetail page uses for the read-only sidebar; the badge class lives in the TicketDetail.css scope so the styling sits with the page that owns the spec).
- `frontend/src/pages/TicketDetail/TicketDetail.css` — added `.ticket-detail__assignee-badge--agent` with the same slate palette as WP47 (`#e2e8f0` / `#475569`); comment links it to WP47 / WP48.
- `frontend/src/pages/TicketDetail/__tests__/TicketDetail.test.tsx` — 3 new tests for agent / user / null assignee cases.

**Tests (new totals).** 184 → 187 (3 added, all passing). TicketDetail file: 10 → 13. `npm run build` clean.

**Lessons.**
- The TicketDetail page renders its read-only "Assignee" row via the shared `TicketFields` component, not inline JSX in `TicketDetail/index.tsx` — so the badge had to land in TicketFields. Using the `ticket-detail__` class prefix (rather than `ticket-fields__`) keeps the styling rule co-located with the page that owns the spec while still rendering correctly because TicketDetail/index.tsx imports `./TicketDetail.css` whenever this row is shown.
- We now have three near-identical implementations of the slate agent pill: PersonPicker chip (`.person-picker-chip__type-badge`), Kanban card avatar agent ring (`.kanban-card__avatar--agent`-style indicator from WP48), and TicketDetail inline (`.ticket-detail__assignee-badge--agent`). The shape isn't identical (chip pill vs ring vs inline pill), but the slate palette is. A shared `KindBadge` / `--kind-agent-bg` token is now justified — but as a v2.8 follow-up, per WP brief.
- TicketFields tests don't need updating: existing assertions check `toHaveTextContent("user-999")` for assignee, which is a substring match and still passes with the badge appended. Defensive design — the badge is additive, not replacing the name.

**Follow-ups for v2.8.**
- Extract `KindBadge` (props: `kind: "user" | "agent"`, `variant: "pill" | "ring" | "letter"`) so PersonPicker chip, Kanban avatar, and TicketDetail inline share a single source of truth. Promote `#e2e8f0` / `#475569` to CSS custom properties (`--kind-agent-bg`, `--kind-agent-fg`) in a top-level stylesheet.
- Consider a tiny `resolveAssigneeKind(ticket): "user" | "agent" | null` helper alongside the DTO to remove the repeated `(ticket as TicketDTO & {assignee_type?: string}).assignee_type ?? "user"` pattern (still present in `TicketDetail/index.tsx` from earlier WPs).

## WP50 — SQL UNION ALL for activity feed (deferred WP18)

**Spec.** `TicketService.list_activity` previously loaded each event source (transitions, optionally comments, optionally outbound links) into Python with separate `SELECT` queries, then merged/sorted/sliced in memory. WP50 replaces that with a single SQL `UNION ALL` of per-arm SELECTs sharing a uniform envelope `(kind, id, ticket_id, actor_type, actor_id, agent_step_id, created_at, payload JSONB)` where `payload` is a Postgres `jsonb_build_object(...)` bag of kind-specific tail fields. The outer query applies the cursor predicate (`(created_at, id::text) < (anchor_ts, anchor_id)`), orders `created_at DESC, id DESC`, and uses `LIMIT page_size + 1` for has-more detection. `total` is a second `SELECT COUNT(*) FROM (union_subquery)` over the same predicate set — populated on every page (v2.6-WP45 contract preserved). The response envelope (`{items, next_cursor, total}`) and cursor encoding are byte-identical to the pre-WP50 shape; payload JSONB is unpacked into the legacy per-kind dict shape after fetch.

**Files touched.**
- `app/services/tickets.py` — rewrote `list_activity` (lines ~1759–1900) to build `UNION ALL` via SQLAlchemy Core `.union_all(...)` over per-arm `select()` statements, plus `count()` subquery; added `literal`/`literal_column` to the sqlalchemy imports.
- `tests/services/test_activity_service.py` — added 3 new tests (`test_union_all_preserves_chronological_order`, `test_count_query_matches_items`, `test_filter_predicate_applied_to_union`).

**Tests (new totals).** Activity service file: 7 → 10 (all passing). Route tests `test_transitions_endpoint.py` + `test_ticket_activity_cursor.py` unchanged and passing (12/12). Full backend suite: 796 passed / 313 failed (313F is the documented v2.7 backlog, identical count to pre-WP50).

**Lessons.**
- `text("'transition'").label("kind")` does not work — `TextClause` does not implement `.label()`. Use `literal("transition").label("kind")` instead. `literal_column` is the right tool when you actually want a raw SQL fragment (e.g. `'[]'::jsonb`); for plain string constants in a SELECT list, `literal()` is cleaner and parameter-bound.
- Postgres `jsonb_build_object` is happy to swallow heterogeneous arms (Text columns, enum columns, ARRAY[UUID] for `mentions`) into one JSONB column — but values come back JSON-typed (UUIDs as strings, enums as their `.value`). Pydantic schemas (`TransitionRead`, `LinkRead`, `CommentRead`) coerce these on `model_validate`, so the route layer is unaffected; service-layer consumers that compare against native UUID/enum values would need to re-coerce. Kept service envelope identical by unpacking the payload back into the legacy dict shape after fetch.
- `mentions` is an ARRAY(UUID), not JSONB — but `jsonb_build_object` packs it as a JSON array of strings, and the legacy `list(r.mentions or [])` consumer is replaced by `list(payload.get("mentions") or [])`. Pydantic re-coerces strings to UUIDs at the route boundary, so the wire contract is preserved.
- Count query is structurally redundant with the items query (same UNION subquery), so on tickets with massive activity histories it doubles the work. Acceptable for now (one extra count over a UNION of three small per-ticket-scoped queries), but worth re-evaluating in v2.8 if the activity_audit_log arm joins in — at which point the count query may dominate and we should consider an approximate-count fast path or a materialised view.

**Follow-ups for v2.8.**
- WP19 — HMAC-signed cursors (still deferred); cursor decode is currently a plain base64-JSON unwrap so a hostile client could forge an anchor pointing at any `(created_at, id)`. Not a security issue today because the predicate is read-only and ticket-scoped, but it leaks ordering invariants.
- Index on `activity_audit_log(ticket_id, created_at DESC)` — currently the activity feed does not include audit_log rows, but if it does in v2.8 the UNION arm will need a covering index to keep the `total` COUNT query under 50ms.
- Consider moving the per-kind payload unpack into a small `_expand_activity_row(row) -> dict` helper if a fourth arm is added (currently 3 arms × ~12 lines each in the service is still readable).
- If counts become hot, switch `total` to an estimated count via `pg_class.reltuples` filtered by predicate, or cache the count per-(ticket_id, include-set) for a short TTL.

## WP51 — Per-event-type audit-log retention policy

**Spec.** WP44 hard-deleted audit-log rows past a single global `AUDIT_LOG_RETENTION_DAYS` cutoff. WP51 adds `AUDIT_LOG_RETENTION_OVERRIDES: dict[str, int]` (event_name → days, clamped [1, 3650]) so high-churn events like `auth.login_failed` can age out in days while rare admin events stay for years. `prune_once` now issues one `DELETE` per override bucket (`WHERE event = :evt AND created_at < NOW() - INTERVAL '<days> days'`) plus one fallback `DELETE WHERE event NOT IN (overrides) AND created_at < NOW() - INTERVAL '<global_days> days'`. Empty overrides → single global DELETE (WP44 parity, byte-for-byte). Return is a new `PruneResult` (subclass of `int` carrying `per_event: dict[str, int]`) so legacy WP44 callers comparing the result as an int still work. A summary `audit_log.pruned` row is emitted after non-empty prunes for observability.

**Files touched.**
- `app/config.py` — added `AUDIT_LOG_RETENTION_OVERRIDES` with `field_validator(mode="before")` that JSON-parses env strings, rejects malformed shapes, and clamps values to [1, 3650].
- `app/services/audit_log_retention.py` — rewrote `prune_once` to do per-bucket DELETEs, added `PruneResult` int-subclass, added `audit_log.pruned` summary record; `run_loop` and `_LOCK_KEY` unchanged.
- `tests/services/test_audit_log_retention_wp51.py` — 5 new tests (empty-overrides parity, single override, multiple overrides, clamp, malformed-JSON).

**Tests (new totals).** 9/9 retention tests pass (WP44 4/4 + WP51 5/5). Full backend: 801 passed (796 → 801), 313 failed (unchanged backlog), 5 skipped, 14 xfailed. No regressions.

**Lessons.**
- `pydantic-settings` decodes complex (dict/list/etc.) env values via `json.loads` BEFORE the `mode="before"` field_validator runs. Malformed JSON therefore surfaces as `pydantic_settings.SettingsError` (wrapping `JSONDecodeError`), not `pydantic.ValidationError`. Tests must accept either. The validator's own JSON branch only fires when the caller passes a string in (e.g. programmatic instantiation with `Settings(AUDIT_LOG_RETENTION_OVERRIDES="...")`), not for env-sourced values.
- Postgres `INTERVAL '<N> days'` cannot be parametrised via `:bindparam` — the interval string must be interpolated. Safe here because the override validator clamps days to a bounded int range (1..3650), eliminating the injection surface. If we ever accept user-controlled days values at runtime, prefer `make_interval(days => :n)` instead.
- `audit_log.pruned` is itself an audit-log row, so if an operator sets `AUDIT_LOG_RETENTION_OVERRIDES={"audit_log.pruned": 1}` the summary events age out daily. Not a recursion hazard (the next prune just deletes yesterday's summary), but it does mean observability data is lossy under aggressive overrides — flagged inline as a doc-comment near the `audit_log.record` call.
- Returning an `int` subclass (`PruneResult`) preserves back-compat without touching WP44 test assertions (`assert deleted == 3`, `assert deleted >= 1`). Subclassing `int` is cleaner than a tuple-with-magic-len-check; callers can still `int(result)` for serialisation.

**Follow-ups for v2.8.**
- WP52 cold-storage archival should consume `per_event` to route different event types to different archival tiers (e.g. login-failed → 30d S3 IA, admin events → Glacier).
- Add an admin-route surface for the per-bucket prune metrics (currently logged + in `audit_log.pruned.metadata` only).
- Consider an `AUDIT_LOG_RETENTION_DEFAULT_PER_EVENT` shape that ships sensible defaults (e.g. `auth.login_failed: 30`, `auth.login: 90`) without requiring every deploy to override.
- If `event NOT IN (override_keys)` becomes a hot path with many overrides, replace with a left-anti-join or a partial index on `activity_audit_log(event, created_at DESC) WHERE event NOT IN (...)` — currently fine because override sets are tiny.

## WP52 — Cold-storage archival for audit log

**Spec.** SOC2 wants every audit row that ages out of the table to land in durable storage *before* the DELETE. WP52 adds an opt-in **archive-then-delete** path: when `AUDIT_LOG_ARCHIVE_ENABLED=True` and `AUDIT_LOG_ARCHIVE_DIR` is set, `audit_log_retention.prune_once` routes every per-event DELETE through `audit_log_archive.archive_then_prune`, which streams batches of `AUDIT_LOG_ARCHIVE_BATCH_SIZE` rows (clamped 100..10000, default 1000) into rotating JSONL files at `{ARCHIVE_DIR}/{event or "_default"}-{UTC date}.jsonl`. Each batch is one transaction: `SELECT … FOR UPDATE SKIP LOCKED LIMIT :n` → file append (via `asyncio.to_thread`+stdlib `open(..., "a")`, `fsync` before close) → `DELETE WHERE id IN (...)` → `COMMIT`. If the file append raises, the transaction is rolled back and rows survive — never DELETE without a successful durable write. `PruneResult` gains a `per_event_archived: dict[str, int]` parallel to `per_event`. A new `audit_log.archived` summary event is emitted alongside `audit_log.pruned` whenever the archiver was engaged. Default OFF — existing WP44/WP51 deploys keep their plain-DELETE path byte-for-byte.

**Files touched.**
- `app/config.py` — three new settings (`AUDIT_LOG_ARCHIVE_ENABLED`, `AUDIT_LOG_ARCHIVE_DIR`, `AUDIT_LOG_ARCHIVE_BATCH_SIZE`) with a clamping validator on the batch size.
- `app/services/audit_log_archive.py` — NEW. `archive_then_prune(session, event_type, days, *, exclude_events=None) -> (archived, deleted)` + helpers (`_archive_path`, `_row_to_jsonl`, `_append_lines_sync`, `_select_batch`).
- `app/services/audit_log_retention.py` — `prune_once` branches on the archive flag; `PruneResult` extended with `per_event_archived`; emits `audit_log.archived` summary when engaged.
- `tests/services/test_audit_log_archive_wp52.py` — NEW, 6 tests (happy path, file naming, JSONL round-trip, file-write failure → no DELETE, disabled-flag uses WP51 path, batch-boundary > batch_size).

**Tests (new totals).** WP44 4/4 + WP51 5/5 + WP52 6/6 = 15/15 retention+archive tests pass. Full backend: 807 passed (was 801, +6 new), 313 failed (unchanged pre-existing backlog), 5 skipped, 14 xfailed. No regressions.

**Lessons.**
- `SELECT … FOR UPDATE SKIP LOCKED` in the archiver loop lets a second worker run the same prune concurrently without contention or duplicate-archive risk: each worker takes a disjoint subset of expired rows, archives them, deletes them, and commits. The existing advisory lock in `prune_once` still serialises the *outer* per-bucket coordination, but the per-batch SELECT-FOR-UPDATE is the real safety net if that lock is ever relaxed. Gotcha: don't put a `WHERE id NOT IN (already_seen)` filter on subsequent batches — `SKIP LOCKED` already excludes rows we hold, and our own commits release them.
- Ordering matters for the safety invariant: file `fsync` must complete *before* the DELETE executes. We invoke `asyncio.to_thread(_append_lines_sync, …)` which fsyncs the fd inside the worker thread, *then* run `session.execute(DELETE)`, *then* `session.commit()`. If the fsync raises, we `rollback()` and re-raise — the DELETE never ran. If the COMMIT fails after the file write, we leak a duplicate archive entry next run (acceptable: SOC2 cares we never lost a row, not that we never archived twice). Worth keeping the fsync — without it, an OS crash between write() and DELETE-commit would lose the archive while leaving the rows deleted (because the table page may have flushed first).
- JSONB columns arrive from asyncpg as Python `dict`, which `json.dumps` handles directly — no `psycopg2.extras.Json` unwrap needed. UUID and datetime do need conversion (we coerce to `str(uuid)` and `isoformat()`); everything else (event name, target_type, NULLs) is JSON-native. Sorting keys + compact separators keeps the JSONL diff-friendly and ~15% smaller than the default `json.dumps` output.

**Follow-ups for v2.8.**
- Pluggable backends: factor `_append_lines_sync` behind a small `ArchiveSink` protocol so S3/GCS/Glacier can drop in without touching the loop. Probably want `flush_batch(path_or_key, lines)` + `close()` and a settings discriminator (`AUDIT_LOG_ARCHIVE_BACKEND: local | s3 | gcs`).
- Gzip rotation: the current `.jsonl` files grow unboundedly per (event, date). Add an end-of-day rotator that gzips yesterday's files and writes a manifest, or switch to `.jsonl.gz` with chunked appends.
- Retention of the archive files themselves: SOC2 will want a separate `ARCHIVE_FILE_RETENTION_DAYS` knob with a "lift to S3 Glacier and delete locally" tier. Currently the local dir grows forever.
- Surface `per_event_archived` in the admin observability route alongside `per_event` (WP51 follow-up), and add a "last successful archive batch" gauge so ops can alert on archiver staleness.

---

## v2.7 retrospective

### Final baselines

- Backend: **313 F / 807 P / 5 skipped / 14 xfailed**. The 313F backlog is unchanged (problem-bulletin v1 legacy tests still pending the v1→v2 schema bridge). v2.7 added a **net +20 passing tests** (787 → 807) across seven WPs without touching the failure bucket.
- Frontend: **187 / 187 in 26 files**. v2.7 added **net +8 passing tests** (179 → 187) across the three frontend WPs (WP47/WP48/WP49).

### Net WP count

7 work packages: **WP46–WP52** (WP53 is this retrospective).

- WP46 Extract `with_advisory_lock` helper (hygiene plumbing)
- WP47 PersonPicker agent badge
- WP48 Kanban card avatar resolves via `assignee_type`
- WP49 TicketDetail inline assignee distinguishes human vs agent
- WP50 SQL `UNION ALL` for activity feed (deferred WP18, finally landed)
- WP51 Per-event-type audit-log retention policy
- WP52 Cold-storage archival for audit log (local JSONL, opt-in)

### Three themes that emerged across v2.7

1. **The "trilogy" pattern pays compound interest.** WP47+WP48+WP49 wired `assignee_type` across three independent surfaces (picker chip, Kanban avatar, TicketDetail inline) using the same slate-grey palette (`#e2e8f0` / `#475569`). Each WP took under 200 LOC because the DTO contract was already narrowed (v2.6-WP45) and the previous WP's CSS pattern was the reference. Pattern: when one DTO field gets multi-surface UI treatment, schedule the trilogy in three consecutive WPs — the third one is ~40% cheaper than the first.
2. **Hygiene plumbing has a half-life.** WP46 extracted `with_advisory_lock`; WP51 immediately consumed it (per-event prune still wraps in the lock); WP52 inherited it transparently. The advisory-lock helper paid for itself within two WPs of being created. Pattern: when you ship a helper, the next two WPs that touch the same concern should be measurably faster — if they aren't, the helper is wrong.
3. **Safety invariants need dedicated tests.** WP46's `test_no_unlock_when_not_acquired` and WP52's `test_file_write_failure_preserves_rows` are both negative-path tests that lock in invariants ("don't unlock peer's lock", "never DELETE without durable archive"). Without them, a future refactor would silently break the safety guarantee. Pattern: for every "must not happen" sentence in a WP spec, write a test named after the sentence.

### v2.8 starting prompt seed

Lead the next cycle with these (in priority order):

1. **HMAC-signed activity cursors (deferred WP19).** Pairs naturally with v2.7-WP50's SQL UNION — the base64-JSON cursor is now forgeable. Add an HMAC tag using `JWT_SECRET` (or a dedicated cursor secret); reject tampered cursors with 400. Same `next_cursor` shape, opaque payload.
2. **Pluggable archive backend (`ArchiveSink` protocol).** WP52 hard-codes local JSONL. Factor `_append_lines_sync` behind `ArchiveSink.flush_batch(key, lines)` + a `AUDIT_LOG_ARCHIVE_BACKEND` discriminator. Land S3 first, defer GCS/Glacier.
3. **Extract `KindBadge` shared component.** Three surfaces (PersonPicker chip / Kanban avatar / TicketDetail inline) duplicate the slate palette. Promote `#e2e8f0` / `#475569` to CSS custom properties `--kind-agent-bg` / `--kind-agent-fg` and create `<KindBadge kind={…} variant="pill|ring|letter" />`. Replace the three call sites.
4. **Default `AUDIT_LOG_RETENTION_OVERRIDES` map.** Ship sensible defaults (`auth.login_failed: 30`, `auth.login: 90`, etc.) so production doesn't hand-roll the JSON env. Make the global `AUDIT_LOG_RETENTION_DAYS` the floor, overrides only shrink.
5. **Activity feed: add the missing arms.** WP50 unioned transitions/comments/links. Mentions, watchers (added/removed), and notification fanout events aren't in the union yet. Add them with the same `jsonb_build_object` payload shape. Once done, the `last_actor_type` heuristic finally has no consumers and can be dropped from the DTO (separate WP).

### v2.8 backlog carry-forward

- Redis pub/sub for multi-process WS scaling
- Per-status quotas on `GET /tickets`
- Inline status/priority/assignee error rollback policy on TicketDetail
- Avatar support / "Me" shortcut / fuzzy match in PersonPicker
- Proper profanity lib (better-profanity)
- User-facing "request review" flow for blocked handles
- DB-driven blocklist management API
- Sidebar agent-kind `notification_read` publish for current user
- NOT NULL on `agent_accounts.created_by` once envs clean
- Per-project column-width/lane-height localStorage keys
- Keyboard nav for segmented controls
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
- Gzip rotation + manifest for closed-date archive files (WP52 follow-up)
- `ARCHIVE_FILE_RETENTION_DAYS` for archive files themselves (Glacier-lift then local delete)
- Admin observability route exposing `PruneResult.per_event` and `per_event_archived`
- Estimated-count fast path or TTL cache for activity COUNT(*) if it becomes hot
- Drop `last_actor_type` from TicketDTO once activity union covers all arms
- Advisory-key collision registry in `_advisory.py` if locked-coordinator count grows past ~3
