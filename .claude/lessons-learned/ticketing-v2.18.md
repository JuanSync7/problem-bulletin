# v2.18 ticketing — lessons learned

Companion to `ticketing-v2.17.md`. v2.18 was the **type-tightening sweep
version** paired with v2.17's preventive-hardening PINs. v2.17 closed
with two new structural lints pinned (TS `any` / `@ts-*` at WP02,
Python `# type: ignore` / `# noqa` at WP03) and a small honest-classified
backlog: **7 LEGACY allow-list entries** (6 TS + 1 Python) marked for
type-tightening. v2.18 swept ALL 7 — the lint allow-lists now contain
ONLY BY-DESIGN entries.

The mechanics mirror v2.15-WP03's sweep-after-pin pattern, generalised
across two languages: each LEGACY entry deleted from its
`_OFFENDER_ALLOWLIST` as its type was tightened; stale-entry detection
in both lint modules enforced the per-entry workflow both directions
(cannot delete an allow-list row without removing the offender, cannot
remove the offender without deleting the row — either drift fails the
lint). 3 sweep WPs + baseline + closure = 5 WPs.

**Closing baselines:** backend **1438 P / 0 F / 5 skipped / 14 xfailed**
(unchanged — sweeps were type-only, no behaviour shift). Frontend
**269 → 276 P / 0 F** (+7 from WP03's `LeaderboardNormaliser.test.ts`
covering the new discriminated-union normaliser per track variant).

---

## v2.18-WP01 (G0) — baseline verify

Backend: **1438 P / 0 F / 5 skipped / 14 xfailed**. Frontend:
**269 P / 0 F**. v2.17 close confirmed as the regression anchor.

All 7 LEGACY allow-list entries grep-confirmed present going into WP02:

- TS allow-list (`frontend/src/__tests__/ts_any_lint.test.ts`): 6
  entries — `Leaderboard.tsx:64`, `:65` (L1, but renumbered post-WP02
  cluster as L3 in the sweep packaging); `ProblemDetail.tsx:530, 534,
  1156, 1207` (L1 + L2 pairs).
- Python allow-list (`tests/test_type_ignore_lint_wp03_v217.py`): 1
  entry — `app/routes/notifications_v1.py:177` (L4).

Bucket A (C7, E3, E4, F3) and Bucket B (B1, B2) — still conditional;
no triggering need fired during v2.18.

No code or test changes in WP01.

---

## v2.18-WP02 — L1 + L2 ProblemDetail `any` → typed (sweep)

**Pre-state.** Four LEGACY `any` sites in
`frontend/src/pages/ProblemDetail.tsx`:

- **L1 editSuggestions pair (530 + 1156)** — `useState<any[]>` + paired
  `.map` callsite.
- **L2 attachments pair (534 + 1207)** — same shape: `useState<any[]>` +
  `.map`.

**Approach — file-local OpenAPI mirror interfaces.** Two new
file-local interfaces, `EditSuggestionRead` and `AttachmentRead`,
mirror 1:1 the backend pydantic shapes
(`app/routes/edit_suggestions.py::EditSuggestionResponse` and
`app/routes/attachments.py::AttachmentResponse`). The v2.17 allow-list
justification had named these aspirational types; no actual `*Read`
modules existed in `frontend/src/api/` (the directory carries only
`*DTO` interfaces). Inlining the interfaces in the consumer page is
the lightweight option vs promoting to `frontend/src/api/*.ts`.

**Consumer-side adaptation — none.** Every existing `.map` callsite's
field access (`s.id`, `s.author?.display_name`, `s.suggested_description`,
`att.content_type?.startsWith("image/")`, etc.) matched the new
interface shapes exactly. No narrowing or new defensive guards needed —
the previous `any` was a load-bearing nothing; tightening was pure.

**Trade-off recorded — parity-lint coverage gap.** These two
interfaces are file-local; they are NOT picked up by
`tests/test_openapi_ts_parity_wp11.py` (which scans
`frontend/src/api/*.ts`). If the backend schemas drift, the parity lint
won't catch it. A future WP could promote them to
`frontend/src/api/editSuggestions.ts` + `frontend/src/api/attachments.ts`
and add parity entries; logged as a follow-up, not a blocker.

**Line-shift collateral — sibling allow-list pin bumped.** The ~34
lines of interface declarations shifted every line in `ProblemDetail.tsx`
below by the same offset. The sibling
`frontend/src/pages/__tests__/catch_block_lint.test.ts` pins one
BY-DESIGN bare-catch in this file by exact line number; bumped from
931 → 965 (and the comment cross-reference at line 87). No other
line-pinned allow-lists were affected. This is the failure mode of
line-number-keyed allow-lists: an unrelated addition in the same file
forces a stale-entry re-pin even though the offender is unchanged.
Context-snippet or function-name anchoring would be more resilient.

**`Response.json(): Promise<any>` axis — uncaught.** `setEditSuggestions(await res.json())`
and `setAttachments(await res.json())` compile cleanly because
`Response.json()` returns `Promise<any>` in `lib.dom.d.ts` — the unsafe
assignment crosses the network boundary unchanged. The structural
lint catches `any` in DECLARATIONS (state types, function params,
generics), not return-type-propagated assignment. Every
`setX(await res.json())` callsite in the codebase is technically an
`any` hole. Logged as a future-sweep candidate: thread through
`unknown` + a runtime parser. Out of scope for L1/L2.

**Numbers.**

- Frontend: 269 P → 269 P (no new tests; tightening was pure-type).
- Backend: 1438 P (untouched).
- 4 LEGACY allow-list entries deleted (the four ProblemDetail rows).
- 1 sibling pin bumped (catch_block_lint 931 → 965).

---

## v2.18-WP03 — L3 Leaderboard `any[]` → discriminated union (sweep)

**Pre-state.** Two LEGACY `any` sites in
`frontend/src/pages/Leaderboard.tsx:64, 65`: the `const raw: any[]`
holding the response payload and the paired `.map(...)` ad-hoc
normaliser. v2.17-WP02's diagnosis named this a discriminated-union
sweep target.

**Backend payload shape — `extra="allow"` ferries the variant.**
`app/services/leaderboard.py` emits two row shapes keyed on the
request `track` parameter:

| Track       | Score column     | Row dict keys                                        |
|-------------|------------------|------------------------------------------------------|
| `solvers`   | `accepted_count` | `user_id`, `display_name`, `accepted_count`, `rank`  |
| `reporters` | `upstar_count`   | `user_id`, `display_name`, `upstar_count`, `rank`    |

These are wrapped in `LeaderboardResponse` where the inner
`LeaderboardEntry` carries `model_config = ConfigDict(extra="allow")`
so the track-specific score key flows through. No per-row discriminator
field is emitted. **The natural discriminator is the request `track`
arg, NOT a runtime tag on the row.**

**Union shape landed.**

```ts
interface LeaderboardEntryBase {
  user_id?: string; userId?: string;
  display_name?: string; displayName?: string;
  rank?: number;
}
interface LeaderboardSolverRaw   extends LeaderboardEntryBase { accepted_count?: number; }
interface LeaderboardReporterRaw extends LeaderboardEntryBase { upstar_count?: number;   }
type     LeaderboardRawEntry = LeaderboardSolverRaw | LeaderboardReporterRaw;
```

All score-source fields are optional — defensively tolerates missing
keys without falling back to `any`. camelCase aliases retained for
legacy in-flight payloads.

**Normaliser with exhaustiveness check.**

```ts
normalizeLeaderboardEntry(raw, track, index) → LeaderboardEntry
```

Switch on the `track` argument (not row-shape sniffing). `solvers` →
`score = raw.accepted_count ?? 0`; `reporters` → `score = raw.upstar_count ?? 0`;
`default` branch holds `const _exhaustive: never = track` so a new track
added without a normaliser arm fails compile.

**`any` hid a phantom branch.** The previous ad-hoc normaliser
included a `e.problem_count` fallback. `problem_count` is NOT emitted
by any current backend service. The union-narrowing forced the
discovery: the field was unreachable dead code. Dropped cleanly. If a
future track ever introduces it, the `never` exhaustiveness will force
the design decision front-and-centre instead of silently working.

**Numbers.**

- Frontend: 269 → **276 P** (+7 from `LeaderboardNormaliser.test.ts`
  covering both track variants, missing-key tolerance, camelCase
  alias path, and the exhaustiveness escape).
- Backend: 1438 P (untouched).
- 2 LEGACY allow-list entries deleted (the Leaderboard pair).

**Deliverables.**

- `frontend/src/pages/Leaderboard.tsx` — union + normaliser; 2 `any`
  removed.
- `frontend/src/pages/__tests__/LeaderboardNormaliser.test.ts` — 7
  new tests.
- `frontend/src/__tests__/ts_any_lint.test.ts` — 2 allow-list rows
  deleted + WP03 closure comment.

---

## v2.18-WP04 — L4 notifications_v1.py SQL-row enum narrowing (sweep)

**Pre-state.** One LEGACY `# type: ignore[arg-type]` site:
`app/routes/notifications_v1.py:177`, in the orphan-actor synthesis
branch of `GET /api/v1/notifications`. When `_hydrate_actors` returns
no `PersonRef` for `(row.actor_type, row.actor_id)` (deleted user or
agent), the route constructs a stand-in
`PersonRef(kind=row.actor_type, ...)`. `PersonRef.kind` is
`Literal["user", "agent"]`; `row.actor_type` (from
`TicketNotification`) is `Mapped[str]` non-nullable plain Text with a
DB-level check constraint enforcing `IN ('user','agent')`.

**LEGACY justification was inaccurate.** The original v2.17-WP03
allow-list comment described `row.actor_type` as `Optional[str]`. It
is not — it's `Mapped[str]` non-nullable. The narrowing problem (`str`
→ `Literal["user", "agent"]`) is real, but the original framing was
wrong. Pattern: re-validate LEGACY justifications at sweep time;
original author's framing may be inaccurate even when the underlying
offender is real.

**Approach chosen — `typing.cast()`.** This is the only callsite in
the file that needs the narrowing — surrounding code uses
`row.actor_type` as a plain string (tuple key, line 173). Migrating
`actor_type` to `Mapped[ActorType]` enum across the model + migrations
+ every consumer (sibling `actor_type` columns on `TicketTransition`,
`AuditLogEvent`, `Ticket`) is disproportionate to one fallback line.
The DB check constraint already guarantees the runtime invariant;
`cast()` documents the assertion without changing behaviour.

```python
kind=cast(Literal["user", "agent"], row.actor_type),
```

(`cast` added to the file's `from typing import ...` line.)

**Typecheck-as-CI gap surfaced.** The repo has no `[tool.mypy]` in
`pyproject.toml` and no `mypy.ini`. There is no typecheck command
wired into CI. `cast()` correctness was eyeball-verified, not
machine-verified. The structural-lint pin (line-keyed `# type: ignore`
detection) catches the SYMPTOM but not the underlying type errors.
This is the strongest v2.19+ signal: wire pyright or mypy into CI so
type-level invariants get machine-enforced. Approximately 15-20
existing BY-DESIGN allow-list residents would surface immediately as
type-checker errors, giving v2.19 the same shape v2.17 had — a fresh
PIN with honest BY-DESIGN/LEGACY classification.

**Numbers.**

- Backend: 1438 P (unchanged — `cast()` is a no-op at runtime).
- Frontend: 276 P (untouched).
- 1 LEGACY allow-list entry deleted (the only one in the Python
  pragma allow-list); LEGACY section header retained empty for
  future-proofing.

---

## v2.18-WP05 (closure) — retrospective + v2.19 seed

This document. Zero code touched.

---

## v2.18 retrospective

### Headline numbers

- **Backend baseline:** 1438 P / 0 F / 5 skipped / 14 xfailed (v2.17
  close).
- **Backend final:** **1438 P / 0 F / 5 skipped / 14 xfailed**
  (unchanged — sweeps were pure-type, no behaviour shift).
- **Net backend delta:** +0.
- **Frontend baseline:** 269 P / 0 F (v2.17 close).
- **Frontend final:** **276 P / 0 F**.
- **Net frontend delta:** +7 (WP03 `LeaderboardNormaliser.test.ts`).
- **LEGACY allow-list entries swept:** **7 / 7** (6 TS + 1 Python).
  Both allow-lists now contain ONLY BY-DESIGN entries.
- **TS `any` BY-DESIGN residents:** 7 (all in `frontend/src/mock/**` —
  demo-mode dispatcher + fixtures). Unchanged from v2.17.
- **Python pragma BY-DESIGN residents:** 33 (SQLAlchemy registry
  barrel F401s, broad-catch boundaries, circular-import locals,
  TYPE_CHECKING shims, runtime-assigned attrs). Unchanged from v2.17.
- **`@ts-*` directive count in `frontend/src/` non-test surface:** 0
  (still locked in from v2.17-WP02 PIN).
- **Production code touched:** 3 files (`Leaderboard.tsx`,
  `ProblemDetail.tsx`, `notifications_v1.py`). All three were the
  named LEGACY offenders.
- **Production bugs caught and fixed:** 1 minor — phantom
  `problem_count` fallback in Leaderboard normaliser (unreachable
  dead code; surfaced by type-tightening, dropped).
- **Production regressions introduced:** zero.

### WPs shipped

| WP | Bucket | Summary | Test delta |
|---|---|---|---|
| WP01 | G0 | Baseline verify (1438 P backend / 269 P frontend). 7 LEGACY allow-list entries grep-confirmed present. | ±0 |
| WP02 | sweep (L1+L2) | `ProblemDetail.tsx` editSuggestions → `EditSuggestionRead[]` and attachments → `AttachmentRead[]` via file-local OpenAPI mirror interfaces. 4 LEGACY allow-list entries deleted. Sibling `catch_block_lint` pin bumped 931 → 965 from line-shift. | ±0 |
| WP03 | sweep (L3) | `Leaderboard.tsx` `raw: any[]` → discriminated `LeaderboardRawEntry` union (`LeaderboardSolverRaw | LeaderboardReporterRaw`) keyed on request `track`. Added `normalizeLeaderboardEntry` helper with `never` exhaustiveness check. Phantom `problem_count` fallback dropped. 2 LEGACY allow-list entries deleted. | +7 (269→276) |
| WP04 | sweep (L4) | `notifications_v1.py:177` `# type: ignore[arg-type]` removed via `cast(Literal["user", "agent"], row.actor_type)`. Original LEGACY justification (claimed `Optional[str]`) re-validated and corrected — column is `Mapped[str]` non-nullable. 1 LEGACY allow-list entry deleted. Surfaced absence of typecheck-as-CI gate. | ±0 |
| WP05 | closure | Retrospective + v2.19 seed (this doc). | ±0 |

### Cross-cutting lessons

1. **Sweep-after-pin generalises both directions — stale-entry
   detection enforces the per-entry workflow.** v2.17 pinned the
   classes; v2.18 swept the LEGACY entries one by one. The stale-entry
   branches in both lint modules ran both ways: deleting an allow-list
   row without removing the offender failed the lint (offender now
   unjustified); removing the offender without deleting the row also
   failed (orphan allow-list entry). The maintainer cannot drift the
   allow-list past the code in either direction. Pattern: when
   designing a structural lint with an allow-list, ALWAYS implement
   stale-entry detection alongside offender detection — it's what
   makes the sweep auditable per-step.

2. **Line-number-keyed allow-lists are fragile against unrelated
   additions in the same file.** WP02 added ~34 lines of interface
   declarations near the top of `ProblemDetail.tsx`, shifting every
   line below by the same offset. A sibling `catch_block_lint`
   BY-DESIGN pin had to be bumped 931 → 965 even though the underlying
   offender was unchanged. The lint correctly fired (stale-detection
   working as designed), but the bump was busywork driven by a
   cosmetic neighbour. Pattern: for future allow-list designs,
   consider context-snippet anchoring (match against a short line
   excerpt or surrounding function name) instead of bare line numbers
   — file-local edits unrelated to the offender shouldn't trigger
   re-pins.

3. **Re-validate LEGACY justifications at sweep time — original
   framing may be inaccurate.** WP04's LEGACY entry described
   `row.actor_type` as `Optional[str]`. The column is actually
   `Mapped[str]` non-nullable. The narrowing problem was real
   (`str` → `Literal["user", "agent"]`) but the framing was wrong.
   Acting on the original framing alone would have led to a different
   (and unnecessary) fix. Pattern: when sweeping a LEGACY entry, treat
   the justification as a hint, not a spec — re-derive the actual
   types at the callsite before choosing a fix.

4. **`Response.json(): Promise<any>` is an unsignal-able `any` axis —
   declaration lints catch declarations, not return-type
   propagation.** Across WP02, the structural `ts_any_lint` correctly
   flagged the `useState<any[]>` declarations but NOT the
   `setX(await res.json())` callsites — `Response.json()` returns
   `Promise<any>` per `lib.dom.d.ts`, and the unsafe value crosses the
   network boundary into a typed slot via assignment-context inference,
   which is invisible to an AST-level `AnyKeyword` walk. Every
   `setX(await res.json())` in the frontend is technically an `any`
   hole. Pattern: declaration-level lints miss return-type
   propagation; a future sweep candidate is `unknown` + a runtime
   parser at the fetch boundary. The lint's blind spot is real and
   documented for v2.19+.

5. **When backend uses `extra="allow"`, the frontend discriminated
   union must key from REQUEST CONTEXT, not response shape.** WP03's
   backend `LeaderboardEntry` carries `model_config = ConfigDict(extra="allow")`
   to ferry track-specific score columns. There is no per-row
   discriminator field. The frontend cannot sniff the variant at
   runtime — the discriminator must come from the caller's request
   knowledge (the `track` argument passed to `fetchLeaderboard`).
   Pattern: any backend schema using `extra="allow"` for variant
   payloads forces the frontend union to be closed from caller-side
   knowledge; design the frontend API surface to require the
   variant-selecting argument explicitly so it's available to the
   normaliser.

6. **`any` hides dead branches — type-tightening surfaces phantom
   fallbacks.** WP03's original normaliser had an
   `e.score ?? e.accepted_count ?? e.upstar_count ?? e.problem_count`
   fallback chain. `problem_count` is not emitted by any current
   backend service — it was unreachable. Under `any`, no compiler
   could see this; under the discriminated union, the unused field
   stood out and was dropped. Pattern: when migrating off `any`,
   expect to find dead branches; the tightening is itself a
   dead-code audit on the consumer side.

7. **File-local OpenAPI mirror interfaces are a lightweight tightening
   tool — promoting to a parity-checked module is a follow-up
   choice, not a blocker.** WP02 introduced `EditSuggestionRead` and
   `AttachmentRead` inline in `ProblemDetail.tsx`. They are NOT in
   `frontend/src/api/*.ts` and therefore NOT picked up by the v2.12-WP11
   parity lint. The trade-off is explicit: inlining is fast and
   removes the immediate `any` debt; promoting earns parity-lint
   coverage at the cost of a new module + parity-entry. Pattern: for
   single-consumer interfaces, inline-local is the right first step;
   promote only when a second consumer surfaces (mirrors C7 / E3 / E4
   second-consumer thresholds from Bucket A).

### What stayed deferred (carry to v2.19)

- **Bucket A (C7, E3, E4, F3)** — still conditional v2.11
  carry-forwards (`decode_email_body` helper, KindPill 7th surface,
  `useSearchV2` ergonomic follow-ups, TipTap second-consumer
  extraction). No triggering need fired during v2.18.
- **Bucket B (B1, B2)** — still conditional v2.13 carry-forwards
  (per-arm `refresh_total` opt-in syntax; WP05 OpenAPI↔TS parser
  expansion). No triggering need fired during v2.18.
- **File-local `*Read` interfaces — promote to `frontend/src/api/`?**
  v2.18-WP02's `EditSuggestionRead` + `AttachmentRead` are file-local.
  Promoting them earns parity-lint coverage but adds new modules.
  Defer unless a second consumer surfaces.
- **`Response.json(): Promise<any>` → `unknown` + runtime parser
  sweep.** Every `setX(await res.json())` callsite is an `any` hole
  the declaration-lint cannot catch. v2.19+ candidate.
- **`actor_type` `Mapped[str]` → `Mapped[ActorType]` enum-backed
  column migration.** Touches `TicketNotification`, `TicketTransition`,
  `AuditLogEvent`, `Ticket`. The WP04 `cast()` can be deleted at that
  time. Disproportionate to a single callsite today; v2.19+ candidate.
- **Typecheck-as-CI gate (mypy or pyright).** No `[tool.mypy]` in
  `pyproject.toml`, no `mypy.ini`, no CI wiring. WP04's `cast()`
  correctness was eyeball-verified, not machine-verified.
  **Strongest v2.19 signal** — recommended as the v2.19 preventive-
  hardening PIN. See seed below.
- **Line-number-keyed allow-list anchoring — promote to context-snippet
  / function-name anchoring.** Surfaced as a design lesson, not a
  blocker. v2.19+ design choice.
- **40 BY-DESIGN allow-list residents (7 TS + 33 Python).**
  PERMANENTLY documented with `BY-DESIGN:` rationale per entry. They
  will not be re-evaluated unless touched for product reasons.

### Files touched (rough stats)

- **Production code (`app/`):** 1 file — `app/routes/notifications_v1.py`
  (cast + import).
- **Production code (`frontend/src/`):** 2 files —
  `frontend/src/pages/ProblemDetail.tsx` (interfaces + state types
  + map callbacks) and `frontend/src/pages/Leaderboard.tsx` (union +
  normaliser + Track export).
- **Alembic (`alembic/versions/`):** 0 files.
- **Lint allow-lists:** 2 files (both shrunk) —
  `frontend/src/__tests__/ts_any_lint.test.ts` (6 LEGACY rows
  deleted), `tests/test_type_ignore_lint_wp03_v217.py` (1 LEGACY row
  deleted). 1 sibling lint bumped:
  `frontend/src/pages/__tests__/catch_block_lint.test.ts` (line 931 →
  965 from WP02 line-shift).
- **Test code (`frontend/`):** 1 new file —
  `frontend/src/pages/__tests__/LeaderboardNormaliser.test.ts` (+7
  tests covering both track variants, missing-key tolerance, camelCase
  alias, exhaustiveness).
- **Docs (`.claude/lessons-learned/`):** 4 per-WP diagnosis files
  (`v2.18-wp01-diagnosis.md` through `v2.18-wp04-diagnosis.md`) + this
  retrospective.

---

## v2.19 starting prompt seed

v2.18 closed as a **type-tightening sweep version**: all 7 LEGACY
allow-list entries (6 TS + 1 Python) from v2.17's PINs cleared. Both
lint allow-lists now contain ONLY BY-DESIGN entries. No production
regressions, +7 frontend tests from WP03's normaliser, zero backend
delta. The sweep-after-pin pattern executed cleanly across two
languages — stale-entry detection enforced every per-entry workflow
step both directions.

v2.19 has **no concrete LEGACY backlog handed forward**. The choice
is between (a) opportunistic-only — pick up Bucket A / Bucket B
carry-forwards only on triggering second-consumer need; or
(b) **wire a Python typecheck-as-CI gate** (pyright or mypy) — a fresh
preventive-hardening PIN surfaced from v2.18-WP04 as a real gap. The
WP04 `cast()` was eyeball-verified because no typecheck command is
wired into CI; `# type: ignore` allow-list catches the SYMPTOM (the
pragma) but not the underlying type errors. Approximately 15-20 of
the 33 BY-DESIGN Python pragma residents would surface immediately
as type-checker errors under pyright/mypy, giving v2.19 the same
shape v2.17 had — a fresh PIN with honest BY-DESIGN / LEGACY
classification of an existing offender set.

**Recommend (b) as v2.19 — typecheck-as-CI PIN.** It is the
strongest signal from this version's findings, has a known-shape
offender set already documented (the 33 BY-DESIGN Python pragmas),
and mirrors v2.17's preventive-hardening shape but on the
type-checker axis rather than the comment-pragma axis. The lint
catches the lint-skipper; the typecheck catches what the lint-skipper
was hiding. After the PIN ships and honestly classifies its
offenders, v2.20 inherits the sweep backlog (if any) — the same
v2.17 → v2.18 cycle that just ran.

### v2.19 backlog

#### Bucket P — Preventive PIN (PRIMARY v2.19 work, RECOMMENDED option (b))

P1. **Wire pyright (or mypy) into CI as a structural-lint surface.**
    Pick one type-checker; add a `[tool.pyright]` (or `[tool.mypy]`)
    config to `pyproject.toml`; add a pytest-runnable shim (e.g.
    `tests/test_typecheck_lint_v219.py`) that invokes the checker on
    `app/**/*.py` and compares against an `_OFFENDER_ALLOWLIST` of
    known errors with `BY-DESIGN:` / `LEGACY:` justifications. Apply
    the same stable-allow-list shape proven in v2.17-WP02 / WP03:
    per-`path:line:errcode` keying, stale-entry detection both
    directions. Honest classification expected — ~15-20 LEGACY
    residents in real terms, mostly SQLAlchemy ORM `attr-defined`
    surfaces, Pydantic-v2 model-rebuild edge cases, and runtime-
    assigned attrs already flagged by the `# type: ignore` PIN.
    The single v2.18-WP04 `cast()` is also a candidate to verify
    end-to-end (the cast SHOULD be no-op under a working typecheck).

#### Bucket A — Conditional v2.11 carry-forwards (act only on triggering need)

A1. **C7 — `decode_email_body` helper.** Pick up only on a second
    QP-wrap consumer.
A2. **E3 — KindPill 7th surface.** Pick up when a real consumer
    surfaces.
A3. **E4 — `useSearchV2` ergonomic follow-ups.** Pick up when a
    second consumer surfaces.
A4. **F3 — TipTap second-consumer extraction.** Pick up when a
    second editor surface lands.

#### Bucket B — Conditional v2.13 carry-forwards

B1. **Per-arm `refresh_total` opt-in syntax** (option (a) from
    v2.13-WP06). Wire-shape change only. Pick up if a real user need
    surfaces.
B2. **WP05 OpenAPI↔TS parser expansion** — nested generics,
    intersection types, multi-param generics, generic type aliases,
    mapped/conditional, default generic params. Pick up when the
    first `frontend/src/api/*.ts` consumer needs one.

#### Bucket C — v2.18 surfaced candidates (conditional)

C1. **Promote `EditSuggestionRead` / `AttachmentRead` to
    `frontend/src/api/*.ts`** with parity-lint entries. Pick up when
    a second consumer surfaces.
C2. **`Response.json(): Promise<any>` → `unknown` + runtime parser
    sweep.** Every `setX(await res.json())` callsite is an `any`
    hole; declaration-lint blind. Significant sweep — schedule only
    after Bucket P closes (typecheck-as-CI will help quantify).
C3. **`actor_type` `Mapped[str]` → `Mapped[ActorType]` enum-backed
    column migration.** Touches `TicketNotification`,
    `TicketTransition`, `AuditLogEvent`, `Ticket`. Disproportionate
    to today's single callsite; pick up if a second narrowing site
    surfaces or if Bucket P flags multiple `actor_type` mismatches.
C4. **Line-number-keyed allow-list anchoring** — design follow-up:
    promote to context-snippet or function-name anchoring across the
    bare-catch, ts-any, and pragma lints to reduce line-shift
    churn. Implementation choice, not a blocker.

### v2.19 prompt seed (paste-ready)

> Proceed with v2.19 of the problem-bulletin ticketing system.
> v2.18 retrospective + carry-forward backlog live at the bottom of
> `.claude/lessons-learned/ticketing-v2.18.md`. Baselines: backend
> **1438 P / 0 F / 5 skipped / 14 xfailed**, frontend **276 P / 0 F**.
> **v2.18 was the type-tightening sweep version paired with v2.17's
> preventive-hardening PINs — all 7 LEGACY allow-list entries (6 TS
> + 1 Python) cleared cleanly via sweep-after-pin. Both lint
> allow-lists now contain ONLY BY-DESIGN entries. v2.19 has NO
> concrete LEGACY backlog handed forward.** Choose one of two
> shapes: (a) opportunistic-only — Bucket A / B / C carry-forwards
> only on triggering second-consumer need; or **(b) wire a Python
> typecheck-as-CI gate (pyright or mypy) as a fresh preventive-
> hardening PIN — RECOMMENDED.** WP04 surfaced this as a real gap:
> the `# type: ignore` PIN catches the pragma SYMPTOM but no
> typecheck verifies the underlying type. Approximately 15-20
> existing BY-DESIGN residents would surface as type-checker errors,
> giving v2.19 the same shape v2.17 had — a fresh PIN with honest
> BY-DESIGN / LEGACY classification on a known-shape offender set.
> **Bucket P (PRIMARY if option b):** P1 typecheck-as-CI PIN — pick
> pyright or mypy; add config to `pyproject.toml`; add pytest shim
> (e.g. `tests/test_typecheck_lint_v219.py`) with allow-list shape
> mirroring v2.17-WP02 / WP03 (per-`path:line:errcode` keying,
> stale-entry detection both directions, BY-DESIGN / LEGACY
> justifications inline). Honest classification expected. **Bucket
> A** (C7, E3, E4, F3), **Bucket B** (B1, B2), and **Bucket C**
> (C1 `*Read` promotion; C2 `Response.json()` → `unknown` sweep;
> C3 `actor_type` enum column migration; C4 context-snippet allow-
> list anchoring) remain conditional carry-forwards — act ONLY on
> triggering need. Follow the sequential subagent loop pattern,
> TDD-first, one diagnosis doc per WP under
> `.claude/lessons-learned/v2.19-wpNN-diagnosis.md`. Append lessons
> to `.claude/lessons-learned/ticketing-v2.19.md`. **Forward rules
> carried from v2.15:** (a) lint-before-sweep when a class has
> known shape; (b) by-design enumeration at FIRST surfacing of any
> mixed-population class; (c) two state slots for pages with both
> load-failure and action-failure UX; (d) `PYTEST_CURRENT_TEST` is
> the canonical no-config test-mode sentinel — prefer over inventing
> a project-local flag; (e) audit metric exporters first when OTel
> noise surfaces. **Forward rules carried from v2.16:** (f)
> `pkgutil.walk_packages` + `warnings.simplefilter('error', ...)` is
> the audit primitive for any compile-time warning class; (g)
> per-file opt-in beats global mock shims for forward-compat flags;
> (h) `BY-DESIGN:` comments in allow-lists answer WHY, not WHERE —
> grep on `BY-DESIGN:` enumerates intentional exceptions; (i) honest
> classification beats stretch target; (j) forward-compat flags are
> forgiving but not free; (k) three Bucket-Z items is the soft
> ceiling per cosmetic version; (l) after a structural-debt version,
> schedule a cosmetic version to mop up compile-time / test-time
> noise. **Forward rules carried from v2.17:** (m) lint-before-sweep
> generalises to preventive-hardening — the PIN alone is load-
> bearing even without a scheduled sweep; (n) compiler-API pragma
> blindspot — pragmas (`@ts-ignore`, `# type: ignore`, `# noqa`)
> are NOT AST nodes in any language; bounded per-line regex over
> source text is the right primitive; (o) a 0-offender axis is its
> own success metric — when a class is already at 0, a PIN locks
> the invariant; (p) per-line dedupe in lint emission keeps allow-
> lists stable — collapse to `path:line` granularity, not
> `path:line:column` or per-match; (q) demo-mode / fixture /
> registry-barrel sites are legitimate BY-DESIGN allow-list residents
> — when a directory's whole purpose is to host the offending
> pattern, the entries are structural, not debt; (r) `r"""..."""` is
> repo-canonical for any docstring documenting escape / regex / LIKE
> / shell / pragma syntax. **Forward rules new from v2.18:** (s)
> sweep-after-pin executes cleanly when stale-entry detection runs
> both directions — deleting an allow-list row without removing the
> offender fails the lint, removing the offender without deleting
> the row also fails; the maintainer cannot drift the allow-list
> past the code; ALWAYS implement bidirectional stale-detection
> alongside offender detection; (t) line-number-keyed allow-lists
> are fragile against unrelated additions in the same file — a
> cosmetic neighbour-edit forces a stale-entry re-pin even though
> the offender is unchanged; consider context-snippet or function-
> name anchoring for future allow-list designs; (u) re-validate
> LEGACY justifications at sweep time — the original author's
> framing may be inaccurate even when the underlying offender is
> real; treat the justification as a hint, not a spec; re-derive
> the actual types at the callsite before choosing a fix; (v)
> `Response.json(): Promise<any>` is an unsignal-able `any` axis —
> declaration-level lints catch declarations, not return-type
> propagation through assignment context; a future sweep candidate
> is `unknown` + a runtime parser at the fetch boundary; the
> declaration-lint blind spot is REAL and worth naming so future
> versions don't mistake the lint's silence for clean code; (w)
> when backend uses `extra="allow"` for variant payloads, the
> frontend discriminated union must key from REQUEST CONTEXT, not
> response shape — design the frontend API surface to require the
> variant-selecting argument explicitly so it's available to the
> normaliser; (x) `any` hides dead branches — type-tightening
> surfaces phantom fallbacks (e.g. `problem_count` slot no backend
> emits); when migrating off `any`, expect to find dead branches;
> the tightening is itself a dead-code audit on the consumer side;
> (y) file-local OpenAPI mirror interface is a lightweight
> tightening tool — promoting to a parity-checked module
> (`frontend/src/api/*.ts` with parity-lint entry) is a follow-up
> choice, not a blocker; for single-consumer interfaces, inline-
> local is the right first step; promote only when a second consumer
> surfaces (mirrors C7 / E3 / E4 second-consumer thresholds).
> Pre-flight any rename WP with `grep -rn` across `app/` AND
> `alembic/` before scoping. Encode numeric decision gates into
> perf-pass WP prompts. Do NOT reintroduce the `_v1_deferred.py`
> skip-hook — per-test deferral uses plain pytest markers.
