# v2.27 ticketing — lessons learned

Companion to `ticketing-v2.26.md`. v2.27 was the **Option (d') C2
GUARDS — runtime guards at audit + users `parseJson<T>` sites +
`UpdateHandleResponse` drift fix** version (the future-teeth slot
that v2.26-WP02's seam reserved per rule eee). WP01 recon enumerated
the 11 `parseJson<T>` callers seam-wide, bucketed them i (typed-
generic helpers — safe) / ii (direct sites with worthwhile guard ROI)
/ iii (unknown-by-design), shortlisted `audit.ts` + `users.ts`, and
confirmed via a UI-fallback decision matrix that BOTH shortlisted
sites had safe rejection paths already in place. The latent drift
surprise: backend `UserHandleResponse.handle: str | None` vs. TS
`UpdateHandleResponse.handle: string` — invisible to tsc/vitest
because the response is consumed only as a discarded await at
`Settings.tsx:366`. WP02 shipped hand-written predicates
(`isActivityEntry`, `isActivityPage` accepting `{items}` OR bare
array; `isUpdateHandleResponse`), wired them into the seam's second
arg, fixed the drift IN THE SAME COMMIT (`UpdateHandleResponse.handle:
string | null`), and added 25 new vitest cases across two new test
files. **WP03 was closure-only** per scope discipline — the
generated-guard tooling conversation (~10+ sites needed before
codegen pays off) is a v2.28 candidate, not a v2.27 expansion.

**Closing baselines:** backend **1459 P / 0 F / 7 skipped / 14
xfailed** (unchanged from v2.26 close — zero functional regressions,
zero backend touches), frontend **301 P / 0 F** (276 → 301, +25 from
two new guard test files), mypy **28 raw errors / 28 keys**
(unchanged — framework-residual floor), **`npx tsc --noEmit`: 0
errors** (PIN floor at `tests/test_frontend_tsc_lint_v225.py` held
across drift fix + guard adoption). WP05 parametrize: **17**
(unchanged). WP11 parametrize: **16** (unchanged). `git status`
clean (0 dirty post-WP03 commit).

**Commits:**
- WP01 — recon only, no commit
- WP02 — `4400063`
- WP03 — this closure; SHA folded post-amend per v2.26 pattern

---

## v2.27-WP01 — recon

Backend **1459 P**, frontend **276 P**, mypy 28 errors / 14 files,
tsc-noEmit 0 errors — all match v2.26 close. 11 `parseJson<T>`
callers enumerated across `frontend/src/api/`. Bucketing:

- **i — typed-generic helper sites (6):** sprints, people, tickets,
  notifications, projects, auditLog. Each goes through `request<T>`
  with a function generic; guard adoption requires a per-route
  predicate, which is push-down out of the seam helper layer. Out of
  scope for v2.27 — would balloon the WP.
- **ii — direct sites with worthwhile guard ROI (2 shortlisted):**
  `audit.ts` (activity feed: `{items: ActivityEntry[]} | null` OR
  bare-array fallback per legacy server behaviour) and `users.ts`
  (handle update response: `{handle, next_allowed_at}`). Both have
  small concrete shapes and live behind a UI surface where the user
  notices breakage.
- **iii — unknown-by-design / skip:** `users.ts:59` error-body parse
  (response shape is server-error envelope; we already destructure
  defensively), `search.ts` (already PIN-protected by WP11 parity —
  shape covered by the seam contract, no second guard pays off).

Design choice: **Option I — hand-written predicates** (over Option II
generic shape-helper, over Option III zod). Two sites doesn't justify
either a library import or a shape-helper abstraction. Decision was
revisited in WP02 and held.

**Latent drift surfaced in WP01:** backend `UserHandleResponse.handle:
str | None` (post v2.23 anon-user nullability work) vs. TS
`UpdateHandleResponse.handle: string`. The TS interface was
hand-maintained, never re-derived from the backend Pydantic schema,
and the response is only consumed as a discarded await at
`Settings.tsx:366` — so neither tsc nor vitest had a tooth to catch
the drift. Promoted to rule (fff) below.

**UI-fallback decision matrix (WP01 deliverable):**

| Site | What does user see if guard rejects? | Safe? |
|------|--------------------------------------|-------|
| `audit.ts` (activity feed) | Existing catch path renders "No recent activity." empty state | YES |
| `users.ts` (handle update) | Existing `catch` block at Settings.tsx renders "Failed to update handle." banner | YES |

Both safe — green-light to ship guards in WP02. Promoted to rule
(ggg) below.

No source edits in WP01.

---

## v2.27-WP02 — sweep, `4400063`

**Outcome.** 2 new test files, 2 source files touched, **+25 vitest
tests** (276 → 301), **tsc still 0**, mypy unchanged at 28, backend
1459 unchanged. Drift fix landed in the same commit as the guard
adoption — not split.

**Files touched:**

| File | Role | Notes |
|------|------|-------|
| `frontend/src/api/audit.ts` | Guard adoption | `isActivityEntry` + `isActivityPage` (accepts `{items}` OR bare array — preserves legacy server-shape tolerance); wired as `parseJson<T>(res, isActivityPage)` |
| `frontend/src/api/users.ts` | Drift fix + guard adoption | `UpdateHandleResponse.handle: string` → `string \| null`; `isUpdateHandleResponse` predicate; wired into seam |
| `frontend/src/api/__tests__/auditGuards.test.ts` | NEW (14 tests) | accept-shape coverage (object + bare array), reject-shape coverage (nulls, missing fields, wrong types) |
| `frontend/src/api/__tests__/userGuards.test.ts` | NEW (11 tests) | accept-shape (handle string + null), reject-shape (missing next_allowed_at, wrong types) |

**Drift fix consumer audit (zero breakage):** `UpdateHandleResponse`
is locally scoped to `users.ts`. The single consumer at
`Settings.tsx:366` discards the return value (`await updateHandle(...)`
not bound). The independent `user.handle` reads at `Settings.tsx:331`
and `Settings.tsx:429` go through an unrelated
`(user as unknown as { handle?: string })` cast, so they were already
null-tolerant. **Zero source-side adjustments outside `users.ts`.**

**Surprises:**
1. **Drift was real, latent, and invisible.** Rule (fff) below.
   Re-deriving from the Pydantic schema at WP01 caught it cheaply;
   re-deriving from the TS would have re-encoded the wrong shape into
   the predicate.
2. **`isActivityPage` dual-shape predicate.** Server returns
   `{items: [...]}` on the modern endpoint but legacy callers
   tolerated a bare array — the existing TS code branched on
   `body?.items`. The predicate accepts BOTH and unwraps to
   `ActivityEntry[]` at the seam. Worth flagging because if a 3rd
   guard with a similar dual-shape requirement appears in v2.28, the
   pattern is liftable to a `oneOfShape<A,B>` helper. Not promoted to
   a rule — single occurrence is too thin.
3. **No call site needed UI changes.** WP01's matrix correctly
   predicted both surfaces. No fallback wiring added beyond what
   existed.

**Residual after WP02.** 0 (no further guard sites in scope). vitest
276 → 301 (+25); tsc 0 unchanged; mypy 28 unchanged; backend 1459
unchanged.

---

## v2.27-WP03 (closure) — this document

Retrospective written. v2.28 paste-ready seed appended at bottom.
Zero production code touched in this WP.

---

## v2.27 retrospective

### Headline numbers

- **Backend:** 1459 → **1459 P** / 0 F / 7 skipped / 14 xfailed
  (unchanged — zero backend touches).
- **Frontend (vitest):** 276 → **301 P** / 0 F (+25 from two new
  guard test files).
- **Frontend (tsc-noEmit):** 0 → **0 errors** (PIN held across drift
  fix + guard adoption).
- **Mypy raw errors:** 28 → 28 (unchanged — framework-residual
  floor).
- **Mypy allow-list keys:** 28 → 28 (unchanged).
- **Classification:** **0 LEGACY throughout.**
- **WP05 parity PIN:** 17 → **17** (unchanged).
- **WP11 parity PIN:** 16 → **16** (unchanged).
- **Net-new typed consumers introduced:** 0 (predicates are guards
  on existing seams, not new consumer chains).
- **Latent shadow-of-builtin sites eliminated:** 0.
- **Real bugs fixed:** 1 (latent — `UpdateHandleResponse.handle`
  drift; no observed runtime impact because the only consumer
  discards the return, but the type lie was real and would have
  bitten any future consumer).
- **Production code touched (`app/`):** 0 files (backend untouched).
- **Production code touched (`frontend/src/`):** 2 files
  (`audit.ts`, `users.ts`), both under `frontend/src/api/`.
- **Config touched:** 0 files.
- **Test code touched:** 2 NEW files
  (`__tests__/auditGuards.test.ts`, `__tests__/userGuards.test.ts`).
- **Production regressions introduced:** zero.
- **Secrets committed:** zero.
- **Closing git status:** 0 dirty (post-WP03 commit).

### WPs shipped

| WP | Bucket | Summary | PIN delta |
|----|--------|---------|----------:|
| WP01 | C C2 GUARDS (d') | Recon. Enumerated 11 `parseJson<T>` callers, bucketed i/ii/iii. Shortlist: `audit.ts` + `users.ts`. UI-fallback matrix confirmed safe under guard rejection. Picked Option I (hand-written predicates). Surfaced latent `UpdateHandleResponse.handle` drift. No source edits. | ±0 |
| WP02 | C C2 GUARDS (d') | Ship 2 predicates + 2 guard wirings + drift fix in single commit. New test files: `auditGuards.test.ts` (14), `userGuards.test.ts` (11). Vitest 276 → 301. Zero drift-fix consumer breakage. | +25 vitest |
| WP03 | closure | Retrospective + v2.28 seed. All 4 channels remain at PIN-protected floor. | ±0 |

### What didn't ship

- **`users.ts:59` error-body parse guard.** Unknown-by-design — the
  response is a server-error envelope, low ROI for a runtime guard
  (we already destructure defensively at the call site).
- **`search.ts` concrete guard.** Already PIN-protected by WP11
  parity; the seam contract covers the shape. A second guard layer
  would be redundant.
- **Bucket i / generic-helper guards (6 sites).** Guards at the
  `request<T>` helper layer can't work — the helper has no per-route
  predicate handle. Push-down to each consumer = WP scope creep
  (~6× the v2.27 WP02 size). Deferred indefinitely; revisit only if
  a specific route surfaces drift in telemetry.
- **Generated-guard tooling (e.g. `openapi-typescript` runtime mode,
  hand-rolled emit from OpenAPI spec).** Hand-written predicates
  don't scale — 2 sites at ~12 LOC predicate + ~30 LOC test ≈ 80
  LOC. At ≥10 sites, codegen pays off; at 2, it's premature.
  Deferred to v2.28 candidate (d'') below as the sole structurally-
  interesting alternate.
- **Option (b) UPSTREAM-WAIT.** v2.26 closure flagged it as the
  honest baseline; user explicitly chose to execute (d') C2 GUARDS.
  Recommendation stands even stronger now (see v2.28 seed below).

### Cross-cutting lessons — NEW forward rules

2 new rules promoted from v2.27 (rules **fff, ggg**), built on the
57 carried from v2.26 (a-eee). **Cumulative: 59 (a-ggg).**

**(fff) When adding a runtime guard to a `parseJson<T>` site,
re-derive the TS interface from the backend Pydantic schema, not
from the existing TS.** v2.27-WP02 surfaced that
`UpdateHandleResponse.handle` had been TS-typed as `string` while
backend `UserHandleResponse.handle: str | None` (post v2.23 anon-user
nullability work). The drift was invisible to tsc/vitest because the
response is only consumed as a discarded await in `Settings.tsx:366`.
A guard authored from the TS would have re-encoded the wrong shape
— `isUpdateHandleResponse` would have rejected legitimate null-handle
responses, the seam would have thrown on them, and the "Failed to
update handle." UI banner would have fired falsely. **Why:** the
backend schema is the source of truth; the TS interface is a
hand-maintained projection that can drift silently when there's no
type-aware consumer to catch the lie. Guard adoption is the *only*
moment where the projection gets re-examined under runtime semantics,
so it's also the cheapest moment to catch drift. **How to apply:**
when scoping a (d')-style guard WP, the first WP01 task per site is
"grep the backend Pydantic model (`app/schemas/`), diff against the
TS interface, flag any drift." Drift fixes are part of the same
commit as the guard adoption — they're not a separate refactor. The
guard adoption commit is the natural home for them because the guard
encodes the corrected shape and the predicate's reject-branch test
covers the corrected nullability. Generalises to any tightening-pass
that crosses a language boundary: GraphQL codegen catches this for
free, hand-maintained TS doesn't, and the guard adoption WP is the
forcing function.

**(ggg) Guard adoption WPs should include a UI-fallback decision
matrix before code lands.** Rule (eee) lets a structural seam ship
without runtime teeth — that's fine, the rejection branch is dead
code at seam-landing time. The moment you add teeth, every rejected
response becomes a thrown error reaching the UI. A guard with teeth
that bricks the page on rejection is strictly worse than no guard
(the un-guarded path at least returns *something* the UI knew how to
discard or fall through). v2.27-WP01 deliverable matrix:

| Site | What does user see if guard rejects? |
|------|--------------------------------------|
| `audit.ts` | "No recent activity." empty state (existing catch path) |
| `users.ts` | "Failed to update handle." banner (existing catch block) |

Both safe → ship in WP02. If either had been "blank screen / uncaught
exception", that site moves to a follow-up WP with paired UI work; do
not ship a guard that bricks the page. **Why:** schema discipline and
UI fallback design are two different design problems. The guard is
the seam between them. Skipping the UI side because "the catch block
already exists" is a one-line audit that takes 60 seconds and prevents
a class of regression where the rejection branch crashes a surface
nobody tested under failure. **How to apply:** any future C2-style
guard WP01 ships with a 2-column table per shortlisted site —
{site, user-visible behaviour on guard rejection}. Sites whose answer
is "uncaught exception / blank screen / wedged state" do NOT ship a
guard in the current WP; they get a paired-UI-work follow-up. Pair
with (eee): seam-without-teeth lands freely; teeth-without-fallback
does not. Generalises to any validator adoption: gRPC client guards,
zod schema rollouts, runtime API contract enforcement — the question
"what does the user see when the contract is violated" is part of the
adoption WP, not a separate concern.

### What stayed deferred (carry to v2.28)

- **Preventative-hygiene (likely empty for v2.28):** no new shadow-
  of-builtin sites surfaced in v2.27. v2.27 was all
  `frontend/src/api/` work; the `app/services/` Python surface
  wasn't touched. Re-audit grep recommended at v2.28-WP01 if it
  runs; expectation empty.

- **Parity expansion (still likely empty for v2.28):** the 3
  unpinned `Page<T>` wrappers still require their TS counterparts to
  upgrade independently and remain redundant per rule (tt). v2.27
  didn't surface new candidates.

- **SubtreeRow recursive parity** — carry from v2.22. Non-trivial
  parser extension required.

- **Bucket C C2 GUARDS continued — marginal remaining sites.** The
  6 bucket-i `request<T>` helpers need per-route predicates that
  require push-down out of the helper layer. Not worth a v2.28 WP
  unless a specific route surfaces drift in telemetry. The
  `users.ts:59` error-body site remains unknown-by-design.

- **(d'') GENERATED GUARDS — NEW candidate for v2.28.** Hand-written
  predicates don't scale (rule reasoning above). OpenAPI-driven
  codegen (e.g., `openapi-typescript` runtime mode, or hand-rolled
  emit from the FastAPI-generated spec) would let bucket-i sites
  adopt guards mechanically. Non-trivial design WP: build-pipeline
  integration, drift-test that compares emitted predicates to a
  golden, decision on whether to emit at lint-time or commit emitted
  output. **Premature without a forcing function** — recommend
  deferring until ≥1 more site shows drift in production telemetry
  or until ≥5 bucket-i guards become independently justified.

- **Bucket A** (C7, E3, E4, F3) — still conditional v2.11
  carry-forwards.
- **Bucket B** (B1, B2) — still conditional v2.13 carry-forwards.
- **Bucket C** (C1, C3, C4) — still conditional v2.18 carry-forwards.

- **Bucket R cosmetic** — `_OFFENDER_ALLOWLIST` helper extract
  (v2.19 rule (ee)) — carry from v2.19 → ... → v2.27. Still 5
  subprocess-shelling lints in the family; v2.27 added no new lints
  to the family.

- **28 BY-DESIGN typecheck residents — the genuine framework-
  residual floor.** Unchanged from v2.21-v2.26 close. Re-evaluate
  every N versions per rule (kk).

### Notes — judgment calls worth recording

- **Drift fix in the same commit as the guard adoption.** The WP02
  agent (correctly) did NOT split the `UpdateHandleResponse.handle`
  fix into a separate refactor commit. Reasoning: the guard encodes
  the corrected shape, the predicate reject-branch test covers the
  corrected nullability, and the consumer audit was a 3-site grep —
  the smallest reviewable unit is "guard adoption + the drift it
  surfaced". Promoted as rule (fff). The alternative — split into
  drift-fix-then-guard — would have created a transient commit where
  the TS interface said `string | null` but no consumer had been
  updated to expect null. Reviewable on its own, but lower
  signal-to-noise.
- **Hand-written predicates over codegen.** At 2 sites, the math
  doesn't justify codegen tooling. Picking Option I in WP01 and
  holding through WP02 was correct scope discipline. The codegen
  conversation is real (rule reasoning above) but premature.
- **Rule numbering correction.** WP02 agent's diagnosis attempted to
  name the drift-discipline rule "(zz)", which is an established v2.21
  rule about type-bug-fix sweeps. Catalogue position at v2.26 close
  was (eee) at 57 rules; next IDs are (fff), (ggg). Corrected in this
  closure doc. Mentioned because the off-by-many-letters slip is the
  kind of thing that compounds if not caught at closure time.
- **No backend touches.** Drift was a TS-side type lie; the backend
  was correct. Pure frontend WP. v2.27 maintains the pattern of
  v2.26 (frontend-only work) — both versions, taken together, closed
  out the `frontend/src/api/` shape-tightening surface.

### Files touched (rough stats — sum of WP01 + WP02 + WP03)

- **Production code (`app/`):** 0 files (backend untouched).
- **Production code (`frontend/src/`):** 2 files, both under
  `frontend/src/api/`:
  - `audit.ts` — `isActivityEntry`, `isActivityPage`, guard wiring.
  - `users.ts` — drift fix (`handle: string | null`),
    `isUpdateHandleResponse`, guard wiring.
- **Config:** 0 files.
- **Lint allow-lists:** 0 files (rule ccc not triggered).
- **Test code (backend, new):** 0 files.
- **Test code (frontend, new):** 2 files:
  - `frontend/src/api/__tests__/auditGuards.test.ts` (14 tests).
  - `frontend/src/api/__tests__/userGuards.test.ts` (11 tests).
- **Docs (`.claude/lessons-learned/`):** WP01 + WP02 diagnosis files
  + this retrospective.

---

## v2.28 starting prompt seed

v2.27 closed as the **Option (d') C2 GUARDS** version. WP01
enumerated 11 `parseJson<T>` callers, shortlisted `audit.ts` +
`users.ts` (bucket ii), confirmed UI-fallback safety per site via a
2-column decision matrix, and surfaced a latent
`UpdateHandleResponse.handle` drift (backend `str | None` vs. TS
`string`). WP02 shipped hand-written predicates + drift fix + 25
vitest cases in a single commit (`4400063`). Closing baselines:
backend **1459 P / 0 F / 7 skipped / 14 xfailed**, frontend
**301 P / 0 F**, mypy **28 errors / 28 keys (0 LEGACY)**, **`npx tsc
--noEmit`: 0 errors** (PIN held across drift fix + guard adoption).
v2.27 added 2 new forward rules: (fff) re-derive TS interfaces from
backend Pydantic schemas when adopting guards — drift fixes belong in
the same commit; (ggg) guard adoption WPs require a UI-fallback
decision matrix before code lands. **Cumulative forward rules total:
59 (a-ggg).**

### Status framing

**v2.27 closed the last named substantive WP from v2.25's seed.** All
four channels at PIN floor. (b) UPSTREAM-WAIT was already the honest
baseline at v2.26 close and remains so. v2.28 has no obvious
must-ship. The sole structurally-interesting alternate is **(d'')
GENERATED GUARDS** — OpenAPI-driven codegen so future guard sites
adopt mechanically — but it's premature without a forcing function
(≥1 more drift in production telemetry, or ≥5 bucket-i guards
becoming independently justified). Hand-rolling a third predicate
would be busywork.

### Shapes for v2.28

- **(a) PREVENTATIVE-HYGIENE — empty.** v2.27 was all
  `frontend/src/api/` work; no new shadow-of-builtin sites surfaced.
  Drop bucket (a) if WP01 grep empty.
- **(b) UPSTREAM-WAIT — STRONGLY RECOMMENDED, primary.** v2.27
  closed the last named substantive WP from v2.25's seed. Monitor
  mypy / SQLAlchemy / Starlette / FastAPI / DOM-lib releases. **This
  is the honest stop position. v2.27 is a clean stopping point.**
- **(c) PARITY EXPANSION — marginal candidates only.** WP01 re-scan
  in v2.26 found `TicketRead` + maybe `LinkRead` as marginal
  candidates (GET-side reads of already-pinned write routes). Low
  value. Likely empty unless a consumer upgrade is independently
  prioritised.
- **(d'') GENERATED GUARDS — net-new candidate substantive WP for
  v2.28.** Hand-written predicates don't scale (v2.27 shipped 2 at
  ~80 LOC total; bucket-i has 6+ sites). Options: (1)
  `openapi-typescript` in runtime mode + type-guards, (2) hand-rolled
  emit from the FastAPI-generated `/openapi.json`, (3) zod-from-
  openapi codegen. Non-trivial design WP: build-pipeline integration,
  drift-test that the emitted predicates match a golden, decision on
  emit-time (lint vs. commit). **Premature without a forcing
  function.** Recommend deferring until ≥1 more site shows drift in
  production telemetry or until ≥5 bucket-i guards become
  independently justified.
- **(e) DIRTY-TREE HOUSEKEEPING — should be empty.** v2.27 closed
  clean. Verify `git status --short | wc -l` = 0 in WP01.
- **(g) non-typecheck PIN sweeps — re-audit on triggering need
  only.** Most reached "all BY-DESIGN" in v2.22 recon. Carry forward
  unchanged.

**Conditional carry-forwards (unchanged from v2.26):** Bucket A (C7,
E3, E4, F3), Bucket B (B1, B2), Bucket C (C1, C3, C4 — note C2 is
now substantively closed; only bucket-i `request<T>` helper guards
remain, deferred to (d'') generated-guards if pursued), Bucket R (R1
`_OFFENDER_ALLOWLIST` extract — still 5 subprocess-shelling lints).
Act ONLY on triggering need.

**Recommend (b) UPSTREAM-WAIT as primary. v2.27 is a clean stopping
point. (d'') GENERATED GUARDS is the ONLY structurally-interesting
alternate but premature without a forcing function; everything else
is prophylactic or upstream-blocked.**

### v2.28 prompt seed (paste-ready)

> Proceed with v2.28 of the problem-bulletin ticketing system —
> **OR consider declaring v2.27 the natural project-finished endpoint
> and stopping.** v2.27 retrospective + carry-forward backlog live at
> the bottom of `.claude/lessons-learned/ticketing-v2.27.md`.
> Baselines: backend **1459 P / 0 F / 7 skipped / 14 xfailed**,
> frontend **301 P / 0 F**, mypy **28 errors / 28 allow-list keys
> (0 LEGACY)**, frontend `npx tsc --noEmit`: **0 errors (PIN at
> `tests/test_frontend_tsc_lint_v225.py`)**, WP05 parity PIN **17
> parametrize entries**, WP11 parity PIN **16 routes**. **v2.27 was
> the (d') C2 GUARDS version executed end-to-end — 2 hand-written
> predicates at `audit.ts` + `users.ts` wired into the seam, +25
> vitest cases, plus a same-commit fix of a latent
> `UpdateHandleResponse.handle` drift (`string` → `string | null`)
> that had been invisible to tsc/vitest because the consumer
> discarded the await.** **All four channels remain at PIN-protected
> floor.**
> Shapes: **(a) PREVENTATIVE-HYGIENE — empty** (drop if WP01 grep
> empty); **(b) UPSTREAM-WAIT — STRONGLY RECOMMENDED**, now even
> stronger because v2.27 closed the last named substantive WP from
> v2.25's seed; **(c) PARITY EXPANSION — marginal candidates only**
> (TicketRead, possibly LinkRead — low value); **(d'') GENERATED
> GUARDS — net-new candidate substantive WP** for v2.28: OpenAPI-
> driven codegen so future guard sites adopt mechanically;
> non-trivial design WP (build-pipeline + drift-test + emit-time
> decision); **premature without a forcing function — recommend
> deferring until ≥1 production drift or ≥5 bucket-i guards become
> independently justified**; **(e) DIRTY-TREE HOUSEKEEPING — should
> be empty** (verify `git status --short | wc -l` = 0); **(g)
> non-typecheck PIN sweeps** — re-audit on triggering need only.
> **Recommend (b) UPSTREAM-WAIT as primary. v2.27 is a clean stopping
> point. (d'') is the only structurally-interesting alternate but
> premature; everything else is prophylactic or upstream-blocked.**
> **Bucket A** (C7, E3, E4, F3), **Bucket B** (B1, B2), **Bucket C**
> (C1, C3, C4 — C2 substantively closed; bucket-i `request<T>`
> helper guards remain deferred to (d'') if pursued), **Bucket R**
> (R1 `_OFFENDER_ALLOWLIST` extract — still 5 subprocess-shelling
> lints) remain conditional carry-forwards — act ONLY on triggering
> need. Follow the sequential subagent loop pattern, TDD-first, one
> diagnosis doc per WP under
> `.claude/lessons-learned/v2.28-wpNN-diagnosis.md`. Append lessons
> to `.claude/lessons-learned/ticketing-v2.28.md`. **Forward rules
> carried from v2.15-v2.26:** (a)-(eee), 57 rules, see
> `ticketing-v2.26.md` close section. **Forward rules new from
> v2.27:** (fff) re-derive TS interfaces from backend Pydantic
> schemas when adopting `parseJson<T>` guards — drift fixes belong
> in the SAME commit as the guard adoption; v2.27-WP01 caught
> `UpdateHandleResponse.handle: string` vs. backend
> `UserHandleResponse.handle: str | None`, invisible to tsc/vitest
> because the consumer discards the await; the guard adoption is the
> cheapest forcing function for catching cross-language type drift;
> generalises to any validator adoption that crosses a language
> boundary. (ggg) guard adoption WPs require a UI-fallback decision
> matrix before code lands — for each shortlisted site, document
> "what does the user see if the guard throws?"; sites whose answer
> is "uncaught exception / blank screen" get paired UI work, not a
> guard in the current WP; v2.27-WP01 verified `audit.ts` ("No
> recent activity." empty state) and `users.ts` ("Failed to update
> handle." banner) as safe before WP02 wrote code; pairs with (eee)
> — seam-without-teeth lands freely, teeth-without-fallback does
> not; generalises to any runtime contract enforcement.
> Do NOT reintroduce the `_v1_deferred.py` skip-hook — per-test
> deferral uses plain pytest markers.

**Cumulative forward rules total: 59 (a-ggg).** v2.27 added 2 new
rules (fff, ggg) to the 57 carried from v2.26 (a-eee).
