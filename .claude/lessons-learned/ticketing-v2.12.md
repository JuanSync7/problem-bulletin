# v2.12 ticketing — lessons learned

Companion to `ticketing-v2.11.md`. Each WP records (a) what shipped,
(b) the cost surface (LOC, files touched), (c) lessons that survive
the WP (i.e. that should still be true in v2.13), and (d) deferred
follow-ups feeding the next backlog.

---

## v2.12-WP02 (B1) — `tests/helpers/source_lint.py` extracted

**Pre-state.** v2.11 closed seven independent source-shape lint
tests (WP02, WP08-a, WP08-b, WP09-a, WP09-b, WP10, WP11, WP12, WP15).
Each one re-implemented the same plumbing: file iteration with
`pycache` skipping, `ast.parse(path.read_text())` with SyntaxError
swallowed, `ast.walk` over `Call`/`Constant(str)`/`JoinedStr`, plus
(in WP08-a) the `unittest.mock._get_target` longest-importable-prefix
walk. The retrospective owed a helper.

**What shipped.**

- `tests/helpers/source_lint.py` — 5 public callables + 1
  dataclass (`PatchTargetResolution`):
  - `iter_source_files(root, *, allow_list, suffix)`
  - `parse_module(path)` — `None` on OSError/UnicodeDecode/SyntaxError
  - `iter_string_literals(tree)` — yields `(Constant, value)`
  - `iter_calls(tree, *, dotted_name)` — tail-attribute-chain match
  - `resolve_patch_target(target)` → `PatchTargetResolution` 3-state
    (`ok` / `unresolvable` / `skip` for environmental import crashes)
- `tests/helpers/test_source_lint.py` — 17 self-tests, each pinning a
  synthetic-bad scenario for the helper it targets (matches the
  established v2.11 self-test pattern).
- Six existing lint consumers migrated to use the helper
  (port-in-place — zero assertion changes):
  - `tests/test_legacy_status_sweep.py`
  - `tests/test_patch_string_resolution_lint_wp08.py`
  - `tests/test_text_cast_lint_wp08.py`
  - `tests/test_create_app_factory_lint_wp09.py`
  - `tests/test_conftest_env_audit_wp09.py`
  - `tests/test_alembic_constraint_name_lint_wp10.py`
  - `tests/test_mock_headers_lint_wp11.py`

**Cost surface.**

- Helper: 257 LOC total (191 non-blank, ~110 code, rest docstring) —
  well within the ≤120-code-LOC budget.
- Consumers: each lost 20–50 LOC of duplicated plumbing.
- Net repo: smaller total LOC across `tests/`.

**Lessons (carry into v2.13).**

1. **Conservative tail-attribute matching subsumes both bare-`Name`
   and `Attribute`-chain consumers.** `iter_calls(dotted_name="patch")`
   matches `patch(...)` AND `mock.patch(...)` AND
   `unittest.mock.patch(...)` because the helper checks that the chain
   *ends* with the target parts. The WP09-a lint deliberately wanted
   *only* the bare-`Name` form — it filters the helper's output
   post-hoc with a one-line `isinstance(node.func, ast.Name)` check.
   This pattern (helper yields the broader set, consumer narrows)
   stays clean and avoids per-consumer matching modes in the helper.
2. **`PatchTargetResolution` (frozen dataclass) is clearer than
   WP08-a's `(ok, detail_with_magic_prefix)` tuple.** The original
   used `detail.startswith("__SKIP__")` as a sentinel. The dataclass
   has explicit `ok` and `skip` booleans — semantically the same, but
   no one will accidentally not check the sentinel.
3. **The `suffix` parameter on `iter_source_files` doubles as a
   filename-suffix filter.** WP09-b only wants `conftest.py` files;
   passing `suffix="conftest.py"` makes the helper glob
   `*conftest.py`, which under `tests/` reduces to every conftest.
   Cheap reuse — no need for a separate `iter_conftests` helper.
4. **`dict.keys()` as an `allow_list`.** WP09's allow-list is a
   `dict[str, str]` keyed by relative path; the helper normalises
   `set(allow_list or ())`, so consumers pass `.keys()` directly
   with no conversion. Preserves the call-site shape.

**Latent issues found in migrated tests (documented, NOT fixed).**

None. Every consumer's assertion shape and test-count is identical
before/after migration; the diff is purely plumbing. Lessons rule:
if a latent issue had surfaced, it would have been deferred to a
future v2.12 WP — none did.

**Test deltas.**

- Backend baseline: 1297 P / 0 F / 5 skipped / 14 xfailed.
- v2.12-WP02 post: **1314 P / 0 F / 5 skipped / 14 xfailed**.
- Net delta: **+17 P** (exactly the helper self-tests in
  `test_source_lint.py`).

**Deferred / scope cut.**

- `tests/test_no_v1_deferred_mechanism_wp12.py` was a candidate but
  uses `ast.walk` over `FunctionDef`/`AsyncFunctionDef` rather than
  `Call`/`Constant(str)`/`JoinedStr`. The shared concerns are too thin
  (one-line `ast.walk(tree)` for FunctionDef) to justify migration
  noise. Left as-is.
- `_func_dotted_chain` could be exposed as public if a future
  consumer needs the chain directly. Keep private until a real second
  caller surfaces (v2.11 lesson: no premature abstraction).

---

## v2.12-WP03 (C1+C2) — ORM `to_dict()` ⊆ `*Read` schema contract pins

**Goal.** Pin v2.11 retrospective lesson #2: every ORM `to_dict()`
contract-matched against its `*Read` Pydantic schema, both narrowing
directions caught. New collected tests are parametrized one-per-pair
so failures point cleanly at the offender.

**Mapping (7 pinned pairs + 1 unmatched).**

- `Ticket` ↔ `TicketRead` (open, `extra="allow"`)
- `Project` ↔ `ProjectRead` (closed)
- `Sprint` ↔ `SprintRead` (closed)
- `Component` ↔ `ComponentRead` (closed)
- `ProjectMember` ↔ `ProjectMemberRead` (closed)
- `TicketWatcher` ↔ `TicketWatcherRead` (open)
- `TicketAttachment` ↔ `TicketAttachmentRead` (open)
- `TicketNotification` ↔ `TicketNotificationRead` — **unmatched**:
  schema replaces raw `actor_id`/`actor_type` with hydrated `PersonRef`;
  routes never serialize `to_dict()` directly. Documented and skipped.

**Polarity flip per pair.**

- **Closed schema** → `to_dict().keys() ⊆ model_fields.keys()`. Catches
  the WP07 failure mode (schema drops a key the ORM produces).
- **Open schema** → flip: every REQUIRED schema field must be in
  `to_dict()` output. Catches the inverse (ORM drops a required key).

Both directions are pinned; future PRs cannot silently shrink either
side without test failure.

**Latent narrowing bugs found.** None. All 7 collected pairs green
first run. `TicketRead`'s `extra="allow"` (added in v2.11-WP07) held;
the four closed Project/Sprint/Component/ProjectMember pairs were
already aligned via the v2.1-WP* original spec work.

**Cost surface.**

- New test file: 262 LOC (`tests/test_orm_to_dict_schema_subset_wp03.py`).
  No production changes; no conftest hooks (per WP rule #5).
- Per-pair runtime ~0.05s — pure attribute-set + dict-key reflection,
  no DB session.

**Lessons (carry into v2.13).**

1. **Polarity flip is load-bearing, not cosmetic.** Naively running
   `to_dict ⊆ schema` against an open schema is a tautology — the
   schema's `extra="allow"` accepts anything, so the subset never
   fails. The flip (`required_fields ⊆ to_dict`) is what catches the
   inverse narrowing direction on open schemas. A single-polarity
   lint would silently green on 3 of 7 pairs.
2. **Hydrated projection schemas need their own invariant.**
   `TicketNotificationRead` replaces FK columns with a hydrated
   `PersonRef`; the wire shape is intentionally non-equivalent to
   `to_dict()`. Trying to lint it with the same shape would produce
   false positives. Three projection patterns now in the codebase
   (notifications, activity feed, search arms) — if a fourth lands
   without its own wire-contract test, time for a generic
   "hydrated-projection contract" helper.
3. **No-DB ORM instantiation is a clean test idiom.** SQLAlchemy ORM
   instances accept plain attribute assignment without a session;
   `to_dict()` methods read attributes only. Factories that do
   `obj = Cls(); obj.field = ...` per column avoid the
   `seed_problem.py`-style fixture cascade for pure serialization
   contract tests. Reusable pattern for future contract pins.

**Test deltas.**

- Pre-WP03: 1314 P / 0 F / 5 skipped / 14 xfailed (v2.12-WP02 close).
- Post-WP03: **1321 P / 0 F / 5 skipped / 14 xfailed**.
- Net delta: **+7 P** — exactly one per parametrized pair.

**Deferred / scope cut.**

- `TicketNotification` hydrated-shape lint — different invariant,
  out of scope. Records pair as unmatched in diagnosis doc.
- Second-variant factories for `member_type='agent'` /
  `reporter_type='agent'` — current `to_dict()` returns `self.<type>`
  verbatim with no branching, so single-variant factory suffices.
  Add a second variant only when a `to_dict()` introduces a branch.

---

## v2.12-WP04 (A1, cluster 1 of 4) — Bare-FastAPI migration

**Scope.** Migrated 8 of 31 legacy WP09 allow-list entries to
`tests.helpers.app_factory.build_test_app()`:
`tests/e2e/test_otel_correlation_trace.py`,
`tests/e2e/test_search_transition_e2e.py`,
`tests/routes/test_admin_handle.py`,
`tests/routes/test_agent_accounts_admin.py`,
`tests/routes/test_agents_activity.py`,
`tests/routes/test_audit_log.py`,
`tests/routes/test_comment_mention_route.py`,
`tests/routes/test_notifications.py`.

**Result.** Allow-list shrinks 31 → 23. Suite at 1321 P / 0 F / 5 skipped /
14 xfailed — net **+0** vs WP02+WP03 baseline. No production code touched.

**Latent bugs found.** Exactly one, test-side, in
`test_otel_correlation_trace.py`:

1. The test installed an `io.StringIO` JSON-log handler on the root
   logger BEFORE calling the app factory. `create_app()` invokes
   `setup_json_logging()` which clears root handlers — the buf handler
   was wiped, so the assertion on the in-span log line failed. Fix:
   build the app first, install the buf handler second.
2. The test registered `@app.get("/echo")` AFTER `build_test_app()`.
   Production's SPA catch-all (`/{full_path:path}`) is added LAST inside
   `create_app()`, and FastAPI matches in registration order — so any
   route appended later is shadowed by the SPA index. Fix: register via
   `app.add_api_route(...)` then `app.routes.insert(0, ...)` to prepend.
   Renamed the probe path to `/_t_echo` for clarity.

**Heuristics for cluster 2-4.**

- If a test calls `app.add_middleware(...)`, check whether `create_app()`
  already installs that middleware — usually yes (CorrelationId,
  SecurityHeaders, Logging, AgentStep). Drop the inline `add_middleware`.
- If a test re-wires `app.add_exception_handler(...)` for known domain
  errors (`PermissionDeniedError`, `HandleTakenError`, etc.), check
  `app/main.py` — production already registers them. Drop the inline
  wiring.
- If a test iterates `app.routes.tickets.EXCEPTION_HANDLERS` and calls
  `add_exception_handler` for each — same deal, `create_app()` does that.
- If a test registers its own route on the migrated app, prepend it via
  `app.routes.insert(0, ...)` so the SPA catch-all doesn't shadow it.
- Custom log capture must be installed AFTER `build_test_app()` because
  `setup_json_logging()` clears root handlers.

**Diagnosis doc.**
`.claude/lessons-learned/v2.12-wp04-diagnosis.md` — per-file notes.

---

## v2.12-WP05 (A1 cluster 2) — bare-FastAPI migration, second batch

**Result.** Eight more legacy `FastAPI()`-builder tests migrated to
`tests.helpers.app_factory.build_test_app()`. Allow-list 23 → 15. Suite
unchanged at 1321 P / 0 F / 5 skipped / 14 xfailed (+0 net).

**Files migrated.**

- `tests/routes/test_notifications_wp25.py`
- `tests/routes/test_notifications_wp30.py`
- `tests/routes/test_page_t_adoption_wp06.py`
- `tests/routes/test_people_search.py`
- `tests/routes/test_projects_permissions.py`
- `tests/routes/test_projects_wp37.py`
- `tests/routes/test_project_wip_limits.py`
- `tests/routes/test_realtime_token.py`

**Dominant pattern this cluster.** Three of the eight files (`test_projects_permissions`,
`test_projects_wp37`, `test_project_wip_limits`) open-coded the same boilerplate:
loop `app.routes.tickets.EXCEPTION_HANDLERS` calling `add_exception_handler`,
then re-register `PermissionDeniedError` with a lambda returning
`JSONResponse(403, {"detail": ...})`. Production already wires both in
`app/main.py` (PermissionDeniedError at line 188, EXCEPTION_HANDLERS loop at
line 265), with the richer `{"error": {...}}` envelope. Dropping the inline
duplicates produced the canonical envelope for free; all assertions in those
files were status-code only, so no body-shape regression.

**Latent bugs found.** None. No prod-side patches. No xfail deferrals.

**Heuristics that paid off.** WP04 heuristic #3 (drop redundant inline
exception handlers) was the only one needed — three files matched it
exactly. The SPA-catch-all-shadow risk (heuristic #1) and the
log-handler-ordering risk (heuristic #2) did not surface in this cluster.

**Conftest env audit (G5).** Checked `tests/test_conftest_env_audit_wp09.py`
— no cluster-2 file referenced. No follow-up.

**Diagnosis doc.**
`.claude/lessons-learned/v2.12-wp05-diagnosis.md` — per-file notes.

---

## v2.12-WP06 (A1 cluster 3) — bare-FastAPI migration, third batch

**Result.** Eight more legacy `FastAPI()`-builder tests migrated to
`tests.helpers.app_factory.build_test_app()`. Allow-list legacy entries
14 → 6 (total entries 21 → 13). Suite unchanged at
1321 P / 0 F / 5 skipped / 14 xfailed (+0 net).

**Files migrated.**

- `tests/routes/test_realtime_ws.py`
- `tests/routes/test_response_model_adoption_wp07.py`
- `tests/routes/test_search_v2.py`
- `tests/routes/test_search_v2_cursors.py`
- `tests/routes/test_search_v2_filters.py`
- `tests/routes/test_ticket_activity_cursor.py`
- `tests/routes/test_tickets_column_counts.py`
- `tests/routes/test_tickets_ordering.py`

**Dominant pattern this cluster.** Three of the eight files
(`test_ticket_activity_cursor`, `test_tickets_column_counts`,
`test_tickets_ordering`) open-coded the `for exc_cls, handler in
EXCEPTION_HANDLERS.items(): app.add_exception_handler(...)` loop —
matching WP04 heuristic #3 and the WP05 pattern exactly. The remaining
five were straight-swap (helper call + dependency_overrides dict).

**Latent bugs found.** None. No prod-side patches. No xfail deferrals.

**Heuristics that paid off.** WP04 #3 (drop redundant `EXCEPTION_HANDLERS`
inline loop) appeared in three files. WP04 #1 (SPA catch-all shadow) and
#2 (log-handler ordering) did not surface — none of the cluster-3 files
add their own routes or log handlers after `build_test_app()`.

**Notable detail.** `test_search_v2_cursors.py` asserts on
`json()["detail"]` for the tampered-cursor 400 case. This still passes
under the real wiring because the search route raises a plain
`HTTPException(400, detail=...)` which FastAPI's default handler keeps
in `{"detail": ...}` shape — it doesn't flow through the central
`AppError` envelope. The `test_ticket_activity_cursor.py` invalid-cursor
case, by contrast, goes through `AppError` and asserts on
`body["error"]["code"]`, which now resolves because `create_app()` wires
the central handler. Both pass with no test-side edits.

**Conftest env audit (G5).** Checked `tests/test_conftest_env_audit_wp09.py`
— no cluster-3 file referenced. No follow-up.

**Diagnosis doc.**
`.claude/lessons-learned/v2.12-wp06-diagnosis.md` — per-file notes.

---

## v2.12-WP07 (A1 cluster 4, FINAL) — bare-FastAPI migration backlog closed

**Pre-state.** Six legacy bare-FastAPI route-test files remained on the
WP09 allow-list. Total entries 13 (6 legacy + 7 permanent by-design).

**What shipped.**

- 6 route-test files migrated to `build_test_app()`:
  - `tests/routes/test_tickets_pagination.py`
  - `tests/routes/test_tickets_routes.py`
  - `tests/routes/test_transitions_endpoint.py`
  - `tests/routes/test_users_handle.py`
  - `tests/routes/test_watchers_wp41.py`
  - `tests/routes/test_ws_tickets.py`
- `tests/test_create_app_factory_lint_wp09.py` allow-list: 13 → 7
  entries. The "Route-test legacy callers — predate the WP09 helper.
  Migration is a follow-up" comment block was removed entirely; the
  header docstring + inline contract comment rewritten to declare the
  list a **closed set** of by-design exceptions.

**Dominant pattern this cluster.** Four of the six (`pagination`,
`routes`, `transitions_endpoint`, `watchers_wp41`) open-coded the same
`for exc_cls, handler in EXCEPTION_HANDLERS.items()` loop as the WP05
and WP06 files — total 10 instances across WP05..WP07.
`test_users_handle.py` is the only file in the four-cluster sweep
where the inline handlers were *functionally* different (not just a
copy of `EXCEPTION_HANDLERS`): it open-coded three custom handlers
(409 / 429 / 422) for `HandleTakenError` / `HandleChangeTooSoonError`
/ `ProfaneHandleError` that pre-dated their migration into
`app.main.create_app()`. Behaviour is unchanged — production wires
the same three handlers with the same status codes and the same
`detail` / `next_allowed_at` body shape.

**Latent bugs found.** None. No prod-side patches. No xfail
deferrals. Final tally: **1321 passed, 5 skipped, 14 xfailed**
(+0 net vs WP06 baseline, +0 net vs WP04 baseline).

**Closed-backlog semantic shift.** The allow-list is no longer a
running TODO list; it's a contract documenting *why* a specific test
must not boot via `create_app()`. New entries are now exceptional and
must justify their addition on those grounds — there is no
"follow-up: migrate" escape hatch. This is the v2.11 backlog closure
that v2.11-WP16's retrospective queued for v2.12.

**Cumulative WP04..WP07.** 22 legacy bare-FastAPI route-test files
migrated; zero production patches; zero test regressions; suite
totals unchanged from the WP02 baseline (1321 P / 0 F). The
`EXCEPTION_HANDLERS`-inline-loop and the central-handler-duplication
patterns are now both gone from the test corpus.

**Heuristics that paid off.** WP04 #3 (drop redundant
`EXCEPTION_HANDLERS` inline loop) — 4 hits. New: detect inline
*custom* exception handlers that have since landed on the central
factory; drop those too (1 hit in `test_users_handle.py`). WP04 #1
(SPA shadow) and #2 (log-handler ordering) did not surface — none
of the cluster-4 files add their own routes or log handlers after
`build_test_app()`.

**Conftest env audit (G5).** Checked
`tests/test_conftest_env_audit_wp09.py` — no cluster-4 file
referenced. No follow-up.

**Diagnosis doc.**
`.claude/lessons-learned/v2.12-wp07-diagnosis.md` — per-file notes +
the closed-set rationale for `_ALLOWLIST`.

---

## WP09 — Exception envelope unification (E1)

**Outcome.** Every error response now ships the same envelope:
`{"error": {"code", "message", "correlation_id", "details"}}`. The
legacy `{"detail": ...}` shape is gone from the app surface
(production code AND tests). Frontend gets an additive `parseApiError`
adapter that tolerates both shapes for transitional safety.

**Backend.** 1320 → 1342 (+21 contract tests, +1 retargeted assertion
on `next_allowed_at` location). 0 failures, 5 skipped, 14 xfailed.

**Frontend.** 236 unchanged.

**Single source of truth.** `app/errors_envelope.py` exports
`build_error_envelope(...)` and `current_correlation_id()`. Every
handler in `app/main.py::create_app` now flows through it; the
per-class tickets handlers in `app/routes/tickets.py` already did. No
module-local `add_exception_handler` calls were duplicating the
central registration — only `create_app` registers handlers — so the
WP05 dead-entry pattern stayed clean here.

**New global handlers.** `HTTPException` (wraps FastAPI default into
`code="http_error"`) and `RequestValidationError` (wraps Pydantic
body/query errors into `code="validation"` with `details.errors`).
Pydantic errors required `jsonable_encoder` because
`exc.errors()[*]["ctx"]["error"]` is a `ValueError` instance, not
JSON-serialisable.

**Correlation id.** Sourced from the existing
`app.middleware.logging._correlation_id_ctx` contextvar (populated by
`CorrelationIdMiddleware`), NOT from the response header (which is
written on the way out, too late for a handler to read). Empty
contextvar → JSON `null`, not a fabricated id.

**Heuristics that paid off.**
1. *Splice at front of `app.router.routes`* — the WP07 SPA-catch-all
   trick still works for the contract test; using `Route(...)` from
   `starlette.routing` directly sidesteps the WP09
   bare-`FastAPI()` lint without an allow-list entry.
2. *Tickets handlers already emit the unified envelope* — keep them;
   only the central `AppError` / `services-exceptions` / `HTTPException`
   / `RequestValidationError` paths needed rewriting.

**Frontend adapter.** Additive only. `frontend/src/api/errors.ts`
exposes `parseApiError(response, body) → {code, message,
correlation_id, details, status}`. Accepts both envelope shapes.
Wired into `users.ts::updateMyHandle` (preserving the
`UpdateHandleError.detail` / `.next_allowed_at` contract for
`Settings.tsx`) and `auditLog.ts::listAuditLog`. ~20+ remaining call
sites still parse ad-hoc; deferred to v2.13.

**Diagnosis doc.**
`.claude/lessons-learned/v2.12-wp09-diagnosis.md` — AppError class
inventory + per-class code mapping + before/after envelope contract.

---

## WP10 — Snapshot-total UI banner + Refresh count button (A3+A4)

**Goal.** Surface the v2.11-WP14 cursor `total_authority` flag in the
Search UI. When a user paginates past page 1 on a single-arm tab, the
displayed `total` is still the snapshot pinned at cursor-mint time —
not a live count of the matching set. Give the user a clear signal
("Showing snapshot count") and a one-click way to force a re-count
via `refresh_total=1`.

**Hook (`frontend/src/hooks/useSearchV2.ts`).**

- New return-shape fields:
  - `refreshTotal: () => void` — zero-arg; flips an internal
    `refreshPendingRef` and bumps a `refreshNonce` state. The existing
    fetch effect picks up the nonce, reads the ref once, and passes
    `refresh_total: true` through to `searchV2`. Cursor stack is
    **not** touched — refresh is a count operation, not navigation.
  - `totalAuthority: "snapshot" | "live" | null` — derived from
    `activeArm.total_authority`. Absent values default to
    `"snapshot"` (matches the API client contract for older
    backends). Returns `null` for `entity=all` (per-arm semantics
    don't combine across arms; the All tab is opt-out by design).
- The pending-ref pattern matters: it ensures that args-driven
  refetches (query change, filter toggle, cursor advance) do **not**
  inherit `refresh_total`. Only the explicit user click sticks for
  exactly one fetch.

**Page (`frontend/src/pages/Search.tsx`).**

- Banner rendered above the loader (so the "Refreshing…" disabled
  state is visible during the refresh fetch). Conditions:
  `activeTab !== "all"` && `hasPrev` && `totalAuthority === "snapshot"`.
- One-shot semantics: if the server returns `snapshot` again (e.g.
  because the reconciliation worker hasn't caught up), the banner
  persists; no auto-retry.
- `role="status"` + `aria-live="polite"` for assistive tech.

**CSS (`frontend/src/pages/Search.css`).**

- Minimal additive `.search-snapshot-banner` block — left-edge
  `4px solid var(--color-info)` to match the existing info-pill
  idiom (App.css l.475).

**Tests added (5 net).**

Hook (10 total, was 8):
- `WP10: refreshTotal preserves the cursor and re-fires with refresh_total=true`
- `WP10: totalAuthority reflects the active arm's value and is null for entity=all`

Page (25 total, was 22):
- `WP10: snapshot banner renders after advancing past page 1 on a single-arm tab`
- `WP10: clicking Refresh count fires searchV2 with refresh_total=true and banner clears on live response`
- `WP10: snapshot banner is hidden on the All tab`

**Test totals.** Backend untouched at 1342 P / 0 F / 5 skipped /
14 xfailed. Frontend 241 P / 0 F (was 236, Δ +5).

**Deferred.** A5 — per-arm `refresh_total` on `entity=all`. The All
tab currently shows aggregate previews with no cursor stack and
`totalAuthority` returns `null`. Surfacing a per-arm refresh there
would require either multi-cursor stacks or arm-scoped banners;
deferred until product confirms the All tab needs the guardrail.

**Diagnosis doc.**
`.claude/lessons-learned/v2.12-wp10-diagnosis.md`.

---


## v2.12-WP11 (Bucket C3) — OpenAPI ↔ frontend TS parity lint

**Goal.** Generalise the v2.11-WP07 / WP06 schema pin so that *every*
named response model in `app.main:app.openapi()` for an in-scope route
must agree (field-set) with the matching TypeScript response interface
in `frontend/src/api/*.ts`. Drift fails CI rather than waiting for a
runtime bug.

**Polarity.**
- Closed OpenAPI schema (no `extra="allow"`) AND TS has no
  `[k: string]: unknown` → OpenAPI ⊆ TS. Missing TS field fails.
- Either side permissive → REQUIRED-TS ⊆ OpenAPI. (Backend can emit
  arbitrary extras; only the strictly-required TS contract is pinned.)
- A synthetic-bad self-test exercises the polarity direction so a
  silent parser regression cannot disable the lint.

**In-scope routes (9).** `ProjectRead`, `ProjectMemberRead`,
`ComponentRead`, `SprintRead`, `PeopleSearchResponse`,
`UserHandleResponse`, `TicketCommentRead`, `TicketLinkRead`,
`TicketNotificationRead`. Skipped (documented): `TicketRead`/`TicketDTO`
(both sides permissive — WP07 already pins wiring), `Page_*` /
`CursorPage_*` / `ActivityPage` (generics + discriminated unions exceed
the flat-interface parser), `SearchV2Response` / `SearchArm` /
`SearchItem` (catch-all index signature + permissive),
`AuditLogEntryRead` (JSON-only smoke tests in
`tests/routes/test_audit_log.py` already pin the inner shape).

**Parser bug found.** The previous-agent regex
`^export\s+(?:interface|type)\s+(?P<name>\w+)\b[^{]*\{` had two latent
defects:

1. `^export` (MULTILINE) doesn't match indented synthetic fixtures, so
   all three parser self-tests blew up with `FakeResp: not found in
   source`.
2. `[^{]*` matches across newlines, so
   `export type SprintState = "planned" | "active" | "closed";`
   followed by `export interface SprintDTO { ... }` produced a single
   regex match starting at `SprintState` and consuming through the
   `{` of `SprintDTO` — `finditer` then never offered `SprintDTO` for
   inspection, raising a false-positive `not found in source` drift.

Fixed with a single regex change to `^\s*export ... [^{;]*\{`. Chose
to fix the parser rather than the fixtures because the parser is the
production artifact and indentation-tolerance / union-alias-tolerance
are properties it ought to have anyway.

**Real drifts found and fixed.**
- `ProjectMemberDTO` (in `frontend/src/api/projects.ts`) was missing
  `created_at`. Pydantic `ProjectMemberRead` declares
  `created_at: datetime`. Added `created_at: string` (required).
  Note: the TS-side `added_at` field is dead — kept it for backward
  compat since closed schemas allow extra-TS fields.
- `ComponentDTO` was missing `updated_at`. Added
  `updated_at?: string | null` to match `ComponentRead.updated_at:
  datetime | None = None`.

No backend Pydantic schemas were touched — the lint's purpose is to
catch *frontend* drift against the (authoritative) backend contract.

**Test totals.**
- Backend: 1354 passed / 5 skipped / 14 xfailed (was 1342, Δ +12: 3
  parser self-tests + 9 parametrised parity cases).
- Frontend: 241 passed (Δ 0 — additive DTO changes only).

**Skipped / deferred.** None. After the parser fix, every in-scope
parametrised case passes — no `pytest.mark.skip` escape-hatch was
needed.

**Diagnosis doc.**
`.claude/lessons-learned/v2.12-wp11-diagnosis.md`.

---

## v2.12 retrospective

### Headline numbers

- **Backend baseline:** 1297 P / 0 F / 5 skipped / 14 xfailed (v2.11 close).
- **Backend final:** **1354 P / 0 F / 5 skipped / 14 xfailed**.
- **Net delta:** +57 tests across 10 shipped WPs (WP02..WP07, WP09..WP11
  — WP08 deferred). Mix: +17 source-lint self-tests (WP02), +7 ORM/schema
  contract pairs (WP03), +21 envelope-contract tests (WP09), +12 OpenAPI
  parity (WP11). The WP04..WP07 migration cluster netted +0 by design —
  factory swap, not new coverage.
- **Frontend:** 236 → **241 P / 0 F**. +5 from the WP10 Search snapshot
  banner + refresh button (3 page tests + 2 hook tests).
- **Production regressions introduced:** zero. Every WP held the
  green-suite invariant across its merge gate.

### WPs shipped

| WP | Bucket | Summary | Test delta |
| --- | --- | --- | --- |
| WP01 | G0 | Baseline verify (1297 P backend / 236 P frontend). | ±0 |
| WP02 | B1 | `tests/helpers/source_lint.py` extracted + 7 lint consumers migrated. | +17 (1297→1314) |
| WP03 | C1+C2 | ORM `to_dict()` ⊆ `*Read` schema contract pins (7 pairs + 1 unmatched). | +7 (1314→1321) |
| WP04 | A1 (1/4) | Migrated 8 bare-`FastAPI()` tests; allow-list 31→23. Found log-handler-ordering + SPA catch-all shadow bugs in `test_otel_correlation_trace.py`. | +0 (1321) |
| WP05 | A1 (2/4) | Migrated 8 more; allow-list 23→15. Dropped 3 redundant inline `EXCEPTION_HANDLERS` loops + `PermissionDeniedError` re-registrations. | +0 (1321) |
| WP06 | A1 (3/4) | Migrated 8 more; allow-list legacy 14→6 (total 21→13). 3 more inline-loop drops. | +0 (1321) |
| WP07 | A1 (4/4) | Final 6 legacy migrations; allow-list CLOSED at 7 permanent-by-design entries. "follow-up: migrate" comment block removed. v2.11-WP09 backlog fully closed. | +0 (1321) |
| WP08 | A2 | **DEFERRED to v2.13.** `ck` naming_convention resurrection — scope was larger than seed estimated (every alembic migration's `CheckConstraint(name="ck_...")` needs sweeping, not just `app/models/`). Partial changes safely reverted. | n/a |
| WP09 | E1 | Unified exception envelope across the app: single `{"error": {code, message, correlation_id, details}}` shape. New `app/errors_envelope.py`; global `HTTPException`/`RequestValidationError`/`AppError` handlers in `create_app()`. 21 contract tests + assertion ports in 6 files. Frontend `parseApiError` adapter + 2 call-site updates. | +21 (1321→1342) |
| WP10 | A3+A4 | Snapshot-total UI banner + Refresh count button on Search. `useSearchV2.refreshTotal()` preserves cursor stack via pending-ref pattern. | +0 backend / +5 frontend (236→241) |
| WP11 | C3 | OpenAPI ↔ frontend TS type-completeness lint. Found 2 real drifts (`ProjectMemberDTO.created_at`, `ComponentDTO.updated_at`) — both fixed. Parser regex bug fixed (false positive on `export type X = "a"|"b";` swallowing next interface). | +12 (1342→1354) |

### Production bugs caught

1. **WP04** — `test_otel_correlation_trace.py` installed an
   `io.StringIO` JSON-log handler on the root logger BEFORE calling the
   app factory; `create_app()` invokes `setup_json_logging()` which
   clears root handlers. The buf handler was wiped silently — the
   in-span log assertion would have green-passed under the bare-rig
   path but failed against the real rig. Test-side bug, surfaced only
   because the migration ran the test through the real factory.
2. **WP04** — same file registered `@app.get("/echo")` AFTER
   `build_test_app()`. Production's SPA catch-all
   (`/{full_path:path}`) is added LAST inside `create_app()`, and
   FastAPI matches in registration order — any test route appended
   later is shadowed by the SPA index. Fix: prepend via
   `app.routes.insert(0, ...)`. Same shape as the v2.11-WP11 finding;
   a second instance of the same pattern under the same migration.
3. **WP09** — `correlation_id` was initially read from the response
   header inside the handler. Headers are written on the way out
   (after the handler returns), so a handler reading the header sees
   nothing. Re-sourced from `app.middleware.logging._correlation_id_ctx`
   (the contextvar populated by `CorrelationIdMiddleware` at request
   entry). Empty contextvar serialises JSON `null` rather than a
   fabricated id.
4. **WP05/WP06/WP07** — 10 test files across three clusters open-coded
   a `for exc_cls, handler in EXCEPTION_HANDLERS.items()` loop that
   duplicated what `create_app()` already wires. None of the inline
   versions emitted the unified envelope (they returned bare
   `JSONResponse({"detail": ...})`). Production code was always
   correct; the tests were silently asserting against a stale
   handler-set. Dropped inline registrations across all 10.
5. **WP07** — `test_users_handle.py` open-coded three *functionally*
   different inline handlers (409 / 429 / 422) for
   `HandleTakenError` / `HandleChangeTooSoonError` /
   `ProfaneHandleError` that had since migrated into
   `create_app()`. Behaviour identical, but the test was asserting
   against the *bare-rig* copy — a future production-side change
   would not have surfaced in CI.
6. **WP11** — `ProjectMemberDTO` (`frontend/src/api/projects.ts`)
   was missing `created_at`. Pydantic `ProjectMemberRead` declares
   `created_at: datetime`. Real cross-stack contract drift, fixed by
   adding `created_at: string` (required) on the TS side.
7. **WP11** — `ComponentDTO` was missing `updated_at`. Real drift,
   fixed by adding `updated_at?: string | null`.
8. **WP11 (meta)** — the parity-parser regex `[^{]*\{` matched across
   newlines and silently consumed `export type SprintState = "..."|
   "...";` into the next interface's brace. `finditer` then never
   offered `SprintDTO` for inspection and raised a false-positive
   `not found in source` drift. Lint-tool bug; would have hidden any
   future `SprintDTO` real drift. Fixed by anchoring the parser
   regex on `[^{;]*\{`.

### Cross-cutting lessons

1. **Closed-backlog over open-backlog for legacy lint allow-lists.**
   The WP09 allow-list ran for an entire version cycle as a TODO list
   with a "follow-up: migrate" escape hatch. v2.12-WP07 closed it by
   semantically reinterpreting the residue: the remaining 7 entries
   are **by-design exceptions** (factories that intentionally skip
   the real middleware/handler stack for protocol-level testing). The
   comment block was rewritten to make new entries exceptional rather
   than promised. Lesson: when a migration finishes, flip the
   semantics of the allow-list at the same commit — if you leave it
   as "follow-up", the next migration cycle inherits the ambiguity.
2. **`source_lint.py`'s "broad helper, narrow consumer" pattern is a
   keeper.** `iter_calls(dotted_name=...)` matches `f(...)`,
   `mod.f(...)`, and `pkg.mod.f(...)` — consumers that want only the
   bare-`Name` form filter post-hoc with a one-line `isinstance` check.
   No per-consumer matching modes leaked into the helper. Generalises:
   the helper yields the superset, consumers narrow at the call site.
3. **Polarity flip is load-bearing on contract subset tests.** WP03's
   open-vs-closed polarity is not cosmetic: a naive `to_dict ⊆ schema`
   greens silently on every `extra="allow"` schema. The inverse
   (`required_fields ⊆ to_dict`) is the active invariant on open
   schemas. Half-pinned contract suites are silent green sinks; any
   future contract pin must enumerate both directions explicitly.
4. **Snapshot-vs-live count UX needs a *one-shot* refresh primitive,
   not a flag.** WP10's `refreshTotal()` flips an internal
   `refreshPendingRef` that the next fetch consumes exactly once. Naive
   designs ("pass `refreshTotal: true` everywhere until the user clears
   it") inherit the flag across cursor navigation, filter toggles, and
   query edits — defeats the snapshot's whole purpose. Pending-ref
   pattern is now the reference shape for "transient request-level
   override" UI primitives.
5. **`correlation_id` is contextvar-shaped, not header-shaped.**
   Anything inside the request lifecycle that needs the id (log
   structuring, error envelopes, audit calls) must read the
   contextvar set by `CorrelationIdMiddleware` at request entry. The
   response header is for the *client*, not for in-process handlers.
   WP09's first cut got this wrong; the fix is a one-liner but the
   bug class is recurring.
6. **Tooling lints need self-tests covering their parser, not just
   their assertions.** WP11's TS-parser regex would have silently
   passed every comparison if the parser swallowed all DTOs into one
   match. Three synthetic-bad self-tests (indented input,
   union-typed alias, simple flat interface) made the parser bug
   surface immediately. New lints owe ≥2 parser self-tests AND their
   assertion self-test — three minimum.
7. **The "rename across migrations" sweep is broader than the source
   tree suggests.** WP08 was scoped on `app/models/`; actual surface
   included every alembic migration file that mentioned the legacy
   `name="..."` form. The seed underestimated by ~3x. Lesson for
   v2.13: scope rename WPs by `grep -rn` of the symbol across `app/`
   AND `alembic/`, not by the model-file count alone.
8. **Migration-batch heuristics compound across clusters.** WP04
   recorded 3 heuristics (log-handler ordering, SPA shadow, redundant
   handler loop); WP05/06/07 reused #3 ten times. Cluster 1 was
   slower than cluster 4 by ~2x — heuristic accrual is the
   compounding artifact. New refactor batches owe a heuristic log on
   the first cluster, even if the batch is only 2 clusters deep.

### What stayed deferred (carry to v2.13)

- **WP08 (A2)** — `ck` naming_convention key resurrection. Sweep
  scope now better-understood: every `app/models/` `CheckConstraint`
  + every `alembic/versions/*.py` `CheckConstraint(name=...)` →
  short-name (or `op.f(...)`) form, plus a live-DB rename migration.
  Budget one WP with explicit pre-flight `grep` to enumerate.
- **WP09 frontend tail** — ~20 frontend call sites still parse
  errors ad-hoc (raw `await response.json()` + `.detail` access).
  Migrate to `parseApiError`. Mechanical sweep; no behaviour change.
- **C7** — `decode_email_body` helper. No second QP-wrap consumer.
- **E3** — KindPill 7th surface. No new consumer.
- **E4** — `useSearchV2` ergonomic follow-ups. No second consumer.
- **F3** — TipTap second-consumer extraction. No second editor surface.
- **A5 (from v2.11-WP14 seed)** — per-arm `refresh_total` semantics on
  `entity=all`. WP10 deferred this; product call needed on whether
  per-arm opt-in or all-arms-or-none is the right invariant.

### Files touched (rough stats)

- **Production code (`app/`):** ~6 files. New: `app/errors_envelope.py`
  (WP09). Modified: `app/main.py` (WP09 handler wiring),
  `app/routes/tickets.py` (WP09 envelope alignment). Untouched by
  WP04–WP07 (migration was test-side only).
- **Test code (`tests/`):** ~30 files. New: `tests/helpers/source_lint.py`
  + self-tests (WP02), `tests/test_orm_to_dict_schema_subset_wp03.py`
  (WP03), `tests/test_error_envelope_contract_wp09.py` + related
  (WP09), `tests/test_openapi_ts_parity_wp11.py` (WP11). Modified:
  22 `tests/routes/*` and `tests/e2e/*` files for `build_test_app()`
  migration (WP04–WP07), 6 files for WP09 assertion ports, 7 lint
  consumers for WP02 helper migration.
- **Frontend (`frontend/`):** ~6 files. New: `frontend/src/api/errors.ts`
  (WP09 adapter). Modified: `frontend/src/hooks/useSearchV2.ts`,
  `frontend/src/pages/Search.tsx`, `frontend/src/pages/Search.css`
  (WP10); `frontend/src/api/users.ts`, `frontend/src/api/auditLog.ts`
  (WP09 partial wire-up); `frontend/src/api/projects.ts`,
  `frontend/src/api/components.ts` (WP11 drift fixes).
- **Docs (`.claude/lessons-learned/`):** 9 new per-WP diagnosis files
  (`v2.12-wp02-diagnosis.md` through `v2.12-wp11-diagnosis.md`,
  skipping WP08) + this retrospective.

---

## v2.13 starting prompt seed

v2.12 closed 8 of 12 planned items. The two clean deferrals are
WP08 (A2) `ck` naming_convention resurrection — now better-scoped
after the failed attempt — and the WP09 frontend tail (~20 call
sites still parsing errors ad-hoc). v2.13 picks both up, continues
the contract-pin pattern in the request direction (Pydantic
`*Create`/`*Update` ↔ ORM accepts), and decides A5's per-arm
`refresh_total` semantics. The four conditional v2.11 carry-forwards
(C7, E3, E4, F3) remain pending a triggering need.

### v2.13 backlog

#### Bucket A — v2.12 carry-forwards

A1. **WP08 (A2) — `ck` naming_convention resurrection.** Short-name
    port for every `CheckConstraint(name="...")` in `app/models/` AND
    every `alembic/versions/*.py` migration file; then a live DB
    rename migration that pre-renames existing constraints to their
    `ck_%(table_name)s_%(constraint_name)s` form before the
    convention flips on. One WP, one migration. Pre-flight:
    `grep -rn 'CheckConstraint(name=' app/ alembic/` and budget by
    the resulting count, not by the model-file count.

A2. **Migrate the ~20 remaining frontend call sites to
    `parseApiError`.** Grep `await response.json()` and `\.detail\b`
    inside `frontend/src/api/`; replace ad-hoc shape parsing with
    the adapter. Mechanical; no behaviour change. Closes the WP09
    frontend tail.

#### Bucket B — New initiatives

B1. **Per-arm `refresh_total` semantics for `entity=all`.**
    v2.11-WP14 + v2.12-WP10 deferred this. Decide: (a) per-arm
    opt-in cursor field, or (b) all-arms-or-none. (b) is cheaper;
    (a) is the right UX if any arm independently warrants a count
    refresh. Product call required; document the decision in the
    diagnosis doc.

B2. **Expand WP11 lint coverage.** Currently skipped:
    `Page_*` / `CursorPage_*` / `ActivityPage` (generics),
    `SearchV2Response` / `SearchArm` / `SearchItem` (union/
    discriminated). Extend the parser to handle `Page<T>` generic
    flatten + tagged-union shapes. Adds parity coverage to the
    largest still-unpinned schemas.

B3. **Apply WP03's contract pattern to the request side.** Every
    Pydantic `*Create`/`*Update` schema covered by a superset/subset
    invariant against the ORM constructor accepting it (or against
    the service-layer `update_*` accepting it). Catches the inverse
    of WP03's narrowing: the ORM dropping a field that the schema
    still emits. Audit count first; ~10–15 pairs expected.

#### Bucket C — Conditional (carry from v2.11)

C1. **C7 — `decode_email_body` helper.** Pick up only on a second
    QP-wrap consumer.
C2. **E3 — KindPill 7th surface.** Pick up when a real consumer
    surfaces.
C3. **E4 — `useSearchV2` ergonomic follow-ups.** Pick up when a
    second consumer surfaces.
C4. **F3 — TipTap second-consumer extraction.** Pick up when a
    second editor surface lands.

### v2.13 prompt seed (paste-ready)

> Proceed with v2.13 of the problem-bulletin ticketing system. v2.12
> retrospective + carry-forward backlog live at the bottom of
> `.claude/lessons-learned/ticketing-v2.12.md`. Baselines: backend
> **1354 P / 0 F / 5 skipped / 14 xfailed**, frontend **241 P / 0 F**.
> Default work order: Bucket A (v2.12 carry-forwards: WP08 `ck` key
> resurrection + WP09 frontend tail) → Bucket B (per-arm
> `refresh_total`, WP11 lint expansion, request-side contract pins) →
> Bucket C (conditional). Follow the sequential subagent loop pattern,
> TDD-first, one diagnosis doc per WP under
> `.claude/lessons-learned/v2.13-wpNN-diagnosis.md`. Append lessons to
> `.claude/lessons-learned/ticketing-v2.13.md`. Pre-flight any rename
> WP with `grep -rn` across `app/` AND `alembic/` before scoping. Do
> NOT reintroduce the `_v1_deferred.py` skip-hook — per-test deferral
> uses plain pytest markers.

