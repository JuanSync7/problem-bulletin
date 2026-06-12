# v2.22 ticketing — lessons learned

Companion to `ticketing-v2.21.md`. v2.22 was the **hybrid (a)+(c)
version**: option (a) preventative-hygiene — landed the latent
`SprintService.list` shadow rename surfaced as forward rule (pp) in
v2.21-WP03 — and option (c) adjacent PIN expansion — broadened the
WP11 OpenAPI↔TS parity lint from 9 to 14 pinned routes. Both worked
**exactly as the v2.20-(kk) / v2.21-(pp) forward rules predicted**: the
SprintService rename produced **zero mypy-key delta** (latent shadow —
confirms rule (pp)) and all five new WP11 parity entries passed on
**first run with zero drift** (confirms field-set parity discipline was
held upstream across WP14/WP32/WP33/WP45). Closing state **28 PIN keys
/ 0 LEGACY** (unchanged), backend **1444 → 1449 P** (+5 parametrize
cases from WP03), frontend **276 P** (untouched), mypy **28 errors /
14 files**. 4 WPs: recon, SprintService preventative rename, WP11
parity expansion, closure.

**Closing baselines:** backend **1449 P / 0 F / 6 skipped / 14 xfailed**
(+5 from WP03 parametrize), frontend **276 P / 0 F** (untouched). Mypy:
**28 raw errors / 28 keys** (unchanged — at the framework-residual
floor).

---

## v2.22-WP01 (G0) — recon

Backend **1444 P**, frontend **276 P**, mypy 28 errors / 28 keys — all
match v2.21 close. Full attack-plan written to
`v2.22-wp01-diagnosis.md`.

**Key recon findings:**
- Confirmed option (a)+(c) hybrid as smallest-safe-next. v2.21 closed
  at the framework-residual floor (28 keys); no E-cluster work
  available without upstream movement.
- H1 `SprintService.list` rename at `app/services/sprints.py:52`
  enumerated as zero-key latent shadow. Pre-flight `grep -rn
  'sprint_service.list\b\|SprintService.list\b'` across `app/` +
  `alembic/` + `tests/` returned a single production caller at
  `app/routes/sprints.py:49` (no test callers, no MCP callers, no
  alembic references).
- WP11 PIN reported as "29 pinned routes" by recon — this was
  **incorrect**; see reconciliation rule (qq) below. Actual size at
  time of recon was 9, expansion target was +5, post-expansion is 14.

**WP ordering:** WP02 = H1 first (smaller blast radius, single caller,
latent — no PIN delta risk); WP03 = parity expansion second (lint-
file edit, +5 parametrize entries; first-run-clean was the success
predicate).

---

## v2.22-WP02 — H1 `SprintService.list → list_all` preventative rename

**Outcome.** 2 files edited (declaration + sole production caller).
Mypy 28 → **28** (zero delta — latent shadow, confirms rule (pp)).
Backend stayed at 1444 P; frontend untouched. PIN lint
`tests/test_typecheck_lint_v219_wp02.py` stayed clean (6 P).

**Files modified (2 production):**
- `app/services/sprints.py:52` — `list` → `list_all`
- `app/routes/sprints.py:49` — caller updated

No internal `self.list(...)` self-calls inside `services/sprints.py`
(unlike `TicketService.search_tickets` in v2.21-WP03). Forward rule
(nn) was nonetheless applied during edit-time via post-edit
`grep -n 'self\.list\|cls\.list' app/services/sprints.py` (empty).

**Untracked-file surprise.** Both `app/services/sprints.py` and
`app/routes/sprints.py` appeared in `git status` as `create mode`
when the WP02 commit landed — `git log --all -- app/services/sprints.py
app/routes/sprints.py` returns ONLY the v2.22-WP02 commit. The Sprint
service was prior-session work left on disk but never committed
between its authoring and v2.22. The WP02 commit therefore added the
service file + the rename in a single create-mode commit. This pattern
is real and surfaces as forward rule (ss) below.

**Residual after WP02.** 28 keys (unchanged — latent shadow had no
PIN entries to delete).

---

## v2.22-WP03 — WP11 OpenAPI↔TS parity coverage expansion (+5 routes)

**Outcome.** `WP11_ROUTES` grew from **9 → 14 entries** (recon-claimed
"29 pinned" was wrong; see rule (qq)). All five new tuples passed on
first run with zero drift — strong evidence the upstream contracts
(WP14 notifications, WP32 PersonPicker, WP33 audit-log API, WP45
activity DTO) had been held in field-set parity throughout. Pytest
1444 → **1449 P** (+5 parametrize cases). Mypy unchanged at 28.
Frontend untouched.

**Routes added (5):**

| Route | Backend schema | TS file | TS type |
|-------|----------------|---------|---------|
| GET /api/v1/agents/activity (items[*]) | `AgentActivityItem` | `audit.ts` | `ActivityEntry` |
| GET /api/v1/audit-log (items[*]) | `AuditLogEntryRead` | `auditLog.ts` | `AuditLogEntry` |
| GET /api/v1/audit-log (items[*].actor) | `PersonRef` | `auditLog.ts` | `AuditLogActor` |
| GET /api/v1/people/search (items[*]) | `PersonRef` | `people.ts` | `PersonRef` |
| GET /api/v1/notifications (items[*].actor) | `PersonRef` | `notifications.ts` | `PersonRef` |

`PersonRef` is pinned three times under different routes / TS-side
type names; each tuple exercises route-existence + schema-vs-TS
comparison independently — no test-level deduplication needed because
the parametrize tuple is keyed by (method, path, schema, ts_file,
ts_type).

**Untracked-file surprise (repeat).** Same as WP02:
`tests/test_openapi_ts_parity_wp11.py` appeared as `create mode` in
the WP03 commit. `git log --all -- tests/test_openapi_ts_parity_wp11.py`
returns ONLY the v2.22-WP03 commit. The lint module itself was
authored earlier (the 9-route base) but was prior-session work left
uncommitted. The +5 expansion landed alongside the file's first
git-tracked appearance. Same pattern as WP02 — forward rule (ss).

**First-run-clean significance.** The +5 expansion had zero drift on
first run. This is the predicted outcome when the pinned surface had
already been held by manual discipline upstream. It is **also** a soft
warning: until the lint is running in CI (mechanically blocking PRs),
the discipline is reviewer-mediated and the deterrent value is
aspirational. Forward rule (rr) below.

**Deferred to v2.23 (from WP03 diagnosis):**
- `SubtreeRow` ↔ TS — TicketRead is nested recursively; the WP11
  parser's "flat interface" support cannot express this without a
  recursive-shape extension. Non-trivial design work.
- `Page<T>` generic parity — the parser pins inner items, not the
  generic envelope. Would either fold into existing WP05 parser
  expansion or require generic-shape support.
- `TicketWatcherRead` / `TicketAttachmentRead` — no hand-written
  frontend interfaces exist yet; pinning requires authoring TS
  interfaces from scratch. Folds naturally into a `Response.json():
  Promise<any>` → `unknown` any-tightening WP (Bucket C C2 from v2.18).

**Residual after WP03.** 28 keys (unchanged); 14 pinned parity
routes.

---

## v2.22-WP04 (closure) — this document

Retrospective written. v2.23 paste-ready seed appended at bottom. Zero
production code touched.

---

## v2.22 retrospective

### Headline numbers

- **Backend:** 1444 → **1449 P** / 0 F / 6 skipped / 14 xfailed (+5
  from WP03 parametrize; zero regressions).
- **Frontend:** 276 P / 0 F — untouched across all 4 WPs.
- **Mypy raw errors:** 28 → 28 (unchanged — at framework-residual
  floor; WP02 was latent shadow with no PIN entries).
- **Mypy allow-list keys:** 28 → 28 (unchanged).
- **Classification:** **0 LEGACY throughout.** No PIN deletions, no
  reclassifications.
- **WP11 parity PIN:** 9 → **14 routes** (+5; first-run-clean).
- **Latent shadow eliminated:** 1 (`SprintService.list` → `list_all`).
- **Real bugs fixed:** 0 (all changes typing-hygiene or PIN
  expansion).
- **Production code touched (`app/`):** 2 files (WP02:
  `services/sprints.py` + `routes/sprints.py`).
- **Test code touched:** 1 file (WP03:
  `tests/test_openapi_ts_parity_wp11.py`).
- **Production regressions introduced:** zero.

### WPs shipped

| WP | Bucket | Summary | PIN delta |
|----|--------|---------|----------:|
| WP01 | G0 | Recon. Confirmed v2.21 close baseline. Mapped H1 (1 declaration + 1 caller) + P3 (+5 parity tuples) attack plans. Recon mis-stated WP11 PIN as "29 routes" — actual was 9 pre-WP03. | ±0 |
| WP02 | H | H1 `SprintService.list → list_all` preventative-hygiene rename. 1 declaration + 1 caller. Latent shadow — zero mypy-key delta confirms rule (pp). | ±0 mypy |
| WP03 | P | P3 OpenAPI↔TS parity expansion: 9 → 14 routes (+5). All five passed first run with zero drift. | +5 parity routes, ±0 mypy |
| WP04 | closure | Retrospective + v2.23 seed. | ±0 |

### Cross-cutting lessons

1. **(qq) Reconciliation rule: closure WP MUST re-count any PIN-size
   figure recon-WPs cite from the working tree.** v2.22-WP01 recon
   reported "29 pinned routes" for the WP11 parity PIN. The actual
   count in `WP11_ROUTES` at that time was 9 (v2.22-WP03 then
   expanded it to 14). Recon may have been reading a stale comment, a
   different file, or counting along a different axis (e.g.
   parametrize cases including unrelated tests). The diagnosis-doc
   number is suggestive but **not authoritative** — the working-tree
   re-count is. Refines rule (kk) (PIN value is the workflow, not the
   taxonomy) by adding: **the workflow includes verifying the
   taxonomy's size at closure time.** Pattern: any time a recon
   document cites a count, the closure WP runs the equivalent
   `grep -c` / `wc -l` / structural-AST query against HEAD before
   citing it in the retrospective. Generalises to allow-list keys,
   parametrize entries, route counts, any list-of-things the recon
   pass enumerated.

2. **(rr) Sweep-after-pin assumption check: zero drift on first run
   means the surface was already disciplined, not that the PIN is
   doing work yet.** v2.22-WP03 added 5 parity entries; all 5 passed
   on first run. The temptation is to read this as "the PIN caught
   nothing because there was nothing to catch — celebrate." The
   accurate read is: **the surface had been held by reviewer
   discipline across WP14 / WP32 / WP33 / WP45 (the authoring WPs);
   the new PIN entries inherit that discipline at the moment of
   addition.** The PIN's deterrent value (catching FUTURE drift) is
   **untested** until either (a) the PIN runs in CI and blocks a PR
   that would have drifted, or (b) a sweep-after-pin iteration
   finds an offender. Strong evidence the PIN captured already-clean
   surfaces is GOOD news (no LEGACY accrual at addition time), but
   does not by itself confirm the PIN works going forward. Generalises
   beyond parity lints to any newly-added structural lint that
   passes first run with zero offenders. Pair with rule (s)
   (sweep-after-pin) and rule (t) (line-keyed allow-lists are
   fragile): the first sweep iteration is the actual test of PIN
   value, not the addition.

3. **(ss) Untracked-but-on-disk file pattern: prior-session work left
   uncommitted will appear as `create mode` in later WPs that touch
   it.** Both v2.22-WP02 (`app/services/sprints.py`,
   `app/routes/sprints.py`) and v2.22-WP03
   (`tests/test_openapi_ts_parity_wp11.py`) committed files whose
   `git log` shows ONLY the v2.22-WP02 / v2.22-WP03 commit — the
   underlying file authoring happened in a prior session and was
   never committed. Subsequent WPs then add the file as `create
   mode` alongside their actual changes, conflating "I authored this
   file" with "I edited this file". Detection: `git log -- <path>`
   for any file the current WP edits — empty result for a file the
   WP doesn't claim to author signals prior-session leakage.
   Mitigation: a housekeeping commit (`v2.NN-WP00: track
   prior-session artifacts`) before functional work begins, OR
   noting the create-mode conflation in the diagnosis doc and the
   retrospective (this WP did the latter; future versions should
   prefer the former). Cross-cuts the version-rollover boundary —
   the prior-session author may have been a different agent or the
   same agent in a different conversation. Generalises to any
   long-lived multi-session repo: the working tree is not the
   commit log, and the gap accumulates silently.

### What stayed deferred (carry to v2.23)

- **Preventative-hygiene (likely empty for v2.23):**
  - v2.22-WP02 cleared the only flagged latent shadow
    (`SprintService.list`). No new latent shadow-of-builtin sites
    surfaced during v2.22. A re-audit grep
    (`grep -rn 'def list\b\|async def list\b' app/services/`,
    plus analogous greps for `type`, `id`, `dict`, `set`) is
    cheap and worth running in v2.23-WP01 recon — but the
    expectation is empty.

- **Parity expansion deferred (v2.22-WP03 diagnosis):**
  - **`SubtreeRow` ↔ TS recursive parity.** Non-trivial — the
    WP11 parser's "flat interface" support cannot express
    recursive shapes. Design work needed before any expansion.
  - **`Page<T>` generic envelope parity.** Folds into WP05
    parser expansion (v2.13 rule (ee) / Bucket B B2). Mechanically
    cleaner than recursive SubtreeRow.
  - **`TicketWatcherRead` / `TicketAttachmentRead` parity.** No
    hand-written frontend interfaces exist — would require
    authoring TS interfaces from scratch. Folds into a
    `Response.json(): Promise<any>` → `unknown` any-tightening
    WP (Bucket C C2 from v2.18 seed).

- **Bucket A** (C7, E3, E4, F3) — still conditional v2.11
  carry-forwards.
- **Bucket B** (B1, B2) — still conditional v2.13 carry-forwards.
- **Bucket C** (C1, C2, C3, C4) — still conditional v2.18
  carry-forwards.
- **Bucket R cosmetic** — `_OFFENDER_ALLOWLIST` helper extract
  (v2.19 rule ee) — 4 lints share the shape; still on backlog from
  v2.19 → v2.20 → v2.21 → v2.22.
- **28 BY-DESIGN typecheck residents — the genuine framework-
  residual floor.** Unchanged from v2.21 close. Per cluster:
  Starlette ASGI `Mount` callable variance (×1), FastAPI
  `add_exception_handler` callable variance (×1), SQLAlchemy
  `Result[Any].rowcount` boundary (×5), joined-load
  `attr-defined` (×~3), co-nullable FK arg-type pair (×2 at
  `services/tickets.py:1195-1196`), scattered single residuals
  (`Mapped[T]` boundary, `coalesce` assignment, dict-item,
  return-value, TYPE_CHECKING name-defined). None reactively
  fixable without upstream Starlette / FastAPI / SQLAlchemy stub
  or plugin improvements. Re-evaluate every N versions per forward
  rule (kk).

### Files touched (rough stats — sum of WP02 + WP03)

- **Production code (`app/`):** 2 files (WP02:
  `app/services/sprints.py` declaration rename;
  `app/routes/sprints.py` caller update).
- **Production code (`frontend/src/`):** 0 files.
- **Alembic (`alembic/versions/`):** 0 files.
- **Config:** 0 files.
- **Lint allow-lists:** 0 files modified (WP03 expanded a parity-lint
  module, not an allow-list).
- **Test code (backend):** 1 file
  (`tests/test_openapi_ts_parity_wp11.py` — WP03 expansion of
  `WP11_ROUTES` 9 → 14 + first-time git-tracking).
- **Docs (`.claude/lessons-learned/`):** 3 per-WP diagnosis files
  (`v2.22-wp01-diagnosis.md`, `v2.22-wp02-diagnosis.md`,
  `v2.22-wp03-diagnosis.md`) + this retrospective.

---

## v2.23 starting prompt seed

v2.22 closed as a **hybrid (a)+(c) version** — preventative-hygiene
landed (SprintService rename, latent, 0 PIN delta — confirms rule
(pp)) + adjacent-PIN expansion landed (WP11 parity 9 → 14, all five
first-run-clean — confirms field-set parity discipline held upstream).
Baselines: backend **1449 P / 0 F / 6 skipped / 14 xfailed**, frontend
**276 P / 0 F**, mypy **28 errors / 28 allow-list keys (0 LEGACY)**.
v2.22 added 3 new forward rules: (qq) reconciliation of recon PIN-size
figures at closure, (rr) sweep-after-pin first-run-clean is GOOD news
but PIN deterrent value is untested until CI-blocking or first-sweep
catch, (ss) untracked-but-on-disk prior-session files appear as
`create mode` in later WPs — separate housekeeping commit is the
mitigation.

**v2.22 confirmed both predictions:** (pp) "latent shadows have zero
mypy-key delta — they are preventative, not reductive" and the rule
(kk) corollary that 28 is the framework-residual floor (no movement
possible without upstream Starlette/FastAPI/SQLAlchemy changes). Three
shapes for v2.23:

- **(a) PREVENTATIVE-HYGIENE — likely empty.** v2.22-WP02 cleared the
  only flagged latent shadow. v2.23-WP01 recon should run the
  shadow-of-builtin grep across `app/services/` (and analogous greps
  for `type`, `id`, `dict`, `set`), but the expectation is empty. If
  empty, drop bucket (a) for v2.23 and revisit at v2.24.
- **(b) UPSTREAM-WAIT — still legitimate "we are done here for now".**
  Declare 28 the floor; monitor mypy / SQLAlchemy / Starlette /
  FastAPI releases for framework-typing improvements; no active
  typecheck work. Pair with a periodic re-evaluation WP per rule
  (kk). **This remains the honest fallback** when toolchain capacity
  is constrained.
- **(c) PARITY EXPANSION continued — three deferred items from
  v2.22-WP03.** P3a `SubtreeRow` recursive parity (non-trivial — the
  WP11 parser needs recursive-shape support; design work, not a
  mechanical addition); P3b `Page<T>` generic envelope parity (folds
  into WP05 parser expansion / Bucket B B2; mechanically cleaner than
  recursive); P3c `TicketWatcherRead` / `TicketAttachmentRead` parity
  (no hand-written TS yet — folds into option (d) below).
- **(d) ANY-TIGHTENING WP on `Response.json(): Promise<any>` →
  `unknown` (Bucket C C2 from v2.18 seed).** Surfaced naturally from
  WP03 deferred items: pinning `TicketWatcherRead` /
  `TicketAttachmentRead` parity requires authoring TS interfaces
  from scratch; that authoring is itself a `Response.json()` →
  `unknown` + runtime-parser tightening sweep. Forward rule (v) from
  v2.18 still applies — this is an unsignal-able `any` axis until
  hand-touched. Pick ONE candidate
  (`TicketWatcherRead` OR `TicketAttachmentRead`, not both) to
  bound blast radius.

**Recommend (c) limited (P3b `Page<T>` via WP05 if mechanically
clean) + (d) one any-tightening WP on `TicketWatcherRead` OR
`TicketAttachmentRead`.** (b) remains the still-valid "stop here"
position if capacity is constrained. (a) probably empty — run the
recon grep and confirm.

### v2.23 backlog

#### Bucket P — Adjacent PIN expansion continued (PRIMARY v2.23 work, RECOMMENDED option (c) limited)

P3a. **`SubtreeRow` recursive parity.** Requires WP11 parser
    recursive-shape support. DESIGN WORK FIRST — non-trivial. Defer
    until parser supports it or skip.
P3b. **`Page<T>` generic envelope parity.** Folds into WP05 parser
    expansion (Bucket B B2 / v2.13 rule (ee)). Mechanically cleaner.
    Pre-flight: confirm WP05 parser supports generic envelope shape
    or extend it.
P3c. **`TicketWatcherRead` / `TicketAttachmentRead` parity.** No
    hand-written frontend interfaces exist — folds into option (d).

#### Bucket D — Any-tightening WP (RECOMMENDED option (d), pick ONE)

D1. **`TicketWatcherRead` frontend interface + parity pin.** Author
    hand-written TS interface from scratch, replace existing
    `Response.json(): Promise<any>` callsites with `unknown` +
    runtime parser, then pin under WP11. Forward rule (v) /
    (y).
D2. **`TicketAttachmentRead` frontend interface + parity pin.**
    Same shape as D1. Pick D1 OR D2 — not both — to bound blast
    radius.

#### Bucket H — Preventative-hygiene (LIKELY EMPTY for v2.23)

H1. **Re-audit grep for latent shadow-of-builtin sites.**
    `grep -rn 'def list\b\|async def list\b' app/services/` +
    analogous greps for `type`, `id`, `dict`, `set`. Run in
    v2.23-WP01 recon. If empty, drop bucket H for v2.23.

#### Bucket R — Cosmetic refactor (carry-forward from v2.19 → v2.20 → v2.21 → v2.22)

R1. **Extract shared `_OFFENDER_ALLOWLIST` helper module** across
    the 4 lints (bare-catch, ts-any, pragma, typecheck).
    Mechanical refactor.

#### Bucket A — Conditional v2.11 carry-forwards (act only on triggering need)

A1. C7 `decode_email_body` helper. A2. E3 KindPill 7th surface.
A3. E4 `useSearchV2` ergonomic follow-ups. A4. F3 TipTap second-
consumer extraction.

#### Bucket B — Conditional v2.13 carry-forwards

B1. Per-arm `refresh_total` opt-in syntax. B2. WP05 OpenAPI↔TS parser
expansion (folds into P3b above if option (c) lands).

#### Bucket C — v2.18 surfaced candidates (conditional)

C1. Promote `EditSuggestionRead` / `AttachmentRead`. C2.
`Response.json(): Promise<any>` → `unknown` sweep (folds into D1/D2
if option (d) lands). C3. `actor_type` enum-backed column migration.
C4. Context-snippet anchoring across lints.

### v2.23 prompt seed (paste-ready)

> Proceed with v2.23 of the problem-bulletin ticketing system.
> v2.22 retrospective + carry-forward backlog live at the bottom of
> `.claude/lessons-learned/ticketing-v2.22.md`. Baselines: backend
> **1449 P / 0 F / 6 skipped / 14 xfailed**, frontend **276 P / 0 F**,
> mypy **28 errors / 28 allow-list keys (0 LEGACY)**, WP11 parity
> PIN **14 routes**. **v2.22 was the hybrid (a)+(c) version — landed
> preventative-hygiene `SprintService.list → list_all` rename
> (latent, 0 mypy delta — confirms rule (pp)) + WP11 parity
> expansion 9 → 14 routes (all five first-run-clean — confirms
> field-set parity discipline held upstream via WP14/WP32/WP33/WP45).**
> v2.22 reached the same framework-residual floor as v2.21 (28 keys,
> all upstream-blocked). Four shapes: **(a) PREVENTATIVE-HYGIENE —
> likely empty** (v2.22-WP02 cleared the only flagged latent shadow;
> v2.23-WP01 recon should run shadow-of-builtin grep and confirm
> empty); **(b) UPSTREAM-WAIT — legitimate "we are done here for
> now"**: declare 28 the floor, monitor framework releases; **(c)
> PARITY EXPANSION continued**: P3a SubtreeRow recursive (non-trivial
> design work — skip unless parser is extended), P3b Page<T> generic
> envelope (mechanical, folds into WP05 parser expansion), P3c
> TicketWatcherRead / TicketAttachmentRead (no hand-written TS —
> folds into option d); **(d) ANY-TIGHTENING WP**: D1
> TicketWatcherRead frontend interface + parity pin OR D2
> TicketAttachmentRead frontend interface + parity pin — pick ONE to
> bound blast radius; replaces `Response.json(): Promise<any>` with
> `unknown` + runtime parser per rules (v) / (y). **Recommend (c)
> limited (P3b only, IF WP05 parser supports it) + (d) one
> any-tightening WP.** **(b) remains the still-valid "stop here"
> position when capacity is constrained.** **Bucket H (likely
> empty):** H1 re-audit grep across `app/services/`. **Bucket R
> (cosmetic carry-forward):** R1 extract shared `_OFFENDER_ALLOWLIST`
> helper module across 4 lints. **Bucket A** (C7, E3, E4, F3),
> **Bucket B** (B1, B2), **Bucket C** (C1, C2, C3, C4) remain
> conditional carry-forwards — act ONLY on triggering need. Follow
> the sequential subagent loop pattern, TDD-first, one diagnosis doc
> per WP under `.claude/lessons-learned/v2.23-wpNN-diagnosis.md`.
> Append lessons to `.claude/lessons-learned/ticketing-v2.23.md`.
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
> **Forward rules carried from v2.21:** (nn) recon caller-counts are
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
> pass). **Forward rules new from v2.22:** (qq) closure WP MUST
> re-count any PIN-size figure recon-WPs cite from the working
> tree — recon's number is suggestive, not authoritative; refines
> rule (kk) by adding that the workflow includes verifying the
> taxonomy's size at closure time; generalises to allow-list keys,
> parametrize entries, route counts, any list-of-things recon
> enumerated; (rr) sweep-after-pin first-run-clean is GOOD news (no
> LEGACY accrual at addition time) but the PIN's deterrent value
> remains UNTESTED until either CI-blocking or the first sweep
> iteration catches an offender; the surface was held by reviewer
> discipline upstream — celebrate but flag; pair with rules (s) and
> (t) — the first sweep is the actual PIN-value test, not the
> addition; (ss) untracked-but-on-disk files from prior sessions
> will appear as `create mode` in later WPs that touch them,
> conflating "I authored" with "I edited"; detection: `git log --
> <path>` returns empty for a file the WP doesn't claim to author;
> mitigation: separate housekeeping commit (`v2.NN-WP00: track
> prior-session artifacts`) before functional work; cross-cuts the
> version-rollover boundary since the prior-session author may have
> been a different agent or the same agent in a different
> conversation. Do NOT reintroduce the `_v1_deferred.py` skip-hook
> — per-test deferral uses plain pytest markers.

**Cumulative forward rules total: 45 (a-ss).** v2.22 added 3 new rules
(qq, rr, ss) to the 42 carried from v2.21.
