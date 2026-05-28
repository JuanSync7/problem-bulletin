# v2.21 ticketing — lessons learned

Companion to `ticketing-v2.20.md`. v2.21 was the **targeted continued
sweep** version: option (a) of the v2.20 seed executed straight. v2.20
closed at **51 allow-list keys / 0 LEGACY** with a concrete ~21-key
mechanically-fixable backlog across two clusters (`pg_insert(Model)`
rewrite, `<Service>.list` self-shadow rename). v2.21 landed both: WP02
rewrote 8 `pg_insert(TicketNotification.__table__)` callsites (−8), and
WP03 renamed `TicketService.list → list_page` and `ProjectService.list
→ list_all` across ~20 callsites (−15). Final state **51 → 28
allow-list keys (−23, ~45% reduction)** with classification still **0
LEGACY throughout** — every residual is a genuine framework typing
limit (Starlette ASGI Mount, FastAPI add_exception_handler, joined-load
attr-defined, co-nullable FK pairs, `Result[Any].rowcount`). v2.21 hit
the framework-residual floor forecast by v2.20-WP03 (~30) and slightly
beat it. 4 WPs: recon, E2 `pg_insert` rewrite, E1 `<Service>.list`
rename, closure.

**Closing baselines:** backend **1444 P / 0 F / 6 skipped / 14 xfailed**
(unchanged across all 4 WPs — no regressions). Frontend **276 P / 0 F**
(untouched). Mypy: **51 raw errors / 51 keys → 28 raw errors / 28
keys**.

---

## v2.21-WP01 (G0) — recon

Backend **1444 P**, frontend **276 P**, mypy 51 errors / 51 keys — all
match v2.20 close. Full attack-plan written to
`v2.21-wp01-diagnosis.md`.

**Key recon findings:**
- E1 owns **15 keys** (7 valid-type + 8 cascading attr-defined), not
  the v2.20-seeded ~14. Ticket-side declaration `list` at
  `services/tickets.py:628` shadows 6 sibling `-> list[T]`
  annotations; Project-side declaration `list` at
  `services/projects.py:127` shadows 1; 8 cascading `attr-defined`
  errors at consumer iteration sites. Production callers: 3
  (`routes/tickets.py:363`, `routes/projects.py:86`,
  `mcp_server/tools.py:154`). Test callers: 8 sites across 3 files.
  Recommended new names: `list_page` (Ticket; returns `Page[Ticket]`)
  and `list_all` (Project; returns `list[Project]`) — two distinct
  names because the return shapes differ.
- E2 owns **8 keys**, not the v2.20-seeded ~7. v2.20 seed missed
  `services/due_soon_scanner.py:184` as a `pg_insert(TicketNotification
  .__table__)` callsite — only 7 in `ticket_notifications.py` were
  enumerated. Total: 8 mechanical 1-token edits.
- Combined forecast: 51 − 15 − 8 = **28 keys**, slightly under the
  ~30-key framework-residual floor.

**WP ordering:** WP02 = E2 first (8 1-token edits, lowest risk warm-up,
no test caller renames needed per recon — incorrect, see WP02
surprise); WP03 = E1 second (~20 callsite rename, larger blast radius).
Forward rule (mm) honoured — separate WPs for separate clusters.

---

## v2.21-WP02 — E2 `pg_insert(Model.__table__)` → `pg_insert(Model)`

**Outcome.** 8 callsites mechanically rewritten across 2 files
(`services/due_soon_scanner.py:184` + 7 in
`services/ticket_notifications.py`). Allow-list 51 → **43** (−8 keys);
mypy errors 51 → 43 exactly. Backend stayed at 1444 P; frontend
untouched.

**Files modified (4):**
- `app/services/due_soon_scanner.py` — 1 rewrite
- `app/services/ticket_notifications.py` — 7 rewrites
- `tests/services/test_ticket_notifications_wp40.py` — predicate widen
- `tests/services/test_watcher_notifications_wp41.py` — predicate widen

No new imports required at either production file — `TicketNotification`
was already imported.

**Surprise.** WP01 recon stated "no test-caller rewrites needed because
tests go through services, not `pg_insert` directly." This was wrong.
Two tests **monkey-patch** `pg_insert` and dispatch on `is`-identity of
the first positional arg:

```python
# tests/services/test_ticket_notifications_wp40.py:178
if table is TicketNotification.__table__:
    ...  # injected failure path
```

After the rewrite, production code passes `TicketNotification` (the
mapped class) rather than `TicketNotification.__table__`, so the
identity check missed → `boom` fell through to `real_pg_insert` → the
SAVEPOINT-isolation assertion failed. Fix: widen the predicate to accept
either form:

```python
if table is TicketNotification or table is TicketNotification.__table__:
```

Two-line change across two test files; preserves original intent
(intercept ticket-notification INSERT only). This pattern surfaces as
forward rule (oo) below.

**Residual after WP02.** 43 keys (target floor ~30; E1 will clear 15
more).

---

## v2.21-WP03 — E1 `<Service>.list` self-shadow rename

**Outcome.** `TicketService.list → list_page` (`Page[Ticket]`),
`ProjectService.list → list_all` (`list[Project]`). 6 production files
edited (2 declaration + 3 caller + 1 internal self-call), 3 test files
(8 sites) updated, 15 allow-list entries deleted. Allow-list 43 →
**28** (−15 keys, exact match to WP01 forecast); mypy errors 43 → 28.
Backend stayed at 1444 P; frontend untouched.

**Files modified (6 production + 3 test + 1 lint PIN):**

*Declaration sites (2):*
- `app/services/tickets.py` — `list` → `list_page` (line 628)
- `app/services/projects.py` — `list` → `list_all` (line 127)

*Production callers (3):*
- `app/routes/tickets.py:363`, `app/routes/projects.py:86`,
  `app/mcp_server/tools.py:154`.

*Internal self-call (1; recon miss):*
- `app/services/tickets.py:1737` — `self.list(...)` inside
  `search_tickets`. Not enumerated in WP01 production-callers table.
  Caught via post-edit grep sweep and patched in lockstep. Forward rule
  (nn) below records this.

*Test callers (3 files / 8 sites):*
- `tests/services/test_tickets_pagination.py:51`
- `tests/services/test_tickets_ordering.py:55,92,133,156,184`
- `tests/services/test_ticket_create.py:194,198`

*Lint PIN:* `tests/test_typecheck_lint_v219_wp02.py` — 15 entries
removed from `_OFFENDER_ALLOWLIST`.

**Latent shadow noted, deferred.** `SprintService.list` exists at
`app/services/sprints.py:52` — same shadow-of-builtin anti-pattern, but
zero current mypy keys (sprint-side annotations don't return
`list[Sprint]` in shadowed scope). Out of scope for v2.21 reactive
sweep; flagged for v2.22 preventative-hygiene. Surfaces as forward rule
(pp) below.

**Residual after WP03.** 28 keys (slight beat vs ~30 forecast). All
genuine framework limits: Starlette ASGI `Mount` callable variance,
FastAPI `add_exception_handler` callable variance, SQLAlchemy
`Mapped[T]` vs `T` boundary, joined-load `attr-defined`,
`Result[Any].rowcount` (×5), `feed.py:35` dict-item, `problems.py:164`
return-value, `exceptions.py:33` TYPE_CHECKING name-defined,
`coalesce` assignment, `Ticket.assignee_type` / `Ticket.assignee_id`
co-nullable FK arg-type pair.

---

## v2.21-WP04 (closure) — this document

Retrospective written. v2.22 paste-ready seed appended at bottom. Zero
production code touched.

---

## v2.21 retrospective

### Headline numbers

- **Backend:** 1444 P / 0 F / 6 skipped / 14 xfailed — unchanged across
  all 4 WPs.
- **Frontend:** 276 P / 0 F — untouched.
- **Mypy raw errors:** 51 → 43 (WP02) → **28** (WP03).
- **Mypy allow-list keys:** 51 → 43 (WP02) → **28** (WP03), **−23
  (~45% reduction)**.
- **Classification:** **0 LEGACY throughout.** All deletions were
  offender-fixed, never reclassified to LEGACY.
- **Real bugs fixed:** 0 (all changes typing-only).
- **Production code touched (`app/`):** 5 files (2 services rewrite +
  2 services method rename + 3 callers; some overlap — net 5).
- **Test code touched:** 5 files (2 monkey-patch predicates widened in
  WP02 + 3 caller files renamed in WP03).
- **Lint allow-list:** 1 file (`tests/test_typecheck_lint_v219_wp02.py`
  — 23 entries deleted across WP02 + WP03).
- **Production regressions introduced:** zero.

### WPs shipped

| WP | Bucket | Summary | Allow-list delta |
|----|--------|---------|-----------------:|
| WP01 | G0 | Recon. Confirmed v2.20 close baseline. Mapped E1 (15 keys, ~20 sites) and E2 (8 keys, 8 sites) attack plans. Both clusters were under-counted by 1 in v2.20 seed. | ±0 |
| WP02 | E | E2 `pg_insert(Model.__table__) → pg_insert(Model)` rewrite across 8 callsites. Surprise: 2 test monkey-patches dispatched on `Model.__table__` identity and required predicate-widening. | −8 |
| WP03 | E | E1 `<Service>.list` self-shadow rename: `TicketService.list → list_page`, `ProjectService.list → list_all`. ~20 callsites across app + tests. One recon miss (`self.list` in `search_tickets`) patched in lockstep. | −15 |
| WP04 | closure | Retrospective + v2.22 seed. | ±0 |

### Cross-cutting lessons

1. **(nn) Recon caller-counts are approximate; expect ±1 internal
   self-call discovered at edit time.** WP01 listed 3 production
   callers for `TicketService.list` (routes/tickets, MCP tools,
   routes/projects-for-projects-side). WP03 edit time discovered a 4th:
   `app/services/tickets.py:1737` — an intra-service `self.list(...)`
   inside `search_tickets`. `grep -rn 'svc.list\|service.list'` across
   `app/` will surface external callers reliably but misses
   `self.<name>(...)` and `cls.<name>(...)` patterns inside the
   declaring file itself. Pattern: when scoping a method rename, ALSO
   run `grep -n 'self\.<name>\|cls\.<name>'` against the declaring file
   and the project-search auto-discovers the rest. Recon caller-counts
   are floors, not totals. Plan for a ±1 surprise at edit time and
   absorb in the same WP via post-edit grep sweep.

2. **(oo) Test monkey-patches that dispatch on `Model.__table__`
   identity must be widened in lockstep with `pg_insert(Model)`
   rewrites.** WP02 found two tests
   (`test_ticket_notifications_wp40.py`,
   `test_watcher_notifications_wp41.py`) that intercept the SQLAlchemy
   bulk-insert primitive and dispatch on `is`-identity of the first
   positional arg to inject failure paths. When the production code
   migrates from `pg_insert(Model.__table__)` to `pg_insert(Model)`,
   the identity check silently misses, the injection is skipped, and
   the SAVEPOINT-isolation assertion fails — but the failure mode
   looks like a regression in production behaviour, not a test-fixture
   drift. Pattern: when rewriting `pg_insert(Model.__table__)` →
   `pg_insert(Model)`, pre-grep for monkey-patches that name the same
   table class — typical idioms are `if table is X.__table__`,
   `monkeypatch.setattr(...pg_insert...)`, `lambda table, ...`. Widen
   the predicate to `if table is Model or table is Model.__table__`.
   Generalises beyond `pg_insert` to any monkey-patch that
   identity-checks a table/class argument whose call-site shape is
   migrating.

3. **(pp) Latent shadow-of-builtin sites with zero current mypy keys
   are out-of-scope for reactive sweep; flag as preventative-hygiene
   backlog.** WP03 surfaced `SprintService.list` at
   `app/services/sprints.py:52` — the same naming anti-pattern that
   v2.20-WP03 / v2.21-WP03 spent attacking on `TicketService` /
   `ProjectService`, but with no current mypy keys (the Sprint service
   does not yet have sibling `-> list[Sprint]` annotations that would
   trigger the shadow). A reactive sweep is governed by the
   `_OFFENDER_ALLOWLIST` — fixing zero-key offenders enlarges the
   sweep's blast radius for zero allow-list reduction. Pattern: when a
   shadow-of-builtin cluster is being fixed for one service, audit
   sibling services for the same name and SHELVE the zero-key latent
   sites as a preventative-hygiene WP (cosmetic version), not as
   carry-on work. Refines rule (ll): the one-time sweep is one-time per
   mypy-key cluster; latent sites become a separate scheduled hygiene
   pass.

### What stayed deferred (carry to v2.22)

- **Preventative-hygiene** (NEW — v2.21-WP03 surfaced):
  - **H1. `SprintService.list` rename to `list_sprints` / `list_all`.**
    Latent shadow; zero current keys. Mechanical rename + caller
    update. Pre-flight with `grep -rn 'sprint_service.list\b\|SprintService.list\b'`
    across `app/` + `alembic/` + `tests/`.
  - **H2. Audit sibling services for any other `list`-shaped
    shadow-of-builtin methods.** Mechanical grep:
    `grep -rn 'def list\b\|async def list\b' app/services/`.
- **Bucket A** (C7, E3, E4, F3) — still conditional v2.11
  carry-forwards.
- **Bucket B** (B1, B2) — still conditional v2.13 carry-forwards.
- **Bucket C** (C1, C2, C3, C4) — still conditional v2.18 carry-forwards.
- **Bucket R cosmetic** — `_OFFENDER_ALLOWLIST` helper extract (v2.19
  rule ee) — 4 lints share the shape; still on backlog from v2.19 →
  v2.20 → v2.21.
- **28 BY-DESIGN typecheck residents — the genuine framework-residual
  floor.** Per cluster:
  - Starlette ASGI variance (`Mount` app= callable, ×1 in
    `mcp_server/server.py:145`).
  - FastAPI variance (`add_exception_handler` callable, ×1 in
    `main.py:321`).
  - SQLAlchemy `Result[Any].rowcount` boundary (×5 across services).
  - Joined-load relationship `attr-defined` (×~3 across `solutions.py`
    / `feed.py` / others).
  - `Ticket.assignee_type` / `Ticket.assignee_id` co-nullable FK
    arg-type pair (×2 in `services/tickets.py:1195-1196`).
  - `Mapped[T]` vs `T` boundary residuals at edges that the v2.20
    migration could not unify.
  - `coalesce(...)` assignment, dict-item, return-value, TYPE_CHECKING
    name-defined — scattered single residuals.
  None of these are reactively fixable without upstream Starlette /
  FastAPI / SQLAlchemy stub or plugin improvements. Re-evaluate every
  N versions (forward rule kk).

### Files touched (rough stats — sum of WP02 + WP03)

- **Production code (`app/`):**
  - `app/services/tickets.py` (WP02 surprise re-grep + WP03 rename +
    self-call patch)
  - `app/services/projects.py` (WP03 rename)
  - `app/services/ticket_notifications.py` (WP02 — 7 callsites)
  - `app/services/due_soon_scanner.py` (WP02 — 1 callsite)
  - `app/routes/tickets.py` (WP03 caller)
  - `app/routes/projects.py` (WP03 caller)
  - `app/mcp_server/tools.py` (WP03 caller)
- **Production code (`frontend/src/`):** 0 files.
- **Alembic (`alembic/versions/`):** 0 files.
- **Config:** 0 files.
- **Lint allow-lists:** 1 file
  (`tests/test_typecheck_lint_v219_wp02.py` — 23 entries deleted
  across WP02 + WP03; bidirectional stale-detection confirmed 1:1
  correspondence with fixed offenders).
- **Test code (backend):**
  - `tests/services/test_ticket_notifications_wp40.py` (WP02 predicate
    widen)
  - `tests/services/test_watcher_notifications_wp41.py` (WP02 predicate
    widen)
  - `tests/services/test_tickets_pagination.py` (WP03 rename)
  - `tests/services/test_tickets_ordering.py` (WP03 rename)
  - `tests/services/test_ticket_create.py` (WP03 rename)
- **Docs (`.claude/lessons-learned/`):** 3 per-WP diagnosis files
  (`v2.21-wp01-diagnosis.md`, `v2.21-wp02-diagnosis.md`,
  `v2.21-wp03-diagnosis.md`) + this retrospective.

---

## v2.22 starting prompt seed

v2.21 closed as a **targeted continued sweep version** — mechanical
execution of v2.20-seeded backlog (E2 `pg_insert(Model)` rewrite −8 +
E1 `<Service>.list` rename −15). Allow-list **51 → 28 (−23, ~45%
reduction)** with classification **0 LEGACY throughout**. Baselines:
backend **1444 P / 0 F / 6 skipped / 14 xfailed**, frontend **276 P / 0
F**. 28 residual keys all genuine framework typing limits (Starlette
ASGI `Mount`, FastAPI `add_exception_handler`, joined-load
`attr-defined`, `Result[Any].rowcount` ×5, co-nullable FK arg-type
pair, scattered single residuals).

**v2.21 reached the genuine framework-residual floor.** Further
reactive reduction requires upstream Starlette / FastAPI / SQLAlchemy
plugin or stub improvements. Three shapes for v2.22:

- **(a) PREVENTATIVE-HYGIENE — RECOMMENDED smallest-safe-next.** Land
  H1 (`SprintService.list` rename — latent shadow surfaced in v2.21-
  WP03) + H2 (audit sibling services for other `list`-shaped or
  builtin-shaped methods). Zero allow-list delta; pre-empts the next
  reactive sweep iteration. Mirrors rule (ll) one-time sweep but on
  preventative axis (rule pp). ~1 WP of mechanical cleanup.
- **(b) UPSTREAM-WAIT — legitimate "we are done here for now".** Declare
  28 the floor; monitor mypy/SQLAlchemy/Starlette/FastAPI releases for
  framework-typing improvements; no active typecheck work until
  upstream moves. Pair with periodic re-evaluation WP per rule (kk).
- **(c) ADJACENT PIN expansion — parallel option.** Pick a non-
  typecheck PIN to tighten. Candidates: catch-block structural lint
  expansion (v2.15-style); `ts-any` lint expansion to `Response.json()`
  → `unknown` sweep (v2.18 rule v); OpenAPI ↔ TS parity (v2.13 rule
  ee). Independent of typecheck PIN; no contention.

**Recommend (a) as smallest-safe-next + (c) as parallel option.** (b)
is the honest "no work to do YET" stance and is the right read if
toolchain capacity is constrained — schedule (b) as the default and
upgrade to (a)+(c) when a sprint has capacity for low-leverage
preventative work.

### v2.22 backlog

#### Bucket H — Preventative-hygiene (PRIMARY v2.22 work, RECOMMENDED option (a))

H1. **`SprintService.list` rename.** `app/services/sprints.py:52`. Same
    shadow-of-builtin anti-pattern; zero current mypy keys. Pre-flight
    with `grep -rn 'sprint_service.list\b\|SprintService.list\b'`
    across `app/` AND `alembic/` AND `tests/`. Recommended new name:
    `list_sprints` or `list_all` depending on return shape.
H2. **Audit sibling services for other latent shadow-of-builtin
    methods.** `grep -rn 'def list\b\|async def list\b' app/services/`
    + analogous greps for other builtins (`type`, `id`, `dict`,
    `set`). Rename any caught.

#### Bucket P — Adjacent PIN expansion (parallel option (c))

P1. **catch-block structural lint expansion.** v2.15 / v2.16 surface;
    re-audit for new bare-catches accumulated since v2.16-WP04.
P2. **`ts-any` / `Response.json(): Promise<any>` → `unknown` sweep.**
    v2.18 rule (v) — unsignal-able `any` axis; mechanical tightening
    on frontend.
P3. **OpenAPI ↔ TS parity tightening.** v2.13 rule (ee) /
    v2.12-WP11 / v2.13-WP05 — expand lint coverage to currently
    out-of-scope schema shapes.

#### Bucket R — Cosmetic refactor (carry-forward from v2.19 → v2.20 → v2.21)

R1. **Extract shared `_OFFENDER_ALLOWLIST` helper module** across the
    4 lints (bare-catch, ts-any, pragma, typecheck). Mechanical
    refactor.

#### Bucket A — Conditional v2.11 carry-forwards (act only on triggering need)

A1. C7 `decode_email_body` helper. A2. E3 KindPill 7th surface.
A3. E4 `useSearchV2` ergonomic follow-ups. A4. F3 TipTap second-
consumer extraction.

#### Bucket B — Conditional v2.13 carry-forwards

B1. Per-arm `refresh_total` opt-in syntax. B2. WP05 OpenAPI↔TS parser
expansion (folds into P3 above if option (c) lands).

#### Bucket C — v2.18 surfaced candidates (conditional)

C1. Promote `EditSuggestionRead` / `AttachmentRead`. C2.
`Response.json(): Promise<any>` → `unknown` sweep (folds into P2 if
option (c) lands). C3. `actor_type` enum-backed column migration.
C4. Context-snippet anchoring across lints.

### v2.22 prompt seed (paste-ready)

> Proceed with v2.22 of the problem-bulletin ticketing system.
> v2.21 retrospective + carry-forward backlog live at the bottom of
> `.claude/lessons-learned/ticketing-v2.21.md`. Baselines: backend
> **1444 P / 0 F / 6 skipped / 14 xfailed**, frontend **276 P / 0 F**,
> mypy **28 errors / 28 allow-list keys (0 LEGACY)**. **v2.21 was the
> targeted continued sweep version — landed v2.20-seeded backlog: E2
> `pg_insert(Model.__table__) → pg_insert(Model)` (−8) + E1
> `<Service>.list` rename (`TicketService.list → list_page`,
> `ProjectService.list → list_all`) (−15), total −23 keys, ~45%
> reduction.** v2.21 reached the genuine framework-residual floor (28
> keys, all upstream-blocked Starlette/FastAPI/SQLAlchemy variance).
> Three shapes: **(a) PREVENTATIVE-HYGIENE — RECOMMENDED smallest-
> safe-next**: H1 `SprintService.list` rename (latent shadow surfaced
> in v2.21-WP03; zero current keys, pre-empts next reactive sweep
> iteration) + H2 audit sibling services for other latent
> shadow-of-builtin methods; ~1 WP mechanical cleanup; (b)
> UPSTREAM-WAIT — legitimate "we are done here for now": declare 28
> the floor, monitor framework releases, no active typecheck work;
> (c) ADJACENT PIN expansion — parallel option: P1 catch-block lint
> re-audit, P2 `ts-any` / `Response.json() → unknown` sweep, P3
> OpenAPI↔TS parity tightening. **Recommend (a) + (c) as parallel
> options; (b) is the honest fallback when toolchain capacity is
> constrained.** **Bucket H (if option a):** H1 rename
> `SprintService.list` → `list_sprints` / `list_all`; pre-flight
> `grep -rn 'sprint_service.list\b\|SprintService.list\b'` across
> `app/` AND `alembic/` AND `tests/`. H2 `grep -rn 'def list\b\|async
> def list\b' app/services/` + analogous greps for other builtins
> (`type`, `id`, `dict`, `set`). **Bucket P (if option c):** P1
> catch-block lint expansion; P2 ts-any sweep; P3 OpenAPI↔TS parity.
> **Bucket R (cosmetic carry-forward):** R1 extract shared
> `_OFFENDER_ALLOWLIST` helper module. **Bucket A** (C7, E3, E4,
> F3), **Bucket B** (B1, B2), **Bucket C** (C1, C2, C3, C4) remain
> conditional carry-forwards — act ONLY on triggering need. Follow
> the sequential subagent loop pattern, TDD-first, one diagnosis doc
> per WP under `.claude/lessons-learned/v2.22-wpNN-diagnosis.md`.
> Append lessons to `.claude/lessons-learned/ticketing-v2.22.md`.
> **Forward rules carried from v2.15:** (a) lint-before-sweep when
> class has known shape; (b) by-design enumeration at FIRST surfacing
> of any mixed-population class; (c) two state slots for pages with
> both load-failure and action-failure UX; (d) `PYTEST_CURRENT_TEST`
> is the canonical no-config test-mode sentinel; (e) audit metric
> exporters first when OTel noise surfaces. **Forward rules carried
> from v2.16:** (f) `pkgutil.walk_packages` +
> `warnings.simplefilter('error', ...)` is the audit primitive for
> any compile-time warning class; (g) per-file opt-in beats global
> mock shims for forward-compat flags; (h) `BY-DESIGN:` comments
> answer WHY, not WHERE; (i) honest classification beats stretch
> target; (j) forward-compat flags are forgiving but not free; (k)
> three Bucket-Z items is the soft ceiling per cosmetic version;
> (l) after a structural-debt version, schedule a cosmetic version
> to mop up compile-time / test-time noise. **Forward rules carried
> from v2.17:** (m) lint-before-sweep generalises to
> preventive-hardening; (n) compiler-API pragma blindspot — pragmas
> are NOT AST nodes in any language, bounded per-line regex is the
> right primitive; (o) a 0-offender axis is its own success metric;
> (p) per-line dedupe in lint emission keeps allow-lists stable;
> (q) demo-mode / fixture / registry-barrel sites are legitimate
> BY-DESIGN allow-list residents; (r) `r"""..."""` is repo-canonical
> for any docstring documenting escape / regex / LIKE / shell /
> pragma syntax. **Forward rules carried from v2.18:** (s)
> sweep-after-pin executes cleanly when stale-entry detection runs
> both directions; ALWAYS implement bidirectional stale-detection
> alongside offender detection; (t) line-number-keyed allow-lists are
> fragile against unrelated additions in the same file — consider
> context-snippet or function-name anchoring; (u) re-validate LEGACY
> justifications at sweep time; (v) `Response.json(): Promise<any>`
> is an unsignal-able `any` axis; (w) when backend uses
> `extra="allow"` for variant payloads, the frontend discriminated
> union must key from REQUEST CONTEXT, not response shape; (x) `any`
> hides dead branches — type-tightening surfaces phantom fallbacks;
> (y) file-local OpenAPI mirror interface is a lightweight tightening
> tool. **Forward rules carried from v2.19:** (z) plugin RUNTIME
> health gates typechecker choice — existence isn't enough (REFINED
> by (gg)); (aa) `warn_redundant_casts = true` auto-validates every
> `cast()` call for free; (bb) when 100% of pinned errors are
> BY-DESIGN, the next-version backlog shape is plugin/refactor
> evaluation at the framework boundary, NOT a LEGACY sweep; (cc)
> cross-lint paired-cleanup falls out of bidirectional
> stale-detection on EACH lint — no synchroniser needed; (dd)
> per-line dedupe refinement — collapse keying at
> `path:line:errcode`; (ee) when 4+ lints share a structural skeleton,
> extract shared helper — schedule as a cosmetic version; (ff)
> subprocess-based lints trade cold-start cost for full-tool
> fidelity — acceptable when warm-cache runtime is sub-second AND
> test is `@pytest.mark.slow`-tagged from day one. **Forward rules
> carried from v2.20:** (gg) plugin RUNTIME health = "mypy
> --config-file <config-with-plugin> <target>" returns a clean delta
> — NOT "import plugin_module from REPL"; (hh) plugin unblocking is
> cross-cluster — the plugin attacks the proximate inference, not
> the labelled cluster; (ii) `Mapped[T]` migration is the unit of
> SQLAlchemy 2.x cluster-reduction effort — one model file ≈ 5–10
> mypy keys eliminated; (jj) when a BY-DESIGN rationale becomes
> obsolete via framework / plugin upgrade, the entry's lifecycle is
> BY-DESIGN → deleted, NOT BY-DESIGN → LEGACY → deleted; (kk) PIN
> value is the WORKFLOW, not the taxonomy — BY-DESIGN classification
> is a snapshot, not a verdict; "0 LEGACY" at PIN time means "no
> work YET — wait for the framework boundary to move"; (ll)
> shadow-of-builtin warnings are mypy's free naming-convention
> check — worth a one-time sweep when surfaced; (mm) two-WP attack on
> a single PIN is the right granularity for plugin-reclassification +
> cluster-sweep — config WP first, code WP second, never combine.
> **Forward rules new from v2.21:** (nn) recon caller-counts are
> approximate; expect ±1 internal self-call discovered at edit time;
> when scoping a method rename, ALSO run `grep -n 'self\.<name>\|cls
> \.<name>'` against the declaring file; recon counts are floors,
> not totals; absorb the ±1 surprise in-WP via post-edit grep sweep;
> (oo) test monkey-patches that dispatch on `Model.__table__`
> identity must be widened in lockstep with `pg_insert(Model)`
> rewrites; pre-grep for `if table is X.__table__`,
> `monkeypatch.setattr(...pg_insert...)`, `lambda table, ...`;
> widen predicate to `if table is Model or table is Model.__table__`;
> generalises to any monkey-patch that identity-checks a table/class
> argument whose call-site shape is migrating; (pp) latent
> shadow-of-builtin sites with zero current mypy keys are
> out-of-scope for reactive sweep; flag as preventative-hygiene
> backlog (refines rule (ll): one-time sweep is one-time per
> mypy-key cluster; latent sites become a separate scheduled hygiene
> pass). Pre-flight any rename WP with `grep -rn` across `app/` AND
> `alembic/` AND `tests/` AND inside the declaring file for
> `self.<name>` / `cls.<name>` patterns. Do NOT reintroduce the
> `_v1_deferred.py` skip-hook — per-test deferral uses plain pytest
> markers.

**Cumulative forward rules total: 42 (a-pp).** v2.21 added 3 new rules
(nn, oo, pp) to the 39 carried from v2.20.
