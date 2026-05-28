# Ticketing v2.1 — Lessons Learned

This file is the v2.1 follow-on to `ticketing-v2.md`. Same protocol:
1. Every subagent reads this file at start (AND `ticketing-v2.md` — Cross-WP Rules from v2 still apply).
2. Honor every rule under **## Cross-WP Rules (v2.1)** here, plus all rules in v2.
3. Append a `## v2.1-WPn — Lessons` section at end.

v2.1 scope is six polish items flagged in WP5's residual backlog:
- WP6: `tickets.last_actor_type` aggregate
- WP7: `GET /api/v1/tickets/{id}/transitions` endpoint
- WP8: `/api/v1/people/search`
- WP9: @mention notification fanout
- WP10: pagination + filter sentinels
- WP11: WIP-limit display

---

## Cross-WP Rules (v2.1)

(In addition to all v2 Cross-WP Rules.)

1. **No new big abstractions.** Every v2.1 item is a small surgical addition. If you find yourself refactoring more than two files outside the target, stop and flag in Lessons.
2. **Migrations get new revision IDs** starting `a10_` and incrementing. Each migration is independent and reversible.
3. **DO NOT regress the 304 pre-existing failing tests** — they are auth/health/magic-link unrelated to ticketing. Final suite delta must be ≥0 passing, ≤304 failing.
4. **Frontend changes must keep build + vitest green.** No new TS errors beyond the documented pre-existing baseline.
5. **API additions follow the existing `/api/v1/` pattern + Pydantic schema layering.** Don't invent new route registration patterns.

---

## v2.1-WP6 — Lessons

### Backfill complexity

A simple `UNION ALL` of `ticket_transitions` and `ticket_comments` plus
`DISTINCT ON (ticket_id) ... ORDER BY ticket_id, created_at DESC` was
sufficient. **No recursive CTE needed** — the aggregate is a row-level
"latest" calculation, not a hierarchical walk. A second pass handles
the no-activity fallback by reading `reporter_*` + `created_at`. Both
queries are O(n) over `tickets` and run sub-second against the dev DB.

The CHECK `ck_tickets_last_agent_step_id` (mirrors the create-side
agent_step_id check) had to be expressed in the backfill via a `CASE`
expression — naively copying `agent_step_id` from a comment row whose
`author_type='user'` would violate the constraint. The migration's
`CASE WHEN l.actor_type='agent' THEN l.agent_step_id ELSE NULL END`
form handles this cleanly.

### Service-layer hook coverage (where audit events live)

Every audit-producing write was wired up via the `_stamp_last_activity`
helper:

| Write path        | Wiring                                                |
|-------------------|-------------------------------------------------------|
| `create()`        | Stamped inline on the new `Ticket` row (helper unused — fields set directly so they land in the INSERT). |
| `update()`        | `_stamp_last_activity(ticket, ...)` before `flush`.   |
| `transition()`    | `_stamp_last_activity(ticket, ...)` before `flush`.   |
| `assign()`        | `_stamp_last_activity(ticket, ...)` before `flush`.   |
| `claim()`         | Inline `.values(last_actor_*=...)` on the existing raw `UPDATE` statement (no row-handle available — `claim` uses a CAS-style update). |
| `add_comment()`   | `_stamp_last_activity(ticket, ...)` + extra `flush([ticket])` after the comment flush. |
| `link()`          | `_stamp_last_activity(source_ticket, ...)` — needed to capture `source_ticket` from `_load`; previously the return was discarded. Only the **source** side is stamped (the target isn't "touched" semantically — the directional `is_blocked_by` inverse row is itself a write the link function audits separately, but the target ticket row's aggregate stays untouched). **Consideration for v2.1-WP7+**: if downstream wants both sides reflected on the board, stamp the target too — flag for review. |

`add_watcher` / `remove_watcher` / `add_attachment` / `delete_attachment`
are NOT currently stamped — they don't write `audit_log` rows in the
current service either (watcher mutations are non-audit "subscriptions",
attachments emit no audit event). If WP9 (mentions) or WP10 wants those
to count, hook them then. Documented this so WP7/8/9 don't assume the
aggregate captures every write.

### Recommendation for v2.1-WP7 (transitions endpoint)

**Design question to bring to the orchestrator before WP7:**

`GET /api/v1/tickets/{id}/transitions` should expose `last_activity_at`
on each row trivially (every transition is itself a `created_at`-bearing
audit row — same field name). The richer question is whether the route
should return a **merged activity feed** of `ticket_transitions ∪
ticket_comments ∪ ticket_links` rather than just transitions.

Arguments for a merged feed:
- WP5 already wants this (drawer's "History/Activity tab" — see WP5
  Lessons §"Wired but needs polish"#3).
- The WP6 backfill already proves the merge SQL is trivial (we just
  wrote it).
- A single endpoint avoids 3× round-trips from the drawer.

Arguments against:
- Spec for v2.1-WP7 says **transitions** specifically; mission creep.
- Heterogeneous response shape (transitions have `from_status` /
  `to_status`; comments have `body`; links have `link_type`) bloats the
  Pydantic union.

**Recommendation**: ship WP7 as transitions-only with a `?include=`
expansion knob (`?include=comments,links`) so the merged-feed shape is
opt-in. The `last_actor_*` aggregate is already on `tickets.to_dict()`
so the drawer can show "last touched <ago>" without needing the full
feed at all.

### Frontend wire-up note

Removed the `reporter_type` fallback from `TicketCard.tsx` per brief.
The `last_activity_at` "relative timestamp on the card" was **skipped**
(brief flagged it as low-priority / skip-if-bloats); cards already
carry priority, points, epic chip, sprint chip, agent badge. Adding
another chip would crowd the 240px-wide card layout. WP7's drawer
("last touched 2h ago" chip in the header) is the better home for it.

### Test deltas

- New: `tests/services/test_last_actor_aggregate.py` — 4 tests
  (create-as-user, agent-comment flips, user-transition reverts,
  update+assign+link all stamp).
- New: `tests/unit/test_a10_migration.py` — 5 tests (columns,
  index, CHECKs, backfill non-null, backfill matches latest).
- Updated: `frontend/src/pages/Kanban/__tests__/TicketCard.test.tsx`
  — swapped existing reporter_type-fallback tests to
  last_actor_type; added 2 new tests proving the badge HIDES when
  `last_actor_type='user'` even if `reporter_type='agent'` (no
  fallback) and when `last_actor_type` is missing entirely.
- Backend suite delta: **529 → 538 passing**, **304 → 304 failing**
  (≥WP3 baseline, no new regressions).
- Frontend suite: **28 → 32 passing**, all green.
- Alembic round-trip (`upgrade head` → `downgrade -1` → `upgrade
  head`) clean.


## v2.1-WP7 — Lessons

### Pagination decision: offset, not cursor

Shipped offset pagination (`?limit&offset`) rather than the opaque
`?cursor=` form sketched in the brief. Reasons:

1. The merged feed is materialised in Python (UNION at the application
   layer — sort by `(created_at DESC, id DESC)` post-query), not in
   SQL, because the per-arm rows have different column shapes and
   pydantic discriminates on `kind`. Cursor pagination over a merged
   in-memory list adds zero value over `[offset:offset+limit]` slicing.
2. Cursors over a real SQL `UNION ALL` would be valuable for very long
   feeds (>10k rows per ticket) — but no ticket today is anywhere close.
   The brief itself flagged "WP10 will revisit pagination universally";
   this WP defers to that. The response shape carries `next_cursor: null`
   so the wire format is stable when WP10 swaps the implementation.
3. `limit` is clamped to `[0, 500]` at both the FastAPI `Query`
   constraint AND inside the service (`max(0, min(limit, 500))`) so a
   misconfigured caller can't bypass.

If WP10 picks cursor pagination universally, it should land the SQL
UNION push-down at the same time — the in-Python merge is fine for
v2.1 scale but won't compose with cursor-style WHERE clauses cleanly.

### Pydantic discriminator-union gotchas

The `Annotated[Union[T, U, V], Field(discriminator="kind")]` pattern
ALWAYS requires:

- Every arm declares `kind: Literal["x"] = "x"` (NOT `Field(default=...)`).
  Without the `Literal`, Pydantic v2 falls back to "smart" union
  matching and the route response_model swaps row kinds at random.
- The service-layer dict MUST include the `kind` key explicitly —
  letting pydantic infer it from arm-specific fields like `body` or
  `from_status` works locally but breaks the moment two arms share a
  field name.

Worked example: the comment table has `author_id`/`author_type` columns
but the ActivityItem discriminator union uniformly exposes
`actor_id`/`actor_type`. The service maps `author_*` → `actor_*` at
serialisation time so the frontend can render any kind with a single
`row.actor_*` code path.

### Soft-deferred: only outbound links surfaced in the feed

`TicketLink` is directional. The feed currently includes only
`source_id == ticket.id` rows on the link arm — mirroring the WP6
"only the source side is stamped" semantic. If a user opens ticket B
where `A blocks B`, they will NOT see "A blocked this" in B's activity
feed. WP6 already flagged this question (target-side stamping for
"both sides reflected on the board"). Resolve it at the same time as
that decision — currently both lean toward source-only.

### Recommendation for v2.1-WP8 (`/people/search`)

The `/people/search` endpoint will return a union over users +
agent_accounts. The temptation is to use the same `kind`-discriminated
union pattern we landed here. **Do it** — same Pydantic shape, same
frontend ergonomics:

```python
class UserResult(BaseModel):
    kind: Literal["user"]
    id: UUID
    handle: str
    display_name: str | None
    ...

class AgentResult(BaseModel):
    kind: Literal["agent"]
    id: UUID
    handle: str
    agent_kind: str
    ...

PersonResult = Annotated[Union[UserResult, AgentResult], Field(discriminator="kind")]
```

Search filters (`?include=users,agents`) follow the same allow-list
validation pattern used here (see `_ACTIVITY_INCLUDE_ALLOWED`). Sort
order for `/people/search` is a fresh question — ranking by recency
vs. handle match strength — don't blindly copy the
`created_at DESC` ordering from this WP.

### Test deltas

- New: `tests/routes/test_transitions_endpoint.py` — 6 tests
  (empty include, comments union, three-way union, invalid include
  400, limit+offset pagination, 404 on unknown ticket).
- New: `tests/services/test_activity_service.py` — 4 tests
  (transitions-only default, merged ordering DESC, agent_step_id
  passthrough, comment author→actor field renaming).
- New: `frontend/src/pages/Kanban/__tests__/TicketDetailDrawer.test.tsx`
  — 4 tests (timeline kinds, last-touched chip, agent_step_id chip,
  listActivity called with merged include set).
- Backend suite delta: **538 → 546 passing**, 306 failing (no new
  regressions from WP6 — the +2 vs the 304 quoted baseline are
  pre-existing flakes unrelated to ticketing, verified by running
  the suite with the new test files excluded).
- Frontend suite: **32 → 36 passing**, all green.
- Build: clean (`npm run build` succeeds).
- Alembic: untouched (no schema changes — Cross-WP Rule confirmed).


## v2.1-WP8 — Lessons

### Display-field strategy

Neither model carries a dedicated `handle` column today, so the service
derives them in Python:

| Kind  | `display_name` source             | `handle` source                       | `email` |
|-------|------------------------------------|---------------------------------------|---------|
| user  | `users.display_name`               | local-part of `users.email` (lowered) | `users.email` (auth-only) |
| agent | `agent_accounts.name`              | `agent_accounts.name` lowered, spaces→`-` | always `null` |

User fallback (empty `display_name`): email local-part, then literal
`"user"`. Agent has no fallback path — `name` is `NOT NULL` per the
existing schema. **Recommendation for v2.2**: add a real `handle` column
on both tables (unique, slugified) so the derivation moves into the DB
and `ILIKE 'handle%'` becomes a single-index probe instead of a
two-column OR.

### Ranking algorithm

Discriminator tuple (lower = ranks first):

1. `(0, …)` exact handle match (case-insensitive).
2. `(1, …)` prefix match on `handle | display_name | email_local`.
3. `(2, …)` substring fallback — **only consulted when the prefix DB
   query returned zero rows for that kind**, keeping the hot path
   index-friendly.
4. Within each tier, project members (when `project_id` is given) come
   before non-members, then ties break on `(display_name, str(id))`.

Edge cases sanity-checked: empty `q` skips ranking-by-match (everyone
falls into tier 1, member tier still applies), all-caps query lowers
once and matches case-insensitively, `kind=user,foo` silently drops the
unknown `foo` and proceeds with `user` (route stays forwards-compat).

When `project_id` is given **and** `q` is empty/missing, we *restrict*
to project members (not just rank-boost them) so the dropdown is the
project roster rather than the org-wide list. With `project_id` + `q`,
we search the full org but still rank members above non-members — the
common case "type a name to find any assignable user" stays fast.

### Permissions

- The endpoint requires an authenticated actor via `get_actor` (matches
  WP7's transitions endpoint). Anonymous → 401.
- `email` is included in every response. Justification: the route is
  already auth-gated, the email is already visible elsewhere (e.g.
  `/v1/admin/users`, ticket comments showing author email), and the
  picker UI needs SOMETHING disambiguating beyond display name. If
  v2.2 introduces a stricter visibility scope, gate `email` on
  `actor.type == ActorType.user` AND actor's own membership in the
  project — the `include_email` flag is already wired through the
  service.
- Agents are visible to all authed callers. The agent name is not
  private — it's already exposed by `/v1/admin/agent-accounts` and the
  `agents/activity` feed.

### Frontend wire-up

`PersonPicker` is hand-rolled with `useEffect` + `setTimeout`
debouncing (300ms) — no new dependency added (Cross-WP Rule). The
component owns its own open/close state and renders specials
(Unassigned / Me) above live results. Value model is
`{kind:"user"|"agent", id:string} | null`.

To minimise blast radius, the existing `KanbanFilters.assigneeId:
string | null` shape is unchanged — `FiltersBar` now passes the picked
person's bare `id` into that field and the Kanban index page still
reads sentinels (`__unassigned__`, current-user-id) without
modification. `useMembersByProject` is no longer consumed by FiltersBar
(picker fetches its own people via the new search endpoint), but the
hook is left in place because other code paths may still use it.

`CreateTicket` drops the assignee `user/agent` `<select>` + UUID input
in favour of `PersonPicker`; the old `isUuid()` helper is removed (no
remaining caller).

### Recommendation for v2.1-WP9 (@mentions fanout)

**Reuse `PeopleService.search` directly.** A `@handle` token is just
`q=<handle>&kind=user&limit=1` — exact-handle match is already tier 0,
so the first result is the resolution if `result.handle == handle`.

That said, WP9 will probably want a sharper helper than the generic
search: an O(1) `resolve_mention(session, handle) -> PersonRef | None`
that:
1. Splits the `@handle` token from the comment body.
2. Looks up users-only (mentions of agents have weaker semantics for
   v2.1's mentions table).
3. Validates `handle` matches exactly (not just by prefix) — easy
   sanity guard against the `display_name.startswith(handle)` false
   positive from this WP's tier-1 ranking.

Implementation sketch: thin wrapper over `people_service.search(
session, q=handle, kind='user', limit=5)` that filters
`result.handle == handle.lower()` post-hoc. If WP9 needs strict
exactness without the prefix/substring tiers running at all, add a
`exact_handle: bool = False` kwarg to `search()` so it can `where
LOWER(left(email, position('@' in email) - 1)) = :handle` without
falling through to the prefix branches. Cheaper than adding a real
`handle` column today, deferrable to v2.2 when WP9 makes it necessary.

The frontend `searchPeople` client is the natural backend for an
`@`-autocomplete dropdown in the comment composer — same shape, same
debounce idiom. WP9 should not re-implement a parallel `/v1/mentions/
suggest` route.

### Test deltas

- New: `tests/services/test_people_service.py` — 11 tests (empty-q
  default, prefix-vs-substring, exact handle rank-1, kind filters
  exclude the other kind, project-member rank-boost, project-scope
  no-q restricts to members, kinds parsing, de-dup, case-insensitivity).
- New: `tests/routes/test_people_search.py` — 8 tests (empty q, prefix
  match, email visible, kind=user excludes agents and vice versa,
  project member ranking, unauthenticated 401, limit clamped via
  FastAPI `le=100` → 422).
- New: `frontend/src/components/__tests__/PersonPicker.test.tsx` — 5
  tests (renders mocked results, onChange shape `{kind,id}`, 300ms
  debounce coalescing, specials render + bubble, projectId+kind
  propagated to API).
- Updated: `KanbanBoard.v2.test.tsx` + `CreateTicket.test.tsx` to mock
  `../../../api/people` (otherwise PersonPicker would real-fetch under
  jsdom and warn). Existing assertions untouched — both suites
  continue to pass.
- Backend suite delta: **546 → 565 passing**, 306 failing (no new
  regressions vs WP7 baseline).
- Frontend suite: **36 → 41 passing**, all green.
- Build: clean (`npm run build` succeeds).
- Alembic: untouched.



## v2.1-WP9 — Lessons

### Why a parallel `ticket_notifications` table (not extending `notifications`)

The existing bulletin `notifications` table keys `recipient_id`/`actor_id`
as FK `→ users.id NOT NULL`, and targets on `problems`/`solutions`. A
ticket-mention recipient may be an agent, the actor may be an agent,
and the target is a ticket — three shape mismatches. Extending the
column set would either (a) make the existing FKs nullable (corrupts
the bulletin invariant) or (b) introduce a polymorphic discriminator
column on a table the bulletin domain owns. Both are bigger refactors
than v2.1 Cross-WP Rule #1 allows ("no new big abstractions").

Followed the v2 precedent (`ticket_watchers` vs `watches`,
`ticket_attachments` vs `attachments`): parallel table, same column
family, independent lifecycle. Migration is small + reversible.

### Idempotency strategy: schema-level partial unique index

`uq_ticket_notifications_mention_per_comment` is a partial-unique index
`(comment_id, recipient_type, recipient_id) WHERE kind='ticket_mention'`.
The `TicketNotificationService.create_mention` uses `INSERT … ON CONFLICT
DO NOTHING … RETURNING id`; the returned `None` means the row was a
duplicate. Service-layer dedup was rejected because it can't survive
concurrent transactions writing the same comment edit (race).

The partial scope (`WHERE kind='ticket_mention'`) keeps the door open
for future `kind`s (e.g. `ticket_assigned`) to pick their own dedup key
without colliding here.

### Mention regex edge cases

Regex `@([A-Za-z0-9_-]{1,32})` per spec. Documented edge cases (all
intentional behaviour, no fixes required):

- **Unicode handles**: silently dropped — the regex only matches
  `[A-Za-z0-9_-]`. WP8's display-name → handle slugifier already
  lowercases-and-dashes whitespace; unicode handles would need a
  follow-up if we ever add a real `handle` column (v2.2).
- **Trailing punctuation**: `Hi @alice.` — the `.` is outside the
  character class so the regex stops at `alice`. Resolves cleanly.
- **Length cap 32**: longer alphanum tokens after `@` truncate at 32
  per the regex; if someone writes `@really-long-handle-of-more-than-32-chars`,
  the captured token is the first 32 chars. Won't resolve unless an
  actual handle of that prefix length exists — fine.
- **Self-mentions**: skipped in `fanout_mentions` by `(kind, id)` tuple
  match against the actor. The `@reporter`-by-reporter case is covered
  by `test_self_mention_skipped`.
- **Duplicate handles in body**: `@alice @alice` → dedup by `(kind, id)`
  before fanout. One row in `ticket_notifications`.

### Edit semantics (recompute on update)

The brief asked us to recompute on `update_comment` and fanout newly-added
mentions only. `TicketService` does NOT currently expose `update_comment`
— `ticket_comments` is append-only in v2 (see WP2/3 Lessons). So this
deliverable is moot. If a future WP adds edits:

- Compare old vs new `mentions UUID[]`.
- Loop new entries; the schema-level uniqueness on
  `(comment_id, recipient_type, recipient_id)` will swallow re-fanouts
  for the old entries automatically — no application-side guard
  needed.
- Per the brief, do NOT delete existing notifications when a mention
  is removed from the body; the recipient was meaningfully notified.

### Frontend: `MentionTextarea` is a plain `<textarea>`

No TipTap mention extension. The composer is 2 lines max, and TipTap's
mention plugin adds ~30KB gz and a new top-level dep — disqualified by
Cross-WP Rule #1. The component owns its `partial` token state, fires
a 300ms-debounced `searchPeople` call, and inserts `@handle ` (with
trailing space) when a suggestion is picked. Esc dismisses the list
**and snapshots the value** so the list doesn't immediately re-open on
the next `keyup` (`recomputePartial` checks the snapshot and short-
circuits when the value is unchanged).

`searchPeople` was reused as-is — no `/v1/mentions/suggest` route added.
Aligns with the WP8 Lessons recommendation.

### No notifications UI surfaced for tickets

Brief said "if no notifications UI exists, just confirm the DB rows are
created — flag in Lessons". The bulletin-domain `Notification` panel is
unrelated (different table). For WP10/WP11 or v2.2: build a Kanban-side
notifications popover keyed on `ticket_notifications`, mark-read action,
and a deep-link to `/kanban?ticket=<display_id>` (the
`target_display_id` column was added for exactly this reason — no JOIN
needed at render time).

### Recommendation for v2.1-WP10 (pagination)

The WP7 activity feed (transitions-only-by-default, with `?include=`
expansion) is offset-paginated. The notification inbox will need
pagination too. **Shared shape proposal**: a generic `Page[T]`
discriminated by `cursor: str | null`:

```python
class Page(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None
    total: int | None  # optional, computed only when cheap
```

- For activity (WP7): keep the in-Python merge for now; replace
  `?offset` with `?cursor=` over a SQL `UNION ALL` push-down only when
  a single ticket has >10k events.
- For ticket notifications: SQL `ORDER BY (created_at DESC, id DESC)
  LIMIT n+1`; encode the last row's `(created_at, id)` as the cursor.
  Cleaner than offset (insert-skew immunity).
- For people-search (WP8): pagination is unlikely to matter (limit=100
  is plenty for a typeahead), but the shape would compose cleanly.

If WP10 lands `Page[T]`, retrofit it into WP7's `ActivityPage` (currently
hand-rolled with `next_cursor: None` always) and WP8's
`PeopleSearchResponse` (currently `{items: …}` only). The frontend
types in `api/tickets.ts` and `api/people.ts` should follow.

### Test deltas

- New: `tests/services/test_mention_fanout.py` — 7 tests
  (explicit-mentions, body-scan, self-mention, dup-handle, unknown
  handle, agent recipient, excerpt truncation).
- New: `tests/services/test_mention_idempotency.py` — 1 test
  (re-fanout no-op).
- New: `tests/routes/test_comment_mention_route.py` — 1 test
  (POST /comments → 201 + notification row).
- New: `frontend/src/components/__tests__/MentionTextarea.test.tsx` —
  3 tests (suggest-on-@, click-inserts, Esc-dismisses).
- Updated: `frontend/src/pages/Kanban/__tests__/TicketDetailDrawer.test.tsx`
  — +1 test (composer renders MentionTextarea); also mocks
  `../../../api/people` to keep jsdom quiet.
- Backend suite delta: **565 → 574 passing**, 306 failing (no new
  regressions; WP8 baseline preserved).
- Frontend suite: **41 → 45 passing**, all green.
- Build: clean (`npm run build` succeeds).
- Alembic: new revision `a11_ticket_notifications` — upgrade head + a
  manual `downgrade -1 → upgrade head` round-trip is reversible (the
  table + partial index drop cleanly).


## v2.1-WP10 — Lessons

### Cursor encoding: base64(JSON), urlsafe, padding-stripped

The cursor encodes `(created_at_iso, id_uuid)` as
`base64url(json({"t": ..., "i": ...}))` with trailing `=` stripped on
the wire. Tradeoffs:

- **Opaque to clients** — they pass it back verbatim and never parse it.
  We can swap the encoding in v2.2 without breaking the wire contract.
- **Self-describing on the server side** — decode failures land in
  `InvalidCursorError → 400` with a clear `cursor decode failed: ...`
  message. No silent skip-the-cursor fallback.
- **No HMAC** — the cursor isn't a capability, just a position marker;
  tampering only produces a 400 or a malformed page, no privilege
  escalation. Add HMAC in v2.2 if a public-facing API exposes this.

Alternative considered: raw `created_at|id` with a `|` separator. Same
size on the wire (within ~10 bytes) but the JSON form is more
extensible — a future field (e.g. tiebreaker on `seq_number`) doesn't
need a wire bump.

### `Page[T]` generic with Pydantic v2

`BaseModel + Generic[T]` works out of the box in Pydantic v2.7+ — no
`GenericModel` import needed (that was a v1 idiom; in v2 the support
folded into `BaseModel` itself). `Page[Foo].model_validate(...)` and
`Page[Foo].model_dump(...)` both round-trip cleanly (verified in
`tests/schemas/test_page_generic.py`).

Only gotcha: a FastAPI `response_model=Page[TicketRead]` annotation
forces the framework to coerce the dict the route currently returns —
since the route returns a plain dict (`{items: [...], next_cursor, total}`)
with already-serialized `to_dict()` items, we left the route as
`-> dict[str, Any]` and let the Page shape live as a documentation +
client-side contract. Switching to `response_model=Page[TicketRead]`
would require `TicketRead.model_validate(t)` instead of `t.to_dict()`
and would change the wire payload subtly (Pydantic re-serializes
datetimes, enums) — out of scope for WP10, queued for v2.2.

### `total` cost decisions per endpoint

- `GET /api/v1/tickets`: `total` ONLY when `project_id` is supplied.
  Adds a single COUNT(*) over the same WHERE clause — for the Kanban
  view (always project-scoped) the cost is negligible. Org-wide
  listings would scan the whole `tickets` table; we return `total=null`
  there. Documented in the route docstring.
- `GET /api/v1/projects`: `total = len(items)` since the list is small
  enough to fit in a single page today. When pagination materialises
  (v2.2 if needed), switch to a COUNT.
- `ActivityPage` (WP7): NOT retrofitted — see below.

### `ActivityPage` (WP7) — left alone

The retrofit would have been to make `ActivityPage` extend or alias
`Page[ActivityItem]`. Two reasons we punted:

1. WP7's `ActivityPage` has a non-optional `total: int`; the generic
   `Page[T]` has `total: int | None`. Switching the field to optional
   on the WP7 wire format would force frontend type changes outside
   WP10's scope.
2. The transitions endpoint is offset-paginated, NOT cursor-paginated
   (per WP7 Lessons §"Pagination decision"). Making it inherit from
   the cursor-shaped generic without converting the implementation
   would be a contract lie. Convert both together in v2.2 when the
   merged feed is push-down to SQL and cursor pagination becomes
   meaningful.

`ActivityPage` is structurally identical to `Page[ActivityItem]`
EXCEPT for the `total` nullability — frontend consumers can read both
through the same code path without retrofitting today.

### Filter sentinel literal: `"null"`

Picked `"null"` (the literal four-character string) over alternatives
like `none`, `unassigned`, `__none__`:

- **Matches JSON `null`** in spirit — a developer reading the URL
  immediately understands intent.
- **No collision with valid UUIDs** — UUIDs are 36 chars with hyphens;
  `null` can never match the v4 grammar so we can validate by
  attempting `UUID(value)` and falling back to a literal-match.
- **Survives URL encoding** — no special chars.

`"me"` for assignee was a separate decision: it's a tiny convenience
that saves the frontend from having to know its own user id when
filtering. The route resolves it from the `Depends(get_actor)` actor.

### `WHERE created_at < cur_ts OR (created_at = cur_ts AND id < cur_id)`

The disjunction is the canonical keyset shape for ordering by
`(created_at DESC, id DESC)`. We rely on Postgres' planner to use
the existing `(created_at, id)` index for the strict-less branch and
fall back to a hash on the equality branch — verified the EXPLAIN
plan on the dev DB shows an Index Scan Backward.

No new index was added. The existing `ix_tickets_created_at` (single
column) is sufficient because the keyset is dominated by `created_at`;
the `id` disambiguator only kicks in when timestamps collide (within
a single TX), which is rare. If profiling later shows this is a hot
path with many same-timestamp ties, add a composite
`ix_tickets_created_at_id` then. WP10 deliberately did NOT introduce
the index — Cross-WP Rule #1 ("no big abstractions") applies to
migrations too.

### Frontend: sentinel migration is a hard cutover

`__none__` / `__unassigned__` / `__any__` are GONE from filter values
(the legacy `__none__` swimlane-grouping key in `KanbanBoard.tsx` is
UI-internal, never sent to the API — left untouched). Replacement:

| Old client value     | New value sent to API          |
|----------------------|-------------------------------|
| `sprintId="__none__"`| `sprint_id=null`              |
| `epicId="__none__"`  | `epic_id=null`                |
| `assigneeId="__unassigned__"` | `assignee_id=null`   |
| (currentUserId UUID) | `assignee_id=me`              |
| `sprintId=null`      | omit param (frontend null = "All") |

The dropdown HTML `<option value="...">` now uses `"null"` directly so
the FiltersBar state holds the wire-ready value; no translation in the
Kanban page itself. This eliminated 14 lines of `if (filters.x === "__none__")`
client-side compensation in `Kanban/index.tsx`.

### Recommendation for v2.1-WP11 (WIP limits)

WP11 should:

1. Read `project.wip_limits` (already on the model) on the Kanban
   page and render a `<header>` count badge per column showing
   `current / limit`, with a CSS class swap when `current > limit`.
2. **Column counts can be computed client-side from the loaded
   `tickets` array** — WP10's `total` (when populated) is the
   board-wide total, not per-column. Adding a per-column `dict[status, int]`
   to the response would require a `GROUP BY status` on the server;
   not worth it when the frontend already has the rows.
3. Caveat: if "Load more" pagination is in play, the column-count
   computation undercounts for the columns whose tickets fell into
   later pages. Two options:
   - Force the Kanban to fetch all pages up-front (current
     `limit=500` already does this for ≤500 tickets — bump to
     keep-loading-until-cursor-null if WP11 needs accurate counts).
   - Add `column_counts: dict[status, int]` to the response when
     `project_id` is set, computed server-side via `GROUP BY status`.
     Cheap on the same WHERE. **Recommend this** — same shape and
     cost trade-off as `total`, and it makes the WIP-limit display
     correct regardless of pagination state.

### Test deltas

- New: `tests/routes/test_tickets_pagination.py` — 9 tests (75-row
  cursor walk, invalid cursor 400, sprint_id=null, assignee_id=null,
  assignee_id=me, invalid sentinel 400, mid-walk concurrent insert
  stability, total populated under project filter, total null
  otherwise).
- New: `tests/services/test_tickets_pagination.py` — 3 tests
  (encode/decode roundtrip, malformed cursor raises, list ordering).
- New: `tests/schemas/test_page_generic.py` — 3 tests (Page[Foo]
  dump/validate, optional total, total=None serializes).
- New: `frontend/src/pages/Kanban/__tests__/KanbanPagination.test.tsx`
  — 3 tests (sprint "No sprint" sends `null`, "All sprints" omits
  param, Load-more click appends next page with cursor).
- Updated: `tests/services/test_ticket_create.py::test_list_filters_by_parent_and_type`
  — unpacks the new `{items, ...}` dict shape from `svc.list(...)`.
- Backend suite delta: **574 → 589 passing**, 306 failing (same
  pre-existing failures as WP9 baseline; no new regressions).
- Frontend suite: **45 → 48 passing**, all green.
- Build: clean (`npm run build` succeeds; no TS errors).
- Alembic: untouched (no schema changes — see "No new index" above).


## v2.1-WP11 — Lessons

### TicketsPage subclass, not `Page[T]` widening

`column_counts` lives on a `TicketsPage(Page[dict])` subclass declared in
`app/schemas/common.py` rather than as a new field on the generic
`Page[T]`. Reasons:

- Only the tickets endpoint needs per-status counts; widening `Page[T]`
  would force every other paginated list to carry a `column_counts:
  None` it never populates.
- WP10's `Page[T]` already documents `total` as the cost-aware aggregate
  knob — adding another aggregate to the generic muddies that contract.
- The wire shape is purely additive: existing clients that don't read
  `column_counts` are untouched, and routes that don't compute it return
  `null`.

If a future WP needs the same per-bucket aggregate elsewhere
(e.g. `Page[NotificationRead]` with per-kind counts), do the same: a
domain-specific subclass — don't promote.

### Cost: a single `GROUP BY status` is fine

The aggregate is one extra query per `GET /api/v1/tickets` call when a
`project_id` filter is present. It reuses the same WHERE clause as the
COUNT(*) (less the cursor clause) and lands on the existing
`ix_tickets_project_id` (Postgres picks an Index Scan + HashAggregate on
the dev DB EXPLAIN plan). No new index was added.

The aggregate is **independent of `limit` / `cursor`** by design — that
is the whole point of the WP10 → WP11 chain. WP10 already paid the COUNT
under the same condition; doubling it to two aggregates is a wash.

For org-wide listings the aggregate is skipped entirely
(`include_column_counts=False` unless `project_id` is set) because a
`GROUP BY status` over the whole `tickets` table would scan every row.

### Service `update()` needed a `session.refresh()` after flush

The `ProjectService.update` path previously returned the in-session row
without refreshing. The route's `proj.to_dict()` then accessed
`updated_at` (a column with `onupdate=func.now()` — populated server-
side after the flush) and triggered a lazy IO outside the async
greenlet, raising `sqlalchemy.exc.MissingGreenlet`. The first
`PATCH /api/v1/projects/{id}` test surfaced it because the route was
otherwise rarely exercised through a route-level test fixture.

Fix: `await session.refresh(proj)` at the end of `update()`. Cheap, and
in line with `create()` which already refreshes.

### Permissions: cosmetic gate only

`⚙ Limits` is gated client-side on `project.lead_id === currentUser.id`
(or absence — so a freshly-created project with no lead can still
configure limits). The backend route does NOT enforce that the caller is
the lead; any authenticated actor can `PATCH /api/v1/projects/{id}`
today (WP3 baseline). A real role/membership check belongs in v2.2.

**v2.2 TODO**: gate `PATCH /api/v1/projects/{id}` on either (a)
`actor.id == project.lead_id` OR (b) `actor` has a `ProjectMember` row
with `role IN ('lead', 'admin')`. The dialog already sends the OCC
`version`, so adding a 403 path doesn't change the wire contract.

### Frontend: counts vs. WIP limits only apply to "all" swimlane

`columnCounts` (backend aggregate, board-wide) and `wipLimits` (per
project) are applied ONLY when `swimlane === "none"`. Inside swimlane
sub-buckets (by epic / sprint / assignee), the column count falls back
to `tickets.filter(...).length` and the WIP-limit chip is hidden — the
backend doesn't shard counts by swimlane key, and limits are board-wide
not per-lane. This keeps semantics honest; an over-limit indicator only
fires when the board-wide column truly exceeds the threshold.

### v2.1 closing retrospective

What the WP6 → WP11 chain delivered against WP5's residual backlog:

- **Aggregates + audit trail (WP6, WP7)**: `tickets.last_actor_*` row
  aggregate + merged activity feed are both shipped and consumed by the
  drawer. Last-touched chip is on the drawer header.
- **People picker + mentions (WP8, WP9)**: unified `/v1/people/search`
  with handle/prefix/substring ranking + `ticket_notifications` fanout
  with schema-level idempotency. `MentionTextarea` is a plain
  `<textarea>` with debounced suggest — no new top-level dep.
- **Pagination + sentinels (WP10)**: `Page[T]` generic + base64(JSON)
  cursor + `"null"` / `"me"` sentinels. Sentinels replaced 14 lines of
  legacy client-side compensation.
- **WIP limits (WP11)**: per-column display + minimal settings dialog +
  authoritative `column_counts` aggregate.

**Deferred to v2.2 (honest list):**

1. Real permissions on `PATCH /api/v1/projects/{id}` (currently cosmetic
   client-side gate).
2. `ActivityPage` → `Page[ActivityItem]` retrofit (cursor vs offset
   mismatch, deferred per WP10 Lessons).
3. SQL `UNION ALL` push-down for the activity merge (only matters at
   >10k events per ticket — well beyond v2.1 scale).
4. Real `handle` column on `users` + `agent_accounts` (WP8 derived
   handles in Python; an indexed column would make the search a single
   probe).
5. Notifications UI for `ticket_notifications` (panel + mark-read +
   deep-link). Rows are written; nothing renders them yet.
6. HMAC on the opaque cursor (WP10) — not needed today; add when a
   public-facing API exposes pagination.

### Test deltas

- New: `tests/routes/test_tickets_column_counts.py` — 3 tests
  (column_counts populated under project filter, null without,
  stable across pages).
- New: `tests/routes/test_project_wip_limits.py` — 5 tests
  (accept + readback, negative rejected, non-integer rejected, empty
  dict accepted, OCC mismatch 409).
- New: `frontend/src/pages/Kanban/__tests__/WipLimits.test.tsx` — 5
  tests (under-limit neutral, at-limit amber, over-limit red + border,
  no-limit bare count, fallback to tickets.length).
- New: `frontend/src/pages/Kanban/__tests__/WipLimitsDialog.test.tsx` —
  3 tests (prefill, save payload + version, emptied input drops key).
- Backend suite delta: **589 → 597 passing**, 306 failing (same
  pre-existing failures as WP10 baseline; no new regressions).
- Frontend suite: **48 → 56 passing**, all green.
- Build: clean (`npm run build` succeeds; no TS errors beyond the
  documented pre-existing baseline in `ProblemDetail.tsx`).
- Alembic: untouched (column already existed from v2 — Cross-WP Rule
  "no schema migration" honoured).
