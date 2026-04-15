# Aion Bulletin — Engineering Guide

> **Document type:** Post-implementation engineering reference
> **Companion spec:** `docs/AION_BULLETIN_SPEC.md`
> **Companion design:** `docs/AION_BULLETIN_DESIGN.md`
> **Source location:** `app/`, `frontend/src/`
> **Last updated:** 2026-04-14

---

## Section 1: System Overview

### Purpose

Aion Bulletin is an internal problem bulletin board built for approximately 100 ASIC engineers at the organization. It provides a single place to surface workplace problems, propose solutions with optional git-link references, vote on problem importance (upstars) and solution quality (upvotes), discuss via threaded comments, and recognize top contributors through a leaderboard. The system supports anonymous posting so engineers can raise sensitive issues without attribution, while retaining author identity for administrative moderation.

The target audience is engineers with mixed technical comfort levels — many do not use GitHub directly. The application is deployed on-premises using rootless Podman containers and authenticates against the company's Azure AD tenant, with a magic-link email fallback for users who encounter SSO issues.

### Architecture at a Glance

```
+---------------------------------------------------------+
|                       Browser                           |
|  React 18 + Vite + TypeScript SPA                       |
|  REST fetch() + WebSocket for notifications             |
+---------------+------------------+----------------------+
                | HTTPS :443       | WSS :443
                v                  v
+---------------------------------------------------------+
|                       NGINX                             |
|  TLS termination . Rate limiting (30/5/1 r/s zones)     |
|  Static SPA serving . Attachment file serving           |
|  Bot detection -> OG meta rewrite                       |
|  WebSocket upgrade proxy (/ws)                          |
+---------------+------------------+----------------------+
                | HTTP :8000       | WS :8000
                v                  v
+---------------------------------------------------------+
|                      FastAPI                            |
|  Python 3.11+ . SQLAlchemy 2.0 + asyncpg               |
|  REST endpoints . WebSocket endpoint                    |
|  JWT auth (HttpOnly cookies) . Structured JSON logging  |
|  Services layer . Domain exception hierarchy            |
+---------------+-----------------------------------------+
                | asyncpg :5432
                v
+---------------------------------------------------------+
|                   PostgreSQL 16                         |
|  All application data . tsvector + GIN full-text search |
|  JSONB metadata columns . Alembic migrations            |
+---------------------------------------------------------+

         +--------------+
         |  /data/       |  Shared volume: API (read-write),
         |  attachments/ |  NGINX (read-only direct serve)
         +--------------+

External:  Azure AD (OIDC)  .  SMTP Server (magic links, digests)  .  Teams Webhook (optional)
```

### Design Goals

1. **Async-first.** Every database operation uses SQLAlchemy 2.0 async sessions with asyncpg. The event loop is never blocked by I/O — SMTP sends use aiosmtplib, Teams webhooks use httpx.AsyncClient, and filesystem probes run on the executor thread pool.

2. **Dual authentication with zero passwords.** Users authenticate via Azure AD OIDC (primary) or passwordless magic-link email (fallback). No password is ever stored or transmitted by the application.

3. **Anonymous posting with admin auditability.** Problems, solutions, and comments can be posted anonymously. The `author_id` is always stored in the database but hidden from non-admin API responses. Admins can de-anonymize with an immutable audit trail.

4. **Real-time notification pipeline.** A watch-level routing matrix fans out events to per-user notification rows, delivered over three independent channels: in-browser WebSocket push, Microsoft Teams Adaptive Card webhook, and plain-text email digest.

5. **Single-server, no external services beyond PostgreSQL.** No Redis, no Elasticsearch, no message queue. Full-text search uses PostgreSQL tsvector with GIN indexes. Rate limiting is in-memory (single process). The entire stack runs in three Podman containers.

### Technology Choices

| Technology | Role | Why Chosen |
|---|---|---|
| FastAPI | API framework | Native async support, automatic OpenAPI docs, Pydantic integration for request/response validation |
| PostgreSQL 16 | Primary database | tsvector + GIN for full-text search, JSONB for flexible metadata, mature async driver (asyncpg) |
| SQLAlchemy 2.0 + asyncpg | ORM + async driver | Declarative ORM with native async session support; `expire_on_commit=False` for safe post-commit serialization |
| React 18 + Vite | Frontend SPA | Lazy-loaded routes for small initial bundle; Vite provides fast HMR in development and optimized production builds |
| NGINX | Reverse proxy | TLS termination, per-route rate limiting (3 zones), static SPA and attachment serving, bot detection for link previews |
| Podman (rootless) | Container runtime | No root daemon; containers run as non-root UIDs; named volumes managed under user home directory |
| Alembic | Schema migrations | Auditable, repeatable migration history; async engine bridge via `run_sync`; database URL from application settings |
| authlib | OIDC client | Handles PKCE, state validation, and Azure AD metadata discovery; lighter than msal |
| python-jose | JWT encode/decode | HS256 symmetric signing; sufficient for single-issuer, no-external-consumer token model |
| aiosmtplib | Async SMTP | Non-blocking email delivery matching the async FastAPI runtime |
| Pydantic v2 | Request/response schemas | Field-level constraint validation, `SecretStr` for secret protection, generic `CursorPage[T]` pagination envelope |

---

## Section 2: Architecture Decisions

### ADR-1: Async-First with SQLAlchemy 2.0

**Context.** The application serves approximately 100 concurrent users with a mix of short REST requests and long-lived WebSocket connections. Database queries, SMTP sends, and HTTP webhook calls are the primary I/O operations.

**Options considered.** (A) Synchronous SQLAlchemy with thread pool executor. (B) SQLAlchemy 2.0 async sessions with asyncpg.

**Choice.** Option B — async sessions with asyncpg throughout.

**Rationale.** FastAPI runs on an async event loop. Using synchronous database calls would require `run_in_executor` wrappers on every query, adding complexity and losing the ability to interleave I/O operations naturally. SQLAlchemy 2.0's native async support eliminates this friction. `expire_on_commit=False` on the session factory prevents `DetachedInstanceError` when FastAPI serializes ORM objects after the transaction commits. `pool_pre_ping=True` detects stale connections before they reach application code.

**Consequences.** All database access must use `await`. Lazy-loading ORM relationships raises errors in async context — relationships must be explicitly loaded via `selectinload` or `joinedload`. The `get_db()` dependency manages commit/rollback automatically, so route handlers never call `commit()` directly.

### ADR-2: JWT in HttpOnly Cookies with Bearer Fallback

**Context.** The SPA needs authenticated access to REST and WebSocket endpoints. Tokens must be protected against XSS theft while remaining accessible to API clients and Swagger UI.

**Options considered.** (A) Authorization header only. (B) HttpOnly cookie only. (C) Cookie-first with Bearer header fallback.

**Choice.** Option C — cookie-first with Bearer header fallback.

**Rationale.** HttpOnly cookies are inaccessible to JavaScript, eliminating XSS-based token theft for browser clients. The `SameSite=Lax` attribute mitigates CSRF. The Bearer header fallback preserves compatibility with API clients, Swagger UI, and WebSocket connections (which pass the token as a query parameter). The `get_current_user` dependency in `app/auth/dependencies.py` checks the cookie first, then falls back to the `Authorization` header. The `Secure` flag is suppressed only when `ENVIRONMENT="development"` to allow plain HTTP local dev servers.

**Consequences.** The WebSocket endpoint at `/ws/notifications` accepts the token via `?token=` query parameter because browsers do not send cookies on WebSocket upgrade requests initiated from JavaScript. The 8-hour fixed expiry with no refresh token simplifies the implementation — sessions are bounded by the workday and forced re-login is acceptable.

### ADR-3: Domain Exceptions Separate from HTTP

**Context.** Business-rule violations (forbidden state transitions, pin limits, duplicate votes) must produce specific HTTP responses without coupling service-layer code to HTTP concepts.

**Options considered.** (A) Raise `HTTPException` directly in service code. (B) Define domain exceptions inheriting from `Exception`, map to HTTP in the app factory.

**Choice.** Option B — `AppError` hierarchy mapped in `app/main.py`.

**Rationale.** Service functions raising `HTTPException` would couple them to FastAPI and make them untestable without a running web server. The `AppError` base class and its subclasses (`ForbiddenTransitionError`, `PinLimitExceededError`, `FileSizeLimitError`, `FileTypeNotAllowedError`, `DuplicateVoteError`, `MagicLinkExpiredError`, `TenantMismatchError`) carry structured fields (e.g., `current`/`target` on `ForbiddenTransitionError`) that exception handlers can inspect. The `_EXCEPTION_STATUS_MAP` in `app/main.py` maps each subclass to its HTTP status code in one place.

**Consequences.** Any new domain exception must be added to the map; an unmapped `AppError` subclass falls back to HTTP 500. Middleware or global handlers catch `AppError` as a fallback so no subclass produces an unhandled 500.

### ADR-4: Two-Axis Voting (Upstars vs Upvotes)

**Context.** The application needs to distinguish between "this problem is worth solving" and "this solution is good." A single voting axis would conflate problem validation with solution quality.

**Options considered.** (A) Single vote type applicable to both problems and solutions. (B) Separate voting tables with independent semantics.

**Choice.** Option B — `upstars` table for problems, `solution_upvotes` table for solutions, with identical toggle mechanics but independent counts.

**Rationale.** Upstars drive problem ranking in the feed (`top` sort mode) and contribute to the "Top Reporters" leaderboard track. Solution upvotes drive solution ordering within a problem and contribute to the "Top Solvers" leaderboard track. Keeping the axes separate ensures accurate scoring on both tracks. Both use `SELECT ... FOR UPDATE` row-level locking on the parent entity to prevent duplicate-vote race conditions, and both return `(active, count)` on every toggle to eliminate the need for a separate read.

**Consequences.** The feed's `top` sort mode uses a correlated `COUNT(Upstar)` subquery. The leaderboard module joins against different tables depending on the track. Anonymous contributions are excluded from leaderboard calculations to prevent de-anonymization through rank correlation.

### ADR-5: Immutable Solution Versioning (Append-Only)

**Context.** Solutions to engineering problems evolve over time. Voters may have upvoted an earlier description that no longer matches the current content.

**Options considered.** (A) In-place mutation with edit history (like problems). (B) Append-only `SolutionVersion` rows with a `current_version_id` pointer.

**Choice.** Option B — append-only versioning.

**Rationale.** The `Solution` row carries no mutable content fields. All text lives in `SolutionVersion` rows, which are write-once. The `current_version_id` pointer advances forward with each new version but never causes old rows to be deleted. `PATCH` and `PUT` on `/solutions/{id}` return HTTP 405 with a message directing callers to `POST /solutions/{id}/versions`. This makes the immutability constraint visible in the API surface rather than relying on a missing route.

**Consequences.** Reading a solution's current content requires joining through `current_version_id` (or falling back to `MAX(version_number)`). The `current_version_id` denormalization eliminates a `MAX` subquery on every read. The complete version history is available at `GET /solutions/{id}/versions`.

### ADR-6: Watch-Level Notification Routing Matrix

**Context.** Users need granular control over which events they receive notifications for. A boolean watch/unwatch is insufficient for a system with eight notification types.

**Options considered.** (A) Boolean watch with per-type opt-out. (B) Four watch levels with a routing matrix.

**Choice.** Option B — `WatchLevel` enum (`all_activity`, `solutions_only`, `status_only`, `none`) with a `WATCH_ROUTING` dict mapping each level to its allowed `NotificationType` set.

**Rationale.** The routing matrix is data, not branching logic. Adding a new watch level or notification type requires only a dict entry. `all_activity` is defined as `set(NotificationType)`, so it automatically covers any new types added to the enum. Auto-watch on participation (problem creation, claiming, commenting) never downgrades an existing watch level — it compares numeric priority and skips the write if the existing level is already equal or higher.

**Consequences.** Fan-out in `generate_notification` queries all watches for a problem, excludes the actor, filters by the routing matrix, and bulk-inserts `Notification` rows. Delivery to WebSocket, Teams, and email is performed separately by the caller, so delivery failures on one channel do not affect the others.

### ADR-7: CSS Custom Properties Instead of Tailwind

**Context.** The frontend needs dark/light mode support and a consistent design token system.

**Options considered.** (A) Tailwind CSS. (B) CSS-in-JS (styled-components, Emotion). (C) CSS custom properties with a `ThemeProvider`.

**Choice.** Option C — CSS custom properties toggled via `data-theme` attribute on `<html>`.

**Rationale.** Zero runtime overhead. Dark/light mode flips by toggling eight root CSS variables set in `applyCssVariables()`. Adding Tailwind would require purge configuration and couples class names to design tokens. CSS-in-JS adds bundle weight and runtime cost. The `useDarkMode` hook persists the mode preference as `"light"`, `"dark"`, or `"system"` in `localStorage` under key `pb-theme`, defaulting to `"system"` which respects `prefers-color-scheme`.

**Consequences.** All color values are defined in `src/theme/colors.ts` as `lightColors`, `darkColors`, `statusColors`, and `gradients`. Components reference CSS variables rather than hard-coded colors. The runtime dependency footprint is three packages: `react`, `react-dom`, and `react-router-dom`.

### ADR-8: Cursor-Based Pagination over Offset

**Context.** The problem feed is the primary read path. New problems can be inserted between page requests, causing offset-based pagination to skip or duplicate entries.

**Options considered.** (A) Offset/limit pagination. (B) Cursor-based keyset pagination.

**Choice.** Option B — cursor encodes `(sort_value, id)` as opaque base64-JSON.

**Rationale.** Keyset pagination avoids offset drift when rows are inserted between pages. The cursor is stateless — no server-side session or cache needed. The compound `WHERE` clause ensures strict, stable ordering:

```python
stmt = stmt.where(
    (Problem.created_at < cursor_value)
    | ((Problem.created_at == cursor_value) & (Problem.id < cursor_id))
)
```

For `top` and `discussed` sort modes, the same correlated subquery used in `ORDER BY` is replicated in the `WHERE` clause. The service fetches `limit + 1` rows; if more than `limit` are returned, `has_next = True` and `next_cursor` is encoded from the last row.

**Consequences.** Pinned problems are prepended outside the pagination window on the first page only (when `cursor is None`), guaranteeing they are always visible regardless of sort mode. The generic `CursorPage[T]` response envelope is reused across problems, notifications, and other paginated endpoints.

---

## Section 3: Module Reference

### 3.1 Foundation Layer (config, database, enums, exceptions, schemas)

<!-- BEGIN VERBATIM: module-config.md -->

### Foundation Layer — Module Reference

The Foundation Layer contains the five modules that every other part of Aion Bulletin depends on: runtime configuration (`config`), database connectivity (`database`), domain enumerations (`enums`), the application exception hierarchy (`exceptions`), and Pydantic request/response contracts (`schemas`). Nothing in this layer imports from feature modules; the dependency arrow points only inward.

---

### 1. `app/config.py` — Application Configuration

#### Purpose

`config.py` centralises every externally supplied parameter the application needs to start and operate: database DSN, Azure AD credentials, JWT signing secret, SMTP relay settings, file-storage path, and environment tag. It uses Pydantic Settings so that values can be supplied through a `.env` file or real environment variables interchangeably, and it exposes a single cached accessor — `get_settings()` — so the entire process shares one `Settings` instance without re-parsing the environment on every call. This satisfies REQ-916, REQ-504, REQ-108, REQ-104, and REQ-404.

#### How it works

1. **Model declaration** — `Settings` subclasses `pydantic_settings.BaseSettings`. Each class attribute is a typed field. Fields without defaults are required; the application will not start if they are absent.

2. **Source resolution** — `SettingsConfigDict` instructs Pydantic to read `.env` first, then fall back to real environment variables. `case_sensitive=False` means `DATABASE_URL` and `database_url` are treated identically. `extra="ignore"` silently discards any env vars that don't map to a declared field, preventing noisy startup errors in containerised environments that inject many platform variables.

3. **Secret wrapping** — `AZURE_CLIENT_SECRET` and `JWT_SECRET` are declared as `SecretStr`. Pydantic wraps the raw string so that `repr()` and logging output print `'**********'` rather than the actual value, protecting secrets from appearing in tracebacks or structured logs.

4. **`BASE_URL` and `TEAMS_WEBHOOK_URL` validation** — Both are declared as `AnyHttpUrl` (or `AnyHttpUrl | None` for the optional webhook). Pydantic validates the URL at parse time; a malformed value raises a `ValidationError` before the app serves any request.

5. **Cached accessor** — `get_settings()` is decorated with `@lru_cache(maxsize=1)`. The first call constructs the `Settings` object; every subsequent call returns the same instance from the cache. Dependency-injected routes receive the instance via `Depends(get_settings)` without paying re-parse cost.

```python
@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
```

Because `lru_cache` caches on argument identity and `get_settings` takes no arguments, the cache holds exactly one slot — effectively a lazy singleton.

#### Key design decisions

| Decision | Alternatives Considered | Why This Choice |
|---|---|---|
| `pydantic_settings.BaseSettings` | `python-decouple`, `dynaconf`, plain `os.environ` | Pydantic Settings gives schema validation, type coercion, and `SecretStr` for free; it integrates directly with FastAPI's `Depends` pattern |
| `@lru_cache(maxsize=1)` singleton | Module-level global, `functools.cached_property` | `lru_cache` on a function is trivially overridable in tests (`get_settings.cache_clear()`) without monkeypatching module globals |
| `SecretStr` for `AZURE_CLIENT_SECRET` and `JWT_SECRET` | Plain `str` | Prevents accidental secret exposure in logs and `repr` output; callers must call `.get_secret_value()` explicitly, making access intentional |
| `extra="ignore"` | `extra="forbid"` (strict mode) | Production containers inject many platform env vars; forbidding extras would cause spurious startup failures in those environments |
| `ENVIRONMENT: Literal["development", "staging", "production"]` | Plain `str` | Constrains the value to a known set at parse time, so feature flags keyed on `ENVIRONMENT` cannot silently match a misspelling |

#### Configuration

| Parameter | Type | Default | Effect |
|---|---|---|---|
| `DATABASE_URL` | `str` | **required** | SQLAlchemy async DSN passed to `create_async_engine`; must use an async driver (e.g. `postgresql+asyncpg://`) |
| `AZURE_TENANT_ID` | `str` | **required** | Used by the Azure AD OIDC flow to construct the token-validation endpoint |
| `AZURE_CLIENT_ID` | `str` | **required** | OAuth2 client ID for the registered Azure AD application |
| `AZURE_CLIENT_SECRET` | `SecretStr` | **required** | OAuth2 client secret; access via `.get_secret_value()` |
| `JWT_SECRET` | `SecretStr` | **required** | HMAC key for signing and verifying internal JWT tokens |
| `SMTP_HOST` | `str` | **required** | Hostname of the outbound mail relay |
| `SMTP_PORT` | `int` | `587` | TCP port for the SMTP connection (STARTTLS default) |
| `SMTP_FROM` | `str` | **required** | RFC 5321 envelope sender address for all outbound mail |
| `BASE_URL` | `AnyHttpUrl` | **required** | Public root URL of the application; used to construct magic-link and notification URLs |
| `APP_NAME` | `str` | `"Aion Bulletin"` | Display name used in email subjects and UI strings |
| `DEV_AUTH_BYPASS` | `bool` | `False` | When `True`, skips Azure AD token validation; must never be `True` in production |
| `ENVIRONMENT` | `Literal[...]` | `"development"` | Controls behaviour flags (e.g. verbose errors); valid values are `development`, `staging`, `production` |
| `STORAGE_PATH` | `str` | `"/data/attachments"` | Filesystem root for uploaded attachment files |
| `TEAMS_WEBHOOK_URL` | `AnyHttpUrl \| None` | `None` | If set, notifications are also dispatched to this Microsoft Teams incoming-webhook URL |

#### Error behavior

All errors arise at process startup when `get_settings()` is first called (typically during module import of `app.database` or the FastAPI `lifespan` hook).

| Condition | Exception | Notes |
|---|---|---|
| Required field absent from env and `.env` file | `pydantic_settings.ValidationError` | Lists every missing field; process exits before serving requests |
| `BASE_URL` or `TEAMS_WEBHOOK_URL` is not a valid HTTP URL | `pydantic.ValidationError` | Raised at `Settings()` construction time |
| `ENVIRONMENT` value not in `{"development", "staging", "production"}` | `pydantic.ValidationError` | Raised at `Settings()` construction time |

Callers that need to handle a missing configuration should do so by catching `ValidationError` in the application entry point. Feature code accessed via `get_settings()` may assume the settings object is valid by the time it is reachable.

---

### 2. `app/database.py` — Database Connectivity

#### Purpose

`database.py` creates the single shared SQLAlchemy async engine and session factory for the process, exposes the `Base` declarative base class that all ORM models inherit from, and provides `get_db()` — a FastAPI-compatible async generator that opens a session per request, auto-commits on clean exit, and rolls back on any exception. All ORM model files import `Base` from this module; all route handlers inject a session via `Depends(get_db)`. This satisfies REQ-916.

#### How it works

1. **Engine construction** — `create_async_engine` is called at module import time with the DSN from `get_settings().DATABASE_URL`. `echo=False` suppresses SQL logging by default (can be overridden for debugging). `pool_pre_ping=True` instructs the connection pool to issue a lightweight `SELECT 1` before lending a connection; stale connections dropped by the database or a network appliance are detected and replaced transparently rather than surfacing as `OperationalError` in a request handler.

2. **Session factory** — `async_sessionmaker` wraps the engine. `expire_on_commit=False` means ORM instances remain readable after `commit()` completes, which matters for FastAPI response serialisation: without this flag, accessing an attribute on a returned model after the session commits would trigger a lazy-load that fails in an async context.

3. **Declarative base** — `Base(DeclarativeBase)` is a plain subclass with no custom configuration. All table models in feature modules inherit from it, allowing Alembic and `Base.metadata.create_all()` to discover the full schema.

4. **`get_db()` dependency** — The generator opens a session via the context manager, yields it, then commits or rolls back in a `try/except`:

```python
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

The `raise` after rollback re-raises the original exception so FastAPI's exception handlers receive it unchanged. Route handlers therefore never need to call `commit()` or `rollback()` explicitly; the dependency manages the transaction boundary.

#### Key design decisions

| Decision | Alternatives Considered | Why This Choice |
|---|---|---|
| `pool_pre_ping=True` | Let pool recycle on `OperationalError` | Pre-ping detects broken connections before they reach application code, eliminating a class of mid-request errors in long-lived processes or after database restarts |
| `expire_on_commit=False` | Default (`True`) | FastAPI serialises the response model after the route function returns; with `expire_on_commit=True`, accessing ORM attributes at that point raises a `DetachedInstanceError` in async context |
| Auto-commit / auto-rollback in `get_db` | Explicit `commit()` in each route | Centralising transaction control removes boilerplate and ensures rollback happens even if a route handler raises an unexpected exception |
| Module-level engine and factory | Per-request engine creation | Engines are expensive to construct and hold the connection pool; sharing one engine across the process is the standard SQLAlchemy pattern |

#### Configuration

| Parameter | Type | Default | Effect |
|---|---|---|---|
| `DATABASE_URL` (from `Settings`) | `str` | **required** | Full async DSN; determines driver, host, port, and database name |
| `echo` | `bool` | `False` | When `True`, SQLAlchemy logs every SQL statement to stdout — change only for local debugging |
| `pool_pre_ping` | `bool` | `True` | Enables liveness check before each borrowed connection |
| `expire_on_commit` | `bool` | `False` | Controls whether ORM attributes expire after commit; set to `False` for async serialisation safety |

#### Error behavior

| Condition | Exception | Notes |
|---|---|---|
| Invalid or unreachable `DATABASE_URL` | `sqlalchemy.exc.OperationalError` | Raised on first query, not at engine creation; pre-ping will surface this at session acquisition time |
| Exception raised inside a route using `get_db` | Original exception, after `await session.rollback()` | The dependency rolls back and re-raises; the route sees the original exception unchanged |
| Commit failure (e.g. constraint violation) | `sqlalchemy.exc.IntegrityError` or subclass | Raised from `await session.commit()` inside the dependency; the session is left in a rolled-back state |

---

### 3. `app/enums.py` — Domain Enumerations

#### Purpose

`enums.py` defines the six closed-value sets that the domain model depends on: problem lifecycle states (`ProblemStatus`), user permission tiers (`UserRole`), notification subscription granularity (`WatchLevel`), notification event types (`NotificationType`), feed ordering modes (`SortMode`), and the commentable entity discriminator (`ParentType`). All enums inherit from both `str` and `Enum`, so their members serialise directly to and from JSON strings without a custom encoder. This satisfies REQ-156, REQ-114, REQ-300, REQ-310, REQ-170, and REQ-258.

#### Key type definitions

```python
class ProblemStatus(str, Enum):      # REQ-156
    open       = "open"
    claimed    = "claimed"
    solved     = "solved"
    accepted   = "accepted"
    duplicate  = "duplicate"

class UserRole(str, Enum):           # REQ-114
    user  = "user"
    admin = "admin"

class WatchLevel(str, Enum):         # REQ-300
    all_activity   = "all_activity"
    solutions_only = "solutions_only"
    status_only    = "status_only"
    none           = "none"

class NotificationType(str, Enum):   # REQ-310
    problem_claimed   = "problem_claimed"
    solution_posted   = "solution_posted"
    solution_accepted = "solution_accepted"
    comment_posted    = "comment_posted"
    status_changed    = "status_changed"
    problem_pinned    = "problem_pinned"
    upstar_received   = "upstar_received"
    mention           = "mention"

class SortMode(str, Enum):           # REQ-170
    top       = "top"
    new       = "new"
    active    = "active"
    discussed = "discussed"

class ParentType(str, Enum):         # REQ-258
    problem  = "problem"
    solution = "solution"
    comment  = "comment"
```

#### Key design decisions

| Decision | Alternatives Considered | Why This Choice |
|---|---|---|
| `str, Enum` dual inheritance | `IntEnum`, plain `Enum`, or `StrEnum` (Python 3.11+) | `str` mixin means `ProblemStatus.open == "open"` is `True`; SQLAlchemy stores the string value directly in VARCHAR columns; Pydantic serialises without a custom encoder; works on Python 3.10 |
| Member values match names exactly (e.g. `open = "open"`) | Human-readable labels, integer codes, UUIDs | Identical name/value strings are self-documenting in database rows and API payloads; no translation layer needed |
| Single file for all enums | One file per enum | All domain constants are discoverable in one place; the file is small enough that co-location adds no meaningful navigation cost |
| `WatchLevel.none` as an explicit member | Treating absence of a row as "no watch" | An explicit `none` level allows a user record to exist with a declared preference of "do not notify", distinguishing deliberate opt-out from a missing row |

---

### 4. `app/exceptions.py` — Application Exception Hierarchy

#### Purpose

`exceptions.py` defines a typed exception hierarchy rooted at `AppError` that maps each business-rule violation to a specific HTTP status code. Raising a typed exception in service or route code communicates the semantic failure precisely; the exception handlers registered in `app.main` translate each subclass to the correct HTTP response without requiring conditional logic scattered across routes. This keeps business-rule validation separate from HTTP serialisation. `AppError` itself inherits from `Exception` (not `HTTPException`) so the exception can be caught and re-raised at service boundaries without carrying HTTP concerns into domain logic.

#### Key type definitions

```python
class AppError(Exception):
    """Base application error."""

class ForbiddenTransitionError(AppError):   # REQ-156 -> HTTP 409
    def __init__(self, current: str, target: str): ...

class PinLimitExceededError(AppError):      # REQ-164 -> HTTP 409
    pass

class FileSizeLimitError(AppError):         # REQ-404 -> HTTP 413
    def __init__(self, file_size: int, max_size: int): ...

class FileTypeNotAllowedError(AppError):    # REQ-402 -> HTTP 422
    def __init__(self, content_type: str, filename: str): ...

class DuplicateVoteError(AppError):         # REQ-250 -> HTTP 409
    pass

class MagicLinkExpiredError(AppError):      # REQ-106 -> HTTP 410
    pass

class TenantMismatchError(AppError):        # REQ-102 -> HTTP 403
    pass
```

#### Key design decisions

| Decision | Alternatives Considered | Why This Choice |
|---|---|---|
| Inherit from `Exception`, not `HTTPException` | Subclass `HTTPException` directly with a `status_code` | Domain exceptions should not carry HTTP concepts; the mapping to status codes lives in exception handlers in `app.main`, keeping this module framework-agnostic |
| Structured `__init__` with named fields (`current`, `target`, `file_size`, etc.) | Plain string messages only | Named fields allow exception handlers and tests to inspect the values without parsing the message string; e.g. `ForbiddenTransitionError.current` |
| `pass` body for `PinLimitExceededError`, `DuplicateVoteError`, `MagicLinkExpiredError`, `TenantMismatchError` | Constructor with context fields | These failures are fully described by their type alone; no additional context is needed for the HTTP response or audit log |
| Single `AppError` root | Separate roots per domain area | A single root allows catch-all middleware to distinguish application errors from unexpected `Exception` instances without enumerating every subclass |

#### Error behavior

These classes are raised by service and route code; they are not raised internally by this module. The table below documents the intent of each class — what condition triggers it and what the registered handler in `app.main` should return.

| Exception | Raised When | Expected HTTP Response |
|---|---|---|
| `ForbiddenTransitionError` | A `ProblemStatus` state-machine transition is not permitted (e.g. `accepted` -> `open`) | `409 Conflict`; response body should include `current` and `target` fields |
| `PinLimitExceededError` | Pinning a problem would exceed the maximum number of simultaneous pins | `409 Conflict` |
| `FileSizeLimitError` | An uploaded file's byte length exceeds the configured maximum | `413 Content Too Large`; response body should include `file_size` and `max_size` |
| `FileTypeNotAllowedError` | An uploaded file's MIME type or extension is not on the allow-list | `422 Unprocessable Entity`; response body should include `content_type` and `filename` |
| `DuplicateVoteError` | A user attempts to upstar or upvote an entity they have already voted on | `409 Conflict` |
| `MagicLinkExpiredError` | A magic-link token is presented after its TTL has elapsed or after single use | `410 Gone` |
| `TenantMismatchError` | An authenticated user's Azure AD tenant does not match the configured `AZURE_TENANT_ID` | `403 Forbidden` |

Callers should catch specific subclasses rather than the `AppError` base where the error type matters for recovery logic. Middleware or global exception handlers should catch `AppError` as a fallback to ensure no subclass produces an unhandled 500.

---

### 5. `app/schemas.py` — Request and Response Schemas

#### Purpose

`schemas.py` defines every Pydantic `BaseModel` used as a FastAPI request body or response model. It establishes the validated contract between HTTP clients and the application: field-level constraints (minimum/maximum lengths, URL format) are declared here and enforced automatically by FastAPI before any route handler runs. The file also contains `CursorPage[T]`, the generic paginated-response envelope used by all list endpoints. This satisfies REQ-168, REQ-150/152/154, REQ-200/204, and REQ-258/260, among others.

#### Key type definitions

**Pagination envelope (REQ-168)**

```python
class CursorPage(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None
```

`CursorPage` is generic over `T`; callers instantiate it as `CursorPage[ProblemResponse]`, `CursorPage[SolutionResponse]`, etc. `next_cursor` is `None` when the caller has reached the last page.

**Auth schemas**

```python
class MagicLinkRequest(BaseModel):   # REQ-104
    email: str

class TokenPayload(BaseModel):       # REQ-108
    sub: str
    role: str
    exp: int
```

**Problem schemas (REQ-150, REQ-152, REQ-154)**

```python
class ProblemCreate(BaseModel):
    title: str = Field(..., min_length=5, max_length=200)
    description: str = Field(..., min_length=10)
    category_id: str
    tag_ids: list[str] = Field(default_factory=list)
    is_anonymous: bool = False
```

**Solution schemas (REQ-200, REQ-204)**

```python
class SolutionCreate(BaseModel):
    description: str = Field(..., min_length=10)
    git_link: AnyHttpUrl | None = None
    is_anonymous: bool = False
```

**Comment schemas (REQ-258, REQ-260)**

```python
class CommentCreate(BaseModel):
    body: str = Field(..., min_length=1, max_length=10000)
    parent_comment_id: str | None = None
    is_anonymous: bool = False

class CommentResponse(BaseModel):
    id: str
    author: UserResponse | None
    body: str
    is_anonymous: bool
    is_edited: bool
    created_at: datetime
    replies: list[CommentResponse] = Field(default_factory=list)

CommentResponse.model_rebuild()   # resolves the self-referential annotation
```

`CommentResponse` is self-referential (`replies: list[CommentResponse]`). The `from __future__ import annotations` at the top of the file makes all annotations lazy strings, so the forward reference does not raise a `NameError` at class definition time. `model_rebuild()` is called after the class is fully defined to resolve the deferred annotation and allow Pydantic to construct the recursive validator.

#### Key design decisions

| Decision | Alternatives Considered | Why This Choice |
|---|---|---|
| `from __future__ import annotations` + `model_rebuild()` for `CommentResponse` | Wrapping the type in a string literal (`"CommentResponse"`), using `Optional` with `update_forward_refs()` | The `__future__` import makes all annotations lazy uniformly; `model_rebuild()` is the Pydantic v2 API for resolving forward references after class creation |
| `CursorPage` generic over `T` rather than a concrete base | One envelope class per resource type, `Any` item type | A single generic class avoids duplication and produces accurate OpenAPI schemas when instantiated with a concrete type parameter |
| `AnyHttpUrl \| None` for `git_link` in `SolutionCreate` | `str \| None` | Pydantic validates and normalises the URL at parse time; malformed links are rejected before reaching service code |
| `tag_ids: list[str] = Field(default_factory=list)` | `tag_ids: list[str] = []` | Mutable default values shared across instances are a Python anti-pattern; `default_factory=list` creates a fresh list per instance (Pydantic enforces this but explicit factory is clearer) |
| `is_anonymous: bool = False` on create schemas | Separate anonymous-create endpoint | A single endpoint with a flag is simpler to document and test; the service layer conditionally nulls out the `author` field when `is_anonymous=True` |
| Separate `ProblemResponse` and `ProblemDetailResponse` (extends the former) | Single response model with all fields always present | List endpoints return the lighter `ProblemResponse`; the detail endpoint returns the richer subclass. Inheritance ensures the list schema stays a strict subset of the detail schema |

#### Error behavior

Schemas are purely declarative. Errors arise when FastAPI attempts to parse an incoming request body or when application code calls `Model(**data)` directly.

| Condition | Exception | Notes |
|---|---|---|
| Required field missing from request body | `pydantic.ValidationError` -> FastAPI returns `422 Unprocessable Entity` | FastAPI catches `ValidationError` automatically and formats the error response |
| `title` shorter than 5 characters in `ProblemCreate` | `pydantic.ValidationError` -> `422` | FastAPI includes field path and constraint in the response detail |
| `git_link` is not a valid HTTP URL in `SolutionCreate` | `pydantic.ValidationError` -> `422` | Pydantic's `AnyHttpUrl` validator rejects the value before service code is reached |
| `body` exceeds 10 000 characters in `CommentCreate` or `CommentUpdate` | `pydantic.ValidationError` -> `422` | `max_length` constraint enforced by Pydantic at parse time |
| `CommentResponse.model_rebuild()` not called before use | `pydantic.PydanticUserError` | Would occur if a module imported `CommentResponse` before module initialisation completed; the module-level call ensures this never happens in normal import order |

<!-- END VERBATIM: module-config.md -->

### 3.2 Authentication Subsystem

<!-- BEGIN VERBATIM: module-auth.md -->

**Spec coverage:** REQ-100, REQ-102, REQ-104, REQ-106, REQ-108, REQ-110, REQ-112, REQ-114, REQ-116, REQ-120, REQ-122

**Source files:**
- `app/auth/jwt.py`
- `app/auth/magic_link.py`
- `app/auth/oidc.py`
- `app/auth/dependencies.py`

---

### `app/auth/jwt.py` — JWT Token Management

#### Purpose

This module handles the creation, validation, and cookie lifecycle of the application's signed JSON Web Tokens (REQ-108). It is the single point of truth for token encoding parameters: the algorithm (`HS256`), the expiry window (8 hours), and the cookie name (`access_token`). All other auth pathways — OIDC callback and magic-link verification — terminate here to issue a token; all protected routes begin here to validate one.

#### How it works

1. **Token creation (`create_access_token`).** Accepts a `User` ORM object. Reads `JWT_SECRET` from `get_settings()` at call time (never at import time). Builds a payload with three application claims — `sub` (UUID string), `role` (string value of the `UserRole` enum), and standard `exp`/`iat` timestamps — then encodes it with `jose.jwt.encode` using `HS256`.

2. **Token validation (`decode_access_token`).** Accepts a raw token string. Calls `jose.jwt.decode` with the same secret and algorithm list. On success it constructs and returns a `TokenPayload` dataclass. Any validation failure — wrong signature, expired, missing claim — surfaces as a `jose.JWTError`; the function does not catch it.

3. **Cookie management (`set_auth_cookie`, `clear_auth_cookie`).** `set_auth_cookie` writes the token into an `HttpOnly`, `SameSite=Lax` cookie whose `Secure` flag is set to `True` in every environment except `"development"`. The cookie's `max_age` mirrors the token's 8-hour expiry. `clear_auth_cookie` calls `delete_cookie` with the same path to ensure browser removal.

```python
## create_access_token — core payload construction
now = datetime.now(timezone.utc)
expire = now + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
payload = {
    "sub": str(user.id),
    "role": user.role if isinstance(user.role, str) else user.role.value,
    "exp": expire,
    "iat": now,
}
return jwt.encode(payload, settings.JWT_SECRET.get_secret_value(), algorithm=ALGORITHM)
```

The `isinstance` guard on `user.role` handles callers that pass a pre-serialised string (e.g. in tests) alongside callers that pass the `UserRole` enum.

#### Key design decisions

| Decision | Alternatives Considered | Why This Choice |
|---|---|---|
| `HS256` symmetric signing | `RS256` asymmetric signing | The application has a single issuer and no external token consumers, so symmetric keys avoid key-pair management overhead while meeting REQ-108 explicitly. |
| 8-hour fixed expiry with no refresh | Short-lived tokens + refresh tokens | Reduces database round-trips and implementation surface area. Sessions are bounded by the workday; forced re-login is acceptable. |
| `HttpOnly` cookie as primary transport | `Authorization` header only | Prevents XSS token theft. Bearer header fallback (handled in `dependencies.py`) preserves API-client compatibility. |
| `Secure` flag suppressed only in `"development"` | Always `Secure` | Allows HTTP-only local dev servers without certificate setup, while production always enforces TLS. |
| Lazy `get_settings()` inside functions | Module-level constant | Enables settings override in tests without patching module globals. |

#### Configuration

| Parameter | Type | Default | Effect |
|---|---|---|---|
| `JWT_SECRET` | `SecretStr` (required) | none — must be set | HMAC signing key. Exposed via `settings.JWT_SECRET.get_secret_value()`. Short or guessable values break token integrity. |
| `ENVIRONMENT` | `str` | `"production"` | When set to `"development"`, the `Secure` cookie flag is omitted, allowing plain HTTP. Any other value forces `Secure=True`. |
| `ACCESS_TOKEN_EXPIRE_HOURS` | module constant (`int`) | `8` | Hard-coded in `jwt.py`. Not currently overridable via settings; change requires a code edit. |

#### Error behavior

| Error | When raised | What callers should expect |
|---|---|---|
| `jose.JWTError` | `decode_access_token` — token is expired, signature is invalid, required claims are absent, or the token string is malformed | Propagates uncaught. `get_current_user` in `dependencies.py` wraps this in a 401 `HTTPException`. Direct callers must handle `JWTError`. |
| No exception | `create_access_token`, `set_auth_cookie`, `clear_auth_cookie` | These functions are non-failable under normal conditions; a misconfigured or missing `JWT_SECRET` will raise a Pydantic validation error at settings load time, not here. |

---

### `app/auth/magic_link.py` — Passwordless Email Authentication

#### Purpose

This module implements the passwordless sign-in flow (REQ-104, REQ-106). When a user submits their email address, `send_magic_link` generates a one-time token, stores only its SHA-256 hash in the database, and emails a verification URL with the raw token. When the user clicks that URL, `verify_magic_link` hashes the incoming token, looks up the record, enforces expiry and single-use semantics, and returns a fully provisioned `User`. Storing only the hash means a database leak cannot be replayed without the original URL.

#### How it works

1. **Token generation and persistence (`send_magic_link`).** Generates a 32-byte URL-safe random token with `secrets.token_urlsafe`. Computes its SHA-256 hash via `_hash_token`. Creates a `MagicLink` record with `consumed=False`, a 15-minute `expires_at`, and — if the email belongs to an existing user — the user's `id`. Calls `db.flush()` to assign the record a primary key before emailing, ensuring the record is durable if the SMTP call fails mid-transaction.

2. **Email dispatch.** Constructs a plain-text `EmailMessage` whose body contains the full verification URL (`/auth/magic/verify?token=<raw_token>`). Sends it via `aiosmtplib.send` using STARTTLS on the configured SMTP host and port. The raw token travels only inside the email; the database row holds only the hash.

3. **Token verification (`verify_magic_link`).** Hashes the incoming raw token and queries for a matching `MagicLink` record. Raises `MagicLinkExpiredError` immediately if the record is absent, already consumed, or past `expires_at`. Sets `record.consumed = True` before touching the `User` table so that concurrent duplicate clicks cannot both succeed.

4. **User provisioning.** Follows a two-path fallback: if `record.user_id` is set and the user still exists, return that user directly. Otherwise query by `record.email`; if found, return the existing user (back-filling `user_id` on the link record). If neither lookup succeeds, create a new `User` with `role=UserRole.user`, `is_active=True`, and a `display_name` derived from the email local part.

```python
## verify_magic_link — consumed check and atomic mark
if record is None:
    raise MagicLinkExpiredError()

now = datetime.now(timezone.utc)
if record.consumed or record.expires_at.replace(tzinfo=timezone.utc) < now:
    raise MagicLinkExpiredError()

record.consumed = True  # mark before any user lookup
db.add(record)
```

The `replace(tzinfo=timezone.utc)` call normalises naive datetimes stored by some database backends before comparing to an aware `datetime.now(timezone.utc)`.

#### Key design decisions

| Decision | Alternatives Considered | Why This Choice |
|---|---|---|
| Store SHA-256 hash of token, not the raw token | Store raw token | Limits exposure if the `magic_links` table is compromised — the hash alone cannot be used to authenticate. |
| 15-minute expiry | 30-minute or 60-minute expiry | Short window reduces the phishing surface if an email is forwarded or an inbox is compromised. |
| `consumed` flag (single-use) | Time-window only | A token valid for 15 minutes could be replayed multiple times within that window; the flag eliminates that risk. |
| Provision user on first verification, not on link request | Create user at request time | Avoids polluting the user table with unverified email addresses. The `user_id` pre-fill on the record is an optimisation, not a guarantee. |
| `aiosmtplib` async SMTP | Synchronous `smtplib` via thread pool | Matches the async FastAPI runtime without blocking the event loop during network I/O. |

#### Configuration

| Parameter | Type | Default | Effect |
|---|---|---|---|
| `SMTP_HOST` | `str` (required) | none | Hostname of the SMTP relay. |
| `SMTP_PORT` | `int` (required) | none | Port for STARTTLS (typically 587). |
| `SMTP_FROM` | `str` (required) | none | Envelope and header `From` address. |
| `BASE_URL` | `str` (required) | none | Base URL prepended to `/auth/magic/verify`. Must be publicly reachable by email recipients. |
| `APP_NAME` | `str` | `"Aion Bulletin"` | Displayed in the email subject and body. |
| `MAGIC_LINK_EXPIRY_MINUTES` | module constant (`int`) | `15` | Hard-coded in `magic_link.py`. Not settable via environment; change requires a code edit. |

#### Error behavior

| Error | When raised | What callers should expect |
|---|---|---|
| `MagicLinkExpiredError` | `verify_magic_link` — token not found, already consumed, or past expiry | Callers (route handlers) should return a 400 or 401 response with a user-facing message. The error intentionally conflates "not found", "consumed", and "expired" to avoid oracle attacks. |
| `aiosmtplib.SMTPException` (or subclass) | `send_magic_link` — SMTP server unreachable, authentication failure, or rejected recipient | Propagates uncaught. The `MagicLink` record has already been flushed; callers that catch this exception may choose to delete or leave the orphaned record — it will simply expire unused. |
| `sqlalchemy.exc.IntegrityError` | `send_magic_link` or `verify_magic_link` — rare hash collision or concurrent flush on the same email | Propagates uncaught. Probability is negligible given 32-byte tokens; callers should let this surface as a 500. |

---

### `app/auth/oidc.py` — Azure AD OIDC Integration

#### Purpose

This module implements the Azure Active Directory OpenID Connect login flow (REQ-100, REQ-102, REQ-110, REQ-112, REQ-116). It owns the full OAuth 2.0 Authorization Code exchange: generating the redirect URL with a CSRF nonce, handling the callback, validating that the authenticated user belongs to the configured tenant, and provisioning or linking the application `User` record. The rest of the application never touches OAuth tokens directly; this module extracts and discards them after reading the identity claims.

#### How it works

1. **Lazy OAuth registry (`_get_oauth`).** The `OAuth` registry from `authlib` is module-level but initialised lazily on first call. This avoids reading `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, and `AZURE_TENANT_ID` at import time, which would break unit tests that patch `get_settings`. The registry is cached in the module-level `_oauth` variable after the first call.

2. **Login initiation (`initiate_login`).** Generates a 32-byte `state` nonce with `secrets.token_urlsafe`, stores it in the Starlette session under `"oauth_state"`, then calls `oauth.azure.authorize_redirect` to build and return the Azure AD authorisation URL. The route handler is responsible for issuing the actual HTTP redirect.

3. **Callback handling (`handle_callback`).** Calls `oauth.azure.authorize_access_token` to exchange the authorisation code. Identity claims are read from `userinfo` (if present) or `id_token`. The `tid` (tenant ID) claim is compared to `settings.AZURE_TENANT_ID`; a mismatch raises `TenantMismatchError` before any database work is done (REQ-102). The `oid` (object ID) and `email` claims are extracted and passed to `_provision_user`.

4. **User provisioning (`_provision_user`).** Executes a deterministic three-step lookup (REQ-110, REQ-112, REQ-116):

```python
## Step 1 — exact OID match (returning user on same browser)
stmt = select(User).where(User.azure_oid == oid)
result = await db.execute(stmt)
user = result.scalar_one_or_none()
if user is not None:
    return user

## Step 2 — email match (link OID to pre-existing magic-link account)
stmt = select(User).where(User.email == email)
result = await db.execute(stmt)
user = result.scalar_one_or_none()
if user is not None:
    user.azure_oid = oid          # back-fill OID for future fast path
    if display_name:
        user.display_name = display_name
    db.add(user)
    await db.flush()
    return user

## Step 3 — new user
user = User(email=email, display_name=display_name,
            role=UserRole.user, azure_oid=oid, is_active=True)
db.add(user)
await db.flush()
return user
```

New users always receive `role=UserRole.user`; role elevation is an out-of-band administrative action.

#### Key design decisions

| Decision | Alternatives Considered | Why This Choice |
|---|---|---|
| Lazy singleton `_oauth` registry | Re-initialise on each request; module-level eager init | Eager init breaks test patching. Per-request init is wasteful. Lazy singleton is the standard authlib pattern and is safe for async workloads. |
| Reject non-matching `tid` before provisioning | Log and continue; raise after provisioning | Failing fast on `tid` ensures no database writes occur for cross-tenant tokens, keeping the tenant boundary clean (REQ-102). |
| Three-step OID -> email -> create lookup | OID-only; always create | Email fallback links accounts created via magic-link before the user's first OIDC sign-in, avoiding duplicate records (REQ-112). |
| Back-fill `azure_oid` on email match | Require users to use one auth method only | Makes subsequent OIDC logins hit the faster OID index instead of re-doing the email scan (REQ-116). |
| `authlib` Starlette integration | `python-jose` manual OIDC; `msal` | `authlib` handles PKCE, state validation, and metadata discovery; `msal` is heavier and server-side-only. |

#### Configuration

| Parameter | Type | Default | Effect |
|---|---|---|---|
| `AZURE_CLIENT_ID` | `str` (required) | none | Application (client) ID registered in Azure AD. |
| `AZURE_CLIENT_SECRET` | `SecretStr` (required) | none | Client secret for the authorisation code exchange. |
| `AZURE_TENANT_ID` | `str` (required) | none | Expected `tid` claim value. Only users from this tenant are admitted (REQ-102). |
| `BASE_URL` | `str` (required) | none | Determines the `redirect_uri` sent to Azure (`<BASE_URL>/auth/callback`). Must match a registered Reply URL in the Azure app registration. |

#### Error behavior

| Error | When raised | What callers should expect |
|---|---|---|
| `TenantMismatchError` | `handle_callback` — `tid` claim does not equal `settings.AZURE_TENANT_ID` | Route handlers should return a 403 response. No user record is created or modified. |
| `authlib.integrations.base_client.errors.OAuthError` (or subclass) | `initiate_login` / `handle_callback` — Azure AD returns an error response, state mismatch, or PKCE failure | Propagates uncaught. Route handlers should treat this as a 400/502 and not expose the raw error message to end users. |
| `sqlalchemy.exc.IntegrityError` | `_provision_user` — concurrent OIDC logins for the same new user | Propagates uncaught; should surface as a 500. Rare in practice; resolved on the next login attempt. |

---

### `app/auth/dependencies.py` — FastAPI Auth Dependencies

#### Purpose

This module exposes the FastAPI dependency functions and type aliases that gate access to protected routes (REQ-108, REQ-114, REQ-120, REQ-122). It acts as the authorisation layer that sits between the HTTP request and the route handler: it validates tokens, loads the `User` from the database, enforces role requirements, and provides a controlled development bypass. Route handlers declare their access requirements by injecting `CurrentUser`, `AdminUser`, or calling `require_owner_or_admin` — they never interact with cookies, headers, or JWTs directly.

#### How it works

1. **Token extraction and user loading (`get_current_user`).** Checks the `access_token` cookie first, then falls back to the `Authorization: Bearer` header. If both are absent and `DEV_AUTH_BYPASS=True`, returns a hard-coded dev admin user (see step 5). If both are absent and the bypass is off, raises 401. Decodes the token via `decode_access_token`; any `JWTError` becomes a 401. Loads the `User` by UUID from the `sub` claim; raises 401 if the user is not found or `is_active` is `False`.

2. **Role enforcement (`require_admin`).** A thin dependency that calls `get_current_user` via `Depends`, then checks `user.role == UserRole.admin`. Returns the user unchanged if the check passes; raises 403 otherwise (REQ-114).

3. **Owner-or-admin check (`require_owner_or_admin`).** A plain async function (not a FastAPI dependency) called explicitly by route handlers when the protected resource has an owner. Raises 403 unless `str(user.id) == resource_owner_id` or `user.role == UserRole.admin` (REQ-122).

4. **Type aliases.** `CurrentUser = Annotated[User, Depends(get_current_user)]` and `AdminUser = Annotated[User, Depends(require_admin)]` let route handlers express their requirements as parameter type annotations, keeping route signatures readable.

5. **Dev bypass (`_get_or_create_dev_user`).** Active only when `DEV_AUTH_BYPASS=True` and no token is present (REQ-120). Looks up or creates a user with `email="dev@aion-bulletin.local"`, `role=UserRole.admin`, and `is_active=True`. Because this path is guarded by two conditions (no token AND bypass enabled), a real token always takes precedence even in development.

```python
## get_current_user — token extraction and bypass logic
token = request.cookies.get("access_token")
if token is None:
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]

if token is None and settings.DEV_AUTH_BYPASS:
    return await _get_or_create_dev_user(db)

if token is None:
    raise HTTPException(status_code=401, detail="Not authenticated")

try:
    payload = decode_access_token(token)
except JWTError:
    raise HTTPException(status_code=401, detail="Invalid or expired token")
```

#### Key design decisions

| Decision | Alternatives Considered | Why This Choice |
|---|---|---|
| Cookie-first, Bearer-header fallback | Header-only; cookie-only | Cookie-first prevents XSS token theft for browser clients; Bearer header retains API-client and Swagger UI compatibility without code duplication. |
| Dev bypass only when token is absent | Override any request when bypass is on | Ensures CI test runs with real tokens are not silently short-circuited by an accidentally set environment variable. |
| `require_owner_or_admin` as a plain function, not a dependency | Full `Depends` wiring with path parameter injection | Resource owner IDs are application-level concepts resolved after the route handler loads the resource; they are not available at dependency injection time. |
| `is_active` check on every request | Cache active status in the JWT | Allows administrators to deactivate accounts with immediate effect rather than waiting for token expiry. |
| `AdminUser` / `CurrentUser` type aliases | Repeated `Annotated[User, Depends(...)]` inline | Reduces boilerplate, enforces consistent dependency wiring across all routes, and makes access requirements self-documenting in function signatures. |

#### Configuration

| Parameter | Type | Default | Effect |
|---|---|---|---|
| `DEV_AUTH_BYPASS` | `bool` | `False` | When `True` and no token is present on the request, returns a dev admin user instead of raising 401. Must never be `True` in production. |
| `JWT_SECRET` | `SecretStr` (required) | none | Consumed indirectly via `decode_access_token`. A changed secret invalidates all outstanding tokens immediately. |
| `ENVIRONMENT` | `str` | `"production"` | Not read directly by this module, but affects the `Secure` cookie flag set by `jwt.set_auth_cookie` upstream. |

#### Error behavior

| Error | When raised | What callers should expect |
|---|---|---|
| `HTTPException(401, "Not authenticated")` | `get_current_user` — no token present and `DEV_AUTH_BYPASS=False` | FastAPI returns a 401 JSON response automatically. The route handler is not called. |
| `HTTPException(401, "Invalid or expired token")` | `get_current_user` — `decode_access_token` raises `JWTError` | FastAPI returns 401. Clients should redirect to the login flow to obtain a fresh token. |
| `HTTPException(401, "User not found or inactive")` | `get_current_user` — valid JWT but user row is absent or `is_active=False` | FastAPI returns 401. Indicates a deactivated account or a token issued before a user-deletion event. |
| `HTTPException(403, "Admin access required")` | `require_admin` — authenticated user's role is not `admin` | FastAPI returns 403. |
| `HTTPException(403, "You do not have permission...")` | `require_owner_or_admin` — user is neither the resource owner nor an admin | Route handlers that call this function receive the exception and allow it to propagate; FastAPI returns 403. |

<!-- END VERBATIM: module-auth.md -->


### 3.3 Data Model (ORM)

<!-- BEGIN VERBATIM: module-models.md -->

**Source:** `app/models/`
**Spec coverage:** REQ-104/106, REQ-110/112, REQ-150–166, REQ-200–212, REQ-258–264, REQ-300–320, REQ-400–406, REQ-468, REQ-474, REQ-476

---

### Purpose

This module defines every persistent entity in the Aion Bulletin system using SQLAlchemy declarative ORM mapped to a PostgreSQL database. It covers:

- **Identity & auth** — `User`, `MagicLink` (passwordless login tokens)
- **Content** — `Category`, `Tag`, `ProblemTag`, `Problem`, `ProblemEditHistory`, `Claim`, `Upstar` (the problem domain)
- **Solutions** — `Solution`, `SolutionVersion`, `SolutionUpvote`
- **Discussion** — `Comment` (threaded, attachable to problems or solutions)
- **File storage** — `Attachment` (polymorphic file references)
- **Engagement** — `Watch`, `Notification`, `NotificationPreference`
- **Moderation** — `Flag`, `AuditLog`
- **Operations** — `AppConfig` (runtime key/value settings)

All models inherit from `app.database.Base` (a SQLAlchemy `DeclarativeBase`).

---

### Schema Overview

#### `users` (REQ-110, REQ-112)

Represents a registered human user. All authorship and ownership relations across the system point back to this table.

```
id            UUID          PK, server_default gen_random_uuid()
email         VARCHAR       NOT NULL, UNIQUE, INDEX
display_name  VARCHAR       NOT NULL
role          VARCHAR       NOT NULL, default 'user'  -- enum: user | admin
azure_oid     VARCHAR       UNIQUE, NULLABLE           -- SSO subject claim
is_active     BOOLEAN       NOT NULL, default true
created_at    TIMESTAMPTZ   NOT NULL, server_default now()
updated_at    TIMESTAMPTZ   NULLABLE, onupdate now()
```

Relationships (outbound):
- `problems` → `Problem.author_id`
- `solutions` → `Solution.author_id`
- `comments` → `Comment.author_id`
- `notifications` → `Notification.recipient_id`
- `watches` → `Watch.user_id`

---

#### `magic_links` (REQ-104, REQ-106)

Stores short-lived, single-use tokens for passwordless email authentication. The raw token is never persisted; only its hash is stored.

```
id          UUID         PK, server_default gen_random_uuid()
token_hash  VARCHAR      NOT NULL, UNIQUE, INDEX
user_id     UUID         FK → users.id ON DELETE CASCADE, NULLABLE
             -- NULL while token is unverified (user may not exist yet)
email       VARCHAR      NOT NULL
expires_at  TIMESTAMPTZ  NOT NULL
consumed    BOOLEAN      NOT NULL, default false
created_at  TIMESTAMPTZ  NOT NULL, server_default now()
```

---

#### `categories` (REQ-150)

Organises problems into named groupings. Supports soft delete to preserve historical references.

```
id          UUID         PK, server_default gen_random_uuid()
name        VARCHAR      NOT NULL, UNIQUE
slug        VARCHAR      NOT NULL, UNIQUE
sort_order  INTEGER      NOT NULL, default 0
deleted_at  TIMESTAMPTZ  NULLABLE  -- soft-delete marker
created_at  TIMESTAMPTZ  NOT NULL, server_default now()
updated_at  TIMESTAMPTZ  NULLABLE, onupdate now()
```

Relationships: `problems` → `Problem.category_id`

---

#### `tags` (REQ-152)

Freeform labels applied to problems via a many-to-many join table.

```
id         UUID         PK, server_default gen_random_uuid()
name       VARCHAR      NOT NULL, UNIQUE
created_at TIMESTAMPTZ  NOT NULL, server_default now()
```

---

#### `problem_tags` (REQ-152)

Pure join table. Both columns are part of the composite primary key; both carry `ON DELETE CASCADE`.

```
problem_id  UUID  PK, FK → problems.id  ON DELETE CASCADE
tag_id      UUID  PK, FK → tags.id      ON DELETE CASCADE
```

---

#### `problems` (REQ-150–160)

The central entity of the bulletin board. Tracks status lifecycle, optional anonymity, pinning, and full-text search.

```
id             UUID         PK, server_default gen_random_uuid()
title          VARCHAR      NOT NULL
description    TEXT         NOT NULL
author_id      UUID         FK → users.id, NULLABLE  -- NULL on anonymous post
status         VARCHAR      NOT NULL, default 'open'  -- enum: open | claimed | solved | closed
category_id    UUID         FK → categories.id, NULLABLE
is_pinned      BOOLEAN      NOT NULL, default false
is_anonymous   BOOLEAN      NOT NULL, default false
activity_at    TIMESTAMPTZ  server_default now()  -- updated on new solutions/comments
search_vector  TSVECTOR     NULLABLE              -- populated by DB trigger or service layer
created_at     TIMESTAMPTZ  NOT NULL, server_default now()
updated_at     TIMESTAMPTZ  NULLABLE, onupdate now()
```

Indexes:
- `ix_problems_search_vector` — GIN index on `search_vector` for full-text search

Relationships: `author`, `category`, `tags` (M2M via `problem_tags`), `solutions`, `comments`, `claims`, `edit_history`, `upstars`, `watches`

---

#### `problem_edit_history` (REQ-162)

Immutable audit trail of problem edits. Each row is a point-in-time snapshot of the problem content before an edit.

```
id          UUID         PK, server_default gen_random_uuid()
problem_id  UUID         NOT NULL, FK → problems.id ON DELETE CASCADE
editor_id   UUID         NOT NULL, FK → users.id
snapshot    JSONB        NOT NULL  -- serialised pre-edit problem state
created_at  TIMESTAMPTZ  NOT NULL, server_default now()
```

---

#### `claims` (REQ-164)

Records that a user has claimed a problem (i.e., committed to solving it). Unique per `(user_id, problem_id)` pair.

```
id          UUID         PK, server_default gen_random_uuid()
problem_id  UUID         NOT NULL, FK → problems.id ON DELETE CASCADE
user_id     UUID         NOT NULL, FK → users.id
claimed_at  TIMESTAMPTZ  NOT NULL, server_default now()
created_at  TIMESTAMPTZ  NOT NULL, server_default now()
updated_at  TIMESTAMPTZ  NULLABLE, onupdate now()
```

Unique constraint: `uq_claim_user_problem (user_id, problem_id)`

---

#### `upstars` (REQ-166)

Tracks a user upvoting ("starring") a problem. Unique per `(user_id, problem_id)` pair.

```
id          UUID         PK, server_default gen_random_uuid()
user_id     UUID         NOT NULL, FK → users.id
problem_id  UUID         NOT NULL, FK → problems.id ON DELETE CASCADE
created_at  TIMESTAMPTZ  NOT NULL, server_default now()
```

Unique constraint: `uq_upstar_user_problem (user_id, problem_id)`

---

#### `solutions` (REQ-200–206)

A proposed solution to a problem. Content is versioned; the `current_version_id` pointer identifies the live version.

```
id                 UUID         PK, server_default gen_random_uuid()
problem_id         UUID         NOT NULL, FK → problems.id ON DELETE CASCADE
author_id          UUID         FK → users.id, NULLABLE  -- NULL on anonymous post
status             VARCHAR      NOT NULL, default 'pending'  -- pending | accepted | rejected
is_anonymous       BOOLEAN      NOT NULL, default false
current_version_id UUID         NULLABLE  -- denormalised pointer to SolutionVersion.id
created_at         TIMESTAMPTZ  NOT NULL, server_default now()
updated_at         TIMESTAMPTZ  NULLABLE, onupdate now()
```

Relationships: `problem`, `author`, `versions`, `comments`, `upvotes`

---

#### `solution_versions` (REQ-208)

Immutable versioned content for a solution. Version numbers are monotonically increasing and unique per solution.

```
id             UUID         PK, server_default gen_random_uuid()
solution_id    UUID         NOT NULL, FK → solutions.id ON DELETE CASCADE
version_number INTEGER      NOT NULL
description    TEXT         NOT NULL
git_link       VARCHAR      NULLABLE
created_by     UUID         NOT NULL, FK → users.id
created_at     TIMESTAMPTZ  NOT NULL, server_default now()
```

Unique constraint: `uq_solution_version_number (solution_id, version_number)`

---

#### `solution_upvotes` (REQ-212)

Tracks a user upvoting a solution. Unique per `(user_id, solution_id)` pair.

```
id          UUID         PK, server_default gen_random_uuid()
user_id     UUID         NOT NULL, FK → users.id
solution_id UUID         NOT NULL, FK → solutions.id ON DELETE CASCADE
created_at  TIMESTAMPTZ  NOT NULL, server_default now()
```

Unique constraint: `uq_solution_upvote_user_solution (user_id, solution_id)`

---

#### `comments` (REQ-258–264)

Threaded discussion entries, each anchored to a problem and optionally to a specific solution. Supports one level of reply nesting via the self-referential `parent_comment_id`.

```
id                UUID         PK, server_default gen_random_uuid()
problem_id        UUID         NOT NULL, FK → problems.id ON DELETE CASCADE
solution_id       UUID         FK → solutions.id ON DELETE CASCADE, NULLABLE
author_id         UUID         FK → users.id, NULLABLE  -- NULL on anonymous post
parent_comment_id UUID         FK → comments.id ON DELETE CASCADE, NULLABLE
body              TEXT         NOT NULL
is_anonymous      BOOLEAN      NOT NULL, default false
is_edited         BOOLEAN      NOT NULL, default false
created_at        TIMESTAMPTZ  NOT NULL, server_default now()
updated_at        TIMESTAMPTZ  NULLABLE, onupdate now()
```

The `backref="replies"` on `parent_comment` gives each comment access to its direct children.

---

#### `attachments` (REQ-400–406)

Polymorphic file references using an explicit type discriminator rather than per-type FK columns. The actual binary is stored externally (e.g., S3); this row records metadata and a storage path.

```
id            UUID         PK, server_default gen_random_uuid()
parent_type   VARCHAR      NOT NULL  -- enum: problem | solution | comment (ParentType)
parent_id     UUID         NOT NULL  -- ID of the owning entity (no FK constraint)
uploader_id   UUID         NOT NULL, FK → users.id
filename      VARCHAR      NOT NULL
content_type  VARCHAR      NOT NULL  -- MIME type
byte_size     INTEGER      NOT NULL
storage_path  VARCHAR      NOT NULL  -- provider-relative path (e.g., S3 key)
created_at    TIMESTAMPTZ  NOT NULL, server_default now()
updated_at    TIMESTAMPTZ  NULLABLE, onupdate now()
```

No database-level FK on `parent_id`; referential integrity is enforced at the application layer.

---

#### `watches` (REQ-300–308)

Records that a user is watching a problem for activity notifications. The `level` column controls notification granularity.

```
id          UUID         PK, server_default gen_random_uuid()
user_id     UUID         NOT NULL, FK → users.id
problem_id  UUID         NOT NULL, FK → problems.id ON DELETE CASCADE
level       VARCHAR      NOT NULL, default 'all_activity'  -- WatchLevel enum
created_at  TIMESTAMPTZ  NOT NULL, server_default now()
updated_at  TIMESTAMPTZ  NULLABLE, onupdate now()
```

Unique constraint: `uq_watch_user_problem (user_id, problem_id)`

---

#### `notifications` (REQ-310–316)

In-app notification events delivered to a recipient. References optional problem and solution context for deep-linking.

```
id            UUID         PK, server_default gen_random_uuid()
recipient_id  UUID         NOT NULL, FK → users.id
type          VARCHAR      NOT NULL  -- NotificationType enum
problem_id    UUID         FK → problems.id, NULLABLE
solution_id   UUID         FK → solutions.id, NULLABLE
actor_id      UUID         NOT NULL, FK → users.id  -- user who triggered the event
is_read       BOOLEAN      NOT NULL, default false
created_at    TIMESTAMPTZ  NOT NULL, server_default now()
updated_at    TIMESTAMPTZ  NULLABLE, onupdate now()
```

---

#### `notification_preferences` (REQ-318–320)

Per-user opt-in/out for each notification type. Uses a composite primary key so no surrogate ID is needed.

```
user_id  UUID     PK, FK → users.id ON DELETE CASCADE
type     VARCHAR  PK  -- mirrors NotificationType enum values
enabled  BOOLEAN  NOT NULL, default true
```

---

#### `flags` (REQ-468)

Records user-submitted moderation reports against any content type. Resolution state and admin notes are tracked on the same row.

```
id               UUID         PK, server_default gen_random_uuid()
content_type     VARCHAR      NOT NULL  -- 'problem' | 'solution' | 'comment'
content_id       UUID         NOT NULL  -- ID of flagged entity (no FK constraint)
reporter_id      UUID         NOT NULL, FK → users.id
reason           TEXT         NOT NULL
status           VARCHAR      NOT NULL, default 'pending'  -- pending | resolved | dismissed
resolution_note  TEXT         NULLABLE
resolved_by      UUID         FK → users.id, NULLABLE
created_at       TIMESTAMPTZ  NOT NULL, server_default now()
```

---

#### `audit_logs` (REQ-474)

Append-only log of privileged administrative actions (e.g., de-anonymise, force-close, role changes). The `metadata` JSONB column captures action-specific detail without schema churn.

```
id           UUID         PK, server_default gen_random_uuid()
admin_id     UUID         NOT NULL, FK → users.id
action       TEXT         NOT NULL  -- free-form action label
target_type  VARCHAR      NOT NULL  -- entity type affected
target_id    UUID         NOT NULL  -- ID of affected entity (no FK constraint)
metadata     JSONB        NULLABLE  -- arbitrary action-specific context
created_at   TIMESTAMPTZ  NOT NULL, server_default now()
```

Note: The Python attribute is `metadata_` to avoid collision with SQLAlchemy's reserved `metadata` name; the column name in the database is `metadata`.

---

#### `app_config` (REQ-476)

Simple key/value store for runtime-adjustable application settings. The primary key is the string key itself; there is no surrogate ID.

```
key        VARCHAR      PK
value      TEXT         NOT NULL
updated_at TIMESTAMPTZ  server_default now(), onupdate now()
```

---

### Key Design Decisions

| Decision | Alternatives Considered | Why This Choice |
|---|---|---|
| **UUID primary keys on all tables** | Auto-increment integers | UUIDs are generated server-side (`gen_random_uuid()`), preventing ID enumeration attacks and allowing records to be created before DB round-trips. Safe to expose in URLs. |
| **Soft delete on `Category`** | Hard delete | Problems reference `category_id`; hard-deleting a category would orphan those FKs or require cascading nulls. Soft delete preserves historical integrity while hiding categories from new-problem selection. |
| **`TSVECTOR search_vector` on `Problem`** | `ILIKE` / `pg_trgm` | A dedicated `TSVECTOR` column with a GIN index gives O(log n) full-text search across title + description with PostgreSQL's ranking functions, far outperforming sequential `ILIKE` scans at scale. |
| **`JSONB snapshot` in `ProblemEditHistory`** | Separate delta columns | A JSONB blob captures the entire pre-edit state in one row without schema coupling to the `Problem` column set. New columns on `Problem` require no migration to `problem_edit_history`. |
| **`JSONB metadata` in `AuditLog`** | Separate audit-detail tables per action type | The action space for admin operations is open-ended. JSONB avoids an explosion of sparse tables while remaining queryable with PostgreSQL JSON operators. |
| **Polymorphic `parent_type`/`parent_id` on `Attachment` and `Flag`** | Per-type FK columns | Avoids wide nullable-FK schemas (e.g., `problem_id`, `solution_id`, `comment_id` with CHECK exactly one non-null). The trade-off — no DB-level referential integrity — is accepted because attachments and flags are append-only and the service layer enforces validity. |
| **`current_version_id` denormalisation on `Solution`** | Always join to `MAX(version_number)` | Eliminates a `MAX` subquery on every solution read. The pointer is updated atomically with new version creation. |
| **Composite PK on `NotificationPreference`** | Surrogate UUID PK | The pair `(user_id, type)` is the natural key; a surrogate PK would be meaningless and wasteful. The composite PK also enforces uniqueness without a separate constraint. |
| **`author_id` nullable on `Problem`, `Solution`, `Comment`** | Separate anonymous content table | Allows anonymous posting within the same table. `is_anonymous` controls display; `author_id` is stored for admin de-anonymisation (REQ-474) but hidden from regular reads. |
| **`token_hash` on `MagicLink` (not raw token)** | Storing raw token | A compromised DB read cannot replay login tokens. The raw token travels only in the email and over TLS; only its SHA-256 (or equivalent) hash persists. |

---

### Configuration

`app/models/app_config.py` exports one module-level constant:

```python
ALLOWED_CONFIG_KEYS = frozenset([
    "max_pin_count",          # Maximum number of simultaneously pinned problems
    "claim_expiry_days",      # Days before an uncompleted claim auto-expires
    "magic_link_ttl_minutes", # Lifetime of a magic-link token
    "auto_watch_default_level", # Default WatchLevel applied on problem creation
])
```

Any write to `app_config` must validate that `key` is a member of this set. The frozenset lives in the model module so it is importable by service and router layers without creating a circular dependency.

---

### Relationship Map

```
User ──────────────────────────────────────────────────────┐
 │ 1:N  problems (author_id)                               │
 │ 1:N  solutions (author_id)                              │
 │ 1:N  comments (author_id)                               │
 │ 1:N  notifications (recipient_id)                       │
 │ 1:N  watches                                            │
 └──────────────────────────────────────────────────────┐  │
                                                         │  │
Category ──1:N──> Problem <──M:N──> Tag                  │  │
                    │   (via problem_tags)                │  │
                    │                                     │  │
                    ├──1:N──> ProblemEditHistory ←── User (editor_id)
                    ├──1:N──> Claim             ←── User
                    ├──1:N──> Upstar            ←── User
                    ├──1:N──> Watch             ←── User ─┘
                    ├──1:N──> Notification (problem_id, optional)
                    ├──1:N──> Attachment (parent_type='problem')
                    ├──1:N──> Flag (content_type='problem')
                    │
                    └──1:N──> Solution ──────────────────────┐
                                 │                           │
                                 ├──1:N──> SolutionVersion ←─┤ (created_by)
                                 ├──1:N──> SolutionUpvote ←── User
                                 ├──1:N──> Comment
                                 ├──1:N──> Notification (solution_id, optional)
                                 ├──1:N──> Attachment (parent_type='solution')
                                 └──1:N──> Flag (content_type='solution')

Comment ─────────────────────────────────────────────────────┐
 │ self-ref parent_comment_id (replies)                       │
 ├──1:N──> Attachment (parent_type='comment')                 │
 └──1:N──> Flag (content_type='comment')                      │
                                                              │
MagicLink ──FK──> User (user_id, nullable)                    │
AuditLog  ──FK──> User (admin_id)                             │
Flag      ──FK──> User (reporter_id, resolved_by)             │
Attachment ──FK──> User (uploader_id)                         │
NotificationPreference ──FK──> User (user_id) ────────────────┘
AppConfig  (standalone — no FK relationships)
```

**Cascade behaviour summary:**

- Problem deletion cascades to: `ProblemEditHistory`, `Claim`, `Upstar`, `Watch`, `ProblemTag`, `Solution`, `Comment`
- Solution deletion cascades to: `SolutionVersion`, `SolutionUpvote`, `Comment`
- Comment deletion cascades to: child `Comment` rows (replies)
- User deletion cascades to: `MagicLink`, `NotificationPreference`
- Tag deletion cascades to: `ProblemTag`
- `Attachment`, `Flag`, `AuditLog` — no DB cascade; `parent_id`/`content_id`/`target_id` are unkeyed UUIDs managed at the application layer

<!-- END VERBATIM: module-models.md -->

### 3.4 Problem Management

<!-- BEGIN VERBATIM: module-problems.md -->

### Module Reference: Problem Management

---

### Purpose

The Problem Management module is the core domain layer of the Aion Bulletin application. It owns the full lifecycle of a *problem* — a user-submitted issue that can be discovered, claimed, solved, and accepted by the community. Specifically, the module is responsible for: creating problems with category and tag associations (with optional anonymous authorship); enforcing a finite-state machine (FSM) that governs valid status transitions; allowing any authenticated user to toggle a claim on a problem; allowing administrators to pin up to three problems globally; recording an immutable snapshot-based edit history on every field change; and serving a cursor-paginated, multi-sort feed that is the primary read path for the UI. The module is split across three files: `app/services/problems.py` (write operations), `app/services/feed.py` (read / pagination), and `app/routes/problems.py` (HTTP routing and authorization).

---

### How It Works

#### 1. Creating a Problem (REQ-150, REQ-152, REQ-154)

`create_problem(db, user_id, data: ProblemCreate) -> Problem`

1. Validates that the referenced `category_id` exists and is not soft-deleted.
2. If `data.tag_ids` is non-empty, validates all tag UUIDs exist via a single `COUNT` query; raises `ValueError` if any are missing.
3. Instantiates a `Problem` row with `status=ProblemStatus.open` and the caller-supplied `is_anonymous` flag. The author identity is always stored in `author_id`; the flag only controls whether the author is surfaced in responses.
4. Calls `db.flush()` to materialize `problem.id`, then bulk-inserts `ProblemTag` association rows for each tag.
5. Returns the unserialized `Problem` ORM object. The route layer (`create_problem_route`) immediately calls `get_problem` to produce the full `ProblemDetailResponse`.

#### 2. Status FSM (REQ-156)

`transition_status(db, problem_id, target: ProblemStatus, actor_id) -> Problem`

Permitted transitions are declared in `ALLOWED_TRANSITIONS`, a dict keyed by `(current_status, target_status)` tuples. Each value is a predicate `lambda actor, problem -> bool` evaluated at runtime.

```python
ALLOWED_TRANSITIONS = {
    (ProblemStatus.open,    ProblemStatus.claimed):    lambda actor, problem: True,
    (ProblemStatus.open,    ProblemStatus.duplicate):  lambda actor, problem: actor.role == UserRole.admin,
    (ProblemStatus.claimed, ProblemStatus.open):       lambda actor, problem: True,
    (ProblemStatus.claimed, ProblemStatus.solved):     lambda actor, problem: True,
    (ProblemStatus.solved,  ProblemStatus.accepted):   lambda actor, problem: (
        str(actor.id) == str(problem.author_id) or actor.role == UserRole.admin
    ),
    (ProblemStatus.solved,  ProblemStatus.open):       lambda actor, problem: (
        str(actor.id) == str(problem.author_id) or actor.role == UserRole.admin
    ),
}
```

Full transition table:

| From       | To         | Who may trigger                        |
|------------|------------|----------------------------------------|
| `open`     | `claimed`  | Any authenticated user                 |
| `open`     | `duplicate`| Admin only                             |
| `claimed`  | `open`     | Any authenticated user (release)       |
| `claimed`  | `solved`   | Any authenticated user                 |
| `solved`   | `accepted` | Problem author or admin                |
| `solved`   | `open`     | Problem author or admin (reopen)       |

Any `(current, target)` pair absent from the table raises `ForbiddenTransitionError`. A pair present in the table whose predicate returns `False` also raises `ForbiddenTransitionError`. On success, `problem.activity_at` is updated to `func.now()` before `db.flush()`.

### 3. Claim Toggle (REQ-158, REQ-160)

`claim_problem(db, problem_id, user_id) -> Claim | None`

The operation is a pure toggle:

1. Load the problem; raise `ValueError("Problem not found")` if absent.
2. Query the `Claim` table for a row matching `(problem_id, user_id)`.
3. If a row exists — delete it, flush, and return `None` (claim released).
4. If no row exists — insert a new `Claim`, flush, update `problem.activity_at`, and return the `Claim` object.

The HTTP layer (`POST /problems/{id}/claim`) maps the `None` return to `{"claimed": false}` and a live `Claim` to `{"claimed": true, "claim_id": "..."}`. No status FSM is invoked by claiming; the status must be transitioned separately.

#### 4. Pin Toggle (REQ-164)

`pin_problem(db, problem_id, admin_id) -> Problem`

Pin is guarded by the constant `MAX_PINNED = 3`.

1. Load the problem; raise `ValueError` if absent.
2. If `problem.is_pinned` is `True` — set it to `False`, flush, return. No limit check on unpin.
3. If `problem.is_pinned` is `False` — count rows in `Problem` where `is_pinned IS TRUE`. If the count is `>= MAX_PINNED`, raise `PinLimitExceededError`. Otherwise set `is_pinned = True`, flush, return.

The route (`POST /problems/{id}/pin`) is gated by the `AdminUser` dependency; non-admins receive `403` before the service is called.

#### 5. Edit History (REQ-162, REQ-166)

`update_problem(db, problem_id, editor_id, updates: dict) -> Problem`

Only three fields are editable: `title`, `description`, and `category_id` (defined in `editable_fields = {"title", "description", "category_id"}`).

```python
## Capture snapshot of old values before applying updates
snapshot: dict[str, Any] = {}
for field in editable_fields:
    if field in updates:
        old_value = getattr(problem, field)
        snapshot[field] = str(old_value) if old_value is not None else None

## Record history before mutating
history = ProblemEditHistory(
    problem_id=prob_uuid,
    editor_id=editor_uuid,
    snapshot=snapshot,          # JSON blob of pre-edit values
)
db.add(history)

## Apply updates
for field, value in updates.items():
    if field in editable_fields:
        if field == "category_id" and value is not None:
            value = uuid.UUID(value) if isinstance(value, str) else value
        setattr(problem, field, value)

problem.activity_at = func.now()
await db.flush()
```

`snapshot` stores only the fields that are actually changing, keyed by field name, values serialized to strings. If `updates` contains no editable fields, the function returns early without a database write. The number of history entries is surfaced as `edit_history_count` in the detail response (REQ-166); the route exposes the full `edit_history` relationship via `get_problem` / `ProblemDetailResponse`.

The `PATCH /problems/{id}` route enforces ownership: it loads the problem row, extracts `author_id`, and calls `require_owner_or_admin` before delegating to the service.

#### 6. Cursor-Based Feed (REQ-168, REQ-170, REQ-506)

`get_feed(db, *, sort, filter_status, category_id, tag_ids, is_claimed, cursor, limit) -> CursorPage[ProblemResponse]`

The feed query is assembled in four composable phases:

**Phase 1 — Pinned items (first page only).** When `cursor is None`, a separate query fetches all pinned problems that pass the active filters. These are prepended to the result and do not consume slots from `limit`.

**Phase 2 — Base query.** Selects unpinned problems (`is_pinned IS FALSE`) with `selectinload` for author, category, tags, and solutions. Filters are applied via `_apply_filters`, which ANDs conditions for status, category, per-tag subquery existence, and claim presence.

**Phase 3 — Sort via `_apply_sort`.** Four sort modes are supported:

| Sort mode   | Primary sort column                     | Secondary tie-break |
|-------------|-----------------------------------------|---------------------|
| `new`       | `Problem.created_at DESC`               | `Problem.id DESC`   |
| `top`       | Correlated `COUNT(Upstar)` subquery DESC| `Problem.id DESC`   |
| `active`    | `Problem.activity_at DESC`              | `Problem.id DESC`   |
| `discussed` | Correlated `COUNT(Comment)` subquery DESC | `Problem.id DESC` |

For `top` and `discussed`, the subquery column is added via `add_columns` so its value is returned alongside the ORM object for use in cursor encoding.

**Phase 4 — Keyset cursor via `_apply_cursor`.** The cursor is a base64-encoded JSON payload produced by `encode_cursor(sort_value, row_id)`. On decoding, `_apply_cursor` appends a compound `WHERE` clause:

```python
## Example for SortMode.new:
stmt = stmt.where(
    (Problem.created_at < cursor_value)
    | ((Problem.created_at == cursor_value) & (Problem.id < cursor_id))
)
```

This ensures strict, stable ordering without offset drift. For `top` and `discussed`, the same correlated subquery used in `ORDER BY` is replicated in the `WHERE` clause.

The function fetches `limit + 1` rows. If more than `limit` rows are returned, `has_next = True` and a `next_cursor` is encoded from the last row's sort value and ID; the extra row is dropped from the response. The final `CursorPage` contains `items: list[ProblemResponse]` (pinned first, then paginated) and `next_cursor: str | None`.

---

### Key Design Decisions

| Decision | Alternatives Considered | Why This Choice |
|---|---|---|
| FSM transitions declared as a static dict of lambdas (`ALLOWED_TRANSITIONS`) | Class-based state machine; per-status method dispatch; inline `if/elif` chains | The dict makes the complete transition graph inspectable in one place without framework dependencies. Predicates stay co-located with the transitions they govern. |
| Claim as a toggle (idempotent POST) rather than separate POST/DELETE endpoints | `POST /claim` + `DELETE /claim`; claim stored on the `Problem` row directly | A single idempotent endpoint simplifies client retry logic. A separate `Claim` table supports multiple concurrent claimants and preserves the claim record for audit. |
| Pin limit enforced at write time with a `COUNT` query | Database `CHECK` constraint; application-level cache | A `COUNT` query at write time is simple, correct under concurrent load (transactions serialize the count and the write), and does not require DDL changes to adjust `MAX_PINNED`. |
| Edit history stores a snapshot of *old* values (pre-edit) | Store new values; store full diffs; event-sourcing log | Pre-edit snapshots allow point-in-time reconstruction and are smaller than full row copies. Callers can determine "what it was" without re-querying. |
| Cursor pagination encodes `(sort_value, id)` as opaque base64-JSON | Integer offset; page number; opaque token backed by server-side state | Keyset pagination avoids offset drift when rows are inserted between pages. Encoding the sort value in the cursor means the server is stateless — no session or cache needed. |
| Anonymous posting stored as `is_anonymous` flag; `author_id` is always recorded | Null `author_id` for anonymous posts; separate anonymous post table | Retaining `author_id` allows admins to audit authorship and allows the author to reclaim or accept their own problem. The flag controls presentation only. |
| Pinned problems returned outside the pagination window (prepended, cursor = None only) | Include pinned in normal result set with `is_pinned` sort booster; separate endpoint | Prepending pinned items on the first page guarantees they are always visible regardless of sort mode while not polluting the cursor state for subsequent pages. |

---

### Configuration

| Parameter | Type | Default | Effect |
|---|---|---|---|
| `MAX_PINNED` | `int` (module constant in `problems.py`) | `3` | Maximum number of simultaneously pinned problems globally. `pin_problem` raises `PinLimitExceededError` when the count of pinned rows would exceed this value. |
| `limit` (feed query param) | `int`, 1–50 | `20` | Number of non-pinned problems returned per page. The service hard-caps at `min(limit, 50)` regardless of the caller's requested value. |
| `sort` (feed query param) | `SortMode` enum: `new`, `top`, `active`, `discussed` | `new` | Determines the primary sort column and the keyset cursor encoding strategy. |
| `filter_status` (feed query param, alias `status`) | `ProblemStatus` enum or `null` | `null` (no filter) | When set, restricts the feed to problems in the specified status. Applies to both pinned and unpinned result sets. |
| `category_id` (feed query param) | UUID string or `null` | `null` | Filters the feed to problems belonging to a single category. |
| `tag_ids` (feed query param) | Comma-separated UUID strings or `null` | `null` | AND-filter: problems must carry all specified tags. Each tag ID generates an independent subquery existence check. |
| `is_claimed` (feed query param) | `bool` or `null` | `null` | When `true`, restricts to problems with at least one active claim. When `false`, restricts to unclaimed problems. |

---

### Error Behavior

#### `app/services/problems.py`

| Situation | Exception raised | HTTP status at route layer |
|---|---|---|
| `category_id` does not exist or is soft-deleted | `ValueError("Category {id} does not exist")` | `400 Bad Request` |
| One or more `tag_ids` do not exist | `ValueError("One or more tags do not exist")` | `400 Bad Request` |
| `problem_id` not found in any service function | `ValueError("Problem not found")` | `404 Not Found` (routes map `ValueError` from `get_problem` / `transition_status` / `claim_problem` / `pin_problem` explicitly) |
| `actor_id` not found in `transition_status` | `ValueError("Actor not found")` | `404 Not Found` |
| Transition not in `ALLOWED_TRANSITIONS` | `ForbiddenTransitionError(current, target)` | The route re-raises as-is; callers should expect `ForbiddenTransitionError` or wrap in a `try/except` block. The route currently propagates this as an unhandled exception (no explicit catch), resulting in `500` unless the framework maps it. |
| Transition predicate returns `False` | `ForbiddenTransitionError(current, target)` | Same as above. |
| Pin limit reached (`pinned_count >= MAX_PINNED`) | `PinLimitExceededError(message)` | The route does not catch `PinLimitExceededError`; callers should expect this exception to propagate as `500` unless added to the error handler. |
| `update_problem` called with no editable fields | Returns the unmodified `Problem` (no exception) | Route returns `400 Bad Request` from a pre-check before calling the service; the service itself is silent. |

#### `app/services/feed.py`

| Situation | Exception raised | HTTP status |
|---|---|---|
| `cursor` string is malformed (not valid base64-JSON or missing required keys) | `HTTPException(400, "Malformed cursor")` raised inside `decode_cursor` | `400 Bad Request` |
| `category_id` or `tag_ids` contain non-UUID strings | `ValueError` from `uuid.UUID(...)` inside `_apply_filters` | Propagates as `500` unless caught upstream; callers should validate UUIDs before passing to the service. |

#### Route-layer behavior (`app/routes/problems.py`)

- `POST /problems` — catches `ValueError` from `create_problem`, returns `400`.
- `GET /problems/{id}` — catches `ValueError` from `get_problem`, returns `404`. Authentication failure is silently swallowed so unauthenticated users can read problems; viewer-specific flags (`is_upstarred`, `is_claimed`) will be `false`.
- `PATCH /problems/{id}` — returns `404` if the problem row is missing before the ownership check; returns `400` on empty payload; catches `ValueError` from `update_problem`.
- `POST /problems/{id}/status` — catches `ValueError` from `transition_status`, returns `404`; does not catch `ForbiddenTransitionError`.
- `POST /problems/{id}/claim` — catches `ValueError`, returns `404`.
- `POST /problems/{id}/pin` — gated by `AdminUser` dependency (returns `403` for non-admins); catches `ValueError`, returns `404`; does not catch `PinLimitExceededError`.

<!-- END VERBATIM: module-problems.md -->

### 3.5 Solution Management

<!-- BEGIN VERBATIM: module-solutions.md -->

### Module Reference: Solution Management

**File locations**

- Service layer: `app/services/solutions.py`
- Route layer: `app/routes/solutions.py`

**Requirements covered:** REQ-200, REQ-202, REQ-204, REQ-206, REQ-208, REQ-210, REQ-212

---

### Purpose

The Solution Management module handles the full lifecycle of solutions posted in response to problems on the Aion Bulletin board. Its responsibilities are:

- Accepting new solutions from authenticated users, with optional anonymity (REQ-200, REQ-204).
- Listing all solutions for a given problem, with configurable sort order (REQ-202).
- Enforcing an append-only versioning model: solution text is never edited in place; each revision creates a new `SolutionVersion` row (REQ-206, REQ-208).
- Exposing the complete ordered revision history for any solution (REQ-212).
- Managing solution acceptance: marking one solution as the accepted answer for a problem, and retracting that acceptance, as an atomic swap that keeps at most one accepted solution per problem (REQ-210).

---

### How It Works

#### Posting a solution (REQ-200, REQ-204)

`POST /problems/{problem_id}/solutions` — requires authentication.

The service function `create_solution` runs inside a single database transaction:

1. Loads the target `Problem` row and confirms it exists and is not in a terminal status (`accepted` or `duplicate`). Either condition raises `ValueError`, which the route translates to `HTTP 400`.
2. Inserts a `Solution` row with `status="pending"` and the caller-supplied `is_anonymous` flag.
3. Flushes to obtain the new `solution.id`, then inserts a `SolutionVersion` row with `version_number=1` carrying the description and optional `git_link`.
4. Sets `solution.current_version_id` to the new version's ID.
5. Updates `problem.activity_at` to the current server timestamp.

Callers set `is_anonymous=true` in the request body to hide their identity from other users (REQ-204). The author field in the response is suppressed for anonymous solutions unless the viewer is the author or an admin (see anonymous masking below).

#### Listing solutions (REQ-202)

`GET /problems/{problem_id}/solutions` — authentication optional.

The service function `list_solutions` accepts a `sort` parameter:

- `default` (the standard mode): accepted solutions sort first, then remaining solutions sort by upvote count descending. The database query orders by `status == "accepted"` ascending (placing accepted first) and `created_at` descending; a subsequent in-memory stable sort by `(is_accepted, -upvote_count)` finalises the order, because upvote counts are derived from a loaded relationship rather than a SQL aggregate.
- `newest`: orders entirely by `created_at DESC` in the database, with no secondary in-memory step.

The route exposes the sort parameter as the enum `SolutionSortMode` (`default` | `newest`).

#### Immutable versioning (REQ-206, REQ-208)

`POST /solutions/{solution_id}/versions` — requires authentication.

Every revision is a new append-only `SolutionVersion` row; the original row is never mutated. `create_version` computes the next version number by querying `MAX(version_number)` for the solution and adding one. After inserting the new row, it updates `solution.current_version_id` to point at it. All reads (get, list) resolve the current content through `current_version_id`, falling back to the highest-numbered version if that pointer is unset.

Direct editing is explicitly blocked at the route layer: `PATCH /solutions/{solution_id}` and `PUT /solutions/{solution_id}` both return `HTTP 405 Method Not Allowed` with a message directing callers to the versioning endpoint.

#### Version history (REQ-212)

`GET /solutions/{solution_id}/versions` — authentication not required.

`list_versions` returns all `SolutionVersion` rows for the solution ordered by `version_number ASC`. Each entry includes `id`, `version_number`, `description`, `git_link`, `created_by`, and `created_at`. The solution must exist; a missing solution raises `ValueError`, translated to `HTTP 404`.

#### Accepting a solution (REQ-210)

`POST /solutions/{solution_id}/accept` — requires authentication.

`accept_solution` performs an atomic swap within one flush sequence:

1. Loads the target `Solution` and its parent `Problem`.
2. Loads the actor `User` and checks authorization: the actor must be the problem's author or have `role == admin`. Any other caller raises `PermissionError`, translated to `HTTP 403`.
3. Queries for all `Solution` rows on the same problem that currently have `status == "accepted"` and resets each to `status = "pending"`. This ensures at most one accepted solution per problem at any time.
4. Sets the target solution's `status` to `"accepted"`.
5. Updates `problem.activity_at`.

Retracting acceptance (REQ-210) is handled implicitly: accepting a different solution on the same problem automatically reverts the previously accepted one to `pending`. There is no separate retract endpoint; the swap is the mechanism.

#### Anonymous masking (REQ-204)

The internal helper `_solution_to_dict` controls author visibility. When `is_anonymous=True`:

- The `author` field in the response is `null` by default.
- If the `viewer_id` matches the solution's `author_id`, the author is revealed to the author themselves.
- At the route layer, when the authenticated viewer has `role == admin`, the route helper `_unmask_if_admin` re-fetches the solution and force-populates the `author` field, bypassing the service-layer suppression. This admin override is applied on all read paths: `GET /solutions/{id}`, `GET /problems/{id}/solutions`, and the `POST` create response.

---

### Key Design Decisions

**Append-only versioning over in-place mutation.** `SolutionVersion` rows are write-once. The `Solution` row itself carries no mutable content fields — all text lives in version rows. `current_version_id` is a foreign-key pointer that advances forward with each new version but never causes old rows to be deleted or updated. This gives a complete, auditable revision history at zero extra cost.

**Atomic acceptance swap.** Rather than requiring callers to retract the old accepted solution before accepting a new one, the service layer performs the unaccept-then-accept within a single `flush` sequence. This eliminates the race condition that would otherwise allow two solutions on the same problem to hold `status == "accepted"` simultaneously.

**HTTP 405 blocks for PATCH/PUT.** The route layer declares explicit handlers for `PATCH` and `PUT` on `/solutions/{id}` that unconditionally return `405`. This makes the immutability constraint visible in the API surface rather than relying on a missing route (which would return `404` and give callers no guidance).

**Two-phase sort for default ordering.** The database `ORDER BY` clause handles the accepted-first grouping via a `CASE` expression. The upvote-count secondary sort is done in Python after loading, because upvote counts come from a SQLAlchemy relationship (`solution.upvotes`) rather than a SQL aggregate column. The in-memory sort is stable, so the database-level ordering is preserved within ties.

**Admin unmasking at the route layer.** The service-layer `_solution_to_dict` function cannot check the viewer's role without loading an additional `User` row — it only receives a `viewer_id` string. Rather than add that database roundtrip to every serialization call, admin unmasking is performed once at the route layer for callers whose role is known to be `admin`, keeping the service layer free of role-awareness.

**Terminal problem guard on solution creation.** Problems with status `accepted` or `duplicate` reject new solutions at the service layer with a `ValueError`. This prevents accumulation of solutions on closed problems without requiring the route layer to know anything about problem lifecycle.

---

### Configuration

The module has no application-configuration keys of its own. All relevant behavior is governed by values established at the model and application level:

| Concern | Where it is set |
|---|---|
| Terminal statuses that block new solutions | `_TERMINAL_STATUSES` constant in `services/solutions.py`: `{"accepted", "duplicate"}` |
| Initial solution status on creation | Hard-coded to `"pending"` in `create_solution` |
| Default list sort mode | `SolutionSortMode.default` in the route; resolves to accepted-first then upvote-count-desc |
| Authentication enforcement | FastAPI dependency `CurrentUser` (from `app.auth.dependencies`) on write endpoints; `_optional_viewer_id` for read endpoints |
| Admin role value | `UserRole.admin` from `app.enums`; compared against `actor.role` in accept and delete operations |

There are no feature flags, environment variables, or database-level configuration tables that alter the behavior of this module.

---

### Error Behavior

All errors originate in the service layer as Python exceptions and are translated to HTTP responses by the route layer. The mapping is consistent across all endpoints.

| Condition | Service raises | HTTP status | Detail string |
|---|---|---|---|
| `problem_id` does not exist (create solution) | `ValueError("Problem not found")` | 400 | `"Problem not found"` |
| Problem is in a terminal status | `ValueError("Cannot add solutions to a problem with status '…'")` | 400 | Message includes the current status |
| `solution_id` does not exist (get, version, accept, delete) | `ValueError("Solution not found")` | 404 | `"Solution not found"` |
| `problem_id` does not exist (list solutions) | `ValueError("Problem not found")` | 404 | `"Problem not found"` |
| Actor is not the problem owner or admin (accept) | `PermissionError("Only the problem owner or an admin can accept a solution")` | 403 | Full message |
| Actor is not the solution author or admin (delete) | `PermissionError("Only the solution author or an admin can delete")` | 403 | Full message |
| `PATCH` or `PUT` to `/solutions/{id}` | (route-level, no service call) | 405 | `"Solutions cannot be edited directly. POST a new version to /solutions/{id}/versions instead."` |
| Invalid UUID format for any path parameter | Uncaught `ValueError` from `uuid.UUID(...)` | 400 (FastAPI default) | FastAPI validation message |

Partial state is never committed on error. All write operations use `await db.flush()` within the same session; the enclosing request transaction is rolled back if any step raises before the session commits.

<!-- END VERBATIM: module-solutions.md -->

### 3.6 Comments

<!-- BEGIN VERBATIM: module-comments.md -->

### Module Reference: Comments

---

### Purpose

The Comments module provides the full lifecycle for user commentary on problems and solutions in the Aion Bulletin application. It supports:

- **Threaded discussion** — comments nest arbitrarily deep via a `parent_comment_id` self-referential link (REQ-258).
- **Anonymous authorship** — users may post without revealing their identity to other users, while the system retains the true author for moderation (REQ-260).
- **Non-destructive deletion** — comments with replies are tombstoned rather than hard-deleted, preserving thread coherence (REQ-262).
- **In-place editing** — authors can revise comment bodies; edits are flagged visibly (REQ-264).
- **HTML sanitization** — all comment bodies are sanitized at write time against an explicit allowlist to prevent XSS (REQ-924).

---

### How It Works

#### Creating a comment (REQ-258, REQ-260, REQ-924)

Comments are created via two POST endpoints:

- `POST /problems/{problem_id}/comments` — attaches the comment directly to a problem.
- `POST /solutions/{solution_id}/comments` — attaches the comment to a solution; the `problem_id` is resolved automatically from the solution record.

Both endpoints require an authenticated user (`CurrentUser` dependency). The request body is `CommentCreate`, which carries `body`, `is_anonymous`, and the optional `parent_comment_id`.

**Threading validation.** When `parent_comment_id` is supplied, `create_comment` fetches the parent and verifies:

1. The parent exists.
2. The parent's `problem_id` matches the current request's `problem_id`.
3. If the comment targets a solution, the parent's `solution_id` also matches.

Any mismatch raises a `400 Bad Request` before the record is written.

**Sanitization.** `_sanitize_html` is called on the raw `body` before the `Comment` ORM object is constructed. Only the tags in the allowlist (`p`, `strong`, `em`, `code`, `pre`, `blockquote`, `ul`, `ol`, `li`, `a`, `br`) pass through. For `<a>` elements, only the `href` attribute is kept; all other attributes on all other tags are stripped. Disallowed tags are removed entirely — their inner text is preserved, only the tag markup is dropped.

After `db.flush()` and `db.refresh()`, the route re-fetches the full comment tree via `get_comments` and performs a depth-first search (`_find_comment`) to return the newly created node in its correct position within the tree.

#### Listing comments — threaded tree (REQ-258, REQ-260)

`GET /problems/{problem_id}/comments` and `GET /solutions/{solution_id}/comments` accept unauthenticated requests. The route calls `_optional_user`, which resolves the caller's identity via the normal auth dependency but suppresses the `401` on failure, passing `None` to `get_comments` when no valid session is present.

`get_comments` in the service layer:

1. Queries all `Comment` rows for the target problem (filtered by `solution_id` or `solution_id IS NULL`), ordered by `created_at ASC`.
2. Bulk-loads all referenced `User` records in a single query to avoid N+1.
3. Converts each row to a dict via `_comment_to_dict`, applying anonymous masking (see below).
4. Makes a second linear pass to attach each node to its parent's `replies` list; nodes without a valid parent become roots.

The returned structure is a list of root-level comment dicts, each with a nested `replies` list of the same shape.

**Anonymous masking (REQ-260).** When a comment's `is_anonymous` flag is `True`, the `author` field is set to `None` in the response unless the requester is the comment's own author or holds the `admin` role. The true `author_id` is never exposed to ineligible requesters; the `is_anonymous` flag itself remains visible so clients can render an "anonymous" label.

#### Editing a comment (REQ-264)

`PATCH /comments/{comment_id}` accepts a `CommentUpdate` body containing only the new `body` text. The endpoint requires an authenticated user.

`edit_comment` in the service layer:

1. Fetches the comment or raises `404`.
2. Confirms the actor's `id` matches the comment's `author_id`; raises `403` otherwise. No admin override for edits — only the original author may modify the body.
3. Re-runs `_sanitize_html` on the new body.
4. Sets `is_edited = True` on the record.

The response is built by `_single_comment_response` in the route layer, which reuses the requester object as the author source. Since only the author can reach this path, the requester is always the author, so no additional database lookup is needed to populate the author fields.

#### Deleting a comment (REQ-262)

`DELETE /comments/{comment_id}` returns `204 No Content`. The endpoint requires an authenticated user.

`delete_comment` in the service layer:

1. Fetches the comment or raises `404`.
2. Checks authorization: the actor must be the comment owner (`author_id` match) or have the `admin` role; raises `403` otherwise.
3. Queries `Comment.parent_comment_id == comment.id LIMIT 1` to detect child replies.

- **If replies exist:** the comment is tombstoned — `body` is replaced with the literal string `"[deleted]"` and `is_anonymous` is forced to `True`. The row is kept so child nodes remain reachable in the tree.
- **If no replies exist:** `db.delete(comment)` performs a hard delete, removing the row entirely.

Both branches call `db.flush()` to materialize the change within the current transaction unit of work; the caller is responsible for committing.

---

### Key Design Decisions

**Tombstone-only deletion when replies exist.** Hard-deleting a parent comment would orphan its children, breaking the tree. The tombstone approach keeps the structural link intact while concealing the original content. Forcing `is_anonymous = True` on the tombstone prevents the deleted author's identity from being leaked by a previously non-anonymous comment.

**Sanitization at write time, not read time.** HTML is sanitized once during `create_comment` and `edit_comment` and stored in cleaned form. Reading is therefore free of per-request processing overhead, and the stored body is the authoritative clean representation — there is no risk of a sanitization bypass at the read layer.

**Attribute stripping policy for `<a>` tags.** The sanitizer retains `href` on anchor tags because links are a legitimate inline formatting need. All other attributes (`class`, `id`, `onclick`, `style`, `data-*`, etc.) are dropped from every allowed tag, including `<a>`. The `href` value itself is preserved verbatim; callers that render to HTML should apply their own URL-scheme validation (e.g., reject `javascript:` URIs) at the presentation layer.

**`parent_comment_id` cross-entity validation.** A comment on Problem A cannot be the parent of a comment on Problem B, and a comment on a Solution cannot be the parent of a comment on its parent Problem (or a different solution). Both checks run before the comment is flushed, so constraint violations never reach the database.

**Admin override scoped to deletion only.** Admins can delete any comment but cannot edit another user's comment. This aligns with a moderation model where administrators have the right to remove harmful content but should not silently alter what a user wrote.

**`_optional_user` on list endpoints.** Listing comments is a public-read operation. Rather than requiring a separate unauthenticated route, the route resolves the user opportunistically and passes `None` on failure. This keeps the route table clean while allowing the service layer to apply identity-aware masking for authenticated callers.

**Single-query author bulk-load.** `get_comments` collects all unique `author_id` values from the fetched comments and resolves them in one `SELECT ... WHERE id IN (...)` query. This avoids the N+1 problem that would arise from lazy-loading authors per comment.

---

### Configuration

The Comments module has no external configuration file or environment variable. All tuneable values are defined as module-level constants in `app/services/comments.py`:

| Constant | Location | Value | Effect |
|---|---|---|---|
| `_ALLOWED_TAGS` | `app/services/comments.py` | `frozenset` of 11 tag names | Controls which HTML tags survive sanitization. Add or remove tag names here to change the allowlist. |
| `_TAG_RE` | `app/services/comments.py` | Compiled regex `<(/?)(\w+)([^>]*)>` | The pattern used to detect all HTML tags. Changing this would alter which markup is parsed during sanitization. |

The tombstone body string `"[deleted]"` is a hard-coded literal in `delete_comment`. It is not configurable at runtime; changing it requires a code edit in `app/services/comments.py`.

No pagination, rate-limiting, or depth-capping parameters are defined in the current implementation. All comments for a given problem or solution are fetched and returned in a single query.

---

### Error Behavior

All errors are raised as `fastapi.HTTPException` and translated to JSON responses by FastAPI's default exception handler.

| Condition | HTTP status | Detail string |
|---|---|---|
| `comment_id` or `parent_comment_id` UUID is malformed | `400 Bad Request` | `"Invalid UUID: <value>"` (raised by `_to_uuid` in the route layer) |
| `parent_comment_id` references a comment that does not exist | `404 Not Found` | `"Parent comment not found"` |
| `parent_comment_id` belongs to a different problem | `400 Bad Request` | `"Parent comment does not belong to the same problem"` |
| `parent_comment_id` belongs to a different solution | `400 Bad Request` | `"Parent comment does not belong to the same solution"` |
| Referenced `solution_id` does not exist (solution comment routes) | `404 Not Found` | `"Solution not found"` |
| Fetching a comment by ID that does not exist | `404 Not Found` | `"Comment not found"` |
| Attempting to edit a comment the actor does not own | `403 Forbidden` | `"Only the author can edit this comment"` |
| Attempting to delete a comment without owner or admin role | `403 Forbidden` | `"You do not have permission to delete this comment"` |
| Newly created comment cannot be located in the tree (internal fault) | `500 Internal Server Error` | `"Created comment not found in tree"` |

`db.flush()` is called inside the service functions rather than `db.commit()`. Rollback on unhandled exceptions is the responsibility of the database session middleware that wraps each request. If a flush fails due to a database constraint violation (e.g., a foreign key violation on `problem_id`), SQLAlchemy raises an `IntegrityError` that is not caught at the service level; this surfaces as an unhandled `500` unless the application has a global exception handler for `IntegrityError`.

<!-- END VERBATIM: module-comments.md -->

### 3.7 Voting

<!-- BEGIN VERBATIM: module-voting.md -->

### Module Reference: Voting

### Purpose

The Voting module implements the two-axis engagement model at the core of the Aion Bulletin application. Users express interest in a problem by toggling an **upstar** (REQ-250), and they signal agreement with a proposed solution by toggling an **upvote** (REQ-252). The two axes are intentionally separate: starring a problem does not imply endorsing any solution, and upvoting a solution does not require having starred the parent problem. Both actions are idempotent toggles — a second press by the same user removes the vote rather than adding a duplicate. Updated vote counts are returned with every toggle response (REQ-254).

---

### How It Works

#### Upstar (problem axis)

**Endpoint:** `POST /problems/{problem_id}/upstar`

Authentication is required. The authenticated user's identity is resolved via the `CurrentUser` dependency injected by FastAPI.

The service layer (`toggle_upstar` in `app/services/voting.py`) executes the following sequence within the caller's database transaction:

1. Issue `SELECT … FOR UPDATE` on the `problems` row identified by `problem_id`. This acquires a row-level lock that serialises concurrent toggle requests for the same problem.
2. Query the `upstars` table for an existing `(user_id, problem_id)` record.
3. If a record exists, delete it (`active = False`). If no record exists, insert one (`active = True`).
4. Call `db.flush()` to make the change visible within the current transaction without committing.
5. Count all `upstars` rows for the problem and return `(active, count)`.

The route handler wraps the result as `{"active": <bool>, "count": <int>}` and returns HTTP 200.

#### Solution upvote (solution axis)

**Endpoint:** `POST /solutions/{solution_id}/upvote`

The flow mirrors the upstar path exactly, operating on the `solution_upvotes` table and locking the `solutions` row (`toggle_solution_upvote` in `app/services/voting.py`):

1. `SELECT … FOR UPDATE` on the `solutions` row.
2. Query `solution_upvotes` for an existing `(user_id, solution_id)` record.
3. Delete if found (`active = False`), insert if not found (`active = True`).
4. `db.flush()`.
5. Count and return `(active, count)`.

The route returns `{"active": <bool>, "count": <int>}` with HTTP 200.

---

### Key Design Decisions

**Toggle semantics instead of separate add/remove endpoints.**
A single `POST` to the toggle endpoint is idempotent from a user-intent perspective: the endpoint always leaves the vote in the opposite state from what it found. This eliminates a class of client bugs where a "remove" request races against a "re-add" request, and simplifies mobile clients that may lose connectivity mid-interaction.

**Row-level locking (`SELECT … FOR UPDATE`) instead of application-level deduplication.**
Both service functions acquire a pessimistic lock on the parent row (problem or solution) before reading the vote table. This prevents two concurrent requests from both reading "no vote exists" and both inserting a duplicate row. The lock scope is intentionally narrow — only the single parent row is locked, so concurrent votes on different problems or solutions proceed without contention.

**`db.flush()` before counting.**
Flushing after the insert-or-delete ensures the count query within the same session reflects the just-applied change without requiring a full commit. This keeps the returned count accurate while allowing the route's outer transaction boundary to manage commit/rollback.

**Count returned on every toggle.**
Rather than requiring clients to issue a separate read after a vote action, the toggle response always includes the new total. This collapses two round-trips into one and avoids stale-count display bugs caused by a read that lands before the write propagates (REQ-254).

**Symmetric design across both axes.**
The upstar and solution-upvote paths are structurally identical — same lock pattern, same flush, same response shape. This makes the two code paths easy to audit in parallel and ensures that any future fix or optimization applied to one axis is straightforward to apply to the other.

---

### Configuration

The Voting module has no dedicated configuration file or feature flags. Its runtime behavior depends on three shared infrastructure settings:

| Setting | Where configured | Effect on Voting |
|---|---|---|
| Database connection pool size | `app/database.py` / environment | Controls how many concurrent `FOR UPDATE` lock acquisitions can be in flight simultaneously. |
| SQLAlchemy async session factory | `app/database.py` | Supplies the `AsyncSession` injected via `get_db`. Transaction isolation level is inherited from this factory; serializable isolation is not required because the module's row-level locks achieve the necessary serialisation. |
| Authentication backend | `app/auth/dependencies.py` | `CurrentUser` must resolve to a valid user object with an `id` attribute (UUID). Voting will not proceed without a resolved identity; unauthenticated requests are rejected by the dependency before reaching the service layer. |

No environment variables are read directly by `app/services/voting.py` or `app/routes/voting.py`.

---

### Error Behavior

#### 404 — resource not found

If `problem_id` does not match any row in the `problems` table, `toggle_upstar` raises `HTTPException(404, "Problem not found")`. Likewise, an unrecognised `solution_id` raises `HTTPException(404, "Solution not found")`. These checks occur after the `FOR UPDATE` lock attempt; SQLAlchemy returns `None` from `scalar_one_or_none()` when the row does not exist, which the service interprets as a missing resource.

#### 409 — duplicate vote race condition (`DuplicateVoteError`)

The `FOR UPDATE` lock on the parent row prevents two concurrent sessions from both inserting a vote for the same `(user_id, resource_id)` pair. If, despite the lock, the database raises a unique-constraint violation (for example, if the lock is bypassed via a direct database write or a misconfigured session), the caller's transaction middleware is responsible for mapping that integrity error to HTTP 409. The route layer itself does not catch `DuplicateVoteError` explicitly — the error propagates to the application's global exception handler, which must translate it to a 409 response with an appropriate detail message.

#### 401 — unauthenticated request

Requests that do not carry a valid authentication token are rejected by the `CurrentUser` dependency before the route function is entered. The voting service layer is never reached.

#### 422 — malformed path parameter

FastAPI validates that `problem_id` and `solution_id` are well-formed UUIDs before dispatching to the route handler. Non-UUID path segments return HTTP 422 automatically; the voting service is not invoked.

#### Transaction rollback on unexpected errors

Both service functions run inside the session transaction managed by `get_db`. Any unhandled exception causes the session context manager to roll back the transaction, leaving the vote table in its pre-request state. The lock is released as part of rollback.

<!-- END VERBATIM: module-voting.md -->

### 3.8 Attachments

<!-- BEGIN VERBATIM: module-attachments.md -->

### Module Reference: Attachments

**Spec coverage:** REQ-400, REQ-402, REQ-404, REQ-406

---

### Purpose

The Attachments module lets authenticated users upload files to a problem record, retrieve metadata for all attached files, download individual files, and delete their own attachments. It enforces a MIME-type allowlist, a per-file size ceiling, and a cumulative per-problem storage cap before any bytes are written to disk.

---

### How It Works

#### Upload (REQ-400, REQ-402, REQ-404)

A client posts a multipart file to `POST /problems/{problem_id}/attachments`. The route delegates immediately to `create_attachment` in the service layer, which runs three checks in sequence before touching the filesystem:

1. **Per-file size** — the raw byte length of the uploaded file is compared against `MAX_FILE_SIZE` (10 MB). Exceeding it raises `FileSizeLimitError` immediately, without a database read.
2. **Extension/MIME check** — the file's extension (lowercased via `os.path.splitext`) is looked up in a reverse-index table built from the `ALLOWED_TYPES` dict at module load time. If the extension is absent, `FileTypeNotAllowedError` is raised. The check is extension-based, not content-sniffing-based; the MIME type stored in the database is authoritative and is resolved from that same extension map rather than from the client-supplied `Content-Type` header, preventing MIME spoofing.
3. **Cumulative problem size** — a `SUM(byte_size)` query over all existing attachments for the problem (scoped by `parent_type = 'problem'` and `parent_id`) is compared against `MAX_TOTAL_SIZE` (50 MB). If `current_total + file_size` would exceed the cap, `FileSizeLimitError` is raised.

After all three checks pass, `store_file` writes the bytes under `{STORAGE_PATH}/{problem_id}/{uuid4}{ext}`. The original filename is preserved in the `filename` column; the on-disk name is UUID-generated, preventing collisions and path traversal. A new `Attachment` row is flushed (not yet committed) and returned to the route, which serialises it as `AttachmentResponse` with HTTP 201.

#### List (REQ-406)

`GET /problems/{problem_id}/attachments` calls `list_attachments`, which runs a single `SELECT` filtered by `parent_type` and `parent_id`, ordered by `created_at` ascending. The endpoint is unauthenticated — any caller with the problem ID can retrieve the metadata list.

#### Download (REQ-406)

`GET /attachments/{attachment_id}/download` resolves the `storage_path` stored in the database, reconstructs the absolute filesystem path as `{STORAGE_PATH}/{storage_path}`, verifies the file exists on disk, and returns a `FileResponse`. Images (`content_type` starts with `image/`) are served with `Content-Disposition: inline`; all other types use `Content-Disposition: attachment`. The `render_inline` flag in `AttachmentResponse` carries the same signal to clients so they can drive UI behaviour without parsing the MIME type themselves.

#### Delete

`DELETE /attachments/{attachment_id}` requires the caller to be the original uploader or an admin (`require_owner_or_admin`). The service deletes the database row first (inside the open session transaction), then calls `_remove_file_from_disk` after `flush`. Disk removal is best-effort: `OSError` is caught and logged rather than propagated, so a missing or unremovable file does not roll back the metadata deletion.

---

### Key Design Decisions

**Extension-based MIME resolution, not client headers.** The authoritative content type is derived from the file extension at write time using the internal `_EXT_TO_MIME` reverse map. The client-supplied `Content-Type` is ignored for this purpose. This closes the attack surface where a client labels an arbitrary file as `image/jpeg` to bypass type checks.

**UUID filenames, problem-scoped directories.** On-disk files are named `{uuid4}{ext}` and stored under `{STORAGE_PATH}/{problem_id}/`. The UUID prevents collisions between concurrent uploads and eliminates any path-traversal risk from user-supplied filenames. The original filename is stored only in the database and echoed back in the response.

**Cumulative size is checked inside the service transaction.** The `SUM(byte_size)` query runs within the same async session as the subsequent `flush`, so concurrent uploads to the same problem are serialised by database row-locking semantics rather than application-level locking. This avoids a race condition where two simultaneous uploads could each pass the cap check independently.

**DB row deleted before disk file.** In the event of a crash between the two operations, the result is an orphaned file rather than a dangling database reference. An orphaned file is recoverable by a background reconciliation job; a dangling reference would surface as broken downloads.

**`render_inline` flag on the response.** Rather than requiring clients to re-parse `content_type`, the serialiser pre-computes `render_inline = content_type.startswith("image/")` and includes it in every `AttachmentResponse`. This is a thin convenience field — it carries no server-side authority and is not stored in the database.

**`STORAGE_PATH` is runtime-configurable.** No path is hardcoded; every file operation resolves the base directory from `get_settings().STORAGE_PATH`. This allows the same code to point at a local dev volume or a mounted remote filesystem without modification.

---

### Configuration

| Setting | Source | Default / Notes |
|---|---|---|
| `STORAGE_PATH` | `app.config.Settings` | No default; must be set. All stored files live under this root. |
| `MAX_FILE_SIZE` | `app/services/attachments.py` constant | `10 * 1024 * 1024` (10 MB). Change requires a code deploy. |
| `MAX_TOTAL_SIZE` | `app/services/attachments.py` constant | `50 * 1024 * 1024` (50 MB per problem). Change requires a code deploy. |
| `ALLOWED_TYPES` | `app/services/attachments.py` constant | `image/png`, `image/jpeg`, `image/webp`, `image/gif`, `application/pdf`, `text/plain`. Extensions: `.png`, `.jpg`, `.jpeg`, `.webp`, `.gif`, `.pdf`, `.txt`, `.log`. Change requires a code deploy. |

The size limits and MIME allowlist are module-level constants, not environment-driven settings. Changing them requires a code change and redeploy. There is no feature flag or admin API to alter them at runtime.

---

### Error Behavior

| Condition | Exception / HTTP response |
|---|---|
| File exceeds 10 MB per-file limit | `FileSizeLimitError` raised in service; route should map to HTTP 413 |
| Adding the file would push the problem past 50 MB aggregate | `FileSizeLimitError` raised in service; route should map to HTTP 413 |
| File extension not in the MIME allowlist | `FileTypeNotAllowedError` raised in service; route should map to HTTP 415 |
| Attachment ID not found (download or delete) | HTTP 404 (`detail: "Attachment not found"`) |
| Attachment record exists but file is missing on disk (download) | HTTP 404 (`detail: "File not found on disk"`) |
| Caller is not the uploader or an admin (delete) | `require_owner_or_admin` raises; resolved to HTTP 403 by the auth dependency |
| `ValueError("Attachment not found")` from service during delete | HTTP 404 (re-raised by route after catching `ValueError`) |
| Disk removal fails after a successful delete (OSError) | Error is logged at `EXCEPTION` level; HTTP 204 is still returned. The database row is already deleted. |

The service does not commit the database session; that is the caller's responsibility (typically handled by a FastAPI dependency wrapping the route). If the session is not committed after `create_attachment`, no file metadata is persisted and the written bytes become orphaned on disk.

<!-- END VERBATIM: module-attachments.md -->

### 3.9 Search

<!-- BEGIN VERBATIM: module-search.md -->

### Module Reference: Search

**Source files:**
- `app/services/search.py` — query logic, SQL construction, result shaping
- `app/routes/search.py` — HTTP endpoints, parameter validation

**Requirements covered:** REQ-350, REQ-352, REQ-354, REQ-356, REQ-902 (full-text search); REQ-356 (sort modes); REQ-362 (similar suggestions)

---

### Purpose

The Search module provides two capabilities:

1. **Full-text search** across problems, solutions, and comments. A single query surfaces any problem record that matches — whether the query terms appear in the problem title/description, in a solution body, or in a comment. Results are deduplicated to the problem level and returned with a relevance rank, excerpt, upvote count, and the entity type where the match was found.

2. **Similar-problem suggestions.** Given a problem title (typically entered live in the UI before the user submits), the module returns up to N ranked problems that cover the same topic. This helps surface duplicates early without requiring an explicit search.

Both capabilities are backed by PostgreSQL full-text search primitives (`tsvector`, `tsquery`, `ts_rank`, GIN index) and have no external dependencies beyond the application database.

---

### How It Works

#### Full-text search (`GET /search`)

**Entry point:** `search_problems(db, query, *, sort, category_id, tag_ids, status, limit, offset)` in `app/services/search.py`, called by the `GET /search` route.

**Step 1 — Input guard.** If the query string is empty or blank, the function returns immediately with `{"results": [], "message": "No results found"}` without touching the database.

**Step 2 — Query compilation.** A single CTE (`tsq`) compiles the user's raw string into a PostgreSQL `tsquery` using `plainto_tsquery('english', :query)` (REQ-350). `plainto_tsquery` normalizes whitespace, strips punctuation, and handles multi-word phrases without requiring the user to supply boolean operators.

**Step 3 — Three-branch CTE fan-out (REQ-352).** Three independent CTEs run in the same query plan:

| CTE | Matches against | `match_source` label |
|---|---|---|
| `problem_hits` | `problems.search_vector` (pre-computed `tsvector` column) | `"problem"` |
| `solution_hits` | `to_tsvector('english', solution_versions.description)` (computed inline) | `"solution"` |
| `comment_hits` | `to_tsvector('english', comments.body)` (computed inline) | `"comment"` |

Solution and comment hits join back to their parent `problems` row so that every row in all three CTEs carries the same schema: `(problem_id, title, excerpt, rank, match_source, upstar_count, p_created_at)`.

**Step 4 — UNION ALL and deduplication.** The three CTEs are merged with `UNION ALL` and then collapsed with `SELECT DISTINCT ON (problem_id) … ORDER BY problem_id, rank DESC`. This keeps only the highest-ranked match per problem regardless of which entity type produced it.

**Step 5 — Ranking and sort (REQ-354, REQ-356).** `ts_rank(search_vector, tsq.q)` scores each hit. The outer `ORDER BY` clause is selected from a map at runtime:

| `sort` parameter | SQL clause |
|---|---|
| `relevance` (default) | `rank DESC` |
| `upvotes` | `upstar_count DESC` |
| `newest` | `p_created_at DESC` |

Unknown `sort` values fall back to `rank DESC`.

**Step 6 — Filtering.** Optional filters are appended as parameterized `AND` clauses before the main `WHERE` condition: `category_id`, `status`, and `tag_ids` (the tag filter uses an `INNER JOIN` against `problem_tags` so only problems tagged with all requested tags are included).

**Step 7 — Pagination.** `LIMIT :lim OFFSET :off` are applied on the final result set. The route enforces `limit` in `[1, 100]` and `offset >= 0`.

**Step 8 — Result shaping.** Each row is serialized to a plain dict: UUIDs to strings, `Decimal`/float ranks to `float`, `datetime` to ISO-8601, `None` excerpts to `""`.

#### Similar-problem suggestions (`GET /search/suggest`)

**Entry point:** `suggest_similar(db, title, *, exclude_problem_id, limit)` in `app/services/search.py`, called by the `GET /search/suggest` route.

The function uses the same `plainto_tsquery` + `search_vector @@` pattern but targets only the `problems` table and its pre-computed `search_vector` column. An optional `exclude_problem_id` parameter filters out the calling problem when the UI checks for duplicates mid-edit. Results are capped at 5 by default (max 20 via the route). The route wraps an empty result list in `{"results": [], "message": "No similar problems found"}`.

#### `search_vector` maintenance

The column `problems.search_vector` is a stored `tsvector` over `title || ' ' || description`, using the `english` dictionary. The helper `update_search_vector(db, problem)` issues a targeted `UPDATE` to recompute it for a single row. Callers (create/edit problem handlers) are responsible for invoking this after mutations; the search module does not auto-trigger it.

---

### Key Design Decisions

**`plainto_tsquery` over `to_tsquery` / `websearch_to_tsquery`.** `plainto_tsquery` treats the entire input as an implicit AND of normalized lexemes. It never raises a syntax error on arbitrary user input (unlike `to_tsquery`, which requires valid tsquery syntax) and is supported on all target PostgreSQL versions without the 12+ requirement of `websearch_to_tsquery`. The trade-off is that phrase queries and OR operators are not user-accessible; this is acceptable for the current feature scope.

**Three-branch UNION ALL with `DISTINCT ON`.** Searching solutions and comments inline (REQ-352) avoids a separate application-level fan-out and round-trip. `UNION ALL` is cheaper than `UNION` because deduplication is handled once, precisely, at the `DISTINCT ON` layer where the ranking signal is available. Collapsing to `problem_id` ensures the API always returns problem-level records regardless of which child entity matched.

**Pre-computed `search_vector` for problems only.** Problems are indexed with a GIN index on `search_vector`, giving O(log N) lookup. Solutions and comments use `to_tsvector(…)` inline because they are secondary hit surfaces; adding GIN indexes on those tables is deferred. This keeps index maintenance simple while satisfying REQ-350/352 correctness.

**Raw SQL over ORM query builder.** The query uses PostgreSQL-specific operators (`@@`, `ts_rank`, `DISTINCT ON`, CTEs with comma joins) that SQLAlchemy's ORM layer would either refuse or obscure. Raw `text()` with named bind parameters keeps the logic readable and auditable while retaining parameterization for injection safety.

**Excerpt length fixed at 120 characters.** The constant `_EXCERPT_LEN = 120` is used by the `_truncate` helper and as the literal `LEFT(…, 120)` in SQL. The SQL and Python constants are currently independent; if the excerpt length is ever changed, both must be updated.

**`upstar_count` via correlated subquery.** Upvote counts are fetched inline as `(SELECT count(*) FROM upstars u WHERE u.problem_id = p.id)`. This is simple and correct but executes one subquery per matched row. For result sets near the `limit=100` ceiling this is acceptable; if hot queries routinely return large result sets a materialized count column on `problems` should be evaluated.

---

### Configuration

All configuration is supplied at call time through function parameters or route query parameters. There are no module-level environment variables.

| Parameter | Scope | Default | Constraints | Description |
|---|---|---|---|---|
| `q` | Route / `search_problems` | `""` | — | Raw search query string |
| `sort` | Route / `search_problems` | `"relevance"` | `relevance`, `upvotes`, `newest` | Result ordering |
| `category_id` | Route / `search_problems` | `None` | Valid UUID | Restrict to one category |
| `tag_ids` | Route / `search_problems` | `None` | List of valid UUIDs | Restrict to problems carrying these tags |
| `status` | Route / `search_problems` | `None` | Any string | Restrict to a problem status value |
| `limit` | Route | `20` | `[1, 100]` | Max results per page |
| `offset` | Route | `0` | `>= 0` | Pagination offset |
| `title` | Route / `suggest_similar` | `""` | — | Title text to match for suggestions |
| `exclude_id` | Route / `suggest_similar` | `None` | Valid UUID | Problem ID to omit from suggestions |
| `limit` (suggest) | Route | `5` | `[1, 20]` | Max suggestion results |

**Database dependency.** Both functions receive an `AsyncSession` injected by FastAPI's `Depends(get_db)`. Connection pool sizing, statement timeout, and `work_mem` (relevant for sort and hash operations in the query plan) are managed at the database layer outside this module.

**Performance target (REQ-902).** The p95 response time target is 1000 ms. Staying within this budget relies on the GIN index on `problems.search_vector` being present and healthy. No circuit-breaker or timeout is enforced inside this module; operators should configure `statement_timeout` at the PostgreSQL session or role level if they need a hard server-side ceiling.

---

### Error Behavior

**Empty or blank query.** Both `search_problems` and `suggest_similar` check for empty/blank input before executing any SQL and return an empty result immediately. The route returns HTTP 200 with `{"results": [], "message": "No results found"}` or `{"results": [], "message": "No similar problems found"}` respectively. No error is raised.

**No matches.** When the query is syntactically valid but returns zero rows, the same empty-result response is returned (HTTP 200). Callers must distinguish "no results" from "error" by inspecting the `results` array, not the HTTP status code.

**Unknown `sort` value.** An unrecognized `sort` parameter silently falls back to `rank DESC`. No validation error is raised by the service layer. The route does not constrain the `sort` parameter to an enum, so invalid values reach the service. This is benign but means the API does not reject `sort=bogus`.

**Database errors.** The module does not catch SQLAlchemy exceptions. Any database error (connection failure, query timeout, constraint violation) propagates as an unhandled exception to FastAPI's default exception handler, which returns HTTP 500. Structured error logging is the responsibility of the application's middleware layer.

**SQL injection.** All user-supplied values are passed as named bind parameters (`:query`, `:category_id`, `:tag_N`, etc.) via SQLAlchemy `text()`. Dynamic SQL fragments (the `ORDER BY` clause, the `tag_join` INNER JOIN snippet, the `filter_clause` AND snippets) are constructed from trusted internal values — never from raw user input — so injection via those paths is not possible.

**`search_vector` staleness.** If `update_search_vector` is not called after a problem is created or updated, the `search_vector` column may be stale. Stale vectors cause problems to rank incorrectly or not appear in results. The search module has no mechanism to detect or compensate for staleness; this is an operational risk that must be mitigated at the write path.

<!-- END VERBATIM: module-search.md -->

### 3.10 Watch & Notification Pipeline

<!-- BEGIN VERBATIM: module-notifications.md -->

### Module Reference: Watch & Notification Pipeline

### Purpose

The Watch & Notification Pipeline controls which users receive notifications about activity on a problem bulletin, and how those notifications are delivered. It has two cooperating responsibilities:

**Watch management** lets any authenticated user declare their interest in a problem at a granular level. A watch record encodes exactly which categories of events the user wants to hear about — from complete silence up to every activity type.

**Notification fan-out and delivery** translates a single application event (a new comment, a status change, an accepted solution, etc.) into per-user `Notification` rows and then dispatches those rows over three independent channels: in-browser WebSocket push, Microsoft Teams Adaptive Card webhook, and a plain-text email digest.

Together these two subsystems satisfy REQ-300 through REQ-326 and are the sole components responsible for real-time user alerting in the application.

---

### How It Works

#### 1. Watch levels (REQ-300)

Every watch row carries one of four levels, ordered from least to most inclusive:

| Level | Numeric priority | Receives |
|---|---|---|
| `none` | 0 | Nothing — user is explicitly opted out |
| `status_only` | 1 | `status_changed` events only |
| `solutions_only` | 2 | `solution_posted` and `solution_accepted` |
| `all_activity` | 3 | All eight notification types |

The `_LEVEL_PRIORITY` mapping in `app/services/watches.py` encodes this ordering and is used solely by the auto-watch logic described below.

#### 2. Watch upsert (REQ-302, REQ-304)

A user sets or changes their watch level by calling `PUT /problems/{problem_id}/watch` with a JSON body containing the desired `level`. The service layer executes a PostgreSQL `INSERT … ON CONFLICT DO UPDATE` against the `uq_watch_user_problem` unique constraint, so the operation is idempotent regardless of whether a watch row already exists. To remove a watch entirely, the client calls `DELETE /problems/{problem_id}/watch`; the route returns `204 No Content` on success and `404` if no watch existed. The current level is readable via `GET /problems/{problem_id}/watch`.

### 3. Automatic watch on participation (REQ-302)

When a user creates a problem, claims a problem, or posts a comment, the application calls `auto_watch(db, user_id, problem_id, level=WatchLevel.all_activity)`. This function:

1. Looks up any existing watch for the user/problem pair.
2. Compares the existing level's numeric priority against the requested level's priority.
3. If the existing level is already equal or higher, it returns the existing watch unchanged — participation never silently downgrades a user's explicit preference.
4. Otherwise it calls `set_watch`, which upserts the row to `all_activity`.

#### 4. Notification types (REQ-310)

Eight distinct `NotificationType` enum values exist in `app/enums`:

- `comment_posted`
- `solution_posted`
- `solution_accepted`
- `status_changed`
- `upvote_milestone`
- `problem_claimed`
- `problem_resolved`
- `mention`

#### 5. Fan-out with routing matrix (REQ-312, REQ-314)

When an event occurs, the caller invokes `generate_notification(db, event_type, problem_id, actor_id, solution_id=None)` from `app/services/notifications.py`. The function:

1. Queries all `Watch` rows for the given `problem_id` **excluding** the `actor_id` row (REQ-314 — you do not notify yourself).
2. For each watch, looks up the allowed notification types for that watch level in the `WATCH_ROUTING` matrix:

   ```python
   WATCH_ROUTING = {
       WatchLevel.all_activity:   set(NotificationType),          # all 8 types
       WatchLevel.solutions_only: {solution_posted, solution_accepted},
       WatchLevel.status_only:    {status_changed},
       WatchLevel.none:           set(),
   }
   ```

3. Skips the watch if `event_type` is not in the allowed set.
4. Constructs a `Notification` row for every surviving watcher, bulk-inserts with `db.add_all()`, and flushes.
5. Returns the list of created `Notification` objects to the caller, which is responsible for triggering delivery.

#### 6. WebSocket push (REQ-316)

`app/routes/ws.py` exposes a single endpoint `GET /ws/notifications` upgraded to WebSocket. On connection:

- The client supplies its JWT as the `?token=` query parameter. The endpoint decodes it with `decode_access_token`; if the token is absent or invalid it closes immediately with `WS_1008_POLICY_VIOLATION`.
- On success, the socket is registered with the in-process `ConnectionManager` singleton under the user's UUID string key. `ConnectionManager` holds a `dict[str, set[WebSocket]]`, supporting multiple simultaneous tabs or devices per user.
- A 30-second read loop handles application-level keep-alive: if the client sends the text `ping`, the server replies `pong`. If no message arrives within 30 seconds the server proactively sends a `ping` text frame; a send failure breaks the loop and triggers disconnect cleanup, pruning stale sockets from the set.

When `generate_notification` returns a list of new rows, the caller passes each row to `push_ws_notification(notification)` in `app/services/delivery.py`. That function serialises the row to a JSON envelope with shape:

```json
{
  "type": "notification",
  "payload": {
    "id": "...",
    "notification_type": "...",
    "problem_id": "...",
    "solution_id": "...",
    "actor_id": "...",
    "is_read": false,
    "created_at": "..."
  }
}
```

and calls `connection_manager.broadcast_to_user(recipient_id, data)`. If the recipient has no active connections the call is a no-op. Stale sockets that raise on send are silently pruned.

#### 7. Teams webhook (REQ-318)

`send_teams_webhook(notification)` in `app/services/delivery.py` posts an Adaptive Card (schema version 1.4) to `settings.TEAMS_WEBHOOK_URL`. The card body contains a bold header (`Aion Bulletin — <type>`) and a `FactSet` with the notification type, problem UUID, and timestamp. The HTTP call uses `httpx.AsyncClient` with a 10-second timeout.

Callers use the thin wrapper `schedule_teams_webhook(notification)`, which captures the running event loop and schedules `send_teams_webhook` as a fire-and-forget `asyncio.Task`. If no event loop is running at call time the wrapper silently returns without scheduling — this prevents synchronous startup paths from raising.

#### 8. Email digest (REQ-320)

`send_email_digest(db, user_id, notifications)` in `app/services/delivery.py` is designed to be called in batch (e.g., by a scheduled job). For a given user it:

1. Resolves the `User` row to obtain `display_name` and `email`.
2. Renders a plain-text body listing each notification with its timestamp, type, and problem UUID, plus a direct link to the notifications inbox (`{BASE_URL}/notifications`).
3. Sends via `aiosmtplib` over STARTTLS using the configured SMTP host and port.
4. On success, stamps `updated_at = now()` on every digest notification as a delivery marker, then flushes — **this is the only persistent record that a digest was sent**; there is no separate `email_delivered` boolean column.

#### 9. Mark read / unread (REQ-324)

`PATCH /notifications/{id}/read` sets `is_read = True` on a single notification owned by the authenticated user, returning `204`. If the notification ID is not a valid UUID the endpoint returns `400`; if it does not belong to the caller it returns `404`.

`POST /notifications/read-all` bulk-updates all unread notifications for the user in a single `UPDATE … WHERE recipient_id = ? AND is_read = false` statement, returning `204`.

`GET /notifications` returns a paginated list (cursor-based, descending `created_at`) and always includes the caller's total `unread_count` regardless of the `unread_only` filter. Page size is 1–100 (default 20). The cursor is the ISO-formatted `created_at` of the last item in the previous page.

#### 10. Upvote milestone deduplication (REQ-326)

`is_milestone(count)` in `app/services/delivery.py` returns `True` when `count` is in the list `[10, 25, 50, 100]`. Callers are expected to invoke `generate_notification` with `event_type=upvote_milestone` only when this function returns `True`, ensuring that milestone notifications fire at discrete thresholds rather than on every upvote increment.

---

### Key Design Decisions

**Routing matrix as data, not branching logic.** `WATCH_ROUTING` in `app/services/notifications.py` is a plain `dict[WatchLevel, set[NotificationType]]`. Adding a new watch level or notification type requires only a dict entry — no `if/elif` chains need to be modified across the codebase. `all_activity` is defined as `set(NotificationType)`, so it automatically covers any new types added to the enum.

**Upsert over separate insert/update paths.** `set_watch` uses PostgreSQL `INSERT … ON CONFLICT DO UPDATE` on the `uq_watch_user_problem` constraint. This makes the endpoint idempotent, eliminates the read-before-write race in concurrent participation flows, and removes the need for optimistic-concurrency error handling.

**Auto-watch never downgrades.** `auto_watch` silently skips the write if the existing priority is already equal or higher. This prevents a user's explicit `all_activity` preference from being silently overwritten by a `solutions_only` auto-watch triggered by a comment action.

**Actor exclusion at query time, not filter time.** The `WHERE user_id != actor_uuid` clause in `generate_notification` keeps actors out of the result set before any Python iteration, avoiding unnecessary `Notification` object construction for the common case where the actor watches the problem.

**ConnectionManager holds a set of sockets per user.** Users can have multiple simultaneous connections (multiple browser tabs, mobile clients). `broadcast_to_user` fans out to all of them and self-heals by pruning sockets that raise on send, avoiding an accumulation of dead handles.

**Delivery channels are fully decoupled from fan-out.** `generate_notification` only produces database rows. Dispatching to WebSocket, Teams, or email is performed separately by the caller. This separation means delivery failures on one channel do not affect the others and the caller can choose which channels to activate for a given event.

**Teams webhook is fire-and-forget via asyncio.Task.** `schedule_teams_webhook` schedules the HTTP call as a background task. The request handler returns immediately without waiting for the Teams API. Failures are logged but never propagated.

**Email uses `updated_at` as a delivery marker.** There is no dedicated `email_delivered` column on the `Notification` model. Digest jobs that need idempotency must query by `updated_at` range or track delivery state in a separate job-management layer.

---

### Configuration

All settings are resolved through `app.config.get_settings()`. The relevant fields for this pipeline are:

| Setting | Type | Purpose |
|---|---|---|
| `TEAMS_WEBHOOK_URL` | `str \| None` | Teams Adaptive Card endpoint. If `None` or empty, `send_teams_webhook` returns immediately without making any HTTP call. |
| `SMTP_HOST` | `str` | Hostname of the SMTP relay used by the email digest. |
| `SMTP_PORT` | `int` | Port for the SMTP relay; `aiosmtplib` upgrades to TLS via STARTTLS. |
| `SMTP_FROM` | `str` | RFC 5321 `MAIL FROM` / `From:` header address. |
| `BASE_URL` | `str` | Base URL inserted into digest email links (e.g., `https://bulletin.example.com`). |
| `APP_NAME` | `str` | Application name used in the email subject line. |

**Upvote milestone thresholds** are hardcoded as `UPVOTE_MILESTONES = [10, 25, 50, 100]` in `app/services/delivery.py`. To change the thresholds, edit this list directly; no environment variable override exists.

The WebSocket endpoint has no dedicated configuration. It inherits the application's JWT secret via `decode_access_token` and the 30-second keep-alive timeout is hardcoded in `app/routes/ws.py`.

---

### Error Behavior

**Watch upsert failures.** `set_watch` and `remove_watch` call `db.flush()` but do not commit — they participate in the caller's unit of work. A database error (constraint violation, connection loss) will propagate as a SQLAlchemy exception and the caller's transaction will be rolled back. `remove_watch` returns `False` rather than raising when no row is found; the route layer translates this to `404`.

**Notification fan-out failures.** `generate_notification` calls `db.flush()` after `db.add_all()`. A flush failure raises and unwinds the caller's transaction, so no partial notification set is committed. The function returns an empty list if no watchers qualify — callers must handle that as a no-op.

**WebSocket push failures.** `push_ws_notification` wraps `broadcast_to_user` in a `try/except Exception` block. Any error is logged at `ERROR` level with the notification ID and swallowed — a failed WebSocket push never raises to the caller. Stale sockets are pruned from `ConnectionManager` during the same `broadcast_to_user` call that discovers them.

**Teams webhook failures.** `send_teams_webhook` catches all exceptions around the `httpx` call, logs them at `ERROR` level, and returns silently. Because `schedule_teams_webhook` creates an `asyncio.Task`, any exception that escapes `send_teams_webhook` would surface as an unhandled task exception (Python logs it and discards it). In practice the inner `try/except` ensures that does not happen. If `TEAMS_WEBHOOK_URL` is not configured the function exits before creating any HTTP client, so unconfigured environments produce no errors.

**Email digest failures.** `send_email_digest` catches all `aiosmtplib` exceptions, logs them at `ERROR` level, and returns without updating `updated_at` on the notifications. The caller receives no signal that delivery failed other than the log entry; a digest job that retries by re-querying undelivered notifications will re-attempt on the next run. If the user row cannot be found, the function logs a `WARNING` and returns without attempting SMTP.

**Invalid cursor in pagination.** `GET /notifications` validates the cursor as a parseable ISO datetime; a malformed cursor returns `400 Bad Request` rather than silently dropping results.

**Invalid notification ID in mark-read.** `PATCH /notifications/{id}/read` parses the notification ID as a UUID before querying; a non-UUID value returns `400 Bad Request`.

<!-- END VERBATIM: module-notifications.md -->

### 3.11 Admin Subsystem

<!-- BEGIN VERBATIM: module-admin.md -->

### Module Reference: Admin Subsystem

**Source packages:** `app/services/admin.py`, `app/services/categories.py`,
`app/services/tags.py`, `app/routes/admin/`

**Router mount point:** `POST /admin` — all routes in this subsystem are
registered under this prefix and are protected by a shared `require_admin`
dependency injected at the router level in `app/routes/admin/__init__.py`.

---

### Purpose

The Admin Subsystem provides the operational back-office capabilities of the
Aion Bulletin application. It gives administrators a single, coherent surface
for four distinct concerns:

1. **User management** — discovering accounts and changing their role or
   activation state (REQ-450, REQ-452, REQ-454).
2. **Taxonomy management** — full CRUD for categories (with controlled deletion
   and presentation ordering) and tags (with rename, delete, and merge
   operations) (REQ-456, REQ-458, REQ-460, REQ-462, REQ-464, REQ-466).
3. **Content moderation** — surfacing flagged content for review, recording
   resolution decisions, and revealing the identity of anonymous problem authors
   under an auditable workflow (REQ-468, REQ-470, REQ-472, REQ-474).
4. **Runtime configuration** — reading and updating key-value application
   settings without a deployment (REQ-476).

No part of this subsystem is reachable by non-admin principals. The admin
check is applied once at the `APIRouter` level, making it impossible for an
individual route to accidentally bypass it.

---

### How It Works

#### Authentication and routing

`app/routes/admin/__init__.py` creates a single `APIRouter` at the `/admin`
prefix with `dependencies=[Depends(require_admin)]`. Five sub-routers are
included into this parent:

| Sub-router | Prefix | Module |
|---|---|---|
| `users.router` | `/admin/users` | `app/routes/admin/users.py` |
| `admin_tag_router` | `/admin/tags` | `app/routes/admin/tags.py` |
| `categories.router` | `/admin/categories` | `app/routes/admin/categories.py` |
| `moderation.router` | `/admin/moderation` | `app/routes/admin/moderation.py` |
| `config.router` | `/admin/config` | `app/routes/admin/config.py` |

Each sub-router delegates all database work to a corresponding service module
(`app/services/admin.py`, `app/services/categories.py`,
`app/services/tags.py`). Routes are thin: they validate input via Pydantic
schemas, call one service function, translate domain exceptions into HTTP
responses, and return a Pydantic output model.

#### User management (REQ-450, REQ-452, REQ-454)

`GET /admin/users/` accepts an optional `?q=` query string.
`search_users` (in `admin.py`) performs a case-insensitive `ILIKE` match on
both `User.display_name` and `User.email`, returning results ordered by
`created_at DESC`. When `q` is absent the full user list is returned.

`PATCH /admin/users/{user_id}/role` calls `update_user_role`, which loads the
user by UUID, updates the `role` field, flushes, and emits a `user.role_changed`
structured log event via `log_event`.

`PATCH /admin/users/{user_id}/status` calls `update_user_status`, which
toggles `User.is_active` and emits a `user.status_changed` event. Both
mutation paths use the shared helper `_get_user_or_404` to produce a
consistent 404 before attempting any write.

#### Category CRUD and reordering (REQ-456, REQ-458)

All category logic lives in `app/services/categories.py`. The `deleted_at`
column is the soft-delete marker; every query that reads categories filters on
`Category.deleted_at.is_(None)` so deleted records are invisible to all
ordinary callers.

**Create** (`POST /admin/categories`): `create_category` computes `next_order`
by querying `MAX(sort_order)` over non-deleted categories (defaulting to -1 if
empty, so the first category gets `sort_order = 0`) and derives a URL-safe slug
via `_slugify` (lowercase, strip non-word characters, collapse whitespace/underscores
to hyphens).

**Update** (`PATCH /admin/categories/{category_id}`): partial update of `name`
and/or `slug`. The `updated_at` timestamp is set explicitly to
`datetime.now(timezone.utc)`.

**Reorder** (`PATCH /admin/categories/reorder`): accepts an array of
`{id, sort_order}` pairs and issues a bulk `UPDATE` for each. No sort-order
uniqueness constraint is enforced at the database layer, giving callers full
control over tie-breaking.

**Soft delete** (`DELETE /admin/categories/{category_id}`): before setting
`deleted_at`, `soft_delete_category` counts `Problem` rows whose
`category_id` matches. If the count is greater than zero it raises
`CategoryInUseError` and the route translates this to HTTP 409. This prevents
orphaning live problems. The category record is never physically removed.

#### Tag management (REQ-460, REQ-462, REQ-464, REQ-466)

Tag logic lives in `app/services/tags.py`. Tags are not soft-deleted; deletion
is hard and cascades through the join table.

**List** (`GET /tags`, public): `get_tags` performs a `LEFT OUTER JOIN`
against `ProblemTag` grouped by `Tag.id` to compute a live `usage_count` per
tag. The `?sort=` parameter accepts `"name"` (alphabetical, default) or
`"usage"` (descending count, then name for ties). This endpoint is on the
public router and does not require admin access.

**Rename** (`PATCH /admin/tags/{tag_id}`): `rename_tag` checks that the tag
exists and that no other tag already carries the requested name, raising
`TagNameConflictError` if there is a collision. The route maps this to HTTP 409.

**Delete** (`DELETE /admin/tags/{tag_id}`): `delete_tag` explicitly removes
all `ProblemTag` association rows for the tag before removing the tag row
itself, both within the same `flush`. This ensures referential integrity is
satisfied even if the database schema lacks a cascading foreign key.

**Merge** (`POST /admin/tags/merge`): `merge_tags` is the most complex tag
operation. It:
1. Validates that source and target are distinct and both exist.
2. Collects all `problem_id` values currently associated with the source tag.
3. Bulk-inserts `(problem_id, target_id)` rows using a PostgreSQL
   `INSERT ... ON CONFLICT DO NOTHING` against the `(problem_id, tag_id)`
   composite unique index. This skips any problem that is already tagged with
   the target, preventing duplicate rows without requiring a prior existence
   check per row.
4. Deletes remaining `ProblemTag` rows for the source tag and then deletes
   the source `Tag` row itself.
5. Refreshes and returns the target tag object.

The entire sequence runs inside the caller's transaction, making the merge
atomic.

#### Content moderation (REQ-468, REQ-470, REQ-472, REQ-474)

**List flags** (`GET /admin/moderation/flags`): `get_flagged_content` returns
`Flag` rows ordered by `created_at DESC`. An optional `?status=` query
parameter (e.g., `pending`, `resolved`) filters the result set.

**Resolve flag** (`POST /admin/moderation/flags/{flag_id}/resolve`):
`resolve_flag` sets `Flag.status = "resolved"`, writes the admin's
`resolution_note` and `resolved_by` (the requesting admin's UUID), flushes,
and emits a `flag.resolved` log event. The admin UUID is extracted from
the `AdminUser` dependency injected directly into the route handler.

**De-anonymize** (`POST /admin/moderation/de-anonymize/{problem_id}`):
`de_anonymize` first verifies the target problem exists and is actually
anonymous (HTTP 400 if it is not). Before returning any data it writes an
`AuditLog` record carrying `action="de_anonymize"`, `target_type="problem"`,
`target_id`, and `metadata_` containing the `author_id`. The flush order is
deliberate: the audit row is committed to the database before the author
identity is returned to the caller. This ensures traceability even if the
application crashes after the flush but before the response is sent. A
`admin.de_anonymize` log event is also emitted via `log_event`.

#### Runtime configuration (REQ-476)

**List** (`GET /admin/config/`): `get_config` returns all `AppConfig` rows
ordered alphabetically by key.

**Upsert** (`PATCH /admin/config/`): `update_config` validates the provided
key against `ALLOWED_CONFIG_KEYS` (defined in `app/models/app_config`). If the
key is not in the allowlist it raises HTTP 400 before touching the database. If
the key exists its value is updated in-place; if it does not exist a new
`AppConfig` row is inserted. A `config.updated` log event is emitted on every
successful write.

---

### Key Design Decisions

**Single router-level auth guard.** Rather than applying `require_admin` to
each route individually, it is passed as a `dependencies` argument to the
parent `APIRouter`. Any route included under `admin_router` is automatically
protected. New routes added to any sub-router inherit the guard without
developer action. A graceful import fallback (`try/except ImportError`) allows
the admin router to load during development before the auth module exists,
without silently removing protection in production.

**Service layer owns domain exceptions; routes own HTTP translation.** The
service modules raise typed Python exceptions (`CategoryNotFoundError`,
`CategoryInUseError`, `TagNotFoundError`, `TagNameConflictError`,
`TagMergeError`). Routes catch these and return the appropriate HTTP status
codes. This keeps service logic free of HTTP concerns and makes it testable
without a running web server.

**Soft delete for categories, hard delete for tags.** Categories carry
structural meaning — they are referenced by problems and must be recoverable
or auditable. Tags are editorial labels; deleting one removes all its
associations, which is the expected behavior. The two policies are therefore
intentionally different.

**Merge atomicity via ON CONFLICT DO NOTHING.** The tag merge could have been
implemented with a per-row `SELECT` before each `INSERT`. Instead, a single
bulk `INSERT ... ON CONFLICT DO NOTHING` is used, relying on the database
unique index on `(problem_id, tag_id)` to silently skip duplicates. This
eliminates the N+1 pattern and makes the deduplication logic a database
invariant rather than application logic.

**Audit-before-reveal for de-anonymization.** The `AuditLog` row is flushed
before `de_anonymize` returns the `author_id`. This write-ahead pattern means
the audit trail is durable even if the caller never receives the response (e.g.,
due to a network failure). The same operation also emits a `log_event` call for
real-time observability.

**Config key allowlist.** Rather than allowing arbitrary key-value writes,
`update_config` validates the key against `ALLOWED_CONFIG_KEYS` and returns
HTTP 400 for unrecognized keys. This prevents accidental or malicious injection
of undocumented config keys and makes the set of tuneable parameters explicit
and auditable.

**Dual logging on mutations.** Every state-changing operation in
`app/services/admin.py` calls both `db.flush()` (durable write to the
transaction) and `log_event(...)` (structured log emission). This gives
operators both a database audit trail and a real-time log stream.

---

### Configuration

The Admin Subsystem does not read environment variables directly. Its behavior
is influenced by one model-level constant:

| Constant | Location | Effect |
|---|---|---|
| `ALLOWED_CONFIG_KEYS` | `app/models/app_config` | Defines the exhaustive set of keys that `update_config` will accept. Any key not in this set is rejected with HTTP 400. To expose a new runtime setting, add its key to this set. |

No feature flags gate individual routes. All admin functionality is available
once `require_admin` resolves successfully.

The `_slugify` function in `app/services/categories.py` uses Python's `re`
module to normalize category names into URL-safe slugs. There is no
configurable slug strategy; the algorithm is fixed at
`lowercase → strip non-word chars → collapse whitespace/underscores to hyphens`.

---

### Error Behavior

The table below covers all error conditions reachable through the Admin
Subsystem's public API surface.

| Condition | HTTP Status | Detail message |
|---|---|---|
| User not found (role or status update) | 404 Not Found | `"User not found"` |
| Category not found (update or delete) | 404 Not Found | `"Category not found"` |
| Category has live problem references (delete) | 409 Conflict | `"Category is referenced by existing problems and cannot be deleted"` |
| Tag not found (rename, delete, or merge) | 404 Not Found | `"Tag {tag_id} not found"` |
| Tag name already taken (rename) | 409 Conflict | `"A tag with that name already exists"` |
| Merge source equals target | 400 Bad Request | `"Source and target tags must be different"` |
| Flag not found (resolve) | 404 Not Found | `"Flag not found"` |
| Problem not found (de-anonymize) | 404 Not Found | `"Problem not found"` |
| Problem is not anonymous (de-anonymize) | 400 Bad Request | `"Problem is not anonymous"` |
| Config key not in allowlist (upsert) | 400 Bad Request | `"Key '{key}' is not an allowed config key. Allowed: {sorted list}"` |
| Invalid `?sort=` value on tag list | 422 Unprocessable Entity | `"sort must be 'name' or 'usage'"` |

**Transaction and flush semantics.** All service functions call `db.flush()`
rather than `db.commit()`. The session transaction is committed (or rolled
back) by the database dependency in `app/database` after the route handler
returns. If a flush raises an integrity error (e.g., a race condition on a
unique constraint), the exception propagates as an unhandled 500 unless caught
by a higher-level error handler. The ON CONFLICT DO NOTHING path in
`merge_tags` is the one deliberate exception: it absorbs duplicate-key
conflicts at the SQL level before they can surface as Python exceptions.

**De-anonymize partial-failure window.** Because the audit log is flushed
before the HTTP response is sent, a crash between flush and response delivery
will leave an audit record with no corresponding disclosure to the requester.
The admin would need to re-request; the second call will succeed (there is no
idempotency guard on the de-anonymize endpoint) and will write a second audit
record. This is accepted behavior — over-auditing is preferable to
under-auditing.

**Auth failure.** If `require_admin` raises (e.g., missing or invalid token,
insufficient role), FastAPI returns the response before any route handler
executes. The specific status code and message are determined by the auth
module, not by this subsystem.

<!-- END VERBATIM: module-admin.md -->

### 3.12 Middleware & Logging

<!-- BEGIN VERBATIM: module-middleware.md -->

### Module Reference: Middleware & Logging

**Spec requirements covered:** REQ-908, REQ-918, REQ-924, REQ-912, REQ-104

**Source files:**
- `app/middleware/security.py`
- `app/middleware/logging.py`
- `app/middleware/rate_limit.py`
- `app/logging.py`

---

### Purpose

The Middleware & Logging module is the application's first and last line of defense on every HTTP request. It handles four concerns that must operate uniformly across all routes without burdening individual endpoint authors:

1. **Security hardening** (REQ-908, REQ-918): Attach a fixed set of browser-security response headers, including a strict Content-Security-Policy, to every outbound response.
2. **XSS prevention** (REQ-924): Provide a callable sanitizer that strips dangerous HTML from user-supplied content before it is stored or rendered.
3. **Structured observability** (REQ-912): Emit machine-readable JSON log lines for every request and response, with a correlation ID threaded through the entire request lifecycle.
4. **Magic-link rate limiting** (REQ-104): Enforce a per-email cap of 5 magic-link requests per 10-minute window to prevent email-based abuse.

---

### How It Works

#### Security Headers — `SecurityHeadersMiddleware`

`SecurityHeadersMiddleware` is a Starlette `BaseHTTPMiddleware` subclass registered globally on the ASGI application. On every response it calls `response.headers.setdefault(header, value)` for each entry in the `_SECURITY_HEADERS` dict, which contains:

| Header | Value |
|---|---|
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `X-XSS-Protection` | `1; mode=block` |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=()` |
| `Content-Security-Policy` | see below |

The CSP value (REQ-918) is assembled at module import time from the `_CSP` constant:

```
default-src 'self';
script-src 'self';
style-src 'self' 'unsafe-inline';
img-src 'self' data:;
font-src 'self';
frame-ancestors 'none';
form-action 'self';
base-uri 'self'
```

Using `setdefault` means any route that explicitly sets one of these headers retains its value; the middleware only fills gaps.

#### HTML Sanitization — `sanitize_html`

`sanitize_html(text: str) -> str` is a standalone function in `app/middleware/security.py`. It is not a middleware; endpoint code calls it explicitly before persisting or returning user-supplied HTML. Processing happens in two passes:

**Pass 1 — whole-element removal.** A `re.sub` call with `re.DOTALL` removes the full opening tag, body, and closing tag of elements that have no safe use at all: `script`, `style`, `iframe`, `object`, `embed`, `applet`, `form`, `input`, `textarea`, `select`, and `button`.

**Pass 2 — tag-level filtering.** The `_TAG_RE` regex matches every remaining HTML tag. The `_replace_tag` callback:
- Drops the tag entirely if its name is not in `_SAFE_TAGS`.
- For safe tags, calls `_clean_attrs` to strip `on*` event-handler attributes (matched by `_EVENT_HANDLER_RE`) and `javascript:` href values (matched by `_JS_HREF_RE`) from the attribute string, then reconstructs the sanitized tag.

The safe-tag allowlist is: `p`, `strong`, `em`, `code`, `pre`, `blockquote`, `ul`, `ol`, `li`, `a`, `br`, `h1`–`h6`.

#### Structured JSON Logging — `LoggingMiddleware` and `JSONFormatter`

**`app/logging.py`** defines `JSONFormatter`, a `logging.Formatter` subclass. `format()` builds a dict with four mandatory keys (`timestamp`, `level`, `logger`, `message`) and then merges in optional fields when present on the log record: `correlation_id`, any flattened `extra_data`, and a formatted exception string. The dict is serialized with `json.dumps(..., default=str)`, so non-serializable values (datetimes, UUIDs, etc.) fall back to their `str()` representation.

`configure_logging(environment)` replaces all handlers on the root logger with a single `StreamHandler(sys.stdout)` using `JSONFormatter`. The log level is `DEBUG` for `environment="development"` and `INFO` for everything else. This function must be called once at application startup; subsequent calls clear and reset handlers, making it safe to call in test setups.

`get_logger(name)` is a thin wrapper around `logging.getLogger(name)` for consistent naming under the `aion.*` hierarchy.

**`app/middleware/logging.py`** defines `LoggingMiddleware`, a Starlette `BaseHTTPMiddleware`. Its `dispatch` method:

1. Reads the `X-Correlation-ID` request header; generates a new `uuid.uuid4()` string if absent.
2. Stores the correlation ID in a module-level `contextvars.ContextVar` (`_correlation_id_ctx`). Any code running in the same async context can retrieve it via `get_correlation_id()`.
3. Emits a `request_started` INFO log containing the method, path, query string, and `user_id` cookie value.
4. Awaits `call_next(request)` under a `try/except`. On exception, emits `request_failed` with duration and re-raises.
5. On success, emits `request_finished` with status code, duration in milliseconds, and response body size (when `Content-Length` is present).
6. Writes `X-Correlation-ID` back onto the response headers so clients and upstream proxies can correlate entries.

**`log_event`** in `app/logging.py` is an audit-trail helper for business events (e.g., `problem.solved`). It calls `get_correlation_id()` to attach the active request's correlation ID to the event log line, linking audit records to HTTP traffic.

#### Magic-Link Rate Limiting — `MagicLinkRateLimiter`

`MagicLinkRateLimiter` maintains an in-memory `dict[str, list[float]]` keyed by email address. Each value is a list of Unix timestamps for recent attempts. On each call to `check(email)`:

1. The current time minus `window_seconds` (600 s) is computed as `cutoff`.
2. Expired timestamps are pruned from the email's list in place.
3. If the remaining count is `>= max_requests` (5), an `HTTPException(429)` is raised with a `Retry-After` header whose value is the integer seconds until the oldest recorded attempt ages out of the window, plus one second of buffer.
4. Otherwise the current timestamp is appended and the call returns normally.

The `cleanup()` method removes entire email keys whose all timestamps have expired. It must be called by a periodic background task to prevent unbounded memory growth; the limiter does not self-clean.

A module-level singleton `magic_link_limiter` is created at import time. The `check_magic_link_rate(email)` function delegates to it and is designed for use as a FastAPI dependency.

---

### Key Design Decisions

**`setdefault` over direct assignment for security headers.** The middleware does not overwrite headers that routes set explicitly. This gives route handlers an escape hatch (e.g., serving a file download that needs a different `Content-Disposition`) while still ensuring headers are present on all other responses.

**`contextvars.ContextVar` for correlation IDs.** Python's `contextvars` module provides async-safe, task-local storage without requiring the correlation ID to be threaded through every function signature. Code anywhere in the call stack — including `log_event` — can call `get_correlation_id()` without coupling to the HTTP layer.

**Two-pass sanitization strategy.** Whole-element removal in Pass 1 catches tags whose body content is also dangerous (e.g., `<script>alert(1)</script>`). A tag-only regex in Pass 2 would strip the `<script>` wrapper but leave the JS text in the output. Running whole-element removal first closes that gap before Pass 2 handles attribute-level vectors.

**In-memory rate limiter, no Redis.** The design comment in `rate_limit.py` is explicit: this is a single-process deployment where a Redis dependency is not justified at current scale. IP-level throttling is delegated to NGINX upstream. The application-level limiter adds per-email granularity as defense in depth. Teams scaling to multiple processes must replace `magic_link_limiter` with a shared-backend implementation.

**`json.dumps(default=str)` fallback.** Rather than pre-converting every log field, the formatter relies on `default=str` to handle unanticipated types gracefully. This avoids `TypeError` on log records that carry unexpected metadata while ensuring output remains valid JSON.

**Lazy import of `get_correlation_id` in `log_event`.** `app/logging.py` imports from `app/middleware/logging` inside the function body, not at the top of the module. This breaks a potential circular import: the middleware imports `get_logger` from `app/logging`, and `app/logging` would form a cycle if it imported the middleware at module level.

---

### Configuration

#### `configure_logging(environment: str)`

Called once at application startup. Controls the log level:

| `environment` value | Effective log level |
|---|---|
| `"development"` | `DEBUG` |
| anything else | `INFO` |

All output goes to `stdout` via `StreamHandler`. There is no file handler or log rotation configured in this module.

#### `SecurityHeadersMiddleware` — no runtime configuration

The security headers and CSP value are compile-time constants defined at the top of `app/middleware/security.py`. Changing any header value requires editing the source and redeploying. This is intentional: header policy is a security-sensitive artifact that should live in version control, not in environment variables.

#### `MagicLinkRateLimiter(max_requests, window_seconds)`

The singleton is instantiated with defaults:

| Parameter | Default | Meaning |
|---|---|---|
| `max_requests` | `5` | Maximum allowed requests within the window |
| `window_seconds` | `600` | Sliding window duration in seconds (10 minutes) |

To override, replace the module-level `magic_link_limiter` singleton before the application starts or instantiate `MagicLinkRateLimiter` with custom arguments and wire it into the dependency. There is no environment-variable or settings-file hook for these values in the current implementation.

#### `LoggingMiddleware` — no configuration

Correlation ID header name (`X-Correlation-ID`) and the logger name (`aion.http`) are hardcoded. The log level for request lifecycle events is always `INFO`; exceptions use `logger.exception` which emits at `ERROR` with a traceback.

---

### Error Behavior

#### Security headers

`SecurityHeadersMiddleware` calls `call_next` unconditionally and applies headers to whatever response is returned, including error responses (4xx, 5xx). The middleware itself has no error path: if `call_next` raises, the exception propagates to Starlette's exception handler before the middleware can attach headers. Security headers will therefore be absent on responses produced by Starlette's internal error boundary (e.g., unhandled 500s that bypass the middleware chain).

#### HTML sanitization

`sanitize_html` does not raise. If the input contains malformed or deeply nested HTML that the regexes cannot fully parse, the function returns a best-effort sanitized string. Callers are responsible for treating an empty or suspicious output as an application-level error. There is no logging or exception generated by the sanitizer itself.

#### Structured logging

`LoggingMiddleware` re-raises any exception from `call_next` after logging a `request_failed` entry. The `duration_ms` field is included in the failure log. No exception is swallowed. If the logger itself fails (e.g., disk full on a file handler), the standard Python logging machinery suppresses the `logging` error by default; this does not affect request processing.

#### Rate limiting

When the per-email limit is exceeded, `MagicLinkRateLimiter.check` raises `fastapi.HTTPException` with:

- **Status code:** `429 Too Many Requests`
- **Detail:** `"Too many magic link requests"`
- **`Retry-After` header:** integer seconds until the oldest qualifying timestamp expires from the window, plus one second of buffer to account for sub-second timing.

FastAPI's exception handler converts this to a JSON response automatically. No log entry is emitted by the limiter itself; if rate-limit events need to be audited, the calling route handler is responsible for logging before calling `check_magic_link_rate`.

If `cleanup()` is never called, expired entries accumulate in `_attempts` indefinitely. Memory growth is bounded by the number of distinct email addresses that have ever made a magic-link request, not by request volume, so this is a slow leak rather than an acute risk — but `cleanup()` should still be scheduled.

<!-- END VERBATIM: module-middleware.md -->

### 3.13 Leaderboard

<!-- BEGIN VERBATIM: module-leaderboard.md -->

### Module Reference: Leaderboard

**Spec coverage:** REQ-370 (top solvers), REQ-372 (top reporters), REQ-374 (time-based filtering)

**Source files:**
- `app/services/leaderboard.py` — ranking logic and database queries
- `app/routes/leaderboard.py` — HTTP endpoint and request validation

---

### Purpose

The Leaderboard module exposes a single ranked-list endpoint that surfaces two competitive tracks across the application's user base:

- **Top solvers** (REQ-370): users ranked by the number of accepted solutions they have submitted.
- **Top reporters** (REQ-372): users ranked by the total upstars received on problems they have authored.

Both tracks support time-based filtering (REQ-374), letting callers scope rankings to all activity, the last 30 days, or the last 7 days. The module is read-only and has no write side effects.

---

### How it works

#### Endpoint

```
GET /leaderboard
```

**Query parameters:**

| Parameter | Type | Default | Allowed values |
|-----------|------|---------|----------------|
| `track` | string | `solvers` | `solvers`, `reporters` |
| `period` | string | `all_time` | `all_time`, `this_month`, `this_week` |
| `limit` | integer | `20` | `1` – `100` |

**Response shape:**

```json
{
  "track": "solvers",
  "period": "this_week",
  "entries": [
    {
      "rank": 1,
      "user_id": "<uuid>",
      "display_name": "alice",
      "accepted_count": 42
    }
  ]
}
```

For the `reporters` track, the per-entry metric key is `upstar_count` instead of `accepted_count`.

#### Request routing

`app/routes/leaderboard.py` validates the three query parameters using FastAPI's `Query()` declarative binding (with `ge=1, le=100` enforcement on `limit`) and delegates immediately to one of two service functions based on the `track` value. The route performs no data transformation beyond wrapping the service result with `track` and `period` labels.

#### Ranking — top solvers (REQ-370)

`get_top_solvers()` issues a single aggregating SQL query:

1. Joins `users` to `solutions` on `Solution.author_id == User.id`.
2. Filters to rows where `Solution.status == "accepted"` and `Solution.is_anonymous IS FALSE`.
3. If a time window is active, adds `Solution.created_at >= cutoff`.
4. Groups by `(User.id, User.display_name)`, counts matching solution rows as `accepted_count`.
5. Orders by `accepted_count DESC`, then `User.display_name ASC` as a stable tiebreaker.
6. Applies `LIMIT`.

Rank numbers are assigned in Python by enumerating the returned rows (`rank = idx + 1`), so rank 1 is always the row with the highest `accepted_count`.

#### Ranking — top reporters (REQ-372)

`get_top_reporters()` follows the same pattern with different joins:

1. Joins `users` to `problems` on `Problem.author_id == User.id`, then joins `upstars` on `Upstar.problem_id == Problem.id`.
2. Filters to rows where `Problem.is_anonymous IS FALSE`.
3. If a time window is active, adds `Problem.created_at >= cutoff`.
4. Groups by `(User.id, User.display_name)`, counts upstar rows as `upstar_count`.
5. Orders by `upstar_count DESC`, then `User.display_name ASC`.

#### Time filtering (REQ-374)

The `_period_cutoff()` helper maps `TimePeriod` enum values to UTC cutoff datetimes:

| `period` value | Cutoff |
|----------------|--------|
| `all_time` | `None` (no filter applied) |
| `this_month` | `now - 30 days` |
| `this_week` | `now - 7 days` |

When `cutoff` is `None`, the `WHERE` clause for the timestamp column is omitted entirely, so the query touches all historical rows.

For solvers, the cutoff filters on `Solution.created_at` — meaning a solution counts toward a time-bounded ranking based on when it was submitted, not when its parent problem was posted.

For reporters, the cutoff filters on `Problem.created_at` — upstars are counted only from problems posted within the window, regardless of when those upstars were cast.

---

### Key design decisions

**Single endpoint, two tracks via query parameter.** Rather than separate `/leaderboard/solvers` and `/leaderboard/reporters` routes, the module uses a `track` parameter on one route. This keeps the URL surface minimal and allows clients to switch tracks without changing the base path. The route handler's `if/else` on `track` is intentionally shallow — all branching logic lives in the service layer.

**Anonymous content is excluded.** Solutions marked `is_anonymous=True` do not contribute to a solver's `accepted_count`, and problems marked `is_anonymous=True` do not contribute to a reporter's `upstar_count`. This preserves the opt-out contract that anonymous contributors have: choosing anonymity means forgoing leaderboard credit. The filter is applied in SQL, not post-processing, so anonymous entries never appear in the result set.

**Rank is computed in application code, not SQL.** `ROW_NUMBER()` or `RANK()` window functions are not used. Because the query result is already ordered and limited, the Python enumeration `rank = idx + 1` is equivalent and avoids a dependency on database-specific window function syntax. This is valid as long as `limit` is applied in SQL before Python enumeration, which it is.

**`this_week` means a rolling 7-day window, not a calendar week.** `timedelta(weeks=1)` produces `now - 7 days`, not "since last Monday." Similarly, `this_month` is `now - 30 days`, not "since the 1st of this month." This makes the cutoff continuously sliding rather than resetting at calendar boundaries, which avoids discontinuous ranking jumps at midnight on Mondays or the first of the month.

**Reporter time filter applies to problem creation, not upstar casting.** The `Problem.created_at >= cutoff` clause determines which problems are eligible, but the upstars on those eligible problems are counted in full regardless of when they were cast. An upstar given today on a problem posted six weeks ago would be excluded from `this_month` rankings because the problem falls outside the window. This was a deliberate scoping choice: the ranking rewards recent problem-posting activity, not recent voting activity on old posts.

**Stable alphabetical tiebreaker.** Both queries include `User.display_name ASC` as a secondary sort. This ensures that users with identical scores appear in a deterministic order across requests, preventing ranking shuffles due to non-deterministic database ordering.

---

### Configuration

All configurable values are passed as query parameters by the caller; there are no server-side environment variables or application settings specific to this module.

The `limit` parameter accepts values from `1` to `100` (inclusive). FastAPI enforces this range via `Query(20, ge=1, le=100)` and returns a `422 Unprocessable Entity` response automatically if the constraint is violated — no service-layer guard is needed.

The default values applied when parameters are omitted:

| Parameter | Default |
|-----------|---------|
| `track` | `solvers` |
| `period` | `all_time` |
| `limit` | `20` |

There is no pagination beyond `limit`. Callers that need more than 100 entries cannot request them through this endpoint as currently implemented.

---

### Error behavior

**Invalid `track` or `period` value.** FastAPI validates enum membership before the handler runs. A value outside `{solvers, reporters}` or `{all_time, this_month, this_week}` produces a `422 Unprocessable Entity` response with a structured validation error body. The service layer is never called.

**`limit` out of range.** A `limit` below `1` or above `100` also produces a `422 Unprocessable Entity` response from FastAPI's `ge`/`le` constraint. The service layer is never called.

**Empty result set.** If no users qualify (e.g., no accepted solutions exist in the requested time window), the service returns an empty list. The route returns HTTP 200 with `"entries": []`. This is not treated as an error.

**Database failure.** Neither the route nor the service catches SQLAlchemy exceptions. An unhandled database error propagates to the application's global exception handler. Under standard FastAPI setups this produces a `500 Internal Server Error`. No partial results are returned — the response is all-or-nothing.

**Tied scores at the boundary of `limit`.** If the Nth and (N+1)th users share an identical score, only the user whose `display_name` sorts earlier alphabetically appears in the result. The other is silently excluded. There is no tie-expansion mechanism.

<!-- END VERBATIM: module-leaderboard.md -->

### 3.14 Infrastructure & Deployment

<!-- BEGIN VERBATIM: module-infra.md -->

### Module Reference: Infrastructure & Deployment

**Covers:** FastAPI app factory · NGINX reverse proxy · Podman Compose · Alembic migrations · Health checks · Operational scripts

**Requirements satisfied:** REQ-906, REQ-908, REQ-910, REQ-912, REQ-914, REQ-920, REQ-922, REQ-928, REQ-368

---

### 1. FastAPI App Factory

#### Purpose

`app/main.py` is the sole entry-point that assembles a fully configured FastAPI application instance. All middleware, exception handlers, and routers are registered here, giving one authoritative place to reason about startup order and cross-cutting concerns.

#### How it works

`create_app()` is an application factory — it calls `get_settings()` to read environment configuration, then builds and returns a `FastAPI` instance. The module-level `app = create_app()` line makes the result importable by uvicorn (`app.main:app`).

Middleware is added in outermost-first order — the first `add_middleware` call wraps all subsequent ones:

1. `SecurityHeadersMiddleware` — injects HTTP security headers on every response (REQ-908).
2. `LoggingMiddleware` — emits structured per-request log lines (REQ-912).
3. `SessionMiddleware` — manages signed server-side sessions using `JWT_SECRET`.

All domain-specific exceptions (`AppError` and its subclasses) are mapped to deterministic HTTP status codes via `_EXCEPTION_STATUS_MAP`. Any `AppError` subclass not listed in the map falls back to `500`. The handler returns a consistent `{"detail": "..."}` JSON envelope.

Routers are registered unconditionally; prefix and tag configuration is owned by each router module.

#### Key design decisions

- **Factory pattern over module-level construction.** Wrapping construction in `create_app()` means test suites can call the factory with patched settings and get a clean, isolated instance instead of sharing global state.
- **Middleware ordering is explicit.** The outermost layer (security headers) must run even if an inner layer raises, so it is registered first. Logging sits inside security so the log record can observe the response headers that were added.
- **Belt-and-suspenders security headers.** `SecurityHeadersMiddleware` applies headers at the application layer independently of NGINX. If the service is ever reached directly — during local development, internal calls, or misconfigured proxy routing — security headers are still present. NGINX adds the same headers at the edge for defense in depth (REQ-908).
- **Centralised exception mapping.** Rather than scattering `HTTPException` raises across business logic, domain exceptions carry their own semantics and the factory translates them once. This keeps business logic free of HTTP concepts.

#### Configuration

| Setting | Source | Effect |
|---|---|---|
| `APP_NAME` | `settings.APP_NAME` | Sets the OpenAPI `title` field |
| `JWT_SECRET` | `settings.JWT_SECRET` (SecretStr) | Signs session cookies |

All settings are read from `app.config.get_settings()`, which in turn reads environment variables and a `.env` file.

#### Error behavior

- An `AppError` subclass present in `_EXCEPTION_STATUS_MAP` returns the mapped code with `{"detail": "<message>"}`.
- An `AppError` subclass not in the map returns `500` with the exception message or class name.
- Unhandled exceptions bubble to FastAPI's default handler (500 with generic detail).
- Middleware errors (e.g., a failure inside `SecurityHeadersMiddleware`) propagate as unhandled 500s; they are not caught by the `AppError` handler.

---

### 2. NGINX Reverse Proxy

#### Purpose

NGINX (`nginx/nginx.conf`) is the public-facing edge component. It terminates TLS, enforces per-route rate limits, serves the static SPA, and detects link-preview crawlers so they receive Open Graph HTML rather than the SPA shell.

#### How it works

**Rate limiting zones (REQ-910).** Three `limit_req_zone` directives are declared in the `http` block, each keyed on `$binary_remote_addr` (the client IP in 4-byte binary form, chosen to minimise shared-memory footprint):

| Zone | Shared memory | Steady-state rate | Applied to |
|---|---|---|---|
| `api` | 10 MB | 30 r/s | All `/api/` traffic |
| `auth` | 10 MB | 5 r/s | `/api/auth/` |
| `magic` | 10 MB | 1 r/s | `/api/auth/magic` |

Location blocks match most-specific first: `/api/auth/magic` is matched before `/api/auth/` which is matched before `/api/`. Each block applies `burst` queuing with `nodelay` to reject excess requests immediately rather than queuing them. Rate-limit violations return a custom JSON body `{"error": "rate_limit_exceeded", ...}` via a named `@rate_limited` location, avoiding NGINX's default plain-text error page.

**TLS termination (REQ-906).** The production TLS block is present but commented out. When enabled it listens on port 443, loads a certificate and key from `/etc/nginx/ssl/`, enforces TLSv1.2 and TLSv1.3, and adds an HSTS header (`max-age=31536000; includeSubDomains`). The current development default listens on port 8000 (mapped to host port 80 in Compose).

**Security headers (REQ-908).** `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, and `Referrer-Policy: strict-origin-when-cross-origin` are added to every response via `add_header ... always`. The `always` flag ensures headers are present even on error responses. These headers duplicate those set by `SecurityHeadersMiddleware` in the application layer — intentional belt-and-suspenders defense.

**Link-preview bot detection (REQ-368).** A `map` block inspects `$http_user_agent` against a set of case-insensitive patterns (Twitterbot, facebookexternalhit, Slackbot, LinkedInBot, Discordbot, TelegramBot, WhatsApp) and sets `$is_link_preview_bot` to `1` on a match. The `/problems/<uuid>` location block checks this variable: matching bots are rewritten to `/api/problems/<uuid>/meta` and proxied to the `api` upstream, which returns a minimal HTML page containing Open Graph tags. Non-bot requests fall through to the SPA root with `try_files`.

**WebSocket support.** The `/ws` location upgrades the connection via `proxy_http_version 1.1` and `Upgrade`/`Connection` headers.

**Static file serving.** All non-matched paths use `try_files $uri /index.html` — the standard SPA fallback pattern. Attachments are served directly from the `/data/attachments/` volume using an `alias` directive, bypassing the application tier.

#### Key design decisions

- **Zone granularity by risk profile.** Magic-link endpoints are the single most abuse-sensitive surface (they authenticate users from a link in an email). A dedicated 1 r/s zone reduces their blast radius independently of the broader auth zone.
- **`nodelay` on burst.** Bursts are permitted to handle brief legitimate spikes (e.g., page-load parallelism) but are not queued. Queuing would delay responses during an attack and inflate perceived latency without improving security.
- **Custom 429 JSON body.** API clients expect JSON. NGINX's default error page is HTML. The named-location technique produces a machine-readable response without requiring a separate error-page file.
- **Bot rewrite before SPA fallback.** Placing the bot-redirect `if` block inside the `/problems/` location rather than a separate server block keeps routing logic co-located and avoids duplicating the SPA fallback for non-bot requests.
- **TLS configuration commented-in rather than absent.** Operators enabling production TLS uncomment existing, tested configuration rather than writing it from scratch, reducing the chance of misconfiguration.

#### Configuration

| Directive | Value | Purpose |
|---|---|---|
| `worker_processes` | `auto` | Match available CPU cores |
| `worker_connections` | `1024` | Max simultaneous connections per worker |
| `keepalive_timeout` | `65s` | Keep upstream connections alive |
| `gzip_types` | text/html, application/json, text/css, application/javascript | Compress API and SPA assets |
| `limit_req_zone api` | 30 r/s, 10 MB | General API rate limit |
| `limit_req_zone auth` | 5 r/s, 10 MB | Auth endpoint rate limit |
| `limit_req_zone magic` | 1 r/s, 10 MB | Magic-link rate limit |
| TLS certificate path | `/etc/nginx/ssl/cert.pem` | Mount point for production cert |
| TLS key path | `/etc/nginx/ssl/key.pem` | Mount point for production key |
| Static root | `/usr/share/nginx/html` | Built SPA files |
| Attachments alias | `/data/attachments/` | Shared volume with `api` service |

#### Error behavior

- Requests exceeding a rate limit zone receive `429` with JSON `{"error": "rate_limit_exceeded", "retry_after": "<value>"}`. The `retry_after` field is populated from the upstream `Retry-After` header if present, and empty otherwise.
- If the `api` upstream is unavailable, NGINX returns `502 Bad Gateway`.
- If `try_files` cannot resolve a static asset and the SPA fallback `/index.html` is also missing, NGINX returns `404`.
- A bot request for a `problem_id` that does not exist will proxy to the application tier, which returns `404 {"detail": "Problem not found"}` — the bot receives a non-2xx HTML-content-type response, which most crawlers interpret as an unfurling failure rather than a hard error.

---

### 3. Podman Compose Stack (REQ-920)

#### Purpose

`podman-compose.yml` defines the complete three-service runtime stack — `postgres`, `api`, and `nginx` — as a rootless Podman deployment. It encodes startup ordering, health-gate dependencies, volume mounts, and the single network namespace shared by all services.

#### How it works

**Service topology.** Three services start in dependency order enforced by `condition: service_healthy`:

```
postgres  (health: pg_isready)
    └── api  (health: httpx GET /health)
            └── nginx  (starts after api is healthy)
```

No service starts until its dependency reports healthy, preventing nginx from proxying to an unready API or the API from migrating against an unready database.

**`postgres` service.** Uses the official `postgres:16` image. Database name, user, and password are read from environment variables with defaults (`aion_bulletin`, `aion`, `changeme`). Data is persisted to the named volume `pgdata`. The healthcheck polls `pg_isready` every 10 seconds with a 5-second timeout and allows up to 5 consecutive failures before marking the container unhealthy.

**`api` service.** Built from the local `Dockerfile`. Runs `uvicorn app.main:app --host 0.0.0.0 --port 8000`. Port 8000 is exposed only within the Compose network (`expose`, not `ports`), so it is not reachable from the host directly — all external traffic must pass through nginx. The application source at `./app` is bind-mounted at runtime for development; the `attachments` named volume is shared with nginx. Configuration is injected via `.env` file. The healthcheck makes an HTTP GET to `http://localhost:8000/health` using `httpx` (already a runtime dependency) every 30 seconds; 3 consecutive failures mark the service unhealthy.

**`nginx` service.** Uses `nginx:stable-alpine`. The config file is bind-mounted read-only (`nginx.conf:/etc/nginx/conf.d/default.conf:ro`). Port 80 on the host maps to port 80 in the container. Nginx does not define its own healthcheck; the `depends_on` condition on `api` is sufficient since nginx has no internal state to probe.

**Rootless deployment (REQ-920).** Podman runs containers without a root daemon. All processes inside containers run as non-root UIDs mapped to the host user's subuid range. Named volumes (`pgdata`, `attachments`) are managed by Podman under the user's home directory, not `/var/lib/docker`.

#### Key design decisions

- **`expose` instead of `ports` for the API.** Keeping port 8000 off the host interface ensures all traffic — including health checks from external monitors — flows through NGINX, where rate limiting and security headers are enforced.
- **`condition: service_healthy` rather than `depends_on` without condition.** Plain `depends_on` only waits for the container to start, not for the service inside it to be ready. The health-gate pattern prevents race conditions during cold starts and after a postgres restart.
- **Shared `attachments` volume between `api` and `nginx`.** Attachments written by the API are served directly by NGINX via `alias /data/attachments/`, avoiding a round-trip through the application tier for binary file downloads.
- **`.env` file injection.** All secrets (database password, JWT secret, SMTP credentials) live in `.env` rather than being baked into the compose file or image layers. The `.env` file is not committed to source control.
- **`postgres:16` pinned minor-version series.** Using `postgres:16` (rather than `latest`) pins to a major version so automated pulls do not silently introduce breaking changes, while still receiving patch updates within the series.

#### Configuration

| Variable | Default | Service | Purpose |
|---|---|---|---|
| `POSTGRES_DB` | `aion_bulletin` | postgres | Database name |
| `POSTGRES_USER` | `aion` | postgres | Superuser name |
| `POSTGRES_PASSWORD` | `changeme` | postgres | Superuser password — must be overridden in production |
| All `app/config.py` vars | — | api | Injected via `.env` file |

Named volumes: `pgdata` (postgres data directory), `attachments` (user-uploaded files).

#### Error behavior

- If `postgres` never becomes healthy (e.g., wrong password), `api` remains in the `starting` state indefinitely. Podman Compose does not automatically abort; the operator must inspect `podman logs` to diagnose.
- If the `api` healthcheck fails 3 times in a row after the start period, Podman marks the container `unhealthy`. The container continues running — Compose does not restart it automatically unless a restart policy is configured. Use the systemd unit generated by `generate-systemd.sh` for automatic restart behavior.
- If the `./app` bind mount is missing (e.g., running from a CI artifact without source), the API container will fail to import its application module and exit with a non-zero code before the healthcheck ever passes.

---

### 4. Alembic Migrations

#### Purpose

`alembic/env.py` configures Alembic to run schema migrations against the application's async PostgreSQL engine. It bridges the synchronous Alembic runner with the async SQLAlchemy 2.0 engine, and pulls the database URL from application settings so there is a single source of truth for connection configuration.

#### How it works

On import, `env.py` calls `get_settings()` and injects the resulting `DATABASE_URL` into the Alembic config object via `config.set_main_option("sqlalchemy.url", ...)`. This means `alembic.ini` does not need to contain a database URL and the file is safe to commit.

All SQLAlchemy model classes are imported indirectly through `app.models.Base` — the `# noqa: F401` comment on that import is intentional: the import must occur for Alembic's autogenerate to detect model metadata even though `Base` itself is not explicitly used in the file.

`target_metadata = Base.metadata` gives Alembic the full schema map for `--autogenerate` diff comparisons.

**Online mode** (the normal path) uses `async_engine_from_config()` with `poolclass=pool.NullPool`. `NullPool` is required for migration runs: Alembic opens and closes a single connection per migration batch, and a connection pool would hold that connection open past the point where Alembic expects to release it, causing deadlocks under some database configurations. The async engine is run inside `asyncio.run()` in `run_migrations_online()`, wrapping the async coroutine in a synchronous entry point that Alembic can call.

**Offline mode** configures the context with a literal URL and emits SQL to stdout rather than executing it against a live database. This is used to generate migration scripts for review or for applying to databases where direct access is restricted.

#### Key design decisions

- **Database URL from settings, not `alembic.ini`.** This eliminates a second place where database credentials could diverge from the application configuration and prevents credentials from accidentally appearing in a committed `alembic.ini`.
- **`NullPool` for migrations.** Connection pooling is counterproductive for migrations (short-lived, single-connection workloads). `NullPool` ensures the connection is fully closed after each migration transaction, which is required for certain Alembic operations that alter connection-level state (e.g., `SET search_path`).
- **Async engine with sync runner.** Alembic's runner is synchronous; the application uses an async engine. The `run_sync` bridge (`connection.run_sync(do_run_migrations)`) is the standard Alembic pattern for running a synchronous migration context on an async connection without losing the async engine's driver.

#### Configuration

| Setting | Source | Effect |
|---|---|---|
| `DATABASE_URL` | `get_settings().DATABASE_URL` | Connection string for the migration engine |
| Config file logging | `alembic.ini` | Python logging for Alembic output |

Migrations are run with:

```bash
alembic upgrade head          # apply all pending migrations
alembic revision --autogenerate -m "<description>"  # generate a new migration
alembic downgrade -1          # roll back one step
```

#### Error behavior

- If `DATABASE_URL` is unset or malformed, `get_settings()` raises a `pydantic.ValidationError` before any migration logic runs.
- If the database is unreachable, `async_engine_from_config()` raises a `sqlalchemy.exc.OperationalError` from within `asyncio.run()`, and the process exits with a non-zero code. No partial migration is applied.
- If an autogenerated migration contains a destructive operation (e.g., `DROP TABLE`), Alembic does not block it. Review generated scripts before applying to production.
- Offline mode with a malformed URL produces a script with an incorrect `--` preamble; the error is silent until the script is executed against a database.

---

### 5. Health Check Endpoint (REQ-928)

#### Purpose

`GET /healthz` is the liveness and readiness probe endpoint. It concurrently exercises the two external dependencies — PostgreSQL and the file-storage directory — and returns a structured JSON report with an overall status and per-check detail. The HTTP status code alone is sufficient for orchestrators; the JSON body provides diagnostic detail for operators.

#### How it works

Two async probe functions run concurrently via `asyncio.gather()`:

**`_check_database()`** opens an `async_session_factory()` context and executes `SELECT 1`. The query is wrapped in `asyncio.wait_for(..., timeout=2.0)` so a slow or unresponsive database does not block the probe indefinitely. Success returns `{"status": "ok"}`; timeout returns `{"status": "fail", "error": "timeout"}`; any other exception returns `{"status": "fail", "error": "<exception message>"}`.

**`_check_storage()`** runs a blocking filesystem operation on the executor thread pool to avoid blocking the event loop. It calls `storage_path.mkdir(parents=True, exist_ok=True)` (creating the directory if needed) then opens a `NamedTemporaryFile` with `delete=True` inside the storage directory. Successfully creating and immediately closing the temp file proves both that the path is writable and that there is sufficient space for a create operation. The entire executor call is also wrapped in `asyncio.wait_for(..., timeout=2.0)`.

The handler aggregates check results, sets the response status to `503` if any check reports `"fail"`, and returns:

```json
{
  "status": "ok" | "degraded",
  "checks": {
    "database": {"status": "ok" | "fail", "error": "..."},
    "storage":  {"status": "ok" | "fail", "error": "..."}
  }
}
```

The Podman Compose healthcheck (`api` service) calls this endpoint via `httpx.get('http://localhost:8000/health').raise_for_status()`, which treats any non-2xx status (including 503) as an unhealthy signal.

Note: the compose healthcheck targets `/health` while the route is registered at `/healthz`. These must be kept in sync; a mismatch causes the container to report permanently unhealthy on startup.

#### Key design decisions

- **Concurrent probes with independent timeouts.** Running probes with `asyncio.gather()` means a 2-second timeout on the database probe and a 2-second timeout on the storage probe produce a worst-case response time of approximately 2 seconds, not 4. Each probe's timeout is independent, so a hung storage check does not delay the database result.
- **Temp-file writability probe rather than a stat check.** `os.access(path, os.W_OK)` checks permission bits but does not detect a full filesystem or a read-only bind mount. Creating and deleting a real temp file proves end-to-end writability.
- **2-second per-check timeout.** Short enough that orchestrators with 10-second probe timeouts receive a response well within their deadline, and long enough to tolerate a transient database query under moderate load.
- **503 status on degradation.** Kubernetes, Podman Compose, and most load balancers treat any non-2xx as unhealthy. Returning 503 rather than 200 with `"status": "degraded"` means the endpoint works correctly with orchestrators that inspect only the status code.
- **No authentication on `/healthz`.** Health probes run before or independently of user sessions. Requiring authentication would prevent the probe from working during cold start or session-store degradation.

#### Configuration

| Setting | Source | Effect |
|---|---|---|
| `STORAGE_PATH` | `get_settings().STORAGE_PATH` | Directory probed for writability |
| `_CHECK_TIMEOUT` | Module constant, `2.0` | Per-probe timeout in seconds |

#### Error behavior

- If both checks fail, the response is `503` with `"status": "degraded"` and both `checks` entries showing `"fail"`.
- If only one check fails, the same 503 / `"degraded"` response is returned — there is no partial-health status code.
- If the storage path cannot be created (e.g., parent directory is read-only), `mkdir` raises `PermissionError`, which is caught and returned as `{"status": "fail", "error": "..."}`.
- The handler does not retry on failure. Transient failures (e.g., a momentary database blip) will cause the probe to report unhealthy for that cycle and recover on the next poll.

---

### 6. Open Graph Meta Endpoint (REQ-368)

#### Purpose

`GET /api/problems/{problem_id}/meta` returns a minimal HTML page containing Open Graph meta tags for a specific problem. It exists exclusively to serve link-preview crawlers (Twitterbot, Slackbot, Discordbot, etc.) that do not execute JavaScript and therefore cannot read metadata from the React SPA.

#### How it works

NGINX identifies crawlers via the `$is_link_preview_bot` map variable. When a crawler requests `/problems/<uuid>`, NGINX rewrites the path to `/api/problems/<uuid>/meta` and proxies the request to the `api` service. Human browsers are served `index.html` directly from the static root.

The handler queries the `problems` table for the given UUID. If found, it constructs a raw HTML string using Python's `html.escape()` to sanitise all user-supplied content before embedding it in tag attributes. The description is truncated to 200 characters to stay within typical crawler limits. Five Open Graph properties are emitted: `og:title`, `og:description`, `og:url`, `og:site_name`, and `og:type` (hardcoded to `"article"`). The response is returned as `HTMLResponse` with content-type `text/html`.

The canonical URL (`og:url`) is constructed as `{BASE_URL}/problems/{problem.id}` — pointing at the SPA route, not the meta endpoint itself. This ensures that when a user clicks a link preview they land on the interactive problem page.

#### Key design decisions

- **NGINX-layer routing, not application-layer user-agent detection.** Bot detection in NGINX keeps the application tier free of user-agent sniffing and ensures the redirect happens before any application middleware runs, reducing unnecessary load.
- **`html.escape()` on all user content.** Problem titles and descriptions are user-supplied. Injecting them unescaped into an HTML attribute would create a stored XSS vector in a context (a shared link preview) that could be seen by users who never visited the bulletin.
- **Minimal HTML with no scripts or styles.** Crawlers extract meta tag content only; any additional markup wastes bandwidth and creates surface area for rendering issues in crawler engines.
- **Description truncated to 200 characters.** Open Graph consumers typically display 100–160 characters of description text. Truncating at the data layer ensures the truncation is deterministic regardless of which crawler processes the page.

#### Configuration

| Setting | Source | Effect |
|---|---|---|
| `BASE_URL` | `get_settings().BASE_URL` | Canonical origin for `og:url` construction |
| `APP_NAME` | `get_settings().APP_NAME` | Value of the `og:site_name` tag |

#### Error behavior

- If `problem_id` is not a valid UUID, FastAPI's path parameter validation returns `422 Unprocessable Entity` before the handler is called.
- If the problem is not found, the handler raises `HTTPException(status_code=404, detail="Problem not found")`. Crawlers receiving a 404 will not cache or display a preview.
- If `BASE_URL` is not set, `get_settings()` raises a validation error at application startup — the endpoint will never be reachable if configuration is incomplete.
- If the database is unavailable, the `get_db` dependency raises an exception, which propagates as a 500 response. Crawlers that receive a 5xx may retry; no permanent unfurl failure is recorded.

---

### 7. Backup and Restore Scripts (REQ-914)

#### Purpose

`scripts/backup.sh` and `scripts/restore.sh` provide operator-run database backup and recovery. The backup script implements a 7-daily / 4-weekly retention policy using `pg_dump` with gzip compression. The restore script validates the target environment, applies the backup, and verifies the result with a table-count check.

#### How it works

**backup.sh.** On each invocation:

1. Validates that all five required environment variables (`PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`) are set; exits 1 immediately if any are missing.
2. Creates `$BACKUP_DIR/daily/` and `$BACKUP_DIR/weekly/` directories if they do not exist.
3. Runs `pg_dump ... --clean --if-exists | gzip > <daily_file>`. The `--clean --if-exists` flags cause the dump to include `DROP ... IF EXISTS` statements before each `CREATE`, making restores idempotent against an existing schema.
4. If today is Sunday (`DAY_OF_WEEK=7`), copies the just-written daily file to `$BACKUP_DIR/weekly/` — promoting it to a weekly backup without a second dump.
5. Applies retention: lists files in `daily/` sorted newest-first, removes all past position 7; does the same for `weekly/` past position 4.

**restore.sh.** On each invocation:

1. Validates that exactly one argument (the backup file path) is provided.
2. Verifies the backup file exists on disk.
3. Validates the five required environment variables.
4. Pipes `gunzip -c <file>` to `psql ... -q` against the target database.
5. Queries `information_schema.tables` to count tables in the `public` schema; exits 1 if the count is zero (indicating an empty or failed restore).

Both scripts use `set -euo pipefail` — any command that exits non-zero aborts the script immediately, and unbound variable references are fatal errors.

All output is timestamped via the `log()` function (`[YYYY-MM-DD HH:MM:SS] message`), making entries suitable for ingestion by structured log collectors.

#### Key design decisions

- **`--clean --if-exists` in pg_dump.** Restoring to a database that already has tables would fail without the `DROP ... IF EXISTS` preamble. Including these statements in every dump means `restore.sh` does not need to drop and recreate the database schema before running, which simplifies the restore procedure and reduces the blast radius of a mistaken restore target.
- **Weekly promotion by copy, not a second dump.** Running `pg_dump` twice on Sunday doubles I/O and increases the window during which the dump might capture a different state than the daily backup. Copying the daily file ensures the weekly archive is bit-for-bit identical to the daily one taken on the same day.
- **Retention via `ls -1t | tail -n +N`.** This approach avoids interpreting timestamps embedded in filenames, which would break if the date format ever changed. Sorting by modification time and pruning by list position is robust to filename format changes.
- **Post-restore table-count verification.** A restore can appear to succeed (zero exit code from `psql`) while silently failing to apply any statements if, for example, the dump was truncated. The table-count check catches the most common class of silent failure.
- **No automatic scheduling.** The scripts are designed to be invoked by a cron job or a systemd timer owned by the operator, not to schedule themselves. This separates mechanism from policy and allows the operator to choose scheduling infrastructure.

#### Configuration

| Variable | Default | Purpose |
|---|---|---|
| `BACKUP_DIR` | `/data/backups` | Root directory for daily and weekly archives |
| `PGHOST` | (required) | PostgreSQL host |
| `PGPORT` | (required) | PostgreSQL port |
| `PGDATABASE` | (required) | Database name |
| `PGUSER` | (required) | Database user |
| `PGPASSWORD` | (required) | Database password (used by `pg_dump`/`psql` via env) |

#### Error behavior

- Any missing required environment variable causes an immediate exit 1 before any database connection is attempted.
- If `pg_dump` fails (non-zero exit), the partial output file is deleted with `rm -f` and the script exits 1. A partial backup file is never left in the daily directory.
- If `gunzip | psql` fails during restore, the script exits 1 but does not attempt to roll back the partially applied SQL. The operator must inspect the database state and re-run the restore if needed.
- If the post-restore table count is zero, the script exits 1 with a `"Verification failed"` log line. This does not undo the restore — it is a diagnostic, not a rollback.
- Retention failures (e.g., `rm` on a read-only filesystem) abort the script via `set -e`. A failed retention step is treated as a fatal error to avoid silently accumulating files until the disk is full.

---

### 8. Systemd Unit Generation (REQ-922)

#### Purpose

`scripts/generate-systemd.sh` generates `systemd` unit files from running Podman containers and reloads the systemd daemon, enabling the containers to start automatically on system boot and to be managed with standard `systemctl` commands.

#### How it works

1. Verifies `podman` is in `$PATH`.
2. Verifies the script is running as root (required to write to `/etc/systemd/system/`).
3. Queries `podman ps --format '{{.Names}}'` and filters for containers whose names start with `$PROJECT_NAME` (default: `aion-bulletin`). Exits 1 with instructions if none are found.
4. For each matching container, calls `podman generate systemd --name <container> --restart-policy=always --new`, writing the output to `/etc/systemd/system/container-<container>.service`.
5. Checks the generated unit file for `Restart=always`; if absent, injects it immediately after the `[Service]` section header as a safety net.
6. Runs `systemctl daemon-reload` to register the new unit files with systemd.
7. Prints instructions for enabling and starting each unit with `systemctl enable --now`.

The `--new` flag tells `podman generate systemd` to generate a unit that creates and destroys the container on start/stop rather than one that wraps a pre-existing container. This is the correct mode for boot-time units because no container will exist at cold boot.

#### Key design decisions

- **Generates units from live containers, not from the Compose file.** Running containers have resolved image IDs, environment bindings, and volume mounts. Generating from them captures the exact runtime configuration rather than re-interpreting the Compose file.
- **Belt-and-suspenders `Restart=always` injection.** `podman generate systemd --restart-policy=always` should already emit `Restart=always`, but the script verifies and injects it if missing to guard against Podman version differences in output format.
- **Root check before side effects.** The script validates prerequisites before making any filesystem changes. This avoids a partial run where some units are written before the permission error surfaces.
- **Must be run after `podman-compose up -d`.** The script requires at least one running container to discover. This is a documented prerequisite (printed in the error message) rather than a hidden dependency.

#### Configuration

| Variable | Default | Purpose |
|---|---|---|
| `PROJECT_NAME` | `aion-bulletin` | Prefix filter for container name discovery |
| `UNIT_DIR` | `/etc/systemd/system` | Destination for generated `.service` files |

Generated unit files are named `container-<container_name>.service`.

#### Error behavior

- If `podman` is not installed, the script exits 1 before any filesystem writes.
- If run as non-root, the script exits 1 before any filesystem writes.
- If no containers match `$PROJECT_NAME`, the script exits 1 with a message directing the operator to run `podman-compose up -d` first.
- If `podman generate systemd` fails for a specific container (e.g., the container is in an error state), `set -e` causes the script to abort at that point. Unit files for earlier containers in the loop will have been written; the operator must inspect and clean up manually.
- If `systemctl daemon-reload` fails (e.g., systemd is not running, as in a container or WSL environment without systemd), the script exits 1 after having already written unit files. The files remain on disk and can be loaded once systemd is available.

<!-- END VERBATIM: module-infra.md -->

### 3.15 Frontend SPA

<!-- BEGIN VERBATIM: module-frontend.md -->

### Module Reference: Frontend SPA

**Stack:** React 18.3 + Vite 5.3 + TypeScript 5.5 + React Router 6  
**Entry point:** `frontend/src/main.tsx`  
**Build output:** `frontend/dist/`  
**Spec coverage:** REQ-500, REQ-502, REQ-504, REQ-506, REQ-508, REQ-510, REQ-512, REQ-514, REQ-516, REQ-518, REQ-520, REQ-522, REQ-524, REQ-526, REQ-528

---

### Purpose

The Frontend SPA is the sole user-facing client for the Aion Bulletin platform. It delivers a single-page application that lets employees browse, submit, and collaborate on workplace problems. The SPA serves two distinct audiences: general users (browsing the problem feed, submitting problems, writing solutions and comments) and administrators (managing categories, tags, users, and flagged content through a gated admin section). The application runs entirely in the browser; all data access goes through a REST/WebSocket backend proxied at `/api` and `/ws`.

---

### How It Works

#### App Shell Structure

`main.tsx` boots React 18 in Strict Mode, mounts `<App />` to `#root`, and imports the global stylesheet (`App.css`). `App.tsx` composes the full provider and routing tree:

```
<BrowserRouter>
  <ThemeProvider>           ← injects CSS custom properties, exposes useTheme()
    <ToastProvider>         ← global toast queue, renders <ToastContainer />
      <MainLayout>          ← responsive shell (sidebar + mobile header)
        <Suspense fallback={<AppFallback />}>
          <Routes> ... </Routes>
        </Suspense>
      </MainLayout>
    </ToastProvider>
  </ThemeProvider>
</BrowserRouter>
```

`MainLayout` uses `useMediaQuery("(min-width: 1024px)")` to decide whether the sidebar is permanently visible (desktop) or toggled via a hamburger button (mobile). On mobile the sidebar renders as an overlay with a backdrop click-to-dismiss. The `Sidebar` component reads `VITE_APP_NAME` from the environment for the application title.

#### Routing Strategy — Lazy Loading (REQ-500)

Every page is loaded with `React.lazy()` and a shared `<Suspense>` boundary in `App.tsx`. There is no per-route Suspense; all routes share a single centered spinner (`AppFallback`). This keeps the initial bundle small: the vendor chunk (React + React Router) loads immediately, and page chunks are fetched on demand.

Route table:

| Path | Component | Notes |
|---|---|---|
| `/` | `Landing` | Redirects to `/problems` if already authenticated |
| `/problems` | `Feed` | Infinite-scroll problem list |
| `/problems/:id` | `ProblemDetail` | Tab-based (solutions / comments) |
| `/submit` | `Submit` | Auth-gated inline, not via route guard |
| `/search` | `Search` | Debounced keyword search |
| `/ai-search` | `AISearch` | Placeholder (coming soon) |
| `/leaderboard` | `Leaderboard` | Track + period filters |
| `/settings` | `Settings` | Dark mode + notification prefs |
| `/admin` | `Dashboard` | Wrapped in `AdminRouteGuard` |
| `/admin/categories` | `Categories` | Wrapped in `AdminRouteGuard` |
| `/admin/tags` | `Tags` | Wrapped in `AdminRouteGuard` |
| `/admin/users` | `Users` | Wrapped in `AdminRouteGuard` |
| `/admin/moderation` | `Moderation` | Wrapped in `AdminRouteGuard` |
| `*` | `NotFound` | Catch-all 404 |

#### Authentication Flow (REQ-504)

Authentication is session-cookie-based; the SPA does not manage tokens directly. `useAuth` (a standalone hook, not a context) is called per-component. On mount it calls `GET /api/auth/me` with `credentials: "include"`. Two login methods are available:

- **Microsoft OIDC redirect:** `login()` sets `window.location.href = "/api/auth/login"`, triggering a server-side OIDC redirect to Azure AD.
- **Magic link:** `loginWithMagicLink(email)` posts to `/api/auth/magic/send`; the user follows the emailed link, which sets the session cookie.

`logout()` posts to `/api/auth/logout` then clears local state regardless of network outcome so the UI is never stuck in a logged-in state on a failed request.

The `AuthCard` component presents both methods on a tabbed card rendered on the `Landing` page. `Landing` redirects authenticated users to `/problems` immediately after `isLoading` clears.

Admin route protection is handled by `AdminRouteGuard`, which wraps each admin page's inner content component. It checks `isLoading`, then `isAuthenticated`, then `user.role === "admin"`, redirecting to `/` at any failure point. Unauthenticated and non-admin users are silently bounced; no error message is shown on redirect.

#### Data Fetching Patterns

The SPA uses the native `fetch` API throughout — no external HTTP client. All requests pass `credentials: "include"` so cookies are sent. Patterns in use:

- **One-shot fetch on mount:** `ProblemDetail`, `Leaderboard`, `Admin/*` pages fetch on `useEffect` with a `useCallback`-wrapped async function. AbortControllers cancel in-flight requests when dependencies change.
- **Infinite scroll (REQ-508):** `Feed` uses `IntersectionObserver` on a sentinel `<div>` at the bottom of the list. When the sentinel enters the viewport (with a `200px` root margin for pre-loading), the next page is fetched using a cursor returned in `FeedResponse.nextCursor`. Sort/filter changes reset the cursor and refetch from the beginning; an `AbortController` ref prevents race conditions.
- **Debounced search (REQ-518):** `Search` debounces the raw query input by 300ms using `setTimeout`/`clearTimeout` before firing a fetch. `TagAutocomplete` debounces tag lookups by 200ms. Both components hold an `AbortController` ref to cancel superseded requests.
- **Optimistic toggle:** `ProblemDetail` applies upstar and claim state changes to local React state immediately on a successful API response, without a full refetch.
- **Two-step form submission:** `Submit` first posts the problem JSON, then uploads attachments as `multipart/form-data` in a second request. If attachments fail after a successful problem creation, the user is shown an error toast but is still navigated to the new problem.

#### State Management

There is no global state library. State is managed entirely with React's built-in primitives:

- `useState` / `useReducer` for local component state.
- `useContext` for the two cross-cutting concerns: `ThemeContext` (from `ThemeProvider`) and `ToastContext` (from `ToastProvider`).
- `useAuth` is a standalone hook that re-fetches `/api/auth/me` independently in every component that calls it. There is no shared auth context; each call creates its own `AuthState`.

---

### Key Design Decisions

| Decision | Alternatives Considered | Why This Choice |
|---|---|---|
| CSS custom properties for theming | Tailwind CSS, CSS-in-JS (styled-components, Emotion) | Zero runtime overhead; dark/light mode flips by toggling eight root variables set in `applyCssVariables`. Adding Tailwind would require purge configuration and couples class names to design tokens. CSS-in-JS adds bundle weight and runtime cost. |
| Lazy-loaded routes with a single Suspense boundary | Per-route Suspense, React Router's data loader API | Keeps `App.tsx` simple. A single spinner covers all page transitions uniformly. Per-route Suspense would require duplicating fallback UI across 13 routes. |
| No global auth context; `useAuth` called per component | Shared `AuthContext`, Redux/Zustand slice | Avoids a provider wrapping every test and every page. The cost — an extra `/api/auth/me` call per mounting component — is acceptable given the session-cookie model (the browser caches at the network layer). |
| Native `fetch` over Axios | Axios, `swr`, `react-query` | Zero additional dependencies; the fetch API covers all required patterns (AbortController, FormData, credentials). `react-query` would simplify infinite scroll and cache but was out of scope. |
| `IntersectionObserver` for infinite scroll | Scroll event listener, `react-infinite-scroll-component` | Observer-based approach is performant (no per-scroll handler) and declarative. The sentinel div pattern requires no third-party library. |
| `useMediaQuery` hook for responsive layout | CSS-only responsive classes, container queries | JavaScript breakpoint detection lets `MainLayout` conditionally render the mobile header in React rather than using CSS `display: none`, keeping DOM structure clean and accessible. |
| Regex-based Markdown renderer built-in to `MarkdownEditor` | `marked`, `remark`, `react-markdown` | Eliminates a parsing dependency. Handles headings, bold, italic, code blocks, links, blockquotes, and lists — the subset actually used in problem descriptions. Preview is debounced 300ms so it never blocks typing. |
| `data-theme` attribute on `<html>` for dark mode | Class-based toggling, separate stylesheets | Single attribute switch allows all CSS selectors to scope their dark variants with `[data-theme="dark"]`. The `useDarkMode` hook persists the mode preference as `"light"`, `"dark"`, or `"system"` in `localStorage` under key `pb-theme`, defaulting to `"system"`. |
| `AdminRouteGuard` wrapping inner content component | Route-level wrapper in `App.tsx` | Keeps admin page components self-contained: each page imports and applies its own guard. No central route configuration needs to distinguish admin vs. public routes. |

---

### Configuration

#### Vite Proxy (`frontend/vite.config.ts`)

During development, Vite proxies two path prefixes to `http://localhost:8000`:

| Prefix | Target | WebSocket? |
|---|---|---|
| `/api` | `http://localhost:8000` | No |
| `/ws` | `http://localhost:8000` | Yes (`ws: true`) |

`changeOrigin: true` rewrites the `Host` header so the backend does not reject requests. In production, these paths are expected to be handled by a reverse proxy (e.g., nginx) at the network level — no Vite proxy is involved.

A TypeScript path alias is configured:

```
"@" → "./src"
```

This allows imports like `import { useAuth } from "@/hooks/useAuth"` throughout the codebase.

#### Build Scripts (`frontend/package.json`)

| Script | Command | Purpose |
|---|---|---|
| `dev` | `vite` | Dev server with HMR on the default Vite port |
| `build` | `tsc && vite build` | Type-check first, then produce optimized production bundle |
| `preview` | `vite preview` | Serve the production build locally for smoke-testing |

The `build` script runs `tsc` before Vite so type errors fail the build. The output is an ESM bundle emitted to `frontend/dist/`.

#### Environment Variables

| Variable | Used In | Default | Purpose |
|---|---|---|---|
| `VITE_APP_NAME` | `Sidebar.tsx` | `"Aion Bulletin"` | Application display name in sidebar header |

#### Runtime Dependencies

The dependency footprint is intentionally minimal:

| Package | Version | Role |
|---|---|---|
| `react` | ^18.3.1 | UI rendering |
| `react-dom` | ^18.3.1 | DOM reconciler |
| `react-router-dom` | ^6.23.1 | Client-side routing |

No state management library, no HTTP client, no CSS framework, no Markdown parser, no date library.

---

### Error Behavior

#### Toast Notification System (REQ-528)

`ToastProvider` maintains a queue managed by `useReducer`. Toasts have three severity levels: `"success"`, `"error"`, `"info"`. The queue is capped at three visible toasts; when a fourth arrives, the oldest is silently dropped. Each toast auto-dismisses after 5 seconds (configurable per call) via a `setTimeout` stored in a `Map` ref. Timers are cleared on manual dismiss and on unmount.

`ToastContainer` renders at the bottom of the provider tree (outside `MainLayout`), ensuring toasts overlay all page content. Each `ToastItem` applies a CSS `toast--visible` class on the next animation frame to trigger a CSS fade-in transition; dismissal delays the `REMOVE` dispatch by 200ms to allow a fade-out animation to complete.

`useToast()` throws if called outside `ToastProvider`, providing a clear misconfiguration message.

#### Feed and Search Error States

`Feed`, `Search`, `Leaderboard`, and all admin pages display inline error messages with a `role="alert"` attribute when fetches fail. `Feed` additionally renders a "Retry" button that re-triggers the fetch from the beginning. `AbortError` rejections from cancelled requests are silently swallowed and never surfaced to the user.

#### Problem Detail Error States

`ProblemDetail` shows a full-page error block with a "Retry" button when the primary problem fetch fails. Solutions and comments fetch errors are swallowed silently (non-critical sections); the page still renders with empty tabs rather than blocking.

#### Form Validation (Submit Page)

`Submit` uses progressive disclosure validation: errors are only shown for fields the user has touched (`touched` state map). On form submission, all fields are marked touched before the full error check. Validation runs on every field change after the first touch. Server-side errors are surfaced via the toast system, not inline.

#### HTML Content Sanitization

`ProblemDetail` renders `descriptionHtml` from the server using `dangerouslySetInnerHTML`. A local `sanitizeHtml` function strips `<script>` tags and inline event handlers (`on*` attributes) before rendering. The comment in the source acknowledges this is a basic allowlist and recommends DOMPurify for production hardening.

#### Loading States

All data-fetching pages show either:
- A skeleton card list (Feed: 5 skeleton cards during initial load),
- A centered spinner (`app-loading__spinner`), or
- Inline `"Loading..."` text with a spinner.

Admin pages and `ProblemDetail` use spinner-only loading states. The global `AppFallback` (a centered spinner) covers the Suspense boundary while lazy page chunks are downloading.

#### Notification Bell WebSocket (REQ-522)

`NotificationBell` opens a WebSocket to `ws[s]://<host>/ws/notifications` on mount. On `ws.onclose`, it schedules a reconnect after 5 seconds using a ref-guard (`wsRef.current === ws`) to prevent reconnect loops after intentional disconnects. The component stores the five most recent notifications in local state. Opening the dropdown marks all notifications as read in local state (no API call). Malformed WebSocket messages are caught and ignored.

---

### Sections by Concern

#### App Shell & Routing

- `src/App.tsx` — provider tree, lazy route definitions, single Suspense boundary
- `src/main.tsx` — React 18 `createRoot`, Strict Mode mount
- `src/layouts/MainLayout.tsx` — responsive two-column shell; hamburger toggle on mobile
- `src/layouts/Sidebar.tsx` — navigation links, theme toggle button, conditional admin nav section

#### Authentication & Authorization

- `src/hooks/useAuth.ts` — session probe (`/api/auth/me`), OIDC redirect, magic-link send, logout
- `src/components/AuthCard.tsx` — tabbed card: Microsoft OIDC button and magic-link email form
- `src/components/AdminRouteGuard.tsx` — role check wrapper; redirects to `/` for unauthenticated or non-admin users

#### Theme & Styling

- `src/theme/colors.ts` — design token constants: `lightColors`, `darkColors`, `statusColors`, `gradients`
- `src/theme/index.ts` — `ThemeProvider`, `useTheme()` hook, `applyCssVariables()` — maps tokens to CSS custom properties on `<html>`
- `src/hooks/useDarkMode.ts` — three-way mode state (`"light"` / `"dark"` / `"system"`), `localStorage` persistence, `prefers-color-scheme` detection via `useMediaQuery`
- `src/hooks/useMediaQuery.ts` — reactive `window.matchMedia` wrapper

#### Core Components

- `src/components/ProblemCard.tsx` — clickable summary card with upstar count, status badge, tags, solution/comment counts, relative timestamp
- `src/components/StatusBadge.tsx` — colour-coded badge for five statuses: `open`, `claimed`, `solved`, `accepted`, `duplicate`
- `src/components/SortFilterBar.tsx` — sort selector (new/top/active/discussed), status checkboxes, category dropdown
- `src/components/EmptyState.tsx` — generic empty-list placeholder with optional icon and CTA link
- `src/contexts/ToastContext.tsx` + `src/components/Toast.tsx` — `useReducer`-based queue, `ToastContainer`, animated `ToastItem`
- `src/components/MarkdownEditor.tsx` — split-pane editor/preview; built-in regex renderer; 300ms debounced preview; character counter with optional min/max
- `src/components/AttachmentDropZone.tsx` — drag-and-drop / click-to-browse / clipboard-paste; 10MB per-file limit; images, PDF, TXT allowed; per-file validation errors
- `src/components/TagAutocomplete.tsx` — ARIA combobox; 200ms debounced `GET /api/tags?q=`; keyboard navigation (arrows, Enter, Escape); pill display with remove buttons
- `src/components/NotificationBell.tsx` — bell icon with unread badge; WebSocket-driven notification list; auto-reconnect; navigates to problem on item click

#### Pages

- `src/pages/Landing.tsx` — decorative problem cards backdrop + `AuthCard`; redirects authenticated users to `/problems`
- `src/pages/Feed.tsx` — cursor-based infinite scroll, `IntersectionObserver` sentinel, skeleton loading, `SortFilterBar` integration
- `src/pages/ProblemDetail.tsx` — tabbed solutions/comments view; upstar/claim toggles; HTML description with client-side sanitization; collapsible threaded comments
- `src/pages/Submit.tsx` — multi-field form with `MarkdownEditor`, `TagAutocomplete`, `AttachmentDropZone`, anonymous submission toggle, two-step POST + multipart upload
- `src/pages/Search.tsx` — 300ms debounced full-text search with `AbortController` cancellation
- `src/pages/AISearch.tsx` — placeholder UI (disabled input, "Coming Soon" notice)
- `src/pages/Leaderboard.tsx` — track (solvers / reporters) and period (week / month / all-time) filter tabs; gold/silver/bronze rank styling
- `src/pages/Settings.tsx` — notification preference toggles (email on comments, solutions, status changes); dark mode toggle; persists via `PATCH /api/auth/me`

**Admin pages** (all wrapped in `AdminRouteGuard`):

- `src/pages/admin/Dashboard.tsx` — four stat cards: problems, solutions, users, flagged items
- `src/pages/admin/Categories.tsx` — create, inline-edit, delete with confirmation, and up/down reorder
- `src/pages/admin/Tags.tsx` — rename, delete with confirmation, merge via modal
- `src/pages/admin/Users.tsx` — search, inline role selector, activate/deactivate toggle
- `src/pages/admin/Moderation.tsx` — flagged content cards with resolve and de-anonymize (confirmation modal) actions

<!-- END VERBATIM: module-frontend.md -->

---

## Section 4: End-to-End Data Flow

### Scenario 1: Happy Path — User Submits a Problem and Receives a Solution

**Stage 1 — Landing and Authentication.**
The user opens the application in a browser. NGINX serves the React SPA from `/usr/share/nginx/html`. The `Landing` page renders with the cork-texture bulletin board theme and the `AuthCard` component. The user clicks "Sign in with Microsoft", which sets `window.location.href = "/api/auth/login"`. NGINX proxies this to FastAPI. The `initiate_login` function in `app/auth/oidc.py` generates a 32-byte `state` nonce, stores it in the Starlette session, and returns a redirect to the Azure AD authorization endpoint. Azure AD authenticates the user and redirects back to `/api/auth/callback` with an authorization code.

**Stage 2 — Token Issuance and User Provisioning.**
`handle_callback` in `app/auth/oidc.py` exchanges the authorization code for identity claims. It verifies the `tid` claim matches `AZURE_TENANT_ID` (rejecting cross-tenant tokens with `TenantMismatchError`). `_provision_user` executes the three-step lookup: OID match, email match with OID back-fill, or new user creation. `create_access_token` in `app/auth/jwt.py` builds an HS256 JWT with `sub`, `role`, `exp`, and `iat` claims. `set_auth_cookie` writes it as an `HttpOnly`, `SameSite=Lax` cookie with an 8-hour `max_age`. The user is redirected to `/problems`.

**Stage 3 — Problem Submission.**
The user navigates to `/submit`. The `Submit` page renders with `MarkdownEditor`, `TagAutocomplete`, category dropdown, and anonymous checkbox. As the user types a title, `TagAutocomplete` debounces at 200ms and fires `GET /api/tags?q=...`. The `Search` suggest panel shows up to 5 similar problems via `GET /search/suggest?title=...` after a 300ms debounce. The user fills the form and clicks Submit. The SPA posts `POST /api/problems` with `ProblemCreate` payload (title, description, category_id, tag_ids, is_anonymous). FastAPI validates via Pydantic (`min_length=5` on title, `min_length=10` on description). `create_problem` in `app/services/problems.py` validates the category exists and is not soft-deleted, validates tag UUIDs via a single `COUNT` query, inserts the `Problem` row with `status=open`, flushes, then bulk-inserts `ProblemTag` rows. The route calls `update_search_vector` to populate `search_vector`. If attachments are selected, a second `POST /api/problems/{id}/attachments` uploads them as `multipart/form-data`.

**Stage 4 — Auto-Watch and Notification Setup.**
After problem creation, the application calls `auto_watch(db, user_id, problem_id, level=WatchLevel.all_activity)`. This upserts a `Watch` row at `all_activity` level. The user is now watching their own problem for all events.

**Stage 5 — Another User Discovers and Posts a Solution.**
A second user browses the feed at `GET /api/problems?sort=new`. The cursor-based pagination returns `CursorPage[ProblemResponse]` with pinned problems prepended on the first page. The user clicks into the problem detail view (`GET /api/problems/{id}`). They upstar it via `POST /api/problems/{id}/upstar` — `toggle_upstar` acquires a `SELECT ... FOR UPDATE` lock on the problem row, inserts an `Upstar` row, flushes, counts, and returns `{active: true, count: N}`. They then post a solution via `POST /api/problems/{problem_id}/solutions` with `SolutionCreate` payload. `create_solution` inserts a `Solution` row with `status=pending`, creates a `SolutionVersion` with `version_number=1`, sets `current_version_id`, and updates `problem.activity_at`.

**Stage 6 — Notification Fan-Out and Delivery.**
The route calls `generate_notification(db, event_type=solution_posted, problem_id, actor_id)`. This queries all `Watch` rows for the problem excluding the actor, checks `WATCH_ROUTING[watch.level]` for each watcher, and bulk-inserts `Notification` rows for qualifying watchers. The problem author (watching at `all_activity`) receives a notification. `push_ws_notification` serializes the notification to JSON and calls `connection_manager.broadcast_to_user(recipient_id, data)`. If the author has an active WebSocket connection, the `NotificationBell` component receives the payload and updates its unread count. If `TEAMS_WEBHOOK_URL` is configured, `schedule_teams_webhook` fires an `asyncio.Task` to post an Adaptive Card.

**Stage 7 — Solution Acceptance.**
The problem author reviews the solution, clicks Accept. `POST /api/solutions/{id}/accept` calls `accept_solution`, which verifies the actor is the problem author or admin, resets any previously accepted solution on the same problem to `status=pending`, sets the target solution to `status=accepted`, and updates `problem.activity_at`. A `solution_accepted` notification fans out to all qualifying watchers.

### Scenario 2: Error/Fallback Path — Forbidden Status Transition

**Stage 1 — User Attempts Invalid Transition.**
A user who does not own a problem attempts to accept a solution. They call `POST /api/solutions/{id}/accept`.

**Stage 2 — Authorization Check.**
`accept_solution` in `app/services/solutions.py` loads the actor `User` and verifies `actor.id == problem.author_id or actor.role == UserRole.admin`. Neither condition is true.

**Stage 3 — PermissionError Raised.**
The service raises `PermissionError("Only the problem owner or an admin can accept a solution")`.

**Stage 4 — Route Translation.**
The route handler catches `PermissionError` and returns `HTTPException(status_code=403, detail="Only the problem owner or an admin can accept a solution")`. No database state is modified — `db.flush()` was never called.

**Alternate path — Forbidden FSM transition:** A user calls `POST /api/problems/{id}/status` with `target=accepted` on a problem currently in `open` status. `transition_status` looks up `(ProblemStatus.open, ProblemStatus.accepted)` in `ALLOWED_TRANSITIONS`. The pair is absent from the dict. `ForbiddenTransitionError(current="open", target="accepted")` is raised. The `_EXCEPTION_STATUS_MAP` in `app/main.py` maps this to HTTP 409. The response body includes `{"detail": "..."}` with current and target values.

### Scenario 3: Search with Fallback — Full-Text Search with Suggestions

**Stage 1 — User Types a Query.**
The user navigates to `/search` and types "clock domain crossing" into the search input. The `Search` component debounces by 300ms, then fires `GET /api/search?q=clock+domain+crossing&sort=relevance&limit=20&offset=0`.

**Stage 2 — Query Compilation.**
`search_problems` in `app/services/search.py` checks that the query is non-empty. It compiles the raw string with `plainto_tsquery('english', :query)`, which normalizes to an implicit AND of lexemes without requiring boolean syntax.

**Stage 3 — Three-Branch CTE Fan-Out.**
Three CTEs execute in one query plan: `problem_hits` matches against `problems.search_vector` (GIN-indexed), `solution_hits` matches against `to_tsvector('english', solution_versions.description)` (computed inline), and `comment_hits` matches against `to_tsvector('english', comments.body)` (computed inline). Each CTE joins back to the parent problem to produce a uniform schema: `(problem_id, title, excerpt, rank, match_source, upstar_count, p_created_at)`.

**Stage 4 — Deduplication and Ranking.**
`UNION ALL` merges the three CTEs. `SELECT DISTINCT ON (problem_id) ... ORDER BY problem_id, rank DESC` keeps only the highest-ranked match per problem. The outer `ORDER BY` applies `rank DESC` (relevance sort). `LIMIT 20 OFFSET 0` paginates.

**Stage 5 — Result Rendering.**
Results are serialized as dicts with UUIDs as strings, ranks as floats, timestamps as ISO-8601. The SPA renders each result as a clickable card with title, excerpt, match source label, upstar count, and status badge.

**Stage 6 — No Results Fallback.**
If zero rows are returned, the service returns `{"results": [], "message": "No results found"}`. The SPA renders: "No problems match your search. Try different keywords or submit a new problem." with a link to `/submit`.

**Stage 7 — Similar Problem Suggestion (Submit Page Context).**
When instead the user is on the `/submit` page and types a title, the `TagAutocomplete` integration calls `GET /api/search/suggest?title=clock+domain+crossing&limit=5`. `suggest_similar` uses the same `plainto_tsquery` + `search_vector @@` pattern but targets only the `problems` table. Up to 5 results are returned with titles and 120-character description excerpts.

### Branching Points Summary

| Decision Point | Condition | Path A | Path B |
|---|---|---|---|
| Authentication method | User clicks "Microsoft" vs "Magic Link" | OIDC redirect flow via `oidc.py` | Magic link email flow via `magic_link.py` |
| Token present on request | Cookie or Bearer header found | Decode and validate JWT | Check `DEV_AUTH_BYPASS`; if off, return 401 |
| FSM transition validity | `(current, target)` in `ALLOWED_TRANSITIONS` | Execute predicate; if True, apply transition | Raise `ForbiddenTransitionError` (409) |
| Vote toggle state | Existing vote record found | Delete record (unvote) | Insert record (vote) |
| Comment deletion | Comment has child replies | Tombstone (replace body with "[deleted]") | Hard delete (remove row) |
| Search match source | Match in problem vs solution vs comment | `match_source = "problem"` | `match_source = "solution"` or `"comment"`, join to parent problem |
| Watch level vs event type | Event type in `WATCH_ROUTING[level]` | Generate notification for this watcher | Skip this watcher |
| Attachment MIME check | Extension in `ALLOWED_TYPES` | Proceed with upload | Raise `FileTypeNotAllowedError` (422) |
| Solution edit attempt | `PATCH`/`PUT` to `/solutions/{id}` | Return 405 with message to use versioning endpoint | N/A (always rejected) |
| Pin limit check | `COUNT(is_pinned) >= MAX_PINNED` | Raise `PinLimitExceededError` (409) | Set `is_pinned = True` |

---

## Section 5: Configuration Reference

All configurable parameters consolidated from all module sections, grouped by module.

### Foundation / Config (`app/config.py`)

| Parameter | Type | Default | Valid Range | Effect |
|---|---|---|---|---|
| `DATABASE_URL` | `str` | **required** | Valid async DSN | SQLAlchemy async engine connection string |
| `AZURE_TENANT_ID` | `str` | **required** | UUID string | Azure AD tenant for OIDC token validation |
| `AZURE_CLIENT_ID` | `str` | **required** | UUID string | OAuth2 application client ID |
| `AZURE_CLIENT_SECRET` | `SecretStr` | **required** | Non-empty | OAuth2 client secret |
| `JWT_SECRET` | `SecretStr` | **required** | Non-empty | HMAC-HS256 signing key |
| `SMTP_HOST` | `str` | **required** | Hostname | Outbound SMTP relay |
| `SMTP_PORT` | `int` | `587` | 1-65535 | SMTP port (STARTTLS) |
| `SMTP_FROM` | `str` | **required** | Email address | Envelope sender for all outbound mail |
| `BASE_URL` | `AnyHttpUrl` | **required** | Valid HTTP URL | Public root URL for link construction |
| `APP_NAME` | `str` | `"Aion Bulletin"` | Any string | Display name in UI and emails |
| `DEV_AUTH_BYPASS` | `bool` | `False` | `True`/`False` | Skip auth in development; must be `False` in production |
| `ENVIRONMENT` | `Literal` | `"development"` | `development`, `staging`, `production` | Controls log level, `Secure` cookie flag, error verbosity |
| `STORAGE_PATH` | `str` | `"/data/attachments"` | Writable directory path | Root for uploaded attachment files |
| `TEAMS_WEBHOOK_URL` | `AnyHttpUrl\|None` | `None` | Valid HTTP URL or None | Teams incoming webhook for notifications |

### Database (`app/database.py`)

| Parameter | Type | Default | Valid Range | Effect |
|---|---|---|---|---|
| `echo` | `bool` | `False` | `True`/`False` | Log all SQL statements to stdout |
| `pool_pre_ping` | `bool` | `True` | `True`/`False` | Liveness check before each borrowed connection |
| `expire_on_commit` | `bool` | `False` | `True`/`False` | Whether ORM attributes expire after commit |

### Auth (`app/auth/`)

| Parameter | Type | Default | Valid Range | Effect |
|---|---|---|---|---|
| `ACCESS_TOKEN_EXPIRE_HOURS` | `int` (constant) | `8` | Positive integer | JWT lifetime; change requires code edit |
| `MAGIC_LINK_EXPIRY_MINUTES` | `int` (constant) | `15` | Positive integer | Magic link token TTL; change requires code edit |

### Problem Management (`app/services/problems.py`)

| Parameter | Type | Default | Valid Range | Effect |
|---|---|---|---|---|
| `MAX_PINNED` | `int` (constant) | `3` | Positive integer | Maximum simultaneously pinned problems |
| `limit` (feed query) | `int` | `20` | 1-50 | Non-pinned problems per page (hard-capped at 50) |
| `sort` (feed query) | `SortMode` | `new` | `new`, `top`, `active`, `discussed` | Primary sort column for feed |
| `filter_status` (feed query) | `ProblemStatus\|None` | `None` | Any `ProblemStatus` value | Filter feed to one status |
| `category_id` (feed query) | `UUID\|None` | `None` | Valid UUID | Filter feed to one category |
| `tag_ids` (feed query) | `list[UUID]\|None` | `None` | Valid UUIDs | AND-filter: problems must carry all tags |
| `is_claimed` (feed query) | `bool\|None` | `None` | `True`/`False` | Filter to claimed/unclaimed problems |

### Attachments (`app/services/attachments.py`)

| Parameter | Type | Default | Valid Range | Effect |
|---|---|---|---|---|
| `MAX_FILE_SIZE` | `int` (constant) | `10485760` (10 MB) | Positive integer | Per-file upload size limit |
| `MAX_TOTAL_SIZE` | `int` (constant) | `52428800` (50 MB) | Positive integer | Cumulative attachment size per problem |
| `ALLOWED_TYPES` | `dict` (constant) | png, jpeg, webp, gif, pdf, txt | MIME types | File type allowlist |

### Search (`app/services/search.py`)

| Parameter | Type | Default | Valid Range | Effect |
|---|---|---|---|---|
| `q` (query param) | `str` | `""` | Any string | Raw search query |
| `sort` (query param) | `str` | `"relevance"` | `relevance`, `upvotes`, `newest` | Result ordering |
| `limit` (query param) | `int` | `20` | 1-100 | Max results per page |
| `offset` (query param) | `int` | `0` | >= 0 | Pagination offset |
| `_EXCERPT_LEN` | `int` (constant) | `120` | Positive integer | Excerpt truncation length |

### Notifications (`app/services/delivery.py`)

| Parameter | Type | Default | Valid Range | Effect |
|---|---|---|---|---|
| `UPVOTE_MILESTONES` | `list[int]` (constant) | `[10, 25, 50, 100]` | Positive integers | Thresholds for milestone notifications |

### Middleware (`app/middleware/`)

| Parameter | Type | Default | Valid Range | Effect |
|---|---|---|---|---|
| `max_requests` (rate limiter) | `int` | `5` | Positive integer | Magic link requests per window |
| `window_seconds` (rate limiter) | `int` | `600` | Positive integer | Sliding window duration (seconds) |

### Leaderboard (`app/services/leaderboard.py`)

| Parameter | Type | Default | Valid Range | Effect |
|---|---|---|---|---|
| `track` (query param) | `str` | `solvers` | `solvers`, `reporters` | Leaderboard track |
| `period` (query param) | `str` | `all_time` | `all_time`, `this_month`, `this_week` | Time filter |
| `limit` (query param) | `int` | `20` | 1-100 | Max entries returned |

### NGINX (`nginx/nginx.conf`)

| Parameter | Type | Default | Valid Range | Effect |
|---|---|---|---|---|
| `worker_processes` | `string` | `auto` | `auto` or integer | CPU core matching |
| `worker_connections` | `int` | `1024` | Positive integer | Max connections per worker |
| `limit_req_zone api` | rate | `30 r/s` | Any rate | General API rate limit |
| `limit_req_zone auth` | rate | `5 r/s` | Any rate | Auth endpoint rate limit |
| `limit_req_zone magic` | rate | `1 r/s` | Any rate | Magic link rate limit |

### Podman Compose (`podman-compose.yml`)

| Parameter | Type | Default | Valid Range | Effect |
|---|---|---|---|---|
| `POSTGRES_DB` | `str` | `aion_bulletin` | Any string | Database name |
| `POSTGRES_USER` | `str` | `aion` | Any string | Database superuser |
| `POSTGRES_PASSWORD` | `str` | `changeme` | Any string | Database password (override in production) |

### Frontend (`frontend/`)

| Parameter | Type | Default | Valid Range | Effect |
|---|---|---|---|---|
| `VITE_APP_NAME` | `str` | `"Aion Bulletin"` | Any string | Application display name in sidebar |

### Runtime App Config (`app_config` table)

| Parameter | Type | Default | Valid Range | Effect |
|---|---|---|---|---|
| `max_pin_count` | `str` (value) | Not set | Numeric string | Maximum pinned problems |
| `claim_expiry_days` | `str` (value) | Not set | Numeric string | Days before claim auto-expiry |
| `magic_link_ttl_minutes` | `str` (value) | Not set | Numeric string | Magic link token lifetime |
| `auto_watch_default_level` | `str` (value) | Not set | WatchLevel value | Default watch level on problem creation |

---

## Section 6: Integration Contracts

### REST API Entry Points

All REST endpoints are served under `/api/` and proxied by NGINX to FastAPI on port 8000. Authentication is via `access_token` HttpOnly cookie (primary) or `Authorization: Bearer <token>` header (fallback).

**Problem lifecycle:**
- `POST /api/problems` — create problem (requires auth)
- `GET /api/problems` — paginated feed (auth optional)
- `GET /api/problems/{id}` — problem detail (auth optional)
- `PATCH /api/problems/{id}` — edit problem (owner or admin)
- `POST /api/problems/{id}/status` — FSM transition (varies by transition)
- `POST /api/problems/{id}/claim` — toggle claim (requires auth)
- `POST /api/problems/{id}/pin` — toggle pin (admin only)
- `POST /api/problems/{id}/upstar` — toggle upstar (requires auth)
- `POST /api/problems/{id}/attachments` — upload file (requires auth)
- `GET /api/problems/{id}/attachments` — list attachments (public)
- `POST /api/problems/{id}/watch` — set watch level (requires auth)
- `GET /api/problems/{id}/watch` — get watch level (requires auth)
- `DELETE /api/problems/{id}/watch` — remove watch (requires auth)
- `POST /api/problems/{id}/comments` — add comment (requires auth)
- `GET /api/problems/{id}/comments` — list comments (auth optional)

**Solutions:**
- `POST /api/problems/{problem_id}/solutions` — create solution (requires auth)
- `GET /api/problems/{problem_id}/solutions` — list solutions (auth optional)
- `POST /api/solutions/{id}/versions` — add version (requires auth)
- `GET /api/solutions/{id}/versions` — list versions (public)
- `POST /api/solutions/{id}/accept` — accept solution (problem owner or admin)
- `POST /api/solutions/{id}/upvote` — toggle upvote (requires auth)
- `POST /api/solutions/{id}/comments` — add comment (requires auth)
- `GET /api/solutions/{id}/comments` — list comments (auth optional)

**Comments:**
- `PATCH /api/comments/{id}` — edit comment (author only)
- `DELETE /api/comments/{id}` — delete comment (author or admin)

**Attachments:**
- `GET /api/attachments/{id}/download` — download file (public)
- `DELETE /api/attachments/{id}` — delete attachment (uploader or admin)

**Search:**
- `GET /api/search` — full-text search (public)
- `GET /api/search/suggest` — similar problem suggestions (public)

**Auth:**
- `POST /api/auth/login` — initiate OIDC redirect
- `GET /api/auth/callback` — OIDC callback
- `POST /api/auth/magic/send` — send magic link email
- `GET /api/auth/magic/verify` — verify magic link token
- `GET /api/auth/me` — current user profile (requires auth)
- `POST /api/auth/logout` — clear auth cookies

**Notifications:**
- `GET /api/notifications` — paginated notification list (requires auth)
- `PATCH /api/notifications/{id}/read` — mark one as read (requires auth)
- `POST /api/notifications/read-all` — mark all as read (requires auth)

**Leaderboard:**
- `GET /api/leaderboard` — ranked list (public)

**Tags:**
- `GET /api/tags` — list with usage counts (public)

**Admin (all require admin role):**
- `GET /api/admin/users` — user list with search
- `PATCH /api/admin/users/{id}/role` — change role
- `PATCH /api/admin/users/{id}/status` — activate/deactivate
- `POST /api/admin/categories` — create category
- `PATCH /api/admin/categories/{id}` — update category
- `PATCH /api/admin/categories/reorder` — reorder categories
- `DELETE /api/admin/categories/{id}` — soft-delete category
- `PATCH /api/admin/tags/{id}` — rename tag
- `DELETE /api/admin/tags/{id}` — delete tag
- `POST /api/admin/tags/merge` — merge tags
- `GET /api/admin/moderation/flags` — list flags
- `POST /api/admin/moderation/flags/{id}/resolve` — resolve flag
- `POST /api/admin/moderation/de-anonymize/{problem_id}` — reveal author
- `GET /api/admin/config` — list runtime config
- `PATCH /api/admin/config` — upsert config key

**Health:**
- `GET /healthz` — liveness/readiness probe (no auth)

**Meta:**
- `GET /api/problems/{id}/meta` — Open Graph HTML for link previews

### WebSocket Contract

**Endpoint:** `GET /ws/notifications?token=<JWT>`

The client must supply its JWT as a query parameter. On successful authentication, the connection is registered under the user's UUID. The server pushes JSON payloads:

```json
{
  "type": "notification",
  "payload": {
    "id": "<uuid>",
    "notification_type": "<NotificationType>",
    "problem_id": "<uuid>",
    "solution_id": "<uuid|null>",
    "actor_id": "<uuid>",
    "is_read": false,
    "created_at": "<ISO-8601>"
  }
}
```

Keep-alive: client sends `ping` text, server replies `pong`. 30-second timeout for stale connections.

### Authentication Contract

All authenticated endpoints accept one of:
1. **Cookie:** `access_token=<JWT>` with `HttpOnly`, `SameSite=Lax`, `Secure` (non-development)
2. **Header:** `Authorization: Bearer <JWT>`

JWT payload claims: `sub` (user UUID), `role` (user/admin), `exp` (Unix timestamp), `iat` (Unix timestamp). Algorithm: HS256 with `JWT_SECRET`.

### External Dependency Contracts

**PostgreSQL:** Requires PostgreSQL 16+ with `asyncpg` driver. The application expects `gen_random_uuid()` function availability, GIN index support, JSONB column type, and `tsvector`/`tsquery` full-text search primitives. Connection via `DATABASE_URL` async DSN.

**Azure AD:** Requires a single-tenant App Registration with `openid`, `profile`, and `email` scopes. The `redirect_uri` must be registered as `<BASE_URL>/auth/callback`. The application validates the `tid` claim against `AZURE_TENANT_ID`.

**SMTP Server:** Requires an SMTP relay accepting STARTTLS connections on `SMTP_PORT`. Used for magic-link emails and daily email digests. No authentication is configured in the current implementation — the relay must accept unauthenticated connections from the application host.

**Microsoft Teams (optional):** Requires an Incoming Webhook connector URL. The application posts Adaptive Card JSON payloads via `httpx.AsyncClient` with a 10-second timeout. Delivery is fire-and-forget; failures are logged but do not affect other notification channels.

---

## Section 7: Operational Notes

### Running the System

```bash
# Start the full stack
podman-compose up -d

# Apply database migrations
podman exec -it aion-bulletin-api-1 alembic upgrade head

# View logs
podman logs -f aion-bulletin-api-1

# Stop
podman-compose down
```

The startup order is health-gated: `postgres` must pass `pg_isready` before `api` starts, and `api` must pass its health check (`GET /health`) before `nginx` starts.

### Key Monitoring Signals

All logs are structured JSON emitted to stdout via `JSONFormatter`. Key fields per log entry:

- `timestamp` — ISO-8601
- `level` — DEBUG/INFO/WARNING/ERROR
- `logger` — under the `aion.*` hierarchy
- `correlation_id` — UUID linking all log entries for a single request
- `message` — event description

Key business events emitted via `log_event`:
- `problem.created`, `problem.solved`, `problem.accepted`
- `user.role_changed`, `user.status_changed`
- `flag.resolved`, `admin.de_anonymize`
- `config.updated`

Request lifecycle entries:
- `request_started` — method, path, query string, user_id cookie
- `request_finished` — status code, duration_ms, response size
- `request_failed` — duration_ms, exception traceback

### Common Failure Modes

| Symptom | Root Cause | Debug Path |
|---|---|---|
| 401 on all requests after deployment | `JWT_SECRET` changed between deploys; all outstanding tokens are invalid | Compare `JWT_SECRET` across deploys. Users must re-authenticate. |
| 502 Bad Gateway from NGINX | FastAPI container not healthy or not started | `podman logs aion-bulletin-api-1`; check health endpoint at `GET /healthz` |
| Magic link emails not arriving | SMTP relay unreachable or rejecting connections | Check `SMTP_HOST`/`SMTP_PORT` in `.env`; run `podman exec api python -c "import aiosmtplib; ..."` to test connectivity |
| Search returns stale results | `update_search_vector` not called after problem create/edit | Check that the create/edit route calls `update_search_vector(db, problem)` after mutation |
| WebSocket notifications not arriving | Token passed via `?token=` query param is expired or invalid | Check browser console for `WS_1008_POLICY_VIOLATION` close code; verify token is fresh |
| Rate limit (429) on legitimate requests | NGINX rate limit zone exceeded | Check `limit_req_zone` settings in `nginx.conf`; increase `burst` value if needed |
| Container marked unhealthy but running | Health endpoint path mismatch (`/health` vs `/healthz`) | Verify compose healthcheck path matches the registered route |
| Database connection errors at startup | `DATABASE_URL` missing or malformed | Check `.env` file; ensure DSN uses `postgresql+asyncpg://` scheme |
| Attachment upload returns 413 | File exceeds 10 MB per-file limit or 50 MB cumulative limit | Check `MAX_FILE_SIZE` and `MAX_TOTAL_SIZE` constants in `app/services/attachments.py` |
| Admin endpoints return 403 | User role is `user`, not `admin` | Promote via `PATCH /api/admin/users/{id}/role` from an existing admin account |

### Backup and Restore

**Automated backup** is handled by `scripts/backup.sh`. Schedule it via cron:

```bash
# Daily at 2:00 AM
0 2 * * * /path/to/scripts/backup.sh >> /var/log/aion-backup.log 2>&1
```

Required environment variables: `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`, `BACKUP_DIR` (default `/data/backups`).

Retention policy: 7 daily backups + 4 weekly backups. Weekly backups are promoted from the Sunday daily backup (no second dump). Retention is enforced by listing files sorted by modification time and removing excess entries.

**Restore procedure:**

```bash
# Verify backup file exists
ls -la /data/backups/daily/aion_bulletin_2026-04-14.sql.gz

# Restore to target database
./scripts/restore.sh /data/backups/daily/aion_bulletin_2026-04-14.sql.gz

# Verify restore succeeded (script checks table count automatically)
```

The restore script pipes `gunzip | psql` and runs a post-restore table-count verification. The `--clean --if-exists` flags in the dump make restores idempotent against an existing schema.

**Systemd auto-restart:**

```bash
# Generate systemd units from running containers
sudo ./scripts/generate-systemd.sh

# Enable auto-start on boot
sudo systemctl enable --now container-aion-bulletin-postgres-1.service
sudo systemctl enable --now container-aion-bulletin-api-1.service
sudo systemctl enable --now container-aion-bulletin-nginx-1.service
```

---

## Section 8: Known Limitations

The following limitations, gaps, and missing features are extracted from all module sections.

| # | Limitation | Module | Impact |
|---|---|---|---|
| 1 | **No test suite.** REQ-926 (80% test coverage) is not implemented. No pytest configuration, fixtures, or test files exist. | All | Regressions must be caught manually. |
| 2 | **AI Search is a placeholder.** The `/ai-search` route renders a disabled UI with "Coming Soon" notice. No backend API exists. | Frontend | No semantic or AI-powered search capability. |
| 3 | **No Redis or multi-process rate limiting.** `MagicLinkRateLimiter` is in-memory, single-process. Scaling to multiple API workers requires a shared-backend implementation. | Middleware | Rate limits are per-process, not global. |
| 4 | **Solutions and comments lack GIN indexes for full-text search.** Only `problems.search_vector` has a GIN index. Solution and comment search uses inline `to_tsvector()` without index support. | Search | Solution/comment search performance degrades with table size. |
| 5 | **No email delivery tracking column.** Email digest delivery uses `updated_at` on the `Notification` row as a marker. There is no dedicated `email_delivered` boolean column. | Notifications | Digest idempotency requires querying by `updated_at` range or an external job tracker. |
| 6 | **MarkdownEditor uses regex, not a library.** The built-in renderer handles headings, bold, italic, code blocks, links, blockquotes, and lists via regex. Complex or nested Markdown may not render correctly. | Frontend | Edge cases in Markdown rendering. Consider DOMPurify + a proper parser for production hardening. |
| 7 | **No pagination on leaderboard.** The endpoint returns at most 100 entries (capped by `limit` query param). There is no cursor or offset for deeper pagination. | Leaderboard | Users ranked below position 100 are inaccessible. |
| 8 | **`sanitize_html` uses regex, not a DOM parser.** Deeply nested or malformed HTML may not be fully sanitized. The comment in the frontend source recommends DOMPurify. | Middleware, Frontend | Potential XSS edge cases with adversarial input. |
| 9 | **No claim auto-expiry background job.** REQ-160 specifies 14-day claim auto-expiry. No scheduled job is implemented. | Problems | Claims are never auto-expired; manual unclaiming is required. |
| 10 | **`cleanup()` on rate limiter must be called externally.** Expired timestamp entries accumulate if no periodic task calls `magic_link_limiter.cleanup()`. | Middleware | Slow memory leak proportional to distinct email addresses. |
| 11 | **Health endpoint path mismatch.** The route is registered at `/healthz` but the compose healthcheck targets `/health`. These must be kept in sync. | Infrastructure | Potential for container to report permanently unhealthy if paths diverge. |
| 12 | **Unknown `sort` value on search silently falls back to relevance.** No validation error is raised for invalid sort parameters. | Search | API does not reject `sort=bogus`. |
| 13 | **`ForbiddenTransitionError` and `PinLimitExceededError` may propagate as 500.** Some route handlers do not explicitly catch these domain exceptions. | Problems | Relies on the global `AppError` handler in `app/main.py` being correctly configured. |
| 14 | **No duplicate-confirmation workflow.** REQ-162 specifies a two-step duplicate confirmation. The current FSM allows `open -> duplicate` as an admin-only transition without a suggestion/confirmation flow. | Problems | Duplicate detection is admin-only, not community-sourced. |
| 15 | **No `Idempotency-Key` support.** REQ-176 specifies idempotency keys on problem creation. Not implemented. | Problems | Retried POST requests may create duplicate problems. |
| 16 | **No `starred` feed filter.** REQ-182 (filter to personally upstarred problems) is not implemented. | Problems | Users cannot filter the feed to problems they have starred. |

---

## Section 9: Extension Guide

### 1. Adding a New API Endpoint

To add a new endpoint (e.g., `POST /api/problems/{id}/bookmark`):

1. **Define request/response schemas** in `app/schemas.py`. Add Pydantic `BaseModel` classes with field constraints.
2. **Implement the service function** in the appropriate `app/services/` module. The function receives an `AsyncSession` and domain-typed arguments. Call `db.flush()` (not `db.commit()`) — the `get_db` dependency handles commit/rollback.
3. **Create the route handler** in the appropriate `app/routes/` module. Inject `db: AsyncSession = Depends(get_db)` and `user: CurrentUser` (or `AdminUser`). Call the service function, catch domain exceptions, and translate them to HTTP responses.
4. **Register the router** if it is new — include it in `app/main.py` via `app.include_router(...)`.
5. **Add domain exceptions** if needed in `app/exceptions.py` as `AppError` subclasses. Add the mapping to `_EXCEPTION_STATUS_MAP` in `app/main.py`.

### 2. Adding a New ORM Model

1. **Define the model** in `app/models/` as a class inheriting from `Base` (imported from `app.database`).
2. **Use UUID primary keys** with `server_default=func.gen_random_uuid()`.
3. **Import the model** in `app/models/__init__.py` so Alembic's autogenerate can detect it.
4. **Generate a migration:**
   ```bash
   alembic revision --autogenerate -m "add <model_name> table"
   ```
5. **Review the generated migration** in `alembic/versions/` — verify column types, constraints, and indexes.
6. **Apply:**
   ```bash
   alembic upgrade head
   ```

### 3. Adding a New Notification Type

1. **Add the enum value** to `NotificationType` in `app/enums.py`.
2. **Update `WATCH_ROUTING`** in `app/services/notifications.py` — add the new type to the appropriate watch-level sets. If it should be received by `all_activity` watchers, it is automatically included (defined as `set(NotificationType)`).
3. **Call `generate_notification`** from the code path that triggers the event, passing the new `event_type`, `problem_id`, and `actor_id`.
4. **Update the WebSocket payload** if the notification carries new fields.
5. **Update the frontend `NotificationBell`** component to handle the new type's display text and navigation target.

### 4. Adding a New Frontend Page

1. **Create the page component** in `frontend/src/pages/`. Use `useAuth()` for authentication state. Use `useToast()` for error/success feedback.
2. **Add a lazy route** in `frontend/src/App.tsx`:
   ```tsx
   const NewPage = React.lazy(() => import("./pages/NewPage"));
   // In <Routes>:
   <Route path="/new-page" element={<NewPage />} />
   ```
3. **Add navigation** in `frontend/src/layouts/Sidebar.tsx`.
4. **If admin-gated**, wrap the component with `<AdminRouteGuard>`.
5. **For data fetching**, use `useEffect` + `useCallback` with `AbortController` for cancellation. Pass `credentials: "include"` on all `fetch()` calls.

### 5. Adding a New Admin Panel

1. **Create the admin page** in `frontend/src/pages/admin/`. Wrap with `AdminRouteGuard`.
2. **Add the lazy route** under the `/admin` path in `App.tsx`.
3. **Create the API endpoint** under the admin router in `app/routes/admin/`. The router-level `dependencies=[Depends(require_admin)]` automatically protects all routes.
4. **Implement the service function** in `app/services/admin.py` or a new service file. Use `log_event(...)` for audit-trail structured logging on mutations.
5. **Add navigation** to the admin section of `Sidebar.tsx` (rendered conditionally when `user.role === "admin"`).

---

## Appendix: Requirement Coverage

| Spec Requirement | Covered By (Module Section) | Notes |
|---|---|---|
| REQ-100 | 3.2 Authentication (oidc.py) | Azure AD OIDC authorization code flow |
| REQ-102 | 3.2 Authentication (oidc.py) | Single-tenant `tid` claim validation |
| REQ-104 | 3.2 Authentication (magic_link.py), 3.12 Middleware (rate_limit.py) | Magic link generation, sending, rate limiting |
| REQ-106 | 3.2 Authentication (magic_link.py) | 15-minute expiry, single-use `consumed` flag |
| REQ-108 | 3.2 Authentication (jwt.py, dependencies.py) | HS256 JWT in HttpOnly cookies; 8-hour expiry (spec says 15m access + 7d refresh; implementation uses single 8-hour token) |
| REQ-110 | 3.2 Authentication (oidc.py) | User provisioning on first OIDC login |
| REQ-112 | 3.2 Authentication (oidc.py) | Three-step user lookup (OID -> email -> create) |
| REQ-114 | 3.1 Foundation (enums.py), 3.2 Authentication (dependencies.py) | Two-role model; `require_admin` dependency |
| REQ-116 | 3.2 Authentication (dependencies.py) | `require_owner_or_admin` permission check |
| REQ-118 | 3.2 Authentication (dependencies.py) | `GET /api/auth/me` via `get_current_user` |
| REQ-120 | 3.2 Authentication (jwt.py) | `clear_auth_cookie` clears HttpOnly cookie |
| REQ-122 | 3.2 Authentication (dependencies.py) | `DEV_AUTH_BYPASS` with dev user provisioning |
| REQ-124 | 3.2 Authentication (oidc.py) | Configured via authlib OAuth registry; scopes set in registration |
| REQ-126 | 3.12 Middleware (logging.py) | Structured log entries for auth events via `log_event` |
| REQ-128 | 3.12 Middleware (rate_limit.py) | In-memory `MagicLinkRateLimiter`: 5 requests / 10 minutes |
| REQ-150 | 3.4 Problem Management | `create_problem` with category + tag validation |
| REQ-152 | 3.1 Foundation (schemas.py) | `ProblemCreate` field constraints (title 5-200, description 10+) |
| REQ-154 | 3.4 Problem Management | `is_anonymous` flag; `author_id` always stored |
| REQ-156 | 3.4 Problem Management | `ALLOWED_TRANSITIONS` FSM dict with predicates |
| REQ-158 | 3.4 Problem Management | Claim toggle; multiple claims allowed per problem |
| REQ-160 | 3.4 Problem Management | Claim model exists; auto-expiry background job not implemented |
| REQ-162 | 3.4 Problem Management | `open -> duplicate` admin-only transition; two-step confirmation not implemented |
| REQ-164 | 3.4 Problem Management | `pin_problem` with `MAX_PINNED=3` guard |
| REQ-166 | 3.4 Problem Management | `ProblemEditHistory` snapshot on edit |
| REQ-168 | 3.4 Problem Management, 3.1 Foundation (schemas.py) | Cursor-based pagination via `CursorPage[T]` |
| REQ-170 | 3.4 Problem Management | Four sort modes: `new`, `top`, `active`, `discussed` |
| REQ-172 | 3.4 Problem Management | Feed filters: status, category, tag_ids, is_claimed |
| REQ-174 | 3.4 Problem Management | Pinned problems prepended outside pagination on first page |
| REQ-176 | Not implemented | Idempotency-Key header not supported |
| REQ-178 | 3.9 Search | Full-text search endpoint |
| REQ-180 | 3.4 Problem Management | `activity_at` updated on claims, edits, solutions, comments |
| REQ-182 | Not implemented | Starred filter not available |
| REQ-200 | 3.5 Solution Management | Solutions as first-class objects with versioning |
| REQ-202 | 3.5 Solution Management | `GET /problems/{id}/solutions` listing |
| REQ-204 | 3.5 Solution Management, 3.1 Foundation (schemas.py) | `git_link` as `AnyHttpUrl | None`; anonymous via `is_anonymous` flag |
| REQ-206 | 3.5 Solution Management | Append-only versioning; PATCH/PUT return 405 |
| REQ-208 | 3.5 Solution Management | `GET /solutions/{id}/versions` ordered by version_number ASC |
| REQ-210 | 3.5 Solution Management | `accept_solution` with atomic swap of previously accepted |
| REQ-212 | 3.5 Solution Management | Default sort: accepted first, then upvote count DESC |
| REQ-214 | 3.5 Solution Management | `SolutionSortMode.newest` for chronological ordering |
| REQ-216 | 3.5 Solution Management | Anonymous masking via `_solution_to_dict` |
| REQ-218 | 3.7 Voting | Toggle semantics on `POST /solutions/{id}/upvote` |
| REQ-220 | 3.15 Frontend (StatusBadge, ProblemDetail) | Accepted solution visual distinction in UI |
| REQ-250 | 3.7 Voting | Upstar with `FOR UPDATE` lock and unique constraint |
| REQ-252 | 3.7 Voting | Toggle: delete if exists, insert if not |
| REQ-254 | 3.7 Voting | Solution upvotes in separate `solution_upvotes` table |
| REQ-256 | 3.7 Voting | Identical toggle mechanics for solution upvotes |
| REQ-258 | 3.6 Comments | Threaded via `parent_comment_id` self-referential FK |
| REQ-260 | 3.6 Comments | Anonymous masking; `is_anonymous` flag on create |
| REQ-262 | 3.6 Comments | Tombstone if replies exist; hard delete if leaf |
| REQ-264 | 3.6 Comments | `edit_comment` sets `is_edited=True`; author-only |
| REQ-266 | 3.6 Comments, 3.12 Middleware (security.py) | HTML sanitization allowlist; MarkdownEditor in frontend |
| REQ-268 | 3.13 Leaderboard | Dual-track: top solvers + top reporters |
| REQ-270 | 3.13 Leaderboard | `is_anonymous=False` filter in SQL |
| REQ-300 | 3.1 Foundation (enums.py), 3.3 Data Model | `WatchLevel` enum; `watches` table with `level` column |
| REQ-302 | 3.10 Watch & Notification Pipeline | PUT/DELETE/GET watch endpoints with upsert |
| REQ-304 | 3.10 Watch & Notification Pipeline | `auto_watch` on problem creation, claiming, solution posting |
| REQ-306 | 3.10 Watch & Notification Pipeline | `auto_watch` on commenting (never downgrades) |
| REQ-308 | 3.10 Watch & Notification Pipeline | Auto-watch respects existing higher-priority level |
| REQ-310 | 3.10 Watch & Notification Pipeline | Eight `NotificationType` enum values; per-watcher row generation |
| REQ-312 | 3.10 Watch & Notification Pipeline | `WATCH_ROUTING` matrix mapping levels to allowed types |
| REQ-314 | 3.10 Watch & Notification Pipeline | In-app notification list with pagination and mark-read |
| REQ-316 | 3.10 Watch & Notification Pipeline | WebSocket push via `ConnectionManager` singleton |
| REQ-318 | 3.10 Watch & Notification Pipeline | Teams webhook via `schedule_teams_webhook` (fire-and-forget) |
| REQ-320 | 3.10 Watch & Notification Pipeline | Email digest via `send_email_digest` with `aiosmtplib` |
| REQ-322 | 3.10 Watch & Notification Pipeline | `is_milestone` checks against `[10, 25, 50, 100]` |
| REQ-324 | 3.10 Watch & Notification Pipeline | Claim expiry notification type exists; background job not implemented |
| REQ-350 | 3.9 Search | `problems.search_vector` tsvector + GIN index |
| REQ-352 | 3.9 Search | `plainto_tsquery` with `ts_rank` scoring |
| REQ-354 | 3.9 Search | Three-branch CTE: problems + solutions + comments |
| REQ-356 | 3.9 Search | Sort modes: relevance, upvotes, newest |
| REQ-358 | 3.9 Search | Filters: category_id, status, tag_ids |
| REQ-360 | 3.9 Search, 3.15 Frontend | Empty-result message with CTA link |
| REQ-362 | 3.9 Search | `suggest_similar` endpoint for duplicate detection |
| REQ-364 | 3.9 Search | 120-character excerpt truncation |
| REQ-366 | 3.14 Infrastructure (OG meta endpoint) | `og:title`, `og:description`, `og:url`, `og:site_name`, `og:type` |
| REQ-368 | 3.14 Infrastructure (NGINX) | Bot User-Agent detection via `$is_link_preview_bot` map |
| REQ-400 | 3.8 Attachments | Multipart upload to `POST /problems/{id}/attachments` |
| REQ-402 | 3.8 Attachments | Extension-based MIME allowlist |
| REQ-404 | 3.8 Attachments | 10 MB per-file, 50 MB cumulative limits |
| REQ-406 | 3.8 Attachments | UUID filenames under `STORAGE_PATH/{problem_id}/` |
| REQ-408 | 3.3 Data Model | `attachments` table with full metadata |
| REQ-410 | 3.14 Infrastructure (NGINX) | Direct file serving via `alias /data/attachments/` |
| REQ-412 | 3.8 Attachments, 3.15 Frontend | `render_inline` flag; images inline, others as downloads |
| REQ-414 | 3.15 Frontend (AttachmentDropZone) | Clipboard paste support |
| REQ-416 | 3.8 Attachments | DB row deleted before disk file; `require_owner_or_admin` |
| REQ-450 | 3.11 Admin | Router-level `require_admin` dependency |
| REQ-452 | 3.11 Admin | Category CRUD in `app/services/categories.py` |
| REQ-454 | 3.11 Admin | Default categories seeded on first run |
| REQ-456 | 3.11 Admin | `PATCH /admin/categories/reorder` bulk update |
| REQ-458 | 3.11 Admin | Soft delete via `deleted_at`; 409 if problems reference category |
| REQ-460 | 3.11 Admin | Tag listing with `usage_count` via LEFT JOIN + GROUP BY |
| REQ-462 | 3.11 Admin | Tag rename and hard delete with cascade cleanup |
| REQ-464 | 3.11 Admin | `merge_tags` with `INSERT ... ON CONFLICT DO NOTHING` |
| REQ-466 | 3.11 Admin | User search via case-insensitive `ILIKE` |
| REQ-468 | 3.11 Admin, 3.3 Data Model | Flag model; `resolve_flag` with admin notes |
| REQ-470 | 3.11 Admin | Flagged content list with status filter |
| REQ-472 | 3.11 Admin | `de_anonymize` with `AuditLog` write-ahead pattern |
| REQ-474 | 3.11 Admin, 3.3 Data Model | `AuditLog` model; `ALLOWED_CONFIG_KEYS` for runtime config |
| REQ-476 | 3.11 Admin, 3.15 Frontend | `AdminRouteGuard` in frontend; `require_admin` in backend |
| REQ-500 | 3.15 Frontend | CSS custom properties, gradient accents, theme tokens |
| REQ-502 | 3.15 Frontend (Landing) | Cork-texture background, decorative cards, centered auth card |
| REQ-504 | 3.1 Foundation (config.py), 3.15 Frontend | `APP_NAME` env var; `VITE_APP_NAME` in sidebar |
| REQ-506 | 3.15 Frontend (Feed, ProblemCard, SortFilterBar) | Card layout with upstar count, status badge, tags, counts |
| REQ-508 | 3.15 Frontend (StatusBadge) | Color-coded badges consistent across all views |
| REQ-510 | 3.15 Frontend (ProblemDetail) | Header + markdown description + tabbed solutions/comments |
| REQ-512 | 3.15 Frontend (App.tsx) | React Router 6 with lazy-loaded routes |
| REQ-514 | 3.15 Frontend (useDarkMode, ThemeProvider) | Three-way mode: light/dark/system; localStorage persistence |
| REQ-516 | 3.15 Frontend (EmptyState) | Generic empty-list component with message and CTA |
| REQ-518 | 3.15 Frontend (Toast, Feed, ProblemDetail) | Toast system, 404 page, inline validation errors |
| REQ-520 | 3.15 Frontend (MainLayout) | `useMediaQuery("(min-width: 1024px)")` for responsive layout |
| REQ-522 | 3.15 Frontend (Submit) | Minimal form with MarkdownEditor, TagAutocomplete, anonymous toggle |
| REQ-524 | 3.15 Frontend (AISearch) | Placeholder page with disabled inputs and "Coming Soon" |
| REQ-526 | 3.15 Frontend (Leaderboard) | Track/period filter tabs; gold/silver/bronze rank styling |
| REQ-528 | 3.15 Frontend (Toast) | Toast queue with 3 max visible, 5-second auto-dismiss |
| REQ-900 | 3.14 Infrastructure | Performance target; async-first architecture |
| REQ-902 | 3.9 Search | p95 < 1000ms target; GIN index on `problems.search_vector` |
| REQ-904 | 3.14 Infrastructure | 100-500 user capacity; single-server deployment |
| REQ-906 | 3.14 Infrastructure (NGINX) | TLS 1.2+ termination (config commented-in for production) |
| REQ-908 | 3.12 Middleware (security.py), 3.14 Infrastructure (NGINX) | Belt-and-suspenders security headers at both layers |
| REQ-910 | 3.14 Infrastructure (NGINX) | Three rate limit zones: api (30), auth (5), magic (1) |
| REQ-912 | 3.12 Middleware (logging.py) | `JSONFormatter` + `LoggingMiddleware` + correlation IDs |
| REQ-914 | 3.14 Infrastructure (backup/restore scripts) | `pg_dump` with 7-daily/4-weekly retention |
| REQ-916 | 3.1 Foundation (config.py) | `pydantic_settings.BaseSettings` from `.env` |
| REQ-918 | 3.12 Middleware (security.py) | CSP, X-Content-Type-Options, X-Frame-Options, sanitization |
| REQ-920 | 3.14 Infrastructure (Alembic) | Async engine bridge; `NullPool` for migrations |
| REQ-922 | 3.14 Infrastructure (generate-systemd.sh) | `podman generate systemd` with `Restart=always` |
| REQ-924 | 3.12 Middleware (security.py), 3.6 Comments | Two-pass HTML sanitization; extension-based MIME check on attachments |
| REQ-926 | Not implemented | No test suite exists |
| REQ-928 | 3.14 Infrastructure (health check) | `/healthz` with database + storage probes |
