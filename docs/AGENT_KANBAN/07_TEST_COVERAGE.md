# Agent Kanban — Test Coverage Register

> **Living document.** Initialized by `write-test-coverage`, maintained incrementally by `/patch-docs`.
> Do NOT regenerate entirely on each change — update affected sections only.

**Intent document:** `docs/AGENT_KANBAN/01_SPEC.md`
**Implementation doc:** `docs/AGENT_KANBAN/05_IMPLEMENTATION.md`
**Test directory:** `tests/` (Python / pytest)
**Generated:** 2026-05-12
**Languages detected:** Python (pytest), TypeScript (Vitest — no test infrastructure yet)

> **Context note:** All 27 existing test files target the legacy Aion Bulletin domain (problems, solutions, votes, magic-link auth, notifications). Zero existing tests cover any Agent Kanban acceptance criterion. Every entry in this register is therefore `NOT_STARTED`. Status column is intentionally uniform — once tests land, `/patch-docs` updates individual rows.

---

## Coverage Summary

| Module | Total ACs | Covered | Partial | Not Started |
|---|---|---|---|---|
| Ticket CRUD & Data Model (§3) | 9 | 0 | 0 | 9 |
| Hierarchy (§4) | 5 | 0 | 0 | 5 |
| Status Transitions & Workflow (§5) | 4 | 0 | 0 | 4 |
| Assignments (§6) | 2 | 0 | 0 | 2 |
| Comments (§7) | 3 | 0 | 0 | 3 |
| Labels / Custom Fields (§8) | 2 | 0 | 0 | 2 |
| Search & Filter (§9) | 3 | 0 | 0 | 3 |
| Kanban Board View (§10) | 3 | 0 | 0 | 3 |
| Hierarchy Tree View (§11) | 1 | 0 | 0 | 1 |
| Agent Activity Feed (§12) | 1 | 0 | 0 | 1 |
| Audit Log (§13) | 4 | 0 | 0 | 4 |
| Notifications / WebSocket (§14) | 4 | 0 | 0 | 4 |
| MCP Server Tools (§15) | 13 | 0 | 0 | 13 |
| Service-Account Auth & API Keys (§16) | 5 | 0 | 0 | 5 |
| OpenTelemetry Instrumentation (§17) | 5 | 0 | 0 | 5 |
| Non-Functional Requirements (§18) | 7 | 0 | 0 | 7 |
| **Total** | **75** | **0** | **0** | **75** |

---

## Prioritized Gaps

All 75 ACs are uncovered. The table below orders by MUST-first, then by subsystem criticality (data integrity and audit invariants are highest because test failure = undetectable data corruption; concurrency invariants second because they cannot be checked post-hoc).

| Priority | AC | Gap description | Implementing task(s) |
|---|---|---|---|
| MUST | AC-100 | Schema introspection confirms all ticket fields with correct nullability | A1, A5 |
| MUST | AC-101 | POST /api/tickets returns 201 + id + key + version=1 | A10, A14 |
| MUST | AC-102 | Soft-deleted tickets excluded from default reads, visible to admin | A10, A14 |
| MUST | AC-103 | Concurrent updates: one 200 (version K+1), one 409 with current_version=K+1 | A10 |
| MUST | AC-104 | 409 body always includes current row | A10, A14 |
| MUST | AC-105 | Unknown `type` → 400 REST / -32602 MCP, both naming `type` | A6, A14, A16 |
| MUST | AC-106 | Key not reused after soft-delete: N → tombstone → N+1 | A10, A1, A2 |
| MUST | AC-120 | Creating child at depth >5 returns 400 | A10 |
| MUST | AC-121 | Adding 201st child returns 400 | A10 |
| MUST | AC-122 | `get_subtree` on 4-level epic returns all descendants in one round trip | A13 |
| MUST | AC-123 | Setting `parent_id = self_or_descendant` returns 400 `cycle_detected` | A10, A11 |
| MUST | AC-124 | Reparenting updates parent_id once; audit row carries before+after parent_id | A10 |
| MUST | AC-130 | Forbidden transition returns 400 `invalid_transition` | A11 |
| MUST | AC-131 | Closing epic with open child returns 409 `children_open` | A11 |
| MUST | AC-132 | Under contention: epic-close is all-or-nothing, no partial close | A11 |
| MUST | AC-133 | Audit insert failure rolls back status update; no broadcast emitted | A11, A9 |
| MUST | AC-140 | Assign to service-account succeeds; audit row shows actor + new assignee | A12 |
| MUST | AC-141 | Two concurrent claim_ticket calls: exactly one success, one -32010 | A12 |
| MUST | AC-145 | Comment update endpoints return 405 | A14 |
| MUST | AC-146 | Comments listed in created_at ASC with stable cursoring | A12, A14 |
| MUST | AC-150 | `?label=blocked` returns only tickets whose labels array contains `blocked` (no substring) | A13 |
| MUST | AC-151 | `custom_fields=[1,2,3]` → 400; `{"vendor":"acme"}` round-trips byte-for-byte | A1, A6 |
| MUST | AC-160 | Every listed filter exercised by integration test returning expected rows | A13, A14 |
| MUST | AC-161 | Cursor pagination over 1000-ticket set: no duplicates/gaps under concurrent inserts | A13 |
| MUST | AC-162 | FTS: two-word query ranks double-hit tickets above single-hit | A13 |
| MUST | AC-170 | Drag to disallowed column → optimistic move + rollback + toast with `invalid_transition` | B5 |
| MUST | AC-171 | Agent-moved card appears in correct column on all human boards within 1 s | B8 |
| MUST | AC-175 | 5-level subtree renders in one network round trip; no per-node refetch | B7, A13 |
| MUST | AC-178 | Every MCP mutation appears in activity feed within 1 s with all required fields | B3 |
| MUST | AC-180 | Property test: create/update/transition/link/comment all produce audit rows with correct before/after | A9, A10–A12 |
| MUST | AC-181 | Audit insert failure rolls back parent op (= AC-133) | A9, A11 |
| MUST | AC-182 | Code search: no UPDATE/DELETE against audit_log in app/ | A3 |
| MUST | AC-183 | Attempting UPDATE/DELETE via app DB connection fails | A3 |
| MUST | AC-185 | Every mutation produces exactly one WS event of correct type within 1 s | B1, B2 |
| MUST | AC-186 | WS subscriber without read access to project P receives no events for P | B1 |
| MUST | AC-187 | correlation_id in WS event matches X-Correlation-Id of triggering REST/MCP response | B2, C1 |
| MUST | AC-188 | WS connection with service-account API key closed with 401 | B1 |
| MUST | AC-200 | MCP `tools/list` returns exactly the 10 enumerated tools with input schemas | A16 |
| MUST | AC-201 | `create_ticket` sets caller service-account as reporter_id | A16 |
| MUST | AC-202 | All error cases in §5 reachable via `update_status` with identical codes | A16 |
| MUST | AC-203 | Assigning to unknown actor → -32602 naming `assignee` | A16 |
| MUST | AC-204 | (same as AC-141) concurrent claim via MCP tool | A16 |
| MUST | AC-205 | MCP-created comments indistinguishable from REST-created except author_type | A16 |
| MUST | AC-206 | `list_my_tickets` never returns tickets not assigned to caller | A16 |
| MUST | AC-207 | Single round trip returns ticket + 20 comments + subtree (if requested) | A16 |
| MUST | AC-208 | Duplicate link insert → -32011 | A16 |
| MUST | AC-209 | Identical filter inputs produce identical row IDs across REST and MCP | A16 |
| MUST | AC-210 | Comment created iff transition succeeds; both rolled back together on failure | A16 |
| MUST | AC-211 | correlation_id present in every tool result, matches OTel trace_id | A16, C1 |
| MUST | AC-220 | Re-reading a key after creation never returns plaintext | A15, A3 |
| MUST | AC-221 | Stored key matches only via verify-only (not equality) | A15 |
| MUST | AC-222 | Revoking a key blocks next request within ≤5 s | A15 |
| MUST | AC-223 | MCP-originated audit rows carry calling service-account | A15, A9 |
| MUST | AC-230 | Startup logs confirm OTLP exporter; smoke trace in Jaeger within 5 s | C1 |
| MUST | AC-231 | Jaeger query by correlation_id/actor_id/project_id/ticket_id returns matching spans | C2 |
| MUST | AC-232 | Random audit row's correlation_id present in Jaeger trace AND app log stream | C1, A9 |
| MUST | AC-233 | OTLP metrics export contains every named metric within one interval | C3 |
| MUST | AC-900 | Load test (10 writers, 1000 ops): 0 lost updates, every 409 has current version, 0 deadlocks, ≥50 writes/sec | C6 |
| MUST | AC-902 | 100 random sampled requests: every one has Jaeger trace, trace_id matches X-Correlation-Id | C1, C6 |
| MUST | AC-903 | Chaos fault between state mutation and audit insert: 0 committed state changes without audit row | A9, C6 |
| MUST | AC-904 | Every row in NFR-904 error table exercised by integration test asserting status+body fields | A7, A14, A16 |
| MUST | AC-905 | Every threshold maps to config key; non-default value changes runtime behavior | C1, C4, C5, A10 |
| MUST | AC-906 | Stopping Jaeger: zero requests fail; restarting resumes export | C1 |
| SHOULD | AC-107 | List with `fields=id,status,version` returns only those keys | A13, A14 |
| SHOULD | AC-108 | Cursor pagination over stable-sorted results never repeats/skips rows | A13 |
| SHOULD | AC-147 | `get_ticket` payload contains `comments` array of up to 20 entries + next_cursor | A13, A14 |
| SHOULD | AC-172 | Inline "+" in column reveals title input; creates ticket with column's status, version=1 | B7 |
| SHOULD | AC-212 | `tools/list` for version-taking tools includes retry-contract note | C5 |
| SHOULD | AC-224 | Exceeding write rate → 429 + retry_after_ms; below threshold → no 429 | C5 |
| SHOULD | AC-234 | Inbound request with `traceparent` produces child span with supplied trace_id | C5, C1 |
| SHOULD | AC-901 | Load-test P95 per operation meets targets: create/update/transition <300ms, read <150ms, subtree <500ms, search <400ms | C3, C6 |

---

## Module Coverage

### Ticket CRUD & Data Model (`app/services/tickets.py`, `app/routes/tickets.py`)

**Test files planned:**
- `tests/migrations/test_a1_rename.py`
- `tests/models/test_ticket_model.py`
- `tests/schemas/test_ticket_schemas.py`
- `tests/services/test_ticket_create.py`
- `tests/services/test_ticket_update.py`
- `tests/routes/test_tickets_routes.py`

**Intent source:** §3 (FR-100 – FR-104)

#### AC-100: Schema has all required fields with correct nullability [MUST]
```
  [ ] Schema introspection confirms every field from FR-100 present        (tests/migrations/test_a1_rename.py::test_new_columns_present_with_defaults)
  [ ] Nullable fields are nullable; non-nullable fields reject NULL         (tests/models/test_ticket_model.py::test_ticket_roundtrip_persistence)
  Status: NOT_STARTED
```

#### AC-101: POST /api/tickets returns 201 + id + key + version=1 [MUST]
```
  [ ] Valid payload returns 201 with id, key, and version=1                (tests/routes/test_tickets_routes.py::test_post_returns_201_with_key_and_version)
  [ ] reporter_id set to caller's actor id                                  (tests/services/test_ticket_create.py::test_create_assigns_key_and_version_one)
  Status: NOT_STARTED
```

#### AC-102: Soft-deleted tickets excluded from default reads, visible to admin [MUST]
```
  [ ] GET /api/tickets excludes deleted_at IS NOT NULL tickets              (tests/routes/test_tickets_routes.py)
  [ ] Admin read includes soft-deleted tickets                              (tests/routes/test_tickets_routes.py)
  Status: NOT_STARTED
```

#### AC-103: Concurrent updates produce one 200 (version K+1) and one 409 [MUST]
```
  [ ] Two concurrent writers on same ticket: exactly one wins               (tests/services/test_ticket_update.py::test_concurrent_update_loser_gets_stale_version_error)
  [ ] Winner's version = K+1; loser's 409 body carries current_version=K+1 (tests/services/test_ticket_update.py::test_update_bumps_version)
  Status: NOT_STARTED
```

#### AC-104: 409 body includes current row [MUST]
```
  [ ] 409 response body contains full current ticket row                   (tests/routes/test_tickets_routes.py::test_patch_conflict_returns_409_with_current_version)
  Status: NOT_STARTED
```

#### AC-105: Unknown `type` → 400 REST / -32602 MCP, both naming `type` field [MUST]
```
  [ ] REST: unknown ticket_type → 400 with `fields` array naming `type`    (tests/routes/test_tickets_routes.py::test_invalid_transition_returns_400)
  [ ] MCP: unknown ticket_type → -32602 with data.fields naming `type`     (tests/mcp/test_create_ticket_tool.py)
  [ ] Both error payloads include correlation_id                            (tests/routes/test_tickets_routes.py::test_x_correlation_id_header_present)
  Status: NOT_STARTED
```

#### AC-106: Key not reused after soft-delete: N → tombstone → N+1 [MUST]
```
  [ ] Create, soft-delete, create again yields keys N, then N+1            (tests/services/test_ticket_create.py)
  [ ] Soft-deleted row's key is never reassigned                            (tests/services/test_ticket_create.py)
  Status: NOT_STARTED
```

#### AC-107: List with `fields=id,status,version` returns only those keys [SHOULD]
```
  [ ] Sparse fieldset request returns only the requested fields             (tests/routes/test_tickets_routes.py)
  [ ] Other fields absent from response                                     (tests/routes/test_tickets_routes.py)
  Status: NOT_STARTED
```

#### AC-108: Cursor pagination never repeats/skips rows in stable-sorted sets [SHOULD]
```
  [ ] Paginate through 100+ tickets: no row appears twice                  (tests/services/test_ticket_list.py::test_cursor_stable_under_concurrent_insert)
  [ ] No row is skipped across page boundaries                              (tests/services/test_ticket_list.py)
  Status: NOT_STARTED
```

---

### Hierarchy (`app/services/tickets.py` — hierarchy paths)

**Test files planned:**
- `tests/services/test_ticket_create.py`
- `tests/services/test_ticket_subtree.py`

**Intent source:** §4 (FR-120 – FR-122)

#### AC-120: Child at depth >5 returns 400 [MUST]
```
  [ ] Creating ticket whose parent chain is already depth 5 → 400          (tests/services/test_ticket_create.py::test_create_rejects_depth_exceeded)
  Status: NOT_STARTED
```

#### AC-121: Adding 201st child returns 400 [MUST]
```
  [ ] Adding 201st child to a parent → 400                                 (tests/services/test_ticket_create.py)
  Status: NOT_STARTED
```

#### AC-122: `get_subtree` returns all descendants in one round trip [MUST]
```
  [ ] 4-level epic: single DB call returns root + all descendants           (tests/services/test_ticket_subtree.py::test_subtree_one_round_trip_depth_five)
  [ ] Soft-deleted descendants excluded                                     (tests/services/test_ticket_subtree.py::test_subtree_excludes_soft_deleted)
  Status: NOT_STARTED
```

#### AC-123: Setting `parent_id = self_or_descendant` returns 400 `cycle_detected` [MUST]
```
  [ ] Setting parent_id to self → 400 with code `cycle_detected`           (tests/services/test_ticket_update.py)
  [ ] Setting parent_id to a descendant → 400 with code `cycle_detected`   (tests/services/test_ticket_update.py)
  Status: NOT_STARTED
```

#### AC-124: Reparenting is atomic; audit row carries before+after parent_id [SHOULD]
```
  [ ] Move subtree: parent_id updated atomically                            (tests/services/test_ticket_update.py)
  [ ] Audit row contains parent_id.before and parent_id.after fields        (tests/services/test_ticket_update.py)
  Status: NOT_STARTED
```

---

### Status Transitions & Workflow (`app/services/tickets.py` — transition, `app/services/board.py`)

**Test files planned:**
- `tests/services/test_ticket_transition.py`

**Intent source:** §5 (FR-130 – FR-132)

#### AC-130: Forbidden transition → 400 `invalid_transition` [MUST]
```
  [ ] Transition to status not in allowed_to → 400 invalid_transition      (tests/services/test_ticket_transition.py::test_invalid_transition_rejected)
  Status: NOT_STARTED
```

#### AC-131: Closing epic with open child → 409 `children_open` [MUST]
```
  [ ] Epic close blocked by one open child: 409 with blocking_child_ids    (tests/services/test_ticket_transition.py::test_epic_close_blocked_by_open_child)
  Status: NOT_STARTED
```

#### AC-132: Under contention, epic-close is all-or-nothing [MUST]
```
  [ ] Concurrent reopen of child during epic close: all-or-nothing outcome  (tests/services/test_ticket_transition.py::test_concurrent_epic_close_no_deadlock)
  [ ] No partial state: child reopened after epic close is impossible        (tests/services/test_ticket_transition.py)
  Status: NOT_STARTED
```

#### AC-133: Audit insert failure rolls back transition; no broadcast [MUST]
```
  [ ] Injecting fault in audit_service.record rolls back status change      (tests/services/test_ticket_transition.py::test_audit_failure_rolls_back_transition)
  [ ] No ticket.transitioned WS event emitted on rollback                  (tests/services/test_ticket_transition.py)
  Status: NOT_STARTED
```

---

### Assignments (`app/services/tickets.py` — assign + claim)

**Test files planned:**
- `tests/services/test_ticket_assign.py`
- `tests/services/test_ticket_claim.py`

**Intent source:** §6 (FR-140 – FR-141)

#### AC-140: Assign to service-account; audit row shows actor + new assignee [MUST]
```
  [ ] Assignment to agent service-account succeeds                         (tests/services/test_ticket_assign.py::test_assign_bumps_version_and_audits)
  [ ] Audit row contains actor_id (assigner) and new assignee_id            (tests/services/test_ticket_assign.py)
  Status: NOT_STARTED
```

#### AC-141: Two concurrent `claim_ticket` calls: exactly one success, one -32010 [MUST]
```
  [ ] Concurrent claims on unassigned ticket: exactly one 200, one -32010   (tests/services/test_ticket_claim.py::test_concurrent_claims_one_wins)
  [ ] -32010 response body contains current_assignee_id                    (tests/services/test_ticket_claim.py)
  [ ] Non-agent actor attempting claim → 403 Forbidden                     (tests/services/test_ticket_claim.py::test_claim_by_non_agent_forbidden)
  Status: NOT_STARTED
```

---

### Comments (`app/services/tickets.py` — add_comment, `app/routes/ticket_comments.py`)

**Test files planned:**
- `tests/services/test_ticket_comment.py`
- `tests/routes/test_comments_routes.py`

**Intent source:** §7 (FR-145 – FR-146)

#### AC-145: Comment update endpoints return 405 [MUST]
```
  [ ] PATCH /api/tickets/{id}/comments/{cid} → 405                         (tests/routes/test_comments_routes.py::test_patch_comment_returns_405)
  [ ] DELETE /api/tickets/{id}/comments/{cid} → 405                        (tests/routes/test_comments_routes.py)
  Status: NOT_STARTED
```

#### AC-146: Comments listed in created_at ASC with stable cursoring [MUST]
```
  [ ] GET /api/tickets/{id}/comments returns created_at ASC ordering        (tests/routes/test_comments_routes.py)
  [ ] Cursor pagination across comment thread is stable                     (tests/routes/test_comments_routes.py)
  Status: NOT_STARTED
```

#### AC-147: `get_ticket` inlines up to 20 recent comments + next_cursor [SHOULD]
```
  [ ] Single ticket fetch includes `comments` array of ≤20 entries          (tests/routes/test_tickets_routes.py)
  [ ] next_cursor present when >20 comments exist                           (tests/routes/test_tickets_routes.py)
  Status: NOT_STARTED
```

---

### Labels / Custom Fields (`app/models/ticket.py`, `app/schemas/tickets.py`)

**Test files planned:**
- `tests/services/test_ticket_list.py`
- `tests/schemas/test_ticket_schemas.py`

**Intent source:** §8 (FR-150 – FR-151)

#### AC-150: `?label=blocked` exact-match filter [MUST]
```
  [ ] Filter returns only tickets whose labels contains `blocked`            (tests/services/test_ticket_list.py::test_filter_by_label_exact_match)
  [ ] Partial string match (e.g. `block`) does NOT return `blocked` tickets  (tests/services/test_ticket_list.py)
  Status: NOT_STARTED
```

#### AC-151: custom_fields array root → 400; object round-trips byte-for-byte [MUST]
```
  [ ] custom_fields=[1,2,3] → 400 at schema validation layer               (tests/schemas/test_ticket_schemas.py::test_create_rejects_array_custom_fields)
  [ ] Object-shaped custom_fields round-trips without mutation              (tests/schemas/test_ticket_schemas.py)
  Status: NOT_STARTED
```

---

### Search & Filter (`app/services/tickets.py` — search + list)

**Test files planned:**
- `tests/services/test_ticket_list.py`
- `tests/services/test_ticket_search.py`

**Intent source:** §9 (FR-160 – FR-161)

#### AC-160: All enumerated filters exercised; pagination stable under concurrent inserts [MUST]
```
  [ ] status filter returns correct subset                                  (tests/services/test_ticket_list.py)
  [ ] type, priority, assignee_id, reporter_id, parent_id filters verified  (tests/services/test_ticket_list.py)
  [ ] labels any/all filter verified                                        (tests/services/test_ticket_list.py)
  [ ] created_at, updated_at, due_date range filters verified               (tests/services/test_ticket_list.py)
  [ ] Pagination stable under concurrent inserts (1000-row set)             (tests/services/test_ticket_list.py::test_cursor_stable_under_concurrent_insert)
  Status: NOT_STARTED
```

#### AC-161: Cursor pagination over 1000-ticket set: no duplicates/gaps [MUST]
```
  [ ] Full paginated traversal collects exactly 1000 unique ticket IDs      (tests/services/test_ticket_list.py)
  Status: NOT_STARTED
```

#### AC-162: FTS: two-word query ranks double-hit tickets above single-hit [MUST]
```
  [ ] "login bug" query: ticket with both words ranked above ticket with one (tests/services/test_ticket_search.py::test_fts_ranks_two_word_hits_above_one_word)
  [ ] Empty query falls through to filter-only behavior                     (tests/services/test_ticket_search.py::test_empty_query_falls_through_to_list)
  Status: NOT_STARTED
```

---

### Kanban Board View (`frontend/src/pages/Kanban/BoardPage.tsx`, `frontend/src/components/KanbanBoard.tsx`)

**Test files planned:**
- `frontend/src/components/__tests__/KanbanBoard.test.tsx`
- `frontend/src/store/__tests__/boardStore.test.ts`

**Intent source:** §10 (FR-170 – FR-172)

#### AC-170: Drag to disallowed column → optimistic move + rollback + toast [MUST]
```
  [ ] DnD to forbidden column triggers optimistic state transition          (frontend/src/components/__tests__/KanbanBoard.test.tsx::dragging_to_disallowed_column_rolls_back)
  [ ] 400 response rolls back card to original column                       (frontend/src/components/__tests__/KanbanBoard.test.tsx)
  [ ] Toast displays server's invalid_transition message                    (frontend/src/components/__tests__/KanbanBoard.test.tsx)
  Status: NOT_STARTED
```

#### AC-171: Agent-moved card appears on all boards within 1 s [MUST]
```
  [ ] WS event applyEvent() updates column membership in store              (frontend/src/store/__tests__/boardStore.test.ts::applyEvent_server_state_wins)
  [ ] Server state wins over local optimistic state on conflict             (frontend/src/store/__tests__/boardStore.test.ts)
  Status: NOT_STARTED
```

#### AC-172: Inline "+" creates ticket with column's status, version=1 [SHOULD]
```
  [ ] Clicking "+" in column reveals title input                            (frontend/src/components/__tests__/TicketCreateModal.test.tsx)
  [ ] Submit creates ticket with column's default status                    (frontend/src/components/__tests__/TicketCreateModal.test.tsx::creates_with_default_status_of_column)
  [ ] Created ticket version=1                                              (frontend/src/components/__tests__/TicketCreateModal.test.tsx)
  Status: NOT_STARTED
```

---

### Hierarchy Tree View (`frontend/src/components/HierarchyTreeView.tsx`)

**Test files planned:**
- `frontend/src/components/__tests__/HierarchyTreeView.test.tsx`

**Intent source:** §11 (FR-175)

#### AC-175: 5-level subtree renders in one network round trip; no per-node refetch [MUST]
```
  [ ] Component renders all nodes from single subtree API response          (frontend/src/components/__tests__/HierarchyTreeView.test.tsx::single_fetch_renders_depth_five)
  [ ] Expanding a collapsed node triggers no additional API calls           (frontend/src/components/__tests__/HierarchyTreeView.test.tsx)
  Status: NOT_STARTED
```

---

### Agent Activity Feed (`app/services/activity.py`, `app/routes/agents.py`)

**Test files planned:**
- `tests/services/test_activity.py`
- `tests/routes/test_agents_activity_route.py`

**Intent source:** §12 (FR-178)

#### AC-178: Every MCP mutation appears in feed within 1 s with all required fields [MUST]
```
  [ ] MCP-originated mutation appears in /api/agents/activity within 1 s   (tests/routes/test_agents_activity_route.py::test_feed_within_1s_of_commit)
  [ ] Feed entry contains actor_id, actor_label, action, ticket_id, correlation_id, created_at (tests/services/test_activity.py::test_only_agent_actions_returned)
  [ ] Human-originated mutations do NOT appear in agent feed                (tests/services/test_activity.py)
  Status: NOT_STARTED
```

---

### Audit Log (`app/services/audit.py`, `alembic/versions/a6_add_agent_accounts_and_audit_log.py`)

**Test files planned:**
- `tests/services/test_audit.py`
- `tests/migrations/test_a6_audit_agents.py`

**Intent source:** §13 (FR-180 – FR-181)

#### AC-180: Every state-changing op produces one audit row with correct before/after [MUST]
```
  [ ] create: audit row with before={}, after=ticket.to_dict()             (tests/services/test_ticket_create.py::test_create_records_audit_row)
  [ ] update: audit row with changed fields reflected in before/after       (tests/services/test_ticket_update.py::test_update_rolls_back_audit_on_failure)
  [ ] transition: audit row with status before/after                        (tests/services/test_ticket_transition.py)
  [ ] link: audit row for TicketLink creation                               (tests/services/test_ticket_link.py)
  [ ] comment: audit row for comment creation                               (tests/services/test_ticket_comment.py)
  [ ] assignment: audit row with assignee before/after                      (tests/services/test_ticket_assign.py)
  Status: NOT_STARTED
```

#### AC-181: Audit insert failure rolls back parent operation [MUST]
```
  [ ] Fault injected into AuditService.record → parent op rolled back      (tests/services/test_audit.py::test_rolls_back_with_parent_tx)
  Status: NOT_STARTED
```

#### AC-182: Code search confirms no UPDATE/DELETE against audit_log in app/ [MUST]
```
  [ ] Static analysis / grep confirms no UPDATE/DELETE on audit_log        (tests/migrations/test_a6_audit_agents.py::test_audit_log_no_update_delete_grant)
  Status: NOT_STARTED
```

#### AC-183: UPDATE/DELETE via app DB connection fails [MUST]
```
  [ ] Direct UPDATE attempt via app role raises DB permission error         (tests/migrations/test_a6_audit_agents.py)
  Status: NOT_STARTED
```

---

### Notifications / WebSocket (`app/routes/ws.py`, `app/services/delivery.py`)

**Test files planned:**
- `tests/routes/test_ws.py`
- `tests/services/test_delivery.py`

**Intent source:** §14 (FR-185 – FR-187)

#### AC-185: Every mutation → exactly one WS event of correct type within 1 s [MUST]
```
  [ ] ticket.created event broadcast after successful create                (tests/routes/test_ws.py::test_subscribe_and_receive_ticket_created)
  [ ] ticket.updated event broadcast after successful update                (tests/routes/test_ws.py)
  [ ] ticket.transitioned event broadcast after transition                  (tests/routes/test_ws.py)
  [ ] ticket.linked event broadcast after link creation                     (tests/routes/test_ws.py)
  [ ] ticket.commented event broadcast after comment creation               (tests/routes/test_ws.py)
  [ ] agent.activity event broadcast after agent mutation                   (tests/routes/test_ws.py)
  Status: NOT_STARTED
```

#### AC-186: Subscriber without read access to project P receives no events for P [MUST]
```
  [ ] Subscribing without project read access: no events delivered          (tests/routes/test_ws.py::test_no_events_for_unsubscribed_project)
  Status: NOT_STARTED
```

#### AC-187: correlation_id in WS event matches X-Correlation-Id of trigger [MUST]
```
  [ ] WS event envelope includes correlation_id field                       (tests/services/test_delivery.py::test_event_payload_has_correlation_id_field)
  [ ] correlation_id in event matches the triggering request's trace_id     (tests/services/test_delivery.py)
  Status: NOT_STARTED
```

#### AC-188: WS connection with service-account API key closed with 401 [MUST]
```
  [ ] Bearer token in WS connect → connection closed with 4401             (tests/routes/test_ws.py::test_bearer_header_rejected_at_connect)
  Status: NOT_STARTED
```

---

### MCP Server Tools (`app/mcp_server/`)

**Test files planned:**
- `tests/mcp/test_tools_list.py`
- `tests/mcp/test_create_ticket_tool.py`
- `tests/mcp/test_update_status_tool.py`
- `tests/mcp/test_claim_tool.py`
- `tests/mcp/test_link_tool.py`
- `tests/mcp/test_mcp_auth.py`
- `tests/mcp/test_correlation.py`

**Intent source:** §15 (FR-200 – FR-212)

#### AC-200: MCP `tools/list` returns exactly 10 tools with input schemas [MUST]
```
  [ ] tools/list response contains exactly 10 tool definitions              (tests/mcp/test_tools_list.py::test_returns_ten_tools_with_input_schemas)
  [ ] Each tool entry has name + description + inputSchema                  (tests/mcp/test_tools_list.py)
  Status: NOT_STARTED
```

#### AC-201: `create_ticket` sets caller as reporter_id [MUST]
```
  [ ] Tool creates ticket with caller service-account as reporter_id        (tests/mcp/test_create_ticket_tool.py::test_creates_and_returns_correlation_id)
  [ ] Response includes ticket_key, id, version, correlation_id            (tests/mcp/test_create_ticket_tool.py)
  Status: NOT_STARTED
```

#### AC-202: All §5 error cases reachable via `update_status` with identical codes [MUST]
```
  [ ] Stale version via MCP → -32004 with current_version                  (tests/mcp/test_update_status_tool.py::test_stale_returns_32004_with_current_version)
  [ ] children_open via MCP → -32005 with blocking_child_ids               (tests/mcp/test_update_status_tool.py::test_epic_close_returns_32005_with_blocking_children)
  [ ] invalid_transition via MCP → -32602                                  (tests/mcp/test_update_status_tool.py)
  Status: NOT_STARTED
```

#### AC-203: Assigning to unknown actor → -32602 naming `assignee` [MUST]
```
  [ ] Unknown assignee → -32602 with data.fields[0].name == "assignee"     (tests/mcp/test_tools_list.py)
  Status: NOT_STARTED
```

#### AC-204: Concurrent `claim` calls: one success, one -32010 (mirrors AC-141) [MUST]
```
  [ ] Two concurrent claim tool calls: one success, one -32010             (tests/mcp/test_claim_tool.py::test_two_agents_one_wins_one_32010)
  [ ] -32010 body includes current_assignee_id                             (tests/mcp/test_claim_tool.py)
  Status: NOT_STARTED
```

#### AC-205: MCP-created comments indistinguishable from REST except author_type [MUST]
```
  [ ] MCP comment appears in comment list with author_type='agent'          (tests/mcp/test_tools_list.py)
  [ ] Body content identical to REST-created comment body                  (tests/mcp/test_tools_list.py)
  Status: NOT_STARTED
```

#### AC-206: `list_my_tickets` never returns tickets not assigned to caller [MUST]
```
  [ ] Results contain only caller-assigned tickets                          (tests/mcp/test_tools_list.py)
  [ ] Other agents' tickets absent from response                           (tests/mcp/test_tools_list.py)
  Status: NOT_STARTED
```

#### AC-207: Single round trip: ticket + 20 comments + optional subtree [MUST]
```
  [ ] get_ticket with include_comments=true returns ≤20 comments inline     (tests/mcp/test_tools_list.py)
  [ ] get_ticket with include_subtree=true returns full hierarchy to depth 5 (tests/mcp/test_tools_list.py)
  Status: NOT_STARTED
```

#### AC-208: Duplicate link → -32011 [MUST]
```
  [ ] Second identical link_tickets call → -32011 link_exists              (tests/mcp/test_link_tool.py::test_duplicate_returns_32011)
  Status: NOT_STARTED
```

#### AC-209: Identical filter inputs → identical row IDs across REST and MCP [MUST]
```
  [ ] search_tickets and REST /api/tickets produce same IDs for same filters (tests/mcp/test_tools_list.py)
  Status: NOT_STARTED
```

#### AC-210: Comment created iff transition succeeds; both rolled back on failure [MUST]
```
  [ ] Successful transition with comment_body: both committed               (tests/mcp/test_tools_list.py)
  [ ] Failed transition (stale version): comment not created                (tests/mcp/test_tools_list.py)
  Status: NOT_STARTED
```

#### AC-211: correlation_id in every tool result matches OTel trace_id [MUST]
```
  [ ] correlation_id present in success response                           (tests/mcp/test_correlation.py::test_every_response_has_correlation_id_equal_to_trace_id)
  [ ] correlation_id present in error response                             (tests/mcp/test_correlation.py)
  [ ] correlation_id equals active span's trace_id                         (tests/mcp/test_correlation.py)
  Status: NOT_STARTED
```

#### AC-212: `tools/list` for version-taking tools includes retry-contract note [SHOULD]
```
  [ ] update_status description contains retry-contract text               (tests/mcp/test_tools_list.py::test_retry_contract_in_description_for_version_tools)
  [ ] assign, transition, link_tickets descriptions contain retry-contract  (tests/mcp/test_tools_list.py)
  Status: NOT_STARTED
```

#### AC-200–AC-211 (auth cross-cut): Missing bearer → -32001 [MUST]
```
  [ ] MCP request without Authorization header → -32001                    (tests/mcp/test_mcp_auth.py::test_missing_bearer_returns_32001)
  [ ] Revoked key → -32001                                                 (tests/mcp/test_mcp_auth.py)
  Status: NOT_STARTED
```

---

### Service-Account Auth & API Keys (`app/services/agent_accounts.py`, `app/auth/bearer.py`)

**Test files planned:**
- `tests/services/test_agent_accounts.py`
- `tests/auth/test_bearer_middleware.py`
- `tests/routes/test_agents_routes.py`

**Intent source:** §16 (FR-220 – FR-223)

#### AC-220: Re-reading a key after creation never returns plaintext [MUST]
```
  [ ] GET agent returns no api_key field after creation                     (tests/services/test_agent_accounts.py::test_create_returns_plaintext_once)
  [ ] DB row contains only hashed value, not plaintext                      (tests/services/test_agent_accounts.py)
  Status: NOT_STARTED
```

#### AC-221: Stored key matches via verify-only [MUST]
```
  [ ] argon2id.verify(stored_hash, plaintext) succeeds                     (tests/services/test_agent_accounts.py)
  [ ] Plain equality check hash==plaintext fails                            (tests/services/test_agent_accounts.py)
  Status: NOT_STARTED
```

#### AC-222: Revoking a key blocks next request within ≤5 s [MUST]
```
  [ ] Revoked key rejected within 5 s (TTLCache invalidation)              (tests/services/test_agent_accounts.py::test_revoke_blocks_next_request_within_5s)
  [ ] Previously authenticated request with same key now returns 401        (tests/services/test_agent_accounts.py)
  Status: NOT_STARTED
```

#### AC-223: MCP-originated audit rows carry calling service-account [MUST]
```
  [ ] Audit row actor_id equals the MCP caller's service_account_id         (tests/services/test_agent_accounts.py)
  [ ] Audit row actor_type = 'agent'                                        (tests/services/test_agent_accounts.py)
  Status: NOT_STARTED
```

#### AC-224: Exceeding write rate → 429 + retry_after_ms; below threshold → no 429 [SHOULD]
```
  [ ] 31st write in 1 min → 429 with retry_after_ms                        (tests/middleware/test_rate_limit.py::test_write_rate_limit_returns_429)
  [ ] 30th write in 1 min → 200 (no throttle)                              (tests/middleware/test_rate_limit.py::test_below_threshold_no_429)
  [ ] MCP equivalent: -32020 with retry_after_ms                           (tests/middleware/test_rate_limit.py)
  Status: NOT_STARTED
```

---

### OpenTelemetry Instrumentation (`app/observability/`)

**Test files planned:**
- `tests/observability/test_otel_init.py`
- `tests/observability/test_logging.py`
- `tests/middleware/test_correlation.py`
- `tests/observability/test_traced.py`
- `tests/observability/test_metrics.py`

**Intent source:** §17 (FR-230 – FR-234)

#### AC-230: Startup logs confirm OTLP exporter; smoke trace in Jaeger within 5 s [MUST]
```
  [ ] init_otel() logs successful exporter registration                    (tests/observability/test_otel_init.py::test_init_registers_otlp_exporter)
  [ ] OTLP unreachable: request still succeeds, warning logged             (tests/observability/test_otel_init.py::test_otlp_unreachable_does_not_fail_request)
  Status: NOT_STARTED
```

#### AC-231: Jaeger query by correlation_id/actor_id/project_id/ticket_id returns spans [MUST]
```
  [ ] Span has actor_id, actor_type attributes set                         (tests/observability/test_traced.py::test_actor_attrs_recorded)
  [ ] Span has project_id, ticket_id attributes when present               (tests/observability/test_traced.py)
  [ ] Span error status set on exception                                    (tests/observability/test_traced.py::test_error_marks_span_status)
  [ ] Span name reflects service method or route                            (tests/observability/test_traced.py::test_decorator_creates_named_span)
  Status: NOT_STARTED
```

#### AC-232: Audit row's correlation_id present in Jaeger trace AND log stream [MUST]
```
  [ ] Log records under an active span contain trace_id and span_id        (tests/observability/test_logging.py::test_log_line_includes_trace_id)
  [ ] X-Correlation-Id header equals active span's trace_id               (tests/middleware/test_correlation.py::test_x_correlation_id_header_equals_trace_id)
  [ ] audit_log.correlation_id = current_trace_id() value at write time    (tests/services/test_audit.py)
  Status: NOT_STARTED
```

#### AC-233: OTLP metrics export contains all named metrics [MUST]
```
  [ ] tickets_created_total increments on create                           (tests/observability/test_metrics.py::test_counter_increments_on_create)
  [ ] db_conflict_total increments on 409 response                         (tests/observability/test_metrics.py::test_outcome_label_set_on_conflict)
  [ ] tickets_transitioned_total has {from, to} labels                      (tests/observability/test_metrics.py)
  [ ] mcp_tool_calls_total has {tool, outcome} labels                       (tests/observability/test_metrics.py)
  [ ] request_duration_ms histogram present per route/tool                  (tests/observability/test_metrics.py)
  Status: NOT_STARTED
```

#### AC-234: Inbound `traceparent` produces child span with supplied trace_id [SHOULD]
```
  [ ] Request with valid traceparent header: response span is child of supplied trace (tests/middleware/test_traceparent.py::test_inbound_traceparent_continues_trace)
  Status: NOT_STARTED
```

---

### Non-Functional Requirements (`tests/e2e/`)

**Test files planned:**
- `tests/e2e/test_three_agent_demo.py`

**Intent source:** §18 (NFR-900 – NFR-906)

#### AC-900: Load test — 0 lost updates, structured 409s, 0 deadlocks, ≥50 writes/sec [MUST]
```
  [ ] 10 concurrent writers × 1000 ops: zero lost updates (before+delta == after) (tests/e2e/test_three_agent_demo.py::test_no_lost_updates)
  [ ] Every 409 carries actual current version                              (tests/e2e/test_three_agent_demo.py)
  [ ] No deadlocks detected                                                 (tests/e2e/test_three_agent_demo.py)
  [ ] Throughput ≥50 successful writes/sec                                  (tests/e2e/test_three_agent_demo.py)
  Status: NOT_STARTED
```

#### AC-901: P95 latency targets met under NFR-900 workload [SHOULD]
```
  [ ] Single-ticket create/update/transition P95 < 300 ms                  (tests/e2e/test_three_agent_demo.py::test_p95_latency_under_targets)
  [ ] Single-ticket read P95 < 150 ms                                       (tests/e2e/test_three_agent_demo.py)
  [ ] Subtree read (depth ≤5, ≤200 children) P95 < 500 ms                  (tests/e2e/test_three_agent_demo.py)
  [ ] Search/filter page P95 < 400 ms                                       (tests/e2e/test_three_agent_demo.py)
  Status: NOT_STARTED
```

#### AC-902: 100 sampled requests: every one has Jaeger trace, trace_id matches header [MUST]
```
  [ ] 100% of sampled requests (incl. 4xx/5xx) have a Jaeger trace          (tests/e2e/test_three_agent_demo.py)
  [ ] trace_id matches X-Correlation-Id in each response                   (tests/e2e/test_three_agent_demo.py)
  Status: NOT_STARTED
```

#### AC-903: Chaos test — 0 committed state changes without matching audit row [MUST]
```
  [ ] Fault between mutation and audit insert: SQL LEFT JOIN shows no orphans (tests/e2e/test_three_agent_demo.py::test_audit_completeness)
  [ ] No orphaned audit rows (audit row without state change)               (tests/e2e/test_three_agent_demo.py)
  Status: NOT_STARTED
```

#### AC-904: Every error class in NFR-904 table exercised with status + body assertions [MUST]
```
  [ ] 400 / -32602: validation error with fields array                      (tests/routes/test_tickets_routes.py)
  [ ] 401 / -32001: auth missing/invalid                                   (tests/auth/test_bearer_middleware.py)
  [ ] 403 / -32002: forbidden                                              (tests/routes/test_tickets_routes.py)
  [ ] 404 / -32003: not found                                              (tests/routes/test_tickets_routes.py)
  [ ] 409 / -32004: stale version with current_version                     (tests/routes/test_tickets_routes.py)
  [ ] 409 / -32005: children_open with blocking_child_ids                  (tests/routes/test_tickets_routes.py)
  [ ] 409 / -32010: already_claimed with current_assignee_id               (tests/routes/test_tickets_routes.py)
  [ ] 409 / -32011: link_exists                                            (tests/routes/test_links_routes.py)
  [ ] 429 / -32020: rate_limited with retry_after_ms                       (tests/middleware/test_rate_limit.py)
  [ ] 500 / -32000: internal error with correlation_id                     (tests/routes/test_tickets_routes.py)
  [ ] All error bodies contain correlation_id                               (tests/routes/test_tickets_routes.py)
  Status: NOT_STARTED
```

#### AC-905: Every threshold from config key; non-default changes runtime behavior [MUST]
```
  [ ] MAX_HIERARCHY_DEPTH config key changes depth enforcement              (tests/test_config.py::test_otel_endpoint_loaded_from_env)
  [ ] MAX_CHILDREN_PER_PARENT config key changes child limit               (tests/test_config.py)
  [ ] OTEL_EXPORTER_OTLP_ENDPOINT config key loads from env               (tests/test_config.py)
  [ ] Rate-limit thresholds load from config                               (tests/test_config.py)
  Status: NOT_STARTED
```

#### AC-906: Stopping Jaeger: zero requests fail; restarting resumes export [MUST]
```
  [ ] OTLP exporter error does not propagate to HTTP response              (tests/observability/test_otel_init.py::test_otlp_unreachable_does_not_fail_request)
  [ ] WS broadcast failure does not roll back DB transaction                (tests/services/test_delivery.py::test_failed_send_does_not_raise)
  Status: NOT_STARTED
```

---

## Cross-Cutting Coverage

### Cross-Cutting: OCC + Audit + Concurrency (NFR-900, FR-101, FR-180, NFR-903)

**Requirement:** Every write either commits atomically (version bump + audit row + broadcast enqueued) or rolls back entirely. No partial state.

```
  [ ] Create: version=1, one audit row, broadcast after commit             (tests/services/test_ticket_create.py::test_create_emits_broadcast_only_after_commit)
  [ ] Update: version K→K+1, one audit row, loser gets 409                 (tests/services/test_ticket_update.py)
  [ ] Transition: version bump + audit + broadcast in same TX              (tests/services/test_ticket_transition.py)
  [ ] Claim: race-free assignment, exactly one winner                      (tests/services/test_ticket_claim.py)
  [ ] Chaos: audit fault → parent op rollback (no orphan commits)          (tests/e2e/test_three_agent_demo.py::test_audit_completeness)
  Status: NOT_STARTED
```

### Cross-Cutting: Structured Error Contract (NFR-904, FR-102)

**Requirement:** REST and MCP return structurally identical error shapes for the same domain exception.

```
  [ ] StaleVersionError → REST 409 and MCP -32004 carry same fields        (tests/routes/test_tickets_routes.py + tests/mcp/test_update_status_tool.py)
  [ ] ValidationError → REST 400 and MCP -32602 carry same fields array    (tests/routes/test_tickets_routes.py + tests/mcp/test_create_ticket_tool.py)
  [ ] All error responses include correlation_id                           (tests/middleware/test_correlation.py + tests/mcp/test_correlation.py)
  Status: NOT_STARTED
```

### Cross-Cutting: Correlation ID Propagation (NFR-902, FR-186, FR-211, FR-232)

**Requirement:** A single correlation_id (= OTel trace_id) flows through REST header, MCP response, WS event, audit row, and log record for every request.

```
  [ ] REST: X-Correlation-Id header = trace_id                            (tests/middleware/test_correlation.py)
  [ ] MCP: correlation_id in result = trace_id                             (tests/mcp/test_correlation.py)
  [ ] WS event: correlation_id field = triggering request's trace_id       (tests/services/test_delivery.py)
  [ ] Audit row: correlation_id = trace_id of committing TX                (tests/services/test_audit.py)
  [ ] Log record: trace_id and span_id present under active span           (tests/observability/test_logging.py)
  Status: NOT_STARTED
```

---

## Orphaned Tests

The following test functions in the existing test suite do not map to any Agent Kanban acceptance criterion. They cover the legacy Aion Bulletin domain. They should be **deleted** once the corresponding source modules are removed (as scoped in `05_IMPLEMENTATION.md`), or reclassified if any legacy module is retained.

| Test File | Behavior Covered | Legacy Module | Disposition |
|---|---|---|---|
| `tests/services/test_problems.py` | Problem CRUD, status transitions, search | `app/services/problems.py` (DELETE per §5) | Delete when problems.py is removed |
| `tests/services/test_solutions.py` | Solution posting, acceptance, ranking | `app/services/solutions.py` (out of scope) | Delete |
| `tests/services/test_voting.py` | Upvote / downvote counting, SELECT FOR UPDATE | `app/services/voting.py` (out of scope) | Delete |
| `tests/services/test_leaderboard.py` | Leaderboard ranking computation | `app/services/leaderboard.py` (out of scope) | Delete |
| `tests/services/test_notifications.py` | WATCH_ROUTING, fan-out delivery | `app/services/notifications.py` (out of scope) | Delete |
| `tests/services/test_comments.py` | Comment posting on problems | `app/services/comments.py` (out of scope) | Delete |
| `tests/services/test_attachments.py` | File-type allowlist, size limits | `app/services/attachments.py` (out of scope) | Delete |
| `tests/services/test_admin.py` | Admin domain operations | Legacy admin routes | Delete |
| `tests/auth/test_magic_link.py` | Passwordless email auth | `app/auth/magic_link.py` | Evaluate: magic-link auth may be retained for human users |
| `tests/auth/test_jwt.py` | JWT encode/decode, expiry | `app/auth/jwt.py` | Evaluate: JWT may remain for human session auth |
| `tests/auth/test_oidc.py` | OIDC token validation | `app/auth/oidc.py` | Evaluate: OIDC retained for human login |
| `tests/auth/test_dependencies.py` | FastAPI auth dependency injection | `app/auth/dependencies.py` (MODIFY per §5) | Update when dependencies.py is modified in Task A8 |
| `tests/middleware/test_security.py` | HTML sanitization, security headers | `app/middleware/security.py` | Evaluate: security headers retained (SecurityHeadersMiddleware) |
| `tests/middleware/test_rate_limit.py` | In-process rate bucket | `app/middleware/rate_limit.py` (MODIFY per C5) | Superseded by AC-224 tests; delete old tests after C5 lands |
| `tests/routes/` (empty `__init__.py`) | — | — | No existing route tests |
| `tests/test_enums.py` | Legacy enum exhaustiveness | Old `app/enums.py` | Replace with Agent Kanban enum tests after A6 lands |
| `tests/test_exceptions.py` | Legacy exception hierarchy | Old `app/exceptions.py` | Supplement with Agent Kanban exception tests after A7 lands |
| `tests/test_config.py` | Settings construction, secrets, defaults | `app/config.py` (MODIFY per C4) | Add new Agent Kanban config key tests; existing tests remain valid |
| `tests/test_known_gaps.py` | Documented spec divergences (legacy) | Various legacy modules | Delete when legacy modules are removed |
| `tests/test_main.py` | App factory smoke test | `app/main.py` (MODIFY per §3.7) | Update after main.py rewrite in Task C1 |
| `tests/test_schemas.py` | Legacy Pydantic schema validation | Old `app/schemas.py` | Superseded by Agent Kanban schema tests after A6 |

---

## Hypothesis-Test Candidates

The following invariants are strong candidates for property-based testing (Hypothesis). They are mathematically characterizable, hold over all inputs, and are particularly important because unit tests with specific examples can miss off-by-one violations or subtle concurrency races.

### H-1: Version Monotonicity

**Invariant:** For any ticket, the sequence of committed `version` values observed in the `audit_log` (ordered by `created_at`) is a strictly increasing sequence starting at 1 with no gaps.

**Formal statement:** For all audit rows on entity_type='ticket' for a given ticket ID, sorted by created_at:
- `version[0] == 1` (created by the create op)
- `version[i+1] == version[i] + 1` for all i (no skips, no repeats)

**Why property-test:**
- A simple parametric test with 2–3 concurrent writers cannot exhaustively cover all interleaving patterns.
- Hypothesis + a Postgres transactional fixture can generate arbitrary write sequences (create, update, transition, assign) and assert the invariant on every run.

**Suggested test:** `tests/properties/test_version_monotonicity.py::test_version_is_always_strictly_increasing`

```python
@given(
    ops=st.lists(
        st.sampled_from(["update_title", "transition", "assign", "add_label"]),
        min_size=1, max_size=50
    )
)
@settings(max_examples=200)
def test_version_is_always_strictly_increasing(ops, db_session, create_ticket):
    ticket = create_ticket(db_session)
    for op in ops:
        apply_op(db_session, ticket.id, op)
    versions = get_audit_versions(db_session, ticket.id)
    assert versions == list(range(1, len(versions) + 1))
```

**Scope:** All write paths in `TicketService` (create, update, transition, assign, claim, add_comment — those that bump version).

---

### H-2: Audit Row Count == State Change Count

**Invariant:** For any ticket, `COUNT(audit_log WHERE entity_id=ticket.id)` equals the total number of state-changing operations applied to that ticket (create + every version bump + every comment + every link).

**Formal statement:** Let S = sequence of operations applied. Let A = set of audit rows for this ticket. Then `|A| == |S|`.

**Why property-test:**
- The danger is a code path that mutates state but forgets to call `audit_service.record` — only detectable if you exhaustively exercise all operation types.
- Hypothesis generates random sequences of mixed operations; assertion is checked after each flush.

**Suggested test:** `tests/properties/test_audit_completeness.py::test_audit_row_count_equals_operation_count`

```python
@given(
    op_sequence=st.lists(
        st.sampled_from(["create", "update", "transition", "assign", "claim",
                         "add_comment", "link", "soft_delete"]),
        min_size=1, max_size=30
    )
)
@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
def test_audit_row_count_equals_operation_count(op_sequence, db_session):
    results = apply_op_sequence(db_session, op_sequence)  # returns (ticket_id, count_of_state_changes)
    actual_audit_count = count_audit_rows(db_session, results.ticket_id)
    assert actual_audit_count == results.state_change_count
```

**Scope:** Every call site of `audit_service.record` across all `TicketService` methods and comment/link paths.

---

### H-3: Hierarchy Parent_id Never Cycles

**Invariant:** For any set of reparenting operations applied to a set of tickets, the resulting adjacency list is always a forest (set of trees). No ticket can be its own ancestor.

**Formal statement:** For all tickets T in the system: the path from T to the root (following parent_id chains) is a finite, non-repeating sequence, i.e., `∀ T: T ∉ ancestors(T)`.

**Why property-test:**
- A cyclic graph requires at least 2 nodes pointing to each other. The `parent_id = self` case is caught by a CHECK constraint, but the cycle T_a → T_b → T_a requires application-layer detection via the recursive-CTE cycle check in `TicketService.update`.
- Hypothesis generates random sequences of reparenting operations (including attempts to create cycles); assertion verifies no cycle exists after each op.

**Suggested test:** `tests/properties/test_hierarchy_acyclic.py::test_parent_chain_never_cycles`

```python
@given(
    reparent_ops=st.lists(
        st.tuples(st.integers(0, 9), st.integers(0, 9)),  # (child_idx, new_parent_idx)
        min_size=1, max_size=40
    )
)
@settings(max_examples=500)
def test_parent_chain_never_cycles(reparent_ops, db_session, create_ticket_pool):
    tickets = create_ticket_pool(db_session, count=10)
    for child_idx, parent_idx in reparent_ops:
        if child_idx == parent_idx:
            continue  # self-reparent — expect 400, skip
        try:
            reparent(db_session, tickets[child_idx].id, tickets[parent_idx].id)
        except (CycleDetectedError, DepthLimitError):
            pass  # expected — constraint fired correctly
    # After all ops, verify no ticket is its own ancestor
    for t in tickets:
        ancestors = get_ancestor_ids(db_session, t.id)
        assert t.id not in ancestors, f"Cycle detected: {t.id} in its own ancestor chain"
```

**Scope:** `TicketService.update` (reparenting path), `TicketService.create` (parent_id on create), and the recursive-CTE subtree read (should never infinite-loop).

---

## Self-Critique

**Recommendation:** All 75 ACs are recorded as NOT_STARTED with specific planned test file + function names taken directly from `05_IMPLEMENTATION.md`. The register is ready for use as a tracking dashboard and as input to `/write-module-tests`.

**Strongest counter-argument:** "With 75 uncovered ACs and zero existing coverage for this domain, this register is documenting the obvious — everything is missing. Is the register useful before any tests exist?"

**Why it stands:** The register is not primarily a measurement tool at this stage — it is a navigation tool. Three concrete values it delivers right now:
1. The prioritized-gaps table gives the agent implementing tests a ranked work queue without re-reading the spec.
2. The scenario decomposition (multiple bullets per AC) is finer-grained than the spec's AC text — the spec says "AC-132: all-or-nothing"; this register says which specific race condition must be exercised. That precision is what `/write-module-tests` needs.
3. The hypothesis-test candidates section is novel: it identifies three invariants that unit tests cannot reliably catch (version monotonicity, audit completeness, acyclicity) and provides ready-to-adapt pseudocode. This is standalone value regardless of baseline coverage.

The register is not a vanity artifact. It is the correct pre-work before dispatching test-writing agents.

---

## Legend

| Symbol | Meaning |
|---|---|
| `[x]` | Scenario covered by a dedicated test |
| `[~]` | Ambiguous match — test exists but coverage is uncertain |
| `[ ]` | Scenario not covered — no matching test found |
| `[!]` | CI-only validation — no dedicated test file |
| `NOT_STARTED` | No tests written for this AC yet (all entries at initialization) |
| `MUST` | Required behavior (highest priority gap) |
| `SHOULD` | Expected behavior (medium priority gap) |
| `MAY` | Optional behavior (lowest priority gap) |
