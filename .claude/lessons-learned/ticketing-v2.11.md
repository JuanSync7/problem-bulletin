# Ticketing System — v2.11 lessons learned

v2.11 picks up the carry-forward backlog from the bottom of
`ticketing-v2.10.md` (Buckets A–F, 30 items). Work order defaults to
Bucket A (production-correctness) → B (API surface) → C (test infra)
→ D (docs cleanup) → E–F (deferred features + cursor polish).

**Starting baselines (carried from v2.10 close):**
- Backend: 1190 passed / 0 failed / 5 skipped / 14 xfailed
- Frontend: 236 passed / 0 failed

**Process invariants** (do not re-litigate, carry-forward from v2.10):
- TDD-first per WP. Write the failing test before the production change.
- Sequential subagent dispatch; each subagent gets a self-contained
  prompt with validatable end goals (G1–GN) declared up front.
- Each WP produces `v2.11-wpNN-diagnosis.md` alongside this file.
- Append per-WP retrospective to this file as the cycle progresses.
- No bespoke deferral registry (no `_v1_deferred.py` revival). Use
  plain `@pytest.mark.skip` / `@pytest.mark.xfail` with a reason.
- Port-in-place rule (WP04b lesson): when rewriting a test file, only
  edit the deferred tests; leave passing tests untouched.

---

## WP-by-WP log

(populated as subagents complete)

### WP01 — agent_accounts NOT NULL alignment (Bucket A1)

**Status:** complete. 1192 passed / 0 failed / 5 skipped / 14 xfailed.

**Drift closed:** v2.10-WP02 tightened the DB column to NOT NULL (migration
`a17`) but left both the ORM (`Mapped[UUID | None]`, `nullable=True`) and
the service signature (`created_by: UUID | None = None`) loose. A forgetful
caller would pass the type checker and fail later with an opaque
`IntegrityError` from the flush.

**Fix shape:**
- `app/models/agent_account.py` — `created_by` → `Mapped[UUID]`, `nullable=False`.
- `app/services/agent_accounts.py` — `created_by: UUID` becomes required kw-only; added a `None` guard that raises `ValidationError([{"name": "created_by", "reason": "required"}])` before any DB work, matching the empty-name guard pattern.
- No alembic migration added (G5 — DB already enforces it).
- No pydantic schema mirroring needed (the admin route synthesises `created_by` from `actor.id`).

**Tests added (+2 net):**
- `tests/test_agent_accounts_created_by_orm_alignment.py` (new, 2 tests): G1 `__table__` introspection + G2 service guard exercising both the signature `TypeError` and the explicit `created_by=None` `ValidationError`.

**Tests updated (port-in-place):**
- `tests/test_agent_accounts_created_by.py::test_service_create_account_without_created_by_raises_integrity_error` → renamed to `..._raises_validation_error`; contract flipped from DB-layer `IntegrityError` to service-layer `ValidationError`, asserting on `ei.value.fields` (correct shape for `app.exceptions.ValidationError`).
- `tests/services/test_agent_account_service.py::test_create_account_rejects_empty_name` now seeds a user and passes `created_by` so the signature-required arg is satisfied before the empty-name guard fires.

**Lessons / v2.11 follow-ups:**
- "Drift" can live on either side of the ORM↔DB seam. v2.10-WP02 closed
  the DB side; only a model-introspection test (G1) made the ORM-side
  drift visible. Worth a future sweep: grep for `nullable=True` columns
  in `app/models/*` whose corresponding migration history asserts NOT
  NULL, and pin each with the same `__table__.columns[...].nullable`
  test pattern.
- `app.exceptions.ValidationError`'s `str()` is generic ("Validation
  failed on N field(s)"); assertions about *which* field failed must
  introspect `.fields`. Update any future tests accordingly.
- A keyword-only-required argument (no default) raises `TypeError` from
  Python's signature layer when omitted entirely. Adding the in-body
  `None` guard on top is belt-and-braces — it catches callers who
  thread a possibly-`None` variable through `**kwargs` or who pass
  `None` explicitly. Both surfaces are now covered by tests.

### WP02 — legacy_status raw-SQL sweep (Bucket A2)

**Status:** complete. 1194 passed / 0 failed / 5 skipped / 14 xfailed.

**Drift surface:** migration `a1_agent_kanban` renamed
`problems.status` → `problems.legacy_status`. ORM keeps the Python attribute
`Problem.status` pointing at the renamed column (asymmetric on purpose —
Bucket E2 owns the full rename). Raw-SQL fragments referencing `p.status` /
`problems.status` are invisible to type checkers and only fail at execute
time. v2.10-WP04b fixed one such hit in `app/services/search.py`; WP02
sweeps the rest and pins the category with a regression lint.

**Audit result:** **0 true positives** remaining. The production surface
was already clean post-WP04b. `app/services/search.py:106` and
`app/services/search_multi.py:364,391` all correctly read
`p.legacy_status`. `t.status` references in `search_multi.py` are the
tickets entity (out of scope). The only `(p|problems)\.status` hits are
three explanatory docstring lines in `tests/services/test_search.py`
documenting the WP04b fix history.

**Fix shape:** no production edits. The deliverable is the regression
lint (`tests/test_legacy_status_sweep.py`).

**Tests added (+2 net):**
- `tests/test_legacy_status_sweep.py::test_no_raw_sql_problems_status_in_app`
  — AST scan of every `.py` under `app/` for `(p|problems)\.status` string
  literals with a negative-lookahead allowing the correct `legacy_status`
  spelling. Currently green.
- `tests/test_legacy_status_sweep.py::test_audit_lint_detects_synthetic_drift`
  — self-test: scanner flags a synthetic `text("... p.status ...")` file,
  ignores the correct `p.legacy_status` spelling, and ignores cross-entity
  `t.status` (tickets). Guards against future refactors silently
  neutering the lint.

**G3 (live-DB integration) coverage was pre-existing:**
- `tests/services/test_search.py::test_search_filter_status` covers
  `app/services/search.py`.
- `tests/routes/test_search_v2.py::test_problem_status_filter_passes_through`
  + `tests/routes/test_search_v2_filters.py` cover `search_multi.py`.

**Regression-lint mechanism:** plain pytest test (not a
`pytest_collection_modifyitems` hook). Justification: v2.10-WP07
explicitly cleared the collection-modify hook from `conftest.py`;
reintroducing one would re-muddy that boundary, and a regular test
gives a cleaner failure with path/line/snippet in the assertion.

**Lessons / v2.11 follow-ups:**
- Sweep WPs sometimes find the production surface already clean. The
  value-add then becomes the regression lint, not a code fix. Document
  the empty-fix result as proof of negative — future readers shouldn't
  have to re-derive that the column rename is fully cleaned.
- Self-test the audit scanner (RED on synthetic drift, GREEN on
  correct spelling and on cross-entity matches). Cheap insurance
  against a future refactor neutering the lint.
- Negative-lookahead `\b(?:p|problems)\.(?!legacy_)status\b` is the
  cleanest "match bad spelling, skip good spelling" pattern; reusable
  for future post-rename sweeps.
- Bucket E2 follow-up unchanged: rename `legacy_status` back to
  `status` and align the ORM. When E2 lands, this lint can be inverted
  (flag `legacy_status` references) or retired.
- Symmetric concern logged but not actioned: if `tickets.status` ever
  gets renamed, a parallel `t.status` / `tickets.status` lint will be
  needed.

### WP03 — admin service input validation + audit-actor consistency (Bucket A3 + A4)

**Scope:** two co-located admin-service-layer fixes in
`app/services/admin.py`:

- A3 — `update_user_role` accepted any string for `new_role`; only the
  route's pydantic schema defended against garbage.
- A4 — `update_config` hard-coded the literal string `"admin"` as the
  audit `user_id`; sibling `update_user_role` / `update_user_status`
  passed the *target* user id instead of the caller's principal id.

**Choices:**
- Tighten the service. Validate `new_role` against `app.enums.UserRole`
  (single source of truth shared with the route's `Literal[...]`/schema).
- Pin audit-actor convention: `log_event(...)`'s `user_id` slot is the
  caller's principal id. Adopted via a kw-only `actor_id: UUID | None`
  parameter on `update_user_role`, `update_user_status`, `update_config`.
  Routes thread `admin.id`; legacy non-route callers get a safe fallback
  (target id for user services; `"system"` for config — not `"admin"`).

**Tests:** 4 new tests in `tests/services/test_admin.py`
(`TestUpdateUserRoleRoleValidation::{rejects_unknown_role, accepts_admin,
accepts_user}`, `TestUpdateConfigAuditActor::test_log_event_uses_actor_id_not_literal_admin`).
Failing-test gate confirmed before fix (G1 raised "DID NOT RAISE",
G3 raised "unexpected keyword argument 'actor_id'").

**Backend baseline:** 1198 passed / 0 failed / 5 skipped / 14 xfailed.
(+4 new over the WP02 close of 1194.)

**G7 audit-actor sweep:** 5 `log_event(...)` call sites total, all in
`app/services/admin.py`. 3 fixed, 2 (`flag.resolved`, `admin.de_anonymize`)
verified already correct. No callers outside this file.

**Lessons / v2.11 follow-ups:**
- `log_event(user_id=...)` is stringly-typed and easy to drift. Worth
  pinning the "caller principal id" convention on the helper docstring
  and considering a `UUID | str` type narrowing.
- Service-layer validators should mirror the route's `Literal[...]`
  allow-lists by sourcing from the same enum, not by retyping the
  values inline. Drift opportunity removed.
- Optional `actor_id` with fallback preserves legacy callers but masks
  drift. Track as a follow-up to make `actor_id` required once all
  call sites are confirmed.

---

## WP04 — service-vs-route auth split, set_watch refresh, tag sort strictness

**Decisions (3):**
- **A5** delete_attachment: lifted uploader-or-admin into the service
  (option a). Route is now a pass-through. Service raises
  `NotFoundError`/`ForbiddenError`, mapped to 404/403 via
  `app.main._EXCEPTION_STATUS_MAP`.
- **A6** set_watch: added `await db.refresh(watch)` after `db.flush()` so
  the returned object reflects the post-upsert `.level` without callers
  having to refresh manually. SQLAlchemy identity-map caching of the
  pre-upsert state is the root cause.
- **A7** get_tags: strict — invalid `sort=` raises `ValidationError` at
  the service. The route already returned 422, so HTTP behaviour is
  unchanged; this protects MCP/script callers from silent fallback.

**Lessons:**
- When a v1 test asserts a service-layer contract that production
  enforces at the route, the resolution is usually to lift the check
  into the service, NOT to rewrite the test to match the looser shape.
  WP04b chose the latter for tags (A7) and attachments (A5); WP04
  reverses both. Single guard at the boundary > guard duplicated /
  guard missing at one of two layers.
- SQLAlchemy `pg_insert(...).on_conflict_do_update(...).returning(Model)`
  returns the identity-mapped instance, not a freshly-materialised one.
  `await db.refresh(obj)` after `db.flush()` is the canonical fix and
  costs one PK lookup. Any service that exposes a mutated row to its
  caller after an upsert needs this; audit any other `pg_insert` uses
  in the services package.
- Mapping a domain exception in `_EXCEPTION_STATUS_MAP` only works for
  routes that don't already register a more-specific handler. The
  tickets module owns `ValidationError -> 400` via
  `EXCEPTION_HANDLERS`, which overrides the generic 422 mapping. Result:
  the v2.11 generic map cannot include `ValidationError`. Document
  divergence; consider unifying when the v2 ticket envelope is
  retired.
- The dead route-layer auth check we removed in WP04 (lines 117-132 of
  `app/routes/attachments.py`) was an example of "two layers each
  *think* they own the check, neither layer's test covers the other
  layer's path". The new pass-through route relies on the service's
  test coverage entirely — flag this as the canonical pattern for
  future route-layer audits.

---

## WP05 — Boot/config hardening (A8/A9/A10)

Three independent items shipped together. Full diagnosis in
`.claude/lessons-learned/v2.11-wp05-diagnosis.md`.

### A8 — Production fail-fast on `ENVIRONMENT=production` + `DEV_AUTH_BYPASS=True`

Guard implemented in `app/main.create_app()`, NOT in `Settings`. The
settings layer must remain a neutral data container — `tests/test_config.py`
pins this with `test_production_with_dev_auth_bypass_no_settings_error`.
Putting the guard in `create_app()` means hundreds of dev/staging tests
that rely on `DEV_AUTH_BYPASS=true` continue to boot; only the production
combo aborts.

Lesson: **module-level `app = create_app()` makes "import" and "boot" the
same event.** The G1 test had to import `create_app` BEFORE flipping env
so its OWN module-load call would not raise outside `pytest.raises`. If
you ever add a fail-fast guard to `create_app()`, every test that
manipulates the relevant settings has to import the module-load path
before flipping env, or you'll see false-positive failures during
collection.

### A9 — `DATABASE_URL` async-driver enforcement

`@field_validator("DATABASE_URL")` accepts `postgresql+asyncpg://` and
`sqlite+aiosqlite://`; rejects `postgresql://`, `postgres://`,
`postgresql+psycopg2://`, `sqlite:///`. The whole codebase already uses
asyncpg (conftest + REQUIRED_ENV), so no test fixture surgery was
required.

Lesson: **silent misconfig at the engine layer surfaces as opaque
"AttributeError: 'Connection' object has no attribute 'execute'" deep
inside SQLAlchemy.** Validators at settings construction time cost one
string-prefix check and turn that 5-stack-frame mystery into a single
clear error message that names the offending scheme. This is the cheapest
DX win in the WP.

### A10 — `_EXCEPTION_STATUS_MAP` dead-entry removal

Removed `ForbiddenTransitionError → 409` (overridden by tickets-local
`invalid_transition_handler → 422`) and `ForbiddenError → 403`
(overridden by tickets-local `forbidden_handler → 403 envelope`). Even
though `ForbiddenError`'s status code matched, the envelope format
differed — keeping the central entry would have shipped the wrong shape
on any non-ticket surface that raised it.

Added `tests/test_v2_11_wp05_boot_hardening.py::
TestA10ExceptionStatusMapHasNoDeadEntries::
test_no_central_map_entry_is_shadowed_by_module_local_handler` — it
walks `_EXCEPTION_STATUS_MAP.keys()` and asserts none appear in
`app.routes.tickets.EXCEPTION_HANDLERS`. This regression test makes the
override-wins rule unmissable: any future AppError subclass added to the
central map AND a module-local handler dict will trip the test.

Lesson: **a per-route exception handler registered via
`app.add_exception_handler(cls, fn)` always wins over a generic
`@app.exception_handler(AppError)` dispatcher that consults a class
table.** Maintaining both is dead code at best and a latent envelope
divergence at worst. Prefer one canonical handler per class. Unifying
the tickets envelope into the generic handler is a future WP.

### Pytest delta

Baseline 1199 passed -> 1212 passed (+13 new), 5 skipped, 14 xfailed,
0 failed.

---

## WP06 — Page[T] adoption across ad-hoc paged-list routes

Seven paged-list route handlers were returning raw `dict[str, Any]`
instead of the canonical `Page[T]` envelope from
`app/schemas/common.py`. WP06 wires `response_model=Page[ItemSchema]`
across all of them so OpenAPI advertises a typed schema (`Page_X_`),
FastAPI validates outbound payloads, and the frontend has one envelope
contract.

### What changed

Routes converted (file:handler → response_model):

- `app/routes/agents.py::list_activity` & `list_activity_compat` →
  `Page[AgentActivityItem]`
- `app/routes/projects.py::list_projects` → `Page[ProjectRead]`
- `app/routes/projects.py::list_members` → `Page[ProjectMemberRead]`
- `app/routes/projects.py::list_components` → `Page[ComponentRead]`
- `app/routes/sprints.py::list_sprints` → `Page[SprintRead]`
- `app/routes/tickets.py::search_tickets` → `Page[TicketRead]`
- `app/routes/tickets.py::list_watchers` → `Page[TicketWatcherRead]`
- `app/routes/tickets.py::list_attachments` → `Page[TicketAttachmentRead]`

New item schemas in `app/schemas/tickets.py`: `TicketWatcherRead`,
`TicketAttachmentRead`, `AgentActivityItem`. Other item schemas
(`ProjectRead`, `ProjectMemberRead`, `ComponentRead`, `SprintRead`,
`TicketRead`) already existed.

### Decision-gate finding

The only real shape drift was `agents/activity`: pre-WP06 it returned
`{items, limit, offset}` (mismatched with `Page[T]`'s `{items,
next_cursor, total}`). I confirmed both via grep and reading
`frontend/src/api/audit.ts` that no consumer reads `body.limit`/
`body.offset` — they're query params, never response fields. Approved
the drop. All other six routes were additive (gained `next_cursor`/
`total`, lost nothing).

### Lesson

When auditing for envelope convergence, the right gate is "does anyone
*read* this key from the response body?", not "does the wire shape
match key-for-key?". A literal key-for-key comparison would have blocked
`agents/activity` on a phantom contract — the `limit`/`offset` keys had
no readers, they were just legacy debug echo.

### Test pin

`tests/routes/test_page_t_adoption_wp06.py` — 19 tests. The two
parametrized batches assert the OpenAPI shape (property set is exactly
`{items, next_cursor, total}` and the schema name resolves to a
`Page_<X>_` alias rather than an inline dict). Runtime smoke test
confirms the converted `agents/activity` no longer leaks the old
`limit`/`offset` keys at the wire level.

### Pytest delta

Baseline 1212 passed -> 1231 passed (+19 new), 5 skipped, 14 xfailed,
0 failed.


---

## v2.11-WP07 — `response_model=` wire-up for single-item routes (Bucket B2)

### What changed

Twenty single-item handlers across five route modules now declare an
explicit `response_model=`. Per-endpoint mapping is in
`.claude/lessons-learned/v2.11-wp07-diagnosis.md`.

New schemas:

- `app/schemas/tickets.py`: `TicketCommentRead`, `TicketCommentsList`,
  `TicketLinkRead`, `TicketLinksGrouped`, `TicketSubtreeRow`,
  `TicketSubtreeResponse`.
- `app/routes/users.py`: `UserHandleResponse` (legacy `UserResponse`
  lacks `handle` / `is_active`, so consolidation wasn't possible).
- `app/routes/leaderboard.py`: `LeaderboardEntry`, `LeaderboardResponse`.
- `app/routes/problems.py`: `ClaimToggleResponse`.
- `app/routes/edit_suggestions.py`: `EditSuggestionActionResponse` (the
  pre-existing `EditSuggestionResponse` was defined-but-unused and is
  now wired on POST create + GET list).

Existing schema **extended**: `TicketRead` gained eight fields that
`Ticket.to_dict()` was already returning but the schema had been
dropping — `project_id`, `sprint_id`, `component_id`, `epic_id`,
`fix_versions`, `resolution`, `resolved_at`, `created_agent_step_id`.
Also `extra="allow"` for forward-compatibility.

### Decision-gate finding

`TicketRead` had been narrowing its declared shape (eight fields short
of `Ticket.to_dict()`'s wire shape) since v2.1. WP06's
`response_model=Page[TicketRead]` on `search_tickets` had been silently
dropping those keys for the duration of WP06 — but no test caught it
because the WP06 tests asserted the envelope shape
(`{items, next_cursor, total}`), not the per-item schema. The drift
showed up here because wiring `TicketRead` on the single-ticket
handlers would have broken the Kanban (which reads `project_id`,
`sprint_id`, `fix_versions`, etc.) on first deploy. Extending the
schema fixes both WP07 and retroactively closes the WP06 hole.

### Lesson

Envelope-shape tests (`{items, next_cursor, total}` property assertions)
are necessary but not sufficient when a `response_model` is added.
A complete pin needs to also assert that the *item* schema name
resolves to the expected pydantic class AND that no fields that the
frontend reads have been dropped.

The follow-up to add a generic "for every route with a response_model,
spec[response].properties ⊇ frontend-read keys" test is bucketed as a
v2.12 candidate — it would have caught this WP06 narrowing automatically.

### Test pin

`tests/routes/test_response_model_adoption_wp07.py` — 21 tests.
Parametrized over 20 (method, path, expected_name) tuples, each
asserting:

1. The success-response (200/201) schema is a `$ref` (not inline).
2. The `$ref` resolves to the expected `components.schemas.<Name>`.

Plus one schema-registration sanity check. All 21 fail on baseline,
all pass after the wire-up.

### Pytest delta

Baseline 1231 passed -> 1252 passed (+21 new), 5 skipped, 14 xfailed,
0 failed.

---

## v2.11-WP08 — collection-time lints (patch-string + text-bind-cast)

Bucket C1/C2 from `ticketing-v2.10.md` lines 1335-1347. Two AST-based
pytest lints that catch, at test-collection time, the two silent-failure
classes that bit v2.10 multiple times:

- **C1** — `unittest.mock.patch("dotted.path", ...)` where the dotted
  target no longer resolves at runtime. The patch silently becomes a
  no-op; production code runs unmocked; the test "passes" because the
  surrounding assertions don't notice. v2.10-WP03, WP05, and WP07 each
  shipped a fix for a real instance. Test: `tests/test_patch_string_resolution_lint_wp08.py`.
- **C2** — `text("... :bind::cast ...")` SQLAlchemy bind-cast trap.
  `:name` is consumed by the bind parser, leaving a stray `::type` that
  errors at execute time (or worse, mis-binds). Correct: `CAST(:name AS type)`
  or push the cast into Python. Test: `tests/test_text_cast_lint_wp08.py`.

### Pattern reuse

Both lints follow the v2.11-WP02 `test_legacy_status_sweep.py` shape
exactly: `ast.parse` → `ast.walk` → string-literal harvest → matcher.
No `conftest.py` collection hooks (v2.10-WP07 cleared those and the
constraint is to keep that boundary clean).

### Iteration finding — `unittest.mock` doesn't use last-dot splitting

First-pass C1 resolver split `a.b.c.d` on the last dot (`a.b.c` import,
`d` getattr) and false-positived on real working patterns:

- `patch("pathlib.Path.unlink")` — `Path` is a class on `pathlib`, not a
  submodule.
- `patch("app.services.delivery.httpx.AsyncClient")` — `httpx` is a
  re-exported attribute on `app.services.delivery`, not a submodule.

`unittest.mock` resolves dotted strings by importing the **longest**
importable prefix and walking the rest as attribute access. The fix
mirrors that: try `parts[:-1]`, `parts[:-2]`, … `parts[:1]` until one
imports, then `getattr` the remainder. Documented in
`.claude/lessons-learned/v2.11-wp08-diagnosis.md`.

### Lesson

When you write a static lint that simulates a runtime behaviour (mock
resolution, sqlalchemy bind parsing, etc.), **match the runtime
algorithm exactly** before turning the lint loose on a real codebase.
Approximations false-positive on legitimate patterns and erode trust in
the lint. The C1 resolver only became useful once it implemented
mock's actual lookup, not a plausible-looking simplification.

### Exclusion rules (both lints)

**C1**: skip `patch.dict(...)` (different mechanism), skip
`patch.object(...)` (first arg is real object, not string), skip
no-dot first args, skip f-string first args (dynamic), skip on
import-time side-effect crashes (env issue, not target issue).

**C2**: AST surface is `text(...).args[0]` so comments and docstrings
are naturally out of scope; non-string args (variables, runtime
concatenations) skipped as out-of-static-scope; naked `column::int`
casts (no leading-colon bind name) intentionally not flagged — the
regex `:[a-zA-Z_][a-zA-Z0-9_]*::[a-zA-Z]` anchors on `:bind::`.

### Real fixups

**None.** Both lints reported clean against the current repo (after C1's
resolver was upgraded to mock-compatible lookup). The lints exist to
catch the next regression, not to clean up an existing mess.

### Pytest delta

Baseline 1252 passed → 1256 passed (+4 new), 5 skipped, 14 xfailed,
0 failed.


## v2.11-WP09 — test-app factory + conftest ambient-env audit

**Status:** ✅
**Suite:** 1256 → 1262 passed (+6 new), 5 skipped, 14 xfailed, 0 failed.

### Two buckets

**C3** — bare `FastAPI()` constructor in tests skips middleware +
exception handlers that `app.main.create_app()` wires. v2.10-WP02/WP07
each shipped a silent-pass bug from this. Fixed by **both**:

- `tests/helpers/app_factory.py::build_test_app(**overrides)` —
  delegates to `create_app()`, merges `dependency_overrides`.
- `tests/test_create_app_factory_lint_wp09.py` — AST lint flagging
  `Call(func=Name('FastAPI'))` across `tests/**`; 37-file allow-list
  with one-line justifications. Smoke test asserts the helper-built
  app wires `AppError` and every `app.routes.tickets.EXCEPTION_HANDLERS`
  key.

Migration of the 31 legacy route-test sites deferred to v2.11-WP09-FU1
(scope too large for this WP; the lint freezes the surface).

**C6** — `os.environ.setdefault(...)` in conftest sets a default for
the whole pytest session, masking Settings model defaults. v2.10-WP05
hit this for `ENVIRONMENT`/`DEV_AUTH_BYPASS`. Fixed by:

- Annotating every setdefault in `tests/conftest.py` with
  `# load-bearing: <reason>` (13 keys; 0 risky — all are either
  Settings-required or deliberately pinned).
- `tests/test_conftest_env_audit_wp09.py` enforces the annotation.

Full classification table lives in
`.claude/lessons-learned/v2.11-wp09-diagnosis.md`.

### Lessons-pin

- **The allow-list is the contract, not the goal.** Shipping the lint
  with 37 documented exceptions is FINE — the lint freezes the surface
  and turns the next bare `FastAPI()` into a CI failure. The 31 legacy
  migrations are a separate WP (the payoff: surfacing silent-pass
  bugs lurking in those tests).
- **Annotation lints beat semantic lints when the value-vs-default
  classification is judgment-heavy.** C6's lint only asserts an
  annotation exists; the diagnosis table carries the rationale. If a
  contributor adds a setdefault without justification, CI fails; the
  reviewer + diagnosis-table-update is the human gate.
- **The smoke test is load-bearing.** `test_build_test_app_helper_wires_exception_handlers`
  pins the contract that `build_test_app()` wires the full production
  exception surface. If a future refactor of `create_app()` ever drops
  a handler, this test catches it before the migration WP silently
  inherits the regression.

---

### WP10 — SQLAlchemy `naming_convention` + alembic constraint-name lint (Bucket C4)

**Status:** complete. 1267 passed / 0 failed / 5 skipped / 14 xfailed (baseline 1262 + 5 new).

**What landed:**
- `app/database.py` — `class Base(DeclarativeBase)` now declares
  `metadata = MetaData(naming_convention=NAMING_CONVENTION)`. Module-level
  `NAMING_CONVENTION` constant ships with 4 keys (`ix`, `uq`, `fk`,
  `pk`) — see "Trade-off" below for why `ck` is intentionally omitted.
  `alembic/env.py` already binds `target_metadata = Base.metadata`, so
  future autogenerate runs pick up the convention automatically.
- `tests/test_naming_convention_wp10.py` (new, 3 tests) — asserts the
  convention dict exactly, plus two pure-unit smoke tests proving
  unnamed `UniqueConstraint` resolves to `uq_<table>_<col>` and an
  unnamed `ForeignKey` resolves to `fk_<table>_<col>_<reftable>` (the
  exact name shape the v2.10-WP06 fix had to write by hand for
  `fk_problems_domain_id_domains`).
- `tests/test_alembic_constraint_name_lint_wp10.py` (new, 2 tests) —
  AST sweep over all 25 `alembic/versions/*.py` files for `None`-named
  or arg-missing constraint calls (`create_foreign_key`,
  `drop_constraint`, `create_unique_constraint`,
  `create_check_constraint`, `create_primary_key`). Currently CLEAN
  (the WP06 fix was the only historical occurrence). Synthetic-bad
  self-test covers 5 cases including a bare-import (no `op.` prefix)
  variant.

**Trade-off discovered: `ck` template omitted.**

The SQLAlchemy idiomatic `ck` template
(`ck_%(table_name)s_%(constraint_name)s`) substitutes
`%(constraint_name)s` with whatever name the caller passes — there is
no "is this already prefixed" detection. Every existing migration in
this repo passes the **full** name
(`op.create_check_constraint("ck_projects_coalesce_seconds_range",
"projects", ...)`), so applying the idiomatic `ck` template
double-wraps to `ck_projects_ck_projects_coalesce_seconds_range` at DDL
compile time. First-pass full suite caught this immediately:
`test_each_agent_kanban_revision_is_reversible` failed with
`UndefinedObjectError: constraint
"ck_projects_ck_projects_coalesce_seconds_range" of relation
"projects" does not exist` on `downgrade base`.

The brief explicitly bans altering existing constraint names *or*
migration files, so the only safe move was to drop `ck` from the
convention. `fk` / `uq` / `ix` / `pk` are immune because their
templates substitute column/table-driven tokens, not the
caller-provided name — explicit `name=` arguments pass through
cleanly.

**Audit findings:**

- All ORM `UniqueConstraint(...)` / `CheckConstraint(...)` /
  `ForeignKeyConstraint(...)` calls in `app/models/**.py` use
  explicit `name=` strings. None rely on auto-naming today, so the
  convention is strictly forward-looking for ORM code.
- Alembic scan: 25 files, 0 hits. v2.10-WP06's manual fix to
  `7f57993c9b09` remains the only historical occurrence; the
  project-wide lint now gates future regressions.

**Lessons-pin:**

- **The idiomatic `naming_convention` is a one-shot project decision,
  not a retrofit.** It assumes short caller-provided names from day
  one. Adopting it mid-life requires rewriting every
  `CheckConstraint(name=)` to short form AND a follow-up migration to
  rename the live DB constraints — too invasive to land in a single
  WP. Shipping 4 of 5 keys with `ck` deferred is the honest call.
- **Column-driven templates are safe; name-driven templates are
  not.** `fk` / `uq` / `ix` / `pk` substitute column/table tokens
  that have no overlap with explicit `name=` strings. `ck` is the
  only template that re-uses the caller's name as a substitution
  token, which is why it's the only one that collides on a legacy
  codebase.
- **Static AST lints across alembic versions are cheap insurance.**
  The WP10 sweep takes <50ms and catches the exact class of bug WP06
  spent 4 deferred-test classifications to surface. Pair the
  `naming_convention` (preventive) with the lint (detective) for
  defense in depth.

Full diagnosis in `.claude/lessons-learned/v2.11-wp10-diagnosis.md`.

---

## WP11 — `MagicMock` Headers + SPA catch-all hardening (C5 + C8)

Two small test-infra hardening items. C5 closes a case-sensitivity
divergence in request mocks; C8 ships a "register a test route that
beats the SPA catch-all" helper plus a regression-shape pin so a
future refactor of `create_app()` can't silently break the assumption.

**Pytest:** 1267 → **1274 passed**, 0 failed, 5 skipped, 14 xfailed.

### C5 — `Headers` everywhere mocks pretend to be a `Request`

- Helper: `tests/helpers/requests.py::build_mock_request(*, headers,
  cookies, **extra)` wraps `headers` in
  `starlette.datastructures.Headers(...)` (case-insensitive, matches
  production) and returns a `MagicMock`.
- Lint: `tests/test_mock_headers_lint_wp11.py` flags two AST patterns
  across `tests/**`:
  1. `MagicMock(headers={dict-literal})` (also `Mock`, `AsyncMock`,
     `NonCallableMock`).
  2. `<expr>.headers = {dict-literal}` (catches the
     `request.headers = headers_dict` shape too).
- Hit count at WP11 land: **1** —
  `tests/auth/test_dependencies.py:50`. Migrated to
  `build_mock_request`; allow-list is empty.
- Bonus: re-seeded the test with canonical `"Authorization"` casing
  (was hand-lowered to `"authorization"` to dodge the dict-case bug)
  so the test now exercises the case-insensitive lookup end-to-end.

### C8 — `register_test_route` + SPA-shape pin

- Mechanism review: `app.main.create_app()` registers the SPA
  catch-all as `@app.get("/{full_path:path}")` (a Route, not a
  Mount) inside `if frontend_dist.is_dir()`, after all
  `app.include_router(...)` and `app.add_exception_handler(...)`
  calls. Test environment runs without `frontend/dist`, so today the
  catch-all isn't even registered at test time — but CI / prod
  builds DO have it, and v2.10-WP01 + WP07 each tripped on it.
- Helper: `tests/helpers/test_routes.py::register_test_route(app,
  path, endpoint, *, methods, name)` adds the route via
  `app.add_api_route(...)` then moves it from the tail of
  `app.router.routes` to `[0]`. Wins against any pre-existing route,
  including a catch-all.
- Regression pin:
  `tests/test_spa_catchall_hardening_wp11.py::test_spa_catchall_shape_in_create_app`
  inspects `create_app`'s source for three facts: (1) decorator-style
  `@app.get("/{full_path:path}")` (not a Mount), (2) guarded by
  `frontend_dist.is_dir()`, (3) catch-all line index is greater than
  every `include_router` and `add_exception_handler` index. Source
  inspection is the right tool here because the load-bearing fact is
  registration *order* inside `create_app`, not the runtime route
  list (a refactor that hoists the catch-all earlier in the function
  but ships before a new router include would slip past a route-list
  check).

### Lessons

- **`unittest.mock.MagicMock` lets you fake any attribute, which is
  exactly why production-shape divergences slip in.** A
  `MagicMock(headers={...})` looks plausible and passes type
  inference, but the dict is case-sensitive and production isn't.
  Two ways to defend: (a) a factory helper that always wraps in the
  production type, (b) a lint that catches the bare-dict shape. WP11
  ships both.
- **A "register at routes[0:0]" helper is smaller than restructuring
  the SPA catch-all.** Option (a) in the brief (sub-router + Mount)
  would change production wiring just to make tests cleaner — the
  bigger fix needs a real motivation. `register_test_route` is
  test-side only and explicit about what it does.
- **For "registration order matters" invariants, AST inspection of
  the factory function beats a runtime route-list check.** The
  invariant is positional within the function body; a list-shape
  check can be defeated by a refactor that moves the line earlier.
  Pair the AST check with a runtime cross-check for cases where the
  conditional branch IS taken (frontend/dist present).
- **An empty allow-list is the load-bearing artifact.** WP11's C5
  `_ALLOWLIST` ships empty — the next test that introduces a
  plain-dict `.headers` has a forcing function (the lint) and a
  clean path (migrate or justify-in-list). Allow-lists with one
  entry are the same shape as allow-lists with thirty, but an empty
  one signals "we currently have zero exceptions" loud and clear.

Full diagnosis in `.claude/lessons-learned/v2.11-wp11-diagnosis.md`.

### WP12 — Docs cleanup: phantom citations + dev-secret audit + v1 mechanism confirmation (Bucket D1/D2/D3)

**Status:** complete. 1281 passed / 0 failed / 5 skipped / 14 xfailed (1274 baseline + 7 new regression tests).

**Three small audits, all closed.**

- **D1 — `AION_BULLETIN_TEST_DOCS.md` citations.** The wp04a/b
  diagnoses called these citations "phantom" — they're not. The doc
  exists at `docs/AION_BULLETIN_TEST_DOCS.md` (3508 lines), and all
  10 test-file citations (`Foundation Layer`, `§Authentication`,
  `Mock/Stub Interface Specifications`, `lines 1731–1876`) line up
  against still-present section headers. Per the brief's threshold
  (≥5 coherent citations to a real doc → keep), zero edits to test
  docstrings. The wp04a/b follow-up annotations remain in the
  historical record but are now superseded by this WP's audit table.

- **D2 — `.env.example` / docs dev-secret audit.** v2.10-WP05 deleted
  six placeholder defaults from `app/config.py` including the
  `JWT_SECRET = "dev-secret-change-me"` footgun. Sweep found exactly
  one literal advertising the deleted footgun in docs:
  `docs/DESIGN_REF.md:1191` showed
  `JWT_SECRET=dev-secret-not-for-production` in a podman-compose
  yaml block. Replaced with `JWT_SECRET=__set_me__   # placeholder
  — must be set to a real ≥32-char secret; never use this literal
  in any environment`. Also rewrote `.env.example` with a top-of-file
  banner declaring every value a placeholder (not safe default) and
  converted the more-plausible-looking values (`replace-with-…`) to
  `__set_me__` form so a copy-paste of the file fails Settings
  validation. No README at repo root; engineering-guide compose
  tables already say "must be overridden in production"; `.env.test`
  and `conftest.py` test fixture values are load-bearing test
  artifacts (already annotated by WP09). Compose `changeme` defaults
  are out of D2 scope.

- **D3 — `_v1_deferred.py` mechanism confirmation.** The file is
  gone (v2.10-WP07); the `pytest_collection_modifyitems` hook is
  gone; `tests/conftest.py` carries two top-of-file explanatory
  comment blocks documenting the deletion. New regression pin:
  `tests/test_no_v1_deferred_mechanism_wp12.py` — 7 tests, AST walk
  for the hook definition (so renames / async-def / nested-class
  variants are caught), filesystem existence check, plus a
  synthetic-bad self-test that exercises the AST detector against a
  source string that DOES define the hook (guards against silent
  detector regression).

### v2.11 deferral-mechanism policy

> The v1 bespoke deferral registry (`tests/_v1_deferred.py` + a
> `pytest_collection_modifyitems` hook that auto-skipped any ID
> listed there) was deleted in v2.10-WP07 and must not be revived.
> All per-test deferral after v2.10 uses plain
> `@pytest.mark.skip(reason=...)` or `@pytest.mark.xfail(reason=...,
> strict=True)` with an explicit reason. Source-shape regression
> pin: `tests/test_no_v1_deferred_mechanism_wp12.py`.

### Lessons

- **"Phantom doc" can mean "phantom citation against a real doc, not
  a missing doc."** wp04a/b inferred the doc was missing because the
  *implementation* the citation pointed at had refactored. The
  remedy when the doc still exists is reconciliation, not deletion.
  A v2.12 audit pass over older lessons-learned follow-ups for the
  same shape would be cheap.
- **`.env.example` files attract footguns by default.** The brief
  framed them as legitimately placeholder-bearing — true, but
  "placeholder" still has a quality bar. `replace-with-…` reads as
  an instruction; `__set_me__` reads as a token that obviously
  cannot work in a real environment. The Settings min-length check
  on `JWT_SECRET` (v2.10-WP05) already catches the worst footgun;
  banner-comments + obvious-tokens close the rest.
- **AST-walk lints beat grep for "this hook must not exist"
  invariants.** A grep for `def pytest_collection_modifyitems` is
  defeated by renames, `async def`, or `import X as
  pytest_collection_modifyitems`. The AST walk in WP12's regression
  test catches all three. Pair it with a synthetic-bad self-test in
  the same file so a refactor of the detector itself can't silently
  break the invariant.

Full diagnosis in `.claude/lessons-learned/v2.11-wp12-diagnosis.md`.

## WP13 — v1 `/api/search` sunset signalling + email-digest empty-list contract

**Status:** ✅ COMPLETE. 1281 → **1288 passed** (+7), 0 failed, 5
skipped, 14 xfailed.

**E1 — v1 `/api/search` sunset.** Added RFC 8594 `Deprecation: true`
and `Sunset: Sun, 22 Jul 2026 00:00:00 GMT` (~60d window) response
headers on the v1 handler in `app/routes/search.py`. Introduced
`V1_SEARCH_SUNSET_RFC1123` constant + `_resolve_v1_caller(request)`
helper that surfaces `auth:<scheme>` (truncated, credential never
logged) or `ip:<host>`, falling back to `unknown`. Every v1 hit now
emits `logger.warning("v1_search.hit caller=%s q_len=%d", ...)` —
the `v1_search.hit` grep tag is the monitoring signal. v1 handler
remains in place per brief; deletion is a future PR after the
window closes. Pruned the orphan `[/^\/api\/search$/, "search"]`
regex from `frontend/src/mock/api.ts`. `frontend/dist` rebuild is a
deployment step, deferred to follow-ups.

**E5 — `send_email_digest` empty-list contract.** Extended the
docstring at `app/services/delivery.py::send_email_digest` to
explicitly document: empty `notifications` ⇒ returns `None` before
DB lookup AND before SMTP call. Pinned by a pure-unit test
(`tests/services/test_send_email_digest_empty_contract_wp13.py`) —
`db` is a `MagicMock` with `db.execute` patched to `AsyncMock`,
`aiosmtplib.send` patched at module level; both `assert_not_called()`.
A second test passes a deliberately-invalid UUID and confirms no
parse-attempt before the early return — guards against a future
"refactor" silently moving the empty-check after `uuid.UUID(...)`.

**Lessons.**
- **`caplog` does not play nice with the project's JSON-logger
  pipeline.** Route-level log assertions need a fresh
  `logging.Handler` attached to the target logger inside the test
  body and detached in `finally:`. The first test draft used
  `caplog.at_level(...)` and silently captured zero records even
  though the log line was clearly emitted to stdout. Worth
  promoting to a shared `tests/helpers/log_capture.py` helper next
  time a second route needs the same treatment.
- **v2.11-WP09's bare-`FastAPI()` lint really does enforce.** First
  draft of the route test built `FastAPI()` directly and tripped
  the allowlist sweep — diff-time error, not a runtime mystery.
  Resolution: always start route tests with
  `tests.helpers.app_factory.build_test_app(dependency_overrides=…)`.
- **Deprecation signalling is two layers, not one.** The
  `Deprecation` + `Sunset` headers are the *machine* signal for
  monitoring/SDK middleware; the WARN log line is the *human*
  signal for SRE grep. Both belong in the same PR — landing only
  one halves the value of the monitoring window.
- **Log hygiene tests pay for themselves.** The dedicated test
  that pins both "Authorization header → `auth:<scheme>` captured"
  AND "credential value NEVER appears in the log line" exists
  specifically because someone, someday, will try to make the
  log line "more useful" and inadvertently leak a token. The test
  refuses to let the leak land silently.

Full diagnosis in `.claude/lessons-learned/v2.11-wp13-diagnosis.md`.

## WP14 — Cursor pagination polish: `total_authority` + `refresh_total` (Bucket F1/F2 from v2.10)

Builds on v2.10-WP10's stable-total cursor mode. Two additive
polish items framed in `ticketing-v2.10.md` lines 1422-1432.

**F1 — `total_authority` cursor-payload field.** The HMAC-signed
cursor envelope's payload now carries an optional `"a"` field
alongside the `"t"` (snapshot total) field added by WP10. Value is
`"snapshot"` (WP10 pinned first-page count) or `"live"` (a re-count
forced by `refresh_total=True`). The arm response surfaces the
same value as `total_authority` so the frontend can — eventually —
show "Showing snapshot count, refresh to update" without us having
to invent a side-channel for the provenance signal. The field is
additive: pre-WP14 cursors lacking `"a"` decode cleanly and are
treated as `"snapshot"` (new helper
`_authority_from_cursor()` in `app/services/search_multi.py`).

**F2 — `refresh_total` query param.** New
`GET /api/search/v2?refresh_total=1` opts out of the snapshot for
the current request. The arm's `total` reflects the live
`COUNT(*) OVER ()`, and `total_authority="live"` is surfaced.
Default `false` preserves WP10's stable-total invariant verbatim —
pinned by `test_refresh_total_false_default_preserves_stable_total`.

**HMAC backwards-compat.** No version bump on the envelope. The
HMAC sig is computed over canonical-JSON of the *received* payload,
so adding a new key just enters the canonicalisation naturally; old
sigs verify against old payloads, new sigs verify against new
payloads, both flow through the same `decode_signed_cursor()`
helper without branching. This is the same property that made WP10
additive on pre-WP10 cursors — WP14 piggybacks.

**Frontend.** Plumbing only:
`SearchArm.total_authority?: "snapshot" | "live" | null` and
`SearchV2Params.refresh_total?: boolean` added to
`frontend/src/api/search.ts`. No UI surface consumes the field yet
(brief explicitly cap-scoped a "snapshot banner" out). 236
frontend tests still green.

**Pytest delta.** 1288 → 1297 (+9 new: 3 cursor-helper roundtrips,
4 service-layer arm-response assertions, 2 route-level smoke
tests). One existing assertion adjusted
(`test_tickets_arm_empty_query_short_circuits`) to include the
new `total_authority` key on the empty-arm shape.

**Lessons.**
- **"Additive cursor field" only stays additive if the new
  field is gated on the *companion* field's presence.** First
  draft of `_build_next_cursor` always emitted `"a"`. That would
  have meant cursors minted before `total=` was threaded in
  (theoretically: legacy code paths or unit-test mints without
  the kwarg) gained an `"a"` without a matching `"t"`. Settled on
  "emit `"a"` only when `"t"` is also being set" — keeps the
  cursor schema tight (no orphan authority statements) and means
  the test `test_legacy_cursor_without_authority_still_decodes`
  isn't just covering "we accept old cursors" but also "we
  produce schema-clean new ones."
- **Authority propagation needs an explicit `prior_authority`
  variable.** First draft just hard-coded `"snapshot"` on the
  cursor-paged branch. That works for the simple
  `snapshot → snapshot → snapshot` chain but throws away
  information when a client opted into `refresh_total=True` then
  dropped it on the next page — the now-fresh total would be
  reported as `"snapshot"` even though it had just been
  re-counted. Reading `_authority_from_cursor(cursor)` into a
  variable and threading it through preserves the audit trail:
  once a chain is on `"live"`, subsequent pages without an
  explicit `refresh_total=False` flag still report `"live"` until
  a fresh cursor-less request resets the snapshot. Worth flagging
  in the diagnosis so anyone touching the state machine later
  doesn't simplify it back to a constant.
- **`build_test_app()` + `dependency_overrides` is the cleanest
  way to add new route-level tests now.** First time using it on
  a new test file (rather than a migration). The two-test smoke at
  `tests/routes/test_search_v2_refresh_total_wp14.py` runs through
  the *real* exception handlers and middleware stack — meaning
  any future regression where a 400 is raised but the JSON
  envelope shape drifts would surface here. The bare-FastAPI
  allowlist stays unchanged; that's the whole point of the
  helper.

Full diagnosis in `.claude/lessons-learned/v2.11-wp14-diagnosis.md`.

## WP15 — `legacy_status` → `status` DB rename (Bucket E2)

- **Closed the Python-attribute-vs-DB-column asymmetry that anchored a
  raw-SQL footgun for three WPs running.** New migration
  `a19_problems_status_rename` renames `problems.legacy_status` →
  `problems.status`; ORM drops its column-name override; three raw-SQL
  hits in `app/services/search.py` + `app/services/search_multi.py`
  revert to the simple spelling. Backend suite stays at the 1297-passed
  baseline; migration roundtrip walks the whole chain.
- **Alembic `version_num VARCHAR(32)` is the silent revision-length
  cap.** First attempt at the revision ID was 43 chars
  (`a19_rename_problems_legacy_status_to_status`) — alembic happily
  registers the script but Postgres-asyncpg raises
  `StringDataRightTruncationError` at the closing `UPDATE alembic_version`
  step. SQLite-backed local testing would not catch this. Shortened to
  `a19_problems_status_rename` (26 chars). The descriptive file name
  itself is unconstrained — only the revision string matters. Worth
  pinning a per-repo convention: revision IDs ≤ 32 chars, file names
  freeform.
- **Inverted the WP02 regression lint rather than deleting it.** The
  AST scanner used to flag `p.status` / `problems.status`; it now flags
  `legacy_status` anywhere under `app/`. The self-test pattern (synthetic
  drift + clean-case) carried over cleanly — only the regex anchor
  changed. Cheap, permanent guard against the asymmetry sneaking back in
  a future copy-paste. The pattern of "invert the lint when the
  invariant flips" is reusable.
- **Test-side raw-SQL inserts had to be ported in lockstep.** Seven test
  files plus `tests/helpers/seed_problem.py` had column-list literals
  `(... , legacy_status, ...)` that would otherwise crash at the first
  INSERT after upgrade. A simple `sed` substitution covered them; the
  audit was the AST lint plus a final `grep -rn legacy_status tests/`
  (zero hits remaining). The grep + lint combo is the assurance, not the
  sed.

Full diagnosis in `.claude/lessons-learned/v2.11-wp15-diagnosis.md`.

---

## v2.11 retrospective

### Headline numbers

- **Backend baseline:** 1190 P / 0 F / 5 skipped / 14 xfailed (v2.10 close).
- **Backend final:** **1297 P / 0 F / 5 skipped / 14 xfailed**.
- **Net delta:** +107 tests across 15 WPs — overwhelmingly lint /
  regression-pin / contract assertions rather than new feature
  coverage. Skipped/xfailed counts unchanged, no churn.
- **Frontend:** 236 P / 0 F unchanged (only WP14 touched
  `frontend/src/api/search.ts` for additive types; no UI surface).
- **Production regressions introduced:** zero. Every WP held the
  green-suite invariant across its merge gate.

### WPs shipped

| WP | Bucket | Summary | Test delta |
| --- | --- | --- | --- |
| WP01 | A1 | `agent_accounts.created_by` ORM↔DB alignment; service-layer required-arg guard. | +2 (1190→1192) |
| WP02 | A2 | `legacy_status` raw-SQL sweep + AST regression lint. | +2 (1192→1194) |
| WP03 | A3+A4 | `update_user_role` role-string validation + `log_event` audit-actor sweep. | +4 (1194→1198) |
| WP04 | A5+A6+A7 | `delete_attachment` service-layer auth, `set_watch` `db.refresh`, strict `get_tags` sort. | +1 (1198→1199) |
| WP05 | A8+A9+A10 | prod + `DEV_AUTH_BYPASS` fail-fast, async-driver `DATABASE_URL` validator, exception-map normalisation. | +13 (1199→1212) |
| WP06 | B1 | `Page[T]` adoption across 7 paged-list routes. | +19 (1212→1231) |
| WP07 | B2 | `response_model=` wire-up across 21 single-item routes; `TicketRead` field-completeness fix. | +21 (1231→1252) |
| WP08 | C1+C2 | `patch("dotted.symbol")` resolver lint + `text("...::cast")` form lint. | +4 (1252→1256) |
| WP09 | C3+C6 | `build_test_app()` helper + bare-`FastAPI()` allow-list lint; conftest ambient-env audit. | +6 (1256→1262) |
| WP10 | C4 | `MetaData.naming_convention` (4/5 keys) + alembic constraint-name lint. | +5 (1262→1267) |
| WP11 | C5+C8 | `Headers` request-mock fixture + lint; `register_test_route` helper + SPA catch-all pin. | +7 (1267→1274) |
| WP12 | D1+D2+D3 | docs reconciliation; `_v1_deferred.py` mechanism-absence AST pin. | +7 (1274→1281) |
| WP13 | E1+E5 | v1 `/api/search` sunset headers + hit-count log + mock prune; `send_email_digest` empty-list pin. | +7 (1281→1288) |
| WP14 | F1+F2 | cursor payload `"a"` (total_authority) + `refresh_total=1` query param. | +9 (1288→1297) |
| WP15 | E2 | `problems.legacy_status` → `problems.status` DB rename + alembic migration; WP02 lint inverted. | ±0 (1297→1297) |

### Production bugs caught

1. **WP01** — `agent_accounts.created_by` mapped `nullable=True` in
   ORM but `NOT NULL` in `a17` migration. Type checker saw `UUID | None`,
   the DB raised `IntegrityError` at write time. Latent class of
   "seed without column" failures pushed from runtime to collection.
2. **WP03** — `update_config` audit log called
   `log_event(..., "admin", ...)` with the literal string `"admin"`
   as `user_id`; sibling admin services passed `str(user_id)`. Audit
   trail was unattributable for every config edit since v1.
3. **WP04 (A5)** — `delete_attachment` service had no
   uploader-or-admin check; the route enforced it but any non-HTTP
   caller (background job, future v3 route) would have bypassed auth.
4. **WP04 (A6)** — `set_watch` returned the SQLAlchemy
   identity-map-cached row after an upsert; `.level` reflected the
   pre-upsert value until the next refresh. Watch-level UI would
   have displayed stale state on the same request that changed it.
5. **WP04 (A7)** — `get_tags` silently fell back to name-order on an
   invalid `?sort=` value; route docstring promised 422. Strict
   422 was chosen.
6. **WP05 (A8)** — `ENVIRONMENT=production` + `DEV_AUTH_BYPASS=True`
   booted silently. Now refused at startup; one config-typo away
   from auth bypass in prod is now one config-typo away from a
   crash loop.
7. **WP05 (A10)** — `_EXCEPTION_STATUS_MAP` declared 409 for
   `ForbiddenTransitionError`, but the tickets router's
   `add_exception_handler` registered a 422-with-envelope override.
   Last-registered-wins made the map entry dead code; tests pinning
   409 were wrong about reality.
8. **WP07** — `TicketRead` schema (added by WP06) narrowed
   `resolved_at` and `created_agent_step_id` out of the response. No
   route returned a 500, but the OpenAPI spec lied to the frontend
   for ~one cycle. Caught before the frontend regenerated types.
9. **WP13** — v1 `/api/search` had no deprecation telemetry. Sunset
   headers + hit-count logging now make removal a measured
   decision rather than a guess.
10. **WP15** — `problems.status` Python attribute mapped to
    `legacy_status` DB column closed permanently. Three WPs in a row
    (v2.10-WP04a/b, v2.11-WP02) tripped on this asymmetry; renamed
    the column and inverted the WP02 lint so the next copy-paste
    fails at collection time.

### Cross-cutting lessons

1. **"Source-shape lint" has reached critical mass — owe a helper.**
   WP02, WP08, WP09, WP10, WP11, WP12, WP15 each wrote AST-walking
   tests over `app/` or `tests/` source. Shared concerns: file
   iteration with allow-list, `ast.parse` + `ast.walk`,
   string-literal harvesting, dotted-path resolution. v2.12 owes
   `tests/helpers/source_lint.py` (~80 LOC) consumed by ≥6 lint
   tests; the duplication is now load-bearing across enough
   modules that a refactor will pay back.
2. **Schema convergence narrows surfaces silently.** WP06 added
   `Page[T]` and WP07 added `response_model=` on adjacent routes;
   in between, `TicketRead` got narrowed without anyone noticing.
   The OpenAPI introspection tests caught it within one WP, but
   the right invariant is a contract test that
   `Ticket.to_dict().keys() ⊆ TicketRead.model_fields` (and
   equivalent pairs across the app). Stage as Bucket C in v2.12.
3. **`patch("module.symbol")` resolution is not single-dot split.**
   `unittest.mock._get_target` walks attributes from the longest
   importable prefix and stops at the first one that imports.
   WP08's first cut split on the last dot and produced false
   positives for `patch("app.services.delivery.httpx.AsyncClient")`
   (httpx is an attribute, not a submodule). The fix walks
   prefixes; documented in the WP08 diagnosis as a reusable
   resolver.
4. **`MetaData.naming_convention` `ck` key double-wraps.** Existing
   `CheckConstraint("...", name="foo")` invocations get re-named
   `ck_<table>_foo` by the convention. WP10 shipped 4-of-5 keys
   (`ix`, `uq`, `fk`, `pk`) and deferred `ck` until a short-name
   port + live DB rename migration lands. Convention keys are
   not atomically additive once data exists.
5. **Alembic `version_num VARCHAR(32)` is a silent cap.** WP15's
   first revision ID was 43 chars; SQLite test pipelines accepted
   it, Postgres-asyncpg raised `StringDataRightTruncationError` at
   the `UPDATE alembic_version` step. Pin the per-repo convention:
   revision IDs ≤32 chars, file names freeform.
6. **JSON-logger pipelines break `caplog`.** WP13's deprecation-hit
   logging assertions needed a fresh `logging.Handler` attached to
   the named logger; `caplog` was already consumed by the
   structured-log pipeline. The pattern (attach handler, run
   request, snapshot `records`, detach) belongs in a
   `tests/helpers/logs.py` sibling to the email helper.
7. **Lint allow-lists are TODO lists, not victories.** WP09 shipped
   with 37 bare-`FastAPI()` files allow-listed against the
   `build_test_app()` lint. Each one is a silent-pass risk for any
   exception-handler or middleware regression on the routes those
   tests cover. v2.12 Bucket A includes the migration; budget it
   per-WP, not as one mega-PR.
8. **"Additive cursor field" stays additive only when the new field
   is gated on its companion.** WP14's `"a"` (total_authority)
   field is emitted only when `"t"` (snapshot total) is also set;
   first draft emitted `"a"` unconditionally and would have created
   schema-orphan cursors from legacy mints. State-machine purity
   compounds with backwards-compat — both invariants per WP.
9. **`build_test_app()` + `dependency_overrides` is the canonical
   route-level test rig.** WP14 was the first new (not-migration)
   consumer of WP09's helper. It runs through the *real* exception
   handlers and middleware stack, so any future envelope-shape
   drift surfaces at the test rather than in production. New
   tests default to it; the allow-list shrinks toward zero.
10. **Inverting a lint is cheaper than deleting it.** WP15 inverted
    the WP02 `legacy_status` scanner from "ban `p.status`" to
    "ban `legacy_status`" — same self-test pattern, opposite
    regex anchor. When an invariant flips, the lint pivots; the
    test infrastructure is the durable artifact, not the
    polarity.

### What stayed deferred (carry to v2.12)

- **C7** — `decode_email_body` helper. No second QP-wrap assertion
  has surfaced; pick up only when one does.
- **E3** — KindPill 7th surface. No new consumer.
- **E4** — `useSearchV2` ergonomic follow-ups. No second consumer.
- **F3** — TipTap second-consumer extraction. No second editor
  surface.
- **WP09 follow-up** — migrate the 37 bare-`FastAPI()` files off the
  allow-list. Staged as v2.12 Bucket A.
- **WP10 follow-up** — resurrect the `ck` naming_convention key via
  a short-name port + live DB rename. Staged as v2.12 Bucket A.

### Files touched (rough stats)

- **Production code (`app/`):** ~25 files. Hottest: `app/main.py`
  (WP05+WP07), `app/routes/tickets.py` (WP06+WP07),
  `app/services/search.py` + `search_multi.py` (WP02+WP13+WP14+WP15),
  `app/schemas/common.py` (`Page[T]` added by WP06), `app/config.py`
  (WP05). One new migration (`a19_problems_status_rename`).
- **Test code (`tests/`):** ~30 files. ~15 net-new test files
  (every lint WP added one), plus ~10 in-place ports for the WP06
  pagination shape and the WP15 column-name flip.
  `tests/helpers/` grew: `seed_problem.py` (column-list flip),
  new `build_test_app` consumer in `tests/routes/`. Conftest
  ambient-env audit (WP09) annotated 13 `os.environ.setdefault`
  sites with `# load-bearing: <reason>`.
- **Frontend (`frontend/`):** 1 file. `frontend/src/api/search.ts`
  +2 additive type fields for WP14 (`total_authority`,
  `refresh_total`). No UI surface yet.
- **Docs (`.claude/lessons-learned/`):** 15 new per-WP diagnosis
  files (`v2.11-wp01-diagnosis.md` through
  `v2.11-wp15-diagnosis.md`) + this retrospective.

---

## v2.12 starting prompt seed

v2.11 closed every Bucket A–F line item from the v2.10 seed that had
a triggering need; the four conditional items (C7, E3, E4, F3) all
held without one. v2.12 picks up two clear migration follow-ups
from v2.11 (the WP09 bare-`FastAPI()` allow-list, the WP10 `ck` key
resurrection), consolidates the source-lint duplication into a
helper, lands the contract pins that would have caught WP07's
narrowing pre-merge, and continues cursor-pagination polish.

### v2.12 backlog

#### Bucket A — v2.11 migration-completion follow-ups

A1. **Migrate the 37 bare-`FastAPI()` test files off WP09's
    allow-list.** Each file replaces `FastAPI()` with
    `build_test_app()`. Expected yield: latent silent-pass bugs
    where a route's real exception handler or middleware
    differs from the test rig's. Budget per-cluster (~6–8 files
    per WP).
A2. **Resurrect WP10's `ck` naming_convention key.** Short-name
    port for every named `CheckConstraint` in `app/models/`, then
    a live DB rename migration that pre-renames existing
    constraints to their `ck_%(table_name)s_%(constraint_name)s`
    form before the convention turns on. One WP, one migration.
A3. **`total_authority="snapshot"` UI banner on Search.**
    Conditional render: when a paginated chain has advanced ≥1
    page and `total_authority === "snapshot"`, show
    "Showing snapshot count — refresh to update". WP14 plumbed
    the field; UI surface is the follow-up.
A4. **"Refresh count" button on Search.** Calls the existing
    endpoint with `refresh_total=1` *without* resetting the
    cursor. Pairs with A3.
A5. **Per-arm `refresh_total` for `entity=all` searches.**
    Today `refresh_total` applies to the whole multi-arm
    response. Decide whether per-arm opt-in makes sense or
    whether all-arms-or-none is the right invariant.

#### Bucket B — `source_lint.py` helper consolidation

B1. **Extract `tests/helpers/source_lint.py`.** Consolidate
    shared AST-walking, file-iter-with-allow-list, and
    literal-harvesting from WP02, WP08, WP09, WP10, WP11,
    WP12, WP15. Target: ~80 LOC consumed by ≥6 lint tests.
    Pure refactor; lint outputs unchanged, test counts
    unchanged.

#### Bucket C — Schema / field-completeness pins

C1. **`Ticket.to_dict().keys() ⊆ TicketRead.model_fields`
    contract test.** Would have caught WP07 pre-merge.
C2. **Extend to other Pydantic↔ORM `to_dict` pairs.**
    Audit every `to_dict()` on an ORM model against the
    matching `*Read` schema; assert the subset invariant.
C3. **OpenAPI vs frontend `*.ts` type-completeness lint.**
    CI step: regenerate types from `app.main:app.openapi()`
    and diff against checked-in `frontend/src/api/*.ts`.
    Fail on field-level drift.

#### Bucket D — Cursor pagination polish (continued)

D1. **Optional `total_authority` per-arm in `entity=all`
    responses** (depends on A5).
D2. **"Showing snapshot count — refresh" UI hint** (depends
    on A3; promote here if the snapshot banner needs more
    states than A3 anticipates).
D3. **F3 (TipTap second-consumer extraction)** — pick up if
    a real second editor surface lands.

#### Bucket E — Exception-envelope unification (WP05 follow-up)

E1. **Unify the two envelope shapes.** The tickets module
    emits `{"error": {code, message, correlation_id, details}}`;
    the rest of the app emits `{"detail": ...}`. Pick one
    (likely the envelope form, with `correlation_id` as the
    durable invariant), wire it through every
    `EXCEPTION_HANDLERS` registration, and add a contract
    test that every `AppError` subclass produces the chosen
    shape. Frontend will need a thin adapter for the period
    until the rest of the app converts.

#### Bucket F — Conditional / deferred

F1. **C7 — `decode_email_body` helper.** Pick up only on a
    second QP-wrap assertion.
F2. **E3 — KindPill 7th surface.** Pick up only when a real
    consumer surfaces.
F3. **E4 — `useSearchV2` ergonomic follow-ups.** Pick up only
    when a second consumer surfaces.
F4. **F3 — TipTap second-consumer extraction.** Pick up when a
    second editor surface lands (see also Bucket D D3).

### v2.12 prompt seed (paste-ready)

> Proceed with v2.12 of the problem-bulletin ticketing system. v2.11
> retrospective + carry-forward backlog live at the bottom of
> `.claude/lessons-learned/ticketing-v2.11.md`. Baselines: backend
> **1297 P / 0 F / 5 skipped / 14 xfailed**, frontend **236 P / 0 F**.
> Default work order: Bucket A (v2.11 migration follow-ups) →
> Bucket B (`source_lint.py` consolidation) →
> Bucket C (schema/field-completeness pins) →
> Bucket D (cursor polish) → Bucket E (exception envelope) →
> Bucket F (conditional). Follow the sequential subagent loop pattern,
> TDD-first, one diagnosis doc per WP under
> `.claude/lessons-learned/v2.12-wpNN-diagnosis.md`. Append lessons to
> `.claude/lessons-learned/ticketing-v2.12.md`. Do NOT reintroduce the
> `_v1_deferred.py` skip-hook — per-test deferral uses plain pytest markers.

