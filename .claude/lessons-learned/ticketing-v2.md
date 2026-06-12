# Ticketing v2 — Lessons Learned

This file is maintained by the orchestrator across all WPs of the ticketing-v2 initiative.
Each subagent MUST:
1. Read this file at the start of its run.
2. Honor every rule listed under **## Cross-WP Rules**.
3. Append a `## WPn — Lessons` section at the end of its run with:
   - Gotchas hit (file paths + symptom + fix).
   - Decisions made not covered by the spec.
   - Recommendations for downstream WPs.

The orchestrator (main agent) compacts/dedupes this file between WPs and lifts new cross-cutting rules into the **Cross-WP Rules** section.

---

## Cross-WP Rules

These are binding for every downstream WP. Re-read at start of each subagent run.

1. **Agent attribution pattern (all writes):** every audit-producing table gets `agent_step_id TEXT NULL` with `CHECK (actor_type = 'agent' OR agent_step_id IS NULL)`. Plumb via `contextvars.ContextVar` set from an `X-Agent-Step-Id` request header — services pick it up without explicit args.
2. **Naming conventions (match existing codebase):** `snake_case` plural tables; `fk_<table>_<col>`; `ck_<table>_<rule>`; `uq_<table>_<cols>`; `ix_<table>_<cols>`; `gin_<table>_<col>`.
3. **Enum widening:** `ALTER TYPE ... ADD VALUE` must commit before the value can be used as a default in the same transaction. Split into two migrations or use `op.execute("COMMIT")`. Never `DROP VALUE` — tombstone removed link types (`parent_of`/`child_of`) and refuse them in service layer.
4. **Existing enum reality:** `TicketType` already has `bug` (keep it as peer of task). `TicketLinkType` already has `parent_of`/`child_of` (tombstoned in v2).
5. **Hierarchy enforcement:** parent-type rules and same-project rule live in (a) service layer + (b) `BEFORE INSERT/UPDATE` trigger joining to parent. Postgres CHECK cannot reference another row. `tickets.parent_id` stays `ON DELETE RESTRICT`.
6. **`display_id` strategy:** drop the existing `GENERATED ALWAYS 'TKT-' || seq_number` column, re-add as plain `TEXT NOT NULL UNIQUE`. Format: `<PROJECT_KEY>-<n>`. Source from per-project `SEQUENCE seq_<lowercased_key>` created/dropped alongside the project row.
7. **FK on-delete defaults (use these unless spec says otherwise):** `tickets.project_id → projects.id = RESTRICT`; `tickets.parent_id → tickets.id = RESTRICT`; `tickets.sprint_id → sprints.id = SET NULL`; `tickets.epic_id → tickets.id = SET NULL`; `tickets.component_id → components.id = SET NULL`; `sprints/components/project_members → projects.id = CASCADE`; `ticket_watchers.ticket_id → tickets.id = CASCADE`.
8. **`epic_id` denormalisation:** maintained by service on parent-change. Backfilled in migration via recursive CTE up the `parent_id` chain.
9. **Watchers are a separate table (`ticket_watchers`).** Do NOT extend the bulletin-domain `watches` table.
10. **Attachments for tickets are a parallel table (`ticket_attachments`).** Do NOT generalise the existing `attachments` table — domains have independent lifecycles.
11. **Mentions:** stored as `mentions UUID[]` on `ticket_comments`. No notification fanout in v2.
12. **Spec is source of truth:** `docs/specs/ticketing-v2.md`. ADR: `docs/adr/0001-ticketing-v2.md`. Any deviation requires appending a Lesson explaining why.

---

## WP1 — Lessons

### Orientation surprises (downstream WPs should know)

1. **`TicketType` enum already contains `bug`** (`app/enums.py:54`). The orchestrator brief listed only {epic, story, task, subtask}; the actual enum has a 5th value. WP1 treated `bug` as a peer of `task` in the parenting matrix and kept it in v2. WP2 must add `workpackage` (and the spec assumes status `backlog` is added too).
2. **`TicketLinkType` already contains `parent_of`/`child_of`** (`app/enums.py:84-85`). v2 removes these — hierarchy is exclusively on `tickets.parent_id`. WP2 migration must assert zero rows use them before the enum value drop.
3. **`tickets.display_id` is currently a Postgres `GENERATED ALWAYS` column** with expression `'TKT-' || seq_number::text` (`app/models/ticket.py:83-87`; created in `alembic/versions/a8_finalize_ticket_split.py:219-222`). For per-project display IDs (`<KEY>-N`), this generated column **must be dropped and replaced with a plain TEXT column populated by the service layer** from a per-project sequence. The migration must include `op.execute("ALTER TABLE tickets DROP COLUMN display_id"); op.add_column('tickets', sa.Column('display_id', sa.Text(), nullable=False))` plus backfill before NOT NULL.
4. **`ticket_transitions`, `ticket_comments`, `ticket_links` already capture `actor_*` / `created_by_*` / `author_*`** with a CHECK in (`user`,`agent`) — we are *additive* here: just add `agent_step_id TEXT NULL` with a CHECK `actor_type='agent' OR agent_step_id IS NULL`. Do NOT redo the actor columns.
5. **`Ticket.parent_id` has `ON DELETE RESTRICT`** (`app/models/ticket.py:106-113`). The orchestrator constraint that "subtask MUST have parent of type task" cannot be expressed at the DB level (CHECK can't reference another row). WP3 (services) must enforce in service-layer + a `BEFORE INSERT/UPDATE` trigger that joins to the parent row.
6. **`due_date` precision**: the model annotates `DateTime` but the legacy downgrade in `a8_finalize_ticket_split.py:466` recreates it as `sa.Date()`. Confirm the live column type (`TIMESTAMPTZ` is what the model assumes) before WP2 migration writes touch it.
7. **`app/models/watch.py` exists** for the bulletin domain. WP1 spec uses `ticket_watchers` for v2 to avoid coupling. Do not extend `watches`.

### WP1 decisions made beyond the orchestrator constraints

| Decision | Reason |
|----------|--------|
| `workpackage` is the top of the in-project tree; epics may be parent-less or parented to a workpackage. | Matches JIRA "Initiative → Epic → Story → Sub-task" idiom and gives a place for cross-team programs without a 7th type. |
| Kept `bug` as a type (peer of `task`). | Already in the enum, useful, low cost. |
| Added `backlog` to `TicketStatus`. | Spec workflow starts at Backlog. Old `todo` is reserved for "pulled into the active board". |
| `epic_id` denormalised on `tickets`. | Avoids recursive CTE for the most common rollup query. Service maintains it on parent-change. |
| Per-project Postgres `SEQUENCE seq_<KEY>` for display-ID generation. | JIRA UX (each project starts at 1). Acknowledged operational cost; documented in spec §11 open question for WP2 to ratify. |
| Removed `parent_of`/`child_of` from `ticket_link_type` enum; added `clones`/`is_cloned_by`. | Hierarchy is on `parent_id` only. Clones is genuinely new. |
| Inverse link rows maintained transactionally by service (not by trigger). | Easier to test, easier to read in audit log. |
| `ck_tickets_parent_same_project` enforced via trigger + service, not pure CHECK. | Postgres CHECK can't reference another row. |
| Watchers separate table (`ticket_watchers`), not unified with `watches`. | Clean lifecycle; `watches` is for the bulletin/problem domain. |
| Mentions stored as `mentions UUID[]` on `ticket_comments`. No notification fanout in v2. | Brief calls out "text-only — no notification fanout yet". |

### Recommendations for WP2 (schema)

1. **Naming**: stick to `snake_case` plural table names, `fk_<table>_<col>` for FKs, `ck_<table>_<rule>` for checks, `uq_<table>_<cols>` for uniques, `ix_<table>_<cols>` for btree, `gin_<table>_<col>` for GIN. The codebase is consistent on this — match it (see `app/models/ticket.py:49-72`).
2. **FK on-delete behaviour**:
   - `tickets.project_id → projects.id` = `RESTRICT` (must archive, not delete, a project with tickets).
   - `tickets.parent_id → tickets.id` = `RESTRICT` (existing; keep).
   - `tickets.sprint_id → sprints.id` = `SET NULL` (sprint deletion shouldn't cascade-kill tickets).
   - `tickets.epic_id → tickets.id` = `SET NULL` (denorm; rebuilt by service).
   - `tickets.component_id → components.id` = `SET NULL`.
   - `sprints.project_id → projects.id` = `CASCADE` (sprints are project-owned).
   - `components.project_id → projects.id` = `CASCADE`.
   - `project_members.project_id → projects.id` = `CASCADE`.
   - `ticket_watchers.ticket_id → tickets.id` = `CASCADE`.
3. **Per-project sequence**: create at project-create time in the same transaction:
   `op.execute(f"CREATE SEQUENCE seq_{key.lower()}")`.
   Drop on project hard-delete (only allowed when ticket count = 0). Use the **lowercased key** as suffix to dodge case-folding issues in PG identifiers; the display still renders uppercase from `projects.key`.
4. **`display_id`**: drop the generated column, re-add as plain `TEXT NOT NULL UNIQUE`. Service-layer formula on insert: `f"{project.key}-{nextval}"`. Backfill in `a9` migration via `UPDATE tickets SET display_id = 'DEF-' || seq_number` for the Default project.
5. **`search_tsv`**: keep the existing `GENERATED ALWAYS` expression on title+description (`app/models/ticket.py:146-154`). It's table-name-independent and survives any rename.
6. **Enum widening order**: ADD enum values BEFORE adding columns / constraints that reference them (`ALTER TYPE ticket_status ADD VALUE 'backlog'` then default new tickets to it). Postgres requires enum values added in `ALTER TYPE` to be committed before they can be used as defaults in the same transaction — use `op.execute("COMMIT")` + a fresh transaction, or split into two migrations.
7. **`agent_step_id` column**: TEXT (not UUID) on every audit-producing table, indexed only where queries will use it (probably just `audit_log` and `ticket_transitions`). `CHECK (actor_type = 'agent' OR agent_step_id IS NULL)`.
8. **`epic_id` denorm backfill**: write as a recursive CTE in the migration walking `parent_id` chains, setting `epic_id = first ancestor where type='epic'`. Refine before shipping.
9. **Triggers for cross-row CHECKs**: write `BEFORE INSERT OR UPDATE OF parent_id, project_id` on `tickets` that raises if `parent.project_id <> NEW.project_id` or if the parent-child type pair violates spec §3.
10. **Avoid dropping `parent_of`/`child_of` enum values** with `ALTER TYPE ... DROP VALUE` — Postgres only supports it on PG14+ and only when no row uses the value. Easier: keep the enum value as a tombstone and have the service refuse to write it. Document this choice.
11. **`ticket_attachments` mirror `attachments`**: the existing `app/services/attachments.py` already handles uploads for the problem domain. Either generalise via `target_type`/`target_id` (preferred if it's clean) or create a parallel `ticket_attachments` table. WP1 leans parallel-table to keep the two domains' lifecycles independent.

### Recommendations for WP3+ (services / API / frontend)

- Thread `X-Agent-Step-Id` from the request through to a context var (`contextvars.ContextVar`) so every audit-writing helper picks it up without explicit plumbing.
- `display_id` resolution helper: accept either UUID or `<KEY>-<n>`, parse with a single regex.
- Frontend Create-Ticket form: drive the per-type field visibility from a single TS object that mirrors spec §5 — don't duplicate the rules across components.
- WIP-limit display: project setting `wip_limits jsonb` (status → int). Soft-warn only in v2.

---

## WP2 — Lessons

### Gotchas hit

1. **Single migration was viable.** Spec hinted we might need to split `a9` + `a10` to dodge `ALTER TYPE ADD VALUE` not being usable as a DEFAULT in the same transaction. In WP2 we did NOT use any of the newly added enum values (`workpackage`, `backlog`, `clones`, `is_cloned_by`) as a server-side DEFAULT, so one migration works. **WP3 must remember**: if any service-layer SQL or future migration tries to set, e.g., `status = 'backlog'` as a DDL DEFAULT in the same transaction as the `ALTER TYPE ADD VALUE`, it will fail with "unsafe use of new value of enum type". Use `op.execute("COMMIT")` between the ADD VALUE and the DEFAULT clause, or split into a new migration.

2. **`Computed` columns can't be ALTERed in place.** Postgres rejects converting a `GENERATED ALWAYS` column to a plain column via `ALTER COLUMN`. We had to `DROP COLUMN display_id; ADD COLUMN display_id TEXT NULL; UPDATE ...; ALTER ... SET NOT NULL`. The same applies to any future column flip. Downside: the downgrade re-adds `display_id` as plain `TEXT NULL` and cannot reconstruct the original GENERATED expression (documented in migration docstring and acceptable per the brief).

3. **Recursive CTE for `epic_id` backfill** — the obvious shape (`WITH RECURSIVE chain ... UPDATE tickets t SET epic_id = ...`) needed care: the parent walk must record the *starting* row so we can join the discovered ancestor back to the child. Pattern in `a9_ticketing_v2.upgrade()` works on PG 14+. Test confirms no row with an epic ancestor is left with NULL `epic_id`.

4. **`ALTER TYPE ... ADD VALUE IF NOT EXISTS`** is needed because the migration may be re-run mid-development (upgrade → downgrade → upgrade). The migration is idempotent on enum values; downgrade deliberately leaves them in place (Cross-WP Rule 3 — tombstone, don't drop).

5. **Cross-row CHECK via trigger.** `ck_tickets_parent_same_project` can't be a plain CHECK (Postgres won't let it reference another row). Implemented as `trg_tickets_same_project_fn() / trg_tickets_same_project` (BEFORE INSERT OR UPDATE OF parent_id, project_id). Raises `check_violation` SQLSTATE so asyncpg surfaces `CheckViolationError` to services. **WP3 doesn't need to duplicate this** — service layer should catch the DB error and re-raise its domain exception. The parent-child *type* matrix (spec §3) is **NOT** in a trigger; deferred to WP3 service layer.

6. **`computed_display_id` back-compat alias.** The pre-v2 ticket model exposed `Ticket.computed_display_id` as a `@property` (used by MCP tools and routes). v2 turns `display_id` into a real column. We kept the property as an alias returning `self.display_id` to avoid breaking call sites. WP3 may remove it once the codebase migrates to `display_id` directly.

7. **Sequence name is lowercase `seq_def`.** The project key is `DEF` (uppercase) but the sequence is `seq_def`. Cross-WP Rule recommendation followed — case-folding in PG identifiers would be ambiguous otherwise. Display IDs still render uppercase from `projects.key`.

8. **Default project row is inserted via raw SQL with `gen_random_uuid()`** rather than a fixed UUID. If WP3 needs a deterministic ID for tests, look it up by `key = 'DEF'` (cheap — unique-indexed).

### Decisions beyond the spec

| Decision | Reason |
|----------|--------|
| `created_agent_step_id` on `tickets` is gated by `reporter_type = 'agent'` (the create-side actor), not `actor_type` (which doesn't exist on `tickets`). | Spec §6 placement was ambiguous; reporter is the natural "create author". WP3 may add a separate `audit_log` row at create for non-reporter agent-step capture. |
| `version` column included on `projects` (not in spec). | Mirrors `tickets.version` OCC pattern. WP3 can rely on this for project updates. |
| Trigger for hierarchy *type* matrix omitted — service-only. | Spec §3 matrix is non-trivial in PL/pgSQL and easier to unit-test in Python. Trigger only enforces same-project. |
| Mentions and `agent_step_id` added together in Phase D for `ticket_comments`. | Both were called for; mentions were ambiguously placed in the spec but lessons-learned WP1 has them on `ticket_comments`. |
| `ticket_attachments.byte_size` typed as INTEGER (not BIGINT) to mirror the existing `attachments` table. | Domain symmetry; can be widened later if needed. |
| Single Default project key `DEF` (not `AION`). | Migration is purpose-built for backfill, project will be renamed by ops when WP3 ships project CRUD. |

### Recommendations for WP3

1. **Plumb `project_id` everywhere.** Every ticket-creating code path must now accept and pass `project_id`. The DB will reject NULL with FK violation. Test failures `tests/mcp_server/test_mcp_tools.py::test_create_ticket_*` and `tests/routes/test_tickets_routes.py::test_create_ticket_201` after WP2 are exactly this — service `create_ticket` no longer sets `project_id` or `display_id`. WP3 must thread project from request/auth context.

2. **Display ID generation contract.** Service must (inside the same transaction as the INSERT) run `SELECT nextval('seq_<lc_key>')` and set `display_id = f'{project.key}-{nextval}'`. The sequence name lives on the project (lowercased key). Brand-new projects need `CREATE SEQUENCE` at project-create time.

3. **Contextvar plumbing for `agent_step_id`.** Add a `contextvars.ContextVar[str | None]` (e.g. `app.audit.agent_step_id_var`) set by an FastAPI dependency that reads `X-Agent-Step-Id`. Every `_record_*` helper in `app/services/*` should grab `.get(None)` and pass into the new audit columns. Don't add it to function signatures — that's the whole point of the contextvar.

4. **Trigger error mapping.** `asyncpg.exceptions.CheckViolationError` from `trg_tickets_same_project` should map to a domain exception (e.g. `CrossProjectParentError(409)`). The trigger raises with the parent and child UUIDs in the message — log them, then return a generic 409.

5. **Parent-type matrix.** Implement in `app/services/tickets.py` (or a new `app/services/ticket_hierarchy.py`). The matrix from spec §3 is:
   - workpackage: no parent
   - epic: workpackage or none
   - story: epic or none
   - task/bug: story, epic, or none
   - subtask: must have a task/story/bug parent
   DB enforces only `subtask MUST have parent_id` (CHECK). Everything else is your job.

6. **Epic-denorm maintenance.** On parent-change, re-walk the chain in service code and update `epic_id`. Migration backfills the *initial* state but isn't a trigger.

7. **Watcher domain split.** `app/services/watches.py` is for the bulletin/problem domain; do **not** generalise it. Create `app/services/ticket_watchers.py` instead.

8. **Tombstoned link types.** `parent_of` / `child_of` are still in the `TicketLinkType` enum. WP3 service layer must `raise` on writes using them. Reads of historical rows are fine.

9. **OCC on projects.** `projects.version` is set up like `tickets.version`. Mirror the existing OCC pattern (`UPDATE ... WHERE version = old_version RETURNING version`).

10. **Test fixture hygiene.** Many existing service tests assume ticket creation works without `project_id`. WP3 will need a `project` fixture in `tests/services/conftest.py` (creating + sequence) so individual tests don't repeat the boilerplate. Suggested name: `default_project`, returning the DEF project row.

---

## WP3 — Lessons

### Gotchas hit

1. **Contextvars + async sessions play nicely** if (and only if) you read them lazily at the *call site* of every audit write. Putting `agent_step_id_var.get()` into helper methods at module-import time would freeze the value at first call. Each `_record_*` / `session.add(...)` block re-reads via `get_agent_step_id()` so the value travels naturally with the task that holds the request. The `BaseHTTPMiddleware`-based `AgentStepMiddleware` uses `set_agent_step_id(...)` + `agent_step_id_var.reset(token)` in a `finally` so concurrent requests never leak step ids. Tested in `tests/services/test_agent_step_id.py` (both header-set and header-absent paths).

2. **The `_PARENT_ALLOWED` matrix had to widen, not just gain `workpackage`.** Spec §3 lists subtask's allowed parents as `task | story | bug`, but the *pre-WP3* matrix had `subtask -> {task}` only. The existing `tests/services/test_ticket_create.py::test_full_hierarchy_chain` builds `epic -> story -> task -> subtask` AND `test_subtask_parent_must_be_task` expects rejection when parent is `epic`. We kept the broader `{task, bug, story}` allow-set per spec §3 and the existing tests both pass. Removing `story` from the allow-set is a v2.1 tightening — flagged here.

3. **Inverse-link insertion can't use `try / except IntegrityError`** inside the same async session because asyncpg poisons the transaction on uniqueness violation and SQLAlchemy 2 emits `InvalidRequestError` on the next flush. Pattern that works: pre-`SELECT` for the existing inverse, only stage the row when absent. See `TicketService.link` for the corrected flow.

4. **Sequence DDL inside `tests/services/conftest.py`'s rollback'd transaction is fine** — Postgres treats `CREATE SEQUENCE` as transactional DDL on PG ≥ 9.1, so test isolation holds. We rely on this in `tests/services/test_projects_service.py::test_create_project_creates_sequence` (calls `nextval` against a freshly created sequence in the same TX as the project).

5. **`DEF` project may legitimately have zero tickets** after WP2 backfill if the test DB was reset between fixtures runs. Tests asserting "delete refused because DEF has tickets" must create their own seeded project rather than relying on DEF (revised the `test_delete_blocked_by_tickets` test accordingly).

6. **The 46 net-new WP2 failures were all `TKT-` vs `DEF-` prefix expectations** (2 test files: `tests/services/test_ticket_create.py` line 60, `tests/routes/test_tickets_routes.py` line 75). The MCP-tool tests and the agents-activity / ws-tickets routes all reach through `TicketService.create()`, which now auto-resolves to `DEF` when no `project_id`/`project_key` is supplied — no further test changes were necessary. Confirmed by full-suite delta: **350 -> 304 failed**, **437 -> 529 passed** (= 46 fewer fails + 46 new WP3 tests, no regressions).

### Decisions beyond the spec

| Decision | Reason |
|----------|--------|
| `_DEFAULT_PROJECT_KEY = "DEF"` constant inside `TicketService` | Cross-WP Rule (Default project from WP2 backfill). Kept private to the service so route layer doesn't need to know. |
| `SprintState.closed` used in the service rather than spec's `completed` | The WP2 enum is `planned/active/closed` — spec §2.3 used `completed` informally but the migration shipped `closed`. Service uses the enum value present in `app/enums.py`. WP4 must reflect this in any state label. |
| Permissive v2 status workflow (any active state → any other) | Spec §4 documents "lenient global workflow" with a half-table that omits some edges. WP3 went with "any active → any active (incl. cancelled); done reopens to in_progress; cancelled reopens to todo/in_progress". |
| `_resolve_handles_to_uuids` resolves `@handle` against `users.email` local-part only | Spec §6 says "best-effort"; we'd need a `users.username` column or an agent-name table for richer resolution. Doc'd here so WP4/v2.1 can revisit. |
| Inverse `relates_to` is **not** auto-duplicated | The link type is self-symmetric; one row suffices and the API already renders both directions (incoming + outgoing). |
| Mentions parsing regex: `@[A-Za-z0-9_-]+` | Matches the WP1 expectation; explicit `mentions: list[UUID]` parameter on `add_comment()` wins over regex parsing when both are supplied. |

### Route/schema decisions not in the spec

- New `app/routes/projects.py` exposes both `/v1/projects` (membership + nested components-list/create) AND a sibling `/v1/components` router for component PATCH/DELETE by id. This matches the existing flat-router idiom used by `app/routes/attachments.py`.
- `TicketCreate` Pydantic body accepts BOTH `project_id` and `project_key`; the service resolves with precedence `project_id > project_key > DEF`. No 400 when both are supplied — `project_id` wins. (This kept the existing test bodies that pass only `{"title": ...}` working without changes.)
- `TicketAttachmentBody` is a metadata-only POST (filename / content_type / byte_size / storage_path). A multipart-upload endpoint that writes to disk + calls this service would mirror `app/routes/attachments.py`; not in WP3 scope.
- `X-Agent-Step-Id` is read by middleware unconditionally — including from user-actor requests. The CHECK constraint `actor_type='agent' OR agent_step_id IS NULL` on each audit-producing table is the source of truth; the service stamps NULL when actor is a user even if the header is present. (Better to enforce in code than to 4xx a request that "looked agenty" — the column is informational.)

### Recommendations for WP4 (frontend)

1. **Create-Ticket form must thread `project_key` (or `project_id`) into the POST body.** The route accepts both. If the URL is `/projects/:projectKey/tickets/new` you can simply forward the key. The default project is `DEF` but **don't rely on the default in the UI** — always pass it explicitly so the user-visible display id matches the project context the form was opened from.

2. **Per-type field-visibility rules from spec §5** map directly to the v2 `TicketCreate` schema. Required-when-type rules to mirror in TS:

   ```ts
   const FIELDS_BY_TYPE = {
     workpackage: { hidden: ['parent_id','story_points'], required: ['title'] },
     epic:        { hidden: ['story_points'],            required: ['title','description'] },
     story:       { hidden: [],                          required: ['title','description'] },
     task:        { hidden: [],                          required: ['title'] },
     bug:         { hidden: [],                          required: ['title','description'] },
     subtask:     { hidden: [],                          required: ['title','parent_id'] },
   };
   ```

   `parent_id` is *required* for subtask. The backend's `HierarchyError` returns 400 with `details.fields[].name = "parent_id"`; surface this in the form rather than a toast.

3. **`X-Agent-Step-Id` from the React side.** Human-driven UI flows should NOT send this header — agent attribution belongs to agent-driven runs (MCP tools, scheduled jobs). If you build an "agent activity replay" surface that re-issues writes on the agent's behalf, mint a step-id per replay, set it as a header on every request, and clear it on idle. Storing it in `axios` interceptors per-request scope is the safest pattern.

4. **API shapes for the Kanban v2 board:**
   - `GET /api/v1/tickets?project_id=<uuid>` lists with the new filters; add `sprint_id=` for sprint backlog view and `epic_id=` for epic-rollup.
   - `GET /api/v1/projects/<id>/components` for the component dropdown.
   - `GET /api/v1/sprints?project_id=<uuid>&state=active` for the active-sprint pill.
   - Watchers: `POST /api/v1/tickets/<id>/watchers` with `{watcher_id, watcher_type}`; the "Watch this ticket" button for the calling user sends `{watcher_id: currentUser.id, watcher_type: "user"}`.

5. **Display-id is now `<KEY>-<n>`, not `TKT-<n>`.** Any TS code that regex'd `TKT-\d+` from a comment body or URL will break. The same `id_or_key` resolver lives on `GET /api/v1/tickets/<id_or_key>` — accepts both UUID and `<KEY>-<n>`. Reuse a single util.

6. **Tombstoned link types.** `TicketLinkType.parent_of` / `child_of` still appear in the enum (for historical reads) but the API will return 400 on writes. The frontend should not include them in the "Add link" dropdown.

7. **Sprint states are `planned | active | closed`** (NOT `completed`). UI labels can say "Completed" but the wire value is `closed`.

### Sweep of WP2 net-new failures — confirmed fixes

| Test file | Pre-WP3 | Post-WP3 |
|-----------|---------|----------|
| `tests/services/test_ticket_create.py` (17 tests) | display_id assertion | passing — display_id now `DEF-N` |
| `tests/routes/test_tickets_routes.py` (9 tests) | display_id + creation flow | passing — POST defaults to DEF |
| `tests/mcp_server/test_mcp_tools.py` (10 tests) | `KeyError: 'id'` from create | passing — MCP `create_ticket` returns id+key |
| `tests/routes/test_agents_activity.py` (3 tests) | downstream of create failure | passing |
| `tests/routes/test_ws_tickets.py` (4 tests) | downstream of create failure | passing |
| `tests/services/test_ticket_transition.py` (13 tests) | OK pre-WP3, still OK | passing |

---

## WP4 — Lessons

### Gotchas hit

1. **Widening `TicketStatus` to include `backlog` (Cross-WP Rule alignment with WP3) created a *new* TS error in `frontend/src/pages/Kanban/KanbanBoard.tsx`** at the `Record<TicketStatus, TicketDTO[]>` literal — the exhaustive map was missing the `backlog` key. The WP4 brief said "do NOT touch Kanban" but the build-check requirement said "no new TS errors". Resolution: added a one-line `backlog: []` entry with a `// WP5 will surface a dedicated backlog view` comment. **Zero behavioural change** to Kanban v1 (backlog tickets simply don't appear in any rendered column). WP5 should fold this into a proper backlog surface (sidebar list or new column).

2. **No frontend test framework existed.** `frontend/package.json` had only `dev`/`build`/`preview` scripts and zero test deps. The brief mandated tests and a `npm test` run. Added `vitest`, `@testing-library/react`, `@testing-library/user-event`, `@testing-library/jest-dom`, and `jsdom` as `devDependencies`, plus `test` and `typecheck` scripts. Justified here because "no new top-level deps without justifying in Lessons" — these are devDeps for the mandated test deliverable. **WP5 should reuse the same infra** (`src/test/setup.ts`, the vitest section of `vite.config.ts`) rather than reinventing it. The vite test block uses `environment: "jsdom"`, `globals: true`, `setupFiles: ["./src/test/setup.ts"]`, `css: false` (skipping `css: false` was important — TipTap CSS imports broke jsdom).

3. **`RichEditor` is incompatible with jsdom.** TipTap/ProseMirror requires real DOM ranges and selection APIs. Tests for any page that uses `RichEditor` MUST module-mock it. Pattern that works (see `src/pages/CreateTicket/__tests__/CreateTicket.test.tsx`):
   ```ts
   vi.mock("../../../components/RichEditor", () => ({
     default: ({ value, onChange, placeholder }) =>
       React.createElement("textarea", { ... }),
   }));
   ```
   The mock path is **the relative specifier of the import in the page being tested**, not a project-root path. Centralising the mock in `setup.ts` only works if every consumer imports via the same alias — they don't, so it's per-test.

4. **`screen.getByText("Create Ticket")` matched both the `<h1>` and the submit `<button>`.** Use `getByRole("heading", { name: "Create Ticket" })` and `getByRole("button", { name: /Create Ticket/ })` to disambiguate. Cheap once you know.

5. **Project-list endpoint default ordering.** The Create form defaults to `DEF` if present, else `projects[0]`. If the project list comes back empty (no auth, network error), we still allow the user to type — the `select` falls back to a single `<option value={projectKey}>{projectKey}</option>` so the form is usable. Worth knowing for WP5 — the Kanban v2 project picker should likely have a "no projects" empty state rather than silently rendering a broken dropdown.

6. **`searchTickets` returns *all* types globally.** The parent picker debounce-searches and then filters client-side by `project_id` + `parentAllowedTypes`. If the search endpoint grows a `project_id`/`type[]` filter in v2.1, push the filter server-side — current approach can starve a 10-result page if most matches are outside the current project.

7. **400 error envelopes from the backend.** WP3 surfaces field-level errors at `envelope.details.fields[]` with `{name, message}`. The Create form maps `parent_id` → form field key `parent`. WP5 should reuse the same shape for inline-error rendering on any form that hits a v2 endpoint.

8. **Assignee lookup is currently UUID-only.** Spec §6 (and WP3 lesson 4) flagged that handle→UUID resolution is best-effort and `users.username` doesn't exist. The form accepts a UUID (validated) and a `user|agent` type toggle. WP5 needs a real user/agent autocomplete — see recommendation below.

### Reusable hooks/utilities created (use them, don't duplicate)

| Module | Exports | Purpose |
|--------|---------|---------|
| `src/api/projects.ts` | `listProjects`, `getProject`, `createProject`, `listMembers`, `listComponents`, types `ProjectDTO`/`ProjectMemberDTO`/`ComponentDTO` | Thin REST wrappers. |
| `src/api/sprints.ts` | `listSprints(projectId, state?)`, `getSprint`, `SprintDTO`, `SprintState` | `SprintState = "planned" \| "active" \| "closed"` per WP3 lesson 2. |
| `src/hooks/useProjectResources.ts` | `useProjects`, `useSprintsByProject`, `useComponentsByProject`, `useMembersByProject` | Each returns `{data, loading, error, refresh}`. All async, cancel-safe, debounce-free (the v2 endpoints are cheap). |
| `src/utils/displayId.ts` | `parseDisplayId(s) -> {key, n} \| null`, `isDisplayId`, `formatDisplayId` | Use this everywhere instead of inline regex. |
| `src/pages/CreateTicket/fieldsByType.ts` | `FIELDS_BY_TYPE`, `TicketTypeV2`, `ALL_TICKET_TYPES`, `TICKET_TYPE_LABEL`, `TICKET_TYPE_BADGE` | Single source of truth for per-type visibility / required-ness / allowed parent types. **WP5 should reuse `TICKET_TYPE_BADGE` for kanban-card type pills.** |
| `src/api/tickets.ts` extensions | `WRITABLE_LINK_TYPES`, `assertWritableLinkType()` | Refuses tombstoned `parent_of`/`child_of` writes client-side. Use for any Add-Link UI in WP5. |

### Top recommendations for WP5 (Kanban v2)

1. **Plug the project selector via `useProjects()` + URL state.** Treat `?project=DEF` (or `:projectKey` in the route) as the source of truth and lift the current selection into `useTicketStream` so the WS subscription scopes to the current project once the backend exposes a per-project topic. Don't store the project in `localStorage` only — the URL must round-trip.

2. **Reuse `useSprintsByProject(projectId, ["active"])` for the active-sprint pill** and `useSprintsByProject(projectId, ["planned", "active"])` for the sprint filter. The hook handles cancellation; just key it on a stable `states.join(",")` (already done internally).

3. **Swimlanes — don't fight the existing `KanbanColumn` shape.** The current board groups by `status`. For swimlanes-by-epic / -by-assignee, render a row of column-groups per swimlane key rather than mutating the column component. The `epic_id` denorm column on tickets (WP2 backfill) means swimlane-by-epic is one `groupBy(ticket.epic_id ?? "no-epic")` away — no extra queries.

4. **`backlog` column.** Don't add it to the kanban v1 column array unconditionally — the lenient v2 workflow lets `backlog → in_progress` / `backlog → cancelled` so the column should be drag-target-aware. Better surface: a "Backlog" tab next to "Board"/"Hierarchy" that lists tickets `WHERE status='backlog' AND sprint_id IS NULL`.

5. **Display-ID URL routing.** The Create page navigates to `/board?ticket=DEF-7` on success because there is no v2 ticket-detail route yet. When you wire `/projects/:projectKey/tickets/:displayId` (spec §9), update the navigate call in `CreateTicket.tsx` (search for `navigate(\`/board?ticket=`). Also: anywhere you take a string from URL/state and need to know "is this a display id or a UUID?", use `isDisplayId()` from `utils/displayId.ts`.

6. **Don't duplicate `TICKET_TYPE_BADGE`.** Card type pills on the board should import `TICKET_TYPE_BADGE` and `TICKET_TYPE_LABEL` from `pages/CreateTicket/fieldsByType.ts`. If that import direction feels wrong, lift the constant to `src/utils/ticketTypes.ts` (cheap one-file move). Either way, **one source of truth**.

7. **Tombstoned link types in the UI.** When you build "Add link" on a ticket detail drawer, source the options from `WRITABLE_LINK_TYPES` (exported from `api/tickets.ts`), NOT from a hardcoded array. `assertWritableLinkType()` is also defence-in-depth at the `linkTickets()` call site.

8. **Assignee picker is the next frontier.** The Create form currently accepts a UUID with a `user|agent` type toggle. WP5 (or v2.1) should:
   - Add `GET /api/v1/users/search?q=` and an agent equivalent (or a single `/people/search?q=` that returns both with a `type` flag).
   - Build `AssigneeAutocomplete` as a shared component; the Create form will swap its UUID input for the new component verbatim.
   - Same shape will be needed for **@mentions** in comments — `mentions` is already in `CreateTicketBody.addComment(mentions: string[])`.

9. **Agent activity badges.** `agent_step_id` lives on every audit row already (WP3). On the board, a dot/badge on cards whose `last_actor_type === "agent"` opens the existing `AgentActivityFeed` filtered to that step — don't build a separate tracer surface.

10. **Project create flow.** `createProject({key, name, ...})` is exposed in `api/projects.ts`. The route is mounted at `POST /api/v1/projects`. There is no UI for it yet — putting a small "+ New Project" affordance in the WP5 project switcher would close the gap without a separate admin page.

---

## WP5 — Lessons

### UX decisions made (beyond the brief)

1. **Backlog as leftmost column, always visible.** `status='backlog'` is now the leftmost column of the v2 board (WP4's TODO marker is resolved). The board no longer needs a separate "Backlog tab" — the column-vs-tab debate was sidestepped by adding the column. If product wants a sprint-planner-style backlog later, a dedicated `/projects/:projectKey/backlog` route would be the right surface, not a tab here.

2. **Blocked + Cancelled live behind a toggle, not as separate left/right columns.** Added a "Show Blocked / Cancelled" checkbox in the filters bar; when on, they render as two extra columns to the right of Done. Default off keeps the 5-column board (Backlog / To Do / In Progress / In Review / Done) within ~1280px viewports without horizontal scroll. Trade-off: drag-into-Blocked-from-anywhere requires the user to toggle the columns on first, which is fine — Blocked is a rare transition.

3. **Swimlanes by `epic` / `assignee` / `sprint` / `none`.** Implemented as a row-of-board-rows: each swimlane keeps the full status column set, grouped by the swimlane key. The droppable id is `col:<status>:<lane>` (vs. `col:<status>` when lanes are off) so drops are visually scoped to the lane but the transition is identical — we only read `<status>` server-side. Empty lanes are not rendered; orphan tickets land under `__none__` (label "No epic" / "Unassigned" / "No sprint").

4. **Project selector + URL sync.** `/board?project=DEF` is the source of truth; `localStorage.kanban.project` is a fallback default only. Switching projects clears active filters (per the brief) and triggers a refetch with `project_id=<uuid>`. The selector uses the project's `key` (`DEF`) as its option value; we resolve to the `id` (UUID) at the API call boundary because `listTickets` expects a UUID.

5. **Agent activity badge source.** The brief noted backend has no `last_actor_type` aggregate field. We compromised: `TicketCard` reads `ticket.last_actor_type` if present, **falling back to `ticket.reporter_type`** ("create-side actor"). This catches agent-created tickets at minimum. The badge is a 🤖 emoji in the top-right of the card. v2.1 backend should add a `tickets.last_actor_type` aggregate (or `last_actor_step_id`) populated from the most recent audit row — flagged below.

6. **Hierarchy tree picker.** When no `rootKey` is typed, the tree view now lists the project's epics + workpackages as buttons so the user can drill in without knowing a display id. Defensive client-side `project_id` filter applied to subtree rows as belt-and-braces against cross-project drift (server already enforces same-project parenting).

7. **View toggle persistence.** Board ↔ Hierarchy persists in `localStorage.kanban.view` (per brief option (a)). URL does not encode the view — it's a personal preference, not a shareable link concern.

8. **Drawer agent-activity surface.** `TicketDetailDrawer` comment list now stamps each comment with an actor badge (`🤖 agent` / `👤 user`) and a small monospaced chip showing `agent_step_id` when present. The drawer still doesn't fetch a separate `/transitions` endpoint (backend doesn't expose one) — flagged below.

### Backend gaps that would make v2.1 easier

1. **`tickets.last_actor_type` aggregate column.** Currently we fall back to `reporter_type`, which misses agent activity that happened *after* create (transitions/comments). A trigger-maintained `last_actor_type` + `last_actor_id` + `last_actor_step_id` triplet on `tickets` would let the card badge be precise without an N+1 fetch.

2. **`GET /api/v1/tickets?sprint_id=__none__` (or `&has_sprint=false`).** The list endpoint accepts `sprint_id=<uuid>` but has no first-class "no sprint" filter. WP5 compensates by client-side-filtering on the loaded page, which is fine at our `limit=500` scale but breaks at pagination. Same story for `epic_id=__none__` and `assignee_id=__unassigned__`.

3. **`GET /api/v1/tickets/{id}/transitions`.** No exposed endpoint to fetch the audit history per ticket. Drawer's "History/Activity tab" is therefore limited to comments + the ticket's current state. The audit data is in `ticket_transitions` (WP2) — just needs a thin route.

4. **`GET /api/v1/users/search?q=` + agent search.** Assignee dropdown currently lists `member_type:short_uuid (role)` for each `project_members` row, which is unreadable. The brief acknowledged this (WP4 lesson 8). Until `/people/search` exists, the dropdown is functional but ugly.

5. **WebSocket per-project topic.** `useTicketStream` already passes `projectId` and sends a `{op:"subscribe", project_id}` frame, but the server-side subscription/filter has not been verified. We defensively drop foreign-project ticket payloads on the client. A confirmed per-project topic would let the server skip the broadcast in the first place.

### Wired but needs polish

1. **Members lookup is project-membership-table only.** `useMembersByProject` returns `project_members` rows. Tickets can be assigned to users outside the membership table (e.g., guest reviewers), and those won't appear in the dropdown by name. Functional via the "type a UUID into a search box" workaround on the Create form; the Kanban filter currently has no escape hatch — flagged.

2. **Sprint chip uses the planned+active sprint lookup.** Tickets in a closed sprint will not show a sprint chip until the user toggles to include closed sprints. Reasonable v2 default (closed sprints are noise) but could be surprising. Could add `useSprintsByProject(projectId, ["planned","active","closed"])` for the lookup-only purpose; we kept the current scope to avoid an extra query per page load.

3. **Type chips are filter-only, not row separators.** A "Group by type" swimlane mode would be cheap to add (5 lines in `groupForSwimlane`) but isn't in the brief; skipped.

4. **WIP-limit indicators.** Spec §9 calls for a soft WIP-limit display per column ("project setting `wip_limits jsonb`"). The column shows a count but does not surface the WIP cap. Backend has no `projects.wip_limits` column yet, so it's strictly a v2.1 follow-up.

5. **Hierarchy tree's `getSubtree` does not honour the project filter server-side.** Wired purely as a client-side defensive filter; if a subtree response ever leaks a different project (it shouldn't given §3), we drop those rows. Cheap insurance.

### Reusable surfaces added by WP5 (for downstream / v2.1)

| Module | Purpose |
|--------|---------|
| `src/hooks/useTickets.ts` | `useTickets(filters)` — stable-keyed list fetch with `{data, loading, error, refresh}`. Drop-in for any future ticket-list surface. |
| `src/pages/Kanban/FiltersBar.tsx` | Reusable filters bar; `KanbanFilters` type + `EMPTY_FILTERS` const exported. Lift to `src/components/` if a sibling page (backlog planner, sprint board) wants the same surface. |
| `KanbanColumn` `dropIdSuffix` prop | Lets multi-board / multi-lane layouts share a single column component without colliding drop ids. |
| `TicketCard` `epicLookup` + `activeSprintLookup` + `onEpicClick` props | Composable chip surface; the chip styling and badge constants come from `pages/CreateTicket/fieldsByType.ts` (WP4) — single source of truth. |

