# v2.20 ticketing — lessons learned

Companion to `ticketing-v2.19.md`. v2.20 was the **plugin re-evaluation +
cluster source-code sweep** version that reopened the v2.19 "0 LEGACY"
PIN at the framework boundary. The v2.19 close handed forward **157
BY-DESIGN / 0 LEGACY** mypy allow-list entries with the explicit note
that the next-version backlog shape had to look one level deeper than a
LEGACY sweep — at the framework typing limit the BY-DESIGN cluster
traced to. v2.20 confirmed that hypothesis: a single config touch
(enabling `pydantic.mypy`) reclassified 25 entries from BY-DESIGN to
deleted, and a focused `Mapped[T]` migration WP across 12 ORM models
collapsed another 81. Final state **157 → 51 allow-list keys (−106,
68% reduction)** with classification still **0 LEGACY** throughout —
every residual is a genuine framework typing limit (joined-load
attr-defined variance, Starlette ASGI Mount signature variance,
dialect-specific `pg_insert(Model.__table__)` overload). Two
attackable clusters surfaced as concrete v2.21 backlog (`<Service>.list`
self-shadow rename + `pg_insert` rewrite, jointly ~21 keys). 4 WPs:
baseline + plugin recon, pydantic plugin enable, SQLA Mapped[T] sweep,
closure.

**Closing baselines:** backend **1444 P / 0 F / 6 skipped / 14 xfailed**
(unchanged across all 4 WPs — no regressions). Frontend **276 P / 0 F**
(untouched). Mypy: **164 raw errors / 157 keys → 51 raw errors / 51
keys**.

---

## v2.20-WP01 (G0) — baseline confirm + plugin recon

Backend **1444 P**, frontend **276 P**, mypy 164 errors / 157 keys — all
match v2.19 close.

Tooling versions: mypy 1.20.1, pydantic 2.13.0 (bumped vs v2.19 sample),
SQLAlchemy 2.0.49 (`sqlalchemy.ext.mypy` deprecated for 2.x line).

**Key recon finding:** v2.19-WP02's "pydantic.mypy is broken against
mypy 1.20.1" rationale was based on a raw Python REPL test
(`import pydantic.mypy` → `AttributeError: module 'mypy.expandtype' has
no attribute 'ExpandTypeVisitor'`). v2.20-WP01 sandboxed a
plugin-enabled mypy config and ran `.venv/bin/python -m mypy
--config-file /tmp/pyproject_pydantic_test.toml app` — mypy loaded the
plugin cleanly and produced **164 → 132 errors (−32, 0 regressions)**.
The raw-import failure is a red herring caused by mypy's vendored
module shape; only the mypy-run-via-plugin is a valid health check.

Cluster breakdown of the 157 allow-list: SQLAlchemy 136 (86.6%),
Pydantic 6 (3.8%), other (FastAPI/jose) 15 (9.6%). SQLA cluster
dominates and is the structural target for WP03.

Plugin verdicts: **enable `pydantic.mypy` in WP02** (purely additive in
sandbox); **leave `sqlalchemy.ext.mypy` OFF** (deprecated for SA 2.x —
attack the cluster via finishing the `Mapped[T]` migration instead).

---

## v2.20-WP02 — enable `pydantic.mypy`

**Outcome.** `plugins = ["pydantic.mypy"]` added under `[tool.mypy]` in
`pyproject.toml` with the v2.19 misleading-rationale comment block
rewritten to document the v2.20-WP01 recon. `_OFFENDER_ALLOWLIST`
shrunk from 157 → 132 (−25 keys); mypy errors 164 → 132 (−32, exactly
matching the sandbox prediction). Backend stayed at 1444 P; frontend
untouched.

**The 25 eliminated keys broke down surprisingly:**

| Cluster                       | Eliminated | Notes |
|-------------------------------|-----------:|-------|
| Pydantic-cluster (direct)     | 5          | `BaseSettings` constructor + `Page[T]` item-type drift |
| SQLAlchemy-cluster (indirect) | 20         | Pydantic-side narrowing was the proximate blocker for SA boundary errors |

The plugin's effect was **cross-cluster** — only 5 of 25 eliminated
keys were in the nominal "Pydantic-cluster"; 20 were classified as
SQLAlchemy-cluster but disappeared because Pydantic-side inference was
the proximate blocker. The v2.19 cluster taxonomy was approximate; the
plugin attacks the proximate inference, not the labelled cluster.

`warn_unused_ignores` produced 0 new findings — no v2.17-WP03 inline
ignores became redundant under the plugin.

---

## v2.20-WP03 — SQLAlchemy cluster source-code sweep

**Outcome.** Pure-mode `Mapped[T]` migration across 12 bulletin-domain
ORM models plus 4 narrowly-scoped service-layer fixes. Allow-list 132 →
**51** (−81 keys, **2× the aspirational 40-key target, 4× the firm
20-key minimum**). Classification still 0 LEGACY — every deletion was
the offender being fixed, not reclassified.

**Models migrated (12 files):** `solution.py`, `user.py`, `comment.py`,
`problem.py`, `notification.py`, `attachment.py`, `watch.py`,
`audit_log.py`, `magic_link.py`, `edit_suggestion.py`, `flag.py`,
`domain.py`, `app_config.py`.

**Service-layer fixes (4):**
- `services/solutions.py` — `result =` reuse across heterogeneous
  `select()` calls renamed to row-specific bindings (`sol_result`,
  `prob_result`, etc.) — mypy was locking onto the first inferred row
  type and cascading `attr-defined` errors.
- `services/tickets.py:701` — untyped `conds = []` annotated as
  `list[Any]` (mypy fixated on `BinaryExpression` from first append).
- `services/feed.py:_apply_sort` — `sort_col: Any` widening after
  `Problem.activity_at` became `Mapped[datetime | None]`.
- `services/comments.py` — explicit None-guard on `c.author_id` after
  it became `Mapped[UUID | None]`.

**Density observation:** one model file ≈ 5–10 mypy keys eliminated.
Scales linearly across consumer-side surface area. The aspirational
target undershot because Mapped[T] migration is high-leverage — one
file fixes many consumer-side errors.

**Two future-attackable clusters surfaced as 51-key floor residents:**
- `<Service>.list` self-shadow (7 + 7 cascading = 14 keys; ~11
  external callers across MCP tools, routes, tests).
- `pg_insert(Model.__table__)` (7 keys; mechanical rewrite to
  `pg_insert(Model)`).

These become v2.21 Bucket E.

---

## v2.20-WP04 (closure) — this document

D3 follow-up: registered `slow` pytest marker under new
`[tool.pytest.ini_options].markers` section in `pyproject.toml`.
`PytestUnknownMarkWarning` is now silent in the
`test_typecheck_lint_v219_wp02.py` run. Retrospective written. Zero
production code touched.

---

## v2.20 retrospective

### Headline numbers

- **Backend:** 1444 P / 0 F / 6 skipped / 14 xfailed — unchanged across
  all 4 WPs.
- **Frontend:** 276 P / 0 F — untouched.
- **Mypy raw errors:** 164 → 132 (WP02) → **51** (WP03).
- **Mypy allow-list keys:** 157 → 132 (WP02) → **51** (WP03), **−106
  (68% reduction)**.
- **Classification:** **0 LEGACY throughout.** All deletions were
  offender-fixed, never reclassified to LEGACY.
- **Real bugs fixed:** 0 (all changes typing-only).
- **Production code touched (`app/`):** 16 files (12 models, 4
  services).
- **Config:** 1 file (`pyproject.toml` — pydantic.mypy plugin enable +
  pytest markers).
- **Allow-list test file:** `tests/test_typecheck_lint_v219_wp02.py`
  shrunk by 106 entries.
- **Production regressions introduced:** zero.

### WPs shipped

| WP | Bucket | Summary | Allow-list delta |
|----|--------|---------|-----------------:|
| WP01 | G0 | Baseline verify + plugin recon. Confirmed pydantic.mypy loads cleanly under mypy 1.20.1 + pydantic 2.13.0 via mypy itself (raw-import was a red herring). Confirmed sqlalchemy.ext.mypy is correctly deferred (deprecated for SA 2.x). SQLA cluster 136/157 dominates. | ±0 |
| WP02 | Q | Enable `pydantic.mypy` plugin. Sandbox prediction matched exactly. 25 keys eliminated; surprise finding: 20 of 25 were SQLA-cluster (Pydantic inference was the proximate blocker, cluster taxonomy is approximate). | −25 |
| WP03 | Q | Pure-mode `Mapped[T]` migration across 12 bulletin-domain models + 4 service fixes. 4× the firm minimum target. | −81 |
| WP04 | closure | Retrospective + D3 (`slow` marker registration) + v2.21 seed. | ±0 |

### Cross-cutting lessons

1. **(gg) Plugin RUNTIME health = "mypy --config-file <config-with-plugin>
   <target>" returns a clean delta — NOT "import plugin_module from
   REPL".** v2.19 rule (z) said "check plugin runtime compatibility
   before committing" but didn't specify what RUNTIME meant. v2.19-WP02
   ran `python -c "import pydantic.mypy"` from the .venv REPL, got an
   `AttributeError: module 'mypy.expandtype' has no attribute
   'ExpandTypeVisitor'`, and disabled the plugin BY-DESIGN. v2.20-WP01
   sandboxed an actual mypy run with the plugin in the config; the
   plugin loaded cleanly. The raw `import pydantic.mypy` failure is a
   red herring — mypy's vendored module shape doesn't match what the
   plugin imports at REPL time, but mypy's own bootstrap loads the
   plugin correctly. Pattern: plugin RUNTIME health is whether the
   tool-with-plugin-in-config runs cleanly on a representative target,
   not whether the plugin module imports in isolation. Rule (z) is
   preserved as-is for history; (gg) supersedes it for new work.

2. **(hh) Plugin unblocking is cross-cluster — the plugin attacks the
   proximate inference, not the labelled cluster.** Enabling
   `pydantic.mypy` was expected to eliminate ~5–6 Pydantic-cluster
   entries (BaseSettings constructor + `Page[T]` drift). It actually
   eliminated 5 Pydantic + 20 SQLAlchemy-cluster entries — because
   Pydantic-side inference was the proximate blocker for downstream
   SQLAlchemy boundary errors (a `Page[T]` item-type drift downstream
   of a service returning `list[Pydantic[Model]]` would surface as
   "arg-type at the SQLA boundary"). The v2.19 cluster taxonomy was
   approximate — labels reflect the most-visible symptom, not the
   proximate cause. Pattern: when evaluating a plugin's blast radius,
   expect cross-cluster unblocking; do not budget purely off the
   nominal cluster's count. Plugins attack the proximate inference,
   labels follow the symptom.

3. **(ii) `Mapped[T]` migration is the unit of SQLAlchemy 2.x
   cluster-reduction effort — one model file ≈ 5–10 mypy keys
   eliminated, scales linearly across models.** v2.20-WP03 migrated 12
   model files and eliminated 81 keys (~6.75 keys/file average). The
   leverage is consumer-side: one `Column[T]` → `Mapped[T]` change in
   a model file collapses every downstream `arg-type` / `attr-defined`
   error against that column's descriptor return type. Pattern: when
   sizing a SQLAlchemy 2.x typing-cluster sweep, count model files
   that still emit bare `Column[T]`, multiply by 5–10 for an order-of-
   magnitude estimate. The aspirational target should be ~10×files, the
   firm minimum ~5×files. Mixed declarative-form codebases will
   undershoot; cleanly-2.0-pattern codebases will overshoot.

4. **(jj) When a BY-DESIGN rationale becomes obsolete via framework /
   plugin upgrade, the entry's lifecycle is BY-DESIGN → deleted, NOT
   BY-DESIGN → LEGACY → deleted.** v2.20 took 106 of 157 v2.19
   BY-DESIGN entries to "deleted" without ever passing through a
   LEGACY state. The LEGACY tag is for "should fix but disproportionate
   today" — when "disproportionate today" becomes "trivial tomorrow"
   (because a plugin or framework upgrade reclassifies the underlying
   limit as fixable), the entry's correct lifecycle skips LEGACY
   entirely. Pattern: do NOT preemptively reclassify BY-DESIGN to
   LEGACY when a framework upgrade is on the horizon — wait for the
   actual reclassification event (sweep version) and delete in one
   step. LEGACY is for genuine deferral, not for staging.

5. **(kk) PIN value is the WORKFLOW, not the taxonomy — BY-DESIGN
   classification is a snapshot, not a verdict.** v2.19 said "157
   BY-DESIGN, no sweep backlog" with full honesty given mypy 1.20.1 +
   the plugins it had tested. v2.20 found 106 of those entries were
   now-fixable. The taxonomy was correct AT THAT MOMENT; the PIN's
   value was making the cluster visible as an audit surface that made
   reclassification mechanical. Pattern: PINs are dynamic — their
   value compounds as the framework / toolchain underneath shifts.
   "0 LEGACY" at PIN time is not "no work to do," it's "no work to do
   YET — wait for the framework boundary to move." Schedule a
   re-evaluation WP every N versions on any PIN with a non-trivial
   BY-DESIGN floor.

6. **(ll) Shadow-of-builtin warnings (e.g. `<Service>.list`) are
   mypy's free naming-convention check — worth a one-time sweep when
   surfaced.** WP03 left 7 + 7 = 14 keys traceable to `TicketService.list`
   and `ProjectService.list` shadowing the builtin `list` inside the
   class body, breaking subsequent `-> list[T]` annotations and the
   route-layer iteration over the returned values. The fix is
   mechanical (rename to `list_tickets` / `list_projects`); the cost
   is touching ~11 external callers. Pattern: when mypy surfaces a
   shadow-of-builtin cluster, treat it as a free naming-convention
   audit — the rename touches callers but the code becomes more
   readable AND types tighten. Schedule as a focused WP; do NOT inline
   with new feature work.

7. **(mm) Two-WP attack on a single PIN is the right granularity for
   plugin-reclassification + cluster-sweep — config WP first, code WP
   second, never combine.** v2.20 split as WP02 (plugin enable, −25) +
   WP03 (Mapped[T] sweep, −81). Combining them in one WP would have
   conflated two distinct verification surfaces: (a) does the plugin
   load cleanly + behave purely additively, and (b) does the source
   migration close the targeted cluster without regressions. Splitting
   gave clean before/after numbers for each axis and made the
   surprise cross-cluster finding (lesson hh) visible. Pattern:
   plugin enable + downstream cluster sweep are independent
   verification surfaces — always sequence them as two WPs. The PIN's
   bidirectional stale-detection composes correctly across both.

### What stayed deferred (carry to v2.21)

- **Bucket E (NEW — v2.20-WP03 surfaced):**
  - **E1. `<Service>.list` self-shadow rename** — 7 direct + 7
    cascading = 14 keys; ~11 callers across MCP tools, routes, tests.
    Mechanical rename to `list_tickets` / `list_projects`.
  - **E2. `pg_insert(Model.__table__)` → `pg_insert(Model)`** — 7
    callsites, all in `services/ticket_notifications.py`. SA accepts
    ORM classes in dialect `insert()` overloads; mechanical rewrite.
- **Bucket A** (C7, E3, E4, F3) — still conditional v2.11
  carry-forwards.
- **Bucket B** (B1, B2) — still conditional v2.13 carry-forwards.
- **Bucket C** (C1, C2, C3, C4) — still conditional v2.18 carry-forwards.
- **Bucket D** (D1 `<Service>.list` covered by E1; D2 `Page[T]` drift
  partially resolved by pydantic.mypy plugin; D3 `slow` marker
  COMPLETED in WP04).
- **`_OFFENDER_ALLOWLIST` helper extraction** (v2.19 rule ee) — 4
  lints share the shape; cosmetic-version candidate.
- **51 BY-DESIGN typecheck residents.** The 51-key floor is durable
  pending E1/E2 attack. After E1/E2 lands, expected ~30-key floor
  consisting of joined-load attr-defined variance + Starlette ASGI
  Mount signature variance — genuinely fixed framework limits.

### Files touched (rough stats)

- **Production code (`app/`):** 16 files —
  - Models (12): `solution.py`, `user.py`, `comment.py`, `problem.py`,
    `notification.py`, `attachment.py`, `watch.py`, `audit_log.py`,
    `magic_link.py`, `edit_suggestion.py`, `flag.py`, `domain.py`,
    `app_config.py`.
  - Services (4): `solutions.py`, `tickets.py`, `feed.py`, `comments.py`.
- **Production code (`frontend/src/`):** 0 files.
- **Alembic (`alembic/versions/`):** 0 files.
- **Config:** 1 file — `pyproject.toml` (pydantic.mypy plugin enable in
  WP02 + `[tool.pytest.ini_options]` `slow` marker registration in
  WP04 + rewritten comment block).
- **Lint allow-lists:** 1 file — `tests/test_typecheck_lint_v219_wp02.py`
  (106 entries deleted across WP02 + WP03; bidirectional
  stale-detection confirms 1:1 correspondence with fixed offenders).
- **Test code (backend):** 0 new files.
- **Docs (`.claude/lessons-learned/`):** 3 per-WP diagnosis files
  (`v2.20-wp01-diagnosis.md`, `v2.20-wp02-diagnosis.md`,
  `v2.20-wp03-diagnosis.md`) + this retrospective.

---

## v2.21 starting prompt seed

v2.20 closed as a **plugin re-evaluation + cluster source-code sweep
version** — config touch (enable `pydantic.mypy`, −25) followed by
source-code sweep (`Mapped[T]` migration across 12 bulletin-domain
models + 4 service fixes, −81). Allow-list **157 → 51 (−106, 68%
reduction)** with classification **0 LEGACY throughout** (every
deletion was the offender being fixed, not reclassified). Baselines:
backend **1444 P / 0 F / 6 skipped / 14 xfailed**, frontend **276 P / 0
F**. 51 residual keys split as: ~14 `<Service>.list` self-shadow
(direct + cascading), 7 `pg_insert(Model.__table__)` dialect overload,
~5 `comments.py:167` return-value drift, ~3 `solutions.py` joined-load
attr-defined, ~2 Starlette ASGI Mount signature variance, ~2
`Ticket.assignee_id` co-nullable FK pair, plus scattered single
residuals.

v2.21 has **a concrete backlog of ~21 mechanically-fixable keys**
across two clusters. Three shapes to choose between:

- **(a) Targeted continued sweep — RECOMMENDED.** Land E1
  (`<Service>.list` rename, ~14 keys) and E2 (`pg_insert(Model)`
  rewrite, ~7 keys). Post-v2.21 floor would be ~30 keys, almost all
  genuinely fixed framework limits (Starlette/FastAPI ASGI variance,
  joined-load typing residuals). Mirrors the v2.18 sweep shape
  (concrete LEGACY-like target list) but on the typecheck axis.
- **(b) Opportunistic-only.** Bucket A (C7, E3, E4, F3) / Bucket B
  (B1, B2) / Bucket C (C1, C2, C3, C4) carry-forwards on triggering
  second-consumer need only. Lowest-friction; no committed surface.
- **(c) Cosmetic extract of shared `_OFFENDER_ALLOWLIST` helper
  module** (v2.19 rule ee). 4 lints share the skeleton; still on
  backlog from v2.19. Schedule-able any time, not blocking.

**Recommend (a) targeted continued sweep as v2.21.** Concrete
~21-key backlog is ready; mechanical scope (1 rename + 1 mechanical
rewrite); matches v2.18 sweep shape; reduces residual floor to genuine
framework-limit floor. (b) and (c) are alternative shapes if (a) is
blocked.

### v2.21 backlog

#### Bucket E — targeted continued sweep (PRIMARY v2.21 work, RECOMMENDED option (a))

E1. **`<Service>.list` self-shadow rename.** Rename
    `TicketService.list` → `list_tickets` and `ProjectService.list` →
    `list_projects`. Update ~11 external callers across MCP tools,
    routes, tests. Expected −14 mypy keys (7 direct + 7 cascading
    `routes/tickets.py:attr-defined`). Pre-flight with `grep -rn` across
    `app/` AND `alembic/` AND `tests/` before scoping.
E2. **`pg_insert(Model.__table__)` → `pg_insert(Model)`.** 7 callsites
    in `services/ticket_notifications.py`. Mechanical rewrite +
    re-run service tests. Expected −7 mypy keys.
E3. **Triage allow-list delta post-E1/E2.** Bidirectional
    stale-detection auto-cleans deletions; any newly surfaced entries
    classified honestly BY-DESIGN / LEGACY.

#### Bucket R — Cosmetic refactor (alternative option (c))

R1. **Extract shared `_OFFENDER_ALLOWLIST` helper module** across the
    4 lints (bare-catch, ts-any, pragma, typecheck). Mechanical
    refactor; carried from v2.19 → v2.20 → v2.21.

#### Bucket A — Conditional v2.11 carry-forwards (act only on triggering need)

A1. C7 `decode_email_body` helper. A2. E3 KindPill 7th surface.
A3. E4 `useSearchV2` ergonomic follow-ups. A4. F3 TipTap second-consumer
extraction.

#### Bucket B — Conditional v2.13 carry-forwards

B1. Per-arm `refresh_total` opt-in syntax. B2. WP05 OpenAPI↔TS parser
expansion.

#### Bucket C — v2.18 surfaced candidates (conditional)

C1. Promote `EditSuggestionRead` / `AttachmentRead`. C2.
`Response.json(): Promise<any>` → `unknown` sweep. C3. `actor_type`
enum-backed column migration. C4. Context-snippet anchoring across
lints.

#### Bucket D — v2.19 surfaced candidates (status)

D1. `<Service>.list` rename — folded into E1.
D2. `Page[T]` item-type drift — partially resolved by pydantic.mypy
    plugin (v2.20-WP02); residual may surface during E1/E2 triage.
D3. **Register `slow` pytest marker — COMPLETED in v2.20-WP04.**

### v2.21 prompt seed (paste-ready)

> Proceed with v2.21 of the problem-bulletin ticketing system.
> v2.20 retrospective + carry-forward backlog live at the bottom of
> `.claude/lessons-learned/ticketing-v2.20.md`. Baselines: backend
> **1444 P / 0 F / 6 skipped / 14 xfailed**, frontend **276 P / 0 F**,
> mypy **51 errors / 51 allow-list keys (0 LEGACY)**. **v2.20 was the
> plugin re-evaluation + cluster source-code sweep version — enabled
> `pydantic.mypy` (−25) + finished `Mapped[T]` migration across 12
> bulletin-domain ORM models + 4 service fixes (−81), total −106 keys,
> 68% reduction.** v2.20 hands forward a **concrete ~21-key backlog
> across two mechanically-fixable clusters** (`<Service>.list`
> self-shadow rename, `pg_insert(Model.__table__)` rewrite). Three
> shapes: **(a) targeted continued sweep — RECOMMENDED**: E1
> `<Service>.list` rename (~14 keys, ~11 callers) + E2 `pg_insert`
> rewrite (~7 keys, 1 file); post-v2.21 floor would be ~30 keys,
> almost all genuinely fixed framework limits; (b) opportunistic-only —
> Bucket A / B / C carry-forwards on triggering need only; (c)
> cosmetic version — extract shared `_OFFENDER_ALLOWLIST` helper
> module across 4 lints (still on backlog from v2.19). **Bucket E
> (PRIMARY if option a):** E1 rename `TicketService.list` →
> `list_tickets`, `ProjectService.list` → `list_projects`, update ~11
> callers (pre-flight with `grep -rn` across `app/` AND `alembic/`
> AND `tests/` before scoping); E2 mechanical
> `pg_insert(Model.__table__)` → `pg_insert(Model)` in 7 callsites in
> `services/ticket_notifications.py`; E3 triage allow-list delta
> (bidirectional stale-detection auto-cleans deletions; classify any
> newly surfaced entries honestly). **Bucket R (if option c):** R1
> extract shared allow-list helper module. **Bucket A** (C7, E3, E4,
> F3), **Bucket B** (B1, B2), **Bucket C** (C1 `*Read` promotion;
> C2 `Response.json()` → `unknown` sweep; C3 `actor_type` enum
> migration; C4 context-snippet anchoring) remain conditional
> carry-forwards — act ONLY on triggering need. D3 (`slow` marker)
> COMPLETED in v2.20-WP04. Follow the sequential subagent loop
> pattern, TDD-first, one diagnosis doc per WP under
> `.claude/lessons-learned/v2.21-wpNN-diagnosis.md`. Append lessons
> to `.claude/lessons-learned/ticketing-v2.21.md`. **Forward rules
> carried from v2.15:** (a) lint-before-sweep when class has known
> shape; (b) by-design enumeration at FIRST surfacing of any
> mixed-population class; (c) two state slots for pages with both
> load-failure and action-failure UX; (d) `PYTEST_CURRENT_TEST` is
> the canonical no-config test-mode sentinel; (e) audit metric
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
> health gates typechecker choice — existence isn't enough
> (REFINED by (gg) for new work; preserved as-is for history); (aa)
> `warn_redundant_casts = true` auto-validates every `cast()` call
> for free; (bb) when 100% of pinned errors are BY-DESIGN, the
> next-version backlog shape is plugin/refactor evaluation at the
> framework boundary, NOT a LEGACY sweep; (cc) cross-lint
> paired-cleanup falls out of bidirectional stale-detection on EACH
> lint — no synchroniser needed; (dd) per-line dedupe refinement —
> collapse keying at `path:line:errcode`; (ee) when 4+ lints share
> a structural skeleton, extract shared helper — schedule as a
> cosmetic version; (ff) subprocess-based lints trade cold-start
> cost for full-tool fidelity — acceptable when warm-cache runtime is
> sub-second AND test is `@pytest.mark.slow`-tagged from day one.
> **Forward rules new from v2.20:** (gg) plugin RUNTIME health =
> "mypy --config-file <config-with-plugin> <target>" returns a clean
> delta — NOT "import plugin_module from REPL"; refines (z), the raw
> REPL import path is a red herring against mypy's vendored module
> shape; (hh) plugin unblocking is cross-cluster — the plugin attacks
> the proximate inference, not the labelled cluster; expect a
> meaningful slice of "other-cluster" reductions when enabling a
> plugin (pydantic.mypy eliminated 5 nominal Pydantic + 20 SQLA
> keys); cluster taxonomy is approximate; (ii) `Mapped[T]` migration
> is the unit of SQLAlchemy 2.x cluster-reduction effort — one model
> file ≈ 5–10 mypy keys eliminated, scales linearly across consumer
> surface; size sweeps as 5×files (firm) to 10×files (aspirational);
> (jj) when a BY-DESIGN rationale becomes obsolete via framework /
> plugin upgrade, the entry's lifecycle is BY-DESIGN → deleted, NOT
> BY-DESIGN → LEGACY → deleted; LEGACY is for "should fix but
> disproportionate today," not for staging future deletions; (kk)
> PIN value is the WORKFLOW, not the taxonomy — BY-DESIGN
> classification is a snapshot, not a verdict; PINs are dynamic and
> their value compounds as the framework underneath shifts; "0
> LEGACY" at PIN time means "no work YET — wait for the framework
> boundary to move"; (ll) shadow-of-builtin warnings (e.g.
> `<Service>.list`) are mypy's free naming-convention check — worth
> a one-time sweep when surfaced; rename touches callers but
> improves readability AND types tighten; schedule as focused WP;
> (mm) two-WP attack on a single PIN is the right granularity for
> plugin-reclassification + cluster-sweep — config WP first, code WP
> second, never combine; independent verification surfaces should be
> sequenced not merged; PIN's bidirectional stale-detection
> composes across both. Pre-flight any rename WP with `grep -rn`
> across `app/` AND `alembic/` AND `tests/` before scoping. Encode
> numeric decision gates into perf-pass WP prompts. Do NOT
> reintroduce the `_v1_deferred.py` skip-hook — per-test deferral
> uses plain pytest markers.
