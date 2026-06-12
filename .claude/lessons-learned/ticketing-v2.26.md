# v2.26 ticketing — lessons learned

Companion to `ticketing-v2.25.md`. v2.26 was the **Option (d)
`Response.json(): Promise<any>` → `unknown` sweep + `parseJson<T>`
seam** version (Bucket C C2 from v2.18 seed; the only substantial
remaining WP per v2.25-WP04's recommendation). WP01 recon mapped 19
`.json()` sites across `frontend/src/api/` and bucketed them D1/D3/D4.
WP02 shipped a structural seam at `frontend/src/api/_jsonParse.ts`
(~25 LOC) — `parseJson<T>(res, guard?): Promise<T>` — and migrated
the 6 `request<T>` helpers (sprints, people, tickets, notifications,
projects, auditLog) plus 4 direct sites (search, 2× users, audit).
**No runtime guards adopted in this version**; the optional second
arg is the future-teeth slot. The one surprise was `audit.ts`:
`body?.items` compiled fine under implicit `any`, but under the
seam's `Promise<unknown>` return needed an explicit
`(body as { items?: ActivityEntry[] } | null)?.items` annotation —
the seam earned its keep on 1/10 sites by surfacing a hidden shape
assumption. **WP03 was closure-only** per WP02's recommendation:
guards on high-value sites (audit, users) are a v2.27 conversation
requiring schema discipline + rejection-branch tests + UI fallback
decisions, and conflating them with the seam WP would have muddied
scope.

**Closing baselines:** backend **1459 P / 0 F / 7 skipped / 14
xfailed** (unchanged from v2.25 close — zero functional regressions),
frontend **276 P / 0 F** (untouched), mypy **28 raw errors / 28 keys**
(unchanged — framework-residual floor), **`npx tsc --noEmit`: 0
errors** (PIN floor at `tests/test_frontend_tsc_lint_v225.py` held
across the sweep — confirming the seam was type-tight). WP05
parametrize: **17** (unchanged). WP11 parametrize: **16** (unchanged).
`git status` clean (0 dirty post-WP03 commit).

**Commits:**
- WP01 — recon only, no commit
- WP02 — `cbcccf9e7ea17f1887fac6c984e0d69898574b46`
- WP03 — `33bd8c270a7021420d5da631911c5db43b8b1a56` (this closure; amend-folded)

---

## v2.26-WP01 — recon

Backend **1459 P**, frontend **276 P**, mypy 28 errors / 14 files,
tsc-noEmit 0 errors — all match v2.25 close. 19 `.json()` sites
enumerated across `frontend/src/api/`. Bucketing:

- **D1 — `request<T>` helpers (6 files):** sprints.ts, people.ts,
  tickets.ts, notifications.ts, projects.ts, auditLog.ts. Single
  parse site each, returns shaped through a typed function generic.
- **D3 — direct call-site parses (4 sites, 3 files):** search.ts,
  users.ts (2 parses — handle update + suggestions), audit.ts.
- **D4 — N/A in v2.26 scope.**

Design choice: **Option I — `parseJson<T>(res, guard?): Promise<T>`
helper at `frontend/src/api/_jsonParse.ts`.** Type generic on the
first arg, optional runtime guard on the second. Zero call sites
ship with a guard in v2.26 — the optional second arg is purely a
future-teeth slot so v2.27 (if it runs) can adopt `parseJson<T>(res,
isFoo)` instead of an inline `if`/throw.

No source edits in WP01.

---

## v2.26-WP02 — seam + sweep, `cbcccf9`

**Outcome.** 1 new file, 10 files touched, **0 vitest regressions**,
**tsc still 0**, mypy unchanged at 28, backend 1459 unchanged.

**Files touched:**

| File | Role | Notes |
|------|------|-------|
| `frontend/src/api/_jsonParse.ts` | new (~25 LOC) | `parseJson<T>(res, guard?)` |
| `frontend/src/api/sprints.ts` | D1 helper | `request<T>` parses via `parseJson<T>` |
| `frontend/src/api/people.ts` | D1 helper | same |
| `frontend/src/api/tickets.ts` | D1 helper | same |
| `frontend/src/api/notifications.ts` | D1 helper | same |
| `frontend/src/api/projects.ts` | D1 helper | same |
| `frontend/src/api/auditLog.ts` | D1 helper | same |
| `frontend/src/api/search.ts` | D3 direct | 1 inline swap |
| `frontend/src/api/users.ts` | D3 direct | 2 inline swaps (handle update, suggestions) |
| `frontend/src/api/audit.ts` | D3 direct + REAL SHAPE FIX | `body?.items` → `(body as { items?: ActivityEntry[] } | null)?.items` |

**Surprises:**
1. **`audit.ts` shape-assumption surprise.** Under the prior
   implicit-`any` regime, `const body = await res.json(); return
   body?.items;` compiled cleanly even though the response shape was
   never promised by `lib.dom`'s `.json(): Promise<any>`. Migrated
   to the seam's `Promise<unknown>`, the same line failed tsc and
   required `(body as { items?: ActivityEntry[] } | null)?.items` to
   make the shape contract explicit. **The seam earned its keep on
   1/10 sites by forcing a hidden assumption into code.** Generalises
   into rule (ddd) below.
2. **9/10 sites were truly mechanical.** The 6 `request<T>` helpers
   already had a function generic; swapping `await res.json()` for
   `await parseJson<T>(res)` was a one-liner each. 3 of the 4 D3
   sites likewise — only `audit.ts` surfaced the hidden shape.
3. **No call site adopted the guard arg.** Decision: ship the seam
   without simultaneous guard adoption. Conflating seam landing with
   schema-discipline decisions would have stretched WP02 into design
   territory it wasn't scoped for. Generalises into rule (eee).

**Residual after WP02.** 0 (no further sweep work intended for
v2.26). vitest 276 P unchanged; tsc 0 unchanged; mypy 28 unchanged;
backend 1459 unchanged.

---

## v2.26-WP03 (closure) — this document

Retrospective written. v2.27 paste-ready seed appended at bottom.
Zero production code touched in this WP.

---

## v2.26 retrospective

### Headline numbers

- **Backend:** 1459 → **1459 P** / 0 F / 7 skipped / 14 xfailed
  (unchanged — zero functional regressions, zero new tests).
- **Frontend (vitest):** 276 P / 0 F — untouched across all WPs by
  test count. 10 files diff-touched in WP02; 1 new file
  (`_jsonParse.ts`).
- **Frontend (tsc-noEmit):** 0 → **0 errors** (PIN held across the
  sweep — confirming the seam was type-tight).
- **Mypy raw errors:** 28 → 28 (unchanged — framework-residual
  floor).
- **Mypy allow-list keys:** 28 → 28 (unchanged).
- **Classification:** **0 LEGACY throughout.**
- **WP05 parity PIN:** 17 → **17** (unchanged).
- **WP11 parity PIN:** 16 → **16** (unchanged).
- **Net-new typed consumers introduced:** 0.
- **Latent shadow-of-builtin sites eliminated:** 0.
- **Real bugs fixed:** 0 (the `audit.ts` shape fix was a precondition
  for the seam to compile, not a runtime bug — the prior code would
  have returned `undefined` if the server ever changed shape, which
  was already the consumer-side behaviour. The fix made the
  assumption explicit).
- **Production code touched (`app/`):** 0 files.
- **Production code touched (`frontend/src/`):** 11 files
  (1 new + 10 edits, all under `frontend/src/api/`).
- **Config touched:** 0 files.
- **Test code touched:** 0 files.
- **Production regressions introduced:** zero.
- **Secrets committed:** zero.
- **Closing git status:** 0 dirty (post-WP03 commit).

### WPs shipped

| WP | Bucket | Summary | PIN delta |
|----|--------|---------|----------:|
| WP01 | C C2 | Recon. Confirmed v2.25 close baseline. Enumerated 19 `.json()` sites across `frontend/src/api/` bucketed D1 (6 helpers) / D3 (4 direct) / D4 (none in scope). Picked Option I — `parseJson<T>(res, guard?)` helper. No source edits. | ±0 |
| WP02 | C C2 | Ship the seam (`_jsonParse.ts`, ~25 LOC) + migrate 10 sites. **`audit.ts` required a real source-level shape annotation** — the seam earned its keep on 1/10 sites. No guards adopted (deferred to v2.27 candidate). Vitest 276 P, tsc 0, mypy 28 all invariant. | ±0 |
| WP03 | closure | Retrospective + v2.27 seed. Both type channels remain at PIN-protected floor. | ±0 |

### What didn't ship

- **Runtime guards on the seam.** Zero call sites pass `parseJson<T,
  guard>` in v2.26. The optional second arg ships as a future-teeth
  slot; adopting guards at high-value sites (audit, users) is
  deferred to v2.27 as candidate (d') because it requires schema
  discipline + rejection-branch tests + a UI-fallback decision per
  surface. Conflating it with the seam-landing WP would have
  stretched scope into design territory.
- **Option (b) UPSTREAM-WAIT.** v2.25 closure flagged this as the
  honest baseline; user explicitly chose to execute the substantive
  WP. Recommendation stands even stronger now (see v2.27 seed below).

### Cross-cutting lessons — NEW forward rules

2 new rules promoted from v2.26 (rules **ddd, eee**), built on the
55 carried from v2.25 (a-ccc).

**(ddd) Implicit-any → unknown migration earns its keep on first
contact when ≥1 callsite forces real source-level reasoning to
compile.** When scoping a `Promise<any>` → `Promise<unknown>` sweep
(or any equivalent loosen-to-tighten migration), expect roughly
1-in-10 sites to surface a real shape assumption that was hiding
behind the loose type. In v2.26-WP02, `audit.ts`'s `body?.items`
compiled cleanly under implicit `any` despite the field being
un-promised by `lib.dom`'s `Response.json(): Promise<any>`; under
the seam's `Promise<unknown>`, the same line failed tsc until
`(body as { items?: ActivityEntry[] } | null)?.items` made the
shape contract explicit. **Why:** the value of these sweeps isn't
just type-hygiene — it's surfacing latent assumptions. The
mechanical sites are the cost; the friction sites are the payoff.
**How to apply:** budget for it. Don't pre-declare the sweep
"mechanical only" in scoping; explicitly call out that a fraction
of sites will need real shape annotations and that's the point.
Pair with rule (zz) — these aren't *runtime* bugs the way zz's
type-bug-fix cases are, but they're the same family: tightening
types catches real semantic ambiguity. Generalises across any
loosen-to-tighten type migration: `any` → `unknown`, `Object` →
typed dict, `interface{}` → concrete struct, untyped Go interface
→ typed assertion, raw JSON → schema-validated.

**(eee) Structural seams without runtime teeth are still ship-worthy
when they make future teeth a one-line change.** `parseJson<T>(res,
guard?)` shipped in v2.26-WP02 with zero call sites passing a
`guard`. The win is the *optional second arg*: adopting a runtime
guard at a high-value site becomes `parseJson<T>(res, isFoo)`
instead of inline `if (!isFoo(body)) throw …`. **Why:** seams and
teeth are independent design problems. Schema design (what does a
valid `ActivityFeed` look like?) deserves its own attention and
its own rejection-branch tests; gating the seam on simultaneous
guard adoption conflates scope and risks blocking the seam on
schema decisions that haven't been made. **How to apply:** when
sketching a seam that *could* carry teeth, design the API so teeth
are an optional second arg (or analogous slot), land the seam
across all call sites WITHOUT teeth, and defer teeth to a follow-up
WP where each high-value site gets a schema + rejection-branch test
+ UI-fallback decision treated as first-class design work. The
seam itself is a structural improvement (types tighten, shape
assumptions get audited per rule ddd) — that justifies the WP
independent of teeth adoption. Generalises to ANY validator-shaped
seam: parser adapters, deserialisation wrappers, message-bus
envelopes, IPC boundary translators. Pair with (eee predecessor
rule ccc-family on lockstep edits): seam landings should be
clean-scope; teeth adoption is a different commit-family.

### What stayed deferred (carry to v2.27)

- **Preventative-hygiene (likely empty for v2.27):** no new shadow-
  of-builtin sites surfaced in v2.26. v2.26 was all
  `frontend/src/api/` work; the `app/services/` Python surface
  wasn't touched. Re-audit grep recommended at v2.27-WP01 if it
  runs; expectation empty.

- **Parity expansion (still likely empty for v2.27):** the 3
  unpinned `Page<T>` wrappers (`Page_AgentActivityItem_`,
  `CursorPage_ProblemResponse_`, `Page_TicketAttachmentRead_`) all
  still require their TS counterparts to upgrade independently and
  remain redundant per rule (tt). v2.26 didn't surface new
  candidates.

- **SubtreeRow recursive parity** — carry from v2.22. Non-trivial
  parser extension required.

- **Bucket C C2 GUARDS (NEW candidate for v2.27 — Option (d')).**
  Adopt runtime guards at high-value `parseJson<T>` sites — primarily
  `audit.ts` (`{items?: ActivityEntry[]} | null` narrower) and
  `users.ts` (handle-update `next_allowed_at` shape). 2–3 sites,
  needs schema discipline + UI-fallback decision (what does the page
  show when the guard throws? Empty list? Error banner? Retry?).
  Cousin of v2.18 L1+L2 ProblemDetail typed work. **Prophylactic**
  in the same sense as v2.25's seed warning for parent (d) — the
  seam already makes the shape assumptions visible (per rule ddd);
  guards would harden them to runtime rejection. Trade-off: each
  guard is a place where a server-side shape drift will start
  throwing, which is good for debuggability but requires the UI to
  handle the rejection branch gracefully.

- **Bucket A** (C7, E3, E4, F3) — still conditional v2.11
  carry-forwards.
- **Bucket B** (B1, B2) — still conditional v2.13 carry-forwards.
- **Bucket C** (C1, C3, C4) — still conditional v2.18 carry-forwards.

- **Bucket R cosmetic** — `_OFFENDER_ALLOWLIST` helper extract
  (v2.19 rule (ee)) — carry from v2.19 → ... → v2.26. Still 5
  subprocess-shelling lints in the family (bare-catch, ts-any,
  pragma, typecheck-mypy, typecheck-tsc); v2.26 added no new lints
  to the family.

- **28 BY-DESIGN typecheck residents — the genuine framework-
  residual floor.** Unchanged from v2.21/v2.22/v2.23/v2.24/v2.25
  close. Re-evaluate every N versions per rule (kk).

### Notes — judgment calls worth recording

- **Recon-vs-edit boundary at WP01.** Strict no-source-edits in
  recon per rule (ww). Even the `_jsonParse.ts` helper, which was
  fully designed in WP01, didn't land until WP02. This kept WP01
  reversible and lossless.
- **Seam-vs-teeth split at WP02.** Decided in WP02 (not pre-scoped
  in WP01) to ship the seam without guards. Promoted as rule (eee).
  The alternative — land seam + 1 guard on `audit.ts` as a
  forcing-function example — would have demanded a UI-fallback
  decision that the WP02 agent wasn't positioned to make. Correct
  call.
- **WP03 as closure-only.** WP02 agent recommended closure-only
  WP03 (their recommendation (b)) rather than landing a second
  substantive sweep. Reason: with the seam banked and `tsc` at 0,
  the next substantive axis is guards (which is design WP territory)
  and would have been miscategorised as a WP03 incremental. Better
  as a v2.27 conversation. Closure-only WP03 is consistent with
  v2.24 and v2.25 closure shapes.
- **`audit.ts` cast vs. proper interface declaration.** The fix
  uses an inline `body as { items?: ActivityEntry[] } | null` rather
  than declaring a top-level `ActivityFeedResponse` interface. This
  is intentional: the inline cast makes the assumption visible at
  the call site, which is exactly the value rule (ddd) wants to
  capture. A top-level interface would have been the right move IF
  the seam was simultaneously adopting a runtime guard
  (`isActivityFeedResponse`), but that's v2.27 work.

### Files touched (rough stats — sum of WP01 + WP02 + WP03)

- **Production code (`app/`):** 0 files (backend untouched).
- **Production code (`frontend/src/`):** 11 files, all under
  `frontend/src/api/`:
  - `_jsonParse.ts` — NEW (~25 LOC).
  - 6 D1 helpers: sprints, people, tickets, notifications, projects,
    auditLog.
  - 4 D3 direct sites: search, users (×2), audit.
- **Config:** 0 files.
- **Lint allow-lists:** 0 files (rule ccc not triggered — no
  line-shift cross-lint break).
- **Test code (backend, new):** 0 files.
- **Test code (frontend):** 0 new files; 0 edits.
- **Docs (`.claude/lessons-learned/`):** WP01 + WP02 diagnosis files
  + this retrospective.

---

## v2.27 starting prompt seed

v2.26 closed as the **Option (d) `Response.json()` any → unknown
sweep + `parseJson<T>` seam** version. Recon enumerated 19 sites in
`frontend/src/api/` (D1 helpers / D3 direct). WP02 shipped
`frontend/src/api/_jsonParse.ts` (~25 LOC) — `parseJson<T>(res,
guard?): Promise<T>` — and migrated 10 sites (6 D1 helpers + 4 D3
direct). `audit.ts` was the only site needing a real source-level
shape annotation (`(body as { items?: ActivityEntry[] } | null)?.items`)
— the seam earned its keep on 1/10 sites by surfacing a hidden shape
assumption (rule ddd). No call site adopted a runtime guard; the
optional second arg ships as a future-teeth slot (rule eee). Closing
baselines: backend **1459 P / 0 F / 7 skipped / 14 xfailed**, frontend
**276 P / 0 F**, mypy **28 errors / 28 keys (0 LEGACY)**, **`npx tsc
--noEmit`: 0 errors** (PIN held across the sweep). v2.26 added 2 new
forward rules: (ddd) implicit-any → unknown migrations earn their
keep when ≥1 callsite forces real source-level reasoning; (eee)
structural seams without runtime teeth are still ship-worthy when
they make future teeth a one-line change.

### Status framing

**v2.26 closed the last substantial frontend type-safety WP that
existed in the v2.25 seed.** Mypy at PIN floor (28 keys,
upstream-blocked). Tsc at 0 + PIN. The `Promise<any>` →
`Promise<unknown>` sweep is done. **(b) UPSTREAM-WAIT is now the
strongest it has ever been.** The only candidate substantive WP for
v2.27 is **(d') C2 GUARDS** — adopting runtime guards at high-value
`parseJson<T>` sites — and that's prophylactic the way parent (d)
was prophylactic. There is no remaining typecheck-PIN reduction work
without external dependency movement.

### Shapes for v2.27

- **(a) PREVENTATIVE-HYGIENE — empty.** v2.26 was all
  `frontend/src/api/` work; no new shadow-of-builtin sites surfaced.
  Drop bucket (a) if WP01 grep empty.
- **(b) UPSTREAM-WAIT — STRONGLY RECOMMENDED.** v2.26 closes the
  last substantial frontend type-safety WP. Monitor mypy /
  SQLAlchemy / Starlette / FastAPI / DOM-lib releases. **This is
  the honest stop position.**
- **(c) PARITY EXPANSION continued — marginal candidates.** WP01
  re-scan surfaced `TicketRead` + possibly `LinkRead` as marginal
  candidates (existing TS interfaces, GET-side reads of
  already-pinned write routes). Low value. Likely empty unless a
  consumer upgrade is independently prioritised.
- **(d') C2 GUARDS — net-new bucket for v2.27.** Adopt runtime
  guards at high-value `parseJson<T>` sites — primarily `audit.ts`
  and `users.ts`. 2–3 sites. Requires schema discipline +
  rejection-branch tests + UI-fallback decision per surface (what
  does the page show when the guard throws? empty list? error
  banner? retry?). Cousin of v2.18 L1+L2 ProblemDetail typed work.
  **Prophylactic — same warning v2.25 gave for parent (d).** The
  seam already makes the shape assumptions visible (per rule ddd);
  guards would harden them to runtime rejection.
- **(e) DIRTY-TREE HOUSEKEEPING — should be empty.** v2.26 closed
  clean. Verify `git status --short | wc -l` = 0.
- **(g) non-typecheck PIN sweeps — re-audit on triggering need
  only.** Most reached "all BY-DESIGN" in v2.22 recon. Carry forward
  unchanged.

**Conditional carry-forwards (unchanged from v2.25):** Bucket A (C7,
E3, E4, F3), Bucket B (B1, B2), Bucket C (C1, C3, C4), Bucket R (R1
`_OFFENDER_ALLOWLIST` extract — still 5 subprocess-shelling lints
in the family). Act ONLY on triggering need.

**Recommend (b) UPSTREAM-WAIT as primary. (d') C2 GUARDS is the
ONLY candidate substantive alternate if the user keeps pushing.**

### v2.27 prompt seed (paste-ready)

> Proceed with v2.27 of the problem-bulletin ticketing system —
> **OR consider declaring v2.26 the natural project-finished endpoint
> and stopping.** v2.26 retrospective + carry-forward backlog live at
> the bottom of `.claude/lessons-learned/ticketing-v2.26.md`.
> Baselines: backend **1459 P / 0 F / 7 skipped / 14 xfailed**,
> frontend **276 P / 0 F**, mypy **28 errors / 28 allow-list keys
> (0 LEGACY)**, frontend `npx tsc --noEmit`: **0 errors (PIN at
> `tests/test_frontend_tsc_lint_v225.py`)**, WP05 parity PIN **17
> parametrize entries**, WP11 parity PIN **16 routes**. **v2.26 was
> the (d) `Response.json()` any → unknown sweep version executed
> end-to-end — 10 sites migrated to `frontend/src/api/_jsonParse.ts`'s
> `parseJson<T>(res, guard?)` seam. `audit.ts` needed a real
> source-level shape annotation; the seam earned its keep on 1/10
> sites (rule ddd). No call site adopted a runtime guard — that's
> the future-teeth slot deferred to v2.27 candidate (d') C2 GUARDS.**
> **Both type channels remain at PIN-protected floor.**
> Shapes: **(a) PREVENTATIVE-HYGIENE — empty** (drop if WP01 grep
> empty); **(b) UPSTREAM-WAIT — STRONGLY RECOMMENDED**, now even
> stronger because v2.26 closed the last substantial frontend
> type-safety WP; **(c) PARITY EXPANSION — marginal candidates only**
> (TicketRead, possibly LinkRead — low value); **(d') C2 GUARDS —
> net-new candidate substantive WP** for v2.27: adopt runtime guards
> at high-value `parseJson<T>` sites (audit.ts, users.ts — 2-3 sites)
> with schema discipline + rejection-branch tests + UI-fallback
> decisions; **prophylactic, same warning v2.25 gave for parent (d)**;
> **(e) DIRTY-TREE HOUSEKEEPING — should be empty** (verify `git
> status --short | wc -l` = 0); **(g) non-typecheck PIN sweeps** —
> re-audit on triggering need only. **Recommend (b) UPSTREAM-WAIT
> as primary. v2.26 is a clean stopping point. (d') is the only
> substantial work remaining; everything else is prophylactic or
> upstream-blocked.** **Bucket A** (C7, E3, E4, F3), **Bucket B**
> (B1, B2), **Bucket C** (C1, C3, C4), **Bucket R** (R1
> `_OFFENDER_ALLOWLIST` extract — still 5 subprocess-shelling lints)
> remain conditional carry-forwards — act ONLY on triggering need.
> Follow the sequential subagent loop pattern, TDD-first, one
> diagnosis doc per WP under
> `.claude/lessons-learned/v2.27-wpNN-diagnosis.md`. Append lessons
> to `.claude/lessons-learned/ticketing-v2.27.md`. **Forward rules
> carried from v2.15-v2.25:** (a)-(ccc), 55 rules, see
> `ticketing-v2.25.md` close section. **Forward rules new from
> v2.26:** (ddd) implicit-any → unknown migrations earn their keep
> on first contact when ≥1 callsite forces real source-level
> reasoning to compile — v2.26-WP02 `audit.ts` needed
> `(body as { items?: ActivityEntry[] } | null)?.items` under
> `unknown` even though `body?.items` worked under implicit `any`;
> the seam payoff is the friction sites, not the mechanical ones;
> pair with (zz); generalises to any loosen-to-tighten type
> migration. (eee) structural seams without runtime teeth are still
> ship-worthy when they make future teeth a one-line change — the
> `parseJson<T>(res, guard?)` seam shipped with zero guard adoption,
> but the optional second arg makes future adoption `parseJson<T>(res,
> isFoo)` instead of inline `if`/throw; design seam APIs so teeth
> are an optional slot; defer teeth to a follow-up WP where schema
> design + rejection-branch tests + UI-fallback decisions get their
> own attention; generalises to any validator-shaped seam.
> Do NOT reintroduce the `_v1_deferred.py` skip-hook — per-test
> deferral uses plain pytest markers.

**Cumulative forward rules total: 57 (a-eee).** v2.26 added 2 new
rules (ddd, eee) to the 55 carried from v2.25 (a-ccc).
