# v2.24 ticketing — lessons learned

Companion to `ticketing-v2.23.md`. v2.24 was the **hybrid (e)+(c)
version**: option (e) dirty-tree housekeeping executed first as a
split per-surface multi-commit sweep — 387 dirty files → 0 dirty,
**439 files tracked across 8 sub-commits** (a-gitignore, b-M/D,
c-docs, d-alembic, d-app, d-frontend, d-tests, d-docs), zero secrets,
zero deferrals — followed by option (c) parity expansion mirror of
v2.23-WP03 on a richer 10-field schema (`TicketAttachmentRead` typed
consumer + WP11 inner-pair pin, first-run-clean). v2.24 did **not**
introduce any new production logic; both functional WPs were
type-hygiene / contract-capture in shape. Closing state **28 PIN keys
/ 0 LEGACY** (unchanged), backend **1452 → 1453 P** (+1 parametrize
case from WP03), frontend **276 P** (untouched), mypy **28 errors /
14 files**. 4 WPs: recon, housekeeping (8 split commits), TicketAttachment
typed consumer + WP11 pin, closure.

**Closing baselines:** backend **1453 P / 0 F / 6 skipped / 14 xfailed**
(+1 over v2.23 close), frontend **276 P / 0 F** (untouched), mypy
**28 raw errors / 28 keys** (unchanged — at the framework-residual
floor). WP05 parametrize: **17** (unchanged from v2.23 close — no new
WP05 entries this version). WP11 parametrize: 15 → **16** (+1 from WP03).
`git status` clean (0 dirty after WP04 commit; was 387 at v2.24 open).

---

## v2.24-WP01 (G0) — recon

Backend **1452 P**, frontend **276 P**, mypy 28 errors / 14 files —
all match v2.23 close. Full attack-plan written to
`v2.24-wp01-diagnosis.md`.

**Key recon findings:**
- `git status --short | wc -l` = **387** vs v2.23-close cited "~390".
  Within rule (qq) tolerance. Composition: 117 M, 7 D, 263 ??.
- M-set is **incidental drift from prior WPs** (TicketStatus/Priority
  enum cascade, schema additions, route renames, frontend page
  refactors) — tests have been validating the *working tree*, not
  HEAD, across all of v2.1 → v2.23 close.
- D-set is 7 legacy `tests/services/test_ticket_*.py` files superseded
  by `tests/services/test_tickets_v2.py` (untracked replacement).
- ??-set is 263 files: 88 lessons-learned diagnosis docs spanning
  v2.1-v2.23, plus 173 real source/test/migration files + 2 noise
  paths.
- TicketAttachmentRead schema verified at
  `app/schemas/tickets.py:218-230` — exactly 10 fields, mirror of
  TicketWatcherRead's discriminator pattern
  (`uploaded_by_type: Literal["user", "agent"]` ≅ `watcher_type`).
- Shadow-of-builtin grep (`grep -rn 'def list\b\|async def list\b'
  app/services/`) returned **empty**. Confirms v2.23-seed prediction.
  Bucket H dropped for v2.24.

**WP ordering:** WP02 first (housekeeping — reduces blast-radius noise
for WP03); WP03 second (functional parity pin); WP04 closure.

---

## v2.24-WP02 — Dirty-tree housekeeping (8 split commits, 439 files)

**Outcome.** 387 dirty files (117 M + 7 D + 263 ??) → 0 dirty.
**8 commits**, **439 files tracked**, **0 secrets**, **0 deferrals**.
Backend / frontend / mypy baselines unchanged at every sub-commit
boundary. Recon estimate was 385 — actual 439 (+14%, rule (kk)
tolerance — recon under-counted co-located test files under
`frontend/src/**/__tests__/*` and top-level `tests/test_*.py`).

**Per-commit ledger:**

| Commit | SHA | Files | Surface |
|--------|------|-------|---------|
| WP02a | e027994 | 1 | `.gitignore` — `.backups/`, `.claude/scheduled_tasks.lock` |
| WP02b | 978b07b | 123 | tracked M (117) + tracked D (7) across surfaces |
| WP02c | ebc5f07 | 89 | `.claude/lessons-learned/*.md` (v2.1-v2.24 diagnosis docs) |
| WP02d-alembic | dc28ecf | 15 | `alembic/versions/a4-a20` migrations |
| WP02d-app | b04f2b6 | 32 | `app/` source (models, routes, schemas, services) |
| WP02d-frontend | 29cdbb7 | 81 | `frontend/src/` (api/, components/, pages/, etc.) |
| WP02d-tests | 1f9aca0 | 96 | `tests/` (unit/, helpers/, parity lints, etc.) |
| WP02d-docs | 144b67e | 2 | `docs/adr/*`, `docs/specs/*` |

**Rationale for split.** A single-commit 387-file sweep would have
been bisect-hostile — any future `git bisect` collision with v2.24-WP02
would dump the user into a 387-file unrelated diff. The per-surface
split means each commit can stand alone for revert/bisect at ~1–100
file granularity. Cost: 8 commits vs 1. Benefit: bisectability
preserved across the version-rollover housekeeping boundary.

**Secret audit.** Pre-commit grep over `git diff --cached --name-only`
for `\.env$|credential|secret|api[_-]?key|\.pem$|id_rsa` returned
empty across WP02b. Tracked `.env.example` is the published template
(no real secrets).

**Residual after WP02.** 28 keys (unchanged); WP05/WP11 parametrize
unchanged; backend 1452 P / frontend 276 P unchanged. The commit was
**pure tracking** — git's view changed, runtime didn't.

---

## v2.24-WP03 — TicketAttachmentRead typed consumer + WP11 inner-pair pin (+1)

**Outcome.** 2 files modified: `frontend/src/api/tickets.ts` (new
interface + helper) and `tests/test_openapi_ts_parity_wp11.py`
(+1 WP11_ROUTES tuple). Backend 1452 → **1453 P** (+1 parametrize
case). Frontend 276 P (preserved). Mypy untouched. **First-run-clean**
— zero drift, exact mirror of v2.23-WP03 precedent.

**TicketAttachment interface added (10 fields):**

```ts
export interface TicketAttachment {
  id: string;
  ticket_id: string;
  uploaded_by: string;
  uploaded_by_type: "user" | "agent";
  filename: string;
  content_type: string;
  byte_size: number;
  storage_path: string;
  agent_step_id: string | null;
  created_at: string;
}
export async function listTicketAttachments(
  idOrKey: string,
): Promise<Page<TicketAttachment>>;
```

`uploaded_by_type` discriminator mirrors WP47-WP49 / v2.23-WP03
pattern. No UI integration in this WP — pure prospective
contract-capture per rule (uu).

**WP11_ROUTES += 1 tuple:**

| Route | Backend schema | TS file | TS type |
|-------|----------------|---------|---------|
| GET /api/v1/tickets/{id_or_key}/attachments (items[*]) | `TicketAttachmentRead` | `tickets.ts` | `TicketAttachment` |

**Schema asymmetry surfaced.** `agent_step_id: str | None = None` in
Pydantic (NOT `UUID | None`) — TS-side `string | null` is correct
regardless. Recorded but not actioned (schema-side asymmetry is
outside parity-lint scope).

**tsc-noEmit baseline noise observed.** Pre-existing TS errors in
`frontend/src/pages/__tests__/*` were surfaced when WP03 ran
`npx tsc --noEmit` for sanity. Vitest scope is narrower; the
276-passing test count was unaffected. Flagged for v2.25 (see rule
(yy) and v2.25 seed below).

**Residual after WP03.** 28 keys (unchanged); WP11 PIN 15 → 16
parametrize entries (module total 19 incl. 3 parser self-tests).

---

## v2.24-WP04 (closure) — this document

Retrospective written. v2.25 paste-ready seed appended at bottom.
Zero production code touched in this WP.

**tsc-noEmit recon at closure time.** Per WP03 surprise flagging, ran
`cd frontend && npx tsc --noEmit 2>&1 | grep -c "error TS"` → **76
total errors**, with **23 errors localised in `pages/__tests__/*`**
(the remainder in `pages/*.tsx`, `pages/admin/*.tsx`, etc.). This is
genuine pre-existing baseline noise (unused `React` imports under the
new JSX runtime, missing `node:fs`/`node:path` types for the
catch-block lint test, missing es2022 `Array.prototype.at` lib,
`global` not declared in non-jest contexts). Recommend v2.25 (f) as
the primary candidate — see seed.

---

## v2.24 retrospective

### Headline numbers

- **Backend:** 1452 → **1453 P** / 0 F / 6 skipped / 14 xfailed
  (+1 from parametrize: WP03 +1; zero regressions).
- **Frontend:** 276 P / 0 F — untouched across all 4 WPs by test
  count. New `TicketAttachment` interface + helper added in WP03; no
  new vitest file (compile-time + parity-lint coverage suffices).
- **Mypy raw errors:** 28 → 28 (unchanged — framework-residual floor).
- **Mypy allow-list keys:** 28 → 28 (unchanged).
- **Classification:** **0 LEGACY throughout.**
- **WP05 parity PIN:** 17 → **17 parametrize entries** (unchanged).
- **WP11 parity PIN:** 15 → **16 parametrize entries** (+1; first-run-clean).
- **Net-new typed consumers introduced:** 1 (`TicketAttachment` +
  `listTicketAttachments`).
- **Latent shadow-of-builtin sites eliminated:** 0 (none surfaced).
- **Real bugs fixed:** 0 (all changes typing-hygiene / contract /
  tracking).
- **Files tracked into git via WP02:** **439** across 8 sub-commits
  (was 387 dirty pre-WP02; recon estimate 385; actual +14% over
  recon).
- **Production code touched (`app/`):** 0 files (WP02 tracked 32
  pre-existing files; no new edits).
- **Production code touched (`frontend/src/`):** 1 file
  (`frontend/src/api/tickets.ts` — WP03).
- **Test code touched:** 1 file (`tests/test_openapi_ts_parity_wp11.py` —
  WP03).
- **`.gitignore` modified:** 1 commit (WP02a, 2 path entries).
- **Production regressions introduced:** zero across all 8 WP02
  sub-commits and the WP03 functional commit.
- **Secrets committed:** zero.
- **Closing git status:** 0 dirty (was 387 at v2.24 open).

### WPs shipped

| WP | Bucket | Summary | PIN delta |
|----|--------|---------|----------:|
| WP01 | G0 | Recon. Confirmed v2.23 close baseline. Enumerated 387 dirty files (117 M + 7 D + 263 ??). Verified TicketAttachmentRead 10-field schema + WP05 vs WP11 home selection. Shadow-of-builtin grep empty. | ±0 |
| WP02 | E | Dirty-tree housekeeping. 8 split per-surface commits (a-gitignore, b-M/D, c-docs, d-alembic, d-app, d-frontend, d-tests, d-docs). 439 files tracked. 0 secrets. 0 deferrals. All sub-commit baselines green. | ±0 |
| WP03 | C | P3c TicketAttachmentRead typed-consumer introduction + WP11 inner-pair pin. Net-new TS interface (10 fields) + helper; mirror of v2.23-WP03 on richer schema. First-run-clean. | +1 WP11 route, ±0 mypy |
| WP04 | closure | Retrospective + v2.25 seed. tsc-noEmit baseline quantified (76 total / 23 in pages/__tests__). | ±0 |

### Cross-cutting lessons

1. **(ww) Dirty-tree housekeeping must split by surface for
   bisectability.** Single-commit ~400-file sweeps destroy `git bisect`
   — any later collision dumps the bisector into a high-cardinality
   unrelated diff. Per-surface sub-commits (a-gitignore, b-M/D,
   c-docs, then d-by-surface for source/tests/migrations) preserve
   bisectability at ~1–100 file granularity. The cost is ~8 commits;
   the benefit is each commit can stand alone for revert or bisect.
   Verify the baselines (pytest / vitest / mypy / parity-lint) at
   every sub-commit boundary so any single revert leaves the tree
   green. Refines rule (ss): the WP00-style "single housekeeping
   commit" prescription is a floor — when the housekeeping target
   exceeds ~50 files OR spans >3 distinct surfaces (e.g.
   `app/`, `frontend/src/`, `tests/`, `alembic/`, `docs/`,
   lessons-learned), split. Generalises to any cross-version
   leakage cleanup where the dirty set is heterogeneous.

2. **(xx) Net-new typed-consumer mirror commits are first-run-green
   when precedent is followed exactly.** Both v2.23-WP03
   (`TicketWatcher`, 5 fields) and v2.24-WP03 (`TicketAttachment`,
   10 fields) had zero drift on first run despite the 2× schema
   size increase. Refines rules (rr) and (uu): when WP_{n+1} is a
   structural mirror of WP_n (same pattern: typed interface +
   `list*` helper + WP11 inner-pair tuple), drift probability is
   near-zero IF the WP_n precedent is treated as the authoritative
   template — including discriminator-literal shape, header comment
   block format, parameter signature (no params arg when route
   ignores cursor/limit), and the `extra="allow"` permissive
   polarity on the Pydantic side. Generalises to any future "WP_n
   was a mirror of WP_{n-1}" sequence: copying the precedent
   *exactly* (down to comment block whitespace) outperforms
   "reimplementing from first principles".

3. **(yy) Pre-existing tsc-noEmit errors in tests are not blocked
   by vitest passing — frontend has two type channels.** vitest
   passes the 276 tests with its narrower type-check scope (it
   compiles tests through `esbuild`/`swc` with limited strict
   options); `npx tsc --noEmit` runs the full `tsconfig.json`
   strictness over the same files and produces a different result.
   v2.24-WP03 surfaced 76 tsc-noEmit errors (23 in
   `pages/__tests__/*`) that vitest had been silent about across
   v2.18-v2.23 close. **One channel can drift while the other
   holds.** Practical implication: vitest "276 P / 0 F" is a real
   PIN value for *runtime behaviour* but does NOT cover *type
   correctness* — those are separable axes. Promote `npx tsc
   --noEmit` to a tracked baseline in v2.25 if a tsc-cleanup WP
   lands; until then, flag as a separate backlog axis distinct
   from vitest pass count. Generalises: in any project where two
   tooling layers nominally cover the "same" type-check surface
   (e.g. esbuild vs tsc; rollup vs tsc; SWC vs tsc), at least one
   will silently drift unless explicitly pinned.

### What stayed deferred (carry to v2.25)

- **Preventative-hygiene (likely empty for v2.25):** no new shadow-
  of-builtin sites surfaced in v2.24 (no Python source edits in WP02
  beyond bulk-tracking; WP03 was frontend + parity-test only). Cheap
  re-audit grep still recommended at v2.25-WP01; expectation empty.

- **Parity expansion deferred:**
  - **`Page_AgentActivityItem_` wrapper pin** — defer until
    `audit.ts` upgrades from `ActivityEntry[]` to
    `Page<ActivityEntry>`.
  - **`CursorPage_ProblemResponse_`** — defer until problems API
    gains a hand-written TS Page wrapper.
  - **`Page_TicketAttachmentRead_` wrapper pin** — could be added
    for symmetry, but per rule (tt) is redundant (wrapper field set
    already covered 6× by existing PAGE_PAIRS).
  - **TicketWatcherRead + TicketAttachmentRead UI integration** —
    helpers exist (v2.23-WP03, v2.24-WP03); TicketDetail surface
    integration is a feature, out of scope for parity-lint WPs.

- **SubtreeRow recursive parity** — carry from v2.22. Non-trivial
  parser extension required.

- **Frontend tsc-noEmit cleanliness** — NEW from WP03 surprise.
  76 total / 23 in `pages/__tests__/*`. Real backlog axis distinct
  from vitest pass count per rule (yy). Triage candidates: unused
  `React` imports under new JSX runtime (~20 sites, mechanical),
  `node:fs`/`node:path` missing in browser-scoped tsconfig (1 file,
  add `@types/node` or split tsconfig), `Array.prototype.at` lib
  raise to es2022 (2 sites), `global` declaration in non-jest
  contexts (~7 sites, switch to `globalThis` or vitest-typed
  globals), `ProblemDetail.tsx:1052` `MouseEventHandler` mismatch
  (1 real type bug, needs wrapper).

- **Bucket A** (C7, E3, E4, F3) — still conditional v2.11
  carry-forwards.
- **Bucket B** (B1, B2) — still conditional v2.13 carry-forwards.
- **Bucket C** (C1, C2, C3, C4) — still conditional v2.18
  carry-forwards. C2 (`Response.json(): Promise<any>` → `unknown`
  sweep on `frontend/src/api/`) is the major next-step any-tightening
  axis — design WP territory.

- **Bucket R cosmetic** — `_OFFENDER_ALLOWLIST` helper extract
  (v2.19 rule (ee)) — carry from v2.19 → ... → v2.24.

- **28 BY-DESIGN typecheck residents — the genuine framework-
  residual floor.** Unchanged from v2.21/v2.22/v2.23 close. Per
  cluster: Starlette ASGI `Mount` callable variance (×1), FastAPI
  `add_exception_handler` callable variance (×1), SQLAlchemy
  `Result[Any].rowcount` boundary (×5), joined-load `attr-defined`
  (×~3), co-nullable FK arg-type pair (×2 at
  `services/tickets.py:1195-1196`), scattered single residuals.
  None reactively fixable without upstream Starlette / FastAPI /
  SQLAlchemy stub or plugin improvements. Re-evaluate every N
  versions per rule (kk).

### Files touched (rough stats — sum of WP02 + WP03)

- **Production code (`app/`):** 0 net new edits in v2.24 (WP02
  tracked 32 pre-existing files; WP03 untouched `app/`).
- **Production code (`frontend/src/`):** 1 file edited in WP03
  (`frontend/src/api/tickets.ts` — TicketAttachment interface +
  helper). 81 pre-existing `frontend/src/` files tracked in WP02d.
- **Alembic (`alembic/versions/`):** 15 pre-existing migrations
  tracked in WP02d-alembic; 0 net new edits.
- **Config:** 1 file edited (`.gitignore`, WP02a, +2 entries).
- **Lint allow-lists:** 0 files modified.
- **Test code (backend):** 1 file edited in WP03
  (`tests/test_openapi_ts_parity_wp11.py` — +1 entry). 96 pre-
  existing `tests/` files tracked in WP02d-tests.
- **Docs (`.claude/lessons-learned/`):** 89 prior docs tracked in
  WP02c + 3 per-WP diagnosis files for v2.24 (WP02, WP03, WP04) +
  this retrospective.

---

## v2.25 starting prompt seed

v2.24 closed as a **hybrid (e)+(c) version** — dirty-tree
housekeeping landed first (387 dirty → 0 dirty; 439 files tracked
across 8 split sub-commits; zero secrets; zero deferrals; backend /
frontend / mypy baselines unchanged at every sub-commit boundary) +
TicketAttachmentRead typed-consumer + WP11 pin landed second (mirror
of v2.23-WP03 on a 10-field schema, first-run-clean). Baselines:
backend **1453 P / 0 F / 6 skipped / 14 xfailed**, frontend **276 P /
0 F**, mypy **28 errors / 28 allow-list keys (0 LEGACY)**. v2.24
added 3 new forward rules: (ww) dirty-tree housekeeping must split
by surface for bisectability (refines rule (ss)), (xx) net-new
typed-consumer mirror commits are first-run-green when precedent is
followed exactly (refines (rr) and (uu)), (yy) pre-existing
tsc-noEmit errors are a separate backlog axis from vitest pass count
— two type channels can drift independently. Frontend tsc-noEmit
surveyed at WP04 closure: **76 total errors / 23 in
`pages/__tests__/*`**.

**v2.24 confirmed v2.23's predictions:** rule (qq) (closure re-counts
recon figures) caught the recon-vs-actual 387→388 status delta and
the 385→439 WP02 file-count delta. Rule (rr) held across the WP03
first-run-clean pin (deterrent value remains untested but consistent
with the rule). Rule (ss) was exercised at v2.24 scale (~400 files);
the new rule (ww) refines its mitigation. Rule (vv) was NOT
exercised in v2.24 (WP02 completed before WP03 touched any source;
no in-WP sweep needed).

Six shapes for v2.25:

- **(a) PREVENTATIVE-HYGIENE — likely empty.** No new latent
  shadow-of-builtin sites surfaced in v2.24. Cheap re-audit grep in
  v2.25-WP01; expectation empty. Drop bucket (a) if empty.
- **(b) UPSTREAM-WAIT — still legitimate "we are done here for now".**
  28-key floor unchanged across v2.21/v2.22/v2.23/v2.24. Monitor
  mypy / SQLAlchemy / Starlette / FastAPI releases. **Remains the
  honest stop position** if no other axis has triggering need.
- **(c) PARITY EXPANSION continued — likely empty.** The two "easy"
  net-new typed-consumer candidates (TicketWatcher, TicketAttachment)
  have both landed (v2.23-WP03, v2.24-WP03). Re-enumerating
  Page<T>-shaped OpenAPI schemas: `Page_AgentActivityItem_`,
  `CursorPage_ProblemResponse_`, `Page_TicketAttachmentRead_` (now
  the inner-item is pinned but the wrapper remains redundant per
  rule (tt)). All three require frontend-side TS upgrades before a
  parity pin makes sense. **Bucket (c) is empty unless one of those
  consumer upgrades is independently prioritised.**
- **(d) ANY-TIGHTENING.** Bucket C C2 from v2.18 seed —
  `Response.json(): Promise<any>` → `unknown` + runtime parser
  across `frontend/src/api/`. Major effort: ~20 helper functions
  return `Promise<T>` over `Response.json()`. Design WP territory
  (parser shape, error reporting, migration order). Significant
  but doable.
- **(f) TSC-NOEMIT CLEANUP — NEW from v2.24-WP03 surprise.** Quantified
  at WP04: **76 total tsc errors / 23 in `pages/__tests__/*`**.
  Categories: unused `React` imports under new JSX runtime
  (~20 mechanical sites), missing `node:fs`/`node:path` types
  (1 file, add `@types/node` or split tsconfig), `Array.prototype.at`
  lib version (2 sites, raise to es2022), `global` declaration in
  non-jest contexts (~7 sites, switch to `globalThis`),
  `ProblemDetail.tsx:1052` `MouseEventHandler` mismatch (1 real
  type bug). **Recommend ONE WP to triage + fix top-N (likely
  top-50 mechanical + the 1 real bug).**
- **Conditional carry-forwards:** Bucket A (C7, E3, E4, F3),
  Bucket B (B1, B2), Bucket C (C1, C3, C4), Bucket R (R1
  `_OFFENDER_ALLOWLIST` extract) — act ONLY on triggering need.

**Recommend (f) tsc-noEmit triage as primary** (concrete, quantified,
mechanical-heavy, one real type bug to fix) **+ (b) UPSTREAM-WAIT as
the legitimate stop position** for the typecheck axis. If (f)
resolves to <10 residual errors, v2.25 close could be the natural
"project-finished-typecheck-PIN" endpoint — at that point both
backend mypy (28 floor) and frontend tsc-noEmit (sub-10 residual)
are at upstream-blocked-or-trivially-acceptable floors.

### v2.25 backlog

#### Bucket F — TSC-noEmit cleanup (NEW, RECOMMENDED PRIMARY)

F1. **Triage `npx tsc --noEmit` baseline.** Quantified at v2.24-WP04
    as 76 total / 23 in `pages/__tests__/*`. Categories listed above.
    Target: <10 residual errors after one WP. Pair with adding tsc-
    noEmit as a tracked baseline alongside vitest 276 P. Per rule
    (yy), the two type channels are separable axes — pin both.

#### Bucket P — Adjacent PIN expansion continued (LIKELY EMPTY)

P3d. Wrapper-pin candidates (`Page_AgentActivityItem_`,
     `CursorPage_ProblemResponse_`, `Page_TicketAttachmentRead_`) —
     defer until corresponding TS counterparts upgrade. Per rule
     (tt) still redundant unless the wrapper field set diverges from
     the generic `Page<T>` declaration.
P3e. **SubtreeRow recursive parity.** Non-trivial parser work. Defer.

#### Bucket D — Any-tightening (option (d), major effort)

D2. **`Response.json(): Promise<any>` → `unknown` sweep on
    `frontend/src/api/`.** Bucket C C2 from v2.18 carry-forward.
    ~20 helpers; design WP needed (runtime parser shape, error
    reporting, migration order). Pair with (f) if the frontend
    type-tightening lands as a multi-WP arc.

#### Bucket H — Preventative-hygiene (LIKELY EMPTY for v2.25)

H1. **Re-audit grep for latent shadow-of-builtin sites.** Run in
    v2.25-WP01 recon. If empty, drop bucket H.

#### Bucket R — Cosmetic refactor (carry-forward from v2.19 → ... → v2.24)

R1. **Extract shared `_OFFENDER_ALLOWLIST` helper module** across
    the 4 lints (bare-catch, ts-any, pragma, typecheck). Mechanical.

#### Bucket A — Conditional v2.11 carry-forwards (act only on triggering need)

A1. C7 `decode_email_body` helper. A2. E3 KindPill 7th surface.
A3. E4 `useSearchV2` ergonomic follow-ups. A4. F3 TipTap second-
consumer extraction.

#### Bucket B — Conditional v2.13 carry-forwards

B1. Per-arm `refresh_total` opt-in syntax. B2. WP05 OpenAPI↔TS parser
expansion — partially landed via v2.13-WP05 + v2.23-WP02; remaining
deferred per Bucket P above.

#### Bucket C — v2.18 surfaced candidates (conditional)

C1. Promote `EditSuggestionRead` / `AttachmentRead`. C2. folds into
D2. C3. `actor_type` enum-backed column migration. C4. Context-
snippet anchoring across lints.

### v2.25 prompt seed (paste-ready)

> Proceed with v2.25 of the problem-bulletin ticketing system.
> v2.24 retrospective + carry-forward backlog live at the bottom of
> `.claude/lessons-learned/ticketing-v2.24.md`. Baselines: backend
> **1453 P / 0 F / 6 skipped / 14 xfailed**, frontend **276 P / 0 F**,
> mypy **28 errors / 28 allow-list keys (0 LEGACY)**, WP05 parity
> PIN **17 parametrize entries**, WP11 parity PIN **16 routes**,
> **frontend `npx tsc --noEmit`: 76 errors / 23 in
> `pages/__tests__/*`** (new tracked baseline). **v2.24 was the
> hybrid (e)+(c) version — dirty-tree housekeeping first (387 dirty
> → 0 dirty; 439 files tracked across 8 split per-surface sub-commits;
> 0 secrets; 0 deferrals) + TicketAttachmentRead typed consumer +
> WP11 inner-pair pin (10 fields; mirror of v2.23-WP03 on richer
> schema; first-run-clean).** v2.24 reached the same framework-
> residual floor as v2.21/v2.22/v2.23 (28 keys, all upstream-blocked)
> and additionally surfaced a NEW backlog axis: frontend tsc-noEmit
> cleanliness, distinct from vitest pass count per new rule (yy).
> Six shapes: **(a) PREVENTATIVE-HYGIENE — likely empty** (drop if
> WP01 grep empty); **(b) UPSTREAM-WAIT — legitimate "we are done
> here for now"** for the mypy axis; **(c) PARITY EXPANSION
> continued — likely empty** (the two "easy" net-new candidates
> have landed; remaining wrapper pins are redundant per rule (tt)
> until their TS counterparts upgrade independently); **(d) ANY-
> TIGHTENING — major effort**: D2 `Response.json(): Promise<any>` →
> `unknown` sweep on `frontend/src/api/` (~20 helpers, design WP
> needed); **(f) TSC-NOEMIT CLEANUP — NEW, RECOMMENDED PRIMARY**:
> F1 triage `npx tsc --noEmit` baseline (76 → target <10), categories
> are unused-React-imports / missing-`@types/node` / `global` →
> `globalThis` / es2022 `Array.prototype.at` lib raise / 1 real
> `MouseEventHandler` type bug at `ProblemDetail.tsx:1052`. **Recommend
> (f) PRIMARY + (b) UPSTREAM-WAIT as the honest stop for the mypy
> axis. If (f) resolves to <10 residual, v2.25 may be the natural
> project-finished-typecheck-PIN endpoint across both Python and TS
> sides.** **Bucket H (likely empty):** H1 re-audit grep across
> `app/services/`. **Bucket R (cosmetic carry-forward):** R1 extract
> shared `_OFFENDER_ALLOWLIST` helper. **Bucket A** (C7, E3, E4, F3),
> **Bucket B** (B1, B2), **Bucket C** (C1, C3, C4) remain conditional
> carry-forwards — act ONLY on triggering need. Follow the sequential
> subagent loop pattern, TDD-first, one diagnosis doc per WP under
> `.claude/lessons-learned/v2.25-wpNN-diagnosis.md`. Append lessons
> to `.claude/lessons-learned/ticketing-v2.25.md`.
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
> conversation. **Forward rules carried from v2.23:** (tt) parity-pin
> home selection: WP05 captures envelope shape (`Page<T>` / union /
> flat wrapper); WP11 captures inner-item field sets; for `Page[X]`-
> returning routes, the new signal lives in WP11 (inner item)
> unless WP05 hasn't pinned the wrapper shape yet for that route;
> refines rule (qq); (uu) net-new typed consumer is a valid v.NN
> deliverable even with no existing `any` to clear; pinning the
> contract before the UI consumer is built means the eventual UI
> integration cannot drift; value is prospective deterrent (catching
> backend renames between now and the UI integration) rather than
> retrospective; pair with rule (v); (vv) pre-existing dirty-tree
> modifications may be swept into a WP commit when the WP must edit
> the same file; refines rule (ss); the separation has a cost
> (stash-pop or revert-reapply dance, both merge-error-prone), and
> bundling is acceptable if documented. **Forward rules new from
> v2.24:** (ww) dirty-tree housekeeping must split by surface for
> bisectability; single-commit ~400-file sweeps destroy `git bisect`
> — any later collision dumps the bisector into a high-cardinality
> unrelated diff; per-surface sub-commits (a-gitignore, b-M/D,
> c-docs, then d-by-surface for source/tests/migrations) preserve
> bisectability at ~1–100 file granularity; cost ~8 commits,
> benefit each commit can stand alone for revert/bisect; verify
> baselines at every sub-commit boundary so any single revert
> leaves the tree green; refines rule (ss) — the WP00-style
> "single housekeeping commit" prescription is a floor, split when
> dirty set exceeds ~50 files OR spans >3 surfaces; (xx) net-new
> typed-consumer mirror commits are first-run-green when precedent
> is followed exactly; refines rules (rr) and (uu) — when WP_{n+1}
> is a structural mirror of WP_n (same pattern: typed interface +
> `list*` helper + WP11 inner-pair tuple), drift probability is
> near-zero IF the WP_n precedent is treated as the authoritative
> template (down to comment block whitespace, parameter signature,
> `extra="allow"` polarity); copying the precedent exactly
> outperforms reimplementing from first principles; (yy)
> pre-existing tsc-noEmit errors in tests are not blocked by vitest
> passing — frontend has two type channels (vitest's narrower
> esbuild/swc-driven type check vs the full `tsc --noEmit` strict
> check), and one can drift while the other holds; vitest "276 P"
> is a real PIN for runtime behaviour but does NOT cover type
> correctness — those are separable axes; in any project where two
> tooling layers nominally cover the "same" type-check surface, at
> least one will silently drift unless explicitly pinned.
> Do NOT reintroduce the `_v1_deferred.py` skip-hook — per-test
> deferral uses plain pytest markers.

**Cumulative forward rules total: 51 (a-yy).** v2.24 added 3 new
rules (ww, xx, yy) to the 48 carried from v2.23.
