# v2.28 ticketing — lessons learned

Companion to `ticketing-v2.27.md`. v2.28 is a **recon-only closure
version** — WP01 enumerated the predicted forcing-function themes
((d'') GENERATED GUARDS and (c) PARITY NIBBLE) and found ZERO drift,
ZERO clean nibbles, and therefore **no WP02**. Per global instructions
("don't manufacture work") and per newly-promoted rule (hhh) below,
v2.28 ships zero source edits and exists as proof-by-exhaustion that
v2.27's recommendation of (b) UPSTREAM-WAIT was correct.

**Theme line:** Recon-only — no forcing function for (d'') or (c);
STOP at WP01.

**Closing baselines (UNCHANGED from v2.27 close — no code touched):**
backend **1459 P / 0 F / 7 skipped / 14 xfailed**, frontend **301 P
/ 0 F**, mypy **28 raw errors / 28 keys** (framework-residual floor),
**`npx tsc --noEmit`: 0 errors** (PIN at
`tests/test_frontend_tsc_lint_v225.py` held). WP05 parametrize: **17**
(unchanged). WP11 parametrize: **16** (unchanged). `git status`
clean (0 dirty pre-closure-commit).

**Commits:**
- WP01 — recon only, no commit (audit captured directly in this
  closure doc per recon-only pattern)
- Closure — this doc; SHA folded post-commit

---

## v2.28-WP01 — recon (no commit)

Backend **1459 P**, frontend **301 P**, mypy 28, tsc-noEmit 0 — all
match v2.27 close exactly. Two predicted themes audited:

### Theme (d'') GENERATED GUARDS — backend-Pydantic-vs-TS drift audit

Per rule (fff), enumerated every `parseJson<T>` callsite in
`frontend/src/api/` and confirmed each TS interface against the
corresponding backend Pydantic schema. **Result: zero drift across
all 10 sites.** The WP11 parity PIN (16 routes) already covers every
flat-parseable interface; the 2 sites that are not WP11-pinned are
unpinnable by design (escape hatches on both sides).

Drift-audit summary table (for future versions to re-derive without
redoing the recon):

| Site | TS type | Backend schema | WP11-pinned? | Drift? | Notes |
|------|---------|----------------|--------------|--------|-------|
| `audit.ts` (activity feed) | `ActivityEntry`, `ActivityPage` | `ActivityItem`, `Page[ActivityItem]` | YES | none | guard wired v2.27 |
| `users.ts` (handle update) | `UpdateHandleResponse` | `UserHandleResponse` | YES (post v2.27) | none | drift fixed in v2.27 |
| `users.ts:59` (error body) | `unknown` | server-error envelope | n/a (envelope) | n/a | unknown-by-design |
| `sprints.ts` | bucket-i generic | `SprintRead`, `Page[SprintRead]` | YES | none | |
| `people.ts` | bucket-i generic | `PersonRead`, `Page[PersonRead]` | YES | none | |
| `tickets.ts` | bucket-i generic | `TicketDTO` (escape hatch) | NO — unpinnable | none | TicketDTO is permissive-on-both-sides |
| `notifications.ts` | bucket-i generic | `NotificationRead`, `Page[NotificationRead]` | YES | none | |
| `projects.ts` | bucket-i generic | `ProjectRead`, `Page[ProjectRead]` | YES | none | |
| `auditLog.ts` | bucket-i generic | `AuditLogRead`, `Page[AuditLogRead]` | YES | none | |
| `search.ts` | `SearchV2Response` | `SearchV2Response` (union/discriminator) | NO — unpinnable | none | permissive-on-both-sides; seam-contracted |

**Bottom line:** the JSON-parse seam from v2.26-WP02 + the guards
from v2.27-WP02 + the WP11 parity PIN collectively seal the drift
surface for every flat-parseable interface. The 2 unpinned sites are
`TicketDTO` and `SearchV2Response`, both of which are **permissive on
both sides** — backend emits a union/discriminator/escape-hatch shape
and TS consumes via a matching escape hatch. Codegen would NOT
improve coverage here; it would just regenerate the same permissive
shape from the same OpenAPI input. Promoted as part of rule (hhh)
below: **distinguish "permissive-on-both-sides" PIN gaps from
"missing-coverage" PIN gaps — codegen only helps the latter.**

### Theme (c) PARITY NIBBLE — TicketRead and LinkRead/LinkDTO

Re-audited the two pre-flagged marginal parity candidates from v2.26
and v2.27 seeds:

- **`TicketRead`** — still skip-listed for the same **structural
  tautology** reason that's held since v2.14. The Pydantic schema is
  generated from the SQLAlchemy ORM via a `model_config` direct
  passthrough; adding a WP11 parity entry would assert "the schema
  matches itself". Reason unchanged from v2.27 close. Not a nibble.
- **`LinkRead` / `LinkDTO`** — share a name only. Backend `LinkRead`
  is a relationship-link ORM read schema (source/target ticket IDs,
  link_kind, created_at). Frontend `LinkDTO` is a rich-text-editor
  hyperlink shape (href, text, target). Pinning them via WP11 would
  require real parser work to extract a shared sub-shape that doesn't
  exist; either schema can change independently and SHOULD, because
  they model different domain objects. Not a nibble — would require
  net-new contract work, which is product scope, not version-pipeline
  scope.

Both pre-flagged candidates dead-end. No clean (c) nibble exists.

### Conclusion

Neither (d'') nor (c) has a forcing function. Per rule (hhh)
(promoted in this version), STOP at WP01. No WP02. v2.27's
recommendation of (b) UPSTREAM-WAIT was correct; this version proves
it by exhaustion.

---

## v2.28 closure — what shipped

**Source edits:** ZERO. This is a deliberate recon-only version per
rule (hhh).

**Docs:**
- This closure doc (`ticketing-v2.28.md`) which absorbs the WP01
  recon findings inline (no separate `v2.28-wp01-diagnosis.md` —
  recon-only versions can fold WP01 into the closure doc).

**Tests:** unchanged. All four channels at PIN floor, identical to
v2.27 close.

**Quadruple at HEAD:** pytest **1459 P** / vitest **301 P** / mypy
**28** / tsc-noEmit **0** — verified at WP01 baseline and again at
closure.

---

## What didn't ship and why

**(d'') GENERATED GUARDS — DID NOT SHIP.** WP01 drift audit found
zero drift across all 10 `parseJson<T>` sites. Every
flat-parseable interface is already pinned by WP11 parity (16
routes). The 2 unpinned sites (`TicketDTO`, `SearchV2Response`) are
permissive-on-both-sides by design — codegen does not fix them
because there's nothing to fix. Shipping codegen tooling would
produce the same coverage set with no improvement, at the cost of
significant build-pipeline complexity (rule eee territory: seam
without teeth). The v2.27 seed condition ("≥1 more drift in
production telemetry or ≥5 bucket-i guards independently justified")
remains unmet. **Deferred — unconditional until external signal.**

**(c) PARITY NIBBLE — DID NOT SHIP.** Both marginal candidates
dead-end:
- `TicketRead` is a structural tautology (Pydantic-from-ORM
  passthrough; would assert "schema matches itself").
- `LinkRead` vs. `LinkDTO` share a name only; they model different
  domain objects (ORM relationship-link vs. rich-text hyperlink).

Neither would add safety; both would add LOC and review burden.
**Deferred — would require net-new contract work, which is product
scope.**

---

## Forward rules promoted

### (hhh) Recon-only closure is a valid version shape

**When a recon WP finds zero forcing function for the predicted
theme, STOP at WP01 with a closure doc. Do not manufacture WP02
scope.**

**Why:** v2.28-WP01 enumerated all 10 `parseJson<T>` sites, did the
backend-Pydantic-vs-TS drift audit per rule (fff), and found zero
drift. The two pre-flagged parity-nibble candidates (`TicketRead`,
`LinkRead`) were both structural dead-ends. Continuing into WP02
would have meant either (i) generating predicates that duplicate the
WP11 parity PIN's coverage or (ii) inventing a parity entry that
asserts nothing. Both are make-work — net LOC, net review burden,
zero net safety. The version-pipeline pattern allows thin recon-only
versions exactly so that an honest null result can be recorded
without manufacturing scope to justify the version slot.

**How to apply:**
- A version with `WP01 + closure` is a valid shape; the
  forward-rule catalogue still grows, the test floors still get
  re-verified, the v2.NN+1 seed still gets written.
- What does NOT happen is forced make-work that adds LOC without
  adding safety.
- Recon-only versions can fold WP01 findings directly into the
  closure doc rather than emitting a separate
  `v2.NN-wp01-diagnosis.md` — the audit table belongs in the
  retrospective so future versions can re-derive without redoing it.

**Sub-rule:** **distinguish "permissive-on-both-sides" PIN gaps from
"missing-coverage" PIN gaps.** A site that lacks a WP11 parity entry
is NOT automatically a codegen target. If backend AND frontend both
intentionally use escape-hatch shapes (union/discriminator/`unknown`),
codegen will regenerate the same permissive shape and add zero
safety. Codegen only helps **missing-coverage** gaps — where a flat
shape exists on both sides and the pin is absent only because nobody
wrote it. v2.28-WP01: `TicketDTO` and `SearchV2Response` are
permissive-on-both-sides, NOT missing-coverage. Codegen would not fix
them.

**Generalises to:** any recon WP across any layer. If you can't name
a forcing function after the audit completes, the honest move is to
close the version, promote the meta-rule, and wait.

---

**Cumulative forward rules: 59 → 60 (a-hhh).** v2.28 added 1 rule
(hhh) to the 59 carried from v2.27.

---

## Open conditional carry-forwards (UNCHANGED from v2.27)

- **Bucket A** (C7, E3, E4, F3) — conditional v2.11 carry-forwards.
- **Bucket B** (B1, B2) — conditional v2.13 carry-forwards.
- **Bucket C** (C1, C3, C4) — conditional v2.18 carry-forwards.
  Note: C2 was substantively closed in v2.27; only bucket-i
  `request<T>` helper guards remain, deferred to (d'') if pursued.
- **Bucket R cosmetic** — `_OFFENDER_ALLOWLIST` helper extract
  (v2.19 rule (ee)). Still 5 subprocess-shelling lints in the
  family; v2.28 added no new lints.
- **28 BY-DESIGN typecheck residents** — the genuine
  framework-residual floor. Unchanged from v2.21-v2.27 close.
  Re-evaluate every N versions per rule (kk).

---

## v2.29 starting prompt seed (paste-ready)

v2.28 closed as a **recon-only proof-by-exhaustion** that no internal
forcing function exists. v2.27's recommendation of (b) UPSTREAM-WAIT
was correct; v2.28's WP01 confirms it. **v2.29 should be a HARD STOP
absent an external signal.** Cumulative forward rules: **60 (a-hhh)**.

### PRIMARY: HARD STOP

**v2.29 should execute ONLY if an external signal appears:**
- **Production drift report** — a guard rejected a real payload, or
  a 4xx/5xx pattern points to envelope mismatch.
- **Upstream library release that mandates change** — FastAPI /
  Pydantic / SQLAlchemy major; React / Vite major; mypy / tsc
  major. Minor releases without forcing changes do NOT count.
- **User-reported bug that maps to one of the carry-forward
  buckets** — Bucket A / B / C / R entries become active ONLY if
  triggered by a real bug, not by their existence on the list.
- **New feature work** — note that feature work is NOT
  version-pipeline scope; that's product work and should land
  through the normal product flow, not as a vN.M+1 version.

### Carry-forward conditional buckets (verbatim from v2.25/v2.26/v2.27)

- **Bucket A** — C7, E3, E4, F3 (v2.11 carry-forwards).
- **Bucket B** — B1, B2 (v2.13 carry-forwards).
- **Bucket C** — C1, C3, C4 (v2.18 carry-forwards; C2 substantively
  closed in v2.27).
- **Bucket R** — R1 `_OFFENDER_ALLOWLIST` extract (v2.19; 5
  subprocess-shelling lints remain).
- **28 BY-DESIGN typecheck residents** — framework-residual floor.

Act ONLY on triggering need.

### Final recommendation

**WAIT FOR EXTERNAL SIGNAL.** A v2.29 invocation without one should
default to **repeating this v2.28 audit, expecting the same null
result, and closing as another recon-only version per rule (hhh).**
The fact that two consecutive versions (v2.28 and a hypothetical
v2.29-null) close recon-only is itself the strongest possible signal
that the version-pipeline has reached steady state, and the
appropriate next action is to STOP invoking the pipeline until an
external trigger arrives.

### v2.29 prompt seed (paste-ready)

> Proceed with v2.29 of the problem-bulletin ticketing system —
> **OR, more likely, decline to proceed.** v2.28 retrospective +
> carry-forward backlog live at the bottom of
> `.claude/lessons-learned/ticketing-v2.28.md`. Baselines: backend
> **1459 P / 0 F / 7 skipped / 14 xfailed**, frontend **301 P / 0 F**,
> mypy **28 errors / 28 allow-list keys (0 LEGACY)**, frontend
> `npx tsc --noEmit`: **0 errors (PIN at
> `tests/test_frontend_tsc_lint_v225.py`)**, WP05 parity PIN **17
> parametrize entries**, WP11 parity PIN **16 routes**. **v2.28 was
> a recon-only closure version — WP01 audited all 10 `parseJson<T>`
> sites for backend-vs-TS drift (rule fff) and found zero. Both
> pre-flagged parity-nibble candidates (`TicketRead`, `LinkRead`)
> are structural dead-ends. v2.28 shipped zero source edits per
> rule (hhh).** **Before doing anything, check for an external
> signal:** (1) production drift report, (2) upstream major
> release that mandates change, (3) user-reported bug that maps to
> Bucket A/B/C/R, (4) net-new feature work (which is product, not
> version-pipeline). **If no external signal: default to repeating
> v2.28's recon-only audit and closing as another null version per
> rule (hhh).** **If external signal present:** dispatch the matching
> WP per the standard sequential subagent loop, TDD-first, one
> diagnosis doc per WP under
> `.claude/lessons-learned/v2.29-wpNN-diagnosis.md`. Append lessons
> to `.claude/lessons-learned/ticketing-v2.29.md`. **Forward rules
> carried from v2.15-v2.27:** (a)-(ggg), 59 rules, see
> `ticketing-v2.27.md` close section. **Forward rules new from
> v2.28:** (hhh) recon-only closure is a valid version shape — when
> a recon WP finds zero forcing function for the predicted theme,
> STOP at WP01 with a closure doc, do NOT manufacture WP02 scope; a
> version with WP01 + closure is a valid shape, the catalogue still
> grows and the floors still re-verify, what does NOT happen is
> forced make-work; sub-rule: distinguish "permissive-on-both-sides"
> PIN gaps (escape-hatch on both sides — codegen does NOT help) from
> "missing-coverage" PIN gaps (flat shape on both sides, pin absent
> only because nobody wrote it — codegen DOES help); v2.28-WP01
> classified `TicketDTO` and `SearchV2Response` as
> permissive-on-both-sides; generalises to any recon WP across any
> layer.
> Do NOT reintroduce the `_v1_deferred.py` skip-hook — per-test
> deferral uses plain pytest markers.

**Cumulative forward rules total: 60 (a-hhh).** v2.28 added 1 new
rule (hhh) to the 59 carried from v2.27 (a-ggg).

---

## Notes — judgment calls worth recording

- **Recon-only is legitimate.** v2.28's "ship" is the proof of
  negative. Recording an honest null result is a positive
  contribution to the catalogue — it prevents future versions from
  re-litigating the same dead-end themes. Rule (hhh) codifies this so
  the pattern is reusable.
- **The drift-audit table is the artifact.** Future versions can
  re-derive (d'')'s null result in O(table-lookup) rather than
  O(audit-redo) by reading the table in this doc's WP01 section.
- **No separate WP01 diagnosis file.** Recon-only versions can fold
  WP01 directly into the closure doc. v2.28 has no
  `v2.28-wp01-diagnosis.md` — this is intentional per rule (hhh).
- **v2.27's recommendation was correct.** v2.27 close recommended
  (b) UPSTREAM-WAIT as primary and noted that (d'') was premature
  without a forcing function. v2.28 confirmed this by exhaustion.
  The version-pipeline is functioning correctly: predictions made
  one version ahead are being validated by the next version's recon.
- **Two consecutive recon-only versions would be a signal.** If
  v2.29 also closes recon-only, that's the strongest possible
  evidence the pipeline has reached steady state and should pause
  until an external trigger arrives.

### Files touched (rough stats — sum of WP01 + closure)

- **Production code (`app/`):** 0 files.
- **Production code (`frontend/src/`):** 0 files.
- **Config:** 0 files.
- **Lint allow-lists:** 0 files.
- **Test code (backend, new):** 0 files.
- **Test code (frontend, new):** 0 files.
- **Docs (`.claude/lessons-learned/`):** 1 file — this retrospective
  (absorbs WP01 findings inline per rule (hhh)).
