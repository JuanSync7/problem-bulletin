# v2.19 ticketing — lessons learned

Companion to `ticketing-v2.18.md`. v2.19 was the **preventive-hardening
PIN version** that mirrors v2.17's shape on the type-checker axis: a
fresh structural lint (mypy-as-CI) wired against a frozen offender set
with honest BY-DESIGN / LEGACY classification. The v2.17 → v2.18 cycle
was "PIN pragmas → sweep LEGACY pragmas"; v2.19 reopens that loop on
the type-checker axis. **0 LEGACY** in the new allow-list — every one
of the 157 unique `path:line:errcode` keys traces to a concrete
framework typing limit (SQLAlchemy `Column[T]` / `Mapped[T]` ORM-boundary
leakage dominates at ~130 entries; smaller clusters on Pydantic v2
BaseSettings env constructor, `Service.list` self-shadow, `Page[T]`
item-type drift, Starlette callable variance, python-jose / authlib
downstream Any flow). Two real bugs fixed as fallout (unused
`# type: ignore` entries from v2.17-WP03 surfaced by
`warn_unused_ignores`, paired-deleted under bidirectional stale-detection
on both the v2.17 pragma lint and the new v2.19 mypy lint). 3 WPs:
baseline+recon + PIN + closure.

**Closing baselines:** backend **1438 → 1444 P / 0 F / 5 → 6 skipped /
14 xfailed** (+6 from WP02's lint shim self-tests + main test).
Frontend **276 P / 0 F** (untouched — type-only backend change).

---

## v2.19-WP01 (G0) — baseline verify + typecheck-tooling recon

Backend: **1438 P / 0 F / 5 skipped / 14 xfailed**. Frontend:
**276 P / 0 F**. v2.18 close confirmed as the regression anchor.

Tooling recon: `mypy 1.20.1` already installed in `.venv` and listed in
`pyproject.toml [project.optional-dependencies] dev`. `pyright` NOT
installed, not on `$PATH`, not in `pyproject.toml`. No `[tool.mypy]`
config block and no `pyrightconfig.json` — either tool would start from
zero config.

Mypy sniff against `app/` (default config, no per-module overrides):
**170 errors in 47 files** (checked 134 source files). Dominant
clusters identified up-front: SQLAlchemy `Column[T]` leakage past the
ORM boundary (most `arg-type` / `attr-defined` hits), `list?[T]`
unconditional iteration in routes (real fixable bugs), Pydantic-v2
`Page[T]` item-type drift, missing stubs (`python-jose` / `authlib`),
`<Service>.list` self-shadow on `typing.List` style annotations.

**Recommendation:** keep mypy. Already installed, dominant error
clusters are not pyright-exclusive wins on this codebase, 170-error
surface is small enough to PIN against a frozen allow-list rather than
adopt a second toolchain. Pyright would also work but costs an install
+ a parallel config + npm/node coupling on the backend with no
proportional payoff visible in the sniff.

---

## v2.19-WP02 — mypy typecheck-as-CI PIN

**Outcome.** `[tool.mypy]` config block landed in `pyproject.toml`;
`tests/test_typecheck_lint_v219_wp02.py` landed with bidirectional
stale-entry detection + 5 parser self-tests + 1 opt-in end-to-end
synthetic-bad self-test; `.gitignore` updated with `.mypy_cache/` and
`.pytest_cache/`.

**Numbers — recon vs final.**

| Stage                                            | Errors | Files |
| ------------------------------------------------ | ------ | ----- |
| WP01 sniff (mypy default config)                 | 170    | 47    |
| After landing `[tool.mypy]` config               | 166    | 45    |
| After 2 real-bug fixes (unused inline ignores)   | 164    | 44    |

Allow-list size: **157 unique `path:line:errcode` keys** (vs 164 raw
errors — `app/config.py:172` emits 8 distinct `call-arg`s collapsed
under a single key by the dict).

**Real bugs fixed (count: 2).**

1. **`app/middleware/security.py:97`** — removed unused
   `# type: ignore[type-arg]` and properly typed `re.Match[str]`. The
   original justification ("re.Match not generic-subscriptable across
   the minor Python versions we support") is no longer true on Python
   3.12 / 3.11. Paired v2.17-WP03 allow-list entry deleted.
2. **`app/routes/realtime_ws.py:55`** — removed unused
   `# type: ignore[attr-defined]` on
   `async with async_session_factory() as session`. Under the current
   `[tool.mypy]` config mypy resolves the module-level
   `async_sessionmaker(...)` assignment correctly. Paired v2.17-WP03
   allow-list entry deleted.

Both fixes are coordinated 2-step removals (inline ignore + paired
v2.17-WP03 allow-list entry) — the new v2.19-WP02 lint surfaced them
via `warn_unused_ignores`, and the v2.17-WP03 stale-detection forced
the paired allow-list cleanup. **Cross-lint paired-cleanup validated
on a real example, not a contrived one.**

**Allow-list classification — 157 BY-DESIGN, 0 LEGACY.** Every
remaining error traces to a concrete framework typing limit:

| Cluster                                          | Approx. count |
| ------------------------------------------------ | ------------- |
| SQLAlchemy `Column[T]` / `Mapped[T]` leakage     | ~130          |
| Pydantic v2 BaseSettings env-driven constructor  | 12 (8 + 4)    |
| python-jose / authlib downstream `Any` flow      | 4             |
| Starlette / FastAPI handler-callable variance    | 2             |
| `<Service>.list` self-shadowing the `list` name  | 7             |
| Pydantic v2 `Page[T]` item-type drift            | ~5            |
| Misc Pydantic / overload / index variance        | ~10           |

**v2.18-WP04 cast verified as no-op.** The
`cast(Literal["user", "agent"], row.actor_type)` at
`app/routes/notifications_v1.py:177` produces **zero mypy errors**
under the new config — neither a `redundant-cast` warning (we set
`warn_redundant_casts = true`) nor any downstream artefact at that
line. ✅ v2.18-WP04 was a genuine narrowing, not a paper-over.

**Mypy config choices.**

```toml
[tool.mypy]
python_version = "3.12"
follow_imports = "silent"
warn_unused_ignores = true
warn_redundant_casts = true
exclude = ["alembic/", "tests/", "scripts/"]

[[tool.mypy.overrides]]
module = ["jose", "jose.*", "authlib", "authlib.*"]
ignore_missing_imports = true
```

**Choices deliberately NOT made.**

- **`pydantic.mypy` plugin** — broken vs mypy 1.20.1
  (`module 'mypy.expandtype' has no attribute 'ExpandTypeVisitor'`).
  Pinned BY-DESIGN with a single rationale at `app/config.py:172`;
  revisit when either package releases a compatibility bump.
- **`sqlalchemy.ext.mypy` plugin** — would resolve the dominant
  ~130-entry cluster in one stroke, but requires a coordinated
  declarative-form cleanup and would invalidate the whole PIN at once.
  Out of scope for WP02; v2.20+ candidate.
- **Strict mode** — we PIN-and-fix-forward, not bulk-tighten.

**Runtime.** Cold (no `.mypy_cache/`) ~11.75s; warm ~0.45s. Marked
`@pytest.mark.slow` (the mark isn't yet registered — emits one
`PytestUnknownMarkWarning`; small follow-up).

---

## v2.19-WP03 (closure) — retrospective + v2.20 seed

This document. Zero code touched.

---

## v2.19 retrospective

### Headline numbers

- **Backend baseline:** 1438 P / 0 F / 5 skipped / 14 xfailed (v2.18
  close).
- **Backend final:** **1444 P / 0 F / 6 skipped / 14 xfailed**
  (+6 from WP02's lint shim — 5 parser self-tests + 1 main allow-list
  test; 1 opt-in synthetic-bad self-test gated behind
  `RUN_MYPY_SELFTEST=1` accounts for the +1 skipped).
- **Net backend delta:** +6.
- **Frontend baseline:** 276 P / 0 F (v2.18 close).
- **Frontend final:** **276 P / 0 F** (untouched).
- **Net frontend delta:** +0.
- **Mypy raw errors:** **164** (down from 170 sniff: −4 from
  `ignore_missing_imports` overrides, −2 from real-bug fixes).
- **Mypy allow-list keys:** **157 unique `path:line:errcode`** (164
  raw errors minus 7 collapsed-on-same-`(path,line,errcode)`-triple at
  `app/config.py:172`).
- **Allow-list classification:** **157 BY-DESIGN / 0 LEGACY.** Every
  entry traces to a concrete framework typing limit.
- **Real bugs fixed:** 2 (both unused `# type: ignore` entries from
  v2.17-WP03 surfaced by `warn_unused_ignores`; cross-lint
  paired-cleanup with the v2.17 pragma allow-list).
- **Production code touched:** 2 files
  (`app/middleware/security.py`, `app/routes/realtime_ws.py`) — both
  for the unused-ignore removals.
- **New lint surface:** 1 (mypy via subprocess parsed against
  `_OFFENDER_ALLOWLIST`).
- **Production regressions introduced:** zero.

### WPs shipped

| WP | Bucket | Summary | Test delta |
|---|---|---|---|
| WP01 | G0 | Baseline verify (1438 P / 276 P). Typecheck-tooling recon: mypy 1.20.1 already installed; pyright NOT installed; sniff = 170 errors in 47 files; recommended mypy over pyright (no proportional gain from adding a second toolchain). | ±0 |
| WP02 | P (PIN) | `[tool.mypy]` config block in `pyproject.toml`; `tests/test_typecheck_lint_v219_wp02.py` with `_OFFENDER_ALLOWLIST` of 157 `path:line:errcode` keys (157 BY-DESIGN / 0 LEGACY), bidirectional stale-entry detection, 5 parser self-tests, 1 opt-in synthetic-bad e2e self-test. Per-module `ignore_missing_imports` for jose/authlib. 2 real bugs fixed (unused `# type: ignore` cross-lint paired-cleanup with v2.17-WP03 allow-list). `.gitignore` updated. Pydantic mypy plugin disabled (broken vs mypy 1.20.1); SQLAlchemy plugin scope-deferred. | +6 (1438→1444) |
| WP03 | closure | Retrospective + v2.20 seed (this doc). | ±0 |

### Cross-cutting lessons

1. **(z) Plugin RUNTIME health gates typechecker choice — existence
   isn't enough.** Both Pydantic and SQLAlchemy mypy plugins exist; on
   paper either would dissolve a large chunk of the offender set.
   Today, neither was usable: Pydantic's plugin errors against mypy
   1.20.1 with a missing-attribute crash; SQLAlchemy's plugin requires
   a declarative-form cleanup that we don't have appetite for in a
   PIN-shape WP. Pattern: when selecting a typechecker (or any tool
   that depends on plugins for the boring-but-large win), check
   plugin runtime compatibility against the current tool version
   BEFORE committing — plugin existence does not imply plugin works.
   The ~130-entry ORM-leakage cluster is the COST of plugin-less mypy
   on this stack; it's an honest cost, not a defect.

2. **(aa) `warn_redundant_casts = true` is a free unit-test for every
   `cast()` call — set from day one of any typecheck wiring.** The
   v2.18-WP04 `cast(Literal["user", "agent"], row.actor_type)` produced
   zero mypy errors AND zero redundant-cast warning under the v2.19
   config — direct evidence the cast was a genuine narrowing, not a
   paper-over. The flag costs nothing to enable and validates every
   existing `cast()` in the codebase as a side effect. Pattern: any
   time you wire a static-type CI gate, enable `warn_redundant_casts`
   immediately — it back-validates every `cast()` already in the tree
   for free.

3. **(bb) When 100% of pinned errors are BY-DESIGN, the next-version
   backlog shape changes — it's plugin/refactor evaluation, NOT a
   LEGACY sweep.** v2.17 closed with 7 LEGACY entries (sweep work
   waiting); v2.18 swept them; v2.19 closes with 0 LEGACY. The
   sweep-after-pin pattern is conditional on having LEGACY entries to
   sweep — when the offender set is 100% BY-DESIGN, the next-version
   pickup must look one level deeper: at the framework typing limit
   the BY-DESIGN cluster traces to. For v2.20 that means evaluating
   the SQLAlchemy mypy plugin and re-checking the Pydantic plugin —
   plugin enablement may reclassify a meaningful slice of BY-DESIGN
   entries as LEGACY-now-fixable. Pattern: 0-LEGACY at PIN time is
   itself a signal — the next version should attack the framework
   boundary, not the offender count.

4. **(cc) Cross-lint paired-cleanup falls out of bidirectional
   stale-detection on EACH lint — no cross-lint synchronisation logic
   needed.** The 2 unused `# type: ignore` fixes touched both the
   v2.17-WP03 pragma allow-list AND the v2.19-WP02 mypy lint: the
   pragma had to be removed (or the v2.17 lint flagged the missing
   pragma) AND the allow-list row had to be deleted (or the v2.17
   stale-detection fired) AND mypy had to stay green under
   `warn_unused_ignores`. All three constraints composed without any
   explicit cross-lint synchronisation code — each lint's own
   bidirectional stale-detection was sufficient. Pattern: when two
   lints overlap on an axis, do NOT design a cross-lint synchroniser;
   bidirectional stale-detection on EACH lint composes to give
   correct cross-lint behaviour for free.

5. **(dd) Per-line dedupe refinement: when multiple errors fire on
   the same `path:line:errcode`, collapse to ONE allow-list entry —
   the errcode is the third dimension v2.17's `path:line` keying
   lacked.** `app/config.py:172` emits 8 distinct `call-arg` errors
   from the Pydantic-v2 BaseSettings env-driven constructor. Under
   v2.17 rule (p) (per-line dedupe), this could have been collapsed
   to one `path:line` entry — but mypy can also emit DIFFERENT error
   codes on the same line that deserve separate justification. The
   right granularity is `path:line:errcode`: multiple same-errcode
   errors on one line are usually one underlying cause and collapse;
   different errcodes on one line are usually different causes and
   stay separate. Pattern: structural-lint allow-list keys should
   include the error code where the underlying tool emits codes; it
   adds the dimension that distinguishes "8 expressions of one bug"
   from "2 different bugs on a busy line."

6. **(ee) `_OFFENDER_ALLOWLIST` keying scheme is becoming a repo-wide
   pattern — 4 lints now share it (bare-catch, ts-any, pragma,
   typecheck). Worth extracting a shared helper module in a future
   cosmetic version.** Each lint reimplements the same skeleton:
   regex over source text or subprocess output, parse to a
   structured key, diff against a dict-shaped allow-list, fire
   bidirectional stale-detection. The shapes are aligned enough that
   one helper module could host the diff + stale-detection logic and
   let each lint supply only its parser. Pattern: when 4 lints
   share a structural skeleton, extract — but schedule the
   extraction as a cosmetic version, not inline with new-lint work.
   The pattern is stable enough now (v2.15 / v2.17 / v2.19) that
   extraction won't lock in premature shape.

7. **(ff) Subprocess-based lints (invoke external tool, parse output)
   trade cold-start cost for full-tool fidelity — acceptable when
   warm-cache runtime is sub-second and the test is
   `@pytest.mark.slow`-tagged.** Mypy via subprocess costs ~11.75s
   cold but ~0.45s warm. The cold cost is paid on first CI run and
   on cache invalidation; the warm cost is paid on every developer
   iteration. The trade was worth it because (a) full-tool fidelity
   means we don't have to maintain a parallel mypy-in-process
   harness, (b) warm runtime is comfortably under 1s, and (c) the
   `@pytest.mark.slow` mark gives future CI tiers a clean escape via
   `-m "not slow"`. Pattern: subprocess-based lints are fine
   primitives when the warm path stays sub-second and the slow
   primary path is escape-tagged from day one.

### What stayed deferred (carry to v2.20)

- **Bucket A (C7, E3, E4, F3)** — still conditional v2.11
  carry-forwards (`decode_email_body` helper, KindPill 7th surface,
  `useSearchV2` ergonomic follow-ups, TipTap second-consumer
  extraction). No triggering need fired during v2.19.
- **Bucket B (B1, B2)** — still conditional v2.13 carry-forwards
  (per-arm `refresh_total` opt-in syntax; WP05 OpenAPI↔TS parser
  expansion). No triggering need fired during v2.19.
- **Bucket C (C1, C2, C3, C4)** — v2.18 surfaced candidates
  (`*Read` promotion; `Response.json(): Promise<any>` → `unknown`
  sweep; `actor_type` enum column migration; context-snippet
  allow-list anchoring). No triggering need fired during v2.19.
- **Pydantic mypy plugin re-enable** — gated on a version bump in
  either mypy or pydantic that resolves the `ExpandTypeVisitor`
  crash. Recurring re-check candidate for every minor-version bump.
- **SQLAlchemy mypy plugin evaluation** — would dissolve ~130 of
  157 allow-list entries in one stroke; requires a coordinated
  declarative-form audit (`Column[T] = Column(...)` vs
  `Mapped[T] = mapped_column(...)`). PRIMARY v2.20 candidate.
- **`<Service>.list` self-shadow rename** — 7 entries; renaming
  to `.list_page(...)` (or similar) would clear them. Invasive but
  bounded.
- **Pydantic `Page[T]` item-type drift** — ~5 entries; switching
  routes from `[t.to_dict() for t in rows]` to
  `[XRead.model_validate(t) for t in rows]` would clear them.
- **Register the `slow` pytest marker** in
  `[tool.pytest.ini_options].markers` so the
  `PytestUnknownMarkWarning` from the WP02 test quiets. One-line
  follow-up, not a blocker.
- **`_OFFENDER_ALLOWLIST` helper extraction** — 4 lints now share
  the shape; cosmetic-version candidate.
- **157 BY-DESIGN typecheck residents.** PERMANENTLY documented
  with `BY-DESIGN:` rationale per entry. They will not be
  re-evaluated unless a plugin (or framework move) shifts the
  boundary.

### Files touched (rough stats)

- **Production code (`app/`):** 2 files —
  `app/middleware/security.py` (removed unused
  `# type: ignore[type-arg]`; typed `re.Match[str]`),
  `app/routes/realtime_ws.py` (removed unused
  `# type: ignore[attr-defined]`).
- **Production code (`frontend/src/`):** 0 files.
- **Alembic (`alembic/versions/`):** 0 files.
- **Config:** 1 file — `pyproject.toml` (`[tool.mypy]` block +
  per-module `jose` / `authlib` override).
- **Repo hygiene:** 1 file — `.gitignore` (`.mypy_cache/`,
  `.pytest_cache/`).
- **Lint allow-lists:** 2 files —
  `tests/test_typecheck_lint_v219_wp02.py` (NEW, 157 entries),
  `tests/test_type_ignore_lint_wp03_v217.py` (2 cross-lint
  paired-deletions from the security / realtime_ws fixes).
- **Test code (backend):** 1 new file
  (`tests/test_typecheck_lint_v219_wp02.py`, +6 tests counted in the
  1444 total).
- **Docs (`.claude/lessons-learned/`):** 2 per-WP diagnosis files
  (`v2.19-wp01-diagnosis.md`, `v2.19-wp02-diagnosis.md`) + this
  retrospective.

---

## v2.20 starting prompt seed

v2.19 closed as a **preventive-hardening PIN version** mirroring v2.17
on the type-checker axis: mypy 1.20.1 wired as CI lint via subprocess
+ pytest shim, against a frozen `_OFFENDER_ALLOWLIST` of 157
`path:line:errcode` keys. **All 157 entries are BY-DESIGN — 0 LEGACY
handed forward.** 2 real bugs fixed as fallout (unused `# type: ignore`
entries from v2.17-WP03 surfaced by `warn_unused_ignores`; cross-lint
paired-cleanup with the v2.17 pragma allow-list). +6 backend tests
from the WP02 lint shim (5 parser self-tests + 1 main allow-list
test); frontend untouched. Pydantic mypy plugin disabled (broken vs
mypy 1.20.1); SQLAlchemy mypy plugin scope-deferred — together these
account for the ~130-entry ORM-leakage cluster and the 12-entry
BaseSettings cluster that dominate the allow-list.

v2.20 has **no concrete LEGACY backlog handed forward.** Three shapes
to choose between:

- **(a) Opportunistic-only** — Bucket A (C7, E3, E4, F3) / Bucket B
  (B1, B2) / Bucket C (C1, C2, C3, C4) carry-forwards on triggering
  second-consumer need only. Lowest-friction; no committed surface.
- **(b) Plugin re-evaluation sweep — RECOMMENDED.** Re-check the
  Pydantic mypy plugin against the latest pydantic / mypy versions
  (the `ExpandTypeVisitor` crash may be fixed); evaluate the
  SQLAlchemy mypy plugin (or `sqlalchemy2-stubs`) against the current
  declarative-form mix. Either plugin enabling would reclassify a
  meaningful slice of BY-DESIGN entries as LEGACY-now-fixable — the
  ~130-entry ORM-leakage cluster is the single largest concentration
  in the allow-list and directly attackable at the framework boundary.
  This is the v2.17 → v2.18 cycle reopened one level deeper: instead
  of sweeping LEGACY entries (none exist), we evaluate whether the
  framework boundary itself has shifted.
- **(c) Cosmetic version — extract shared `_OFFENDER_ALLOWLIST`
  helper module** (lesson ee). 4 lints (bare-catch, ts-any, pragma,
  typecheck) now share a structural skeleton stable enough to extract
  without locking in premature shape. Mechanical refactor; not
  blocking but reduces drift surface for the next lint added.

**Recommend (b) plugin re-evaluation as v2.20.** It's the strongest
signal — directly attacks the cluster that dominates the allow-list,
and the year-or-so since the last plugin compatibility check is long
enough for either Pydantic or mypy to have shipped the fix. Failure
mode is well-bounded: if neither plugin is usable, the version closes
as a no-op recon (mirror of v2.10's pydantic audit shape) and v2.21
picks up (a) or (c). Note (a) and (c) as alternatives if (b) blocked.

### v2.20 backlog

#### Bucket Q — Plugin re-evaluation sweep (PRIMARY v2.20 work, RECOMMENDED option (b))

Q1. **Re-test `pydantic.mypy` plugin** against current pydantic + mypy
    versions. If the `ExpandTypeVisitor` crash is fixed, enable the
    plugin and re-snapshot the allow-list. Expected: 12 BaseSettings
    env-constructor entries dissolve; possibly some `Page[T]` drift
    entries shift. Reclassify dissolved entries as no longer in
    allow-list (deletion via stale-detection); reclassify newly
    surfaced entries as BY-DESIGN or LEGACY honestly.
Q2. **Evaluate `sqlalchemy.ext.mypy` plugin** (or migrate to
    `sqlalchemy2-stubs`). Survey current declarative-form mix in
    `app/models/` — `Mapped[T] = mapped_column(...)` vs legacy
    `Column[T] = Column(...)`. If majority on `Mapped[T]`, enable
    the plugin and triage the resulting allow-list delta. If still
    mixed, scope a small declarative-cleanup WP first.
Q3. **Triage allow-list delta from plugin enablement.** Any entries
    dissolved → deleted. Any newly surfaced → honestly classified
    BY-DESIGN / LEGACY. Any reclassified BY-DESIGN → LEGACY (plugin
    revealed they're now fixable) → scheduled for v2.21 sweep.

#### Bucket R — Cosmetic refactor (alternative option (c))

R1. **Extract shared `_OFFENDER_ALLOWLIST` helper module.** 4 lints
    share the skeleton: parser → key tuple → dict diff →
    bidirectional stale-detection. Host the diff + stale-detection
    logic centrally; let each lint supply its parser callback.
    Mechanical refactor across `tests/test_bare_catch_lint*.py`,
    `frontend/src/__tests__/ts_any_lint.test.ts`,
    `tests/test_type_ignore_lint_wp03_v217.py`,
    `tests/test_typecheck_lint_v219_wp02.py`.

#### Bucket A — Conditional v2.11 carry-forwards (act only on triggering need)

A1. **C7 — `decode_email_body` helper.** Second QP-wrap consumer.
A2. **E3 — KindPill 7th surface.** Real consumer surfaces.
A3. **E4 — `useSearchV2` ergonomic follow-ups.** Second consumer
    surfaces.
A4. **F3 — TipTap second-consumer extraction.** Second editor
    surface lands.

#### Bucket B — Conditional v2.13 carry-forwards

B1. **Per-arm `refresh_total` opt-in syntax** (option (a) from
    v2.13-WP06). Pick up on real user need.
B2. **WP05 OpenAPI↔TS parser expansion** — nested generics,
    intersections, multi-param generics, generic type aliases,
    mapped/conditional, default generic params. Pick up when first
    consumer needs one.

#### Bucket C — v2.18 surfaced candidates (conditional)

C1. **Promote `EditSuggestionRead` / `AttachmentRead` to
    `frontend/src/api/*.ts`** with parity-lint entries. Second
    consumer surfaces.
C2. **`Response.json(): Promise<any>` → `unknown` + runtime parser
    sweep.** Significant sweep; schedule only after Bucket Q closes
    (the typecheck-as-CI gate will help quantify the blast radius).
C3. **`actor_type` `Mapped[str]` → `Mapped[ActorType]` enum-backed
    column migration.** Touches `TicketNotification`,
    `TicketTransition`, `AuditLogEvent`, `Ticket`. Pick up if a
    second narrowing site surfaces or if Bucket Q surfaces multiple
    `actor_type` mismatches.
C4. **Line-number-keyed allow-list anchoring** — design follow-up:
    context-snippet or function-name anchoring across the
    bare-catch, ts-any, pragma, AND typecheck lints to reduce
    line-shift churn. Pairs naturally with Bucket R extraction.

#### Bucket D — v2.19 surfaced candidates (conditional)

D1. **`<Service>.list` self-shadow rename** — 7 typecheck allow-list
    entries. Rename `TicketService.list` / `ProjectService.list` to
    `.list_page(...)`. Invasive but bounded.
D2. **Pydantic `Page[T]` item-type drift** — ~5 typecheck allow-list
    entries. Switch routes from
    `Page(items=[t.to_dict() for t in rows])` to
    `Page(items=[XRead.model_validate(t) for t in rows])`. Pick up
    if Bucket Q does NOT dissolve these.
D3. **Register `slow` pytest marker** — one-line addition to
    `[tool.pytest.ini_options].markers` to quiet the
    `PytestUnknownMarkWarning` from `test_typecheck_lint_v219_wp02.py`.
    Trivial follow-up; can fold into any v2.20 WP.

### v2.20 prompt seed (paste-ready)

> Proceed with v2.20 of the problem-bulletin ticketing system.
> v2.19 retrospective + carry-forward backlog live at the bottom of
> `.claude/lessons-learned/ticketing-v2.19.md`. Baselines: backend
> **1444 P / 0 F / 6 skipped / 14 xfailed**, frontend **276 P / 0 F**.
> **v2.19 was the preventive-hardening PIN version mirroring v2.17 on
> the type-checker axis — mypy 1.20.1 wired as CI lint with 157
> `path:line:errcode` allow-list entries, ALL 157 BY-DESIGN / 0 LEGACY.
> v2.20 has NO concrete LEGACY backlog handed forward.** Choose one
> of three shapes: (a) opportunistic-only — Bucket A / B / C / D
> carry-forwards on triggering need only; **(b) plugin re-evaluation
> sweep — RECOMMENDED**: re-check `pydantic.mypy` plugin against
> current pydantic+mypy (was broken vs mypy 1.20.1 with an
> `ExpandTypeVisitor` crash); evaluate `sqlalchemy.ext.mypy` plugin
> (or `sqlalchemy2-stubs`) against the current declarative-form mix.
> Either plugin enabling would dissolve a meaningful slice of the
> ~130-entry ORM-leakage cluster + 12-entry BaseSettings cluster that
> together dominate the v2.19 allow-list. Failure mode well-bounded:
> if neither plugin usable today, version closes as a no-op recon
> (mirror v2.10 pydantic audit shape); (c) cosmetic version — extract
> shared `_OFFENDER_ALLOWLIST` helper module across 4 lints
> (bare-catch, ts-any, pragma, typecheck). **Bucket Q (PRIMARY if
> option b):** Q1 re-test `pydantic.mypy` (re-snapshot allow-list);
> Q2 evaluate `sqlalchemy.ext.mypy` / `sqlalchemy2-stubs` (survey
> `Mapped[T]` vs `Column[T]` mix first); Q3 honestly classify the
> allow-list delta (dissolved entries deleted; newly surfaced
> BY-DESIGN/LEGACY; reclassified BY-DESIGN→LEGACY scheduled for
> v2.21 sweep). **Bucket R (if option c):** R1 extract shared
> allow-list helper module. **Bucket A** (C7, E3, E4, F3),
> **Bucket B** (B1, B2), **Bucket C** (C1 `*Read` promotion;
> C2 `Response.json()` → `unknown` sweep — defer until after Bucket
> Q; C3 `actor_type` enum migration; C4 context-snippet anchoring),
> **Bucket D** (D1 `<Service>.list` rename; D2 `Page[T]` item-type
> tightening — defer until after Bucket Q; D3 register `slow`
> marker) remain conditional carry-forwards — act ONLY on triggering
> need. Follow the sequential subagent loop pattern, TDD-first, one
> diagnosis doc per WP under
> `.claude/lessons-learned/v2.20-wpNN-diagnosis.md`. Append lessons
> to `.claude/lessons-learned/ticketing-v2.20.md`. **Forward rules
> carried from v2.15:** (a) lint-before-sweep when a class has known
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
> preventive-hardening — the PIN alone is load-bearing even without
> a scheduled sweep; (n) compiler-API pragma blindspot — pragmas
> (`@ts-ignore`, `# type: ignore`, `# noqa`) are NOT AST nodes in any
> language; bounded per-line regex over source text is the right
> primitive; (o) a 0-offender axis is its own success metric — when
> a class is already at 0, a PIN locks the invariant; (p) per-line
> dedupe in lint emission keeps allow-lists stable — collapse to
> `path:line` granularity, NOT `path:line:column` or per-match; (q)
> demo-mode / fixture / registry-barrel sites are legitimate
> BY-DESIGN allow-list residents — when a directory's whole purpose
> is to host the offending pattern, the entries are structural, not
> debt; (r) `r"""..."""` is repo-canonical for any docstring
> documenting escape / regex / LIKE / shell / pragma syntax.
> **Forward rules carried from v2.18:** (s) sweep-after-pin executes
> cleanly when stale-entry detection runs both directions — the
> maintainer cannot drift the allow-list past the code; ALWAYS
> implement bidirectional stale-detection alongside offender
> detection; (t) line-number-keyed allow-lists are fragile against
> unrelated additions in the same file — consider context-snippet or
> function-name anchoring; (u) re-validate LEGACY justifications at
> sweep time — original author's framing may be inaccurate even when
> the underlying offender is real; (v) `Response.json(): Promise<any>`
> is an unsignal-able `any` axis — declaration-level lints catch
> declarations, not return-type propagation through assignment
> context; the declaration-lint blind spot is REAL; (w) when backend
> uses `extra="allow"` for variant payloads, the frontend
> discriminated union must key from REQUEST CONTEXT, not response
> shape; (x) `any` hides dead branches — type-tightening surfaces
> phantom fallbacks; the tightening is itself a dead-code audit on
> the consumer side; (y) file-local OpenAPI mirror interface is a
> lightweight tightening tool — promote to a parity-checked module
> only when a second consumer surfaces. **Forward rules new from
> v2.19:** (z) plugin RUNTIME health gates typechecker choice —
> existence isn't enough; check Pydantic / SQLAlchemy / etc. plugin
> compatibility with the CURRENT tool version before committing; the
> ORM-leakage cluster is the HONEST cost of plugin-less mypy, not a
> defect; (aa) `warn_redundant_casts = true` auto-validates every
> `cast()` call for free — set from day one of any typecheck wiring
> alongside `warn_unused_ignores`; (bb) when 100% of pinned errors
> are BY-DESIGN, the next-version backlog shape changes — it's
> plugin/refactor evaluation at the framework boundary, NOT a LEGACY
> sweep; sweep-after-pin doesn't fire when there's nothing to sweep;
> attack the framework boundary instead; (cc) cross-lint
> paired-cleanup falls out of bidirectional stale-detection on EACH
> lint — no cross-lint synchronisation logic needed; composition of
> single-lint invariants gives correct cross-lint behavior for free;
> (dd) per-line dedupe refinement (v2.17 rule p): when multiple
> errors fire on the same line, collapse keying at
> `path:line:errcode` — the errcode is the third dimension that
> distinguishes "N expressions of one bug" from "N different bugs on
> a busy line"; (ee) when 4+ lints share a structural skeleton
> (parser → key tuple → dict diff → bidirectional stale-detection),
> extract a shared helper module — but schedule the extraction as a
> cosmetic version, not inline with new-lint work; (ff)
> subprocess-based lints (invoke external tool, parse output) trade
> cold-start cost for full-tool fidelity — acceptable when warm-cache
> runtime is sub-second AND the test is `@pytest.mark.slow`-tagged
> from day one. Pre-flight any rename WP with `grep -rn` across
> `app/` AND `alembic/` before scoping. Encode numeric decision gates
> into perf-pass WP prompts. Do NOT reintroduce the
> `_v1_deferred.py` skip-hook — per-test deferral uses plain pytest
> markers.
