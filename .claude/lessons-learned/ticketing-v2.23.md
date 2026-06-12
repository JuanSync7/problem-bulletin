# v2.23 ticketing — lessons learned

Companion to `ticketing-v2.22.md`. v2.23 was the **hybrid (c)+(d)
version**: option (c) parity expansion — Page<T> envelope parity
expansion in WP02 added +2 pins (`Page_TicketRead_` generic +
`AuditLogPage` flat), both first-run-clean — and option (d)
any-tightening adjacent — WP03 introduced a net-new typed
`TicketWatcher` consumer (interface + `listTicketWatchers` helper) and
pinned the inner-item field set in WP11. v2.23 did **not** tighten an
existing `any`; the watchers route had **zero frontend callers**, so
WP03 captured the contract upstream of any future UI integration —
a cousin of preventative-hygiene, applied to a typed-consumer surface
instead of a shadow-of-builtin. Closing state **28 PIN keys /
0 LEGACY** (unchanged), backend **1449 → 1452 P** (+3 parametrize
cases: WP02 +2, WP03 +1), frontend **276 P** (untouched), mypy
**28 errors / 14 files**. 4 WPs: recon, Page<T> +2, TicketWatcherRead
typed-consumer + WP11 pin, closure.

**Closing baselines:** backend **1452 P / 0 F / 6 skipped / 14 xfailed**
(+3 over v2.22 close), frontend **276 P / 0 F** (untouched), mypy
**28 raw errors / 28 keys** (unchanged — at the framework-residual
floor). WP05 parametrize: 15 → **17** (+2 from WP02). WP11
parametrize: 14 → **15** (+1 from WP03).

---

## v2.23-WP01 (G0) — recon

Backend **1449 P**, frontend **276 P**, mypy 28 errors / 14 files —
all match v2.22 close. Full attack-plan written to
`v2.23-wp01-diagnosis.md`.

**Key recon findings:**
- WP05 parity PIN size **5 PAGE + 1 UNION + 3 FLAT = 9 parametrize
  entries**, not 14 (the v2.22 retrospective "14" figure counts the
  WP11 PIN, a different module). Per rule (qq), re-counted at recon
  time via direct read of `tests/test_openapi_ts_parity_wp05_v213.py`.
- Enumerated all 12 `Page*`-shaped OpenAPI schemas; 5 already pinned,
  3 unpinnable (no hand-written TS counterpart:
  `Page_AgentActivityItem_`, `Page_TicketAttachmentRead_`,
  `CursorPage_ProblemResponse_`), 2 pinnable for WP02
  (`Page_TicketRead_` via `TicketsPage extends Page<TicketDTO>`,
  `AuditLogPage` flat).
- TicketWatcherRead (5 fields) chosen over TicketAttachmentRead
  (10 fields incl. file metadata) for WP03 to bound blast radius and
  avoid attachments-UX design questions (signed URLs, agent-step
  surfacing).
- Recon recommended adding the `Page_TicketWatcherRead_` *wrapper*
  pin to WP05_PAGE_PAIRS in WP03. WP03 implementation found this
  would be **redundant** (the wrapper field set is already pinned by
  the 6 existing PAGE_PAIRS entries against the same `Page<T>`
  declaration) and instead pinned the **inner** `TicketWatcherRead`
  field set in WP11 — see rule (tt) below.

**Pre-existing dirty-tree noted.** WP01 flagged `frontend/src/App.css`,
`frontend/src/pages/Kanban/{KanbanBoard,index}.tsx`,
`frontend/src/pages/ProblemDetail.{css,tsx}`,
`frontend/vite.config.ts`, plus `.backups/` and `.claude/`
untracked. Recommended separate `v2.23-WP00` housekeeping commit
before functional work, per rule (ss). **Was not executed** — see
rule (vv) below for the in-WP sweep that occurred in WP03.

**WP ordering:** WP02 first (lint-only edit, zero source-code blast
radius); WP03 second (new TS interface + helper, lint append); WP04
closure.

---

## v2.23-WP02 — Page<T> envelope parity expansion (+2 pins)

**Outcome.** 1 file edited (`tests/test_openapi_ts_parity_wp05_v213.py`).
Backend 1449 → **1451 P** (+2 parametrize cases). Frontend untouched
(276 P). Mypy untouched (28 / 14). Both new tuples first-run-clean.

**Tuples added (2):**

| List | Route | Backend schema | TS file | TS type |
|------|-------|----------------|---------|---------|
| WP05_PAGE_PAIRS | GET /api/v1/tickets/search | `Page_TicketRead_` | `tickets.ts` | `Page<TicketDTO>` |
| WP05_FLAT_PAIRS | GET /api/v1/audit-log | `AuditLogPage` | `auditLog.ts` | `AuditLogPage` |

Both passed first-run-clean — strong evidence the wrapper field set
(`items, next_cursor, total`) has been held in parity discipline
across all paging-route authoring (rule (rr) framing). The
`TicketsPage extends Page<TicketDTO>` subclass pattern integrates
cleanly with the existing parser (which targets the generic
`Page<T>` declaration, not the subclass), so no parser extension was
needed.

**Residual after WP02.** 28 keys (unchanged); WP05 PIN 9 → 11
parametrize entries (5 PAGE + 1 UNION + 3 FLAT + 2 new = 11; the
17-passed figure in the WP02 diagnosis doc includes 6 synthetic
parser unit-tests that share the file).

---

## v2.23-WP03 — TicketWatcherRead typed consumer + WP11 inner-pair pin (+1)

**Outcome.** 2 files modified: `frontend/src/api/tickets.ts` (new
interface + helper) and `tests/test_openapi_ts_parity_wp11.py`
(+1 WP11_ROUTES tuple). Backend 1451 → **1452 P** (+1 parametrize
case). Frontend 276 P (preserved). Mypy untouched. First-run-clean.

**TicketWatcher interface added (5 fields):**

```ts
export interface TicketWatcher {
  id: string;
  ticket_id: string;
  watcher_id: string;
  watcher_type: "user" | "agent";
  created_at: string;
}
export async function listTicketWatchers(
  idOrKey: string,
): Promise<Page<TicketWatcher>>;
```

`watcher_type` discriminator mirrors the assignee-type chip pattern
landed in WP47-WP49. No UI integration in this WP — net-new typed
surface, zero existing call sites to migrate.

**WP11_ROUTES += 1 tuple:**

| Route | Backend schema | TS file | TS type |
|-------|----------------|---------|---------|
| GET /api/v1/tickets/{id_or_key}/watchers (items[*]) | `TicketWatcherRead` | `tickets.ts` | `TicketWatcher` |

**Home-selection refinement (rule (tt) below).** Recon recommended
adding the *wrapper* pin to WP05_PAGE_PAIRS. WP03 found that the
**inner** WP11 pin is where the new signal lives — the wrapper field
set is already covered 6× by existing PAGE_PAIRS entries against the
same `Page<T>` declaration. The wrapper pin would have re-asserted
the identical `{items, next_cursor, total}` field set against the
same TS source; the inner pin captures the 5-field
`TicketWatcher`/`TicketWatcherRead` contract that has no prior
coverage.

**Pre-existing dirty-tree sweep (rule (vv) below).** The
`frontend/src/api/tickets.ts` file already had **substantial
pre-existing modifications** on the working tree before WP03 began
(per WP01 rule (ss) flagging). Specifically:

* `TicketStatus` gained `"backlog"` variant.
* `TicketPriority` renamed `lowest/low/medium/high/highest` →
  `low/medium/high/urgent`.
* `TicketType` gained `"workpackage"` prefix.
* `TicketLinkType` gained `clones`, `is_cloned_by`, `parent_of`,
  `child_of` variants (with two tombstoned via runtime guard).
* New `WRITABLE_LINK_TYPES` array + `assertWritableLinkType` helper.
* `parseApiError` import + docstring addendum.
* Numerous `TicketDTO` field renames/additions (`display_id` replaces
  `key`/`project_id`, etc.).

These pre-existing modifications had been on disk through both v2.22
close and v2.23-WP02 — passing **1449 P** then **1451 P** on the
implicit guarantee that the frontend baseline (276 P) covered them.
WP03's commit therefore swept these into the same commit as the
WP03 functional changes (TicketWatcher interface + helper). The
WP03 commit message documented this explicitly. Per rule (vv): the
in-WP sweep is acceptable when the WP **must** edit the same file —
forcing a separate `v2.23-WP00` housekeeping commit would have
required either (a) two passes through `tickets.ts` (housekeeping
then functional) or (b) a stash-pop dance — both higher risk than
the actual outcome.

**Residual after WP03.** 28 keys (unchanged); WP11 PIN 14 → 15
parametrize entries.

---

## v2.23-WP04 (closure) — this document

Retrospective written. v2.24 paste-ready seed appended at bottom.
Zero production code touched in this WP.

---

## v2.23 retrospective

### Headline numbers

- **Backend:** 1449 → **1452 P** / 0 F / 6 skipped / 14 xfailed
  (+3 from parametrize: WP02 +2, WP03 +1; zero regressions).
- **Frontend:** 276 P / 0 F — untouched across all 4 WPs by test
  count (276 P preserved). New `TicketWatcher` interface + helper
  added in WP03; no new vitest file (compile-time guarantee covers
  the 5 string properties; lint covers the OpenAPI parity).
- **Mypy raw errors:** 28 → 28 (unchanged — at framework-residual
  floor; no Python source touched, no plugin movement).
- **Mypy allow-list keys:** 28 → 28 (unchanged).
- **Classification:** **0 LEGACY throughout.** No PIN deletions, no
  reclassifications.
- **WP05 parity PIN:** 9 → **11 parametrize entries** (+2;
  first-run-clean).
- **WP11 parity PIN:** 14 → **15 parametrize entries** (+1;
  first-run-clean).
- **Net-new typed consumers introduced:** 1 (`TicketWatcher` +
  `listTicketWatchers`).
- **Latent shadow-of-builtin sites eliminated:** 0 (none surfaced).
- **Real bugs fixed:** 0 (all changes typing-hygiene or PIN
  expansion).
- **Production code touched (`app/`):** 0 files.
- **Production code touched (`frontend/src/`):** 1 file
  (`frontend/src/api/tickets.ts` — WP03; includes substantial
  in-WP sweep of pre-existing dirty-tree modifications).
- **Test code touched:** 2 files
  (`tests/test_openapi_ts_parity_wp05_v213.py` — WP02;
  `tests/test_openapi_ts_parity_wp11.py` — WP03).
- **Production regressions introduced:** zero.

### WPs shipped

| WP | Bucket | Summary | PIN delta |
|----|--------|---------|----------:|
| WP01 | G0 | Recon. Confirmed v2.22 close baseline. Mapped Page<T> +2 candidate set, TicketWatcherRead vs TicketAttachmentRead trade-off. Recon mis-routed the WP03 pin home (WP05 wrapper vs WP11 inner-pair); WP03 corrected. | ±0 |
| WP02 | P | P3b Page<T> envelope parity expansion: `Page_TicketRead_` + `AuditLogPage` pinned. Both first-run-clean. | +2 WP05 routes, ±0 mypy |
| WP03 | D | D1 TicketWatcherRead typed-consumer introduction + WP11 inner-pair pin. Net-new TS interface + helper; in-WP sweep of pre-existing dirty-tree `tickets.ts` modifications. | +1 WP11 route, ±0 mypy |
| WP04 | closure | Retrospective + v2.24 seed. | ±0 |

### Cross-cutting lessons

1. **(tt) Parity-pin home selection: `WP05` captures envelope shape
   (`Page<T>` / union / flat wrapper); `WP11` captures inner-item
   field sets. For `Page[X]`-returning routes, the **new signal
   lives in WP11** (inner item) unless WP05 hasn't pinned the
   wrapper shape yet for that route.** WP01 recon framed
   TicketWatcherRead as a candidate for *either* WP05_PAGE_PAIRS
   (wrapper-symmetric) *or* WP11_ROUTES (inner-pair). WP03 found
   the WP05 entry would be **redundant** — the wrapper field set
   `{items, next_cursor, total}` is already pinned by the 6
   existing PAGE_PAIRS entries against the same generic `Page<T>`
   TS declaration; a 7th entry would re-assert the identical field
   set against the same source. The WP11 inner-pair pin captured
   the new 5-field contract — that's the value-add. Refines rule
   (qq) (recon counts are floors): recon's pin-home recommendation
   is *also* a floor — verify at implementation time whether the
   recommended home adds new signal or merely duplicates an
   existing pin. Generalises to any expand-the-parity-lint WP
   where the candidate route has multiple plausible lint homes.

2. **(uu) Net-new typed consumer is a valid v.NN deliverable even
   with no existing `any` to clear.** v2.18 framed
   any-tightening as the workflow for axes where `Response.json():
   Promise<any>` had been used. v2.23-WP03 introduced a typed
   `TicketWatcher` interface for a route with **zero frontend
   callers** — no `any` site existed, because no consumer existed.
   The value buy is **upstream contract capture**: the eventual UI
   integration (TicketDetail watcher list, or a future watcher
   sidebar) will be written *against* the pinned interface, so it
   cannot drift from the OpenAPI schema. Cousin of rule (rr)
   (sweep-after-pin first-run-clean is GOOD news but PIN deterrent
   value is untested): here the deterrent value is *prospective*
   (catching backend renames between now and the UI integration)
   rather than retrospective (catching drift already in flight).
   Generalises to any future route-without-consumer where the
   backend schema is non-trivial and the eventual UI integration
   is likely. Pair with rule (v) (`Response.json(): Promise<any>`
   is unsignal-able): authoring the typed consumer **before** the
   UI integration is the way to avoid the `any`-shaped trap from
   appearing in the first place.

3. **(vv) Pre-existing dirty-tree modifications may be swept into a
   WP commit when the WP must edit the same file — in-WP mitigation
   is acceptable when file overlap is unavoidable.** Rule (ss)
   prescribed a separate housekeeping commit
   (`v2.NN-WP00: track prior-session artifacts`) as the mitigation
   for untracked/dirty files. v2.23-WP03 needed to edit
   `frontend/src/api/tickets.ts`, which already had **substantial
   pre-existing modifications** on the working tree (enum
   additions, helper functions, field renames). A separate
   `v2.23-WP00` commit would have required either (a) reverting
   the working-tree changes to commit them in isolation, then
   re-applying them before WP03 edits — high risk of merge error
   — or (b) a stash-pop dance with equivalent risk. The in-WP
   sweep (commit message documents the conflation explicitly,
   diagnosis doc enumerates the pre-existing modifications) was
   the lower-risk path. **Refines rule (ss):** detection still
   matters (the WP must know what it's sweeping in), but the
   mitigation may be **in-WP** rather than a separate commit when
   file overlap is unavoidable. Generalises to any housekeeping
   pattern where the housekeeping target and the next functional
   WP both must touch the same file — separation has a cost, and
   bundling is acceptable if documented.

### What stayed deferred (carry to v2.24)

- **Preventative-hygiene (likely empty for v2.24):**
  - No new latent shadow-of-builtin sites surfaced during v2.23
    (no Python source touched in WP02 or WP03). The v2.22-WP02
    sweep cleared the only flagged site (`SprintService.list`);
    v2.23-WP01 did not re-run the shadow-of-builtin grep
    (no Python work). Run cheap re-audit
    (`grep -rn 'def list\b\|async def list\b' app/services/`
    plus `type` / `id` / `dict` / `set` analogues) in
    v2.24-WP01 — expectation remains empty.

- **Parity expansion deferred (v2.23-WP01 recon enumeration):**
  - **`Page_AgentActivityItem_` wrapper pin** — defer until
    `audit.ts` upgrades from `ActivityEntry[]` to
    `Page<ActivityEntry>` (the endpoint already returns a Page
    envelope; the frontend strips it). Forward-looking refactor,
    not a parity expansion.
  - **`Page_TicketAttachmentRead_` + `TicketAttachmentRead` typed
    consumer** — 10 fields, requires attachments UX decisions
    (signed-URL strategy, agent-step surfacing). Mirror v2.23-WP03
    pattern when the UI work is in scope.
  - **`CursorPage_ProblemResponse_`** — defer until the problems
    API gains a hand-written TS Page wrapper. Currently uses
    inline pagination shape.
  - **`Page_TicketWatcherRead_` wrapper pin in WP05_PAGE_PAIRS** —
    could be added for symmetry with the other 6 entries, but adds
    no new signal until the watchers route either gains its own TS
    Page subclass or the generic `Page<T>` declaration drifts. Per
    rule (tt), redundant pin — skip.

- **`SubtreeRow` recursive parity** — carry from v2.22. Non-trivial
  — the WP11/WP05 parser cannot express recursive shapes. Design
  work needed before any expansion.

- **`TicketWatcher` UI integration** — TicketDetail could render a
  watcher list using the new helper. Out of scope for a parity-lint
  WP; surfaces in v2.24+ only if the UI work is prioritised.

- **Bucket A** (C7, E3, E4, F3) — still conditional v2.11
  carry-forwards.
- **Bucket B** (B1, B2 — B2 partially landed via WP05 generic
  envelope parity in v2.13 + v2.23-WP02; remaining unpinned
  Page<T> entries deferred per above) — still conditional v2.13
  carry-forwards.
- **Bucket C** (C1, C2, C3, C4) — still conditional v2.18
  carry-forwards. C2 (`Response.json(): Promise<any>` → `unknown`
  sweep) is the natural follow-on to v2.23-WP03 if the frontend
  `api/` layer is audited for genuine `any`-typed JSON parsing.

- **Bucket R cosmetic** — `_OFFENDER_ALLOWLIST` helper extract
  (v2.19 rule (ee)) — 4 lints share the shape; still on backlog
  from v2.19 → v2.20 → v2.21 → v2.22 → v2.23.

- **28 BY-DESIGN typecheck residents — the genuine framework-
  residual floor.** Unchanged from v2.21/v2.22 close. Per cluster:
  Starlette ASGI `Mount` callable variance (×1), FastAPI
  `add_exception_handler` callable variance (×1), SQLAlchemy
  `Result[Any].rowcount` boundary (×5), joined-load `attr-defined`
  (×~3), co-nullable FK arg-type pair (×2 at
  `services/tickets.py:1195-1196`), scattered single residuals
  (`Mapped[T]` boundary, `coalesce` assignment, dict-item,
  return-value, TYPE_CHECKING name-defined). None reactively
  fixable without upstream Starlette / FastAPI / SQLAlchemy stub
  or plugin improvements. Re-evaluate every N versions per rule
  (kk).

- **Dirty-tree housekeeping (v2.24-WP00 candidate).** The working
  tree carried ~390 modified/untracked files at v2.23 open per WP02
  diagnosis (`.backups/`, `.claude/`, plus the
  `frontend/src/{App.css, pages/Kanban/*, pages/ProblemDetail.*,
  vite.config.ts}` files). WP03 swept the `tickets.ts` subset
  in-line per rule (vv). The remaining dirty files were not touched
  by v2.23. A dedicated `v2.24-WP00` housekeeping commit to triage
  these is a legitimate next-version candidate — see seed below.

### Files touched (rough stats — sum of WP02 + WP03)

- **Production code (`app/`):** 0 files.
- **Production code (`frontend/src/`):** 1 file
  (`frontend/src/api/tickets.ts` — WP03: new
  `TicketWatcher` interface + `listTicketWatchers` helper, plus
  in-WP sweep of pre-existing dirty-tree modifications per rule
  (vv)).
- **Alembic (`alembic/versions/`):** 0 files.
- **Config:** 0 files.
- **Lint allow-lists:** 0 files modified (WP02/WP03 expanded parity-
  lint modules, not allow-lists).
- **Test code (backend):** 2 files
  (`tests/test_openapi_ts_parity_wp05_v213.py` — WP02 +2 entries;
  `tests/test_openapi_ts_parity_wp11.py` — WP03 +1 entry).
- **Docs (`.claude/lessons-learned/`):** 3 per-WP diagnosis files
  (`v2.23-wp01-diagnosis.md`, `v2.23-wp02-diagnosis.md`,
  `v2.23-wp03-diagnosis.md`) + this retrospective.

---

## v2.24 starting prompt seed

v2.23 closed as a **hybrid (c)+(d) version** — Page<T> envelope
parity expansion landed (+2 pins: `Page_TicketRead_` generic +
`AuditLogPage` flat — both first-run-clean) + TicketWatcherRead
typed-consumer introduction landed (net-new TS interface + helper +
WP11 inner-pair pin — first-run-clean, no `any` to clear, contract
captured upstream of any UI integration). Baselines: backend
**1452 P / 0 F / 6 skipped / 14 xfailed**, frontend **276 P / 0 F**,
mypy **28 errors / 28 allow-list keys (0 LEGACY)**. v2.23 added
3 new forward rules: (tt) parity-pin home selection (WP05 envelope
vs WP11 inner-item; for `Page[X]` routes the new signal lives in
WP11), (uu) net-new typed consumer is valid even with no `any` to
clear (prospective deterrent value via upstream contract capture),
(vv) pre-existing dirty-tree modifications may be swept into a WP
commit when file overlap is unavoidable (refines rule (ss)).

**v2.23 confirmed v2.22's predictions:** rule (qq) (closure re-counts
recon's PIN-size figures) caught a "14 routes" → 9 mismatch at
WP01 recon (the 14 was the v2.22-close WP11 count, not the v2.23-
open WP05 count). Rule (rr) (first-run-clean is GOOD news but
deterrent value untested) held across all 3 new pins in WP02+WP03.
Rule (ss) (untracked-but-on-disk prior-session leakage) was active
on `tickets.ts` and was mitigated in-WP per the new rule (vv) rather
than via a separate housekeeping commit.

Five shapes for v2.24:

- **(a) PREVENTATIVE-HYGIENE — likely empty.** v2.22-WP02 cleared
  the only flagged latent shadow; no new sites surfaced in v2.23.
  v2.24-WP01 recon should run the shadow-of-builtin grep across
  `app/services/` (and analogous greps for `type`, `id`, `dict`,
  `set`), but the expectation is empty. If empty, drop bucket (a)
  for v2.24 and revisit at v2.25.
- **(b) UPSTREAM-WAIT — still legitimate "we are done here for now".**
  Declare 28 the floor; monitor mypy / SQLAlchemy / Starlette /
  FastAPI releases for framework-typing improvements; no active
  typecheck work. Pair with a periodic re-evaluation WP per rule
  (kk). **Remains the honest fallback** when toolchain capacity is
  constrained.
- **(c) PARITY EXPANSION continued.** Three deferred items from
  v2.23-WP01 recon:
  - P3c **`TicketAttachmentRead` typed consumer + WP11 pin**
    (10 fields incl. file metadata — `filename`, `content_type`,
    `byte_size`, `storage_path`, `agent_step_id`). Mirror
    v2.23-WP03 pattern. Larger blast radius — requires
    attachments-UX decisions if pursued as a full any-tightening
    sweep with UI integration. As a **pure parity pin** (no UI
    integration, no `any` to clear), the contract-capture value
    is high; as a UI surface, it's an entire feature.
  - P3d **Re-evaluate `Page_AgentActivityItem_` /
    `Page_TicketAttachmentRead_` / `CursorPage_ProblemResponse_`**
    wrapper pins — only pinnable if/when their TS counterparts are
    authored. Defer unless one of the consumers is upgraded.
  - P3e **SubtreeRow recursive parity** — carry from v2.22.
    Non-trivial design work on the WP11/WP05 parser. Skip unless
    parser is extended.
- **(d) ANY-TIGHTENING continued.** Same as v2.22 seed —
  `Response.json(): Promise<any>` → `unknown` sweep across the
  frontend `api/` layer (Bucket C C2 from v2.18 seed). Forward rule
  (v) (unsignal-able `any` axis) still applies — pick a targeted
  candidate route + page-pair rather than a blanket sweep.
- **(e) DIRTY-TREE HOUSEKEEPING — legitimate v2.24-WP00 candidate.**
  The working tree carried ~390 modified/untracked files at v2.23
  open. WP03 swept `tickets.ts` in-line; the remainder
  (`.backups/`, `.claude/`, `frontend/src/App.css`, Kanban tsx,
  ProblemDetail tsx/css, `vite.config.ts`) is still dirty. A
  dedicated v2.24-WP00 to triage and commit (or .gitignore) these
  may be warranted before further functional WP scoping — the
  WP02 surprise count of 390 files in `git status` makes accurate
  blast-radius estimation difficult for any v2.24 WP that touches
  affected directories.

**Recommend (e) FIRST — v2.24-WP00 housekeeping — followed by (c)
TicketAttachmentRead typed consumer + WP11 pin (mirror of v2.23-WP03
on a richer schema) as the working WP.** (b) remains the still-valid
"stop here" position if capacity is constrained.

### v2.24 backlog

#### Bucket WP00 — Dirty-tree housekeeping (RECOMMENDED first)

WP00. **Triage ~390 modified/untracked files.** Either commit
   intentional changes (App.css, Kanban tsx, ProblemDetail.{tsx,css},
   vite.config.ts) as a `v2.24-WP00: track prior-session artifacts`
   commit per rule (ss), or move to `.gitignore` if scratch
   (`.backups/`, `.claude/` if not meant to be tracked). Reduces
   blast-radius noise for subsequent WPs.

#### Bucket P — Adjacent PIN expansion continued (RECOMMENDED option (c))

P3c. **TicketAttachmentRead typed consumer + WP11 pin.** 10 fields,
    mirror of v2.23-WP03. Pure parity pin (no UI integration) is
    low-risk; UI integration is a separate feature and out of scope.
P3d. Wrapper-pin candidates (deferred until TS counterparts exist):
    `Page_AgentActivityItem_`, `Page_TicketAttachmentRead_` (after
    P3c lands the `TicketAttachment` interface — wrapper pin is then
    available but per rule (tt) still redundant unless the watchers/
    attachments route gets a dedicated TS Page subclass like
    `TicketsPage`).
P3e. **SubtreeRow recursive parity.** Non-trivial parser work. Defer.

#### Bucket D — Any-tightening continued (option (d))

D2. **`Response.json(): Promise<any>` → `unknown` sweep on the
    frontend `api/` layer.** Targeted candidate route + runtime
    parser, not a blanket sweep. Bucket C C2 from v2.18 carry-
    forward. Pair with P3c (D2's UI-side cleanup is the natural
    consumer of P3c's pinned contract if an attachments UX lands).

#### Bucket H — Preventative-hygiene (LIKELY EMPTY for v2.24)

H1. **Re-audit grep for latent shadow-of-builtin sites.**
    `grep -rn 'def list\b\|async def list\b' app/services/` +
    analogous greps for `type`, `id`, `dict`, `set`. Run in
    v2.24-WP01 recon. If empty, drop bucket H for v2.24.

#### Bucket R — Cosmetic refactor (carry-forward from v2.19 → v2.20 → v2.21 → v2.22 → v2.23)

R1. **Extract shared `_OFFENDER_ALLOWLIST` helper module** across
    the 4 lints (bare-catch, ts-any, pragma, typecheck).
    Mechanical refactor.

#### Bucket A — Conditional v2.11 carry-forwards (act only on triggering need)

A1. C7 `decode_email_body` helper. A2. E3 KindPill 7th surface.
A3. E4 `useSearchV2` ergonomic follow-ups. A4. F3 TipTap second-
consumer extraction.

#### Bucket B — Conditional v2.13 carry-forwards

B1. Per-arm `refresh_total` opt-in syntax. B2. WP05 OpenAPI↔TS parser
expansion — partially landed via v2.13-WP05 generic envelope support
+ v2.23-WP02 +2 wrapper pins; remaining unpinned `Page<T>` entries
deferred per Bucket P above.

#### Bucket C — v2.18 surfaced candidates (conditional)

C1. Promote `EditSuggestionRead` / `AttachmentRead`. C2.
`Response.json(): Promise<any>` → `unknown` sweep (folds into D2
if option (d) lands). C3. `actor_type` enum-backed column migration.
C4. Context-snippet anchoring across lints.

### v2.24 prompt seed (paste-ready)

> Proceed with v2.24 of the problem-bulletin ticketing system.
> v2.23 retrospective + carry-forward backlog live at the bottom of
> `.claude/lessons-learned/ticketing-v2.23.md`. Baselines: backend
> **1452 P / 0 F / 6 skipped / 14 xfailed**, frontend **276 P / 0 F**,
> mypy **28 errors / 28 allow-list keys (0 LEGACY)**, WP05 parity
> PIN **11 parametrize entries** (5 PAGE + 1 UNION + 5 FLAT — the
> "5 FLAT" includes the v2.23-WP02 `AuditLogPage` addition; the
> total counting synthetic parser tests is 17 passed), WP11 parity
> PIN **15 routes**. **v2.23 was the hybrid (c)+(d) version — Page<T>
> envelope parity expansion +2 (both first-run-clean) + net-new
> typed TicketWatcherRead consumer + WP11 inner-pair pin (first-run-
> clean, no `any` to clear — prospective contract capture upstream
> of any UI integration per new rule (uu)).** v2.23 reached the same
> framework-residual floor as v2.21/v2.22 (28 keys, all upstream-
> blocked). Five shapes: **(a) PREVENTATIVE-HYGIENE — likely empty**
> (no new latent shadows; cheap re-audit grep in WP01); **(b)
> UPSTREAM-WAIT — legitimate "we are done here for now"**: declare
> 28 the floor, monitor framework releases; **(c) PARITY EXPANSION
> continued**: P3c TicketAttachmentRead typed consumer + WP11 pin
> (10 fields incl. file metadata; mirror of v2.23-WP03 on a richer
> schema), P3d wrapper-pin candidates (defer until TS counterparts
> exist), P3e SubtreeRow recursive (non-trivial parser work — skip
> unless parser extended); **(d) ANY-TIGHTENING continued**: D2
> `Response.json(): Promise<any>` → `unknown` sweep on the frontend
> `api/` layer (Bucket C C2 carry-forward from v2.18); **(e) DIRTY-
> TREE HOUSEKEEPING — legitimate v2.24-WP00 candidate**: ~390
> modified/untracked files at v2.23 open; WP03 swept `tickets.ts`
> in-line per new rule (vv), but the remainder
> (`.backups/`, `.claude/`, App.css, Kanban tsx, ProblemDetail
> tsx/css, vite.config.ts) is still dirty — a dedicated
> housekeeping commit reduces blast-radius noise for subsequent
> WPs. **Recommend (e) FIRST (v2.24-WP00 housekeeping) + (c)
> P3c TicketAttachmentRead as the working WP. (b) remains the
> still-valid stop position.** **Bucket H (likely empty):** H1
> re-audit grep across `app/services/`. **Bucket R (cosmetic
> carry-forward):** R1 extract shared `_OFFENDER_ALLOWLIST`
> helper module across 4 lints. **Bucket A** (C7, E3, E4, F3),
> **Bucket B** (B1, B2), **Bucket C** (C1, C2, C3, C4) remain
> conditional carry-forwards — act ONLY on triggering need.
> Follow the sequential subagent loop pattern, TDD-first, one
> diagnosis doc per WP under
> `.claude/lessons-learned/v2.24-wpNN-diagnosis.md`. Append lessons
> to `.claude/lessons-learned/ticketing-v2.24.md`.
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
> pass). **Forward rules carried from v2.22:** (qq) closure WP MUST
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
> conversation. **Forward rules new from v2.23:** (tt) parity-pin
> home selection: WP05 captures envelope shape (`Page<T>` / union /
> flat wrapper); WP11 captures inner-item field sets; for `Page[X]`-
> returning routes, the new signal lives in WP11 (inner item)
> unless WP05 hasn't pinned the wrapper shape yet for that route;
> refines rule (qq) — recon's pin-home recommendation is also a
> floor, verify at implementation time whether the recommended home
> adds new signal or merely duplicates an existing pin; (uu)
> net-new typed consumer is a valid v.NN deliverable even with no
> existing `any` to clear; pinning the contract before the UI
> consumer is built means the eventual UI integration cannot drift;
> value is prospective deterrent (catching backend renames between
> now and the UI integration) rather than retrospective; pair with
> rule (v) — authoring the typed consumer before the UI integration
> avoids the `any`-shaped trap appearing in the first place; (vv)
> pre-existing dirty-tree modifications may be swept into a WP
> commit when the WP must edit the same file; refines rule (ss) —
> detection still matters but mitigation may be in-WP (documented
> in commit message + diagnosis doc) rather than a separate
> housekeeping commit when file overlap is unavoidable; the
> separation has a cost (stash-pop or revert-reapply dance, both
> merge-error-prone), and bundling is acceptable if documented.
> Do NOT reintroduce the `_v1_deferred.py` skip-hook — per-test
> deferral uses plain pytest markers.

**Cumulative forward rules total: 48 (a-vv).** v2.23 added 3 new
rules (tt, uu, vv) to the 45 carried from v2.22.
