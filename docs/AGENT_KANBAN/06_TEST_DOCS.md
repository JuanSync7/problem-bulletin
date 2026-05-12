# Agent Kanban — Test Plan

| Field | Value |
|-------|-------|
| Status | Ready |
| Subsystem | Agent Kanban (evolution of Aion Bulletin) |
| Last updated | 2026-05-12 |
| Spec | `docs/AGENT_KANBAN/01_SPEC.md` |
| Design | `docs/AGENT_KANBAN/04_DESIGN.md` |
| Implementation | `docs/AGENT_KANBAN/05_IMPLEMENTATION.md` |

This document is the test planning source-of-truth for the Agent Kanban subsystem. It defines, per module, the scenarios to test, the test type (unit / integration / e2e), the FR/AC each scenario covers, and the fixtures / infrastructure required. Test **bodies** are deferred to `/write-module-tests`; this doc defines *what* must be tested, not *how* the assertions are written.

---

## 0. Testing Philosophy

| Principle | Application |
|----------|-------------|
| **Real DB over mocks** | All service-layer and route tests run against a real Postgres 16 instance via `pytest-postgresql` or a session-scoped docker container fixture. SQLAlchemy is never mocked. Audit / OCC / hierarchy-aware behavior is invisible without real Postgres semantics (row locks, generated columns, GIN indexes, RAISE on REVOKE). |
| **Mocks only at the edge** | The only mockable surfaces are: (a) OTel exporter (an in-memory `InMemorySpanExporter`), (b) the WebSocket subscriber set (a test double `Broadcaster` that captures emitted envelopes), and (c) outbound HTTPX clients (none in this MVP). Everything else is real. |
| **Audit invariant verified by construction** | Every service-level write test asserts that exactly one matching `audit_log` row exists for the operation, joined on `correlation_id`. This is automated via a `pytest` fixture (`assert_audit_row(...)`). |
| **Concurrency tested with real contention** | OCC, claim, and epic-close scenarios use `asyncio.gather` across N independent sessions on the same database. ≥10-writer scenarios are mandatory (NFR-900 / AC-900). Single-threaded "simulated conflict" tests are insufficient and explicitly disallowed for the conflict requirements. |
| **Trace correlation tested as a data property** | The `correlation_id` returned to the caller MUST equal the OTel `trace_id` recorded in the audit row, the broadcast envelope, and the structured log line for that request. This is tested as a property — sample N random requests, assert all five carriers carry the same ID. |
| **Frontend kanban tested at component + e2e levels** | Component-level tests use Vitest + React Testing Library. Drag-and-drop and WS reconciliation are tested end-to-end via Playwright against the real backend. |

---

## 1. Test Infrastructure

### 1.1 Fixtures (`tests/conftest.py` extensions)

| Fixture | Scope | Purpose |
|---------|-------|---------|
| `pg_url` | session | Spins up a Postgres 16 container (or uses `TEST_DATABASE_URL` if set in CI). |
| `db_engine` | session | Async SQLAlchemy engine pointing at `pg_url`; runs alembic upgrade to head before yielding. |
| `db_session` | function | Per-test `AsyncSession` wrapped in a SAVEPOINT that rolls back on teardown (transactional isolation). |
| `db_session_factory` | function | Returns a factory producing independent sessions, for concurrent-write scenarios (cannot share a single SAVEPOINT). |
| `seeded_project` | function | Creates a `projects` row with `key_prefix='TKT'` and the default board column flow. |
| `human_actor` / `agent_actor` | function | Returns `Actor` dataclasses; agent variant inserts an `agent_accounts` row and returns the matching identity. |
| `broadcaster_spy` | function | Replaces `app.services.delivery.broadcast` with a list-capture; assertions are made on `broadcaster_spy.events`. |
| `otel_memory_exporter` | session | In-memory `InMemorySpanExporter` registered as the active exporter; reset per test. |
| `assert_audit_row` | function | Helper: `assert_audit_row(db, entity_id, action, actor_id) -> AuditRow`; asserts exactly one match. |
| `mcp_client` | function | `httpx.AsyncClient` pre-authenticated as an agent against the mounted `/mcp` sub-app. |
| `ws_client` | function | `httpx_ws` async client authenticated via human session cookie. |

### 1.2 Layout

```
tests/
├── conftest.py                       (extended)
├── migrations/                       (alembic-level — A1..A9 invariants)
├── models/                           (SQLAlchemy row I/O)
├── schemas/                          (Pydantic validation)
├── exceptions/                       (domain exception fields)
├── services/                         (TicketService / AuditService / AgentAccountService — REAL DB)
├── routes/                           (REST + WS — TestClient against real DB)
├── mcp/                              (MCP tool dispatch — real auth, real DB)
├── observability/                    (OTel init, traced decorator, metrics, logging)
├── middleware/                       (correlation, rate-limit, bearer auth)
├── auth/                             (existing magic_link tests preserved; new bearer tests)
├── concurrency/                      (≥10-writer NFR-900 scenarios — REAL DB)
├── chaos/                            (audit-rollback / OTel-down NFR-903/906)
└── e2e/                              (Playwright + backend — full kanban workflow)
```

### 1.3 Markers

```
@pytest.mark.unit            # no I/O — Pydantic schemas, exception classes, helpers
@pytest.mark.integration     # real DB; sub-second
@pytest.mark.concurrency     # real DB + asyncio.gather; ≥10 workers; multi-second
@pytest.mark.chaos           # injects faults; isolated DB; multi-second
@pytest.mark.e2e             # Playwright + uvicorn + Postgres + Jaeger; minutes
```

CI default: `pytest -m "unit or integration"`. Nightly: also `concurrency`, `chaos`, `e2e`.

---

## 2. Per-Module Test Plans

### 2.1 Migrations (`tests/migrations/`)

| # | Scenario | Type | Maps to |
|---|----------|------|---------|
| MIG-01 | `test_problems_renamed_to_tickets` — table `problems` is gone, `tickets` exists with the additive columns | integration | FR-100, AC-100, Task A1 |
| MIG-02 | `test_new_columns_present_with_defaults` — every column in §1.2 of design exists with declared nullability | integration | FR-100, AC-100, A1 |
| MIG-03 | `test_enums_created` — `ticket_type`, `ticket_priority`, `ticket_status`, `ticket_link_type` exist | integration | FR-100, A1, A4 |
| MIG-04 | `test_check_constraints_enforced` — `ck_tickets_assignee_pair`, custom_fields-object-only, source≠target on links | integration | FR-151, A1 |
| MIG-05 | `test_domains_renamed_and_columns_added` — `projects.key_prefix`, `next_key_seq` present | integration | FR-103, A2 |
| MIG-06 | `test_key_backfilled_and_unique` — every ticket row has a unique `key` after M3 | integration | FR-103, AC-106 |
| MIG-07 | `test_uq_project_seq_enforced` — direct insert of duplicate `(project_id, seq_number)` raises IntegrityError | integration | FR-103 |
| MIG-08 | `test_audit_log_no_update_delete_grant` — `REVOKE UPDATE, DELETE` is in effect for `app_rw` role; attempted UPDATE raises insufficient_privilege | integration | FR-181, AC-183 |
| MIG-09 | `test_agent_accounts_unique_name` — duplicate `name` insert raises | integration | FR-220 |
| MIG-10 | `test_audit_log_actor_type_check` — actor_type CHECK rejects unknown values | integration | FR-180 |
| MIG-11 | `test_search_tsv_generated` — `search_tsv` column populated from title+description on insert | integration | FR-161, A4 |
| MIG-12 | `test_gin_indexes_present` — `gin_tickets_labels`, `gin_tickets_custom_fields`, `gin_tickets_search_tsv` exist | integration | FR-160, FR-161 |
| MIG-13 | `test_legacy_tables_dropped` — `upstars`, `claims`, `solutions`, old `audit_logs`, old `comments`, `tags` all gone | integration | §1.8 |
| MIG-14 | `test_links_unique_and_no_self` — `uq_ticket_links` + `ck_ticket_links_no_self` enforced | integration | FR-208 |
| MIG-15 | `test_default_flow_seeded` — every existing project has a 6-row `board_columns` set | integration | FR-130 |
| MIG-16 | `test_comments_table_present` — `ticket_comments` exists with FK to `tickets` and ON DELETE CASCADE | integration | FR-145 |
| MIG-17 | `test_migration_chain_reversible` — `alembic downgrade base` then `upgrade head` cycles cleanly | integration | A1..A9 (chain) |

**High-risk:** MIG-08 (REVOKE enforcement) and MIG-06 (`key` backfill correctness) — both are one-shot reshape decisions that, if wrong in production, corrupt audit or break agent retries.

---

### 2.2 SQLAlchemy Models (`tests/models/`)

| # | Scenario | Type | Maps to |
|---|----------|------|---------|
| MOD-01 | `test_ticket_roundtrip_persistence` — insert + reload yields equal field values incl. `labels[]` and `custom_fields` | integration | FR-100 |
| MOD-02 | `test_ck_assignee_pair_violation` — inserting only `assignee_id` without `assignee_type` raises IntegrityError | integration | FR-140 |
| MOD-03 | `test_audit_actor_type_check` — invalid `actor_type` rejected at DB level | integration | FR-180 |
| MOD-04 | `test_api_key_prefix_index_present` — partial index used for prefix lookup verified via EXPLAIN | integration | FR-221 |
| MOD-05 | `test_ticket_link_self_rejected` — inserting `source_id == target_id` raises | integration | FR-208 |

---

### 2.3 Pydantic Schemas (`tests/schemas/`)

| # | Scenario | Type | Maps to |
|---|----------|------|---------|
| SCH-01 | `test_create_rejects_array_custom_fields` — `custom_fields=[1,2,3]` raises ValidationError | unit | FR-151, AC-151 |
| SCH-02 | `test_create_accepts_object_custom_fields` — `{"vendor":"acme"}` round-trips | unit | FR-151 |
| SCH-03 | `test_update_requires_version` — `TicketUpdate(...)` without `version` raises | unit | FR-101 |
| SCH-04 | `test_envelope_has_correlation_id` — every error envelope variant carries `correlation_id` | unit | NFR-904 |
| SCH-05 | `test_ticket_create_title_length_bounds` — empty or >300 char title rejected | unit | FR-102 |
| SCH-06 | `test_unknown_ticket_type_rejected` — string outside enum fails | unit | FR-102, AC-105 |

---

### 2.4 Domain Exceptions (`tests/exceptions/`)

| # | Scenario | Type | Maps to |
|---|----------|------|---------|
| EXC-01 | `test_stale_version_carries_current_version_and_current` | unit | FR-101 |
| EXC-02 | `test_children_open_carries_blocking_child_ids` | unit | FR-131, NFR-904 |
| EXC-03 | `test_already_claimed_carries_current_assignee_id` | unit | FR-141 |
| EXC-04 | `test_link_exists_carries_no_extra_fields_required` | unit | FR-208 |
| EXC-05 | `test_rate_limited_carries_retry_after_ms` | unit | FR-223, NFR-904 |
| EXC-06 | `test_invalid_transition_carries_from_and_to` | unit | FR-130 |

---

### 2.5 Service: `AuditService` (`tests/services/test_audit*.py`)

| # | Scenario | Type | Maps to |
|---|----------|------|---------|
| AUD-01 | `test_records_one_row_with_diff` — record() inserts exactly one row with `{before, after}` JSON diff | integration | FR-180, AC-180 |
| AUD-02 | `test_rolls_back_with_parent_tx` — when the parent TX rolls back, the audit insert rolls back too (zero orphan rows) | integration | NFR-903, AC-181 |
| AUD-03 | `test_correlation_id_equals_active_trace_id` — under an active OTel span, the stored `correlation_id` equals the span's `trace_id` | integration | FR-232, AC-232 |
| AUD-04 | `test_unknown_action_rejected` — `action='floop'` raises ValidationError before SQL | integration | FR-180 |
| AUD-05 | `test_no_update_path_exists` — code-search assertion: grep `app/` for `update(AuditLog)` / `delete(AuditLog)` returns no matches | unit | FR-181, AC-182 |

**High-risk:** AUD-02 is the audit-by-construction invariant; a regression here invalidates NFR-903 silently.

---

### 2.6 Service: `TicketService` (`tests/services/test_ticket_*.py`)

#### 2.6.1 `create` + `update`

| # | Scenario | Type | Maps to |
|---|----------|------|---------|
| TKT-CRE-01 | `test_create_assigns_key_and_version_one` — returned ticket has `key='TKT-1'`, `version=1` | integration | FR-100, FR-103, AC-101 |
| TKT-CRE-02 | `test_create_increments_seq_per_project_monotonic` — three creates produce `TKT-1, TKT-2, TKT-3` | integration | FR-103, AC-106 |
| TKT-CRE-03 | `test_soft_delete_then_create_reuses_no_key` — after soft-delete of `TKT-1`, next create is `TKT-2` (never `TKT-1`) | integration | FR-103, AC-106 |
| TKT-CRE-04 | `test_create_records_audit_row` — exactly one audit row with `action='create'`, `before={}`, `after=ticket_dict` | integration | FR-180, AC-180 |
| TKT-CRE-05 | `test_create_emits_broadcast_only_after_commit` — broadcaster spy receives event AFTER `db.commit()` returns (not mid-tx) | integration | FR-185, FR-132 |
| TKT-CRE-06 | `test_create_rejects_depth_exceeded` — parent chain depth=5; new child raises DepthLimitError | integration | FR-120, AC-120 |
| TKT-CRE-07 | `test_create_rejects_201st_child` — 200 siblings exist; 201st raises ChildLimitError | integration | FR-120, AC-121 |
| TKT-CRE-08 | `test_create_unknown_project_raises_not_found` | integration | FR-100 |
| TKT-UPD-01 | `test_update_bumps_version` — submitted v=1 → returned v=2 | integration | FR-101, AC-103 |
| TKT-UPD-02 | `test_concurrent_update_loser_gets_stale_version_error` — two parallel updates at v=1: one returns v=2, one raises StaleVersionError with `current_version=2` | integration / concurrency | FR-101, AC-103, AC-104 |
| TKT-UPD-03 | `test_update_rolls_back_audit_on_failure` — injecting a fault between UPDATE and audit insert rolls back both | chaos | NFR-903, AC-181, AC-133 |
| TKT-UPD-04 | `test_reparent_atomic_with_audit_before_after` — audit `diff` has `parent_id.before` and `parent_id.after` | integration | FR-122, AC-124 |
| TKT-UPD-05 | `test_reparent_to_descendant_raises_cycle` — setting parent to descendant raises CycleDetectedError | integration | FR-121, AC-123 |
| TKT-UPD-06 | `test_reparent_to_self_raises_cycle` | integration | FR-121 |

#### 2.6.2 `transition`

| # | Scenario | Type | Maps to |
|---|----------|------|---------|
| TKT-TRN-01 | `test_invalid_transition_rejected` — `todo→done` when board only allows `todo→in_progress` raises InvalidTransitionError | integration | FR-130, AC-130 |
| TKT-TRN-02 | `test_epic_close_blocked_by_open_child` — close epic with 1 open child raises ChildrenOpenError listing that child id | integration | FR-131, AC-131 |
| TKT-TRN-03 | `test_epic_close_succeeds_when_all_children_terminal` — close epic with all `done` children commits; closed_at set | integration | FR-131 |
| TKT-TRN-04 | `test_transition_with_comment_is_atomic` — comment_body provided → both transition + comment commit; audit row + comment row + transition row exist | integration | FR-210, AC-210 |
| TKT-TRN-05 | `test_audit_failure_rolls_back_transition` — chaos: audit insert raises → status unchanged in DB, no WS event broadcast | chaos | FR-132, AC-133 |
| TKT-TRN-06 | `test_concurrent_epic_close_no_deadlock` — 10 concurrent epic-close attempts on the same epic with shifting child states: no deadlock, exactly the right subset succeeds, all others get `children_open` or `stale_version` | concurrency | NFR-900, AC-132 |
| TKT-TRN-07 | `test_transition_emits_ticket_transitioned_ws_event` — broadcaster received `ticket.transitioned` with from/to and correlation_id | integration | FR-185 |
| TKT-TRN-08 | `test_stale_version_on_transition_returns_409_with_current` — submit stale version on transition path → StaleVersionError | integration | FR-101 |

#### 2.6.3 `assign` / `claim`

| # | Scenario | Type | Maps to |
|---|----------|------|---------|
| TKT-ASN-01 | `test_assign_bumps_version_and_audits` — audit row has `assignee_id.before` and `assignee_id.after` | integration | FR-140, AC-140 |
| TKT-ASN-02 | `test_assign_unknown_actor_raises_validation` | integration | FR-203 |
| TKT-CLM-01 | `test_concurrent_claims_one_wins` — N=10 agents claim same unassigned ticket via `asyncio.gather` → exactly 1 success, 9× AlreadyClaimedError with the winning assignee_id | concurrency | FR-141, AC-141, NFR-900 |
| TKT-CLM-02 | `test_claim_by_non_agent_forbidden` — actor.type='user' raises ForbiddenError | integration | FR-141 |
| TKT-CLM-03 | `test_claim_records_audit_with_agent_actor` — audit row carries `actor_type='agent'` | integration | FR-222, AC-223 |

#### 2.6.4 `add_comment` / `link`

| # | Scenario | Type | Maps to |
|---|----------|------|---------|
| TKT-CMT-01 | `test_comment_is_immutable` — no update/delete path exists in service module (code search) | unit | FR-145, AC-145 |
| TKT-CMT-02 | `test_comment_records_audit_and_broadcasts` | integration | FR-180, FR-185 |
| TKT-CMT-03 | `test_empty_body_rejected` | integration | FR-145 |
| TKT-LNK-01 | `test_duplicate_link_raises_link_exists` | integration | FR-208, AC-208 |
| TKT-LNK-02 | `test_self_link_rejected` | integration | FR-208 |
| TKT-LNK-03 | `test_link_emits_ticket_linked_ws_event` | integration | FR-185 |

#### 2.6.5 `list` / `search` / `get_subtree`

| # | Scenario | Type | Maps to |
|---|----------|------|---------|
| TKT-LST-01 | `test_cursor_stable_under_concurrent_insert` — paginate over 1000 rows while inserting; no duplicates, no gaps for already-visible rows | concurrency | FR-160, AC-161 |
| TKT-LST-02 | `test_filter_by_label_exact_match` — `?label=blocked` returns only tickets with `'blocked'` in labels (no substring) | integration | FR-150, AC-150 |
| TKT-LST-03 | `test_default_sort_updated_at_desc` | integration | FR-160 |
| TKT-LST-04 | `test_sparse_fieldset_returns_only_requested` | integration | FR-104, AC-107 |
| TKT-SRC-01 | `test_fts_ranks_two_word_hits_above_one_word` — `"login bug"` query: ticket containing both ranks above ticket with only one | integration | FR-161, AC-162 |
| TKT-SRC-02 | `test_empty_query_falls_through_to_list` | integration | FR-161 |
| TKT-SRC-03 | `test_search_respects_all_filters` — every filter listed in FR-160 exercised | integration | FR-160, AC-160 |
| TKT-SUB-01 | `test_subtree_one_round_trip_depth_five` — query count is exactly 1 for a 5-deep tree | integration | FR-121, AC-122, AC-175 |
| TKT-SUB-02 | `test_subtree_excludes_soft_deleted` | integration | FR-121 |
| TKT-SUB-03 | `test_subtree_unknown_root_raises_not_found` | integration | FR-121 |

---

### 2.7 Service: `AgentAccountService` (`tests/services/test_agent_accounts.py`)

| # | Scenario | Type | Maps to |
|---|----------|------|---------|
| AGT-01 | `test_create_returns_plaintext_once` — create returns plaintext key; subsequent reads never expose it | integration | FR-220, AC-220 |
| AGT-02 | `test_stored_key_matches_via_verify_only` — argon2 verify of plaintext against `api_key_hash` succeeds | integration | FR-220, AC-221 |
| AGT-03 | `test_authenticate_unknown_raises_auth_error` | integration | FR-221 |
| AGT-04 | `test_authenticate_revoked_raises` | integration | FR-221 |
| AGT-05 | `test_authenticate_disabled_raises` | integration | FR-221 |
| AGT-06 | `test_revoke_blocks_next_request_within_5s` — revoke; wait <5s; next auth fails (cache TTL bound) | integration | FR-221, AC-222 |
| AGT-07 | `test_cache_hit_avoids_db_roundtrip` — assert query count = 0 on second auth within TTL | integration | FR-221 |
| AGT-08 | `test_last_seen_at_updated` — fire-and-forget update visible after a short delay | integration | FR-220 |

---

### 2.8 REST Routes (`tests/routes/`)

| # | Scenario | Type | Maps to |
|---|----------|------|---------|
| RTE-TKT-01 | `test_post_returns_201_with_key_and_version` | integration | FR-100, AC-101 |
| RTE-TKT-02 | `test_patch_conflict_returns_409_with_current_version_and_current_row` | integration | FR-101, AC-103, AC-104, NFR-904 |
| RTE-TKT-03 | `test_invalid_transition_returns_400_invalid_transition` | integration | FR-130, AC-130 |
| RTE-TKT-04 | `test_epic_close_with_open_children_returns_409_children_open` | integration | FR-131, AC-131, NFR-904 |
| RTE-TKT-05 | `test_x_correlation_id_header_present_on_every_response` — including 4xx and 5xx | integration | FR-186, NFR-902, AC-902 |
| RTE-TKT-06 | `test_x_correlation_id_equals_response_body_correlation_id` | integration | FR-186, AC-187 |
| RTE-TKT-07 | `test_soft_deleted_excluded_from_default_reads` | integration | FR-100, AC-102 |
| RTE-TKT-08 | `test_admin_can_read_soft_deleted` | integration | AC-102 |
| RTE-TKT-09 | `test_400_validation_lists_fields` — submit unknown ticket type → 400 with `fields[]` naming `ticket_type` | integration | FR-102, AC-105, NFR-904 |
| RTE-TKT-10 | `test_pagination_cursor_stable_over_inserts` | integration | FR-104, AC-108 |
| RTE-CMT-01 | `test_patch_comment_returns_405` | integration | FR-145, AC-145 |
| RTE-CMT-02 | `test_delete_comment_returns_405` | integration | FR-145 |
| RTE-CMT-03 | `test_get_ticket_includes_recent_20_comments_with_cursor` | integration | FR-146, AC-147 |
| RTE-LNK-01 | `test_duplicate_link_returns_409_link_exists` | integration | FR-208, NFR-904 |
| RTE-LNK-02 | `test_unknown_link_type_returns_400` | integration | FR-208 |
| RTE-PRJ-01 | `test_board_returns_columns_with_tickets_in_order` | integration | FR-170 |
| RTE-PRJ-02 | `test_board_excludes_other_projects_tickets` | integration | FR-185 |
| RTE-AGT-01 | `test_post_agent_admin_only_returns_403_for_user` | integration | FR-220 |
| RTE-AGT-02 | `test_post_agent_returns_plaintext_key_once_then_404_on_read` | integration | FR-220, AC-220 |
| RTE-AGT-03 | `test_revoke_returns_204` | integration | FR-221 |
| RTE-ACT-01 | `test_agents_activity_only_returns_agent_actor_rows` | integration | FR-178, AC-178 |
| RTE-ACT-02 | `test_agents_activity_within_1s_of_commit` | integration | FR-178, AC-178 |
| RTE-ERR-01 | `test_full_error_table_conformance` — parametrized: each NFR-904 row is reachable, status+code+body fields match | integration | NFR-904, AC-904 |

**High-risk:** RTE-TKT-02 (the OCC 409 contract — agents cannot retry deterministically without `current_version` + `current` in the body), RTE-ERR-01 (the entire structured-errors-over-silent-loss principle).

---

### 2.9 WebSocket Routes (`tests/routes/test_ws.py`)

| # | Scenario | Type | Maps to |
|---|----------|------|---------|
| WS-01 | `test_bearer_header_rejected_at_connect` — agent API key → 401 close | integration | FR-187, AC-188 |
| WS-02 | `test_session_cookie_accepted_at_connect` | integration | FR-185 |
| WS-03 | `test_subscribe_and_receive_ticket_created` — subscribe project P; emit event; client receives | integration | FR-185, AC-185 |
| WS-04 | `test_no_events_for_unsubscribed_project` — events for project Q not delivered | integration | FR-185, AC-186 |
| WS-05 | `test_every_event_payload_has_correlation_id` | integration | FR-186, AC-187 |
| WS-06 | `test_event_delivered_within_1s_of_commit` — measure latency, assert ≤1000ms | integration | FR-171, AC-171 |
| WS-07 | `test_broadcast_failure_does_not_fail_request` — close a subscriber socket then trigger a write: request still 201 | integration | NFR-906, AC-906 |
| WS-08 | `test_post_commit_only` — abort the parent TX → no WS event emitted (broadcaster spy empty) | chaos | FR-132, NFR-903 |
| WS-09 | `test_transition_emits_correct_event_type` — `ticket.transitioned` not `ticket.updated` | integration | FR-185 |
| WS-10 | `test_link_emits_ticket_linked` | integration | FR-185 |

**High-risk:** WS-08 — silent broadcast of an uncommitted change creates ghost events on the board.

---

### 2.10 MCP Tools (`tests/mcp/`)

| # | Scenario | Type | Maps to |
|---|----------|------|---------|
| MCP-LST-01 | `test_returns_ten_tools_with_input_schemas` — `tools/list` lists exactly the 10 tools | integration | FR-200, AC-200 |
| MCP-LST-02 | `test_retry_contract_in_description_for_version_tools` — descriptions of `update_status`, `assign`, `transition`, `link_tickets` document the retry contract | integration | FR-212, AC-212 |
| MCP-AUTH-01 | `test_missing_bearer_returns_32001` | integration | FR-221, NFR-904 |
| MCP-AUTH-02 | `test_revoked_bearer_returns_32001` | integration | FR-221 |
| MCP-AUTH-03 | `test_unknown_bearer_returns_32001` | integration | FR-221 |
| MCP-CRE-01 | `test_create_ticket_creates_and_returns_correlation_id` | integration | FR-201, AC-201, FR-211 |
| MCP-CRE-02 | `test_create_ticket_reporter_id_equals_caller_service_account` | integration | FR-201, AC-201, FR-222 |
| MCP-CRE-03 | `test_create_ticket_unknown_type_returns_32602_with_fields` | integration | FR-102, AC-105 |
| MCP-UPD-01 | `test_update_status_stale_returns_32004_with_current_version` | integration | FR-202, AC-202, NFR-904 |
| MCP-UPD-02 | `test_update_status_invalid_transition_returns_32602_or_proper_code` (per error table) | integration | FR-202, NFR-904 |
| MCP-UPD-03 | `test_epic_close_returns_32005_with_blocking_children` | integration | FR-202, AC-202, FR-131 |
| MCP-CLM-01 | `test_two_agents_one_wins_one_32010` — N=10 agents call `claim` concurrently → 1 ok + 9× -32010 with `current_assignee_id` | concurrency | FR-204, AC-141, NFR-900 |
| MCP-CLM-02 | `test_claim_unknown_ticket_returns_32003` | integration | FR-204 |
| MCP-ASN-01 | `test_assign_unknown_assignee_returns_32602` | integration | FR-203, AC-203 |
| MCP-CMT-01 | `test_add_comment_returns_comment_id_and_correlation_id` | integration | FR-205, AC-205 |
| MCP-CMT-02 | `test_mcp_comments_indistinguishable_from_rest_except_author_type` | integration | FR-205, AC-205 |
| MCP-LMT-01 | `test_list_my_tickets_only_returns_caller_assigned` | integration | FR-206, AC-206 |
| MCP-LMT-02 | `test_list_my_tickets_status_filter` | integration | FR-206 |
| MCP-GET-01 | `test_get_ticket_one_roundtrip_with_subtree_and_comments` | integration | FR-207, AC-207 |
| MCP-LNK-01 | `test_duplicate_link_returns_32011` | integration | FR-208, AC-208 |
| MCP-SRC-01 | `test_search_tickets_equivalent_to_rest` — identical filters produce identical row IDs across REST and MCP | integration | FR-209, AC-209 |
| MCP-TRN-01 | `test_transition_with_comment_atomic` — comment created iff transition succeeded | integration | FR-210, AC-210 |
| MCP-COR-01 | `test_every_response_has_correlation_id_equal_to_trace_id` — sample 100 random tool calls; every response.correlation_id matches the OTel trace_id | integration | FR-211, NFR-902, AC-902, AC-211 |
| MCP-COR-02 | `test_error_responses_also_carry_correlation_id` | integration | FR-211, NFR-902 |
| MCP-TRP-01 | `test_inbound_traceparent_produces_child_span_with_same_trace_id` | integration | FR-234, AC-234 |
| MCP-TRP-02 | `test_streaming_sse_transport_basic_roundtrip` — reconnect a dropped SSE stream and verify a subsequent tool call still works with the same auth | integration | FR-200, FR-211 |

**High-risk:** MCP-CLM-01 (claim race — the single most concurrency-sensitive verb in the system), MCP-COR-01 (correlation invariant — failure mode is silent and shows up only during incident forensics), MCP-TRP-02 (SSE reconnect behavior was deferred but the underlying transport needs at least one smoke test).

---

### 2.11 Observability (`tests/observability/`, `tests/middleware/`)

| # | Scenario | Type | Maps to |
|---|----------|------|---------|
| OBS-OTL-01 | `test_init_registers_otlp_exporter` — startup attaches the OTLPExporter | integration | FR-230, AC-230 |
| OBS-OTL-02 | `test_otlp_unreachable_does_not_fail_request` — point exporter at unreachable host; request still 201 | chaos | NFR-906, AC-906 |
| OBS-OTL-03 | `test_jaeger_down_does_not_affect_audit_writes` — audit_log still receives rows when collector is down | chaos | NFR-906, AC-906 |
| OBS-LOG-01 | `test_log_line_includes_trace_id_and_span_id` — under active span, every JSON log record has both fields | integration | FR-232, AC-232 |
| OBS-LOG-02 | `test_audit_row_trace_id_matches_log_line_trace_id` — the join key works across both signals | integration | FR-232, AC-232 |
| OBS-COR-01 | `test_x_correlation_id_header_equals_trace_id` — both inbound (none supplied) and inbound (traceparent supplied) | integration | FR-234, AC-234, NFR-902 |
| OBS-COR-02 | `test_correlation_id_round_trips_through_all_five_carriers` — sample N requests; the same ID appears in response header, response body, audit row, log line, WS event, OTel span | integration | NFR-902, AC-902, AC-232 |
| OBS-TRC-01 | `test_decorator_creates_named_span_for_service_method` | integration | FR-231, AC-231 |
| OBS-TRC-02 | `test_actor_attrs_recorded` — `actor_id`, `actor_type`, `project_id`, `ticket_id` on the span | integration | FR-231, AC-231 |
| OBS-TRC-03 | `test_error_marks_span_status_error` | integration | FR-231 |
| OBS-TRC-04 | `test_4xx_and_5xx_responses_still_traced` — 100% trace coverage including error paths | integration | NFR-902, AC-902 |
| OBS-MET-01 | `test_counter_increments_on_create` — `tickets_created_total` +1 | integration | FR-233, AC-233 |
| OBS-MET-02 | `test_outcome_label_set_on_conflict` — `mcp_tool_calls_total{outcome='conflict'}` on stale | integration | FR-233 |
| OBS-MET-03 | `test_db_conflict_total_increments_on_409` | integration | FR-233 |
| OBS-MET-04 | `test_request_duration_histogram_records_for_each_route` | integration | FR-233, NFR-901 |
| OBS-MET-05 | `test_baseline_metric_set_complete` — every metric named in FR-233 emitted within one collection interval | integration | FR-233, AC-233 |

**High-risk:** OBS-COR-02 — this is the trace-correlation round-trip the user explicitly flagged. It tests the system-of-record invariant.

---

### 2.12 Concurrency Suite (`tests/concurrency/`)

These are the load-and-contention tests that NFR-900 demands. All run against a real Postgres with N independent sessions via `asyncio.gather`.

| # | Scenario | Type | Maps to |
|---|----------|------|---------|
| CON-01 | `test_ten_concurrent_writers_mixed_workload_no_lost_updates` — 10 writers × 1000 mixed (create/update/transition) ops × 100 shared tickets. Assert: zero lost updates; every committed `after` equals some observed `before+delta`; every 409 carries the actual current version; no deadlocks; ≥50 successful writes/sec | concurrency | NFR-900, AC-900 |
| CON-02 | `test_parallel_claim_race_exactly_one_winner` — 50 agents call `claim_ticket` on same row concurrently; exactly 1 success, 49× AlreadyClaimedError with matching winner id | concurrency | FR-141, AC-141 |
| CON-03 | `test_parallel_epic_close_under_child_flap` — 1 epic-close call + 5 agents flipping a child's status concurrently; final state is one of {epic closed, all children closed} or {epic open, at least one child non-terminal} — never partial | concurrency | FR-131, AC-132 |
| CON-04 | `test_parallel_create_under_seq_lock_no_skipped_keys` — 20 agents create concurrently in same project; assigned keys are exactly TKT-1..TKT-20 (no gaps, no duplicates) | concurrency | FR-103, AC-106 |
| CON-05 | `test_parallel_link_create_dedup` — 10 agents call `link_tickets(A,B,blocks)` simultaneously; exactly 1 success, 9× LinkExistsError | concurrency | FR-208 |
| CON-06 | `test_audit_row_count_equals_successful_write_count_under_load` — after CON-01 finishes, `SELECT count(*) FROM audit_log WHERE created_at >= t0` equals total successful writes; LEFT JOIN tickets ON correlation_id has zero orphans both directions | concurrency | NFR-903, AC-903 |
| CON-07 | `test_p95_latency_meets_targets_under_load` — emit OTel histograms during CON-01; P95 ≤ 300ms for write paths, ≤ 150ms for `get_ticket`, ≤ 500ms for subtree, ≤ 400ms for list/search | concurrency | NFR-901, AC-901 |
| CON-08 | `test_rate_limit_engages_under_burst` — single agent issues 60 writes/sec for 5s; expect 429 responses after threshold; recovery after backoff | concurrency | FR-223, AC-224 |

**High-risk (user-flagged):** CON-01 is the ≥10 concurrent writers anchor scenario. CON-03 is the parallel claim/transition race. CON-04 covers the per-project key allocation under contention.

---

### 2.13 Chaos Suite (`tests/chaos/`)

| # | Scenario | Type | Maps to |
|---|----------|------|---------|
| CHA-01 | `test_audit_insert_fault_rolls_back_state_change` — monkey-patch AuditService.record to raise after the state mutation; assert: ticket row unchanged, no WS event emitted, exception surfaces as 500 with correlation_id | chaos | NFR-903, AC-903, FR-132, AC-133 |
| CHA-02 | `test_otel_exporter_down_no_5xx` — block egress to OTLP endpoint; submit 100 mixed requests; zero 5xx; audit_log still populated | chaos | NFR-906, AC-906 |
| CHA-03 | `test_postgres_disconnect_returns_500_with_correlation_id` — kill DB connection mid-transaction; response is 500 with correlation_id; recovery on next request | chaos | NFR-904, NFR-906 |
| CHA-04 | `test_websocket_subscriber_failure_does_not_block_writes` — register a subscriber that raises on receive; submit write; write succeeds; broadcaster logs error | chaos | NFR-906 |
| CHA-05 | `test_orphan_audit_or_orphan_state_after_chaos_is_zero` — run CHA-01 under load; post-run SQL: `tickets t LEFT JOIN audit_log a ON a.entity_id = t.id AND a.correlation_id = ...` has zero orphans in either direction | chaos | NFR-903, AC-903 |

**High-risk (user-flagged):** CHA-01 + CHA-05 verify the audit-by-construction invariant under fault injection — without these, NFR-903 is aspirational.

---

### 2.14 Frontend Kanban (`frontend/src/**/*.test.ts(x)`, `tests/e2e/`)

#### Component-level (Vitest + React Testing Library)

| # | Scenario | Type | Maps to |
|---|----------|------|---------|
| FE-CMP-01 | `KanbanBoard renders columns from board_columns config` | unit | FR-170 |
| FE-CMP-02 | `KanbanColumn highlights drop target on dragOver` | unit | FR-170 |
| FE-CMP-03 | `TicketCard click opens TicketDetailDrawer` | unit | FR-170 |
| FE-CMP-04 | `useBoardStore.applyEvent overwrites local state with server payload` | unit | FR-171, AC-171 |
| FE-CMP-05 | `useBoardStore.optimisticTransition reverts on rollback` | unit | FR-170, AC-170 |
| FE-CMP-06 | `FilterBar emits onChange with combined filters` | unit | FR-160 |
| FE-CMP-07 | `TicketCreateModal posts with column's status and version=1` | unit | FR-172, AC-172 |
| FE-CMP-08 | `HierarchyTreeView fetches subtree in one call and renders 5 levels` | unit | FR-175, AC-175 |
| FE-CMP-09 | `AgentActivityFeed renders ws events appended in order` | unit | FR-178 |
| FE-CMP-10 | `WS reconciliation: optimistic transition discarded when server event for same correlation_id lands` | unit | FR-171 |
| FE-CMP-11 | `WS reconciliation: optimistic move rolled back after 2s budget without server confirmation` | unit | FR-171 |

#### End-to-end (Playwright + real backend)

| # | Scenario | Type | Maps to |
|---|----------|------|---------|
| FE-E2E-01 | `human drags card from todo to in_progress; backend transitions; board reflects new column on second browser within 1s` | e2e | FR-170, FR-171, AC-170, AC-171 |
| FE-E2E-02 | `human drags card to disallowed column → optimistic move rolls back with toast carrying server's invalid_transition` | e2e | FR-170, AC-170, FR-130 |
| FE-E2E-03 | `inline-create in column produces ticket with column's status` | e2e | FR-172, AC-172 |
| FE-E2E-04 | `agent (via MCP) moves a card; connected human board reflects within 1s` | e2e | FR-171, FR-185, AC-171, AC-185 |
| FE-E2E-05 | `hierarchy tree page renders 5-level subtree in one round trip` | e2e | FR-175, AC-175 |
| FE-E2E-06 | `agent activity feed live-updates as MCP tools run` | e2e | FR-178, AC-178 |
| FE-E2E-07 | `bearer-authed WS connection is rejected at connect` | e2e | FR-187, AC-188 |
| FE-E2E-08 | `Demo script — 3 concurrent agents create→claim→transition→close an epic with children; final board state correct; traces visible in Jaeger; audit join across all events succeeds` | e2e | NFR-900, NFR-902, NFR-903, all of §15 |

**High-risk:** FE-E2E-01 (the entire kanban contract), FE-E2E-04 (the cross-actor WS propagation), FE-E2E-08 (the full system-of-record demo).

---

## 3. High-Risk Scenarios — User-Flagged Coverage Map

| Risk | Covered by |
|------|-----------|
| **OCC version conflict** | TKT-UPD-02, RTE-TKT-02, MCP-UPD-01, CON-01 |
| **Parallel claim race** | TKT-CLM-01, MCP-CLM-01, CON-02 |
| **Hierarchy depth/child limits** | TKT-CRE-06, TKT-CRE-07, MIG-12 (perf), TKT-SUB-01 |
| **MCP transport reconnect (SSE)** | MCP-TRP-02 (smoke) + FE-E2E-04 (cross-actor live propagation) |
| **OTel correlation_id round-trip** | OBS-COR-01, OBS-COR-02, MCP-COR-01, AUD-03 |
| **≥10 concurrent writers (user-mandated)** | CON-01 (10×1000×100), CON-02 (50 claim race), CON-03 (parallel epic+child flap), CON-04 (key allocation under contention) |
| **Real-DB integration (user-mandated)** | Entire `tests/services/`, `tests/routes/`, `tests/mcp/`, `tests/concurrency/`, `tests/chaos/` suites — all use the `db_engine` Postgres fixture, no SQLAlchemy mocks |
| **Audit-by-construction (NFR-903)** | AUD-02, TKT-UPD-03, TKT-TRN-05, CHA-01, CHA-05, CON-06, WS-08 |
| **Trace coverage on errors (NFR-902)** | RTE-TKT-05, OBS-TRC-04, MCP-COR-02 |

---

## 4. Coverage Posture by Module

| Module | Test count (planned) | Real-DB? | Concurrency? | Chaos? |
|--------|---------------------|----------|--------------|--------|
| Migrations | 17 | yes | — | — |
| Models | 5 | yes | — | — |
| Schemas | 6 | no (Pydantic only) | — | — |
| Exceptions | 6 | no | — | — |
| AuditService | 5 | yes | — | rollback (AUD-02) |
| TicketService.create/update | 14 | yes | TKT-UPD-02 | TKT-UPD-03 |
| TicketService.transition | 8 | yes | TKT-TRN-06 | TKT-TRN-05 |
| TicketService.assign/claim/comment/link | 10 | yes | TKT-CLM-01 | — |
| TicketService.list/search/subtree | 9 | yes | TKT-LST-01 | — |
| AgentAccountService | 8 | yes | — | — |
| REST routes | 22 | yes | — | — |
| WS routes | 10 | yes | — | WS-07, WS-08 |
| MCP tools | 27 | yes | MCP-CLM-01 | — |
| Observability | 15 | yes | — | OBS-OTL-02, OBS-OTL-03 |
| Concurrency (NFR-900 suite) | 8 | yes | yes (anchor) | — |
| Chaos | 5 | yes | — | yes (anchor) |
| Frontend components | 11 | n/a (FE) | — | — |
| Frontend e2e | 8 | yes (live backend) | FE-E2E-08 | — |
| **Total planned scenarios** | **194** | | | |

---

## 5. Self-Critique (persona: senior eng, demands real-DB integration tests over mocks; ≥10 concurrent writers must exist)

**Counter-arg 1 — "194 planned scenarios is too many. You will never write them all and the team will cherry-pick the easy ones."**
*Defense:* The list is enumerative on purpose — each row is one acceptance criterion in the spec or one error-table cell in NFR-904, both of which are non-negotiable. The "easy" scenarios (Pydantic SCH-*, EXC-*) are unit tests that take minutes; cutting them does not save meaningful time. Concurrency and chaos are 13 scenarios total, isolated under markers — they are runnable on demand and on nightly CI. Triage, if needed, is to defer the SHOULD-priority paths (FR-104 sparse-fieldset, FR-212 retry contract docstrings) — not to skip the MUST-priority CON-* suite. Recommendation stands.

**Counter-arg 2 — "You demand real Postgres for everything but `pytest-postgresql` startup is slow; CI will revolt."**
*Defense:* Session-scoped engine fixture with per-test SAVEPOINT keeps the container alive for the whole pytest run; per-test cost is the SAVEPOINT rollback (sub-millisecond). Total startup cost is ~3s amortized across hundreds of tests. The CI cost is dwarfed by the value of catching FOR UPDATE / generated-column / REVOKE behavior that mocks cannot model. The user's "demands real-DB integration tests not mocks" line is load-bearing — defending it by accepting 3s startup is the right trade.

**Counter-arg 3 — "CON-01 (10 writers × 1000 ops × 100 tickets) is a load test pretending to be a unit test. It belongs in a separate harness."**
*Defense:* It is marked `@pytest.mark.concurrency` and excluded from default CI. It runs on nightly. The reason to keep it in pytest is that it shares fixtures (`db_engine`, `seeded_project`) with the unit-level OCC tests; refactoring it into a separate harness duplicates fixture setup and creates a second source of truth for the schema. Keeping it in-tree with a marker is the minimum-cost shape for "this is testable, not just specifiable." The user explicitly demanded ≥10 concurrent writers; CON-01 is the literal materialization of NFR-900.

**Counter-arg 4 — "MCP-TRP-02 (SSE reconnect) is one test for an entire transport class. That's a smoke test, not coverage."**
*Defense:* Correct — and the design explicitly defers the reconnect behavior to "best-effort" since agents are write-only and idempotent on `correlation_id`. A full reconnect/replay test suite is a v2 deliverable. The smoke test exists to verify "the transport works at all" after a deliberate drop; deeper coverage would specify behavior the design does not commit to. Acceptable.

**Counter-arg 5 — "Chaos tests rely on monkey-patching service-layer functions. That is mock-ish behavior in a 'no mocks' regime."**
*Defense:* The user's constraint is "no mocks for the persistence layer / SQLAlchemy". Chaos tests monkey-patch at the *application boundary* (e.g., raise inside `AuditService.record`) to simulate an OS-level fault. The DB layer remains real; the audit row's presence or absence is verified against real Postgres. This is fault injection, not mocking. The distinction matters: a mocked SQLAlchemy session cannot tell you whether `REVOKE UPDATE` is in effect; a real session with a monkey-patched call site can.

**Residual risk:** The frontend e2e tests rely on Playwright + a live uvicorn + Postgres + Jaeger; the harness setup is heavier than backend tests. Mitigation: FE-E2E-* run on nightly only; FE-CMP-* run on every commit.

**Verdict:** Plan holds. All five user-flagged high-risk scenarios are covered. The ≥10 concurrent writers requirement is materialized in CON-01/CON-02/CON-04. Real-DB-over-mocks is enforced across services, routes, MCP, concurrency, and chaos suites.

---

## 6. Downstream Handoff

- `/write-test-coverage` — consumes §2 scenario IDs + §3 risk map to build the living coverage register.
- `/write-module-tests` — consumes per-module §2 scenarios to implement pytest bodies, one module at a time. Each task takes a §2 subsection as input.
- `/build-plan` — consumes §1.2 layout + §2 module groupings to slot test-writing tasks into the existing TDD-loop batches.
- `/parallel-agents-dispatch` — dispatches independent per-module test-writing tasks in parallel (modules listed in §4 are leaf-level independent).
