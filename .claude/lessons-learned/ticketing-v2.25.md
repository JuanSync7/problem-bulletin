# v2.25 ticketing — lessons learned

Companion to `ticketing-v2.24.md`. v2.25 was the **(f) tsc-noEmit
triage version** executed end-to-end: 76 errors → 0 across 4
categorical commits (A/B/C/E+F+G config & sweeps) + 1 real bug fix
(`ProblemDetail.tsx:1052` onClick handler — a latent UX side-effect
discovered hiding under the type bug). The fix was paired with a new
PIN installed at `tests/test_frontend_tsc_lint_v225.py` that mirrors
the v2.19-WP02 mypy PIN structure: empty allow-list, bidirectional
stale-detection, synthetic-bad teeth verified end-to-end. **Both
type channels (mypy + tsc-noEmit) are now at floor + PIN-protected**.
Backend grew **+6 tests** from the new PIN (parser self-tests + main
lint + opt-in subprocess teeth gate). The frontend bug at line 1052
would have triggered a full-screen spinner on retry (the truthy
MouseEvent flowing into `showLoading`) — TS caught a real runtime
bug, not a typing artefact.

**Closing baselines:** backend **1459 P / 0 F / 7 skipped / 14 xfailed**
(+6 over v2.24 close: 5 parser self-tests + 1 bidirectional pin in
the new tsc PIN module, plus 1 opt-in subprocess teeth gate skipped
by default), frontend **276 P / 0 F** (untouched by test count),
mypy **28 raw errors / 28 keys** (unchanged — framework-residual
floor), **frontend `npx tsc --noEmit`: 0 errors** (NEW PIN at floor).
WP05 parametrize: **17** (unchanged). WP11 parametrize: **16**
(unchanged). `git status` clean (0 dirty after WP04 commit).

---

## v2.25-WP01 (G0) — recon

Backend **1453 P**, frontend **276 P**, mypy 28 errors / 14 files,
tsc-noEmit 76 errors — all match v2.24 close. Full attack-plan
written to `v2.25-wp01-diagnosis.md`.

**Key recon findings:**
- `npx tsc --noEmit` produced 78 output lines but only **76 distinct
  errors** — 2 lines were continuation/detail lines for the single
  TS2322 at `ProblemDetail.tsx:1052`. Confirms rule (qq): recon must
  *count* not *line-count*.
- Categorisation went **beyond the v2.24 seed's category enumeration**:
  v2.24 cited 5 categories (unused React, missing node types, lib
  raise, globalThis, real bug). v2.25-WP01 surfaced **7 root-cause
  categories**: A (`@types/node`, 17), B (ES2022 lib, 2), C (unused
  `React` import, 44), D (real bug, 1), E (misc unused locals, 4),
  F (test-fixture missing `version` prop, 4), G (vite/client types
  for `import.meta.env`, 2). +2 categories (F, G) beyond seed.
- **All categories had FIX as the right answer (not PIN).** Distinct
  from the mypy 28-key floor: those are framework-friction
  upstream-blocked. Tsc residuals were environment/config drift
  fixable in-version.
- **WP ordering:** WP02 first (infra sweep, A/B/C/E/F/G), WP03 second
  (real bug + PIN), WP04 closure.

---

## v2.25-WP02 — Config + mechanical sweep, 4 commits, 76 → 1

**Outcome.** 76 → 1 across 4 per-category commits. **0 vitest
regressions** at every sub-commit boundary. Cat D (1 remaining error)
deferred to WP03 as planned.

**Per-commit ledger:**

| Commit | SHA | Cat | tsc-after | Surface |
|--------|-----|-----|-----------|---------|
| WP02a | `07e4319` | A | 59 (-17) | `frontend/package.json` + `package-lock.json` + `tsconfig.json` (`types: ["node", "vite/client"]`) |
| WP02b | `1a77bd0` | B | 57 (-2)  | `tsconfig.json` (target/lib → ES2022) |
| WP02c | `b042db4` | C | 9 (-48)  | 48 files — unused `import React` swept (script-driven, zero manual triage) |
| WP02d | `0ec4a6a` | E+F+G | 1 (-8) | 6 targeted files — unused locals + 4 test fixtures get `version: 1` + Search.tsx line-shift allow-list fix |

**Surprises:**
1. **Cat C estimate 44 → actual 48** (+9%, within rule (kk)
   tolerance). All 48 matched the safe pattern (pure default or
   `React, { named }`), and the sweep script flagged zero `React.X`
   body refs — entirely mechanical.
2. **Cat G was a free side-effect of Cat A.** Adding `"vite/client"`
   to `compilerOptions.types` cleared both `import.meta.env` TS2339
   errors at the same commit as Cat A's broader fix. Pre-anticipated
   in WP01; confirmed.
3. **Line-shift cross-lint break in WP02d.** Removing the 4-line
   unused `armTotal` helper in `Search.tsx` shifted later line
   numbers, which broke the catch-block lint allow-list (entry pinned
   to line 354, now at 350). Fixed in-commit by updating the
   allow-list constant. No production code change. **Generalises into
   forward rule (ccc).**
4. **`@types/node` lockfile delta was small** — single devDep add, no
   dependency tree shake.

**Residual after WP02.** 1 (the Cat D real bug); vitest 276 P
unchanged; mypy 28 unchanged; backend 1453 unchanged.

---

## v2.25-WP03 — Real bug fix + tsc PIN install

**Outcome.** 2 commits. tsc 1 → 0; backend 1453 → **1459 P** (+6 from
new PIN); vitest 276 P preserved. PIN structurally mirrors v2.19-WP02
mypy precedent.

### WP03a — ProblemDetail.tsx:1052 fix (`44cfb15`)

The bare `onClick={fetchProblem}` passed `MouseEvent` into
`fetchProblem`'s `showLoading?: boolean` slot. Under JS truthy
semantics, the MouseEvent would have **flipped the full-screen
spinner on instead of doing the inline retry**. TS was reporting a
real runtime bug, not a typing artefact.

**Fix:** `onClick={() => fetchProblem()}` — single-line arrow-wrap to
drop the event and let `showLoading` default to `false`.

### WP03b — `tests/test_frontend_tsc_lint_v225.py` PIN install

Structural mirror of `tests/test_typecheck_lint_v219_wp02.py`. ~245
LOC. 7 tests collected (5 named parser self-tests + 1
bidirectional offender pin marked `@pytest.mark.slow` + 1 opt-in
synthetic-bad subprocess gated by `RUN_TSC_SELFTEST=1`).

- Regex: `^(?P<path>[^\s()][^()]*?)\((?P<line>\d+),(?P<col>\d+)\):\s*error\s+(?P<code>TS\d+):\s.*$`
  — anchored single-line; tsc continuation/indented detail lines
  silently skipped.
- Subprocess: `cwd=frontend/`, `npx tsc --noEmit`, timeout=180,
  stdout+stderr merged. Skipped if `npx` not on PATH.
- Allow-list: `_OFFENDER_ALLOWLIST: dict[str, str] = {}` — empty,
  enforcing the 0-floor.
- Bidirectional stale-detection: NEW offenders **and** STALE
  allow-list entries both fail loud (per rule (s)).

**Synthetic-bad teeth verified PASS→FAIL→PASS** by injecting a
`const n: number = "not-a-number";` into `src/__tsc_pin_selftest__.ts`,
asserting the lint failed loud, deleting the scratch file, and
re-confirming PASS. Opt-in subprocess teeth gate
(`RUN_TSC_SELFTEST=1`) also exercised end-to-end.

**Performance:** ~5s warm full PIN; tsc invocation alone ~3-4s.
Marked `@pytest.mark.slow` per rule (mm) refinement (see (bbb) below).

**Residual after WP03.** tsc 0; backend 1459 P; mypy 28 unchanged;
**both type channels PIN-protected at floor.**

---

## v2.25-WP04 (closure) — this document

Retrospective written. v2.26 paste-ready seed appended at bottom.
Zero production code touched in this WP.

---

## v2.25 retrospective

### Headline numbers

- **Backend:** 1453 → **1459 P** / 0 F / 7 skipped / 14 xfailed
  (+6 from new tsc PIN module: 5 parser self-tests + 1 bidirectional
  offender pin + 1 opt-in subprocess teeth gate skipped by default;
  zero functional regressions).
- **Frontend (vitest):** 276 P / 0 F — untouched across all 4 WPs
  by test count. 48 files diff-touched in WP02c (unused `import
  React` strip); 6 files diff-touched in WP02d; 1 file diff-touched
  in WP03a.
- **Frontend (tsc-noEmit):** 76 → **0 errors** (full elimination).
  NEW PIN tracking the floor; per rule (yy) the two type channels
  are separable axes — both now pinned.
- **Mypy raw errors:** 28 → 28 (unchanged — framework-residual
  floor).
- **Mypy allow-list keys:** 28 → 28 (unchanged).
- **Classification:** **0 LEGACY throughout.**
- **WP05 parity PIN:** 17 → **17** (unchanged).
- **WP11 parity PIN:** 16 → **16** (unchanged).
- **Net-new typed consumers introduced:** 0 (v2.25 was type-channel
  closure, not contract expansion).
- **Latent shadow-of-builtin sites eliminated:** 0.
- **Real bugs fixed:** **1** — `ProblemDetail.tsx:1052` retry-button
  onClick (latent UX bug masked by TS error per (zz)).
- **Production code touched (`app/`):** 0 files.
- **Production code touched (`frontend/src/`):** ~54 files — 48 in
  WP02c (mechanical `import React` strip), 5 in WP02d (targeted),
  1 in WP03a (the real fix).
- **Config touched:** 3 files (`package.json`, `package-lock.json`,
  `tsconfig.json` over WP02a/WP02b).
- **Test code touched:** 1 new test file
  (`tests/test_frontend_tsc_lint_v225.py` — WP03b PIN install) +
  2 existing test files in WP02d (1 fixture file, 1 line-shift fix).
- **Production regressions introduced:** zero.
- **Secrets committed:** zero.
- **Closing git status:** 0 dirty (post-WP04 commit).

### WPs shipped

| WP | Bucket | Summary | PIN delta |
|----|--------|---------|----------:|
| WP01 | G0 | Recon. Confirmed v2.24 close baseline. Enumerated 76 tsc errors across 7 root-cause categories (A/B/C/D/E/F/G — 2 categories F/G beyond seed). All FIX, no PIN. | ±0 |
| WP02 | F | tsc-noEmit infra sweep. 4 per-category commits (A `@types/node`, B ES2022, C 48-file React strip, E+F+G targeted). 76 → 1. Vitest 276 P invariant. Cross-lint line-shift fix in WP02d. | ±0 |
| WP03 | F + new PIN | (a) Real bug fix at `ProblemDetail.tsx:1052` (latent UX side-effect). (b) Install `tests/test_frontend_tsc_lint_v225.py` mirroring v2.19-WP02 mypy PIN — empty allow-list, bidirectional stale, synthetic-bad teeth. Backend +6 P. tsc 1 → 0. | +1 PIN module (+6 tests), ±0 mypy |
| WP04 | closure | Retrospective + v2.26 seed. **Both type channels at floor + PIN-protected.** | ±0 |

### Cross-cutting lessons — NEW forward rules

4 new rules promoted from v2.25 (rules **zz, aaa, bbb, ccc**), built
on the 51 carried from v2.24 (a-yy).

**(zz) Type-bug fixes often hide latent runtime bugs.** The
`ProblemDetail.tsx:1052` fix was not purely cosmetic: the truthy
MouseEvent flowing into `showLoading: boolean | undefined` would have
triggered a full-screen spinner on retry (the user would see the
whole page blank to a loader instead of the inline button-pending
indicator). **When fixing a type error, always check whether the
type fix changes runtime behaviour** — sometimes the typechecker is
reporting a real semantic bug masquerading as cosmetic. Procedure:
before applying the fix, trace what the source argument actually is
at runtime under the buggy signature, and what the consumer does
with it. If the answer is "non-trivial side-effect", the
type-channel close is also a UX regression fix and should land
with a vitest regression test where feasible. Generalises across
any `(EventLike) → (Boolean | undefined)` mismatch and more broadly
any callback-passing-event-as-data scenario.

**(aaa) PIN mirror skill compounds across versions.** v2.25-WP03b
ported the mypy PIN's parser + allowlist + self-test structure to TS
in one WP. Cousin of (xx) for typed consumers: when a structural
mirror exists, reuse the precedent verbatim — subprocess shim,
error parsing, bidirectional staleness, `RUN_X_SELFTEST=1` opt-in,
allow-list dict shape, `path:line:errcode` keying. The PIN's
parser shape transfers between language ecosystems with only
regex + subprocess cwd + error-code alphabet swapped out. Drop the
blast-radius by treating the precedent as authoritative template
(down to test-function naming and `@pytest.mark.slow` marker
placement). Generalises across ANY PIN-shape mirror between
toolchains (linter A → linter B; formatter A → formatter B; CI
gate A → CI gate B). Pair with (xx): both refine (rr) and (uu) —
mirror commits are first-run-clean when precedent is followed
verbatim.

**(bbb) `@pytest.mark.slow` is the right gate for any
subprocess-shelling PIN.** Both the mypy PIN (slow, ~12s warm) and
the new tsc PIN (slow, ~5s warm) shell out to a typechecker
binary. Without the marker, dev loops running `pytest -x` grind to
a halt; with it, devs opt in via `pytest -m slow` and CI runs with
no marker filter so the floor is still enforced. Refines (mm) and
(ff): subprocess-based lints are acceptable when warm-cache
runtime is single-digit seconds AND the test is
`@pytest.mark.slow`-tagged from day one. Generalises to ruff,
prettier, black, eslint, or any tool whose Python binding shells
out and adds non-trivial latency. The marker is part of the PIN
contract, not optional polish.

**(ccc) Removing unused locals can shift unrelated lint allow-list
line numbers.** WP02d's `armTotal` removal in `Search.tsx` shifted a
catch-block lint pin from line 354 → 350. Lockstep update kept tests
green. **Refines (t) and (qq).** When a sweep edits a file that is
also referenced by a line-number-keyed lint allow-list, the sweep
WP must include the allow-list update in the same commit. Detection:
after applying any unused-local removal, run the line-number-keyed
lints whose allow-lists reference the touched file. Mitigation
(strategic): context-snippet or function-name anchoring per (t) is
still the right long-term fix; lockstep update is the tactical
patch. Generalises to any keying scheme that embeds source-file
positions — bare-catch, type-ignore, ts-any, pragma allowlists.

### What stayed deferred (carry to v2.26)

- **Preventative-hygiene (likely empty for v2.26):** no new shadow-
  of-builtin sites surfaced in v2.25. Re-audit grep recommended at
  v2.26-WP01 if it runs; expectation empty.

- **Parity expansion (likely empty for v2.26):** the two "easy"
  net-new typed-consumer candidates (TicketWatcher, TicketAttachment)
  landed in v2.23/v2.24. No new candidates surfaced in v2.25 (which
  was type-channel triage, not contract expansion). The 3 unpinned
  `Page<T>` wrappers (`Page_AgentActivityItem_`,
  `CursorPage_ProblemResponse_`, `Page_TicketAttachmentRead_`) all
  still require their TS counterparts to upgrade independently and
  remain redundant per rule (tt).

- **SubtreeRow recursive parity** — carry from v2.22. Non-trivial
  parser extension required.

- **Bucket C C2 — `Response.json(): Promise<any>` → `unknown` +
  runtime parser sweep** — STILL legitimate v.NN work if the user
  wants to push beyond v2.25. ~30+ call sites across
  `frontend/src/api/`. Non-trivial design WP (parser shape, error
  reporting, migration order). This is the only remaining
  substantial axis if the user wants to keep going post-v2.25.

- **Bucket A** (C7, E3, E4, F3) — still conditional v2.11
  carry-forwards.
- **Bucket B** (B1, B2) — still conditional v2.13 carry-forwards.
- **Bucket C** (C1, C3, C4) — still conditional v2.18 carry-forwards.

- **Bucket R cosmetic** — `_OFFENDER_ALLOWLIST` helper extract
  (v2.19 rule (ee)) — carry from v2.19 → ... → v2.25. With the new
  tsc PIN bringing the family to **5 subprocess-shelling lints**
  (bare-catch, ts-any, pragma, typecheck-mypy, typecheck-tsc), the
  extract grows more compelling but remains cosmetic.

- **28 BY-DESIGN typecheck residents — the genuine framework-
  residual floor.** Unchanged from v2.21/v2.22/v2.23/v2.24 close.
  Re-evaluate every N versions per rule (kk).

### Files touched (rough stats — sum of WP02 + WP03)

- **Production code (`app/`):** 0 files (backend untouched).
- **Production code (`frontend/src/`):** ~54 files:
  - WP02c: 48 files — unused `import React` strip (script-driven).
  - WP02d: 5 files — targeted edits (1 fixture file, 4 unused-local
    removals).
  - WP03a: 1 file — `pages/ProblemDetail.tsx` real fix.
- **Config:** 3 files (`frontend/package.json`,
  `frontend/package-lock.json`, `frontend/tsconfig.json`).
- **Lint allow-lists:** 1 file
  (`frontend/src/pages/__tests__/catch_block_lint.test.ts` — WP02d
  line-shift accommodation per rule (ccc)).
- **Test code (backend, new):** 1 new file
  (`tests/test_frontend_tsc_lint_v225.py` — WP03b PIN, 7 tests).
- **Test code (frontend):** 0 new files; 2 existing edits
  (ticketDto fixtures, KanbanHorizontalScroll unused local).
- **Docs (`.claude/lessons-learned/`):** 3 per-WP diagnosis files for
  v2.25 (WP01, WP02, WP03) + this retrospective.

---

## v2.26 starting prompt seed

v2.25 closed as a **(f) tsc-noEmit triage version** executed
end-to-end: 76 errors → 0 across 4 categorical commits + 1 real bug
fix (`ProblemDetail.tsx:1052` onClick — latent UX side-effect: a
truthy MouseEvent would have triggered a full-screen spinner on
retry). A new PIN
(`tests/test_frontend_tsc_lint_v225.py`, 245 LOC, 7 tests) mirrors
the v2.19-WP02 mypy PIN structure with empty allow-list,
bidirectional stale-detection, and synthetic-bad teeth verified.
Closing baselines: backend **1459 P / 0 F / 7 skipped / 14 xfailed**
(+6 from new PIN; zero functional regressions), frontend **276 P /
0 F**, mypy **28 errors / 28 allow-list keys (0 LEGACY)**, **`npx
tsc --noEmit`: 0 errors (NEW PIN)**. v2.25 added 4 new forward
rules: (zz) type-bug fixes often hide latent runtime bugs; (aaa)
PIN mirror skill compounds across versions; (bbb)
`@pytest.mark.slow` is the right gate for any subprocess-shelling
PIN; (ccc) removing unused locals can shift unrelated lint
allow-list line numbers.

### Status framing

**v2.25 is a natural project-finished-typecheck endpoint.** Mypy at
PIN floor (28 keys, all upstream-blocked); tsc at 0 + PIN; vitest
276 P; pytest 1459 P. **Both type-channel floors PIN-protected.**
There is no more typecheck-PIN reduction work without external
dependency movement (Starlette / FastAPI / SQLAlchemy stub upgrades).
The remaining axes are either prophylactic (Bucket H), redundant
(parity wrapper pins per (tt)), or substantial-new-WP territory
(Bucket C C2 `Response.json()` tightening).

### Six shapes for v2.26

- **(a) PREVENTATIVE-HYGIENE — likely empty.** No latent shadows
  surfaced in v2.25 (no Python source edits in WP02; WP03 was a
  single frontend onClick + new test file). Cheap re-audit grep in
  v2.26-WP01; expectation empty. Drop bucket (a) if empty.
- **(b) UPSTREAM-WAIT — STRONGLY RECOMMENDED.** v2.25 closes both
  type channels. There is no more typecheck-PIN reduction work
  without external dependency movement. Monitor mypy / SQLAlchemy /
  Starlette / FastAPI releases. **This is the honest stop position.**
- **(c) PARITY EXPANSION continued — likely empty.** Re-enumerating
  Page<T>-shaped OpenAPI schemas with no TS counterpart yet:
  `Page_AgentActivityItem_`, `CursorPage_ProblemResponse_`,
  `Page_TicketAttachmentRead_`. TicketWatcher + TicketAttachment
  were the last "easy" net-new candidates and have landed.
  Likely empty unless a consumer upgrade is independently
  prioritised.
- **(d) `Response.json(): Promise<any>` → `unknown` + runtime
  parser sweep** (Bucket C C2 from v2.18 seed). **The only
  remaining substantial WP** if the user wants to keep going.
  ~30+ call sites across `frontend/src/api/`. Design WP territory
  (parser shape, error reporting, migration order). Would clear
  ~30 ts-any-lint entries IF those exist; otherwise prophylactic.
- **(e) DIRTY-TREE HOUSEKEEPING — should be empty.** v2.24-WP02
  cleared everything; v2.25 closed clean. Verify
  `git status --short | wc -l` post-closure-commit = 0.
- **(g) NEW: non-typecheck PIN sweeps** — e.g., bare-FastAPI lint
  (already at closed-set per v2.12-WP07), parseApiError sweep,
  catch-block lint. Most reached "all BY-DESIGN" in v2.22 recon.
  Re-audit if user pursues.

**Conditional carry-forwards:** Bucket A (C7, E3, E4, F3), Bucket B
(B1, B2), Bucket C (C1, C3, C4), Bucket R (R1 `_OFFENDER_ALLOWLIST`
extract — now even more compelling with **5 subprocess-shelling
lints** in the family). Act ONLY on triggering need.

**Recommend (b) UPSTREAM-WAIT as primary.** v2.25 is a clean
stopping point — both Python and TS type-channels at PIN-protected
floor. (d) is the only substantial remaining WP if the user wants to
keep going; everything else is prophylactic or upstream-blocked.

### v2.26 prompt seed (paste-ready)

> Proceed with v2.26 of the problem-bulletin ticketing system —
> **OR consider declaring v2.25 the natural project-finished-
> typecheck endpoint and stopping.** v2.25 retrospective + carry-
> forward backlog live at the bottom of
> `.claude/lessons-learned/ticketing-v2.25.md`. Baselines: backend
> **1459 P / 0 F / 7 skipped / 14 xfailed**, frontend **276 P / 0 F**,
> mypy **28 errors / 28 allow-list keys (0 LEGACY)**, frontend
> `npx tsc --noEmit`: **0 errors (NEW PIN at
> `tests/test_frontend_tsc_lint_v225.py`)**, WP05 parity PIN **17
> parametrize entries**, WP11 parity PIN **16 routes**. **v2.25 was
> the (f) tsc-noEmit triage version executed end-to-end — 76 → 0
> across 4 categorical commits + 1 real bug fix at
> `ProblemDetail.tsx:1052` (the retry button's `onClick={fetchProblem}`
> would have passed a truthy MouseEvent into the `showLoading`
> boolean slot, triggering the full-screen spinner on retry instead
> of the inline indicator).** **Both type channels are now at floor
> + PIN-protected.** v2.25 reached the same framework-residual mypy
> floor as v2.21/v2.22/v2.23/v2.24 (28 keys, upstream-blocked).
> Six shapes: **(a) PREVENTATIVE-HYGIENE — likely empty** (drop if
> WP01 grep empty); **(b) UPSTREAM-WAIT — STRONGLY RECOMMENDED**,
> the honest stop position now that both type-channel floors are
> PIN-protected; **(c) PARITY EXPANSION continued — likely empty**
> (no easy net-new candidates remain); **(d) `Response.json():
> Promise<any>` → `unknown` + runtime parser sweep** (Bucket C C2
> from v2.18 seed) — the only remaining substantial WP if the user
> wants to keep going (~30 call sites in `frontend/src/api/`);
> **(e) DIRTY-TREE HOUSEKEEPING — should be empty** (verify
> `git status --short | wc -l` = 0); **(g) non-typecheck PIN
> sweeps** — re-audit on triggering need only. **Recommend (b)
> UPSTREAM-WAIT as primary. v2.25 is a clean stopping point. (d)
> is the only substantial work remaining; everything else is
> prophylactic or upstream-blocked.** **Bucket H (likely empty):**
> H1 re-audit grep across `app/services/`. **Bucket R (cosmetic
> carry-forward):** R1 extract shared `_OFFENDER_ALLOWLIST` helper —
> now spans 5 subprocess-shelling lints (bare-catch, ts-any, pragma,
> typecheck-mypy, typecheck-tsc). **Bucket A** (C7, E3, E4, F3),
> **Bucket B** (B1, B2), **Bucket C** (C1, C3, C4) remain
> conditional carry-forwards — act ONLY on triggering need. Follow
> the sequential subagent loop pattern, TDD-first, one diagnosis
> doc per WP under `.claude/lessons-learned/v2.26-wpNN-diagnosis.md`.
> Append lessons to `.claude/lessons-learned/ticketing-v2.26.md`.
> **Forward rules carried from v2.15-v2.24:** (a)-(yy), 51 rules,
> see `ticketing-v2.24.md` close section. **Forward rules new from
> v2.25:** (zz) type-bug fixes often hide latent runtime bugs —
> when fixing a type error, check whether the fix changes runtime
> behaviour; the `ProblemDetail.tsx:1052` case showed TS catching a
> real UX regression (truthy MouseEvent → `showLoading=true` →
> full-screen spinner on retry); pair the fix with a vitest
> regression test where feasible; generalises to any
> callback-passing-event-as-data scenario. (aaa) PIN mirror skill
> compounds across versions — v2.25-WP03b ported the mypy PIN's
> parser/allowlist/self-test/marker structure to TS in one WP by
> treating the precedent as authoritative template (subprocess shim,
> error parsing, bidirectional staleness, `RUN_X_SELFTEST=1` opt-in,
> `path:line:errcode` keying); the PIN's parser shape transfers
> between language ecosystems; pair with (xx); refines (rr) and
> (uu). (bbb) `@pytest.mark.slow` is the right gate for any
> subprocess-shelling PIN — both mypy and tsc PINs are
> `@pytest.mark.slow`-tagged from day one; without it dev loops
> grind, with it CI still enforces the floor; the marker is part
> of the PIN contract, not optional polish; refines (mm) and (ff).
> (ccc) removing unused locals can shift unrelated lint allow-list
> line numbers — WP02d's `armTotal` removal shifted a catch-block
> lint pin from 354 → 350; lockstep allow-list update in the same
> commit kept tests green; sweep WPs touching files referenced by
> line-number-keyed allow-lists must include the allow-list update;
> refines (t) and (qq).
> Do NOT reintroduce the `_v1_deferred.py` skip-hook — per-test
> deferral uses plain pytest markers.

**Cumulative forward rules total: 55 (a-ccc).** v2.25 added 4 new
rules (zz, aaa, bbb, ccc) to the 51 carried from v2.24 (a-yy).
