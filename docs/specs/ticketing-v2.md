# Ticketing v2 — Implementation Spec

> Status: WP1 design output. Implementation-grade. Downstream WPs (schema, services, API, frontend) consume this without re-interpretation.
> Companion: `docs/adr/0001-ticketing-v2.md`.

---

## 1. Goals & Non-goals

### Goals
- Replace the flat `tickets` table with a **JIRA-equivalent project management surface** for the agent-driven Kanban: Projects own Workpackages / Epics / Stories / Tasks / Subtasks.
- First-class **agent attribution** on every write: every author/actor row records `actor_type`, `actor_id`, and (when an agent) the `agent_step_id` that produced the change, so the agent tracer is one click away from any audit row.
- Single **standard workflow** (Backlog → To Do → In Progress → In Review → Done, plus Blocked / Cancelled) shared by all projects in v2.
- Hierarchy queries (sprint backlog, epic burndown, agent activity by project) are O(depth) not O(table-scan): hierarchy fields stay denormalised (`project_id`, `parent_id`) and indexed.
- Sprints, Components, ProjectMembers, Watchers, @mentions in comments, full ticket-link exposure, ticket attachments — all live in v2.

### Non-goals
- Worklogs / time tracking (deferred to v2.1).
- Per-project custom workflows / states (deferred to v2.1).
- Fix-version / Release as a separate table (kept as `fix_versions text[]` on ticket; promoted in v2.1).
- Fine-grained per-issue permissions. v2 has role labels (`lead` / `member` / `viewer`) but enforcement is coarse: any project member can transition any ticket.
- Migration of pre-v2 ticket rows (see §10 — fresh start with a backfilled "Default" project).

---

## 2. Entity Model

> Conventions: PK is `id UUID` (server default `gen_random_uuid()`) unless stated. Every row has `created_at TIMESTAMPTZ NOT NULL DEFAULT now()` and (where mutable) `updated_at TIMESTAMPTZ` updated by trigger or by SQLAlchemy `onupdate=func.now()`. All FKs name explicitly (`fk_<table>_<col>`). `text` ≡ Postgres `TEXT`. All check / unique / FK constraints named.

### 2.1 `projects` (NEW table)

| Field            | Type                          | Null | Default              | Index           | Purpose |
|------------------|-------------------------------|------|----------------------|-----------------|---------|
| id               | UUID                          | NO   | gen_random_uuid()    | PK              | |
| key              | TEXT                          | NO   | —                    | UNIQUE          | Display-ID prefix, e.g. `AION`. Enforced `^[A-Z][A-Z0-9]{1,9}$`. |
| name             | TEXT                          | NO   | —                    |                 | Human label. |
| description      | TEXT                          | YES  | NULL                 |                 | |
| lead_id          | UUID FK users.id              | YES  | NULL                 | btree           | Optional project lead (informational). |
| default_assignee_id   | UUID                     | YES  | NULL                 |                 | New tickets auto-assign here when assignee omitted. |
| default_assignee_type | TEXT                     | YES  | NULL                 |                 | `user`/`agent`. Co-null with `default_assignee_id`. |
| icon             | TEXT                          | YES  | NULL                 |                 | Emoji / URL. Cosmetic. |
| archived_at      | TIMESTAMPTZ                   | YES  | NULL                 | partial-where   | Soft-archived projects hide from default list. |
| created_by       | UUID                          | NO   | —                    |                 | User/agent that created the project. |
| created_by_type  | TEXT                          | NO   | `'user'`             |                 | CHECK in (`user`,`agent`). |
| created_at       | TIMESTAMPTZ                   | NO   | now()                |                 | |
| updated_at       | TIMESTAMPTZ                   | YES  | onupdate=now()       |                 | |

Constraints:
- `uq_projects_key UNIQUE (key)`
- `ck_projects_key_format CHECK (key ~ '^[A-Z][A-Z0-9]{1,9}$')`
- `ck_projects_default_assignee_pair CHECK ((default_assignee_id IS NULL AND default_assignee_type IS NULL) OR (default_assignee_id IS NOT NULL AND default_assignee_type IS NOT NULL))`
- `ck_projects_created_by_type CHECK (created_by_type IN ('user','agent'))`

Sequence: one `seq_<KEY>` sequence per project (see §11 lessons for the trade-off). Used to generate `tickets.display_id = '<KEY>-<n>'`.

### 2.2 `tickets` (EXTENDED — the existing table)

Existing columns kept: `id`, `seq_number`, `display_id` (regenerated, see below), `title`, `description`, `type`, `status`, `priority`, `parent_id`, `reporter_id/_type`, `assignee_id/_type`, `story_points`, `due_date`, `labels[]`, `custom_fields jsonb`, `version`, `created_at`, `updated_at`, `search_tsv`.

**New / changed columns:**

| Field            | Type                  | Null | Default      | Index                            | Purpose |
|------------------|-----------------------|------|--------------|----------------------------------|---------|
| project_id       | UUID FK projects.id ON DELETE RESTRICT | NO | — | btree; composite `(project_id, status)` partial WHERE status NOT IN ('done','cancelled'); composite `(project_id, type)` | Hard-required FK. Every work item belongs to exactly one project. |
| sprint_id        | UUID FK sprints.id ON DELETE SET NULL | YES | NULL | btree partial WHERE sprint_id IS NOT NULL | Optional sprint assignment. |
| epic_id          | UUID FK tickets.id ON DELETE SET NULL  | YES | NULL | btree partial WHERE epic_id IS NOT NULL | Denormalised pointer to ancestor epic, for fast epic-rollup queries. Maintained by service-layer on parent-change. |
| component_id     | UUID FK components.id ON DELETE SET NULL | YES | NULL | btree | Per-project bucket (e.g. "Frontend", "API"). |
| fix_versions     | TEXT[]                | NO   | `'{}'`       | gin                              | v2.1 will lift to a real table; keep array for now. |
| resolution       | TEXT                  | YES  | NULL         |                                  | Free text (`done`, `wont_do`, `duplicate`, `cannot_reproduce`). Set when status → done/cancelled. |
| due_date         | TIMESTAMPTZ           | YES  | NULL         | btree (existing)                 | (Existing — promote from DATE to TIMESTAMPTZ if not already.) |
| resolved_at      | TIMESTAMPTZ           | YES  | NULL         |                                  | Set by service when status enters terminal. |

**`type` enum widened** to `workpackage|epic|story|task|subtask|bug`. (We keep `bug` because it already exists in the enum and is useful; treat `bug` as a peer of `task` in the parenting matrix.)

**`status` enum widened** to add `backlog`. New ordering: `backlog|todo|in_progress|in_review|blocked|done|cancelled`. Default for new tickets: `backlog` for `epic`/`workpackage`, `todo` for everything else.

**`display_id` regenerated** as a *non*-computed column, populated by service-layer trigger: `display_id = '<project.key>-' || nextval('seq_<project.key>')`. The current `Computed('TKT-' || seq_number)` expression is dropped; `seq_number` per ticket is now project-scoped, not global.

Constraints (additions to the existing set):
- `fk_tickets_project_id ON DELETE RESTRICT` (you can't delete a project that still has tickets — archive instead).
- `ck_tickets_parent_same_project CHECK (parent_id IS NULL OR <enforced by trigger or service>)` — DB cannot self-join cheaply in a CHECK; enforce in service-layer + trigger that raises on mismatch.
- `ck_tickets_subtask_has_parent CHECK (type <> 'subtask' OR parent_id IS NOT NULL)`.
- `uq_tickets_project_seq UNIQUE (project_id, seq_number)`.

### 2.3 `sprints` (NEW)

| Field        | Type        | Null | Default | Purpose |
|--------------|-------------|------|---------|---------|
| id           | UUID        | NO   | gen_random_uuid() | |
| project_id   | UUID FK projects.id ON DELETE CASCADE | NO | — | Sprint is project-scoped. |
| name         | TEXT        | NO   | — | e.g. "Sprint 12 — May 16". |
| goal         | TEXT        | YES  | NULL | |
| state        | sprint_state ENUM (`planned`,`active`,`completed`) | NO | `'planned'` | At most one `active` per project (partial-unique). |
| start_date   | TIMESTAMPTZ | YES  | NULL | |
| end_date     | TIMESTAMPTZ | YES  | NULL | |
| completed_at | TIMESTAMPTZ | YES  | NULL | |
| created_by / _type | UUID + TEXT | NO/NO | — / `'user'` | Actor attribution. |
| created_at   | TIMESTAMPTZ | NO   | now() | |
| updated_at   | TIMESTAMPTZ | YES  | — | |

Constraints: `uq_sprints_active_per_project UNIQUE (project_id) WHERE state = 'active'`, `ck_sprints_date_order CHECK (start_date IS NULL OR end_date IS NULL OR start_date <= end_date)`.

### 2.4 `components` (NEW)

| Field        | Type        | Null | Default | Purpose |
|--------------|-------------|------|---------|---------|
| id           | UUID        | NO   | gen_random_uuid() | |
| project_id   | UUID FK projects.id ON DELETE CASCADE | NO | — | |
| name         | TEXT        | NO   | — | |
| description  | TEXT        | YES  | NULL | |
| lead_id / _type | UUID + TEXT | YES | NULL | Optional component owner. |
| created_at   | TIMESTAMPTZ | NO   | now() | |

`uq_components_project_name UNIQUE (project_id, lower(name))`.

### 2.5 `project_members` (NEW)

| Field        | Type        | Null | Default | Purpose |
|--------------|-------------|------|---------|---------|
| id           | UUID        | NO   | gen_random_uuid() | |
| project_id   | UUID FK projects.id ON DELETE CASCADE | NO | — | |
| member_id    | UUID        | NO   | — | User or agent. |
| member_type  | TEXT        | NO   | `'user'` | CHECK in (`user`,`agent`). |
| role         | project_role ENUM (`lead`,`member`,`viewer`) | NO | `'member'` | |
| added_by / _type | UUID + TEXT | NO/NO | — / `'user'` | |
| added_at     | TIMESTAMPTZ | NO   | now() | |

`uq_project_members UNIQUE (project_id, member_id, member_type)`.

### 2.6 `watchers` (NEW — generic over tickets; tickets-only in v2)

| Field         | Type        | Null | Default | Purpose |
|---------------|-------------|------|---------|---------|
| id            | UUID        | NO   | gen_random_uuid() | |
| ticket_id     | UUID FK tickets.id ON DELETE CASCADE | NO | — | |
| watcher_id    | UUID        | NO   | — | |
| watcher_type  | TEXT        | NO   | `'user'` | CHECK in (`user`,`agent`). |
| added_at      | TIMESTAMPTZ | NO   | now() | |

`uq_watchers UNIQUE (ticket_id, watcher_id, watcher_type)`. Index: `(watcher_id, watcher_type)` for "all tickets I watch" reverse lookup.

> Note: an existing `app/models/watch.py` covers the bulletin/problem domain. v2 adds a parallel ticket-scoped table to avoid coupling the two domains' lifecycles. WP2 should confirm the naming (`ticket_watchers` is the safer name to avoid collision).

### 2.7 Work-item types (rows in `tickets`)

The five "issue types" (plus `bug`) are not separate tables — they are values of `tickets.type`. Per-type validation lives in the service layer and is enforced via the parenting matrix (§3).

---

## 3. Hierarchy Parenting Matrix

`workpackage` is the highest-level container *inside* a project (use for cross-team initiatives spanning multiple epics).

| Child type     | Allowed parent types                          | Required? | Notes |
|----------------|-----------------------------------------------|-----------|-------|
| workpackage    | (none)                                        | No        | Top of the in-project tree. |
| epic           | workpackage, (none)                           | No        | An epic without a workpackage is fine. |
| story          | epic, (none)                                  | No        | Story without epic = "orphan story" — allowed but flagged in UI. |
| task           | story, epic, (none)                           | No        | |
| bug            | story, epic, (none)                           | No        | Treated like a task in hierarchy. |
| subtask        | task, story, bug                              | **Yes**   | Subtask MUST have a parent. |

Cross-project parenting is **not** allowed in v2 (enforced: `parent.project_id = child.project_id`). For cross-project references, use `ticket_links` with `relates_to` / `blocks`.

`epic_id` (denorm) is computed by service on insert/parent-change: walk up the chain until you hit an `epic`; if none, leave NULL.

---

## 4. Status Workflow

### States
`backlog`, `todo`, `in_progress`, `in_review`, `blocked`, `done`, `cancelled`.

### Transitions (v2 — global, lenient)

| From → To   | backlog | todo | in_progress | in_review | blocked | done | cancelled |
|-------------|---------|------|-------------|-----------|---------|------|-----------|
| backlog     | —       | ✓    | ✓           |           | ✓       |      | ✓         |
| todo        | ✓       | —    | ✓           |           | ✓       |      | ✓         |
| in_progress | ✓       | ✓    | —           | ✓         | ✓       | ✓    | ✓         |
| in_review   |         | ✓    | ✓           | —         | ✓       | ✓    | ✓         |
| blocked     | ✓       | ✓    | ✓           | ✓         | —       |      | ✓         |
| done        |         |      | ✓ (reopen)  |           |         | —    |           |
| cancelled   |         | ✓    | ✓           |           |         |      | —         |

- `blocked` is reachable from any active state and returns to the prior active state.
- `done` and `cancelled` are terminal but **reopenable** to `in_progress` (with audit reason).
- Entering `done`/`cancelled` requires `resolution` to be set (service-layer check, not DB).
- Permission: any project member with role ≥ `member` (lead or member) may transition. `viewer` may not.

Every transition writes a `ticket_transitions` row (`actor_type`, `actor_id`, `agent_step_id`, `reason`, `correlation_id`).

---

## 5. Standard Fields per Type

Legend: **R** required, **O** optional, **H** hidden in UI / not applicable.

| Field          | workpackage | epic | story | task | bug | subtask |
|----------------|-------------|------|-------|------|-----|---------|
| title          | R | R | R | R | R | R |
| description    | O | R | R | O | R | O |
| project_id     | R | R | R | R | R | R |
| parent_id      | H | O (workpackage) | O (epic) | O | O | R |
| type           | R | R | R | R | R | R |
| status         | R | R | R | R | R | R |
| priority       | O | R | R | R | R | O |
| assignee       | O (lead) | O | O | O | O | O |
| reporter       | R | R | R | R | R | R |
| labels         | O | O | O | O | O | O |
| story_points   | H | H | O | O | O | O |
| due_date       | O | O | O | O | O | O |
| sprint_id      | H | O | O | O | O | O (inherits from parent task if NULL) |
| component_id   | O | O | O | O | O | O |
| fix_versions   | O | O | O | O | O | O |
| resolution     | (set on transition to done/cancelled) | same | same | same | same | same |
| custom_fields  | O | O | O | O | O | O |
| watchers       | O | O | O | O | O | O |

Justifications:
- `story_points` hidden on workpackage/epic — those roll up from children (computed view, §8).
- `description` required on epic / story / bug to force minimal scoping discipline. Allowed empty on workpackage because it often just labels an initiative.
- `parent_id` required on subtask, hidden on workpackage.

---

## 6. Agent Attribution Model

### Goal
Any audit row, comment, transition, link, or attachment created by an agent can be deep-linked back to the **exact agent run step** that produced it.

### Column additions

Every write-author table gets the same triplet (in addition to the existing `actor_type` / `actor_id` or `created_by` / `created_by_type` / `author_id` / `author_type`):

- `agent_step_id TEXT NULL` — opaque identifier emitted by the agent tracer (e.g. `run_<runid>_step_<n>`). NULL when `actor_type = 'user'`.
- `correlation_id TEXT NOT NULL DEFAULT ''` — already present on `ticket_transitions` and `ticket_comments`; extend to `ticket_links`, `attachments`, `tickets` (mutation audit only — on the audit row, not on the ticket itself).

Tables affected:
- `tickets` — add `created_agent_step_id TEXT NULL`. Mutations beyond create are captured in `audit_log` rather than on the row.
- `ticket_transitions` — add `agent_step_id TEXT NULL` (already has `actor_*` + `correlation_id`).
- `ticket_comments` — add `agent_step_id TEXT NULL` (already has `author_*` + `correlation_id`).
- `ticket_links` — add `agent_step_id TEXT NULL` (already has `created_by_*`).
- `ticket_attachments` (new — §2.x) — `uploaded_by`, `uploaded_by_type`, `agent_step_id`.
- `audit_log` (existing) — must record `actor_type`, `actor_id`, `agent_step_id`.

### CHECK constraint (every table with the triplet)
`CHECK (actor_type = 'agent' OR agent_step_id IS NULL)`
— users never carry a step id.

### Service-layer contract
- Request middleware extracts actor identity from the auth context (user token or agent API key).
- For agent requests, the request header `X-Agent-Step-Id` is read and threaded through the session as a context var. Every service `_record_*` helper picks it up automatically.
- The frontend agent-activity feed (Kanban v2 badges) renders each row with a "View step" link that opens the tracer at `agent_step_id`.

---

## 7. Ticket Links

### Confirmed link types (replaces existing enum)

| link_type        | Inverse           | Semantics |
|------------------|-------------------|-----------|
| `blocks`         | `is_blocked_by`   | Source blocks target. Both rows are inserted as a directed pair. |
| `is_blocked_by`  | `blocks`          | — |
| `duplicates`     | `is_duplicate_of` | Source is a duplicate of target. Inserting one inserts the inverse. |
| `is_duplicate_of`| `duplicates`      | — |
| `relates_to`     | `relates_to`      | Symmetric; one row suffices but UI shows both directions. |
| `clones`         | `is_cloned_by`    | NEW — captures "ticket B was created from ticket A". |
| `is_cloned_by`   | `clones`          | NEW |

Hierarchy links (`parent_of` / `child_of`) on `ticket_links` are **removed** — hierarchy lives on `tickets.parent_id`. (If we ever need cross-project hierarchy we'll re-add them, but v2 forbids cross-project parenting.)

Invariants:
- `source_id <> target_id` (existing).
- Inverse pairs maintained transactionally by service: inserting `(A blocks B)` also inserts `(B is_blocked_by A)`.
- Unique `(source_id, target_id, link_type)` (existing).

---

## 8. API Surface

> All endpoints under `/api/v1`. Auth required: user JWT or agent API key. Agent requests SHOULD include `X-Agent-Step-Id`.

### Projects
- `GET    /projects` — list, filterable by `archived`, `member_of=me`.
- `POST   /projects` — create. Body: `{ key, name, description?, lead_id?, default_assignee_*? }`.
- `GET    /projects/{id}` — detail (counts: open tickets, active sprint).
- `PATCH  /projects/{id}` — update name/description/lead/default_assignee.
- `POST   /projects/{id}/archive`
- `DELETE /projects/{id}` — **only if zero tickets**; otherwise 409.
- `GET    /projects/{id}/stats` — counts by status × type.

### Project members
- `GET    /projects/{id}/members`
- `POST   /projects/{id}/members` — `{ member_id, member_type, role }`.
- `PATCH  /projects/{id}/members/{member_id}` — change role.
- `DELETE /projects/{id}/members/{member_id}`

### Sprints
- `GET    /projects/{id}/sprints` — filter by `state`.
- `POST   /projects/{id}/sprints`
- `GET    /sprints/{id}` — detail incl. ticket list.
- `PATCH  /sprints/{id}`
- `POST   /sprints/{id}/start` — moves to `active`. Fails if another active sprint exists in project.
- `POST   /sprints/{id}/complete` — body: `{ move_incomplete_to: <sprint_id|"backlog"> }`.

### Components
- `GET    /projects/{id}/components`
- `POST   /projects/{id}/components`
- `PATCH  /components/{id}`
- `DELETE /components/{id}` — un-assigns from all tickets.

### Tickets (changes from current)
- `POST   /tickets` — now requires `project_id`. Body validated against §5 fields-per-type matrix. Service generates `display_id = <KEY>-<n>` from project sequence.
- `GET    /tickets` — adds filters: `project_id`, `sprint_id`, `epic_id`, `component_id`, `type[]`, `status[]`, `assignee_id`, `watcher=me`, `q` (FTS on `search_tsv`).
- `GET    /tickets/{id_or_display_id}` — resolves both UUID and `KEY-N`.
- `PATCH  /tickets/{id}` — partial update; bumps `version` (OCC).
- `POST   /tickets/{id}/transition` — body: `{ to_status, reason?, resolution? }`. Validates against §4 matrix.
- `POST   /tickets/{id}/clone` — creates target ticket in same or different project, auto-links with `clones`.

### Watchers
- `GET    /tickets/{id}/watchers`
- `POST   /tickets/{id}/watchers` — `{ watcher_id?, watcher_type? }` (defaults to caller).
- `DELETE /tickets/{id}/watchers/{watcher_id}`
- `POST   /tickets/{id}/watch` / `POST /tickets/{id}/unwatch` — convenience for "me".

### Attachments
- `POST   /tickets/{id}/attachments` — multipart; mirror existing problem-attachment service (`app/services/attachments.py`).
- `GET    /tickets/{id}/attachments`
- `DELETE /attachments/{id}`

### Comments (unchanged shape; add mentions)
- `POST /tickets/{id}/comments` — service parses `@user-handle` / `@agent-name` from body and stores `mentions UUID[]` on the comment row. No notification fanout in v2 (just storage + UI rendering).

### Links (unchanged endpoint shape; new link types per §7)
- `POST /tickets/{id}/links` / `DELETE /tickets/{id}/links/{link_id}` / `GET /tickets/{id}/links`.

### Agent activity
- `GET /agents/activity` (exists) — extend with `project_id` filter.

---

## 9. Frontend Surface

### Routes
- `/projects` — project list + create.
- `/projects/:projectId` — project home (overview, members, components, sprints).
- `/projects/:projectId/board` — Kanban v2 (replaces current `/kanban`).
- `/projects/:projectId/backlog` — backlog + sprint planner.
- `/projects/:projectId/tickets/new` — **Create Ticket** form (route required).
- `/tickets/:displayId` — detail (already exists at `/problems/:id`; route renames or aliases).
- `/agents/:agentId` — agent profile + activity (existing; cross-link from badges).

### Create Ticket form
A single page with a **Type selector** at the top (`workpackage|epic|story|task|bug|subtask`). Fields shown follow §5. On type change, fields show/hide without losing entered values. `project_id` is preselected from the URL but switchable.

### Kanban v2
- **Project selector** at the top (also lockable via URL param).
- **Swimlanes**: switchable by `epic` / `assignee` / `sprint` / `none`.
- **Hierarchy tree** sidebar (collapsible): workpackage → epic → story → task → subtask.
- **Agent activity badges** on each card: dot indicator when last write was by an agent; click opens tracer at `agent_step_id`.
- **Filter bar**: type, priority, label, sprint, component, watcher=me.
- WIP-limit indicator per column (project setting, soft warning only in v2).

### Ticket detail
- Existing detail page extended: links section, watchers section, attachments, sprint/component selectors, parent picker (typeahead constrained by parenting matrix §3), `agent_step_id` deep-link on every audit row.

---

## 10. Data Migration Strategy

**Decision: fresh start with a backfilled "Default" project.**

Rationale:
- The just-completed `a8_finalize_ticket_split` migration left `tickets` populated by the brief `work_items` window — there is no production user data on this table yet (it was created in `a7`, populated only by dev/test fixtures).
- Wiping the table is the cleanest path but loses dev fixtures and breaks any in-flight feature branches mid-test.
- Backfilling preserves the dev fixtures and gives WP2 a deterministic starting state.

Plan (WP2 migration `a9_ticketing_v2`):
1. Create `projects`, `sprints`, `components`, `project_members`, `ticket_watchers`, `ticket_attachments` tables and the new enums (`project_role`, `sprint_state`).
2. Widen `ticket_status` enum: add `backlog`. Widen `ticket_type`: confirm `workpackage` is added.
3. Insert a `('DEF', 'Default Project', ...)` row in `projects`. Create sequence `seq_DEF`.
4. Add `project_id` to `tickets` NULLABLE; backfill all rows to the Default project; set NOT NULL.
5. Add `sprint_id`, `epic_id`, `component_id`, `fix_versions`, `resolution`, `resolved_at`, `created_agent_step_id` columns.
6. Drop the existing `display_id` generated-column. Recompute `display_id` for backfilled rows as `'DEF-' || seq_number` and re-add as a *plain* (non-generated) column. Going forward, service-layer sets it on insert.
7. Update `ticket_link_type` enum: add `clones`, `is_cloned_by`; remove `parent_of`, `child_of` (assert no rows use them first).
8. Add `agent_step_id` to transitions / comments / links.
9. Add `mentions UUID[]` to `ticket_comments`.
10. Backfill `epic_id` denorm by walking `parent_id` chains.

Downgrade is best-effort and lossy (we will not unwind the data backfill).

---

## 11. Open Questions

1. **Display-ID sequence-per-project vs single global with KEY prefix**: WP1 recommends per-project Postgres sequence `seq_<KEY>` (matches JIRA UX where every project starts at 1). Alternative: keep one global `tickets_seq_number_seq` and render display as `<KEY>-<seq>`. Per-project sequence wins on UX, loses on operational complexity (DDL per project create). WP2 to choose. *Recommendation: per-project sequence, created at project-create-time via `op.execute("CREATE SEQUENCE seq_<key>")`.*
2. **Agent step id format**: spec assumes opaque TEXT. Confirm format with WP3 (services); if structured, consider a check pattern.
3. **Watchers vs. existing `app/models/watch.py`**: keep separate (`ticket_watchers`) or unify via `target_type`/`target_id` generic table? WP1 recommends separate (clean lifecycle, simpler queries).
4. **Default sprint when none active**: do new tickets auto-attach to active sprint? WP1 recommends **no** (must be explicit), matching JIRA.

---

## 12. Out of Scope / Deferred to v2.1

- Worklogs / time tracking.
- Per-project custom workflows / states.
- Fix-versions as a real `releases` table with FK.
- Fine-grained permissions (per-issue ACL, role-action matrix).
- Notification fanout for @mentions (storage exists; delivery deferred).
- WIP-limit hard-enforcement on Kanban transitions.
- Cross-project hierarchy (parent in another project).
- Saved filters / JQL-style query language.
