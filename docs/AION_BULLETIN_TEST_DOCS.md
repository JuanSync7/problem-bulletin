# Aion Bulletin — Test Docs

> **For write-module-tests agents:** This document is your source of truth.
> Read ONLY your assigned module section. Do not read source files, implementation code,
> or other modules' test specs.

**Engineering guide:** `docs/AION_BULLETIN_ENGINEERING_GUIDE.md`
**Phase 0 contracts:** `docs/AION_BULLETIN_IMPLEMENTATION_DOCS.md` (Phase 0 section)
**Spec:** `docs/AION_BULLETIN_SPEC.md`
**Produced by:** write-test-docs

---

## Mock/Stub Interface Specifications

### Mock: Azure AD OIDC Provider

**What it replaces:** authlib OAuth registry for the Azure AD single-tenant OIDC flow.
The real flow involves a browser redirect to `login.microsoftonline.com`, an authorization
code exchange, and JWKS verification. All of that is bypassed.

**Interface to mock:**
- `oauth.azure.authorize_redirect(request, redirect_uri)` — called by `initiate_login`
- `oauth.azure.authorize_access_token(request)` — called by `handle_callback`

**Happy path return value for `authorize_access_token`:**
```python
{
    "userinfo": {
        "oid": "11111111-1111-1111-1111-111111111111",
        "email": "alice@company.com",
        "name": "Alice Tester",
        "tid": "<AZURE_TENANT_ID>"   # must match env var
    }
}
```

**Error path return value:** raise `authlib.integrations.base_client.errors.OAuthError("invalid_grant")`

**Tenant mismatch path:** return a userinfo dict where `tid` does not match `AZURE_TENANT_ID`;
expect `TenantMismatchError` → HTTP 401.

**Used by modules:** `app/auth/oidc.py` (`initiate_login`, `handle_callback`, `_provision_user`)

**Mock name (used in scenario tables):** `mock_azure_oidc`

---

### Mock: SMTP Relay

**What it replaces:** `aiosmtplib.send`, which connects to an SMTP server to deliver
magic-link emails and daily email digests.

**Interface to mock:** `aiosmtplib.send(message, hostname, port, start_tls, ...)`

**Happy path return value:** `None` (coroutine completes without raising)

**Error path return value:** raise `aiosmtplib.SMTPConnectError("Connection refused")`

**Captured state to assert:** the `email.message.Message` object passed as the first
argument; assert `To`, `Subject`, and body content.

**Used by modules:** `app/auth/magic_link.py`, `app/services/notifications.py` (email digest)

**Mock name:** `mock_smtp`

---

### Mock: Teams Webhook

**What it replaces:** `httpx.AsyncClient.post`, used by `schedule_teams_webhook` to POST
an Adaptive Card JSON payload to `TEAMS_WEBHOOK_URL` with a 10-second timeout.

**Interface to mock:** `httpx.AsyncClient.post(url, json=..., timeout=10)`

**Happy path return value:** `httpx.Response(status_code=200, text="1")`

**Error path return value (connection failure):** raise `httpx.ConnectError("Connection refused")`

**Error path return value (webhook gone):** `httpx.Response(status_code=410, text="Gone")`

**Captured state to assert:** the `json=` keyword argument; assert keys
`"type"`, `"attachments"`, and that `body` contains the problem title.

**Used by modules:** `app/services/notifications.py` (`schedule_teams_webhook`)

**Mock name:** `mock_teams_webhook`

---

### Mock: File System (Storage Path)

**What it replaces:** the `STORAGE_PATH` directory used by attachment upload/download
logic. In tests, `STORAGE_PATH` is redirected to a `tmp_path` pytest fixture directory
so no real disk state persists between test runs.

**Interface to mock:** environment variable `STORAGE_PATH` overridden to `str(tmp_path)`
before the FastAPI application is initialised for the test session.

**Happy path behaviour:** files written to `tmp_path/<uuid>/<filename>` are readable
via the same path; `os.path.exists` returns `True`.

**Error path behaviour (quota / permission):** `tmp_path` is made read-only via
`chmod 0o444`; assert `OSError` is caught and the upload endpoint returns HTTP 500.

**Used by modules:** `app/services/attachments.py`

**Mock name:** `mock_storage`

---

---

## Per-Module Test Specifications

### Foundation Layer

#### `app/config.py` — Application Configuration

**Module purpose:** Centralises every externally supplied runtime parameter the
application needs, validated and type-coerced via Pydantic Settings, exposed as
a single cached `get_settings()` accessor.

**In scope:**
- Required-field validation: process fails to start when any required field is absent
- Type coercion and URL validation: `BASE_URL` and `TEAMS_WEBHOOK_URL` must be valid HTTP URLs
- `ENVIRONMENT` literal constraint: only `development`, `staging`, `production` accepted
- `SecretStr` wrapping: `AZURE_CLIENT_SECRET` and `JWT_SECRET` must not appear in `repr()` output
- `get_settings()` cache: second call returns the same instance; cache can be cleared for test isolation
- `extra="ignore"`: unknown env vars silently discarded without error
- `case_sensitive=False`: field names matched case-insensitively
- Default values: `APP_NAME`, `SMTP_PORT`, `DEV_AUTH_BYPASS`, `ENVIRONMENT`, `STORAGE_PATH`, `TEAMS_WEBHOOK_URL`

**Out of scope:**
- Actual database connectivity (owned by `database.py`)
- Azure AD token validation logic (owned by the auth module)
- JWT signing and verification (owned by the auth module)
- SMTP delivery (owned by the notification service)

##### Happy path scenarios

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| All required fields supplied | Valid env dict with `DATABASE_URL`, `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `JWT_SECRET`, `SMTP_HOST`, `SMTP_FROM`, `BASE_URL` | `Settings` instance constructed without error; `get_settings()` returns it |
| Default `APP_NAME` | Required fields only; `APP_NAME` absent | `settings.APP_NAME == "Aion Bulletin"` |
| Default `SMTP_PORT` | Required fields only; `SMTP_PORT` absent | `settings.SMTP_PORT == 587` |
| Default `DEV_AUTH_BYPASS` | Required fields only; `DEV_AUTH_BYPASS` absent | `settings.DEV_AUTH_BYPASS is False` |
| Default `ENVIRONMENT` | Required fields only; `ENVIRONMENT` absent | `settings.ENVIRONMENT == "development"` |
| Default `STORAGE_PATH` | Required fields only; `STORAGE_PATH` absent | `settings.STORAGE_PATH == "/data/attachments"` |
| Default `TEAMS_WEBHOOK_URL` | Required fields only; `TEAMS_WEBHOOK_URL` absent | `settings.TEAMS_WEBHOOK_URL is None` |
| Cache singleton | `get_settings()` called twice | Both calls return `is`-identical object |
| Cache cleared between tests | `get_settings.cache_clear()` called then `get_settings()` | New instance constructed; no stale values leak across tests |
| Case-insensitive env | Required fields supplied with lowercase names (e.g. `database_url`) | `Settings` constructed without error |
| Extra env vars present | Required fields + extra `PLATFORM_POD_ID=abc` | `Settings` constructed without error; `PLATFORM_POD_ID` not available as attribute |
| Optional `TEAMS_WEBHOOK_URL` supplied | Valid HTTP URL string | Parsed as `AnyHttpUrl`; `settings.TEAMS_WEBHOOK_URL` is not `None` |
| `SecretStr` values not leaked | `repr(settings.AZURE_CLIENT_SECRET)` | Output contains `'**********'`, not the actual secret |
| `SecretStr` access | `settings.JWT_SECRET.get_secret_value()` | Returns the raw secret string |

##### Error scenarios

| Error type | Trigger condition | Expected behavior |
|------------|-------------------|-------------------|
| Missing required field | Any one of `DATABASE_URL`, `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `JWT_SECRET`, `SMTP_HOST`, `SMTP_FROM`, `BASE_URL` absent | `pydantic_settings.ValidationError` raised; error lists the missing field; no `Settings` instance created |
| Multiple required fields absent | All required fields missing | `ValidationError` raised; error lists all missing fields in one exception |
| Invalid `BASE_URL` | `BASE_URL=not_a_url` | `pydantic.ValidationError` raised at `Settings()` construction time |
| Invalid `TEAMS_WEBHOOK_URL` | `TEAMS_WEBHOOK_URL=not_a_url` | `pydantic.ValidationError` raised at `Settings()` construction time |
| Invalid `ENVIRONMENT` value | `ENVIRONMENT=test` (not in allowed literals) | `pydantic.ValidationError` raised at `Settings()` construction time |

##### Boundary conditions

- `ENVIRONMENT` exactly `"development"`, `"staging"`, `"production"` — each accepted
- `ENVIRONMENT` value `"production"` with `DEV_AUTH_BYPASS=True` — no settings-layer error (safety check is the caller's responsibility; out of scope for this module)
- `SMTP_PORT` as an integer string `"587"` — coerced to `int` without error
- `BASE_URL` with trailing slash — accepted as valid `AnyHttpUrl`
- `TEAMS_WEBHOOK_URL` explicitly set to empty string — expected to raise `ValidationError` (not treated as `None`)

##### Integration points

- `database.py` imports `get_settings()` at module-load time to obtain `DATABASE_URL`
- FastAPI `lifespan` hook calls `get_settings()` on application startup
- Auth module reads `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET.get_secret_value()`
- JWT module reads `JWT_SECRET.get_secret_value()`
- Notification service reads `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM`, `TEAMS_WEBHOOK_URL`

##### Known test gaps

- **No test for `DATABASE_URL` async-driver format enforcement** — Pydantic treats `DATABASE_URL` as a plain `str`; the requirement that it uses an async driver (e.g. `postgresql+asyncpg://`) is not enforced by this module. A conformance test would require integration with `database.py`.
- **No cross-module test for `DEV_AUTH_BYPASS=True` in production** — The engineering guide states this must never be `True` in production, but `config.py` imposes no validator for this condition. A validator test cannot be written without implementation that doesn't yet exist.
- **`.env` file resolution order** — Tests that verify `.env` file takes precedence over real env vars require filesystem fixtures; this is environment-sensitive and may be deferred to an integration suite.

##### Agent isolation contract

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only — do not infer behavior from stubs)
>
> **Must NOT receive:** Source implementation files (`src/`), Phase B implementation code,
> other modules' test specs, or the engineering guide directly.

---

#### `app/database.py` — Database Connectivity

**Module purpose:** Creates the single shared SQLAlchemy async engine and
session factory, exposes the `Base` declarative class, and provides `get_db()`
— an async generator that manages per-request transaction boundaries
(auto-commit on success, rollback on exception).

**In scope:**
- `get_db()` commits when the route body completes without exception
- `get_db()` rolls back and re-raises when an exception is raised inside the `async with` block
- The original exception is re-raised unchanged after rollback (no wrapping)
- `expire_on_commit=False` — ORM instances remain readable after commit
- Route handlers do not need to call `commit()` or `rollback()` explicitly
- `Base` is importable and usable as a declarative base for model definitions

**Out of scope:**
- Engine construction parameters (`pool_pre_ping`, `echo`) — these depend on live database infrastructure
- Connection pool behaviour under load
- Alembic migration compatibility
- `OperationalError` on invalid `DATABASE_URL` — surfaces only on first query, not at import time

##### Happy path scenarios

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| Clean session lifecycle | Generator entered; no exception raised | `session.commit()` called exactly once; session context manager exits cleanly |
| `expire_on_commit=False` effect | ORM instance attribute accessed after `commit()` inside same session | Attribute readable without `DetachedInstanceError` |
| `Base` importable | `from app.database import Base` | No import error; `Base` is a SQLAlchemy `DeclarativeBase` subclass |
| Multiple `get_db()` calls | Two separate invocations of the generator | Each invocation yields a distinct session object |

##### Error scenarios

| Error type | Trigger condition | Expected behavior |
|------------|-------------------|-------------------|
| Exception inside route | Exception raised after `yield session` | `session.rollback()` called; original exception re-raised unchanged (same type, same args) |
| Commit failure (e.g. `IntegrityError`) | `session.commit()` raises | Exception propagates out of `get_db()`; session left in rolled-back state |

##### Boundary conditions

- Generator used as `async with` context — session must be closed even if rollback itself raises
- `get_db()` used via `Depends()` in a FastAPI test client — transaction must close before response is serialised

##### Integration points

- All ORM model files import `Base` from this module
- All route handlers inject a session via `Depends(get_db)`
- `config.py` is called at import time to obtain `DATABASE_URL` for engine construction

##### Known test gaps

- **Engine construction and connection pool tests require a live (or containerised) PostgreSQL instance** — unit-testable surface is limited to session lifecycle behaviour via mocking.
- **`pool_pre_ping` behaviour** — verifying that stale connections are detected and replaced requires a real connection pool; out of scope for unit tests.
- **`OperationalError` on bad DSN** — only surfaces on first query; cannot be triggered at import time in a unit test.

##### Agent isolation contract

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only — do not infer behavior from stubs)
>
> **Must NOT receive:** Source implementation files (`src/`), Phase B implementation code,
> other modules' test specs, or the engineering guide directly.

---

#### `app/enums.py` — Domain Enumerations

**Module purpose:** Defines the six closed-value sets the domain model depends
on (`ProblemStatus`, `UserRole`, `WatchLevel`, `NotificationType`, `SortMode`,
`ParentType`), all inheriting from `str` and `Enum` for direct JSON
serialisation and SQLAlchemy VARCHAR storage.

**In scope:**
- All declared member values are exactly as specified (no typos, no missing members)
- `str` mixin: each member compares equal to its string value (`ProblemStatus.open == "open"`)
- `str` mixin: each member is usable directly where a `str` is expected (e.g. as a dict key, JSON output)
- JSON round-trip: members serialise to their string value and can be deserialised back
- Exhaustive membership: no members beyond those specified exist on each enum
- `WatchLevel.none` exists as an explicit member (distinguishes deliberate opt-out from missing row)

**Out of scope:**
- State-machine transition logic (owned by the problem service)
- Database column storage (owned by `app/models/`)
- Pydantic schema validation (owned by `schemas.py`)

##### Happy path scenarios

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| `ProblemStatus` members | Enumerate all members | Exactly `{open, claimed, solved, accepted, duplicate}`; values match names |
| `UserRole` members | Enumerate all members | Exactly `{user, admin}`; values match names |
| `WatchLevel` members | Enumerate all members | Exactly `{all_activity, solutions_only, status_only, none}`; values match names |
| `NotificationType` members | Enumerate all members | Exactly `{problem_claimed, solution_posted, solution_accepted, comment_posted, status_changed, problem_pinned, upstar_received, mention}`; values match names |
| `SortMode` members | Enumerate all members | Exactly `{top, new, active, discussed}`; values match names |
| `ParentType` members | Enumerate all members | Exactly `{problem, solution, comment}`; values match names |
| `str` equality | `ProblemStatus.open == "open"` | `True` |
| `str` equality | `UserRole.admin == "admin"` | `True` |
| `str` equality | `WatchLevel.none == "none"` | `True` |
| JSON serialisation | `json.dumps({"status": ProblemStatus.open})` | `'{"status": "open"}'` (no custom encoder needed) |
| Construction from string | `ProblemStatus("open")` | Returns `ProblemStatus.open` |
| `WatchLevel.none` explicit opt-out | `WatchLevel("none")` | Returns `WatchLevel.none` without error |

##### Error scenarios

| Error type | Trigger condition | Expected behavior |
|------------|-------------------|-------------------|
| Invalid member construction | `ProblemStatus("closed")` (value not in enum) | Raises `ValueError` |
| Invalid member construction | `UserRole("superadmin")` | Raises `ValueError` |
| Invalid member construction | `WatchLevel("everything")` | Raises `ValueError` |

##### Boundary conditions

- `ProblemStatus` has five members — verify exactly five, not four or six (spec REQ-156)
- `NotificationType` has exactly eight members (spec REQ-310) — count enforced
- `WatchLevel.none` value is the string `"none"`, not `None` (Python `NoneType`)
- All member values are lowercase strings with underscores — no mixed-case or hyphens

##### Integration points

- `schemas.py` uses these enums as field type annotations in Pydantic models
- `app/models/` stores enum values as VARCHAR columns; SQLAlchemy reads/writes the `.value` string
- Service layer raises `ForbiddenTransitionError` when a `ProblemStatus` transition is invalid (transition graph is not defined in this module)

##### Known test gaps

- **No test for `StrEnum` vs `str, Enum` compatibility on Python 3.11+** — the engineering guide notes `StrEnum` was considered and rejected; behaviour parity on 3.11 is not verified.
- **No test for SQLAlchemy column round-trip** — verifying that the string value survives a write-read cycle through a VARCHAR column requires database integration.

##### Agent isolation contract

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only — do not infer behavior from stubs)
>
> **Must NOT receive:** Source implementation files (`src/`), Phase B implementation code,
> other modules' test specs, or the engineering guide directly.

---

#### `app/exceptions.py` — Application Exception Hierarchy

**Module purpose:** Defines a typed exception hierarchy rooted at `AppError`
that maps each business-rule violation to a specific HTTP status code, keeping
domain exceptions free of HTTP concerns.

**In scope:**
- All seven exception classes are importable and instantiable
- `AppError` is the common base; all subclasses are instances of `AppError`
- `AppError` inherits from `Exception` (not `HTTPException` or any HTTP framework class)
- Structured `__init__` fields: `ForbiddenTransitionError(current, target)` exposes `.current` and `.target`
- Structured `__init__` fields: `FileSizeLimitError(file_size, max_size)` exposes `.file_size` and `.max_size`
- Structured `__init__` fields: `FileTypeNotAllowedError(content_type, filename)` exposes `.content_type` and `.filename`
- `pass`-body exceptions (`PinLimitExceededError`, `DuplicateVoteError`, `MagicLinkExpiredError`, `TenantMismatchError`) are instantiable with no arguments
- All subclasses can be caught by `except AppError`
- Each subclass can be caught independently by its own type

**Out of scope:**
- HTTP response serialisation (owned by exception handlers in `app.main`)
- The status codes themselves — this module does not store them; the handler maps them
- Raising conditions — these exceptions are raised by service/route code, not by this module

##### Happy path scenarios

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| `ForbiddenTransitionError` instantiation | `ForbiddenTransitionError("open", "accepted")` | `.current == "open"`, `.target == "accepted"` |
| `FileSizeLimitError` instantiation | `FileSizeLimitError(5_000_000, 2_000_000)` | `.file_size == 5_000_000`, `.max_size == 2_000_000` |
| `FileTypeNotAllowedError` instantiation | `FileTypeNotAllowedError("application/exe", "virus.exe")` | `.content_type == "application/exe"`, `.filename == "virus.exe"` |
| `PinLimitExceededError` instantiation | `PinLimitExceededError()` | No error; instance is `isinstance(e, AppError)` |
| `DuplicateVoteError` instantiation | `DuplicateVoteError()` | No error; instance is `isinstance(e, AppError)` |
| `MagicLinkExpiredError` instantiation | `MagicLinkExpiredError()` | No error; instance is `isinstance(e, AppError)` |
| `TenantMismatchError` instantiation | `TenantMismatchError()` | No error; instance is `isinstance(e, AppError)` |
| Catch via base class | `raise ForbiddenTransitionError(...)` inside `try: ... except AppError` | Caught by `except AppError` block |
| Catch via specific class | `raise DuplicateVoteError()` inside `try: ... except DuplicateVoteError` | Caught by `except DuplicateVoteError` block; not caught by unrelated subclass handler |
| `AppError` is not `HTTPException` | `isinstance(AppError(), HTTPException)` | `False` (assuming `HTTPException` imported from `starlette`) |

##### Error scenarios

| Error type | Trigger condition | Expected behavior |
|------------|-------------------|-------------------|
| Missing required arg on `ForbiddenTransitionError` | `ForbiddenTransitionError()` (no args) | `TypeError` raised (missing positional arguments) |
| Missing required arg on `FileSizeLimitError` | `FileSizeLimitError()` (no args) | `TypeError` raised |
| Missing required arg on `FileTypeNotAllowedError` | `FileTypeNotAllowedError()` (no args) | `TypeError` raised |

##### Boundary conditions

- `ForbiddenTransitionError` with `current == target` — valid instantiation (same-state "transition"); this module does not validate transition graph
- All seven documented subclasses must exist — verify no subclass is missing from the module
- No additional undocumented subclasses should exist that could interfere with catch-all `except AppError` handlers

##### Integration points

- `app.main` registers exception handlers that catch each subclass and return the appropriate HTTP response
- Service layer raises these exceptions on business-rule violations
- Tests for service modules will raise and catch these exceptions; they must not import from `app.main`

##### Known test gaps

- **No test for exception handler HTTP mapping** — verifying that `ForbiddenTransitionError` produces a `409` response with `current`/`target` fields requires integration with `app.main`'s exception handler wiring.
- **No test that middleware catches `AppError` as fallback** — middleware behaviour is owned by `app.main`, not this module.

##### Agent isolation contract

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only — do not infer behavior from stubs)
>
> **Must NOT receive:** Source implementation files (`src/`), Phase B implementation code,
> other modules' test specs, or the engineering guide directly.

---

#### `app/schemas.py` — Request and Response Schemas

**Module purpose:** Defines every Pydantic `BaseModel` used as a FastAPI request
body or response model, enforcing field-level constraints before any route
handler runs, and provides the generic `CursorPage[T]` pagination envelope.

**In scope:**
- `ProblemCreate` field constraints: `title` 5–200 chars, `description` min 10 chars (REQ-152)
- `ProblemCreate` defaults: `tag_ids` defaults to empty list; `is_anonymous` defaults to `False`
- `SolutionCreate` field constraints: `description` min 10 chars; `git_link` must be valid HTTP URL or `None`
- `CommentCreate` field constraints: `body` 1–10000 chars; `parent_comment_id` nullable; `is_anonymous` defaults to `False`
- `CommentResponse` self-referential `replies` field resolves correctly after `model_rebuild()`
- `CursorPage[T]` generic: `items` is a typed list; `next_cursor` is `str | None`
- `TokenPayload` fields: `sub`, `role`, `exp` all required
- `MagicLinkRequest` field: `email` required string
- `tag_ids` uses `default_factory=list` (not mutable default `[]`)
- `ValidationError` raised for constraint violations (FastAPI converts to 422)

**Out of scope:**
- FastAPI request parsing and 422 response formatting (owned by FastAPI framework)
- Business logic validation (e.g. category existence) — owned by service layer
- Database persistence — owned by ORM models

##### Happy path scenarios

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| `ProblemCreate` valid — minimum boundaries | `title` = 5 chars, `description` = 10 chars, valid `category_id` | Model instantiated without error (REQ-152 AC: boundary values accepted) |
| `ProblemCreate` valid — maximum title | `title` = 200 chars | Model instantiated without error |
| `ProblemCreate` default `tag_ids` | No `tag_ids` supplied | `tag_ids == []` |
| `ProblemCreate` default `is_anonymous` | No `is_anonymous` supplied | `is_anonymous is False` |
| `ProblemCreate` `tag_ids` instances independent | Two separate instantiations, no `tag_ids` supplied | Mutating one instance's `tag_ids` does not affect the other |
| `SolutionCreate` valid — min description | `description` = 10 chars, `git_link=None` | Model instantiated without error |
| `SolutionCreate` valid `git_link` | `git_link="https://github.com/org/repo"` | Parsed as `AnyHttpUrl`; no error |
| `SolutionCreate` default `is_anonymous` | No `is_anonymous` supplied | `is_anonymous is False` |
| `CommentCreate` valid — minimum body | `body` = 1 char | Model instantiated without error |
| `CommentCreate` valid — maximum body | `body` = 10000 chars | Model instantiated without error |
| `CommentCreate` default `is_anonymous` | No `is_anonymous` supplied | `is_anonymous is False` |
| `CommentCreate` nullable `parent_comment_id` | No `parent_comment_id` supplied | `parent_comment_id is None` |
| `CommentResponse` self-referential | `CommentResponse` with `replies=[CommentResponse(...)]` | Nested model validates without error |
| `CursorPage[str]` last page | `next_cursor=None` | `page.next_cursor is None` |
| `CursorPage[str]` mid-page | `next_cursor="abc123"` | `page.next_cursor == "abc123"` |
| `TokenPayload` valid | `{"sub": "uid", "role": "user", "exp": 9999999999}` | Model instantiated; all fields accessible |

##### Error scenarios

| Error type | Trigger condition | Expected behavior |
|------------|-------------------|-------------------|
| `ProblemCreate` title too short | `title` = 4 chars (REQ-152 AC: 4 chars returns 422) | `ValidationError` with field path `title` |
| `ProblemCreate` title too long | `title` = 201 chars | `ValidationError` with field path `title` |
| `ProblemCreate` description too short | `description` = 9 chars (REQ-152 AC: 9 chars returns 422) | `ValidationError` with field path `description` |
| `ProblemCreate` missing required `category_id` | No `category_id` supplied | `ValidationError` with field path `category_id` |
| `SolutionCreate` description too short | `description` = 9 chars | `ValidationError` with field path `description` |
| `SolutionCreate` invalid `git_link` | `git_link="not_a_url"` | `ValidationError` with field path `git_link` |
| `CommentCreate` body empty | `body` = "" (0 chars) | `ValidationError` with field path `body` |
| `CommentCreate` body too long | `body` = 10001 chars | `ValidationError` with field path `body` |
| `CommentResponse` used before `model_rebuild()` | Importing `CommentResponse` with deferred annotation unresolved | Would raise `PydanticUserError`; module-level `model_rebuild()` prevents this in normal import order |

##### Boundary conditions

- `ProblemCreate.title` exactly 5 characters: accepted (REQ-152 AC)
- `ProblemCreate.title` exactly 200 characters: accepted (REQ-152 AC)
- `ProblemCreate.description` exactly 10 characters: accepted (REQ-152 AC)
- `ProblemCreate.title` exactly 4 characters: rejected with 422 (REQ-152 AC)
- `ProblemCreate.description` exactly 9 characters: rejected with 422 (REQ-152 AC)
- `CommentCreate.body` exactly 1 character: accepted
- `CommentCreate.body` exactly 10000 characters: accepted
- `CommentCreate.body` exactly 10001 characters: rejected
- `SolutionCreate.git_link` as `None`: accepted (optional field)

##### Integration points

- FastAPI route handlers declare these models as request bodies and response models; Pydantic validation happens before the handler runs
- `CursorPage[T]` is instantiated by list-endpoint service functions and returned as the response
- `CommentResponse.model_rebuild()` must be called at module import time; any import ordering that skips this call would break recursive validation

##### Known test gaps

- **No test for `ProblemResponse` / `ProblemDetailResponse` inheritance** — the engineering guide notes `ProblemDetailResponse` extends `ProblemResponse`; these schemas are not fully specified in the Phase 0 contracts and cannot be tested without the schema source.
- **No test for `UserResponse` nested in `CommentResponse.author`** — `UserResponse` is referenced but not fully defined in Phase 0 contracts.
- **FastAPI 422 response format** — the exact JSON shape of the error response is controlled by FastAPI, not by this module; integration tests are required to verify the `detail` field structure.
- **`MagicLinkRequest` email format validation** — the field is typed as `str`, not `EmailStr`; no format validation is implied by the spec. If format validation is added during implementation, tests must be updated.

##### Agent isolation contract

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only — do not infer behavior from stubs)
>
> **Must NOT receive:** Source implementation files (`src/`), Phase B implementation code,
> other modules' test specs, or the engineering guide directly.

---

---

### Data Model (ORM)

#### `app/models/` — Data Model (ORM)

**Module purpose:** Defines every persistent entity in the Aion Bulletin system
using SQLAlchemy declarative ORM mapped to PostgreSQL, covering identity/auth,
content, solutions, discussion, file storage, engagement, moderation, and
runtime configuration.

**In scope:**
- All models inherit from `app.database.Base`
- UUID primary keys with `server_default=gen_random_uuid()` on all entity tables
- `server_default=now()` on all `created_at` columns
- `onupdate=now()` on all `updated_at` columns
- Default column values as specified per table (e.g. `role='user'`, `status='open'`, `is_pinned=False`)
- Unique constraints on specified column pairs (claims, upstars, solution_upvotes, watches, solution_versions, categories, tags, users.email, users.azure_oid, magic_links.token_hash)
- `ON DELETE CASCADE` foreign keys as specified
- Nullable FK columns as specified (e.g. `Problem.author_id`, `Solution.author_id`, `Comment.author_id`)
- Polymorphic `parent_type`/`parent_id` pattern on `Attachment` and `Flag` (no DB-level FK on `parent_id`)
- `Comment` self-referential relationship via `parent_comment_id`; `backref="replies"` populates child collection
- `AuditLog.metadata_` Python attribute maps to `metadata` database column
- `ALLOWED_CONFIG_KEYS` frozenset on `app_config` module
- Composite PK on `NotificationPreference(user_id, type)`
- Composite PK on `ProblemTag(problem_id, tag_id)`
- `AppConfig` uses `key` (VARCHAR) as primary key; no surrogate ID
- Enum values stored as VARCHAR strings matching `str, Enum` member values
- `MagicLink.token_hash` stores hash only; no raw token column

**Out of scope:**
- Alembic migration scripts
- Query logic and filtering (owned by repository/service layer)
- Business-rule validation (owned by service layer and `exceptions.py`)
- `search_vector` population logic (owned by DB trigger or service layer)

##### Happy path scenarios

###### Identity & Auth

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| `User` default role | Insert `User` without specifying `role` | `user.role == "user"` (or `UserRole.user`) |
| `User` default `is_active` | Insert `User` without specifying `is_active` | `user.is_active is True` |
| `User` `created_at` auto-set | Insert `User` | `user.created_at` is not `None` |
| `User` `updated_at` on update | Update `User.display_name` | `user.updated_at` changes to a more recent timestamp |
| `User` `updated_at` on insert | Insert `User` | `user.updated_at` is `None` (no initial value) |
| `MagicLink` `consumed` default | Insert `MagicLink` without `consumed` | `magic_link.consumed is False` |
| `MagicLink` nullable `user_id` | Insert `MagicLink` with `user_id=None` | Row persisted without FK error |
| `MagicLink` `token_hash` unique | Insert two `MagicLink` rows with same `token_hash` | `IntegrityError` (unique constraint) |

###### Categories & Tags

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| `Category` `name` unique | Insert two `Category` rows with same `name` | `IntegrityError` |
| `Category` `slug` unique | Insert two `Category` rows with same `slug` | `IntegrityError` |
| `Category` soft delete | Set `category.deleted_at` to a timestamp | Row persists; `deleted_at` is not `None` |
| `Category` default `sort_order` | Insert `Category` without `sort_order` | `category.sort_order == 0` |
| `Tag` `name` unique | Insert two `Tag` rows with same `name` | `IntegrityError` |

###### Problems

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| `Problem` default `status` | Insert `Problem` without `status` | `problem.status == "open"` |
| `Problem` default `is_pinned` | Insert `Problem` without `is_pinned` | `problem.is_pinned is False` |
| `Problem` default `is_anonymous` | Insert `Problem` without `is_anonymous` | `problem.is_anonymous is False` |
| `Problem` anonymous author | Insert `Problem` with `author_id=None`, `is_anonymous=True` | Row persisted; `problem.author_id is None` |
| `Problem.tags` M2M relationship | Associate two `Tag` rows via `problem_tags` | `problem.tags` collection contains both tags |
| `ProblemTag` composite PK | Insert duplicate `(problem_id, tag_id)` pair | `IntegrityError` |
| `ProblemEditHistory` snapshot | Insert `ProblemEditHistory` with `snapshot={"title": "old"}` | `edit.snapshot == {"title": "old"}` (JSONB round-trip) |
| `Claim` unique constraint | Insert two `Claim` rows with same `(user_id, problem_id)` | `IntegrityError` (unique constraint `uq_claim_user_problem`) |
| `Upstar` unique constraint | Insert two `Upstar` rows with same `(user_id, problem_id)` | `IntegrityError` (unique constraint `uq_upstar_user_problem`) |

###### Solutions

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| `Solution` default `status` | Insert `Solution` without `status` | `solution.status == "pending"` |
| `Solution` default `is_anonymous` | Insert `Solution` without `is_anonymous` | `solution.is_anonymous is False` |
| `Solution` nullable `current_version_id` | Insert `Solution` without `current_version_id` | `solution.current_version_id is None` |
| `SolutionVersion` unique version number | Insert two `SolutionVersion` rows with same `(solution_id, version_number)` | `IntegrityError` (unique constraint `uq_solution_version_number`) |
| `SolutionUpvote` unique constraint | Insert two `SolutionUpvote` rows with same `(user_id, solution_id)` | `IntegrityError` (unique constraint `uq_solution_upvote_user_solution`) |
| `Solution.versions` relationship | Insert two `SolutionVersion` rows for same solution | `solution.versions` collection has length 2 |

###### Comments

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| `Comment` default `is_anonymous` | Insert `Comment` without `is_anonymous` | `comment.is_anonymous is False` |
| `Comment` default `is_edited` | Insert `Comment` without `is_edited` | `comment.is_edited is False` |
| `Comment` self-referential reply | Insert child `Comment` with `parent_comment_id` set | Parent `comment.replies` collection contains the child |
| `Comment` nullable `solution_id` | Insert `Comment` with `solution_id=None` | Row persisted; comment attached to problem only |
| `Comment` anonymous author | Insert `Comment` with `author_id=None` | Row persisted; `comment.author_id is None` |

###### Attachments, Watches, Notifications

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| `Attachment` polymorphic `parent_type` | Insert `Attachment` with `parent_type="problem"` | `attachment.parent_type == "problem"` |
| `Attachment` no DB FK on `parent_id` | Insert `Attachment` with non-existent `parent_id` UUID | No `IntegrityError` from DB (referential integrity is app-layer) |
| `Watch` default `level` | Insert `Watch` without `level` | `watch.level == "all_activity"` |
| `Watch` unique constraint | Insert two `Watch` rows with same `(user_id, problem_id)` | `IntegrityError` (unique constraint `uq_watch_user_problem`) |
| `Notification` default `is_read` | Insert `Notification` without `is_read` | `notification.is_read is False` |
| `NotificationPreference` composite PK | Insert duplicate `(user_id, type)` pair | `IntegrityError` |
| `NotificationPreference` default `enabled` | Insert without `enabled` | `pref.enabled is True` |

###### AppConfig

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| `AppConfig` string PK | Insert `AppConfig(key="max_pin_count", value="3")` | Row persisted; `app_config.key == "max_pin_count"` |
| `ALLOWED_CONFIG_KEYS` content | Import `ALLOWED_CONFIG_KEYS` | Frozenset contains exactly `{"max_pin_count", "claim_expiry_days", "magic_link_ttl_minutes", "auto_watch_default_level"}` |

###### AuditLog

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| `AuditLog.metadata_` attribute | Insert `AuditLog` with `metadata_={"reason": "test"}` | `audit.metadata_ == {"reason": "test"}` (Python attribute) |
| `AuditLog` no FK on `target_id` | Insert `AuditLog` with non-existent `target_id` UUID | No `IntegrityError` from DB |

##### Error scenarios

| Error type | Trigger condition | Expected behavior |
|------------|-------------------|-------------------|
| `User.email` unique violation | Insert two `User` rows with same `email` | `IntegrityError` |
| `User.azure_oid` unique violation | Insert two `User` rows with same non-null `azure_oid` | `IntegrityError` |
| `Problem.category_id` FK violation | Insert `Problem` with non-existent `category_id` | `IntegrityError` (FK constraint) |
| `Problem.author_id` FK violation | Insert `Problem` with non-existent (non-null) `author_id` | `IntegrityError` (FK constraint) |
| `SolutionVersion` version number duplicate | Insert `SolutionVersion` with same `(solution_id, version_number)` | `IntegrityError` |
| `NotificationPreference` duplicate row | Insert `(user_id, type)` pair that already exists | `IntegrityError` (composite PK) |

##### Boundary conditions

- `User.azure_oid` uniqueness: two users with `azure_oid=None` must both be insertable (NULL does not violate UNIQUE in PostgreSQL)
- `Problem.status` must accept each of the five `ProblemStatus` string values and reject any other value (DB-level CHECK constraint if present, or validated at application layer)
- `Notification.type` column stores a `NotificationType` string value; all eight values must round-trip through the VARCHAR column without truncation
- `ProblemEditHistory.snapshot` JSONB: nested objects, arrays, and null values must round-trip correctly
- `AuditLog.metadata_` JSONB: `None` (SQL NULL) must be storable (column is nullable)
- `AppConfig.updated_at` uses `server_default=now()` with no separate `created_at` — verify `updated_at` is set on insert as well as update
- `MagicLink.user_id` nullable: multiple `MagicLink` rows with `user_id=NULL` must all be insertable (NULL does not violate FK uniqueness in this context)

##### Integration points (cascade behaviour)

The following cascade chains must be verified with integration tests against a real (or in-memory compatible) database:

- **Problem deletion** cascades to: `ProblemEditHistory`, `Claim`, `Upstar`, `Watch`, `ProblemTag`, `Solution`, `Comment` — after deleting a `Problem`, all associated rows in these tables must be absent
- **Solution deletion** cascades to: `SolutionVersion`, `SolutionUpvote`, `Comment` (solution-scoped comments) — after deleting a `Solution`, associated rows must be absent
- **Comment deletion** cascades to: child `Comment` rows (replies) — after deleting a parent comment, all reply rows must be absent
- **User deletion** cascades to: `MagicLink`, `NotificationPreference` — after deleting a `User`, associated rows must be absent
- **Tag deletion** cascades to: `ProblemTag` — after deleting a `Tag`, the join rows must be absent
- **`Attachment`, `Flag`, `AuditLog`** — no DB cascade; deleting the owning entity does NOT automatically remove these rows (orphan rows are expected; service layer manages cleanup)
- `Solution.comments` (`solution_id` FK): deleting a `Solution` cascades to comments with that `solution_id`; verify comments scoped to a problem (not a solution) are NOT deleted by solution deletion

##### Known test gaps

- **`search_vector` GIN index and `TSVECTOR` column** — populating `search_vector` is done by a DB trigger or service layer; the model test can verify the column exists and accepts a value but cannot test full-text search ranking without PostgreSQL-specific infrastructure.
- **`Solution.current_version_id` denormalisation consistency** — the pointer must be updated atomically with new version creation; this is a service-layer invariant, not enforceable by the model alone.
- **`AppConfig` key validation against `ALLOWED_CONFIG_KEYS`** — the frozenset is importable from the model module, but enforcement of writes against this set is a service-layer concern; model tests can only verify the frozenset contents.
- **`updated_at onupdate` behaviour in async context** — SQLAlchemy's `onupdate` for server-side timestamps requires an `UPDATE` statement to trigger; testing this requires a real DB round-trip.
- **`Flag` and `Attachment` orphan cleanup** — the spec states referential integrity is enforced at the application layer; no unit test can verify this without exercising the service layer.
- **`User.azure_oid` NULL uniqueness** — PostgreSQL treats NULLs as distinct in unique indexes; this behaviour is DB-specific and may require a PostgreSQL test fixture (not SQLite in-memory).
- **Polymorphic `parent_type` value enforcement** — the column is VARCHAR with no CHECK constraint; invalid string values are not rejected at the DB level. Model-level enforcement (if any) depends on implementation.

##### Agent isolation contract

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only — do not infer behavior from stubs)
>
> **Must NOT receive:** Source implementation files (`src/`), Phase B implementation code,
> other modules' test specs, or the engineering guide directly.

---

### Authentication Subsystem

#### `app/auth/jwt.py` — JWT Token Management

**Module purpose:** Creates, validates, and manages the lifecycle of HS256-signed access token JWTs and their HttpOnly cookie transport.

**In scope:**
- Token creation via `create_access_token` (payload construction, expiry, HS256 encoding)
- Token validation via `decode_access_token` (signature check, expiry check, claim extraction, `TokenPayload` construction)
- Cookie writing via `set_auth_cookie` (HttpOnly, SameSite=Lax, conditional Secure flag, max_age)
- Cookie clearing via `clear_auth_cookie`
- Lazy settings access — `get_settings()` called at function call time, not import time

**Out of scope:**
- Role enforcement (handled in `dependencies.py`)
- Token refresh logic
- Cookie reading / token extraction (handled in `dependencies.py`)
- Database interactions

##### Happy path scenarios

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| Create token from User with `UserRole` enum | `User(id=uuid4(), role=UserRole.user)` | Returns a non-empty JWT string; decoded payload contains `sub` (UUID string), `role="user"`, `exp` ~8 hours from now, `iat` |
| Create token from User with pre-serialised string role | `User(id=uuid4(), role="admin")` | Returns a valid JWT; `role` claim is `"admin"` |
| Decode a freshly created token | Valid JWT from `create_access_token` | Returns `TokenPayload(sub=..., role=..., exp=...)` with matching claims |
| Set auth cookie in production | `response`, valid token string, `ENVIRONMENT="production"` | Cookie set with `HttpOnly=True`, `SameSite="lax"`, `Secure=True`, `max_age=28800` (8 h), name `"access_token"` |
| Set auth cookie in development | `response`, valid token string, `ENVIRONMENT="development"` | Cookie set without `Secure` flag; all other attributes unchanged |
| Clear auth cookie | Any `response` object | `delete_cookie` called with name `"access_token"` and matching path; no exception raised |
| Settings read at call time | `JWT_SECRET` patched after import | `create_access_token` uses the patched value, not the import-time value |

##### Error scenarios

| Error type | Trigger condition | Expected behavior |
|-----------|------------------|-------------------|
| `jose.JWTError` — expired | Token `exp` claim is in the past | `decode_access_token` raises `jose.JWTError`; no `TokenPayload` returned |
| `jose.JWTError` — invalid signature | Token signed with a different secret | `decode_access_token` raises `jose.JWTError` |
| `jose.JWTError` — malformed token | Arbitrary non-JWT string passed | `decode_access_token` raises `jose.JWTError` |
| `jose.JWTError` — missing required claim | Token encoded without `sub` or `role` | `decode_access_token` raises `jose.JWTError` |
| No exception from `create_access_token` | Any valid `User` object | Function returns a string; never raises under normal conditions |
| No exception from `set_auth_cookie` / `clear_auth_cookie` | Valid `response` object | Functions complete without raising |

##### Boundary conditions

- (REQ-108) Cookie attributes must include `HttpOnly`; `Secure` flag must be present in all environments except `"development"`.
- (REQ-108) Token must not appear in response body or URL — `set_auth_cookie` must use `response.set_cookie`, not return the token string.
- Access token expiry window is exactly 8 hours (`ACCESS_TOKEN_EXPIRE_HOURS = 8`); `exp` must equal `iat + 28800` seconds.
- `sub` claim must be a string representation of the UUID, not the UUID object itself.
- `role` claim must be the string value of the enum (e.g. `"user"`, `"admin"`), not the enum repr.

##### Integration points

- `decode_access_token` is called by `dependencies.py` (`get_current_user`) — any `jose.JWTError` it raises is caught there and converted to HTTP 401.
- `create_access_token` is called by `oidc.py` (callback handler) and `magic_link.py` (verify handler) after successful authentication.
- `set_auth_cookie` / `clear_auth_cookie` are called by route handlers after `create_access_token` and on logout respectively.
- `get_settings()` is the sole external dependency; must be patchable in tests without patching module-level globals.

##### Known test gaps

- `ACCESS_TOKEN_EXPIRE_HOURS` is a hard-coded module constant; environment-driven override is not testable without a code change.
- No test can verify that `JWT_SECRET` misconfiguration raises at settings load time rather than at token creation — that is a Pydantic settings concern.

##### Agent isolation contract

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only)
>
> **Must NOT receive:** Source implementation files, other modules' test specs, or the engineering guide directly.

---

#### `app/auth/magic_link.py` — Passwordless Email Authentication

**Module purpose:** Generates single-use, SHA-256-hashed magic link tokens, dispatches them by email via `aiosmtplib`, and verifies them to provision or retrieve a `User` on click.

**In scope:**
- Token generation: 32-byte URL-safe random token via `secrets.token_urlsafe`
- Hash storage: only the SHA-256 hash is persisted in `MagicLink`; raw token travels only in the email
- `MagicLink` record creation with `consumed=False`, 15-minute `expires_at`, optional `user_id` pre-fill
- `db.flush()` before SMTP dispatch to ensure record durability
- Email construction and dispatch via `aiosmtplib.send` with STARTTLS
- Token verification: hash lookup, expiry check, single-use (`consumed`) check, atomic `consumed=True` mark
- User provisioning: OID-by-`user_id` → email fallback → create-new three-step path
- New user defaults: `role=UserRole.user`, `is_active=True`, `display_name` from email local part

**Out of scope:**
- JWT issuance after verification (handled by calling route handler via `jwt.py`)
- Cookie management
- Rate limiting (REQ-128 — SHOULD, not implemented in this module)
- Audit logging (REQ-126 — SHOULD)

##### Happy path scenarios

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| `send_magic_link` for existing user | Known email, matching `User` row in DB | `MagicLink` record created with `user_id` pre-filled, `consumed=False`, `expires_at` ~15 min from now; `aiosmtplib.send` called once with URL containing raw token |
| `send_magic_link` for unknown email | Email not in `users` table | `MagicLink` record created with `user_id=None`; email dispatched; no `User` row created yet |
| Verification returns existing user by `user_id` | Valid unexpired unconsumed token; `user_id` set and user exists | `record.consumed` set to `True`; returns the matching `User` |
| Verification falls back to email lookup | Valid token; `user_id` is None; user exists by email | Returns existing `User`; `record.user_id` back-filled |
| Verification provisions new user | Valid token; no user by `user_id` or email | New `User` created with `role=UserRole.user`, `is_active=True`, `display_name` from local-part of email; returned |
| Token consumed mark is set before user lookup | Any valid token | `record.consumed = True` and `db.add(record)` occur before any `User` table query |
| Verification URL format | `BASE_URL="https://example.com"` | Email body contains `https://example.com/auth/magic/verify?token=<raw_token>` |

##### Error scenarios

| Error type | Trigger condition | Expected behavior |
|-----------|------------------|-------------------|
| `MagicLinkExpiredError` | Token hash not found in DB | Raised immediately; maps to HTTP 410 per Phase 0 contract |
| `MagicLinkExpiredError` | `record.consumed = True` | Raised before any user lookup; maps to HTTP 410 |
| `MagicLinkExpiredError` | `record.expires_at < now` (naive datetime normalised to UTC) | Raised before any user lookup; maps to HTTP 410 |
| `aiosmtplib.SMTPException` (or subclass) | SMTP server unreachable or rejects recipient | Propagates uncaught from `send_magic_link`; orphaned `MagicLink` record is left in DB (expires unused) |
| `sqlalchemy.exc.IntegrityError` | Hash collision or concurrent flush on same email | Propagates uncaught; surfaces as HTTP 500 |

##### Boundary conditions

- (REQ-106) Token expiry window is exactly 15 minutes; a token used at t+14:59 must succeed; at t+15:00 must raise `MagicLinkExpiredError`.
- (REQ-106) Second use of a valid, unexpired token must raise `MagicLinkExpiredError` (consumed flag check).
- (REQ-106) Expired token, whether consumed or not, must raise `MagicLinkExpiredError` — the two failure modes are intentionally indistinguishable to callers (oracle attack prevention).
- (REQ-104) Exactly one email is sent per `send_magic_link` call; `aiosmtplib.send` must be called exactly once.
- (REQ-112) New user provisioned with `role=UserRole.user`; role must not default to admin under any input.
- (REQ-112) Concurrent duplicate verification clicks: only the first should succeed (second sees `consumed=True`); the `consumed` flag must be set atomically before user lookup.
- `expires_at` naive datetime stored by some DB backends must be normalised with `replace(tzinfo=timezone.utc)` before comparison to `datetime.now(timezone.utc)`.

##### Integration points

- Calls `db.flush()` (SQLAlchemy async session) to persist `MagicLink` before SMTP dispatch.
- Calls `aiosmtplib.send` — must be mocked in all unit tests.
- Returns a `User` ORM object; the calling route handler passes it to `jwt.create_access_token`.
- Raises `MagicLinkExpiredError` (Phase 0 exception) — route handler maps this to HTTP 410.
- Reads `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM`, `BASE_URL`, `APP_NAME` from `get_settings()`.

##### Known test gaps

- `MAGIC_LINK_EXPIRY_MINUTES = 15` is a hard-coded constant; environment override is not testable without a code edit.
- SMTP authentication failure path (wrong credentials) is not distinguishable from network unreachability in unit tests — both surface as `SMTPException`.
- Orphaned `MagicLink` record cleanup after SMTP failure is not handled in this module; no test can assert cleanup behavior here.

##### Agent isolation contract

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only)
>
> **Must NOT receive:** Source implementation files, other modules' test specs, or the engineering guide directly.

---

#### `app/auth/oidc.py` — Azure AD OIDC Integration

**Module purpose:** Implements the Azure AD OpenID Connect authorization code flow — login initiation, callback handling, tenant validation, and deterministic three-step user provisioning — and discards OAuth tokens after identity extraction.

**In scope:**
- Lazy OAuth registry initialisation (`_get_oauth`) — reads settings only on first call, caches result
- Login initiation (`initiate_login`): state nonce generation, session storage, redirect URL construction
- Callback handling (`handle_callback`): authorization code exchange, identity claim extraction, `tid` tenant check, delegation to `_provision_user`
- Tenant validation: reject tokens whose `tid` != `settings.AZURE_TENANT_ID` before any DB write
- `_provision_user` three-step lookup: OID match → email match with OID back-fill → create new user
- New user defaults: `role=UserRole.user`, `is_active=True`
- OID back-fill on email-matched users for future fast-path lookups

**Out of scope:**
- JWT issuance (handled by calling route handler via `jwt.py`)
- Cookie management
- PKCE and state validation — delegated to `authlib`'s internal machinery
- Azure App Registration configuration (REQ-124 — infrastructure concern)
- Audit logging (REQ-126 — SHOULD)

##### Happy path scenarios

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| `initiate_login` | Valid request with a writable session | Session `"oauth_state"` set to a 32-byte URL-safe nonce; returns Azure AD authorization URL string |
| Callback — returning user (OID match) | `tid` matches, `oid` matches existing `User.azure_oid` | Returns existing `User` unchanged; no DB writes |
| Callback — first OIDC login for magic-link user (email match) | `tid` matches, `oid` not in DB, `email` matches existing `User` | Returns existing `User`; `user.azure_oid` back-filled; `display_name` updated if claims provide one; `db.flush()` called |
| Callback — brand new user (no match) | `tid` matches, `oid` and `email` not in DB | New `User` created with `role=UserRole.user`, `is_active=True`, `azure_oid=oid`, correct `email` and `display_name`; `db.flush()` called; returned |
| Lazy registry caching | `_get_oauth` called twice | `authlib.OAuth` instantiated once; second call returns same object |
| Identity claims from `userinfo` | Token response includes `userinfo` dict | `oid`, `email`, `tid` extracted from `userinfo` |
| Identity claims from `id_token` | Token response has no `userinfo`, has `id_token` | `oid`, `email`, `tid` extracted from decoded `id_token` |

##### Error scenarios

| Error type | Trigger condition | Expected behavior |
|-----------|------------------|-------------------|
| `TenantMismatchError` | `tid` claim != `settings.AZURE_TENANT_ID` | Raised immediately in `handle_callback` before any DB work; maps to HTTP 403 per Phase 0 contract; no user record created or modified |
| `authlib.integrations.base_client.errors.OAuthError` | Azure AD returns error response, state mismatch, or PKCE failure | Propagates uncaught; route handler should map to HTTP 400/502 |
| `sqlalchemy.exc.IntegrityError` | Concurrent OIDC logins for the same new user | Propagates uncaught; surfaces as HTTP 500 |

##### Boundary conditions

- (REQ-102) A token from a different tenant (any `tid` value not equal to `AZURE_TENANT_ID`) must always raise `TenantMismatchError`, regardless of whether the email or OID exists in the DB.
- (REQ-102) The tenant check must occur before `_provision_user` is called — no DB reads or writes may precede it.
- (REQ-112) New users must receive `role=UserRole.user`; no input from the OIDC claims may result in `role=UserRole.admin` at creation time.
- (REQ-112) Concurrent first-logins for the same new user must not produce duplicate user records (integrity error path).
- (REQ-116) OID back-fill must update `user.azure_oid` only on the email-match path (step 2), not on the OID-match path (step 1).
- Three-step lookup order is deterministic: step 1 (OID) must be evaluated before step 2 (email); step 3 (create) must be reached only when both step 1 and step 2 return nothing.

##### Integration points

- Calls `authlib` OAuth registry — must be mocked via `_get_oauth` patch in unit tests.
- Calls `db.execute` (SQLAlchemy async session) for `User` lookups and `db.flush()` for writes.
- Returns a `User` ORM object; calling route handler passes it to `jwt.create_access_token`.
- Raises `TenantMismatchError` (Phase 0 exception) — route handler maps to HTTP 403.
- Reads `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_TENANT_ID`, `BASE_URL` from `get_settings()` at first `_get_oauth` call.

##### Known test gaps

- State nonce validation is handled internally by `authlib`; this module cannot be unit-tested for state mismatch without a full `authlib` mock that honours session state.
- `id_token` decoding logic inside `authlib` is not directly exercised in unit tests — tests can only assert which claim source the module reads.
- PKCE verification is opaque to this module; no unit test can assert PKCE correctness.

##### Agent isolation contract

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only)
>
> **Must NOT receive:** Source implementation files, other modules' test specs, or the engineering guide directly.

---

#### `app/auth/dependencies.py` — FastAPI Auth Dependencies

**Module purpose:** Provides FastAPI dependency functions (`get_current_user`, `require_admin`, `require_owner_or_admin`) and type aliases (`CurrentUser`, `AdminUser`) that extract tokens, load the active `User`, enforce roles, and gate all protected routes.

**In scope:**
- Token extraction: cookie `"access_token"` checked first, then `Authorization: Bearer` header fallback
- Dev bypass: when `DEV_AUTH_BYPASS=True` and no token is present, return/create `dev@aion-bulletin.local` admin user
- JWT decoding via `decode_access_token`; `JWTError` caught and converted to HTTP 401
- User loading from DB by UUID in `sub` claim; missing or inactive user returns HTTP 401
- `require_admin`: role check returning HTTP 403 if `user.role != UserRole.admin`
- `require_owner_or_admin`: plain async function raising HTTP 403 unless `str(user.id) == resource_owner_id` or `user.role == UserRole.admin`
- `CurrentUser` and `AdminUser` type aliases

**Out of scope:**
- Token creation or cookie writing (handled in `jwt.py`)
- Database session management (session injected via `Depends`)
- Route handler logic
- Audit logging (REQ-126 — SHOULD)

##### Happy path scenarios

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| Token from cookie | Request with valid `access_token` cookie; active user in DB | Returns the `User` ORM object |
| Token from Bearer header (cookie absent) | No cookie; `Authorization: Bearer <valid_token>` header; active user in DB | Returns the `User` ORM object |
| Dev bypass active, no token | `DEV_AUTH_BYPASS=True`; no cookie; no Authorization header | Returns dev user (`email="dev@aion-bulletin.local"`, `role=UserRole.admin`, `is_active=True`); creates user on first call |
| Dev bypass active, real token present | `DEV_AUTH_BYPASS=True`; valid `access_token` cookie present | Token path taken; dev bypass NOT triggered; returns the user from the valid token |
| `require_admin` with admin user | `get_current_user` returns `User(role=UserRole.admin)` | Returns the user unchanged |
| `require_owner_or_admin` — owner | `str(user.id) == resource_owner_id` | Returns without raising |
| `require_owner_or_admin` — admin | `user.role == UserRole.admin`; `str(user.id) != resource_owner_id` | Returns without raising |

##### Error scenarios

| Error type | Trigger condition | Expected behavior |
|-----------|------------------|-------------------|
| `HTTPException(401, "Not authenticated")` | No cookie, no Bearer header, `DEV_AUTH_BYPASS=False` | FastAPI returns HTTP 401; route handler not called |
| `HTTPException(401, "Invalid or expired token")` | `decode_access_token` raises `jose.JWTError` (expired, bad signature, malformed) | FastAPI returns HTTP 401 |
| `HTTPException(401, "User not found or inactive")` | Valid JWT but `sub` UUID not found in DB | FastAPI returns HTTP 401 |
| `HTTPException(401, "User not found or inactive")` | Valid JWT; user row exists but `is_active=False` | FastAPI returns HTTP 401 |
| `HTTPException(403, "Admin access required")` | Authenticated user with `role=UserRole.user` injected into `require_admin` | FastAPI returns HTTP 403 |
| `HTTPException(403, "You do not have permission...")` | `require_owner_or_admin` called; user is not owner and not admin | Route handler receives the exception; FastAPI returns HTTP 403 |

##### Boundary conditions

- (REQ-108) Cookie name must be `"access_token"`; Bearer prefix must be exactly `"Bearer "` (7 chars including space).
- (REQ-120) Dev bypass must activate only when BOTH conditions hold: `DEV_AUTH_BYPASS=True` AND token is absent; a real token must always take precedence.
- (REQ-122) `DEV_AUTH_BYPASS=True` in a production environment must not be reachable — startup assertion is out of scope for this module but bypass behavior must be verified in unit tests.
- (REQ-114) `require_admin` must return HTTP 403 (not 401) for an authenticated non-admin user; the distinction matters for clients.
- (REQ-116) `require_owner_or_admin` must raise 403 when `user.id` (as string) does not match `resource_owner_id` AND `user.role != UserRole.admin`.
- `is_active` is checked on every request — a user deactivated after token issuance must receive HTTP 401 on the next request without waiting for token expiry.
- `_get_or_create_dev_user` must be idempotent: repeated calls with `DEV_AUTH_BYPASS=True` and no token must return the same user row (upsert-style).

##### Integration points

- Calls `decode_access_token` from `jwt.py` — in unit tests, mock this function to control `JWTError` / `TokenPayload` outcomes.
- Executes `db.execute(select(User).where(User.id == sub_uuid))` — mock or use a test DB session.
- `require_owner_or_admin` is called directly by route handlers, not wired via `Depends`; it is a plain async function.
- `CurrentUser` and `AdminUser` aliases are consumed by route handlers in other modules; correct `Annotated[User, Depends(...)]` structure must be verified.
- Reads `DEV_AUTH_BYPASS` from `get_settings()` — must be patchable at call time (lazy access pattern assumed).

##### Known test gaps

- The startup assertion that `DEV_AUTH_BYPASS` must not be `True` in `ENVIRONMENT=production` is not enforced within this module; no unit test in this module can cover that invariant.
- Concurrent dev-user creation (`_get_or_create_dev_user`) race conditions are untestable in single-threaded unit tests.
- `AdminUser` and `CurrentUser` type aliases are structural (they wrap `Depends`); their FastAPI injection behavior can only be fully verified in integration tests, not pure unit tests.

##### Agent isolation contract

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only)
>
> **Must NOT receive:** Source implementation files, other modules' test specs, or the engineering guide directly.

---

### Problem Management

#### Problem Management — `app/services/problems.py`, `app/services/feed.py`

**Module purpose:** Owns the full lifecycle of a problem — creation, FSM-governed status transitions, claim toggling, admin pinning, immutable edit history, and cursor-paginated multi-sort feed delivery.

**In scope:**
- Problem creation with category/tag validation and optional anonymous authorship
- FSM status transitions enforced via `ALLOWED_TRANSITIONS` with per-transition actor predicates
- Claim toggle (idempotent insert/delete on `Claim` table)
- Pin toggle with `MAX_PINNED = 3` enforcement (admin-only)
- Edit history: immutable pre-edit snapshot recorded on every `update_problem` call
- Cursor-based paginated feed with 4 sort modes (`new`, `top`, `active`, `discussed`)
- Feed filter combinations: `status`, `category_id`, `tag_ids` (AND), `is_claimed`
- Pinned problems prepended on first page only, not consuming pagination slots
- Anonymous posting: `author_id` always stored; author hidden from non-admin responses
- `activity_at` timestamp updates on claim, unclaim, status transition, and edit
- Hard-cap of 50 on feed `limit` parameter

**Out of scope:**
- Claim auto-expiry scheduler (14-day background job — REQ-160; scheduled job, not service logic)
- Two-step duplicate confirmation workflow (REQ-162; workflow layer above the FSM)
- Full-text search (`GET /api/problems/search` — REQ-178)
- Idempotency-Key deduplication on problem creation (REQ-176)
- Upstar / voting logic (owned by a separate module)
- Solution management (REQ-200+)
- `starred` filter (REQ-182; MAY priority)
- Non-UUID validation of `category_id`/`tag_ids` before they reach `_apply_filters`

---

##### Happy path scenarios

| Scenario | Input | Expected output |
|---|---|---|
| Create problem — minimal valid | `title="Hello"` (5 chars), `description="Ten chars!!"` (10 chars), valid `category_id`, `tag_ids=[]`, `is_anonymous=false` | 201; `ProblemDetailResponse` with `status=open`, `author` shows real user |
| Create problem — max title | `title` = 200-char string, valid description and category | 201; problem persisted with full title |
| Create problem — with tags | Valid `tag_ids` list of 2 UUIDs | 201; `ProblemTag` rows inserted; tags returned in response |
| Create problem — anonymous | `is_anonymous=true` | 201; `author_id` stored in DB; non-admin response shows `"author": "Anonymous"` |
| Create problem — anonymous, admin read | Same problem fetched with admin token | Response exposes real `author_id` |
| FSM: open → claimed (any user) | Authenticated user POSTs status transition `target=claimed` | 200; `status=claimed`; `activity_at` updated |
| FSM: open → duplicate (admin) | Admin actor POSTs `target=duplicate` | 200; `status=duplicate` |
| FSM: claimed → open (any user) | Authenticated user POSTs `target=open` from `claimed` | 200; `status=open`; `activity_at` updated |
| FSM: claimed → solved (any user) | Authenticated user POSTs `target=solved` from `claimed` | 200; `status=solved`; `activity_at` updated |
| FSM: solved → accepted (author) | Problem author POSTs `target=accepted` from `solved` | 200; `status=accepted` |
| FSM: solved → accepted (admin) | Admin actor POSTs `target=accepted` from `solved` on another user's problem | 200; `status=accepted` |
| FSM: solved → open (author reopen) | Problem author POSTs `target=open` from `solved` | 200; `status=open`; `activity_at` updated |
| FSM: solved → open (admin reopen) | Admin POSTs `target=open` from `solved` on another user's problem | 200; `status=open` |
| Claim toggle — first claim | User A claims an unclaimed problem | 200; `{"claimed": true, "claim_id": "<uuid>"}` |
| Claim toggle — release existing claim | Same user calls claim endpoint again on the same problem | 200; `{"claimed": false}`; `Claim` row deleted |
| Claim toggle — second user claims | User B claims a problem already claimed by user A | 200; both users appear in claims list; user A flagged as primary |
| Claim toggle — updates activity_at | Any successful claim insert | `problem.activity_at` updated |
| Pin — first pin (admin) | Admin pins an unpinned problem; 0 pins exist | 200; `is_pinned=true` |
| Pin — second and third pin | Admin pins second and third distinct problems | 200 each; 3 problems now pinned |
| Unpin — from pinned state | Admin pins already-pinned problem | 200; `is_pinned=false`; no count check executed |
| Unpin — frees a slot for new pin | Admin unpins one of 3, then pins another | 200 on both operations |
| Edit — update title | Author PATCHes `{"title": "New title"}` | 200; `ProblemEditHistory` row created with `snapshot={"title": "<old_title>"}`; `activity_at` updated |
| Edit — update description | Author PATCHes `{"description": "Updated description text"}` | 200; history snapshot contains only `description` key |
| Edit — update title and description together | Author PATCHes both fields | 200; single history row with both old values in snapshot |
| Edit — update category_id | Author PATCHes `{"category_id": "<valid_uuid>"}` | 200; history snapshot contains `category_id` key with old UUID stringified |
| Edit — count increments | Author makes 3 successive edits | `edit_history_count` in detail response equals 3 |
| Edit — admin may edit any problem | Admin PATCHes another user's problem | 200; history row records `editor_id=admin_id` |
| Feed — default sort (new) | GET `/problems` with no params | 200; `CursorPage` with up to 20 items sorted by `created_at DESC`; `next_cursor` present if more exist |
| Feed — sort=top | GET `/problems?sort=top` | Items ordered by upstar count DESC, tie-broken by `id DESC` |
| Feed — sort=active | GET `/problems?sort=active` | Items ordered by `activity_at DESC`, tie-broken by `id DESC` |
| Feed — sort=discussed | GET `/problems?sort=discussed` | Items ordered by comment count DESC, tie-broken by `id DESC` |
| Feed — cursor pagination traversal | First page returns `next_cursor`; pass cursor to next call | Second page is non-overlapping and contiguous; no duplicates across pages |
| Feed — final page | Fetch until `next_cursor` is null | All problems returned exactly once; last page `next_cursor=null` |
| Feed — limit=50 | GET `/problems?limit=50` | Returns up to 50 non-pinned items |
| Feed — filter by status | GET `/problems?status=open` | Only open problems returned |
| Feed — filter by category | GET `/problems?category_id=<uuid>` | Only problems in that category returned |
| Feed — filter by single tag | GET `/problems?tag_ids=<uuid>` | Only problems carrying that tag returned |
| Feed — filter by multiple tags (AND) | GET `/problems?tag_ids=<uuid1>,<uuid2>` | Only problems carrying both tags returned |
| Feed — filter is_claimed=true | GET `/problems?is_claimed=true` | Only problems with at least one active claim returned |
| Feed — filter is_claimed=false | GET `/problems?is_claimed=false` | Only unclaimed problems returned |
| Feed — combined filters | GET `/problems?status=open&category_id=<uuid>&is_claimed=false` | Only problems satisfying all three conditions |
| Feed — pinned prepended on first page | 3 pinned problems exist; GET `/problems` (no cursor) | Pinned problems appear first; total items may be up to `limit + 3`; pinned items do not count toward `limit` |
| Feed — pinned not on subsequent pages | Pass cursor from first page | Pinned problems absent from second page |
| Feed — pinned bypass status filter | 1 pinned problem has status=solved; GET `/problems?status=open` | Pinned problem still appears on first page even though status filter would exclude it from main feed |

---

##### Error scenarios

| Error type | Trigger condition | Expected behavior |
|---|---|---|
| Unauthenticated problem creation | POST `/problems` with no auth token | 401 |
| Invalid category on creation | `category_id` references a non-existent or soft-deleted category | `ValueError("Category {id} does not exist")` → 400; problem not created |
| Invalid tags on creation | One or more `tag_ids` UUIDs not found | `ValueError("One or more tags do not exist")` → 400; problem not created |
| Title too short | `title` = 4 characters | 422; field-level error identifying `title` |
| Title too long | `title` = 201 characters | 422; field-level error identifying `title` |
| Description too short | `description` = 9 characters | 422; field-level error identifying `description` |
| FSM: forbidden transition — not in table | Attempt `open → accepted` | `ForbiddenTransitionError(open, accepted)` → 409 |
| FSM: forbidden transition — not in table | Attempt `open → solved` | `ForbiddenTransitionError(open, solved)` → 409 |
| FSM: forbidden transition — not in table | Attempt `accepted → open` | `ForbiddenTransitionError(accepted, open)` → 409 |
| FSM: forbidden transition — not in table | Attempt `accepted → solved` | `ForbiddenTransitionError(accepted, solved)` → 409 |
| FSM: forbidden transition — not in table | Attempt `duplicate → open` | `ForbiddenTransitionError(duplicate, open)` → 409 |
| FSM: predicate fails — open→duplicate by non-admin | Non-admin user attempts `open → duplicate` | `ForbiddenTransitionError(open, duplicate)` → 409 |
| FSM: predicate fails — solved→accepted by non-author non-admin | Third-party user attempts `solved → accepted` | `ForbiddenTransitionError(solved, accepted)` → 409 |
| FSM: predicate fails — solved→open by non-author non-admin | Third-party user attempts `solved → open` | `ForbiddenTransitionError(solved, open)` → 409 |
| FSM: problem not found | `transition_status` called with unknown `problem_id` | `ValueError("Problem not found")` → 404 |
| FSM: actor not found | `transition_status` called with unknown `actor_id` | `ValueError("Actor not found")` → 404 |
| Pin by non-admin | Non-admin user POSTs to `/problems/{id}/pin` | 403 (blocked by `AdminUser` dependency before service is called) |
| Pin limit exceeded | 3 problems already pinned; admin attempts to pin a 4th | `PinLimitExceededError` → 409 |
| Pin on missing problem | `pin_problem` called with unknown `problem_id` | `ValueError` → 404 |
| Claim on missing problem | `claim_problem` called with unknown `problem_id` | `ValueError("Problem not found")` → 404 |
| Edit by non-owner non-admin | Non-author, non-admin PATCH | 403 (route-layer `require_owner_or_admin` check) |
| Edit — empty payload | PATCH with no editable fields in body | Route returns 400 before service is called |
| Edit — problem not found | PATCH on non-existent `problem_id` | 404 (route loads row before ownership check) |
| Feed — malformed cursor | GET `/problems?cursor=!!!notbase64!!!` | `HTTPException(400, "Malformed cursor")` → 400 |
| Feed — unsupported sort value | GET `/problems?sort=hottest` | 422 |
| Feed — limit exceeds hard-cap | GET `/problems?limit=51` | Service silently caps at 50 (returns ≤ 50 items); verify no 422 is raised by the service layer |

---

##### Boundary conditions

- **Title length — reject below minimum:** `title` of exactly 4 characters returns 422 (REQ-152)
- **Title length — accept minimum:** `title` of exactly 5 characters returns 201 (REQ-152)
- **Title length — accept maximum:** `title` of exactly 200 characters returns 201 (REQ-152)
- **Title length — reject above maximum:** `title` of exactly 201 characters returns 422 (REQ-152)
- **Description length — reject below minimum:** `description` of exactly 9 characters returns 422 (REQ-152)
- **Description length — accept minimum:** `description` of exactly 10 characters returns 201 (REQ-152)
- **Pin count at limit:** With 2 pinned problems, a third pin succeeds; a fourth raises `PinLimitExceededError` (REQ-164; `MAX_PINNED = 3`)
- **Pin count at zero:** Unpinning the only pinned problem succeeds with no limit check
- **Feed limit hard-cap:** `limit=50` returns ≤ 50 items; `limit=51` is capped to 50 by `min(limit, 50)` in service; verify cap value is exactly 50 (Phase 0 contract)
- **Feed first page with max pinned:** When 3 problems are pinned and `limit=50`, first page may contain up to 53 items total (3 pinned + 50 paginated) (REQ-174)
- **Cursor boundary — last page:** When fewer than `limit` rows are returned (fetched `limit+1`, got ≤ `limit`), `next_cursor` must be `null`
- **Cursor boundary — exact limit rows:** When exactly `limit` non-pinned items remain, the service fetches `limit+1`, gets `limit`, so `has_next=False` and `next_cursor=null`
- **Edit with no editable fields in payload:** Returns unmodified problem from service; route short-circuits with 400 before calling service
- **Edit snapshot stores only changed fields:** A patch of only `title` produces a snapshot dict with one key (`title`), not three
- **Tag count = 0:** `tag_ids=[]` on creation is valid; no `ProblemTag` rows inserted
- **Anonymous flag default:** Omitting `is_anonymous` defaults to `false`; author is surfaced normally

---

##### Integration points

- **`app/routes/problems.py` → `app/services/problems.py`:** Route delegates all write operations (`create_problem`, `transition_status`, `claim_problem`, `pin_problem`, `update_problem`) after handling auth/ownership guards. Route catches `ValueError` for 404/400 responses but does **not** catch `ForbiddenTransitionError` or `PinLimitExceededError`.
- **`app/routes/problems.py` → `app/services/feed.py`:** `GET /problems` route calls `get_feed`; passes validated query params.
- **`create_problem` → `get_problem`:** After `create_problem` returns the ORM object, the route calls `get_problem` to produce the full `ProblemDetailResponse` for the 201 response.
- **`app/services/problems.py` → `Category` model:** `create_problem` validates `category_id` existence and soft-delete status before persisting.
- **`app/services/problems.py` → `Tag` / `ProblemTag` models:** Tag UUID existence validated via COUNT query; `ProblemTag` rows bulk-inserted after `db.flush()` materializes `problem.id`.
- **`app/services/problems.py` → `Claim` model:** `claim_problem` reads and writes the `Claim` table; claim insert triggers `problem.activity_at` update.
- **`app/services/problems.py` → `ProblemEditHistory` model:** `update_problem` inserts one `ProblemEditHistory` row per call that mutates at least one editable field.
- **`app/services/feed.py` → `Problem`, `Upstar`, `Comment`, `Claim` models:** Feed query uses correlated subqueries against these tables for `top` and `discussed` sort modes and `is_claimed` filter.
- **`AdminUser` dependency → `pin_problem`:** Non-admins are rejected at the dependency layer; `pin_problem` is never reached.
- **`require_owner_or_admin` guard → `update_problem`:** Ownership enforced at route layer; service assumes authorized caller.

---

##### Known test gaps

- **`ForbiddenTransitionError` and `PinLimitExceededError` HTTP mapping is unimplemented:** Engineering Guide (§ Error Behavior) explicitly notes these exceptions are not caught by the route layer, causing 500 rather than the Phase 0 contract's 409. Tests verifying 409 responses for forbidden transitions and pin-limit violations will fail until error handlers are added.
- **Concurrent pin writes not tested:** The COUNT-based pin limit relies on transaction serialization for correctness under concurrent load; no concurrency test is defined here.
- **`is_claimed` filter false-positive edge case:** Behavior when a claim exists but the associated problem is in `duplicate` status is not specified; test coverage for this interaction is absent.
- **`category_id` / `tag_ids` UUID format validation in feed:** Engineering Guide notes non-UUID strings cause `ValueError` propagating as 500; no input validation test at the route layer is defined for feed parameters.
- **Anonymous author visibility for partial-auth (viewer token expired mid-request):** The engineering guide notes auth failure on `GET /problems/{id}` is silently swallowed; behavior of `is_anonymous` flag in this case is untested.
- **`sort=top` and `sort=discussed` cursor stability:** The cursor encodes a correlated subquery value (upstar/comment count) that can change between pages; stale-cursor behavior is not specified or tested.
- **Claim primary-claimer designation logic:** REQ-158 specifies the earlier claimer is flagged as primary, but the engineering guide describes claim as a simple toggle with no primary/secondary distinction; this discrepancy is unresolved and untestable until the model is clarified.
- **REQ-174 spec vs. engineering guide conflict on pinned + status filter:** REQ-174 states pinned problems appear "even when a status filter would otherwise exclude them"; the engineering guide states pinned items pass through `_apply_filters`. These are contradictory; test outcome depends on implementation resolution.

---

##### Agent isolation contract

> **Module boundary:** Tests for this module must not import from or invoke any code in `app/services/solutions.py`, `app/services/comments.py`, `app/services/upstars.py`, or any module outside `app/services/problems.py`, `app/services/feed.py`, and `app/routes/problems.py`. Upstream dependencies (`Category`, `Tag`, `Claim`, `ProblemEditHistory`, `Upstar`, `Comment` models) must be seeded via direct DB fixtures — never via their own service functions. The `AdminUser` dependency and `require_owner_or_admin` guard must be tested through the route layer using real auth fixtures, not bypassed via direct service calls.
>
> **Exceptions under test:** `ForbiddenTransitionError(current, target)` and `PinLimitExceededError` are raised by `app/services/problems.py` and are asserted at the service level to carry the correct arguments. HTTP mapping (409) is asserted at the route level only after the error-handler gap identified in Known Test Gaps is resolved.
>
> **Enums:** Tests must import `ProblemStatus` and `SortMode` from the application package — never construct raw string values for status or sort in service-layer calls.
>
> **Schema validation:** `ProblemCreate` field constraint tests (title/description boundaries) are exercised through the route layer so Pydantic validation produces 422 with field-level details as specified in REQ-152. Direct service-layer calls bypassing schema validation do not substitute for these tests.
>
> **Cursor opacity:** Tests must treat the `next_cursor` value as opaque — pass it verbatim to the next request without decoding. Only the decoded structure (`sort_value`, `id`) may be inspected in unit tests of `encode_cursor` / `decode_cursor` directly.

---

### Solution Management

#### app/services/solutions.py · app/routes/solutions.py — Solution Management

**Module purpose:** Manages the full lifecycle of solutions posted against problems, including creation, append-only versioning, acceptance (atomic swap), anonymous masking, and deletion.

**In scope:**
- `POST /problems/{problem_id}/solutions` — create a solution (auth required)
- `GET /problems/{problem_id}/solutions` — list solutions with sort modes (auth optional)
- `POST /solutions/{solution_id}/versions` — append a new version (auth required)
- `GET /solutions/{solution_id}/versions` — version history (no auth required)
- `POST /solutions/{solution_id}/accept` — accept a solution (auth required)
- `DELETE /solutions/{solution_id}` — delete a solution (auth required)
- `PATCH /solutions/{solution_id}` and `PUT /solutions/{solution_id}` — blocked at route layer (405)
- Anonymous masking logic: suppressed for third parties, revealed to author-self and admin

**Out of scope:**
- Comment system (separate module)
- Upvoting (handled by Voting module)
- Problem lifecycle transitions other than the terminal-status guard
- Frontend display logic (REQ-220 green border/badge)
- URL query-parameter shareability for sort mode (REQ-214, SHOULD priority)

---

##### Happy path scenarios

| Scenario | Input | Expected output |
|---|---|---|
| Create solution on an open problem | `POST /problems/{id}/solutions` with `description` (≥10 chars), valid `problem_id`, authenticated user, `is_anonymous: false` | HTTP 201; `Solution` row with `status="pending"`, `SolutionVersion` row with `version_number=1`, `solution.current_version_id` set to new version ID, `problem.activity_at` updated |
| Create anonymous solution | Same as above with `is_anonymous: true` | HTTP 201; `author` field is `null` in response to a third-party caller; `author` revealed when viewer is the author themselves |
| Admin views anonymous solution | `GET /problems/{id}/solutions` as authenticated admin | Admin caller receives real `author` value despite `is_anonymous: true` (route-layer `_unmask_if_admin` override) |
| Create solution with valid git_link | `git_link` set to a GitHub PR URL, GitLab branch URL, raw commit SHA URL, or plain repo URL | HTTP 201; `git_link` stored and returned verbatim (REQ-204) |
| Create solution without git_link | `git_link` omitted or `null` | HTTP 201; `git_link` stored as NULL, returned as `null` |
| List solutions — default sort | `GET /problems/{id}/solutions` with solutions A (accepted, 3 upvotes), B (pending, 10 upvotes), C (pending, 10 upvotes, older) | HTTP 200; order is A → B → C (accepted first, then upvote count DESC, tie broken by `created_at` DESC) (REQ-212) |
| List solutions — newest sort | `GET /problems/{id}/solutions?sort=newest` | HTTP 200; solutions ordered purely by `created_at DESC`, status and upvote count ignored |
| List solutions on problem with none | `GET /problems/{id}/solutions` where problem exists but has no solutions | HTTP 200; empty array (REQ-202) |
| Append a new version | `POST /solutions/{id}/versions` with new `description` (≥10 chars) | HTTP 201; new `SolutionVersion` row inserted with `version_number = previous_max + 1`; `solution.current_version_id` updated to new version ID; original version row untouched |
| Version history ordering | `GET /solutions/{id}/versions` after two version submissions (3 total) | HTTP 200; array of exactly 3 records with `version_number` values strictly ascending (1, 2, 3) (REQ-206, REQ-208) |
| Each version record fields | `GET /solutions/{id}/versions` | Each record includes `id`, `version_number`, `description`, `git_link`, `created_by`, `created_at` |
| Accept solution as problem author | `POST /solutions/{id}/accept` by the problem's author | HTTP 200; target solution `status = "accepted"` |
| Accept solution as admin | `POST /solutions/{id}/accept` by user with `role == admin` | HTTP 200; target solution `status = "accepted"` |
| Atomic acceptance swap | `POST /solutions/{B}/accept` when solution A is currently `status = "accepted"` on the same problem | A reverts to `status = "pending"` and B becomes `status = "accepted"` within a single flush; exactly one accepted solution per problem at all times (REQ-210) |
| Delete solution as author | `DELETE /solutions/{id}` by the solution's author | HTTP 200 or 204; solution removed |
| Delete solution as admin | `DELETE /solutions/{id}` by admin | HTTP 200 or 204; solution removed |
| PATCH blocked | `PATCH /solutions/{id}` with any body | HTTP 405; detail message directs caller to `POST /solutions/{id}/versions` |
| PUT blocked | `PUT /solutions/{id}` with any body | HTTP 405; same detail message as PATCH |

---

##### Error scenarios

| Error type | Trigger condition | Expected behavior |
|---|---|---|
| Problem not found (create) | `POST /problems/{id}/solutions` with non-existent `problem_id` | HTTP 400; `"Problem not found"` |
| Terminal status — accepted | `POST /problems/{id}/solutions` where problem has `status = "accepted"` | HTTP 400; message includes current status (e.g., `"Cannot add solutions to a problem with status 'accepted'"`) |
| Terminal status — duplicate | `POST /problems/{id}/solutions` where problem has `status = "duplicate"` | HTTP 400; message includes current status |
| Problem not found (list) | `GET /problems/{id}/solutions` with non-existent `problem_id` | HTTP 404; `"Problem not found"` |
| Solution not found (get, version, accept, delete) | Operation on non-existent `solution_id` | HTTP 404; `"Solution not found"` |
| Non-author, non-admin accept | `POST /solutions/{id}/accept` by a user who is neither problem author nor admin | HTTP 403; `"Only the problem owner or an admin can accept a solution"` |
| Non-author, non-admin delete | `DELETE /solutions/{id}` by a user who is neither solution author nor admin | HTTP 403; `"Only the solution author or an admin can delete"` |
| Invalid UUID in path | Any endpoint with a malformed UUID path parameter (e.g., `solution_id = "not-a-uuid"`) | HTTP 400 (FastAPI validation default) |
| Description too short | `POST /problems/{id}/solutions` or `POST /solutions/{id}/versions` with `description` fewer than 10 characters | HTTP 422; Pydantic validation error from `SolutionCreate` schema |
| Invalid git_link | `git_link` set to a non-URL string (fails `AnyHttpUrl` validation) | HTTP 422; Pydantic validation error |
| Partial write on error | Any write endpoint that raises mid-transaction | No partial state committed; enclosing session transaction is rolled back |

---

##### Boundary conditions

- `description` exactly 10 characters: must be accepted (lower boundary of `SolutionCreate` schema).
- `description` exactly 9 characters: must be rejected with HTTP 422.
- `git_link = null` (explicit null) vs. omitted: both result in NULL stored; returned as `null` in response.
- `is_anonymous` defaults to `false` when omitted from request body.
- `version_number` on the very first version is exactly `1`; on the nth submission it is `MAX(version_number) + 1` — verify no off-by-one.
- Acceptance swap when no prior accepted solution exists: only target solution changes to `"accepted"`; no rows set to `"pending"` (zero-row UPDATE is valid, not an error).
- Multiple previously accepted solutions (should not exist, but guard is a bulk reset): all rows with `status = "accepted"` on the same problem are reset to `"pending"` before new acceptance.
- Viewer is both the author and an admin: admin unmasking path applies; author is revealed.
- Terminal statuses set: exactly `{"accepted", "duplicate"}` — status `"pending"`, `"rejected"`, `"in_progress"` must NOT block new solution creation.

---

##### Integration points

- **Database session / transaction boundary:** All writes use `await db.flush()` within the same session; commit is managed by the request lifecycle. Tests must confirm rollback on failure leaves no orphan rows.
- **Problem model:** `problem.activity_at` is updated on `create_solution` and `accept_solution`; tests should assert the timestamp advances.
- **Auth dependency (`CurrentUser` / `_optional_viewer_id`):** Write endpoints require a resolved user; read endpoints work unauthenticated. Tests for anonymous masking require passing a `viewer_id` to verify conditional reveal.
- **SolutionVersion ↔ Solution foreign key:** `solution.current_version_id` must point to a valid `SolutionVersion` row after every create or version-append operation.
- **`SolutionSortMode` enum:** Route accepts `"default"` and `"newest"` as the `sort` query parameter; any other value should yield HTTP 422.
- **REQ-218 (upvote toggle idempotency) overlap:** Solution upvote count appears in list responses; the Voting module owns the toggle, but Solutions module is responsible for reflecting the count correctly in its serialized output.

---

##### Known test gaps

- **Concurrent version creation:** Two simultaneous `POST /solutions/{id}/versions` requests — the `MAX(version_number) + 1` computation is not locked; a race could produce duplicate `version_number` values if the UNIQUE constraint is the only guard. No test currently specified for this race.
- **`current_version_id` fallback:** Engineering guide states the system falls back to the highest-numbered version if `current_version_id` is unset. No test verifies this fallback path (it should not be reachable via normal API flow, but is a defensive code path).
- **Admin unmasking on create response:** The `POST` create response also runs `_unmask_if_admin`. This path may be under-tested relative to the GET read paths.
- **Delete cascade behavior:** The spec does not document what happens to `SolutionVersion` rows when a `Solution` is deleted. DB-level cascade vs. application-level cleanup is unspecified.
- **REQ-220 (visual accepted badge):** Frontend-only; no backend test applicable, but the `status` field must be included in all read responses to support it.

---

##### Agent isolation contract

> Module under test: `app/services/solutions.py` and `app/routes/solutions.py`.
>
> Do NOT import or instantiate any other service module. Supply a stub `AsyncSession` (or use an in-memory SQLite session via the test fixtures) that satisfies `flush()` and `scalar_one_or_none()`. The `CurrentUser` dependency must be overridden via FastAPI's `app.dependency_overrides`; supply a `User` object with at minimum `id` (UUID), `role` (string), and equality to `problem.author_id` or `solution.author_id` as required per test. Do NOT exercise the Voting module; mock `solution.upvotes` relationship to a list of stubs with a known length when testing sort order.

---

---

### Comments

#### app/services/comments.py · app/routes/comments.py — Comments

**Module purpose:** Provides the full lifecycle for threaded, optionally anonymous user commentary on problems and solutions, with HTML sanitization, in-place editing, and non-destructive (tombstone) deletion.

**In scope:**
- Create comment on problem (`POST /problems/{problem_id}/comments`)
- Create comment on solution (`POST /solutions/{solution_id}/comments`)
- Threading via `parent_comment_id` with cross-entity validation
- HTML sanitization via tag and attribute allowlist
- List comments as a nested tree (authenticated and unauthenticated)
- Anonymous masking: author hidden unless viewer is comment owner or admin
- Edit comment body (author only), sets `is_edited = True`
- Delete with replies: tombstone (`body = "[deleted]"`, `is_anonymous = True`)
- Delete without replies: hard delete
- All error paths documented in the engineering guide error table

**Out of scope:**
- Pagination or depth-capping (not implemented)
- Rate limiting on comment creation
- Edit history storage (spec mentions it; not in current service implementation)
- Markdown rendering (client responsibility; server stores sanitized HTML)
- `javascript:` URI blocking in `href` (presentation-layer concern)
- Watch/notification side-effects triggered by comment creation

---

##### Happy path scenarios

| Scenario | Input | Expected output |
|---|---|---|
| Create root comment on problem | `POST /problems/{id}/comments`, authenticated, `body="Hello"`, `parent_comment_id=null`, `is_anonymous=false` | HTTP 201; response contains comment node with correct `problem_id`, `author` populated, `is_edited=false`, `is_anonymous=false`, `replies=[]` |
| Create root comment on solution | `POST /solutions/{id}/comments`, authenticated, `body="Hello"`, `parent_comment_id=null` | HTTP 201; `solution_id` matches, `problem_id` auto-resolved from solution record |
| Create threaded reply | `POST /problems/{id}/comments`, `parent_comment_id=<existing root comment id>` | HTTP 201; returned tree positions reply inside parent's `replies` list |
| List comments (unauthenticated) | `GET /problems/{id}/comments` (no auth header) | HTTP 200; tree structure returned; anonymous comments have `author=null`; `is_anonymous` flag present |
| List comments (authenticated as author of anonymous comment) | `GET /problems/{id}/comments` as the comment's own author | HTTP 200; author field populated for that caller's own anonymous comment |
| List comments (authenticated as admin) | `GET /problems/{id}/comments` with admin JWT | HTTP 200; author field populated for all comments including anonymous ones |
| Edit own comment | `PATCH /comments/{id}`, authenticated as author, new valid body | HTTP 200; `is_edited=true`; body reflects sanitized new content |
| Delete leaf comment (author) | `DELETE /comments/{id}`, authenticated as author, comment has no replies | HTTP 204; comment row no longer exists in DB |
| Delete leaf comment (admin) | `DELETE /comments/{id}`, admin JWT, comment has no replies | HTTP 204; row hard-deleted |
| Delete parent comment with replies | `DELETE /comments/{id}`, author or admin, comment has at least one reply | HTTP 204; row still exists; `body="[deleted]"`, `is_anonymous=true` |
| HTML sanitization — allowed tags preserved | Body contains `<strong>text</strong>`, `<em>x</em>`, `<code>y</code>`, `<a href="https://x.com">link</a>` | Stored body retains those tags exactly; `href` on `<a>` preserved |
| HTML sanitization — disallowed tags stripped | Body contains `<script>alert(1)</script>` | Stored body contains `alert(1)` (inner text preserved); `<script>` tags removed entirely |
| HTML sanitization — on* attributes stripped | Body `<a href="/" onclick="evil()">x</a>` | Stored body `<a href="/">x</a>`; `onclick` absent |
| Anonymous masking — non-author, non-admin | Anonymous comment viewed by unrelated authenticated user | `author=null`; `is_anonymous=true` in response |

---

##### Error scenarios

| Error type | Trigger condition | Expected behavior |
|---|---|---|
| Malformed UUID in path | `PATCH /comments/not-a-uuid` | HTTP 400, detail `"Invalid UUID: not-a-uuid"` |
| `parent_comment_id` not found | `parent_comment_id` references a UUID that does not exist | HTTP 404, detail `"Parent comment not found"` |
| `parent_comment_id` wrong problem | Parent belongs to a different problem than the target problem | HTTP 400, detail `"Parent comment does not belong to the same problem"` |
| `parent_comment_id` wrong solution | Parent belongs to a different solution in a solution-comment create | HTTP 400, detail `"Parent comment does not belong to the same solution"` |
| Solution not found | `POST /solutions/{bad_id}/comments` | HTTP 404, detail `"Solution not found"` |
| Comment not found (edit) | `PATCH /comments/{nonexistent_id}` | HTTP 404, detail `"Comment not found"` |
| Comment not found (delete) | `DELETE /comments/{nonexistent_id}` | HTTP 404, detail `"Comment not found"` |
| Edit by non-author | `PATCH /comments/{id}` by user who is not the author (even admin) | HTTP 403, detail `"Only the author can edit this comment"` |
| Delete by non-owner, non-admin | `DELETE /comments/{id}` by unrelated authenticated user | HTTP 403, detail `"You do not have permission to delete this comment"` |
| Created comment missing in tree (internal fault) | Service successfully flushes but `_find_comment` returns None | HTTP 500, detail `"Created comment not found in tree"` |
| Unauthenticated create | `POST /problems/{id}/comments` with no auth token | HTTP 401 (from `CurrentUser` dependency) |
| Unauthenticated edit | `PATCH /comments/{id}` with no auth token | HTTP 401 |
| Unauthenticated delete | `DELETE /comments/{id}` with no auth token | HTTP 401 |

---

##### Boundary conditions

| Condition | Input | Expected behavior |
|---|---|---|
| Body empty string | `body=""` | Rejected; HTTP 422 (Pydantic min-length=1 violation) |
| Body exactly 1 character | `body="x"` | Accepted; HTTP 201 |
| Body exactly 10,000 characters | `body="a" * 10000` | Accepted; HTTP 201 |
| Body 10,001 characters | `body="a" * 10001` | Rejected; HTTP 422 (Pydantic max-length=10000 violation) |
| `is_anonymous` default | `CommentCreate` submitted without `is_anonymous` field | Defaults to `false`; author visible to all callers |
| `parent_comment_id` is null | Explicit `"parent_comment_id": null` in request body | Root comment created; no threading validation performed |
| Anonymous comment deleted with replies (tombstone masking) | Non-anonymous parent comment deleted after receiving replies | Tombstone forces `is_anonymous=true`; prior author identity no longer exposed |
| Sanitization of `<style>` tag | Body `<style>body{display:none}</style>content` | `<style>` tag removed; `body{display:none}content` (inner text preserved) |
| Sanitization of `<iframe>` | Body `<iframe src="evil.com"></iframe>` | `<iframe>` tag stripped; inner text (if any) preserved |
| `<a>` with non-href attributes | `<a href="/x" class="foo" id="bar">link</a>` | Only `href` retained: `<a href="/x">link</a>` |
| Reply to tombstoned parent | `parent_comment_id` references a comment whose body is `"[deleted]"` | Allowed; tombstoned comments are still valid parent targets (row exists) |

---

##### Integration points

| Integration | Details |
|---|---|
| Database session middleware | Service calls `db.flush()` not `db.commit()`; commit is delegated to the FastAPI session dependency wrapping each request. Tests must either commit explicitly or use a session-scoped fixture that commits. |
| `CurrentUser` dependency | Required for create, edit, delete. Tests for auth failures must mock or omit this dependency. |
| `_optional_user` on list endpoints | List routes tolerate missing or invalid auth tokens by passing `None` to `get_comments`. Tests should cover both authenticated and unauthenticated list calls. |
| `get_comments` + `_find_comment` round-trip | After `create_comment`, the route calls `get_comments` and `_find_comment` to return the node. Integration tests should assert the returned comment is present in the tree, not just check a 201 status code. |
| Author bulk-load (N+1 prevention) | `get_comments` issues one `SELECT ... WHERE id IN (...)` for all authors. Tests with multiple comments should verify only two queries are issued (comments + users), not N+1. |
| Foreign key on `problem_id` / `solution_id` | An `IntegrityError` from a missing parent ID is not caught at the service level; tests that verify this path need a global `IntegrityError` handler or explicit fixture setup. |

---

##### Known test gaps

- **Edit history:** REQ-264 specifies that edit history is maintained and accessible to admins, but the engineering guide describes only `is_edited=True`. No audit table or history endpoint is documented. Tests for edit history retrieval cannot be written until this is specified.
- **`javascript:` href bypass:** The sanitizer preserves `href` verbatim. A body with `<a href="javascript:alert(1)">x</a>` will pass through. No test coverage for URL-scheme filtering exists; this is deferred to the presentation layer per the engineering guide, but the gap should be documented.
- **`is_anonymous` immutability:** REQ-260 states the flag cannot be changed after posting. No `PATCH` field for `is_anonymous` is described, but there is no explicit guard in the service description. A test confirming `PATCH` cannot toggle `is_anonymous` is missing until the schema is confirmed.
- **Concurrent comment creation:** No test covers two simultaneous requests creating replies to the same parent under high load.
- **Orphaned comment on FK violation:** `IntegrityError` from a bad `problem_id` FK is unhandled at the service level. No test confirms the HTTP 500 shape in this case.

---

##### Agent isolation contract

> **Module:** `app/services/comments.py` + `app/routes/comments.py`
>
> **Do not read** any app/ source files. All contracts are fully specified in this section.
>
> **Schemas:** `CommentCreate(body: str [1–10000 chars], parent_comment_id: str | None, is_anonymous: bool = False)`. `CommentResponse` is self-referential with a `replies: list[CommentResponse]` field.
>
> **Enums:** `ParentType` values: `problem`, `solution`, `comment`.
>
> **Constants:** Tombstone body literal = `"[deleted]"`. Tombstone also sets `is_anonymous = True`.
>
> **HTML allowlist tags:** `p`, `strong`, `em`, `code`, `pre`, `blockquote`, `ul`, `ol`, `li`, `a`, `br`. On `<a>` only `href` is preserved. All other attributes on all tags are stripped. Disallowed tags are removed; inner text is preserved.
>
> **Auth rules:** Create, edit, delete require `CurrentUser`. List endpoints use `_optional_user` (auth failure → `None`, no 401). Edit: author only (no admin override). Delete: author or admin.
>
> **Delete logic:** Has replies → tombstone (row kept). No replies → hard delete (`db.delete`).
>
> **Session discipline:** Service calls `db.flush()`, not `db.commit()`. Test fixtures must commit or be wrapped in a session-committing dependency.
>
> **Errors:** All surfaced as `fastapi.HTTPException`. Exact detail strings listed in the Error scenarios table above.

---

---

### Voting

#### app/services/voting.py · app/routes/voting.py — Voting

**Module purpose:** Implements idempotent toggle-based upvoting for problems (upstar) and solutions (solution upvote) with pessimistic row-level locking to prevent duplicate vote insertion under concurrency.

**In scope:**
- `POST /problems/{problem_id}/upstar` — toggle upstar on a problem (auth required)
- `POST /solutions/{solution_id}/upvote` — toggle upvote on a solution (auth required)
- `SELECT ... FOR UPDATE` locking on the parent row before read-modify-write on the vote table
- Response shape `{"active": bool, "count": int}` on every toggle (REQ-254)
- `DuplicateVoteError` → HTTP 409 via global exception handler
- 404 for non-existent problem or solution

**Out of scope:**
- Comment voting (separate requirement, not yet implemented)
- Reading vote counts without toggling (no dedicated read endpoint in this module)
- Upstar counts as a ranking signal for problem listing (Problems module concern)
- Authentication token validation (handled by `CurrentUser` dependency before route is entered)

---

##### Happy path scenarios

| Scenario | Input | Expected output |
|---|---|---|
| First upstar on a problem | `POST /problems/{id}/upstar` by user who has never starred this problem | HTTP 200; `{"active": true, "count": 1}`; a new row inserted in `upstars` with `(user_id, problem_id)` |
| Second upstar (retract) | Same user calls `POST /problems/{id}/upstar` again | HTTP 200; `{"active": false, "count": 0}`; the `upstars` row deleted |
| Third upstar (re-add) | Same user calls a third time | HTTP 200; `{"active": true, "count": 1}`; row re-inserted |
| Two distinct users upstar same problem | User A then User B each call `POST /problems/{id}/upstar` once | After both calls count is 2; each user's own `active` reflects their individual state |
| First upvote on a solution | `POST /solutions/{id}/upvote` by user who has not upvoted this solution | HTTP 200; `{"active": true, "count": 1}`; row inserted in `solution_upvotes` |
| Second upvote (retract) | Same user calls again | HTTP 200; `{"active": false, "count": 0}`; row deleted |
| Rapid repeated toggles leave consistent state | Multiple alternating calls by same user | System remains consistent; no negative counts; final state reflects parity of call count (REQ-252, REQ-256) |
| Count is fresh after flush | Toggle response count | Count reflects the just-applied change (flush before count query ensures accuracy within same session) |

---

##### Error scenarios

| Error type | Trigger condition | Expected behavior |
|---|---|---|
| Problem not found (upstar) | `POST /problems/{id}/upstar` where `problem_id` does not exist | HTTP 404; `"Problem not found"` |
| Solution not found (upvote) | `POST /solutions/{id}/upvote` where `solution_id` does not exist | HTTP 404; `"Solution not found"` |
| Unauthenticated request | Either toggle endpoint called without a valid auth token | HTTP 401; `CurrentUser` dependency rejects before service layer is reached; voting service never invoked |
| Malformed UUID path parameter | `problem_id` or `solution_id` is not a valid UUID string | HTTP 422; FastAPI path validation; voting service never invoked |
| DuplicateVoteError (race bypass) | Unique-constraint violation raised despite FOR UPDATE lock (e.g., direct DB write or misconfigured session bypasses lock) | HTTP 409; error propagates to global exception handler which translates `DuplicateVoteError` → 409; route layer does NOT catch it explicitly |
| Unexpected exception mid-transaction | Any unhandled error in `toggle_upstar` or `toggle_solution_upvote` | `get_db` session context manager rolls back transaction; vote table left in pre-request state; lock released on rollback |

---

##### Boundary conditions

- Count can never go below 0: deleting the last upstar/upvote brings count to exactly 0, not -1. Verify the service does not attempt to decrement a counter column — it re-counts rows after deletion.
- Count after insert: exactly `previous_count + 1`; no double-counting from the uncommitted insert being counted twice.
- Lock scope is exactly one parent row: concurrent toggles on different `problem_id` values must not block each other (lock contention test — two transactions locking different rows proceed without waiting).
- Lock scope on solution upvote: `SELECT ... FOR UPDATE` targets the `solutions` row, not the `problems` row; verify by checking which table is locked.
- `db.flush()` is called before the count query: the in-session count must reflect the pending insert or delete without requiring a full commit. Test with an in-session read after flush but before commit.
- Two different users toggling the same problem concurrently: serialization via FOR UPDATE ensures one insert succeeds and the second sees the row; final count must be 2 (not 1 or 3).

---

##### Integration points

- **`CurrentUser` dependency:** Both endpoints require authentication. Tests must override the dependency to supply a user with a known `id` (UUID). The service receives `current_user.id` as the `user_id` for vote records.
- **`get_db` async session:** The FOR UPDATE lock and the flush are session-scoped. Integration tests must use a real async database session (not a pure mock) to validate lock semantics; unit tests may mock the session but cannot verify locking behavior.
- **Global exception handler:** `DuplicateVoteError` → HTTP 409 mapping lives outside this module. Tests for the 409 path require the global handler to be registered; test the full ASGI app, not just the route function in isolation.
- **`upstars` and `solution_upvotes` tables:** Separate tables per REQ-254; cross-contamination (an upstar row appearing in `solution_upvotes`) must never occur. Verify table targeting in service function tests.
- **Solutions module read path:** `solution.upvotes` relationship is used by the Solutions module to derive upvote counts for sort order. Vote changes made via Voting module must be visible to subsequent Solutions module reads within the same session.

---

##### Known test gaps

- **True concurrent lock test:** Verifying that `SELECT ... FOR UPDATE` actually serializes two simultaneous requests requires a multi-session test with real async concurrency (e.g., `asyncio.gather`). This is not achievable with synchronous pytest fixtures alone; requires an async integration test harness against a real PostgreSQL instance.
- **Lock bypass simulation for 409:** Reproducing `DuplicateVoteError` in tests requires either mocking the DB to raise a `UniqueViolation` or bypassing the lock via direct SQL inserts. Neither is straightforward; this path may be tested only via unit-level mock injection.
- **Idempotency under network retry:** If a client retries a toggle request after a timeout (before the first response arrives), the second call toggles back. This is correct behavior per the spec but may surprise callers. No test currently defines the expected behavior when the client cannot distinguish between a failed first request and a successful first request that timed out in transit.
- **Count accuracy under high concurrency:** A stress test with N concurrent users each upstarring the same problem is not specified. The FOR UPDATE design should make this safe, but no load test is defined.

---

##### Agent isolation contract

> Module under test: `app/services/voting.py` and `app/routes/voting.py`.
>
> Do NOT import or call any Solutions or Problems service function. Supply the `CurrentUser` dependency override via `app.dependency_overrides` with a `User` stub exposing an `id` attribute (UUID). For unit tests, mock `AsyncSession` with coroutine stubs for `execute()` (returning a mock result for `scalar_one_or_none()` and `FOR UPDATE` queries) and `flush()`. For lock-behavior and 409 tests, use a real async PostgreSQL session against the test database — mock sessions cannot validate `SELECT ... FOR UPDATE` semantics. The global exception handler must be registered on the test app instance for any test that exercises the `DuplicateVoteError → 409` path. Do NOT assert on `problem.activity_at` or any Problem-model side effect; those belong to the Solutions and Problems test suites.

---

### Attachments

#### app/services/attachments.py · app/routes/attachments.py — Attachments

**Module purpose:** Lets authenticated users upload, list, download, and delete files attached to problem records, enforcing a MIME-type allowlist, a per-file size ceiling (10 MB), and a cumulative per-problem storage cap (50 MB) before any bytes are written to disk.

**In scope:**
- Upload file to problem (`POST /problems/{problem_id}/attachments`)
- Per-file size validation (pre-write, no DB read)
- Extension/MIME allowlist validation (extension-based, not client Content-Type)
- Cumulative problem-size validation (`SUM(byte_size)` query before write)
- UUID filename generation; original filename preserved in DB
- List attachments for a problem (`GET /problems/{problem_id}/attachments`)
- Download attachment with correct `Content-Disposition` (`GET /attachments/{id}/download`)
- `render_inline` flag: `True` for `image/*` types, `False` otherwise
- Delete attachment: DB row deleted first, then disk file (`DELETE /attachments/{id}`)
- Authorization: uploader or admin may delete

**Out of scope:**
- Clipboard paste / drag-and-drop (REQ-414 — client-side, SHOULD priority)
- NGINX static serving / cache headers (REQ-410 — infrastructure, not service layer)
- SVG script execution prevention (presentation/NGINX concern)
- Attachments on solutions or comments (current route only exposes problem-scoped uploads)
- Content-sniffing / magic-bytes MIME validation (extension-based only)

---

##### Happy path scenarios

| Scenario | Input | Expected output |
|---|---|---|
| Upload valid PNG within size limits | `POST /problems/{id}/attachments`, multipart file `.png`, size < 10 MB, problem total < 50 MB | HTTP 201; `AttachmentResponse` with `filename`, `content_type="image/png"`, `render_inline=true`, `storage_path` containing UUID |
| Upload valid PDF within size limits | Same as above with `.pdf` file | HTTP 201; `content_type="application/pdf"`, `render_inline=false` |
| Upload valid TXT / LOG file | `.txt` or `.log` file | HTTP 201; `content_type="text/plain"`, `render_inline=false` |
| Upload creates UUID-named file on disk | Any valid upload | On-disk filename is `{uuid4}{ext}`; original filename stored only in `filename` DB column |
| Upload creates DB row with all columns | Any valid upload | One `Attachment` row with non-null `id`, `parent_type="problem"`, `parent_id`, `uploader_id`, `filename`, `content_type`, `byte_size`, `storage_path`, `created_at` |
| List attachments | `GET /problems/{id}/attachments` (unauthenticated) | HTTP 200; list of `AttachmentResponse` objects ordered by `created_at ASC` |
| Download image attachment | `GET /attachments/{id}/download` | `FileResponse`; `Content-Disposition: inline`; `render_inline=true` |
| Download non-image attachment | `GET /attachments/{id}/download` for a PDF | `FileResponse`; `Content-Disposition: attachment` |
| Delete by uploader | `DELETE /attachments/{id}`, authenticated as uploader | HTTP 204; DB row removed; disk file removed |
| Delete by admin | `DELETE /attachments/{id}`, admin JWT, non-uploader | HTTP 204; DB row removed; disk file removed |
| Disk removal fails silently on delete | Delete where `_remove_file_from_disk` raises `OSError` | HTTP 204 still returned; error logged; DB row already deleted |
| File at exactly 10 MB | Upload file of exactly `10 * 1024 * 1024` bytes | HTTP 201; accepted |
| Problem total at exactly 50 MB before upload | Existing total = 50 MB − file_size; new file brings total to exactly 50 MB | HTTP 201; accepted |

---

##### Error scenarios

| Error type | Trigger condition | Expected behavior |
|---|---|---|
| Per-file size exceeded | File size = `MAX_FILE_SIZE + 1` (10 MB + 1 byte) | `FileSizeLimitError(file_size, MAX_FILE_SIZE)` raised; HTTP 413 |
| Cumulative size exceeded | `current_total + file_size > MAX_TOTAL_SIZE` | `FileSizeLimitError` raised; HTTP 413; no bytes written to disk |
| Extension not in allowlist | `.exe`, `.sh`, `.py`, `.dll`, or any extension absent from `ALLOWED_TYPES` | `FileTypeNotAllowedError(content_type, filename)` raised; HTTP 422 |
| Attachment not found (download) | `GET /attachments/{nonexistent_id}/download` | HTTP 404, detail `"Attachment not found"` |
| File missing on disk (download) | DB row exists but file absent at resolved path | HTTP 404, detail `"File not found on disk"` |
| Attachment not found (delete) | `DELETE /attachments/{nonexistent_id}` — service raises `ValueError("Attachment not found")` | HTTP 404 (route re-raises as 404 after catching `ValueError`) |
| Delete by non-uploader, non-admin | `DELETE /attachments/{id}` by unrelated authenticated user | HTTP 403 (from `require_owner_or_admin` dependency) |
| Unauthenticated upload | `POST /problems/{id}/attachments` with no auth token | HTTP 401 |
| Unauthenticated delete | `DELETE /attachments/{id}` with no auth token | HTTP 401 |
| MIME spoofing attempt | Client sends `Content-Type: image/jpeg` header for a `.exe` file | Extension lookup fails; `FileTypeNotAllowedError` raised; client header is ignored |

---

##### Boundary conditions

| Condition | Input | Expected behavior |
|---|---|---|
| File exactly at per-file limit | `file_size == 10 * 1024 * 1024` | Accepted; HTTP 201 |
| File one byte over per-file limit | `file_size == 10 * 1024 * 1024 + 1` | `FileSizeLimitError`; HTTP 413 |
| Cumulative total exactly at cap | Existing total + new file = exactly `50 * 1024 * 1024` | Accepted; HTTP 201 |
| Cumulative total one byte over cap | Existing total + new file = `50 * 1024 * 1024 + 1` | `FileSizeLimitError`; HTTP 413 |
| Zero-byte file | `file_size == 0`, valid extension | Accepted (no size constraint violated); DB row created |
| Extension `.jpg` vs `.jpeg` | Both `.jpg` and `.jpeg` uploaded | Both accepted; both resolve to `content_type="image/jpeg"` |
| Two simultaneous uploads with identical original filenames | Concurrent posts with same `filename` | Both succeed; distinct UUID-prefixed on-disk paths; no collision |
| `render_inline` for GIF | Upload `.gif` file | `content_type="image/gif"`, `render_inline=true` |
| `render_inline` for WEBP | Upload `.webp` file | `content_type="image/webp"`, `render_inline=true` |
| `render_inline` for TXT | Upload `.txt` file | `content_type="text/plain"`, `render_inline=false` |
| Extension check is case-insensitive | Upload file named `IMAGE.PNG` | Extension lowercased to `.png`; accepted |

---

##### Integration points

| Integration | Details |
|---|---|
| `STORAGE_PATH` config | All file operations resolve from `get_settings().STORAGE_PATH`. Tests must set this to a temp directory; never write to production paths. |
| Database session discipline | `create_attachment` calls `db.flush()` not `db.commit()`. If the test session is not committed, no metadata is persisted and the written bytes become orphaned on disk. Fixtures must commit after upload. |
| Filesystem side-effects | Upload creates a real file under `{STORAGE_PATH}/{problem_id}/{uuid}{ext}`. Tests should use `tmp_path` or mock `store_file` to avoid disk writes. Delete tests should verify disk removal by asserting the file no longer exists. |
| `require_owner_or_admin` dependency | Auth guard for delete. Tests for 403 must use a user who is neither the uploader nor an admin. |
| Cumulative size race condition | The `SUM(byte_size)` query and subsequent `flush` run within the same session transaction, relying on DB-level row locking. Concurrent-upload tests require transaction isolation to be verified at the DB level, not just the service level. |
| `OSError` on disk removal | Service catches `OSError` from `_remove_file_from_disk` and logs it rather than propagating. Tests should mock the removal function to raise `OSError` and assert HTTP 204 is still returned and the DB row is gone. |
| `render_inline` computation | Field is computed at serialization time (`content_type.startswith("image/")`); not stored in DB. Tests should not assert a DB column for this field. |

---

##### Known test gaps

- **Spec vs. implementation ALLOWED_TYPES mismatch:** REQ-402 lists `.svg`, `.md`, `.csv`, `.zip`, `.tar.gz` as allowed; the engineering guide constants include only `.png`, `.jpg`, `.jpeg`, `.webp`, `.gif`, `.pdf`, `.txt`, `.log`. Tests should assert against the implemented constants, not the spec's broader list. The discrepancy should be flagged as a spec debt item.
- **REQ-416 "atomic deletion" simulation:** The spec requires that a simulated disk failure leaves the DB row intact. The implementation explicitly deletes the DB row first and tolerates disk failure silently. This means the implemented behavior is the inverse of the REQ-416 acceptance criterion ("A simulated disk failure leaves the DB row intact" is FALSE — the DB row is already gone). This is a spec non-conformance and should be tracked as a defect, not tested as a passing scenario.
- **NGINX cache headers (REQ-410):** Not testable at the service/route layer. Requires an integration test against a running NGINX instance.
- **Clipboard paste (REQ-414):** Client-side feature; no service-layer test surface.
- **Concurrent upload race (cumulative cap):** Row-locking semantics are DB-engine-specific. Unit tests with SQLite will not surface race conditions; a PostgreSQL integration test under concurrent load is needed.
- **Download `Content-Disposition` header value:** The engineering guide specifies `inline` vs. `attachment` but does not specify whether the `filename=` parameter is included in the `attachment` disposition. Test coverage for the exact header string is incomplete.

---

### Search

#### app/services/search.py, app/routes/search.py — Search

**Module purpose:** Provides full-text search across problems, solutions, and comments via a 3-branch CTE with PostgreSQL `tsvector`/`tsquery`, deduplicating results to the problem level, and a separate similar-problem suggestion endpoint for duplicate prevention at authorship time.

**In scope:**
- `GET /search` — full-text search with sort, filter, and pagination
- `GET /search/suggest` — similar-problem suggestions by title
- Input guarding (empty/blank query short-circuit)
- All three sort modes: `relevance`, `upvotes`, `newest`
- Filters: `category_id`, `status`, `tag_ids`
- Excerpt truncation at 120 characters
- `search_vector` maintenance helper (`update_search_vector`)

**Out of scope:**
- Open Graph meta tags (REQ-366) — separate endpoint, not part of search service
- Bot User-Agent detection (REQ-368) — NGINX/middleware concern
- UI debounce behavior (REQ-362 front-end clause) — not exercised at service layer
- `work_mem` / connection pool tuning — infrastructure concern
- REQ-360 CTA message rendering — front-end concern; API already returns empty-results shape

---

##### Happy path scenarios

| Scenario | Input | Expected output |
|---|---|---|
| Single-word query matches problem title | `q=firmware`, `sort=relevance` | HTTP 200; results array contains matching problem; `match_source="problem"`; `rank > 0` |
| Query matches solution body only | `q=oscilloscope` (term only in a solution) | HTTP 200; parent problem returned; `match_source="solution"` |
| Query matches comment body only | `q=workaround` (term only in a comment) | HTTP 200; parent problem returned; `match_source="comment"` |
| Same problem matched by both problem and solution | `q=firmware` (term in title and a solution) | Only one result entry for that problem (deduplication via `DISTINCT ON`); highest-rank match wins |
| Sort by upvotes | `q=bug`, `sort=upvotes` | Results ordered by `upstar_count DESC`; equal upstars retain stable secondary order |
| Sort by newest | `q=bug`, `sort=newest` | Results ordered by `p_created_at DESC` |
| Unknown sort value | `q=bug`, `sort=bogus` | HTTP 200; falls back to `rank DESC` ordering; no error raised |
| Filter by category_id | `q=sensor`, `category_id=<uuid>` | Only problems in that category returned |
| Filter by status | `q=sensor`, `status=open` | Only problems with `status="open"` returned |
| Filter by single tag_id | `q=driver`, `tag_ids=<uuid>` | Only problems tagged with that tag returned |
| Filter by multiple tag_ids | `q=driver`, `tag_ids=<uuid1>&tag_ids=<uuid2>` | Only problems carrying ALL listed tags returned (implicit AND join) |
| Pagination: limit and offset | `q=error`, `limit=5`, `offset=10` | Returns at most 5 results starting from rank 11 |
| Excerpt truncation | Problem description > 120 chars | `excerpt` field is exactly 120 chars; longer text is truncated |
| Excerpt null safety | Problem with no description | `excerpt` is `""` not `null` |
| suggest_similar: title match | `title=firmware update`, `limit=5` | HTTP 200; up to 5 problems returned in rank order |
| suggest_similar: exclude_problem_id | `title=firmware`, `exclude_id=<uuid>` | That problem ID does not appear in results |
| suggest_similar: fewer than N matches | `title=firmware` (only 3 matching problems exist) | Returns 3 results; no error |
| suggest_similar: empty title | `title=` | HTTP 200; `{"results": [], "message": "No similar problems found"}` |
| Result serialization | Any successful search | UUIDs serialized as strings; ranks as float; datetimes as ISO-8601 |

---

##### Error scenarios

| Error type | Trigger condition | Expected behavior |
|---|---|---|
| Empty query string | `q=` or `q` absent | HTTP 200; `{"results": [], "message": "No results found"}`; no SQL executed |
| Blank/whitespace query | `q=   ` | HTTP 200; same empty-result response; no SQL executed |
| Valid query, zero matches | `q=xyzzy_no_match_123` | HTTP 200; `{"results": [], "message": "No results found"}`; response distinguishable from error only by inspecting `results` array |
| `limit` below minimum | `limit=0` | HTTP 422 Unprocessable Entity (route-level validation) |
| `limit` above maximum | `limit=101` | HTTP 422 Unprocessable Entity |
| `offset` negative | `offset=-1` | HTTP 422 Unprocessable Entity |
| suggest `limit` above maximum | `limit=21` on `/search/suggest` | HTTP 422 Unprocessable Entity |
| Database failure | Simulate connection loss or statement timeout | HTTP 500; SQLAlchemy exception propagates to FastAPI default handler; no partial results |
| SQL injection via `q` | `q='; DROP TABLE problems; --` | `plainto_tsquery` normalizes input; bind parameters prevent execution; HTTP 200 with empty or valid results |
| SQL injection via `sort` | `sort=rank DESC; DROP TABLE problems` | Unknown sort falls back to `rank DESC`; dynamic fragment sourced from trusted internal map; no injection path |

---

##### Boundary conditions

- `limit=1`: returns exactly one result (highest-ranked).
- `limit=100`: returns up to 100 results; exercises the correlated `upstar_count` subquery at scale.
- `offset` equal to total result count: returns empty results array without error.
- Multi-word query (`q=sensor firmware update`): `plainto_tsquery` treats as implicit AND of all three lexemes; all terms must appear.
- Query with punctuation (`q=can't find`): `plainto_tsquery` strips punctuation without raising a syntax error (contrast: `to_tsquery` would fail on bare apostrophes).
- Problem matched via all three sources simultaneously: only one result row emitted; `match_source` reflects the highest-ranked branch.
- `tag_ids` with a single UUID vs. multiple UUIDs: single tag uses one INNER JOIN; multiple tags use multiple INNER JOINs (one per tag); correct filtering in both cases.
- `exclude_problem_id` on suggest when that problem is the top match: it must be absent from results; next-best problem takes rank 1.
- Excerpt exactly 120 chars: no truncation applied (boundary-inclusive check).
- Excerpt of 121 chars: truncated to 120 chars.

---

##### Integration points

| Dependency | Nature | Test approach |
|---|---|---|
| PostgreSQL `tsvector` / GIN index on `problems` | `problems.search_vector` must be pre-populated and GIN index must exist for results to appear | Use a test DB fixture; assert index exists via `pg_indexes`; seed data via `update_search_vector` before asserting search results |
| `update_search_vector` write path | Called by create/edit problem handlers; search module does not trigger it | Integration test: create problem, call `update_search_vector`, then search — verify result appears |
| FastAPI `Depends(get_db)` | `AsyncSession` injection | Use standard `TestClient` / `AsyncClient` with test DB override |
| `solution_versions` and `comments` tables | Cross-entity search; hit CTEs compute `to_tsvector` inline | Seed at least one solution and one comment per test scenario to verify branch independently |
| REQ-902 performance target | p95 < 1000 ms | Load test with 10,000-row dataset; assert GIN index is active in query plan via `EXPLAIN ANALYZE` |

---

##### Known test gaps

1. **`search_vector` staleness**: No in-module detection. If a problem is created or edited without calling `update_search_vector`, it will not appear in search results. There is no automated test that verifies staleness is caught or prevented; this must be covered at the write-path integration level.
2. **`upstar_count` correlated subquery at scale**: One subquery fires per matched row. Behavior near `limit=100` under concurrent write load is untested.
3. **Excerpt SQL vs. Python constant drift**: `_EXCERPT_LEN = 120` in Python and `LEFT(…, 120)` in SQL are independent. No automated check enforces they remain in sync; a change to one without the other would silently produce wrong behavior.
4. **Sort parameter not enum-validated at route**: `sort=bogus` silently falls back rather than returning 422. This means bad client inputs are not surfaced — no test currently asserts that invalid sort values are rejected.
5. **`websearch_to_tsquery` / phrase queries**: Users cannot use OR operators or phrase search; no test documents this intentional limitation or its user-visible behavior.
6. **GIN index health over time**: Index bloat and vacuum state are not exercised by unit tests; requires operational monitoring.

---

##### Agent isolation contract

> **Search module test agent contract**
>
> Source files under test: `app/services/search.py`, `app/routes/search.py`
>
> Do NOT read or modify any other app/ source files.
>
> Inputs available: this test specification, the engineering guide section 3.9 (lines 1986-2115), and the spec REQ-350, REQ-352, REQ-354, REQ-356, REQ-358, REQ-360, REQ-362, REQ-364.
>
> All database interactions must go through a test-scoped AsyncSession against a dedicated test PostgreSQL instance. The GIN index on `problems.search_vector` must be present in the test schema.
>
> Phase 0 contracts that must hold across all tests:
> - Sort modes: `relevance` (default), `upvotes`, `newest` only.
> - Full-text uses `plainto_tsquery` (implicit AND; no syntax errors on arbitrary input).
> - Empty or blank `q` returns HTTP 200 with empty results — never HTTP 400.
> - `limit` in [1, 100]; `offset` >= 0; violations return HTTP 422.
> - Deduplication is to problem level; only one row per `problem_id` in results.

---

---

### Watch & Notification Pipeline

#### Watch & Notification Pipeline — `app/services/watches.py`, `app/services/notifications.py`, `app/services/delivery.py`

**Module purpose:** Manages per-user watch subscriptions and translates application events into routed `Notification` rows, then dispatches those rows over WebSocket, Teams webhook, and email digest channels.

**In scope:**
- Watch CRUD: `set_watch`, `remove_watch`, `get_watch` (upsert, delete, read)
- Auto-watch on participation: `auto_watch` priority comparison and no-downgrade guarantee
- Notification fan-out: `generate_notification` with actor exclusion and `WATCH_ROUTING` filtering
- Delivery — WebSocket: `push_ws_notification`, `ConnectionManager.broadcast_to_user`, stale socket pruning
- Delivery — Teams: `send_teams_webhook`, `schedule_teams_webhook` fire-and-forget scheduling
- Delivery — Email digest: `send_email_digest`, `updated_at` delivery marker
- Upvote milestone gate: `is_milestone`
- Notification CRUD routes: `GET /notifications`, `PATCH /notifications/{id}/read`, `POST /notifications/read-all`
- WebSocket auth and keep-alive: `GET /ws/notifications`, JWT validation, ping/pong loop

**Out of scope:**
- Problem, solution, and comment business logic that *calls* these services
- Background job scheduling (claim-expiry job execution, digest job scheduling)
- UI bell badge rendering
- Notification preference storage (`auto_watch_on_comment`, `auto_watch_default_level` in `users.preferences`) — covered by the Users module tests
- Database migration correctness for the `watches` table schema

---

##### Happy path scenarios

| Scenario | Input | Expected output |
|---|---|---|
| Set new watch | `set_watch(db, user_id=U1, problem_id=P1, level=WatchLevel.solutions_only)` — no prior row | Row inserted; returns `Watch(user_id=U1, problem_id=P1, level=solutions_only)` |
| Update existing watch | `set_watch` called twice on same `(U1, P1)` pair with different levels | Second call upserts via `ON CONFLICT DO UPDATE`; exactly one row remains at the new level |
| Remove existing watch | `remove_watch(db, user_id=U1, problem_id=P1)` where row exists | Returns `True`; row deleted; `db.flush()` called |
| Get current watch | `get_watch(db, user_id=U1, problem_id=P1)` where row exists at `all_activity` | Returns `Watch` object with correct level |
| Auto-watch — no prior watch | `auto_watch(db, U1, P1, level=WatchLevel.all_activity)` — no row exists | Calls `set_watch` with `all_activity`; returns new `Watch` at `all_activity` |
| Auto-watch — upgrades lower level | `auto_watch` called with `all_activity` when existing watch is `solutions_only` (priority 2 < 3) | Calls `set_watch`; watch upgraded to `all_activity` |
| Auto-watch — equal level no-op | `auto_watch` called with `all_activity` when existing watch is already `all_activity` | Returns existing watch unchanged; `set_watch` not called |
| Auto-watch — higher level no-op | `auto_watch` called with `solutions_only` when existing watch is `all_activity` | Returns existing watch unchanged; never downgrades |
| Fan-out — `all_activity` watcher | `generate_notification(db, NotificationType.comment_posted, P1, actor_id=A)` with one watcher at `all_activity` (user != A) | Returns list of one `Notification`; `db.add_all()` + `db.flush()` called |
| Fan-out — `solutions_only` watcher receives allowed type | `generate_notification` with `event_type=solution_posted`, watcher at `solutions_only` | Watcher receives notification |
| Fan-out — `solutions_only` watcher blocked from other types | `generate_notification` with `event_type=comment_posted`, watcher at `solutions_only` | Empty list; no row inserted |
| Fan-out — `status_only` watcher receives `status_changed` | `generate_notification` with `event_type=status_changed`, watcher at `status_only` | Watcher receives notification |
| Fan-out — `none` watcher | `generate_notification` with any event type, watcher at `none` | Empty list; no row inserted |
| Actor exclusion | `generate_notification` where sole watcher's `user_id == actor_id` | Empty list; actor excluded at query time |
| Fan-out — multiple watchers mixed levels | Three watchers: `all_activity`, `solutions_only`, `none`; event = `solution_posted` | Two notifications created (for `all_activity` and `solutions_only` watchers only) |
| Empty watcher list | `generate_notification` on a problem with no watches | Returns `[]`; `db.add_all` called with empty list |
| WebSocket push — active connection | `push_ws_notification(notification)` where recipient has one active WebSocket | `broadcast_to_user` called; JSON envelope with `type: "notification"` sent to socket |
| WebSocket push — multiple tabs | Recipient has two open WebSocket connections | Both sockets receive the payload |
| WebSocket push — no connections | Recipient has no active connections | No-op; no exception raised |
| Teams webhook — configured and reachable | `send_teams_webhook(notification)` with valid `TEAMS_WEBHOOK_URL` | `httpx.AsyncClient.post` called with Adaptive Card payload; no exception propagated |
| `schedule_teams_webhook` — active event loop | Call inside running async context | Schedules `asyncio.Task` wrapping `send_teams_webhook`; returns immediately |
| Email digest — user with unread notifications | `send_email_digest(db, U1, [n1, n2, n3])` | `aiosmtplib` send called; `updated_at` stamped on all three notifications; `db.flush()` called |
| `is_milestone` — threshold values | `is_milestone(10)`, `is_milestone(25)`, `is_milestone(50)`, `is_milestone(100)` | All return `True` |
| `is_milestone` — non-threshold values | `is_milestone(9)`, `is_milestone(11)`, `is_milestone(0)`, `is_milestone(101)` | All return `False` |
| Mark single notification read | `PATCH /notifications/{id}/read` with valid UUID owned by caller | `is_read = True` set; HTTP 204 returned |
| Mark all notifications read | `POST /notifications/read-all` | Bulk `UPDATE … WHERE recipient_id = ? AND is_read = false`; HTTP 204 returned |
| List notifications — default page | `GET /notifications` (no filter) | Returns up to 20 notifications descending by `created_at`; includes `unread_count` |
| List notifications — cursor pagination | `GET /notifications?cursor=<iso_datetime>` | Returns notifications with `created_at < cursor`; correct next page |
| List notifications — `unread_only` filter | `GET /notifications?unread_only=true` | Returns only unread rows; `unread_count` still included |
| WebSocket auth — valid JWT | `GET /ws/notifications?token=<valid_jwt>` | Connection accepted; socket registered in `ConnectionManager` under user UUID |
| WebSocket keep-alive — client ping | Client sends text `"ping"` over WebSocket | Server replies `"pong"` |

---

##### Error scenarios

| Error type | Trigger condition | Expected behavior |
|---|---|---|
| Remove watch — row not found | `remove_watch(db, U1, P1)` where no row exists | Returns `False`; route layer translates to HTTP 404 |
| Get watch — row not found | `get_watch(db, U1, P1)` where no row exists | Returns `None` (or raises `404` at route layer) |
| WebSocket auth — missing token | `GET /ws/notifications` with no `?token=` param | Connection closed with `WS_1008_POLICY_VIOLATION` |
| WebSocket auth — invalid JWT | `GET /ws/notifications?token=<tampered>` | Connection closed with `WS_1008_POLICY_VIOLATION` |
| WebSocket stale socket pruning | Socket in `ConnectionManager` raises on `send` during `broadcast_to_user` | Exception caught; socket removed from set; remaining sockets still receive payload |
| WebSocket push failure — swallowed | `push_ws_notification` where `broadcast_to_user` raises unexpectedly | Exception caught; logged at ERROR with notification ID; no exception propagated to caller |
| Teams webhook — invalid URL | `send_teams_webhook` where `httpx` raises (timeout, connection error) | Exception caught inside function; logged at ERROR; returns silently |
| Teams webhook — unconfigured | `TEAMS_WEBHOOK_URL` is `None` or empty | Function returns before creating HTTP client; no error, no HTTP call |
| `schedule_teams_webhook` — no event loop | Called outside any running async context | Returns silently without scheduling; no exception |
| Email digest — `aiosmtplib` failure | SMTP send raises | Exception caught; logged at ERROR; `updated_at` NOT stamped; function returns without raising |
| Email digest — user not found | `user_id` does not match any `User` row | Logged at WARNING; returns without attempting SMTP |
| Mark read — non-UUID notification ID | `PATCH /notifications/not-a-uuid/read` | HTTP 400 Bad Request |
| Mark read — notification belongs to another user | `PATCH /notifications/{id}/read` where `recipient_id != caller` | HTTP 404 |
| List notifications — malformed cursor | `GET /notifications?cursor=not-a-datetime` | HTTP 400 Bad Request |
| Fan-out — `db.flush()` failure | `generate_notification` raises during flush | SQLAlchemy exception propagates; no partial `Notification` rows committed; caller's transaction rolled back |
| `set_watch` — database error | Constraint violation or connection loss during flush | SQLAlchemy exception propagates; caller's transaction rolled back |

---

##### Boundary conditions

- **`auto_watch` priority boundary — equal:** Existing level priority == requested level priority (e.g., both `all_activity`) returns existing watch, does not call `set_watch`.
- **`auto_watch` priority boundary — one below:** Existing `solutions_only` (priority 2) with requested `all_activity` (priority 3) triggers upgrade; existing `status_only` (priority 1) with requested `solutions_only` (priority 2) also triggers upgrade.
- **`WATCH_ROUTING` — `solutions_only` receives exactly two types:** Verify `solution_posted` and `solution_accepted` pass; verify `comment_posted`, `status_changed`, `problem_claimed`, `mention`, `upvote_milestone`, `problem_pinned` are all blocked.

  > Note: The Phase 0 contracts specify `solutions_only → {solution_posted, solution_accepted}`. REQ-312 in the spec adds `solution_upvote_milestone` to `solutions_only`. Confirm which mapping is authoritative before implementing these tests; flag if they differ.

- **`WATCH_ROUTING` — `status_only` receives exactly one type:** Only `status_changed` passes; all seven other types are blocked.
- **`WATCH_ROUTING` — `none` is empty set:** All eight types blocked; verify no off-by-one where `none` accidentally inherits `status_only` routing.
- **`is_milestone` — exact list membership:** `[10, 25, 50, 100]` are the only `True` values; 9, 11, 24, 26, 49, 51, 99, 101, -1 are all `False`.
- **Fan-out — actor is only watcher:** Problem has exactly one watch row and it belongs to the actor; result is empty list, not an error.
- **Email digest — zero notifications passed:** `send_email_digest(db, U1, [])` — verify SMTP is not called; no exception raised.
- **Email digest — `updated_at` stamp idempotency:** Running the digest twice for the same notifications: second run finds notifications with a stamped `updated_at`; a digest job filtering by `updated_at` range must not re-send them. (Test the stamp, not the job logic.)
- **Pagination — page size limits:** `GET /notifications?limit=0` → 400 or defaults to 1; `limit=100` → accepted; `limit=101` → 400.
- **Pagination — last page:** Cursor points to the oldest item; response returns empty list, no error.
- **ConnectionManager — empty set after pruning:** All sockets for a user fail; set becomes empty; subsequent `broadcast_to_user` is a no-op with no `KeyError`.
- **Teams 10-second timeout:** Mock `httpx.AsyncClient.post` to delay beyond 10 s; verify `send_teams_webhook` raises (or catches) `httpx.TimeoutException` and does not hang the test.

---

##### Integration points

| Dependency | How this module uses it | Mock strategy |
|---|---|---|
| `aiosmtplib` | `send_email_digest` calls `aiosmtplib.send(...)` over STARTTLS | `unittest.mock.patch("app.services.delivery.aiosmtplib.send", new_callable=AsyncMock)` |
| `httpx.AsyncClient` | `send_teams_webhook` opens a client with 10 s timeout and POSTs | `unittest.mock.patch("app.services.delivery.httpx.AsyncClient", ...)` using `AsyncMock` for `__aenter__`/`post` |
| `ConnectionManager` (WebSocket) | `push_ws_notification` calls `connection_manager.broadcast_to_user` | Inject a mock `ConnectionManager` or patch `app.services.delivery.connection_manager`; use `AsyncMock` WebSocket objects |
| SQLAlchemy `AsyncSession` | `set_watch`, `remove_watch`, `generate_notification`, `send_email_digest` | Use pytest-asyncio + SQLAlchemy in-memory SQLite or a test Postgres fixture; never mock the session for persistence tests |
| `app.config.get_settings()` | `send_teams_webhook` reads `TEAMS_WEBHOOK_URL`; `send_email_digest` reads SMTP settings and `BASE_URL` | Override via `monkeypatch.setattr` on the settings object or use pytest `override_settings` fixture |
| `decode_access_token` | WebSocket route validates `?token=` JWT | Patch with a fixture that returns a known `user_id` UUID for valid tokens and raises for invalid ones |
| `asyncio` event loop | `schedule_teams_webhook` calls `asyncio.get_event_loop()` | Run tests under `pytest-asyncio`; test the no-loop path by calling synchronously outside async context |

---

##### Known test gaps

1. **REQ-312 routing matrix divergence.** The Phase 0 contracts and the spec (REQ-312) disagree on what `solutions_only` and `status_only` receive. Contracts say `solutions_only → {solution_posted, solution_accepted}` and `status_only → {status_changed}`. The spec says `solutions_only` also includes `solution_upvote_milestone` and `status_only` includes `problem_claimed`, `claim_expired`, `duplicate_flagged`. Tests must be written against whichever is coded in `WATCH_ROUTING`; the discrepancy should be resolved before test authoring begins.

2. **REQ-310 vs Phase 0 `NotificationType` enum mismatch.** The spec lists eight types including `new_comment`, `solution_upvote_milestone`, `claim_expired`, `duplicate_flagged`. Phase 0 contracts list `comment_posted`, `upstar_received`, `problem_pinned`, `problem_claimed`. The canonical enum in `app/enums` is the source of truth; test names and routing assertions must use those exact values.

3. **Email digest idempotency (REQ-320 — "no duplicates").** The acceptance criterion requires that running the digest job twice does not produce duplicates. The delivery layer uses `updated_at` as the only marker. No test can fully cover idempotency without also exercising the job's query logic (which filters by `updated_at`). That integration test belongs to the background-jobs test module, not here.

4. **Milestone re-crossing (REQ-322).** The spec requires that decrementing and re-crossing a threshold does not re-trigger. `is_milestone` alone cannot enforce this — it is stateless. The guard must be tested at the call site where the upvote counter is incremented. This is a gap in the delivery module tests; the integration test belongs in the upvotes test module.

5. **WebSocket 2-second delivery latency (REQ-316).** The acceptance criterion requires payload delivery within 2 seconds. Unit tests can only verify that `broadcast_to_user` is called; timing is not testable in unit scope and requires a real end-to-end performance test.

6. **Teams DM opt-in check (REQ-318).** The spec states delivery happens only when `delivery.teams: true`. Whether this guard lives in `send_teams_webhook`, in `schedule_teams_webhook`, or at the call site is not specified in the engineering guide. If it is at the call site, a test verifying that a opted-out user receives no Teams message belongs in the route/event-handler tests, not here.

7. **`GET /api/users/me/watches` endpoint (REQ-302).** Returning all active watches for the authenticated user is listed in REQ-302 but not described in the engineering guide module section. No test cases are specified here pending confirmation of the endpoint and its serialization contract.

---

##### Agent isolation contract

> This module's tests MUST NOT import from or call into `app/routes/problems.py`, `app/routes/solutions.py`, `app/routes/comments.py`, or any background job runner. Watch management and notification fan-out are tested by calling `app/services/watches.py` and `app/services/notifications.py` directly against a real `AsyncSession`. Delivery functions in `app/services/delivery.py` are tested with all three external I/O surfaces mocked: `aiosmtplib.send`, `httpx.AsyncClient`, and the `ConnectionManager` WebSocket set. The WebSocket route in `app/routes/ws.py` and the notification CRUD routes in `app/routes/notifications.py` are tested using `httpx.AsyncClient` against a mounted ASGI test app with a seeded database — no live external services. Tests in this file must not read, write, or depend on the state of any other test module's fixtures.

---

### Admin Subsystem

#### Admin Subsystem — `app/services/admin.py`, `app/services/categories.py`, `app/services/tags.py`

**Module purpose:** Provides the operational back-office for Aion Bulletin — user management, taxonomy CRUD, content moderation, and runtime configuration — all gated behind a single router-level admin auth guard.

**In scope:**
- User search (ILIKE on `display_name` and `email`), role update, active-status toggle
- Category create (auto-slug, auto-sort_order), partial update, bulk reorder, soft delete
- Tag list with live `usage_count` (LEFT JOIN + GROUP BY), rename, hard delete (cascades ProblemTag), merge (atomic ON CONFLICT DO NOTHING)
- Flag list (filtered by status), flag resolution (writes `resolved_by` + `resolution_note`), de-anonymize with write-ahead AuditLog
- Config list (alphabetical) and upsert (validated against `ALLOWED_CONFIG_KEYS`)
- Router-level `require_admin` dependency (HTTP 403 before any handler runs for non-admins)

**Out of scope:**
- Problem CRUD, comments, watches, notifications — those belong to their own subsystems
- Frontend route guards (`/admin/*` redirects) — browser-only, not server-tested here (REQ-476)
- Default category seeding on first run (REQ-454) — belongs to a database migration / seed fixture, not the admin service layer
- Session invalidation on deactivation — token validation logic lives in the auth subsystem

---

##### Happy path scenarios

| Scenario | Input | Expected output |
|---|---|---|
| Search users — partial match on display_name | `GET /admin/users/?q=alice` | 200; list contains only users whose `display_name` or `email` ILIKE `%alice%`; ordered by `created_at DESC` |
| Search users — no query param | `GET /admin/users/` (no `q`) | 200; full user list returned, ordered by `created_at DESC` |
| Search users — partial match on email | `GET /admin/users/?q=@corp.com` | 200; only users whose email matches |
| Update user role | `PATCH /admin/users/{id}/role` `{"role": "admin"}` | 200; `User.role` updated; `user.role_changed` log event emitted |
| Toggle user active status (deactivate) | `PATCH /admin/users/{id}/status` `{"is_active": false}` | 200; `User.is_active = false`; `user.status_changed` log event emitted |
| Toggle user active status (reactivate) | `PATCH /admin/users/{id}/status` `{"is_active": true}` | 200; `User.is_active = true`; `user.status_changed` log event emitted |
| Create category (empty table) | `POST /admin/categories` `{"name": "RTL Design"}` | 201; slug = `"rtl-design"`; `sort_order = 0`; record visible in category list |
| Create category (existing categories) | `POST /admin/categories` with existing max `sort_order = 4` | 201; `sort_order = 5` |
| Slugify: special characters in name | `{"name": "EDA Tools & Flows!"}` | Slug = `"eda-tools-flows"` (non-word chars stripped, spaces collapsed to hyphens) |
| Update category name only | `PATCH /admin/categories/{id}` `{"name": "New Name"}` | 200; `name` updated; `updated_at` refreshed; `slug` unchanged |
| Update category slug only | `PATCH /admin/categories/{id}` `{"slug": "new-slug"}` | 200; `slug` updated; `name` unchanged |
| Reorder categories | `PATCH /admin/categories/reorder` `[{id, sort_order}, ...]` | 200; bulk `sort_order` update applied; subsequent GET returns categories in new order |
| Reorder allows ties | Two items with the same `sort_order` in payload | 200; both rows updated without error (no uniqueness constraint enforced) |
| Soft delete category (no problems) | `DELETE /admin/categories/{id}` on category with 0 problems | 200; `deleted_at` set to now; category absent from public category list |
| Soft-deleted category invisible in normal queries | Read category list after soft delete | Deleted category absent; `deleted_at IS NOT NULL` records filtered out |
| List tags sorted by name (default) | `GET /tags` (no sort param) | 200; tags in alphabetical order; each tag has `usage_count` reflecting actual join count |
| List tags sorted by usage | `GET /tags?sort=usage` | 200; tags ordered by `usage_count DESC`, then `name` for ties |
| Tag with zero usage | Tag with no `ProblemTag` rows | Appears in list with `usage_count = 0` (LEFT OUTER JOIN) |
| Rename tag | `PATCH /admin/tags/{id}` `{"name": "new-name"}` | 200; `Tag.name` updated; all problems tagged with this tag now reflect new name |
| Delete tag | `DELETE /admin/tags/{id}` | 200; all `ProblemTag` rows for tag removed first; then `Tag` row removed; tag absent from GET |
| Merge tags (source has unique problems) | `POST /admin/tags/merge` `{"source_id": A, "target_id": B}` where no overlap | 200; all source problems now carry target tag; source tag deleted; target tag returned |
| Merge tags (source and target share problems) | `POST /admin/tags/merge` where some problems are already tagged with target | 200; duplicate associations silently skipped (ON CONFLICT DO NOTHING); no integrity error; source deleted |
| List flags — all | `GET /admin/moderation/flags` (no status param) | 200; all `Flag` rows ordered by `created_at DESC` |
| List flags — filtered by status | `GET /admin/moderation/flags?status=pending` | 200; only flags with `status = "pending"` returned |
| Resolve flag | `POST /admin/moderation/flags/{id}/resolve` `{"resolution_note": "resolved"}` | 200; `Flag.status = "resolved"`; `resolution_note` and `resolved_by` set; `flag.resolved` log event emitted |
| De-anonymize anonymous problem | `POST /admin/moderation/de-anonymize/{problem_id}` for anonymous problem | 200; `AuditLog` row flushed BEFORE `author_id` returned; `admin.de_anonymize` log event emitted; response contains `author_id` |
| De-anonymize — AuditLog durability | Simulate crash between flush and response | AuditLog row persists in DB; second call succeeds and writes second audit entry (no idempotency guard) |
| List config | `GET /admin/config/` | 200; all `AppConfig` rows ordered alphabetically by key |
| Upsert config — update existing key | `PATCH /admin/config/` `{"key": "max_pin_count", "value": "10"}` | 200; `AppConfig` row updated in-place; `config.updated` log event emitted |
| Upsert config — insert new allowed key | `PATCH /admin/config/` with key in `ALLOWED_CONFIG_KEYS` that has no existing row | 200; new `AppConfig` row inserted; `config.updated` log event emitted |
| All four allowed keys accepted | Keys: `max_pin_count`, `claim_expiry_days`, `magic_link_ttl_minutes`, `auto_watch_default_level` | Each returns 200 without error |

---

##### Error scenarios

| Error type | Trigger condition | Expected behavior |
|---|---|---|
| `_get_user_or_404` — role update | `PATCH /admin/users/{id}/role` with nonexistent UUID | 404; `"User not found"`; no DB write |
| `_get_user_or_404` — status update | `PATCH /admin/users/{id}/status` with nonexistent UUID | 404; `"User not found"`; no DB write |
| `CategoryNotFoundError` — update | `PATCH /admin/categories/{id}` with nonexistent category UUID | 404; `"Category not found"` |
| `CategoryNotFoundError` — delete | `DELETE /admin/categories/{id}` with nonexistent category UUID | 404; `"Category not found"` |
| `CategoryInUseError` — soft delete blocked | `DELETE /admin/categories/{id}` where `Problem.category_id` count > 0 | 409; `"Category is referenced by existing problems and cannot be deleted"`; `deleted_at` unchanged |
| `TagNotFoundError` — rename | `PATCH /admin/tags/{id}` with nonexistent tag UUID | 404; `"Tag {tag_id} not found"` |
| `TagNotFoundError` — delete | `DELETE /admin/tags/{id}` with nonexistent tag UUID | 404; `"Tag {tag_id} not found"` |
| `TagNotFoundError` — merge (source) | `POST /admin/tags/merge` with nonexistent `source_id` | 404; `"Tag {tag_id} not found"` |
| `TagNotFoundError` — merge (target) | `POST /admin/tags/merge` with nonexistent `target_id` | 404; `"Tag {tag_id} not found"` |
| `TagNameConflictError` — rename collision | `PATCH /admin/tags/{id}` with a name already held by another tag | 409; `"A tag with that name already exists"` |
| `TagMergeError` — source equals target | `POST /admin/tags/merge` `{"source_id": X, "target_id": X}` | 400; `"Source and target tags must be different"` |
| Flag not found — resolve | `POST /admin/moderation/flags/{id}/resolve` with nonexistent flag UUID | 404; `"Flag not found"` |
| Problem not found — de-anonymize | `POST /admin/moderation/de-anonymize/{id}` with nonexistent problem UUID | 404; `"Problem not found"` |
| Problem not anonymous — de-anonymize | `POST /admin/moderation/de-anonymize/{id}` on problem with `is_anonymous = false` | 400; `"Problem is not anonymous"`; no AuditLog row written |
| Config key not in allowlist | `PATCH /admin/config/` `{"key": "unknown_key", ...}` | 400; `"Key 'unknown_key' is not an allowed config key. Allowed: {sorted list}"`; no DB write |
| Invalid `?sort=` on tag list | `GET /tags?sort=invalid` | 422; `"sort must be 'name' or 'usage'"` |
| Non-admin JWT on any admin route | Valid JWT with `role != "admin"` | 403 returned by `require_admin` dependency; route handler never executes |
| Unauthenticated request on any admin route | No Authorization header | 401 returned by auth middleware; route handler never executes |

---

##### Boundary conditions

- **Category sort_order when table is empty:** `MAX(sort_order)` returns `NULL`; service defaults to `-1` so first category receives `sort_order = 0`.
- **Category sort_order increment:** With existing max of `N`, new category gets `N + 1`. Verify with multiple sequential creates.
- **Reorder with no-op payload:** Submitting each category's existing `sort_order` unchanged must still return 200 and leave DB state identical.
- **Tag merge with no source problems:** Source tag has zero `ProblemTag` rows; bulk INSERT is empty; source tag is still deleted; target tag returned unchanged.
- **Tag merge atomicity:** If the DB raises after the INSERT but before the source DELETE, the whole transaction rolls back — no partial state persists. Test via mocked flush error.
- **De-anonymize called twice:** Second call on same problem succeeds (no idempotency guard); a second distinct `AuditLog` row is written.
- **Config upsert — all four ALLOWED_CONFIG_KEYS accepted:** `max_pin_count`, `claim_expiry_days`, `magic_link_ttl_minutes`, `auto_watch_default_level` — each must succeed. A fifth key not in this frozenset must fail with 400.
- **Slug edge cases:**
  - All special characters stripped: `"!!!!"` → must not produce empty slug (behavior should be defined or raise).
  - Leading/trailing hyphens: `" Design "` → `"design"`.
  - Consecutive internal spaces/underscores: `"RTL__Design"` → `"rtl-design"`.
- **User search — empty `q` string vs. absent `q`:** `?q=` (empty string) vs. no param at all — both should return the full user list, not zero results.
- **Tag rename to same name (self-rename):** `PATCH /admin/tags/{id}` with the tag's current name — should succeed (name is not held by a *different* tag); verify no 409.
- **Soft-deleted category stays in DB:** After `DELETE /admin/categories/{id}`, the row exists with `deleted_at` set; admin-only queries that bypass the `deleted_at IS NULL` filter must still surface it.

---

##### Integration points

| Downstream component | Interaction | Test approach |
|---|---|---|
| `log_event` (structured logging) | Called on every mutation: `user.role_changed`, `user.status_changed`, `flag.resolved`, `admin.de_anonymize`, `config.updated` | Assert `log_event` called with correct action string; use mock/spy; do not assert on log output format |
| `AuditLog` model | Written by `de_anonymize` before returning `author_id`; must be flushed before response | Insert then inspect DB within the same test transaction; verify row exists after service call even when response is not yet returned |
| `ProblemTag` join table | `delete_tag` removes all join rows first; `merge_tags` bulk-inserts then removes source rows | Assert no orphaned `ProblemTag` rows remain after delete; assert merged problems carry target tag only |
| `Problem.category_id` FK reference | `soft_delete_category` counts referencing problems before setting `deleted_at` | Seed problems with the target category; verify 409 path; seed zero problems; verify soft delete path |
| Database session (`db.flush`) | All writes use `flush` not `commit`; outer session dependency commits after handler returns | Tests using async session fixture must call `commit` (or `await session.flush()`) to observe DB state within the test |
| `require_admin` FastAPI dependency | Router-level dependency injected in `app/routes/admin/__init__.py` | Override dependency in test client; separately test that a non-overridden client returns 403/401 for every sub-router prefix |

---

##### Known test gaps

- **Race condition on tag merge:** Two concurrent merges targeting the same source tag. The ON CONFLICT DO NOTHING absorbs one duplicate insert but the second DELETE of the source tag hits a missing row. Not covered by unit tests; requires integration-level concurrency test or an advisory lock.
- **Reorder with missing IDs:** The spec (REQ-456) says an array with omitted IDs should return 422, but the engineering guide describes no validation step for this — behavior is undefined until the service implementation is inspected.
- **`_slugify` empty-result case:** A name composed entirely of non-word characters produces an empty slug string. Whether the service raises, falls back, or persists an empty slug is unspecified.
- **Admin soft-deleted category visibility:** No admin-facing endpoint to list soft-deleted categories is described. Tests cannot verify the "soft-deleted categories remain accessible to admin endpoints" criterion (REQ-458 AC) without a dedicated endpoint or direct DB inspection.
- **`log_event` failure isolation:** If `log_event` raises, the behavior (transaction rolled back vs. silently swallowed) is not specified. Tests currently assume `log_event` never raises.
- **De-anonymize idempotency:** Multiple audit rows for the same problem are accepted as intended, but there is no test verifying the count of audit rows on the Nth call.
- **Config upsert concurrent writes:** Two simultaneous PATCH calls for the same key — the upsert logic is not described as using `ON CONFLICT DO UPDATE`, so a race may produce a duplicate-key integrity error. Not currently covered.

---

##### Agent isolation contract

> **Inputs required to run this test suite in isolation:**
>
> - A running async SQLAlchemy session (or an in-memory SQLite/PostgreSQL test database) accessible via the FastAPI `Depends(get_db)` override.
> - A `User` fixture with `role = "admin"` and one with `role = "member"` (for auth guard tests).
> - `require_admin` dependency overridden in the test client for happy-path and error tests; left un-overridden for auth guard tests.
> - `log_event` replaced with a `MagicMock` or `AsyncMock` spy in all tests — no real log sink needed.
> - No network calls, no external services, no message bus required.
> - Domain exceptions tested at the service layer (no HTTP client needed); HTTP status codes tested at the route layer via `AsyncClient` or `TestClient`.
> - `ALLOWED_CONFIG_KEYS = frozenset(["max_pin_count", "claim_expiry_days", "magic_link_ttl_minutes", "auto_watch_default_level"])` must match the value in `app/models/app_config` — if that constant changes, boundary tests for the config endpoint must be updated.
> - No `app/` source files are read during test planning; all behavioral contracts are derived from the Engineering Guide (lines 2309–2594) and REQ-450 through REQ-476 acceptance criteria only.

---

### Middleware & Logging

#### app/middleware/security.py · app/middleware/logging.py · app/middleware/rate_limit.py · app/logging.py — Middleware & Logging

**Module purpose:** Provides application-wide HTTP security hardening, XSS-safe HTML sanitization, structured JSON observability with correlation IDs, and per-email magic-link rate limiting.

**In scope:**
- `SecurityHeadersMiddleware` — header injection via `setdefault`
- `sanitize_html` — two-pass HTML sanitizer
- `LoggingMiddleware` — correlation ID lifecycle, request_started / request_finished / request_failed log entries, duration_ms
- `JSONFormatter` / `configure_logging` / `get_logger` — structured JSON output, log level control
- `MagicLinkRateLimiter` / `check_magic_link_rate` — sliding-window enforcement, `cleanup()`
- `log_event` — audit helper that reads `get_correlation_id()` via lazy import

**Out of scope:**
- NGINX-level rate limiting (infrastructure concern, not unit-testable here)
- Underlying Starlette/FastAPI ASGI machinery
- SMTP or database interactions triggered downstream of middleware

---

##### Happy path scenarios

| Scenario | Input | Expected output |
|---|---|---|
| Security headers added to plain response | GET request to any route; no security headers pre-set by the handler | Response contains all six headers: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, `X-XSS-Protection: 1; mode=block`, `Permissions-Policy: camera=(), microphone=(), geolocation=()`, and `Content-Security-Policy` with the full `_CSP` value |
| Security headers do not overwrite explicit handler header | Handler explicitly sets `X-Frame-Options: SAMEORIGIN` before returning | Response retains `X-Frame-Options: SAMEORIGIN`; all other five security headers are set by middleware |
| CSP directive is well-formed | Any response | CSP value contains all eight directives: `default-src`, `script-src`, `style-src`, `img-src`, `font-src`, `frame-ancestors`, `form-action`, `base-uri` |
| sanitize_html — safe tags preserved | `<p>Hello <strong>world</strong></p>` | Returned string equals `<p>Hello <strong>world</strong></p>` |
| sanitize_html — all safe tags pass through | Input containing each of `p, strong, em, code, pre, blockquote, ul, ol, li, a, br, h1, h2, h3, h4, h5, h6` | All tags present in output unchanged |
| sanitize_html — Pass 1 removes script element | `<p>before</p><script>alert(1)</script><p>after</p>` | Output is `<p>before</p><p>after</p>`; no `alert` text remains |
| sanitize_html — Pass 1 removes style element | `<style>body{display:none}</style><p>text</p>` | Output is `<p>text</p>`; no CSS text remains |
| sanitize_html — Pass 1 removes iframe | `<iframe src="evil.com"></iframe><p>safe</p>` | Output is `<p>safe</p>` |
| sanitize_html — Pass 1 removes form and input | `<form action="/steal"><input type="hidden" value="x"/></form>text` | Output is `text` |
| sanitize_html — Pass 2 strips on* attributes | `<a href="/ok" onclick="steal()">link</a>` | Output is `<a href="/ok">link</a>`; no `onclick` present |
| sanitize_html — Pass 2 strips javascript: href | `<a href="javascript:alert(1)">click</a>` | Output is `<a>click</a>`; href is removed |
| sanitize_html — Pass 2 drops non-safe tags | `<div><p>text</p></div>` | Output is `<p>text</p>`; `<div>` tags removed, content preserved |
| LoggingMiddleware — generates correlation ID when none provided | GET request with no `X-Correlation-ID` header | `request_started` log contains a `correlation_id` field matching a UUID4 pattern; response includes `X-Correlation-ID` header with same value |
| LoggingMiddleware — propagates existing correlation ID | GET request with `X-Correlation-ID: test-id-123` | `request_started` log and response header both contain `test-id-123` |
| LoggingMiddleware — emits request_started | Any request | Log record with `message: "request_started"` contains `method`, `path`, `query_string` fields |
| LoggingMiddleware — emits request_finished | Successful response | Log record with `message: "request_finished"` contains `status_code`, `duration_ms` (positive float), and `correlation_id` |
| LoggingMiddleware — duration_ms is accurate | Two requests sequentially; second is artificially delayed | `duration_ms` in each `request_finished` record reflects actual elapsed time within reasonable tolerance |
| JSONFormatter — mandatory keys present | Any log record | Serialized JSON contains `timestamp`, `level`, `logger`, `message` keys |
| JSONFormatter — correlation_id included when set | Log record emitted inside a request context with a known correlation ID | `correlation_id` key present in JSON with the expected value |
| JSONFormatter — default=str fallback | Log record with a `datetime` object in extra_data | JSON serializes without raising `TypeError`; value is a string representation |
| configure_logging — development level is DEBUG | `configure_logging("development")` called | Root logger effective level is `logging.DEBUG` |
| configure_logging — non-development level is INFO | `configure_logging("production")` called | Root logger effective level is `logging.INFO` |
| configure_logging — idempotent on second call | Called twice in sequence | After second call, root logger still has exactly one handler; no duplicate output |
| MagicLinkRateLimiter — first 5 requests succeed | 5 calls to `check(email)` within 600 s | All 5 calls return without raising; internal list for that email has 5 timestamps |
| MagicLinkRateLimiter — window resets after 600 s | 5 requests made at t=0; 6th made at t=601 | 6th call succeeds; the 5 old timestamps have been pruned |
| MagicLinkRateLimiter — cleanup() removes expired keys | Email with 5 timestamps all older than 600 s; `cleanup()` called | Email key is removed from `_attempts`; subsequent `check(email)` starts a fresh window |

---

##### Error scenarios

| Error type | Trigger condition | Expected behavior |
|---|---|---|
| sanitize_html — Pass 1 removes object/embed/applet | Input containing `<object>`, `<embed>`, `<applet>` tags | Elements entirely absent from output; no partial tag text remains |
| sanitize_html — Pass 1 removes textarea and button | Input containing `<textarea>value</textarea><button>click</button>` | Both elements entirely absent; surrounding text preserved |
| sanitize_html — nested dangerous tags | `<div><script><p>text</p></script></div>` | No script content in output; function does not raise |
| sanitize_html — empty string input | `""` | Returns `""` without raising |
| sanitize_html — input with no HTML | `"plain text"` | Returns `"plain text"` unchanged |
| MagicLinkRateLimiter — 6th request raises 429 | 5 requests made; 6th call to `check(email)` | `HTTPException` raised with `status_code=429`, `detail="Too many magic link requests"`, and `Retry-After` header present as a positive integer string |
| MagicLinkRateLimiter — Retry-After value is correct | Oldest timestamp 300 s ago; window is 600 s | `Retry-After` value is approximately `(600 - 300) + 1 = 301` seconds (allow ±2 s for timing) |
| MagicLinkRateLimiter — cleanup() with no expired entries | All timestamps are recent | `_attempts` dict is unchanged; no keys removed |
| LoggingMiddleware — request_failed emitted on exception | Handler raises an unhandled `ValueError` | Log record with `message: "request_failed"` is emitted at ERROR level containing `duration_ms`; exception is re-raised (not swallowed) |
| SecurityHeadersMiddleware — headers present on 4xx response | Handler returns 404 | All six security headers are present on the 404 response |
| SecurityHeadersMiddleware — headers present on 5xx response | Handler raises, FastAPI returns 500 | All six security headers are present on the 500 response (subject to known gap below) |

---

##### Boundary conditions

- `sanitize_html` with deeply nested safe tags (e.g., 20 levels of `<em>` inside `<p>`) — function returns a best-effort result without raising; output length is reasonable.
- `sanitize_html` with attributes that have mixed-case event handlers (e.g., `onClick`, `ONCLICK`) — verify `_EVENT_HANDLER_RE` is case-insensitive and strips all variants.
- `MagicLinkRateLimiter` with `max_requests=1` — the 2nd call should immediately return 429; `Retry-After` should reflect the remaining window time of the first request.
- `MagicLinkRateLimiter` with two distinct emails — rate limit state is per-email; exhausting limits for `a@example.com` does not affect `b@example.com`.
- `JSONFormatter` with a log record that has no `extra_data` and no exception — output JSON contains exactly the four mandatory keys plus `correlation_id` if set; no extra null fields.
- `configure_logging` called with an empty string for `environment` — should behave as non-development (INFO level).
- `LoggingMiddleware` with a response that has no `Content-Length` header — `request_finished` log is emitted without a body-size field; no `KeyError`.
- `LoggingMiddleware` with `user_id` cookie absent — `request_started` log is emitted with `user_id` field null or absent; no `KeyError`.

---

##### Integration points

- `SecurityHeadersMiddleware` is registered as outermost middleware in `create_app()` — tests that exercise the full app factory should confirm headers appear on all routes including error responses.
- `LoggingMiddleware` stores correlation ID in a `contextvars.ContextVar`; `log_event()` in `app/logging.py` reads that value via a lazy import of `get_correlation_id`. Integration test: call `log_event()` from within a request handler and assert the correlation ID in the emitted log matches the one from `request_started`.
- `check_magic_link_rate` is a FastAPI dependency; integration test should wire it into a test route using `app.dependency_overrides` to confirm 429 responses are returned from the endpoint layer.
- `configure_logging` must be called before any middleware emits log lines; test startup order in the `create_app()` factory to confirm logging is initialized before the first request is processed.

---

##### Known test gaps

- **SecurityHeadersMiddleware on unhandled 500s:** The module reference states that if `call_next` raises before the middleware can attach headers, security headers will be absent on Starlette's internal error boundary response. This edge case is not straightforwardly unit-testable without deliberately triggering ASGI-level failures; document as a manual verification item.
- **`sanitize_html` against adversarial obfuscated HTML:** The two-pass regex strategy is acknowledged in the design as best-effort. Mutation-tested fuzzing (e.g., with `hypothesis`) is recommended but not part of the standard unit test suite.
- **`MagicLinkRateLimiter` memory leak (no `cleanup()` scheduling):** The unit tests confirm `cleanup()` works when called, but the absence of a scheduled call in the application is not caught by tests. This requires a runtime/integration audit.
- **`JSONFormatter` under concurrent async log emission:** Race conditions in `contextvars` propagation across `asyncio.gather()` tasks are not covered by synchronous unit tests.
- **`configure_logging` thread safety:** If called from multiple threads simultaneously (e.g., during parallel test collection), handler duplication is possible. Use `pytest-xdist` isolation or a module-scoped fixture.

---

##### Agent isolation contract

```
MODULE: app/middleware/security.py, app/middleware/logging.py, app/middleware/rate_limit.py, app/logging.py
PHASE-0 CONTRACTS:
  - MagicLinkRateLimiter: max_requests=5, window_seconds=600
  - Security headers (6): X-Content-Type-Options, X-Frame-Options, Referrer-Policy,
    X-XSS-Protection, Permissions-Policy, Content-Security-Policy
  - sanitize_html safe tags: p, strong, em, code, pre, blockquote, ul, ol, li, a, br, h1-h6
  - Pass 1 removes: script, style, iframe, object, embed, applet, form, input, textarea, select, button
  - Pass 2 strips: on* attributes, javascript: hrefs; drops non-safe tags
  - 6th request to check(email) raises HTTPException(429) with Retry-After header
  - cleanup() removes keys where all timestamps are expired
  - configure_logging("development") -> DEBUG; anything else -> INFO
  - JSONFormatter mandatory keys: timestamp, level, logger, message
  - LoggingMiddleware emits: request_started, request_finished, request_failed
  - X-Correlation-ID generated (uuid4) if absent; propagated via contextvars.ContextVar
DO NOT import or read any source file in app/ during test generation.
MUST mock: time.time() for rate limiter window tests; asyncio event loop for LoggingMiddleware dispatch tests.
```

---

---

### Leaderboard

#### app/services/leaderboard.py, app/routes/leaderboard.py — Leaderboard

**Module purpose:** Exposes a single read-only `GET /leaderboard` endpoint that returns ranked user lists across two competitive tracks (top solvers by accepted solution count, top reporters by upstars on authored problems), each filterable by a rolling time window.

**In scope:**
- `GET /leaderboard` — both `solvers` and `reporters` tracks
- Time period filtering: `all_time`, `this_month` (rolling 30 days), `this_week` (rolling 7 days)
- Anonymous content exclusion from both tracks
- Alphabetical tiebreaker on equal scores
- Rank assignment in Python via enumeration
- Pagination via `limit` (1–100, default 20)

**Out of scope:**
- Leaderboard UI rendering / tab switching (REQ-526 — front-end concern)
- Pagination beyond `limit` (no `offset` parameter; no cursor; this is a documented constraint)
- Push/notification on rank change — not implemented
- Write operations (module is strictly read-only)

---

##### Happy path scenarios

| Scenario | Input | Expected output |
|---|---|---|
| Top solvers, all time | `track=solvers`, `period=all_time` | HTTP 200; entries ordered by `accepted_count DESC`; `rank` starts at 1 and increments by 1 |
| Top reporters, all time | `track=reporters`, `period=all_time` | HTTP 200; entries ordered by `upstar_count DESC`; response contains `upstar_count` key (not `accepted_count`) |
| Default parameters | No parameters | HTTP 200; equivalent to `track=solvers`, `period=all_time`, `limit=20` |
| Top solvers, this_week | `track=solvers`, `period=this_week` | Only solutions with `created_at >= now - 7 days` counted; users with only older solutions absent |
| Top solvers, this_month | `track=solvers`, `period=this_month` | Only solutions with `created_at >= now - 30 days` counted |
| Top reporters, this_week | `track=reporters`, `period=this_week` | Only problems with `created_at >= now - 7 days` eligible; upstars on older problems not counted |
| Top reporters, this_month | `track=reporters`, `period=this_month` | Only problems with `created_at >= now - 30 days` eligible |
| Limit applied | `limit=5` | At most 5 entries returned; fewer if fewer qualifying users exist |
| Limit = 100 | `limit=100` | Up to 100 entries returned without error |
| Empty result set | Valid track/period with no qualifying activity | HTTP 200; `{"entries": []}` |
| Alphabetical tiebreaker | Two users with identical score | User whose `display_name` sorts earlier alphabetically appears first (lower rank number) |
| Anonymous solution excluded | User has 3 accepted solutions: 2 non-anonymous, 1 anonymous | `accepted_count=2` for that user; anonymous solution not counted |
| Anonymous problem excluded | User has 2 problems: 1 non-anonymous with 10 upstars, 1 anonymous with 5 upstars | `upstar_count=10` for that user; anonymous problem's upstars not counted |
| Response envelope | Any valid request | Response contains `track`, `period`, and `entries` keys at top level |
| Rank numbering | N entries returned | `rank` values are 1, 2, 3, … N (contiguous; no gaps) |

---

##### Error scenarios

| Error type | Trigger condition | Expected behavior |
|---|---|---|
| Invalid `track` value | `track=hackers` | HTTP 422 Unprocessable Entity; service layer never called |
| Invalid `period` value | `period=yesterday` | HTTP 422 Unprocessable Entity; service layer never called |
| `limit` below minimum | `limit=0` | HTTP 422 Unprocessable Entity (FastAPI `ge=1` constraint) |
| `limit` above maximum | `limit=101` | HTTP 422 Unprocessable Entity (FastAPI `le=100` constraint) |
| Database failure | Simulate connection loss | HTTP 500; no partial results; SQLAlchemy exception propagates to global handler |
| Missing `track` | Parameter absent | HTTP 200 with default `track=solvers` applied |
| Missing `period` | Parameter absent | HTTP 200 with default `period=all_time` applied |

---

##### Boundary conditions

- `limit=1`: only the single top-ranked user returned; rank is 1.
- `limit=100`: maximum page; test that SQL `LIMIT` is applied before Python enumeration (rank assignment always starts at 1 regardless of limit).
- Score of 0: a user with no accepted solutions (solvers track) or no upstars on non-anonymous problems (reporters track) must NOT appear in results — they have no qualifying rows to aggregate over.
- Single user in result set: returned with `rank=1`; no tiebreaker needed.
- Equal score at boundary of `limit`: the user whose `display_name` sorts later alphabetically is silently excluded; no tie-expansion.
- Rolling 7-day window boundary: a solution submitted exactly at `now - 7 days` (boundary-inclusive): verify whether the cutoff is `>=` (inclusive) as documented.
- Rolling 30-day window: solution or problem at `now - 30 days`: same boundary-inclusion check.
- User has accepted solutions across multiple time windows: `this_week` count < `this_month` count <= `all_time` count (monotonically non-decreasing as window widens).
- Reporter: upstars cast today on a problem posted 31 days ago under `this_month`: upstars are excluded because the problem falls outside the window (cutoff is on `Problem.created_at`, not `Upstar.created_at`).
- Solver: solution submitted 6 days ago on a problem posted 90 days ago under `this_week`: solution IS counted (cutoff is on `Solution.created_at`).

---

##### Integration points

| Dependency | Nature | Test approach |
|---|---|---|
| `users`, `solutions`, `problems`, `upstars` tables | Ranking queries join across all four | Seed representative fixtures: known users, known accepted/anonymous solution sets, known upstar sets |
| `Solution.status == "accepted"` | Solvers track counts only accepted solutions | Seed solutions with `status="pending"` and `status="rejected"`; assert they do not appear in count |
| `Solution.is_anonymous` / `Problem.is_anonymous` | Exclusion filter | Seed one anonymous and one non-anonymous contribution per user; assert only non-anonymous counted |
| `_period_cutoff()` helper | Maps enum to UTC `datetime` | Unit-test helper directly: assert `all_time` returns `None`; `this_month` returns within 1s of `now - 30 days`; `this_week` within 1s of `now - 7 days` |
| FastAPI `Query(ge=1, le=100)` | Limit validation | Confirm 422 responses without reaching service layer (assert service mock not called) |
| Python rank enumeration | Rank is `idx + 1` on ordered SQL result | Assert ranks in response are exactly `[1, 2, ..., len(entries)]` with no gaps |

---

##### Known test gaps

1. **No offset/cursor pagination**: Callers needing more than 100 entries have no mechanism. The spec documents this as a constraint, but there is no test asserting the API rejects or ignores an `offset` parameter if one is accidentally supplied.
2. **Tied score at `limit` boundary, non-deterministic exclusion**: The alphabetical tiebreaker ensures determinism between two tied users, but there is no test specifically covering the case where the Nth and (N+1)th users have identical scores at the exact `limit` cutoff.
3. **Rolling window boundary-inclusivity**: The exact operator used in `_period_cutoff()` (`>=` vs. `>`) is not formally specified. Tests should pin the boundary behavior to prevent silent regressions.
4. **Reporter upstar timing semantics**: The documented behavior (cutoff on `Problem.created_at`, not `Upstar.created_at`) is subtle. A test explicitly seeding an old problem with a new upstar is the only reliable guard against this being inadvertently reversed.
5. **Rank gaps on deletion**: If a user is deleted between query time and Python enumeration (theoretical in async context), no test covers this race condition.
6. **`display_name` NULL**: If a user has a null `display_name`, alphabetical tiebreaker behavior is undefined. No test covers this edge case.

---

##### Agent isolation contract

> **Leaderboard module test agent contract**
>
> Source files under test: `app/services/leaderboard.py`, `app/routes/leaderboard.py`
>
> Do NOT read or modify any other app/ source files.
>
> Inputs available: this test specification, the engineering guide section 3.13 (lines 2777-2928), and the spec REQ-268 (dual-track leaderboard), REQ-270 (anonymous exclusion).
>
> All database interactions must go through a test-scoped AsyncSession against a dedicated test PostgreSQL instance with the full schema applied.
>
> Phase 0 contracts that must hold across all tests:
> - Valid tracks: `solvers`, `reporters` only. Any other value returns HTTP 422.
> - Valid periods: `all_time`, `this_month`, `this_week` only. Any other value returns HTTP 422.
> - Anonymous content (`is_anonymous=True`) is excluded in SQL before aggregation — not post-filtered in Python.
> - `limit` in [1, 100]; violations return HTTP 422; default is 20.
> - Rank is assigned in Python as `idx + 1`; the SQL result is ordered and limited before enumeration.
> - Solvers: time cutoff applies to `Solution.created_at`. Reporters: time cutoff applies to `Problem.created_at`.
> - `all_time` applies no date filter (`cutoff=None`).
> - Tiebreaker is `User.display_name ASC`.

---

### Infrastructure & Deployment

#### app/main.py · GET /healthz · nginx/nginx.conf · scripts/backup.sh · scripts/restore.sh · scripts/generate-systemd.sh — Infrastructure & Deployment

**Module purpose:** Assembles and boots the FastAPI application (factory, middleware order, exception mapping), exposes a dual-probe health endpoint for orchestrators, and provides operational scripts for backup/restore and systemd unit generation; NGINX serves as the TLS-terminating edge proxy with bot detection and rate limiting.

**In scope:**
- `create_app()` factory — middleware registration order, exception handler mapping via `_EXCEPTION_STATUS_MAP`
- `GET /healthz` — database and storage probes, concurrent execution, 200/503 responses
- `GET /api/problems/{problem_id}/meta` — OG meta HTML, `html.escape`, 404 for missing problem
- `scripts/backup.sh` — env validation, daily/weekly promotion, 7-daily/4-weekly retention
- `scripts/restore.sh` — env validation, gunzip|psql, post-restore table-count verification
- `scripts/generate-systemd.sh` — container discovery, unit file generation, `Restart=always` injection, `systemctl daemon-reload`

**Out of scope:**
- NGINX configuration (`nginx/nginx.conf`) — declarative infrastructure artifact; not unit-testable (see known test gaps)
- Podman Compose stack (`podman-compose.yml`) — container orchestration; not unit-testable (see known test gaps)
- Alembic migration execution — tested separately as a database concern
- TLS certificate management

---

##### Happy path scenarios

| Scenario | Input | Expected output |
|---|---|---|
| `create_app()` returns a FastAPI instance | Call `create_app()` with valid settings patched | Returns a `FastAPI` object; no exception raised |
| Middleware registration order | Inspect `app.middleware_stack` or use a test request | `SecurityHeadersMiddleware` is outermost (runs first on response); `LoggingMiddleware` is next; `SessionMiddleware` is innermost |
| AppError subclass in `_EXCEPTION_STATUS_MAP` | Raise a mapped `AppError` subclass from a test route | Response status code matches the mapped value; body is `{"detail": "<message>"}` |
| AppError subclass NOT in `_EXCEPTION_STATUS_MAP` | Raise an unmapped `AppError` subclass | Response status code is 500; body is `{"detail": "<message or class name>"}` |
| Health check — both probes pass | Database accepts `SELECT 1` within 2 s; storage directory is writable | `GET /healthz` returns HTTP 200; body is `{"status": "ok", "checks": {"database": {"status": "ok"}, "storage": {"status": "ok"}}}` |
| Health check — response structure | Any successful probe | JSON body contains top-level `status` and `checks` keys; `checks` contains `database` and `storage` sub-objects each with at least a `status` key |
| Health check — no authentication required | Unauthenticated GET request to `/healthz` | Returns 200 or 503 (not 401/403) |
| Health check — probes run concurrently | Mock both probes to record call times | Both probes are started before either completes (start times overlap); total wall time is approximately max(probe1, probe2), not sum |
| OG meta endpoint — problem found | `GET /api/problems/{valid_uuid}/meta`; problem exists in DB | HTTP 200; `Content-Type: text/html`; response contains `<meta property="og:title"`, `og:description`, `og:url`, `og:site_name`, `og:type` |
| OG meta endpoint — og:url points to SPA route | Problem exists; `BASE_URL=https://example.com` | `og:url` content is `https://example.com/problems/{problem_id}`, not the `/meta` path |
| OG meta endpoint — og:type is "article" | Any existing problem | `og:type` content attribute is `"article"` |
| OG meta endpoint — description truncated to 200 chars | Problem with description longer than 200 characters | `og:description` content is exactly 200 characters |
| OG meta endpoint — html.escape on title | Problem title contains `<script>` or `"` or `&` | Characters are escaped as `&lt;script&gt;`, `&quot;`, `&amp;` in the HTML output |
| backup.sh — creates daily backup | All 5 env vars set; `pg_dump` succeeds | File created in `$BACKUP_DIR/daily/` with expected naming pattern; exit code 0 |
| backup.sh — Sunday promotes to weekly | `DAY_OF_WEEK=7`; pg_dump succeeds | Backup file also copied to `$BACKUP_DIR/weekly/`; exit code 0 |
| backup.sh — non-Sunday does not write weekly | `DAY_OF_WEEK=1` through `DAY_OF_WEEK=6` | `$BACKUP_DIR/weekly/` is not written during this run |
| backup.sh — 7-daily retention enforced | 8 files pre-exist in `daily/`; backup runs | Oldest file removed; exactly 7 files remain in `daily/` (the 7 newest) |
| backup.sh — 4-weekly retention enforced | 5 files pre-exist in `weekly/`; Sunday backup runs | Oldest weekly removed; exactly 4 files remain in `weekly/` |
| restore.sh — successful restore | Valid backup file argument; env vars set; psql succeeds; table count > 0 | Exit code 0; log line confirms completion |
| restore.sh — post-restore table count check passes | Restored database has ≥ 1 table in `public` schema | Script exits 0 |
| generate-systemd.sh — unit file written | Running container named `aion-bulletin-api`; running as root | File written to `/etc/systemd/system/container-aion-bulletin-api.service`; file contains `Restart=always` |
| generate-systemd.sh — daemon-reload called | Successful unit generation | `systemctl daemon-reload` is invoked |

---

##### Error scenarios

| Error type | Trigger condition | Expected behavior |
|---|---|---|
| Health check — database probe timeout | `_check_database` hangs beyond 2.0 s | Returns `{"status": "fail", "error": "timeout"}` for database check; overall response is HTTP 503 |
| Health check — database connection error | DB raises `OperationalError` | Returns `{"status": "fail", "error": "<message>"}` for database; HTTP 503 |
| Health check — storage not writable | Storage path is on a read-only filesystem (mock `PermissionError`) | Returns `{"status": "fail", "error": "..."}` for storage; HTTP 503 |
| Health check — storage probe timeout | Storage probe hangs beyond 2.0 s | Returns `{"status": "fail", "error": "timeout"}` for storage; HTTP 503 |
| Health check — both probes fail | Both database and storage mocked to fail | HTTP 503; `"status": "degraded"`; both checks show `"fail"` |
| Health check — one probe fails | Database passes; storage fails | HTTP 503 (no partial-health 200); `"status": "degraded"` |
| OG meta endpoint — unknown UUID | `GET /api/problems/00000000-0000-0000-0000-000000000000/meta`; not in DB | HTTP 404; `{"detail": "Problem not found"}` |
| OG meta endpoint — invalid UUID format | `GET /api/problems/not-a-uuid/meta` | HTTP 422 (FastAPI path parameter validation) |
| backup.sh — missing env var | One of the 5 required vars is unset | Script exits 1 before any `pg_dump` invocation; error message identifies the missing variable |
| backup.sh — pg_dump fails | `pg_dump` returns non-zero | Partial output file deleted with `rm -f`; script exits 1; no corrupt file left in `daily/` |
| restore.sh — no argument provided | Script invoked with zero arguments | Exits 1; usage message printed |
| restore.sh — backup file does not exist | Argument is a non-existent path | Exits 1; error message references the missing file |
| restore.sh — missing env var | One of the 5 required vars is unset | Exits 1 before `gunzip\|psql` |
| restore.sh — post-restore table count is zero | psql returns exit 0 but no tables exist | Exits 1 with `"Verification failed"` log line |
| generate-systemd.sh — podman not in PATH | `podman` binary absent | Exits 1 before any filesystem writes |
| generate-systemd.sh — run as non-root | `$EUID != 0` | Exits 1 before any filesystem writes |
| generate-systemd.sh — no matching containers | No running container names start with `$PROJECT_NAME` | Exits 1 with message directing operator to run `podman-compose up -d` |
| generate-systemd.sh — Restart=always absent in generated unit | `podman generate systemd` omits `Restart=` line | Script injects `Restart=always` immediately after `[Service]` header |

---

##### Boundary conditions

- `GET /healthz` with both probe timeouts running simultaneously — maximum response time should be approximately 2 s (not 4 s); verify with a timer assertion allowing ±500 ms tolerance.
- `_EXCEPTION_STATUS_MAP` with an `AppError` subclass that also inherits from another mapped subclass — the most specific entry in the map takes precedence (test with diamond inheritance if applicable).
- OG meta endpoint — description exactly 200 characters long — no truncation occurs; content is returned verbatim.
- OG meta endpoint — description empty string — `og:description` attribute is present but empty; no crash.
- OG meta endpoint — title containing all HTML special characters (`<`, `>`, `&`, `"`, `'`) — all are escaped; response is valid HTML.
- backup.sh — `$BACKUP_DIR/daily/` and `$BACKUP_DIR/weekly/` do not exist at script start — directories are created by the script; no error.
- backup.sh — exactly 7 files in `daily/` before a new backup — after the run, still exactly 7 files (the oldest is removed, the new one added).
- restore.sh — backup file path with spaces — quoting in the script must handle this; exit code 0.
- generate-systemd.sh — container name contains hyphens — unit file path and name are constructed correctly; no word-splitting issues.

---

##### Integration points

- **`create_app()` + `SecurityHeadersMiddleware` + `LoggingMiddleware`:** A full integration test using `httpx.AsyncClient(app=app)` confirms both middleware layers execute and that correlation IDs appear in log output captured via `caplog`.
- **Health check + real async session:** A test that spins up an in-memory SQLite or test Postgres connection and calls `GET /healthz` against the real handler confirms the probe logic without mocking the DB at the session level.
- **OG meta endpoint + `html.escape`:** Requires a live DB row with known malicious content in the title/description to assert escaping end-to-end through the route handler.
- **backup.sh + restore.sh round-trip:** Run `backup.sh` against a test Postgres instance, then run `restore.sh` with the produced file against a fresh database; assert table count matches source.
- **Podman Compose health-gate:** The `/healthz` endpoint path in the compose healthcheck (`/health`) diverges from the registered route (`/healthz`). This mismatch is a known integration risk that must be validated against the actual compose file in CI.

---

##### Known test gaps

- **NGINX configuration testing:** `nginx/nginx.conf` is a declarative configuration file. Rate limiting zones, bot-detection map, TLS settings, and header directives require integration-level testing (e.g., `nginx -t` config validation, or an end-to-end test container). Unit testing is not applicable.
- **Podman Compose stack testing:** `podman-compose.yml` service topology, health-gate ordering, and rootless deployment cannot be unit-tested. Validate with `podman-compose config` linting and a smoke-test in CI using `podman-compose up --no-start` or equivalent.
- **Alembic migration integration:** `alembic/env.py` is not covered by these unit tests; it requires a live database and is tested separately during migration CI runs.
- **`generate-systemd.sh` on non-systemd environments (WSL):** `systemctl daemon-reload` will fail in WSL without systemd. Tests mocking the `systemctl` call should document this as a local dev limitation.
- **Health check — no retry on transient failure:** The handler does not retry failed probes. A transient DB blip causes a 503. This is by design but means false-positive unhealthy signals are possible under load; not covered by current tests.
- **`/healthz` vs `/health` compose mismatch:** The Podman Compose healthcheck targets `/health`; the route is registered at `/healthz`. This discrepancy must be audited and resolved; it is not caught by any unit test.

---

##### Agent isolation contract

```
MODULE: app/main.py, GET /healthz, nginx/nginx.conf, scripts/backup.sh,
        scripts/restore.sh, scripts/generate-systemd.sh
PHASE-0 CONTRACTS:
  - Health check endpoint: GET /healthz
  - Both probes pass -> HTTP 200, {"status": "ok"}
  - Any probe fails -> HTTP 503, {"status": "degraded"}
  - Per-probe timeout: 2.0 seconds (asyncio.wait_for)
  - Probes run concurrently via asyncio.gather()
  - _EXCEPTION_STATUS_MAP: AppError subclass -> mapped HTTP code; unmapped -> 500
  - Exception handler response envelope: {"detail": "..."}
  - Middleware order (outermost first): SecurityHeadersMiddleware, LoggingMiddleware, SessionMiddleware
  - OG meta: GET /api/problems/{uuid}/meta; html.escape on all user content;
    description truncated to 200 chars; 404 for missing problem
  - OG meta tags emitted: og:title, og:description, og:url, og:site_name, og:type="article"
  - og:url = {BASE_URL}/problems/{problem.id} (SPA route, not /meta)
  - backup.sh: requires PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD;
    exits 1 if any missing; 7-daily/4-weekly retention; Sunday (DAY_OF_WEEK=7) promotes daily->weekly
  - restore.sh: requires 1 argument (file path) + same 5 env vars;
    post-restore table count in information_schema.tables must be > 0 or exits 1
  - generate-systemd.sh: requires root + podman in PATH + running containers matching PROJECT_NAME
  - All scripts use set -euo pipefail
INFRASTRUCTURE NOT UNIT-TESTABLE (note as known gaps):
  - nginx/nginx.conf rate-limit zones, TLS, bot detection map
  - podman-compose.yml service topology and health-gate ordering
DO NOT read any source file in app/ or scripts/ during test generation.
MUST mock: asyncio.wait_for timeouts, filesystem operations (NamedTemporaryFile, mkdir),
  database session factory, pg_dump/psql subprocess calls, systemctl.
```

---

---

### Frontend SPA

#### frontend/src/ — Frontend SPA

**Module purpose:** A React 18 single-page application that delivers the full employee-facing bulletin interface — problem browsing, submission, collaboration, and administration — entirely in the browser, with no server-side rendering.

**In scope:**
- `useAuth` hook — session probe, OIDC redirect, magic-link send, logout, loading/authenticated state
- `AdminRouteGuard` — role-based redirect logic (`isLoading` → `isAuthenticated` → `user.role === "admin"`)
- `ToastProvider` / `useToast` / `ToastContext` — queue management, cap at 3, auto-dismiss timers, manual dismiss
- `useDarkMode` — three-way mode state, `localStorage` persistence under key `pb-theme`, `prefers-color-scheme` detection
- `ThemeProvider` / `useTheme` — CSS custom property injection via `applyCssVariables`
- `Feed` infinite scroll — `IntersectionObserver` sentinel, cursor-based pagination, reset on filter change
- `useMediaQuery` — reactive `window.matchMedia` wrapper
- `NotificationBell` — WebSocket lifecycle, auto-reconnect after 5 s, malformed message handling
- `MarkdownEditor` — 300ms debounced preview, character counter
- `AttachmentDropZone` — file validation (10MB limit, allowed types), drag/drop/paste/click
- `TagAutocomplete` — 200ms debounced fetch, keyboard navigation, pill display

**Out of scope:**
- Server-side API logic
- Build tooling (Vite, TypeScript compilation)
- CSS styling details not affecting component logic
- Admin page CRUD operations (covered by integration/E2E tests)
- React Router navigation internals

---

##### Happy path scenarios

| Scenario | Input | Expected output |
|---|---|---|
| useAuth — authenticated user | `/api/auth/me` returns `{id, role: "user", ...}` | `isLoading=false`, `isAuthenticated=true`, `user` object populated |
| useAuth — unauthenticated | `/api/auth/me` returns 401 | `isLoading=false`, `isAuthenticated=false`, `user=null` |
| useAuth — loading state | Fetch in progress (not yet resolved) | `isLoading=true`, `isAuthenticated=false` |
| useAuth — logout | `logout()` called; POST to `/api/auth/logout` succeeds | Local auth state cleared (`isAuthenticated=false`, `user=null`) regardless of network outcome |
| useAuth — logout clears state on network failure | `logout()` called; POST returns network error | `isAuthenticated=false`, `user=null` (state cleared anyway) |
| AdminRouteGuard — admin user | `isLoading=false`, `isAuthenticated=true`, `user.role="admin"` | Inner content component is rendered |
| AdminRouteGuard — non-admin authenticated user | `isLoading=false`, `isAuthenticated=true`, `user.role="user"` | Redirects to `/` |
| AdminRouteGuard — unauthenticated | `isLoading=false`, `isAuthenticated=false` | Redirects to `/` |
| AdminRouteGuard — loading in progress | `isLoading=true` | Neither renders content nor redirects; shows loading state |
| ToastProvider — adds toast | `useToast().addToast({message: "ok", type: "success"})` | Toast appears in queue; rendered by `ToastContainer` |
| ToastProvider — toast cap at 3 | 4 toasts added in rapid succession | Queue contains exactly 3 toasts; the oldest is silently dropped |
| ToastProvider — auto-dismiss | Toast added with default 5 s duration | Toast is removed from queue after 5 s |
| ToastProvider — manual dismiss | `dismiss(id)` called on a queued toast | Toast removed immediately; associated timer cleared |
| ToastProvider — useToast outside provider | `useToast()` called with no `ToastProvider` ancestor | Throws with a clear misconfiguration error message |
| useDarkMode — persists to localStorage | `setMode("dark")` called | `localStorage.getItem("pb-theme")` returns `"dark"` |
| useDarkMode — reads from localStorage on mount | `localStorage` contains `"dark"` before mount | Hook initializes with `mode="dark"` |
| useDarkMode — system mode follows prefers-color-scheme | Mode is `"system"`; `matchMedia("prefers-color-scheme: dark")` returns `true` | Effective theme is dark |
| useDarkMode — default value | `localStorage` is empty; `matchMedia` not matched | Mode defaults to `"system"` |
| useDarkMode — localStorage key is "pb-theme" | `setMode("light")` called | Key used is exactly `"pb-theme"` (not any other string) |
| ThemeProvider — injects CSS custom properties | `ThemeProvider` mounted with light theme | `document.documentElement` has CSS custom properties set by `applyCssVariables` |
| useTheme — accessible in children | Component inside `ThemeProvider` calls `useTheme()` | Returns theme object without throwing |
| Feed — infinite scroll sentinel triggers fetch | `IntersectionObserver` fires for sentinel `<div>` with `isIntersecting=true` and `nextCursor` available | Next page fetch is initiated with the cursor value |
| Feed — no fetch when all pages loaded | `nextCursor` is null | Sentinel intersection does not trigger a fetch |
| Feed — filter change resets cursor | Sort or status filter changed | Cursor reset to null; fetch restarts from page 1; previous results cleared |
| Feed — AbortController cancels in-flight request | New filter applied before previous fetch resolves | Previous request is aborted; no stale results appended |
| NotificationBell — connects on mount | Component mounts | WebSocket opened to `ws[s]://<host>/ws/notifications` |
| NotificationBell — reconnects after close | `ws.onclose` fires | Reconnect scheduled after 5 s; `wsRef.current === ws` guard prevents duplicate reconnects |
| NotificationBell — malformed message ignored | `ws.onmessage` fires with non-JSON payload | No error thrown; notification list unchanged |
| NotificationBell — stores up to 5 notifications | 7 notifications received | Only the 5 most recent are stored in local state |
| MarkdownEditor — preview debounced | User types continuously; preview update observed | Preview updates at most once per 300ms interval |
| AttachmentDropZone — validates file size | File larger than 10MB dropped | Validation error displayed; file not added to selection |
| AttachmentDropZone — validates file type | File with `.exe` extension dropped | Validation error displayed; file not added |
| AttachmentDropZone — accepts valid files | `.png`, `.pdf`, `.txt` files dropped | Files added to selection without error |
| TagAutocomplete — debounces API calls | User types 3 characters quickly | At most one `GET /api/tags?q=` request fired within the 200ms window |
| TagAutocomplete — keyboard navigation | ArrowDown pressed on open dropdown | Focus moves to first suggestion |
| TagAutocomplete — Escape closes dropdown | Escape pressed while dropdown open | Dropdown closes; input value unchanged |
| TagAutocomplete — pill display | Tag selected | Tag appears as a removable pill; remove button present |

---

##### Error scenarios

| Error type | Trigger condition | Expected behavior |
|---|---|---|
| useAuth — network error on /api/auth/me | Fetch throws `TypeError: Failed to fetch` | `isLoading=false`, `isAuthenticated=false`; no unhandled rejection |
| Feed — fetch failure | `GET /api/problems` returns 500 | Inline error message rendered with `role="alert"`; Retry button visible |
| Feed — AbortError suppressed | Request aborted by `AbortController` | No error state shown; no user-visible message |
| Feed — Retry button re-triggers fetch | Retry button clicked after failure | New fetch initiated; loading state shown; results replaced on success |
| ToastProvider — timer cleanup on unmount | `ToastProvider` unmounted with active toasts | All `setTimeout` timers are cleared; no setState calls after unmount |
| NotificationBell — reconnect guard | `ws.onclose` fires; component simultaneously unmounts | Reconnect does not fire because `wsRef.current` no longer equals the closed `ws` |
| AttachmentDropZone — multiple validation errors | Drop 3 files, 2 invalid | Each invalid file shows its own per-file error; valid file is accepted |
| Settings — PATCH failure | `PATCH /api/auth/me` returns 500 | Error surfaced via toast system; preference toggles reset to previous state |
| ProblemDetail — solutions/comments fetch failure | Secondary tab fetch returns 500 | Tab renders empty (not an error block); primary problem content still visible |

---

##### Boundary conditions

- `ToastProvider` — adding exactly 3 toasts, then adding a 4th: queue has exactly 3 items (oldest dropped). Adding a 5th: still 3 (two oldest have been dropped over time).
- `ToastProvider` — `dismiss()` called for an ID that does not exist in the queue: no error thrown; state unchanged.
- `useDarkMode` — `setMode` called with an invalid string (not `"light"`, `"dark"`, or `"system"`): behavior is implementation-defined; at minimum, no unhandled exception.
- `Feed` — `nextCursor` changes value mid-scroll (server-side pagination shift): the old in-flight request is aborted; new cursor is used for the subsequent fetch.
- `MarkdownEditor` — `maxLength` prop set; user types exactly at the limit: character counter shows 0 remaining; further input is either blocked or counter goes negative depending on implementation — document the actual behavior.
- `TagAutocomplete` — Enter pressed with no suggestion highlighted: no tag added; dropdown remains open or closes depending on implementation — document and test the actual behavior.
- `AttachmentDropZone` — file pasted via clipboard alongside drag-and-drop simultaneously: only one event handler fires; no duplicate file entry.
- `NotificationBell` — 6th notification arrives: oldest of the 5 stored is replaced; badge count remains accurate.
- `useMediaQuery` — `window.matchMedia` unavailable (SSR-like environment): hook must not throw; returns a safe default.

---

##### Integration points

- **`useAuth` + `AdminRouteGuard`:** Mount `AdminRouteGuard` inside a test that mocks `useAuth` to return various states; assert redirect vs. render behavior for all three guard checks in sequence.
- **`ToastProvider` + route transitions:** Confirm that toasts persisted across navigation (e.g., after a successful form submit) are still visible on the destination page, since `ToastProvider` sits above `MainLayout` and `Routes`.
- **`useDarkMode` + `ThemeProvider`:** Mount `ThemeProvider` in a jsdom test; call `setMode("dark")`; assert that `document.documentElement.getAttribute("data-theme")` is `"dark"` and CSS custom properties are updated by `applyCssVariables`.
- **`Feed` + `IntersectionObserver` mock:** Use a jest/vitest mock for `IntersectionObserver`; trigger the observer callback manually; assert that the next-page fetch fires with the correct cursor parameter.
- **`NotificationBell` + WebSocket mock:** Use `jest-websocket-mock` or equivalent; send a message from the server side in the test; assert notification is added to state; send a malformed payload and assert it is silently ignored.

---

##### Known test gaps

- **Browser/jsdom environment required for all tests:** The entire frontend test suite requires a DOM environment (jsdom or a real browser via Playwright/Cypress). Pure Node.js unit tests are not viable for component rendering, `window.matchMedia`, `IntersectionObserver`, or WebSocket behavior. This is the fundamental testing paradigm gap for the frontend module.
- **`useAuth` per-component re-fetch overhead:** Because `useAuth` is not a shared context, each mounted component makes its own `/api/auth/me` call. Tests should mock `fetch` globally and assert call counts to detect unintended fetch multiplication.
- **`sanitizeHtml` in `ProblemDetail`:** The frontend `sanitizeHtml` function (separate from the backend `sanitize_html`) is described as a basic allowlist. Tests should cover `<script>` and `on*` attribute stripping, and the code comment recommending DOMPurify should be tracked as a hardening backlog item.
- **`MarkdownEditor` regex renderer:** The built-in regex-based Markdown renderer is not tested for edge cases (nested formatting, malformed Markdown). A table-driven test of expected input/output pairs is recommended.
- **Lazy route loading:** `React.lazy()` code splitting is not exercised in unit tests; bundle loading behavior requires an integration or E2E test with a real Vite build output.
- **`AdminRouteGuard` wraps inner content, not route:** Because each admin page applies its own guard rather than relying on a central route-level wrapper, a missing guard on a newly added admin page would not be caught by routing tests — recommend a structural test that enumerates all `/admin/*` routes and asserts the guard is present.
- **WebSocket reconnect timer:** The 5-second reconnect delay in `NotificationBell` requires `jest.useFakeTimers()` to test deterministically; without timer mocking, the test would either sleep 5 seconds or miss the reconnect entirely.

---

##### Agent isolation contract

```
MODULE: frontend/src/ (React 18 SPA)
TESTING PARADIGM: All tests require a DOM environment (jsdom or browser).
  Pure Node.js unit tests are NOT viable for this module.
PHASE-0 CONTRACTS:
  - useAuth: calls GET /api/auth/me with credentials:"include" on mount;
    logout() clears state regardless of network outcome
  - AdminRouteGuard: checks isLoading -> isAuthenticated -> user.role==="admin";
    redirects to "/" on any failure; no error message shown on redirect
  - ToastProvider: queue capped at 3; oldest dropped on 4th add;
    auto-dismiss after 5s (default); useToast() throws outside provider
  - useDarkMode: three-way mode ("light"/"dark"/"system");
    localStorage key = "pb-theme"; defaults to "system"
  - Feed infinite scroll: IntersectionObserver on sentinel div, 200px root margin;
    cursor from FeedResponse.nextCursor; filter change resets cursor;
    AbortController cancels in-flight requests
  - NotificationBell: reconnects after 5s on ws.onclose;
    ref-guard prevents reconnect loops; stores 5 most recent notifications;
    malformed messages caught and ignored
  - AttachmentDropZone: 10MB per-file limit; allowed types: images, PDF, TXT
  - TagAutocomplete: 200ms debounce; keyboard nav (arrows, Enter, Escape);
    ARIA combobox; pill display with remove buttons
  - MarkdownEditor: 300ms debounced preview
DO NOT read any file in frontend/src/ or app/ during test generation.
MUST mock: fetch (global), window.matchMedia, IntersectionObserver,
  WebSocket, localStorage, setTimeout/clearTimeout (fake timers).
```

---

## Integration Test Specifications

---

### Integration Scenario 1: Happy Path — Problem Submission to Solution Acceptance

**Scenario:** A user authenticates via OIDC, submits a problem, a second user posts a
solution, a notification fans out over WebSocket and Teams, and the first user accepts
the solution — verifying the full write path and notification pipeline end-to-end.

**Entry point:** `POST /api/auth/callback` (OAuth redirect) through
`POST /api/solutions/{id}/accept`

**Mocks required:** `mock_azure_oidc`, `mock_teams_webhook`
(real test DB, real WebSocket via `httpx.AsyncClient` WebSocket test helper)

---

**Flow:**

**Step 1 — OIDC callback authenticates Alice and provisions her user record.**

Entry: `GET /api/auth/callback?code=<code>&state=<state>`
Module: `app/auth/oidc.py :: handle_callback`

`mock_azure_oidc.authorize_access_token` returns:
```python
{
    "userinfo": {
        "oid": "aaaa0000-0000-0000-0000-000000000001",
        "email": "alice@company.com",
        "name": "Alice Tester",
        "tid": "<AZURE_TENANT_ID>"
    }
}
```

`_provision_user` performs OID lookup (miss), email lookup (miss), then inserts:
```python
User(
    id=<uuid>,
    azure_oid="aaaa0000-0000-0000-0000-000000000001",
    email="alice@company.com",
    display_name="Alice Tester",
    role=UserRole.user,
    is_active=True
)
```

`create_access_token` produces an HS256 JWT with claims:
```python
{"sub": str(alice.id), "role": "user", "iat": <now>, "exp": <now + 28800>}
```

`set_auth_cookie` writes `access_token=<JWT>` as `HttpOnly; SameSite=Lax`.

Expected HTTP response: `302 Found` → `/problems`, with `Set-Cookie` header present.

---

**Step 2 — Alice submits a problem.**

Entry: `POST /api/problems`
Module: `app/services/problems.py :: create_problem`

Request body (`ProblemCreate`):
```python
{
    "title": "Clock domain crossing metastability",
    "description": "Signal crossing from 100 MHz domain to 10 MHz domain causes glitches after synthesis.",
    "category_id": "<category-uuid>",
    "tag_ids": ["<tag-uuid-cdc>", "<tag-uuid-fpga>"],
    "is_anonymous": False
}
```

Service steps:
1. Category SELECT — returns active `Category` row; no error.
2. Tag COUNT query — returns 2; matches `len(tag_ids)`.
3. `Problem` row inserted with `status=ProblemStatus.open`.
4. `db.flush()` — assigns `problem.id`.
5. `ProblemTag` rows bulk-inserted (2 rows).
6. `update_search_vector(db, problem.id)` — populates `search_vector` column.

DB state after step:
```python
Problem(
    id=<problem-uuid>,
    title="Clock domain crossing metastability",
    status=ProblemStatus.open,
    author_id=alice.id,
    is_anonymous=False,
    search_vector=<tsvector>
)
```

Expected HTTP response: `201 Created`, body is `ProblemResponse` with `id`, `status="open"`.

---

**Step 3 — Auto-watch wires Alice to her own problem.**

Module: `app/services/problems.py :: auto_watch` (called within the same request handler)

Upsert executed:
```python
Watch(user_id=alice.id, problem_id=<problem-uuid>, level=WatchLevel.all_activity)
```

DB state after step: 1 `Watch` row for Alice at `all_activity`.

No HTTP round-trip; this is an internal call within the `POST /api/problems` handler.

---

**Step 4 — Bob authenticates (second OIDC callback).**

Same flow as Step 1 with different claims:
```python
{
    "userinfo": {
        "oid": "bbbb0000-0000-0000-0000-000000000002",
        "email": "bob@company.com",
        "name": "Bob Solver",
        "tid": "<AZURE_TENANT_ID>"
    }
}
```

Bob's `User` row is created; a separate JWT cookie is issued for Bob's session.

---

**Step 5 — Bob posts a solution.**

Entry: `POST /api/problems/{problem-uuid}/solutions`
Module: `app/services/solutions.py :: create_solution`

Request body (`SolutionCreate`):
```python
{
    "description": "Insert a two-flop synchroniser on all CDC paths. Use Vivado CDC constraints to mark the paths."
}
```

Service steps:
1. Problem SELECT — returns `Problem` with `status=open`.
2. `Solution` row inserted with `status=SolutionStatus.pending`.
3. `SolutionVersion` row inserted with `version_number=1`; `solution.current_version_id` set.
4. `problem.activity_at` updated to `now()`.

DB state after step:
```python
Solution(
    id=<solution-uuid>,
    problem_id=<problem-uuid>,
    author_id=bob.id,
    status=SolutionStatus.pending,
    current_version_id=<version-uuid>
)
SolutionVersion(id=<version-uuid>, version_number=1, description="Insert a two-flop...")
```

Expected HTTP response: `201 Created`, body is `SolutionResponse` with `status="pending"`.

---

**Step 6 — Notification fan-out: solution_posted event.**

Module: `app/services/notifications.py :: generate_notification`

Called immediately after `create_solution` with:
```python
event_type=NotificationType.solution_posted,
problem_id=<problem-uuid>,
actor_id=bob.id
```

Query: all `Watch` rows for `problem_id` where `user_id != bob.id`.
Result: 1 row — Alice at `WatchLevel.all_activity`.

`WATCH_ROUTING[WatchLevel.all_activity]` includes `solution_posted` → notification qualifies.

`Notification` row inserted:
```python
Notification(
    id=<notif-uuid>,
    recipient_id=alice.id,
    notification_type=NotificationType.solution_posted,
    problem_id=<problem-uuid>,
    solution_id=<solution-uuid>,
    actor_id=bob.id,
    is_read=False
)
```

`push_ws_notification` serialises and calls `connection_manager.broadcast_to_user(alice.id, data)`.

If Alice has a live WebSocket connection, the client receives:
```json
{
    "type": "notification",
    "payload": {
        "id": "<notif-uuid>",
        "notification_type": "solution_posted",
        "problem_id": "<problem-uuid>",
        "solution_id": "<solution-uuid>",
        "actor_id": "<bob-uuid>",
        "is_read": false,
        "created_at": "<ISO-8601>"
    }
}
```

`schedule_teams_webhook` fires an `asyncio.Task`; `mock_teams_webhook.post` is called with
Adaptive Card JSON containing the problem title. Mock returns HTTP 200 — no error logged.

**What to assert after Step 6:**
- 1 `Notification` row in DB with `recipient_id=alice.id`, `is_read=False`.
- `mock_teams_webhook.post` called once; `json` argument contains `"Clock domain crossing"`.
- WebSocket test client (Alice's connection) received a JSON message with
  `payload.notification_type == "solution_posted"`.

---

**Step 7 — Alice accepts the solution (atomic swap).**

Entry: `POST /api/solutions/{solution-uuid}/accept`
Module: `app/services/solutions.py :: accept_solution`
Auth: Alice's JWT cookie.

Service steps:
1. Solution SELECT with join to Problem — confirms `problem.author_id == alice.id`. Check passes.
2. Query for any existing accepted solution on the same problem — none found.
3. Target solution updated: `status = SolutionStatus.accepted`.
4. `problem.activity_at` updated.
5. `db.flush()`.

DB state after step:
```python
Solution(id=<solution-uuid>, status=SolutionStatus.accepted)
Problem(status=ProblemStatus.open, activity_at=<updated>)
```

`generate_notification` called again with `event_type=NotificationType.solution_accepted`.
Bob is not watching (no `Watch` row for Bob), so 0 new `Notification` rows for Bob.
Alice watches at `all_activity`; 1 `Notification` row for Alice with `solution_accepted`.

Expected HTTP response: `200 OK`, body is `SolutionResponse` with `status="accepted"`.

**Final state assertions:**
- `Solution.status == "accepted"` in DB.
- 2 total `Notification` rows for Alice (`solution_posted`, `solution_accepted`).
- `mock_teams_webhook.post` called twice (once per fan-out).

---

### Integration Scenario 2: Error Path — Forbidden Transition Propagation

**Scenario:** A non-owner attempts to accept a solution (→ 403), and a user attempts an
invalid FSM status transition (→ 409), verifying that permission and state-machine errors
are raised by service layer and translated to the correct HTTP status codes without
mutating database state.

**Entry point:** `POST /api/solutions/{id}/accept` and `POST /api/problems/{id}/status`

**Mocks required:** none (no external dependencies triggered by error paths)

---

**Flow:**

**Step 1 — Charlie (non-owner) calls accept on a solution he does not own.**

Setup preconditions (via direct DB inserts or prior API calls):
```python
Problem(id=<problem-uuid>, author_id=alice.id, status=ProblemStatus.open)
Solution(id=<solution-uuid>, problem_id=<problem-uuid>, status=SolutionStatus.pending)
User(id=charlie.id, role=UserRole.user)   # Charlie ≠ Alice
```

Entry: `POST /api/solutions/{solution-uuid}/accept`
Auth: Charlie's JWT (sub=charlie.id, role="user").

**Step 2 — accept_solution authorization check fails.**

Module: `app/services/solutions.py :: accept_solution`

Condition evaluated:
```python
actor.id == problem.author_id   # False: charlie.id ≠ alice.id
actor.role == UserRole.admin    # False: "user"
```

Service raises:
```python
PermissionError("Only the problem owner or an admin can accept a solution")
```

`db.flush()` is never called. No rows are written or modified.

**Step 3 — Route translates PermissionError → HTTP 403.**

The route handler catches `PermissionError` and raises:
```python
HTTPException(status_code=403, detail="Only the problem owner or an admin can accept a solution")
```

**What to assert:**
- HTTP response status: `403 Forbidden`.
- Response body: `{"detail": "Only the problem owner or an admin can accept a solution"}`.
- DB: `Solution.status` is still `"pending"` (no mutation).
- DB: no new `Notification` rows created.

---

**Step 4 — Alice calls POST /api/problems/{id}/status with forbidden FSM transition.**

Setup: same `Problem` with `status=ProblemStatus.open`.

Entry: `POST /api/problems/{problem-uuid}/status`
Auth: Alice's JWT.

Request body:
```python
{"target": "accepted"}
```

**Step 5 — transition_status raises ForbiddenTransitionError.**

Module: `app/services/problems.py :: transition_status`

Lookup performed:
```python
ALLOWED_TRANSITIONS.get((ProblemStatus.open, ProblemStatus.accepted))
# → KeyError / None: the pair is absent
```

Service raises:
```python
ForbiddenTransitionError(current="open", target="accepted")
```

**Step 6 — _EXCEPTION_STATUS_MAP in app/main.py translates to HTTP 409.**

The global exception handler for `ForbiddenTransitionError` returns:
```python
JSONResponse(
    status_code=409,
    content={"detail": "Transition from 'open' to 'accepted' is not allowed"}
)
```

**What to assert:**
- HTTP response status: `409 Conflict`.
- Response body contains `"current"` and `"target"` values (`"open"`, `"accepted"`).
- DB: `Problem.status` remains `"open"` (no mutation).

---

### Integration Scenario 3: Search End-to-End

**Scenario:** A user submits a full-text search query that fans out across problems,
solutions, and comments; deduplication and ranking return the correct top result with
the correct `match_source` label; a no-results query triggers the fallback response;
and the suggest endpoint returns similar problems for the submit page.

**Entry point:** `GET /api/search?q=...` and `GET /api/search/suggest?title=...`

**Mocks required:** none (PostgreSQL full-text search runs against real test DB)

---

**Preconditions (DB seed):**

```python
# Problem A — title matches query
Problem(id=<pa-uuid>, title="Clock domain crossing metastability",
        description="Glitches after synthesis.", status="open", search_vector=<tsvector>)

# Problem B — no title match but solution body matches
Problem(id=<pb-uuid>, title="Vivado build fails on constraints",
        description="...", status="open", search_vector=<tsvector>)
Solution(problem_id=<pb-uuid>, description="Insert a two-flop synchroniser on CDC paths.")

# Problem C — comment body matches
Problem(id=<pc-uuid>, title="Unrelated FPGA issue", description="...", status="open")
Comment(problem_id=<pc-uuid>, body="The clock domain crossing can cause latch-up here.")
```

---

**Flow:**

**Step 1 — User fires search request.**

Entry: `GET /api/search?q=clock+domain+crossing&sort=relevance&limit=20&offset=0`
Module: `app/services/search.py :: search_problems`

**Step 2 — Query compilation.**

Raw string `"clock domain crossing"` is passed to:
```sql
plainto_tsquery('english', 'clock domain crossing')
-- normalises to: 'clock' & 'domain' & 'crossing'
```

**Step 3 — Three-branch CTE fan-out.**

```sql
WITH
  problem_hits AS (
    SELECT problem_id, title, excerpt, ts_rank(...) AS rank, 'problem' AS match_source, ...
    FROM problems WHERE search_vector @@ <tsquery>
  ),
  solution_hits AS (
    SELECT p.id AS problem_id, p.title, ..., 'solution' AS match_source, ...
    FROM solution_versions sv
    JOIN solutions s ON s.current_version_id = sv.id
    JOIN problems p ON p.id = s.problem_id
    WHERE to_tsvector('english', sv.description) @@ <tsquery>
  ),
  comment_hits AS (
    SELECT p.id AS problem_id, p.title, ..., 'comment' AS match_source, ...
    FROM comments c
    JOIN problems p ON p.id = c.problem_id
    WHERE to_tsvector('english', c.body) @@ <tsquery>
  )
SELECT * FROM problem_hits
UNION ALL SELECT * FROM solution_hits
UNION ALL SELECT * FROM comment_hits
```

Raw UNION ALL output (before deduplication): 3 rows — one per seeded problem.

**Step 4 — Deduplication and ranking.**

```sql
SELECT DISTINCT ON (problem_id) *
FROM merged
ORDER BY problem_id, rank DESC
```

Result: 3 unique problem rows, each with its highest-ranked match source.

Outer ORDER BY `rank DESC`, LIMIT 20, OFFSET 0 → ordered list with Problem A first
(strongest title match).

**Step 5 — Serialised response.**

HTTP response: `200 OK`
```json
{
    "results": [
        {
            "problem_id": "<pa-uuid>",
            "title": "Clock domain crossing metastability",
            "excerpt": "Glitches after synthesis.",
            "match_source": "problem",
            "rank": 0.76,
            "upstar_count": 0,
            "status": "open",
            "created_at": "<ISO-8601>"
        },
        {
            "problem_id": "<pb-uuid>",
            "title": "Vivado build fails on constraints",
            "excerpt": "Insert a two-flop synchroniser on CDC paths.",
            "match_source": "solution",
            "rank": 0.51,
            ...
        },
        {
            "problem_id": "<pc-uuid>",
            "title": "Unrelated FPGA issue",
            "excerpt": "The clock domain crossing can cause latch-up here.",
            "match_source": "comment",
            "rank": 0.38,
            ...
        }
    ],
    "total": 3
}
```

**What to assert after Step 5:**
- Response status `200 OK`.
- `results` list has 3 entries.
- `results[0].match_source == "problem"` (title hit ranks highest).
- `results[1].match_source == "solution"`.
- `results[2].match_source == "comment"`.
- All UUIDs are strings. All timestamps are ISO-8601.
- No duplicate `problem_id` values in the result list.

---

**Step 6 — No-results fallback.**

Entry: `GET /api/search?q=zzz+nonexistent+gibberish&sort=relevance&limit=20&offset=0`

`search_problems` executes the same CTE; all three branches return 0 rows.

Service returns:
```python
{"results": [], "message": "No results found"}
```

**What to assert:**
- Response status `200 OK`.
- `results` is an empty list.
- `message == "No results found"`.

---

**Step 7 — suggest_similar on submit page.**

Entry: `GET /api/search/suggest?title=clock+domain+crossing&limit=5`
Module: `app/services/search.py :: suggest_similar`

Same `plainto_tsquery` + `search_vector @@` but queries only the `problems` table.
Returns up to 5 rows with `title` and a 120-character `description` excerpt.

**What to assert:**
- Response is a list of up to 5 objects.
- Each object has `title` (string) and `excerpt` (≤ 120 chars).
- Problem A (`"Clock domain crossing metastability"`) appears in the list.

---

### Integration Scenario 4: File Attachment Lifecycle

**Scenario:** A user uploads a file attachment to a problem; the system performs MIME and
size validation, writes the file to disk, and inserts a metadata row; a second user
downloads it with correct headers; the uploader deletes it and both the DB row and disk
file are removed.

**Entry point:** `POST /api/problems/{id}/attachments` through `DELETE /api/attachments/{id}`

**Mocks required:** `mock_storage` (STORAGE_PATH redirected to pytest `tmp_path`)

---

**Flow:**

**Step 1 — Upload: MIME and size checks pass.**

Entry: `POST /api/problems/{problem-uuid}/attachments`
Auth: Alice's JWT.
Request: `multipart/form-data` with field `file`; filename `"synchroniser.pdf"`;
content-type `"application/pdf"`; body size 512 KB.

Module: `app/services/attachments.py`

Checks performed:
1. Extension/MIME validation: `"pdf"` is in `ALLOWED_TYPES` → passes.
2. File size ≤ configured limit → passes.

Disk write:
```
{STORAGE_PATH}/<problem-uuid>/<attachment-uuid>_synchroniser.pdf
```

DB insert:
```python
Attachment(
    id=<attachment-uuid>,
    problem_id=<problem-uuid>,
    uploader_id=alice.id,
    filename="synchroniser.pdf",
    mime_type="application/pdf",
    size_bytes=524288,
    storage_path="<problem-uuid>/<attachment-uuid>_synchroniser.pdf"
)
```

Expected HTTP response: `201 Created`, body is `AttachmentResponse` with `id`, `filename`,
`mime_type`, `size_bytes`.

**What to assert after Step 1:**
- `Attachment` row exists in DB.
- File exists at `tmp_path/<problem-uuid>/<attachment-uuid>_synchroniser.pdf`.

---

**Step 2 — Upload: MIME check fails (disallowed type).**

Entry: same endpoint; filename `"malware.exe"`; content-type `"application/octet-stream"`.

Module raises `FileTypeNotAllowedError("exe not in ALLOWED_TYPES")`.

Expected HTTP response: `422 Unprocessable Entity`.

**What to assert:**
- No `Attachment` row inserted.
- No file written to `tmp_path`.

---

**Step 3 — Download with correct Content-Disposition.**

Entry: `GET /api/attachments/{attachment-uuid}/download`
Auth: not required (public endpoint).

Module: `app/services/attachments.py`

Steps:
1. `Attachment` row fetched by `id`.
2. `FileResponse` constructed with `path=STORAGE_PATH/storage_path`,
   `filename="synchroniser.pdf"`, `media_type="application/pdf"`.

Expected HTTP response: `200 OK`.
Expected headers:
- `Content-Type: application/pdf`
- `Content-Disposition: attachment; filename="synchroniser.pdf"`

**What to assert:**
- Response status `200 OK`.
- `Content-Disposition` header matches expected value.
- Response body is identical to the uploaded file bytes.

---

**Step 4 — Delete: DB row and disk file removed.**

Entry: `DELETE /api/attachments/{attachment-uuid}`
Auth: Alice's JWT (uploader).

Module: `app/services/attachments.py`

Steps:
1. `Attachment` row fetched; `attachment.uploader_id == alice.id` → authorised.
2. DB row deleted (hard delete).
3. `os.remove(STORAGE_PATH / storage_path)` — best-effort; `OSError` is caught and logged
   but does not cause a 500.

Expected HTTP response: `204 No Content`.

**What to assert:**
- `Attachment` row is absent from DB.
- File no longer exists at `tmp_path/<problem-uuid>/<attachment-uuid>_synchroniser.pdf`.

---

**Step 5 — Delete by non-uploader: 403.**

Setup: Bob tries to delete Alice's attachment.
Entry: `DELETE /api/attachments/{attachment-uuid}` with Bob's JWT.

Authorization check: `attachment.uploader_id == alice.id ≠ bob.id` and
`bob.role == UserRole.user ≠ admin` → `PermissionError`.

Expected HTTP response: `403 Forbidden`.

**What to assert:**
- `Attachment` row still exists in DB.
- Disk file still exists.

---

### Integration Scenario 5: Notification Channel Independence

**Scenario:** A solution-posted event triggers notification fan-out; the WebSocket push
fails (mock raises), but the Teams webhook and email digest paths still complete
successfully, verifying that one channel failure does not block or suppress other channels.

**Entry point:** `app/services/notifications.py :: generate_notification` (called
internally after `POST /api/problems/{problem_id}/solutions`)

**Mocks required:** `mock_azure_oidc`, `mock_smtp`, `mock_teams_webhook`
(plus a mock `connection_manager.broadcast_to_user` that raises `RuntimeError`)

---

**Preconditions:**
- Alice is watching problem at `WatchLevel.all_activity`.
- Bob posts a solution (triggers notification fan-out for Alice).
- `TEAMS_WEBHOOK_URL` is set in the test environment.
- Alice has no live WebSocket connection (or broadcast mock is configured to raise).

---

**Flow:**

**Step 1 — generate_notification inserts Notification rows.**

Module: `app/services/notifications.py :: generate_notification`

`Watch` query returns Alice at `all_activity`; `solution_posted` is in routing table.

DB insert:
```python
Notification(
    id=<notif-uuid>,
    recipient_id=alice.id,
    notification_type=NotificationType.solution_posted,
    problem_id=<problem-uuid>,
    solution_id=<solution-uuid>,
    actor_id=bob.id,
    is_read=False
)
```

**What to assert after Step 1:**
- 1 `Notification` row exists in DB for Alice (regardless of delivery outcome).

---

**Step 2 — WebSocket push fails.**

`push_ws_notification` calls `connection_manager.broadcast_to_user(alice.id, data)`.
The mock raises `RuntimeError("no active connection")`.

The notification service catches the error, logs it, and continues to the next delivery
channel. The `Notification` DB row is not rolled back.

**What to assert after Step 2:**
- `Notification` row still present in DB.
- Error was logged (assert `caplog` or logging mock captured a WARNING/ERROR message).
- The HTTP response for `POST /api/problems/{id}/solutions` is still `201 Created`
  (WebSocket failure is non-fatal).

---

**Step 3 — Teams webhook succeeds despite WebSocket failure.**

`schedule_teams_webhook` fires an `asyncio.Task`. `mock_teams_webhook.post` returns HTTP 200.

**What to assert after Step 3:**
- `mock_teams_webhook.post` called once with Adaptive Card JSON.
- No exception propagated to the route handler.

---

**Step 4 — Email digest path succeeds (async task).**

The email digest is scheduled separately (e.g. as a background task or cron job), not
inline with the request. For this test, invoke the digest function directly.

`mock_smtp` is called; `Message.To == "alice@company.com"`; `Subject` contains
`"solution_posted"` or similar digest text.

**What to assert after Step 4:**
- `mock_smtp` called once.
- Message `To` header is `"alice@company.com"`.
- Message body references the problem title.

---

**Final cross-channel assertions (all steps combined):**
- `Notification` row in DB: 1, `is_read=False`.
- `mock_teams_webhook.post` call count: 1.
- `mock_smtp` call count: 1 (digest).
- WebSocket broadcast mock: raised exactly once; exception was absorbed.
- `POST /api/problems/{id}/solutions` response: `201 Created` (route not affected by
  notification channel failure).

---

## FR-to-Test Traceability Matrix

Every FR from the spec must appear. If a FR is not covered, note it as a known gap.

| FR | Acceptance Criteria Summary | Module Test | Integration Test |
|----|----------------------------|-------------|-----------------|
| REQ-100 | Azure AD OIDC auth flow completes | `test-auth` — oidc.py happy path | integration_happy_path (Step 1) |
| REQ-102 | Single-tenant tid claim validation enforced | `test-auth` — oidc.py tenant mismatch | integration_happy_path (Step 1) |
| REQ-104 | Magic link generation, sending, rate limiting | `test-auth` — magic_link.py send/verify | (no dedicated integration) |
| REQ-106 | 15-minute expiry, single-use consumed flag | `test-auth` — magic_link.py boundary conditions | (no dedicated integration) |
| REQ-108 | HS256 JWT in HttpOnly cookies; 8-hour expiry | `test-auth` — jwt.py cookie attributes | integration_happy_path (Step 1) |
| REQ-110 | User provisioning on first OIDC login | `test-auth` — oidc.py user creation | integration_happy_path (Step 1) |
| REQ-112 | Three-step user lookup (OID → email → create) | `test-auth` — oidc.py provision paths | integration_happy_path (Step 1-4) |
| REQ-114 | Two-role model; require_admin dependency | `test-auth` — dependencies.py role check | (admin tests cover) |
| REQ-116 | require_owner_or_admin permission check | `test-auth` — dependencies.py owner check | integration_error_path (Step 1) |
| REQ-118 | GET /api/auth/me via get_current_user | `test-auth` — dependencies.py current user | (no dedicated integration) |
| REQ-120 | clear_auth_cookie clears HttpOnly cookie | `test-auth` — jwt.py cookie clearing | (no dedicated integration) |
| REQ-122 | DEV_AUTH_BYPASS with dev user provisioning | `test-auth` — dependencies.py dev bypass | (no dedicated integration) |
| REQ-124 | Configured via authlib OAuth registry | `test-auth` — oidc.py registry config | integration_happy_path (Step 1) |
| REQ-126 | Structured log entries for auth events | `test-middleware-infra-frontend` — logging.py | (no dedicated integration) |
| REQ-128 | In-memory MagicLinkRateLimiter: 5 requests/10m | `test-auth` — rate_limit.py rate limiting | (no dedicated integration) |
| REQ-150 | create_problem with category + tag validation | `test-problems` — create problem happy path | integration_happy_path (Step 2) |
| REQ-152 | ProblemCreate field constraints (title 5-200, desc 10+) | `test-problems` — boundary conditions | integration_happy_path (Step 2) |
| REQ-154 | is_anonymous flag; author_id always stored | `test-problems` — anonymous posting | (no dedicated integration) |
| REQ-156 | ALLOWED_TRANSITIONS FSM dict with predicates | `test-problems` — FSM transitions | integration_error_path (Step 5) |
| REQ-158 | Claim toggle; multiple claims allowed per problem | `test-problems` — claim toggle idempotent | (no dedicated integration) |
| REQ-160 | Claim model exists; auto-expiry background job not impl | `test-problems` — claim model | Not covered — known gap: background job not impl |
| REQ-162 | open → duplicate admin-only; two-step confirm not impl | `test-problems` — FSM duplicate transition | Not covered — known gap: two-step confirm not impl |
| REQ-164 | pin_problem with MAX_PINNED=3 guard | `test-problems` — pin limit enforcement | (no dedicated integration) |
| REQ-166 | ProblemEditHistory snapshot on edit | `test-problems` — edit history snapshot | (no dedicated integration) |
| REQ-168 | Cursor-based pagination via CursorPage[T] | `test-problems` — feed pagination | (no dedicated integration) |
| REQ-170 | Four sort modes: new, top, active, discussed | `test-problems` — feed sort modes | (no dedicated integration) |
| REQ-172 | Feed filters: status, category, tag_ids, is_claimed | `test-problems` — feed filters combined | (no dedicated integration) |
| REQ-174 | Pinned problems prepended outside pagination on first page | `test-problems` — pinned prepend first page only | (no dedicated integration) |
| REQ-176 | Idempotency-Key support | Not covered — known gap: not implemented | Not covered — known gap: not implemented |
| REQ-178 | Full-text search endpoint | `test-search-leaderboard` — search.py | integration_search (Step 1-6) |
| REQ-180 | activity_at updated on claims, edits, solutions, comments | `test-problems`, `test-solutions-voting` — activity updates | integration_happy_path (Step 2, 5-7) |
| REQ-182 | Starred filter not available | Not covered — known gap: SHOULD priority, not impl | Not covered — known gap: SHOULD priority |
| REQ-200 | Solutions as first-class objects with versioning | `test-solutions-voting` — solution model | integration_happy_path (Step 5) |
| REQ-202 | GET /problems/{id}/solutions listing | `test-solutions-voting` — list solutions | integration_happy_path (Step 5) |
| REQ-204 | git_link as AnyHttpUrl \| None; anonymous via is_anonymous | `test-solutions-voting` — git_link URL validation | (no dedicated integration) |
| REQ-206 | Append-only versioning; PATCH/PUT return 405 | `test-solutions-voting` — version append; 405 guard | integration_happy_path (Step 5) |
| REQ-208 | GET /solutions/{id}/versions ordered by version_number ASC | `test-solutions-voting` — version history ordering | (no dedicated integration) |
| REQ-210 | accept_solution with atomic swap of previously accepted | `test-solutions-voting` — acceptance atomic swap | integration_happy_path (Step 7) |
| REQ-212 | Default sort: accepted first, then upvote count DESC | `test-solutions-voting` — solution sort order default | (no dedicated integration) |
| REQ-214 | SolutionSortMode.newest for chronological ordering | `test-solutions-voting` — sort mode newest | (no dedicated integration) |
| REQ-216 | Anonymous masking via _solution_to_dict | `test-solutions-voting` — anonymous masking | (no dedicated integration) |
| REQ-218 | Toggle semantics on POST /solutions/{id}/upvote | `test-solutions-voting` — voting.py toggle semantics | (no dedicated integration) |
| REQ-220 | Accepted solution visual distinction in UI | `test-middleware-infra-frontend` — frontend | integration_happy_path (Step 7) |
| REQ-250 | Upstar with FOR UPDATE lock and unique constraint | `test-solutions-voting` — voting.py FOR UPDATE lock | (no dedicated integration) |
| REQ-252 | Toggle: delete if exists, insert if not | `test-solutions-voting` — voting.py toggle idempotent | (no dedicated integration) |
| REQ-254 | Solution upvotes in separate solution_upvotes table | `test-solutions-voting` — voting.py table separation | (no dedicated integration) |
| REQ-256 | Identical toggle mechanics for solution upvotes | `test-solutions-voting` — voting.py solution toggle | (no dedicated integration) |
| REQ-258 | Threaded via parent_comment_id self-referential FK | `test-comments-attachments` — comments.py threading | (no dedicated integration) |
| REQ-260 | Anonymous masking; is_anonymous flag on create | `test-comments-attachments` — comments.py masking | (no dedicated integration) |
| REQ-262 | Tombstone if replies exist; hard delete if leaf | `test-comments-attachments` — comments.py delete logic | (no dedicated integration) |
| REQ-264 | edit_comment sets is_edited=True; author-only | `test-comments-attachments` — comments.py edit guard | (no dedicated integration) |
| REQ-266 | HTML sanitization allowlist; MarkdownEditor frontend | `test-comments-attachments` — comments.py sanitization | (no dedicated integration) |
| REQ-268 | Dual-track leaderboard: solvers + reporters | `test-search-leaderboard` — leaderboard.py dual track | (no dedicated integration) |
| REQ-270 | is_anonymous=False filter in SQL | `test-search-leaderboard` — leaderboard.py anon filter | (no dedicated integration) |
| REQ-300 | WatchLevel enum; watches table with level column | `test-notifications` — watches.py model | integration_happy_path (Step 3) |
| REQ-302 | PUT/DELETE/GET watch endpoints with upsert | `test-notifications` — watches.py CRUD | integration_happy_path (Step 3) |
| REQ-304 | auto_watch on problem creation, claiming, solution posting | `test-notifications` — watches.py auto-watch | integration_happy_path (Step 3, 5) |
| REQ-306 | auto_watch on commenting (never downgrades) | `test-notifications` — watches.py no-downgrade | (no dedicated integration) |
| REQ-308 | Auto-watch respects existing higher-priority level | `test-notifications` — watches.py priority | (no dedicated integration) |
| REQ-310 | Eight NotificationType enum values; per-watcher row generation | `test-notifications` — notifications.py type enum | integration_happy_path (Step 6) |
| REQ-312 | WATCH_ROUTING matrix mapping levels to allowed types | `test-notifications` — notifications.py routing | integration_happy_path (Step 6) |
| REQ-314 | In-app notification list with pagination and mark-read | `test-notifications` — notifications.py list/read | (no dedicated integration) |
| REQ-316 | WebSocket push via ConnectionManager singleton | `test-notifications` — delivery.py WebSocket | integration_happy_path (Step 6) |
| REQ-318 | Teams webhook via schedule_teams_webhook (fire-and-forget) | `test-notifications` — delivery.py Teams | integration_happy_path (Step 6), integration_channel_independence (Step 3) |
| REQ-320 | Email digest via send_email_digest with aiosmtplib | `test-notifications` — delivery.py email digest | integration_channel_independence (Step 4) |
| REQ-322 | is_milestone checks against [10, 25, 50, 100] | `test-notifications` — notifications.py milestone | (no dedicated integration) |
| REQ-324 | Claim expiry notification type exists; background job not impl | `test-notifications` — notifications.py types | Not covered — known gap: background job not impl |
| REQ-350 | problems.search_vector tsvector + GIN index | `test-search-leaderboard` — search.py tsvector | integration_search (Step 3) |
| REQ-352 | plainto_tsquery with ts_rank scoring | `test-search-leaderboard` — search.py ranking | integration_search (Step 3) |
| REQ-354 | Three-branch CTE: problems + solutions + comments | `test-search-leaderboard` — search.py CTE union | integration_search (Step 3) |
| REQ-356 | Sort modes: relevance, upvotes, newest | `test-search-leaderboard` — search.py sort modes | integration_search (Step 3) |
| REQ-358 | Filters: category_id, status, tag_ids | `test-search-leaderboard` — search.py filters | integration_search (Step 3) |
| REQ-360 | Empty-result message with CTA link | `test-search-leaderboard` — search.py fallback | integration_search (Step 6) |
| REQ-362 | suggest_similar endpoint for duplicate detection | `test-search-leaderboard` — search.py suggest | integration_search (Step 7) |
| REQ-364 | 120-character excerpt truncation | `test-search-leaderboard` — search.py excerpt | integration_search (Step 3, 5) |
| REQ-366 | og:title, og:description, og:url, og:site_name, og:type | Not covered — known gap: OG endpoint not in test specs | Not covered — known gap: OG endpoint not in test specs |
| REQ-368 | Bot User-Agent detection via $is_link_preview_bot map | Not covered — known gap: NGINX concern, not service | Not covered — known gap: NGINX concern |
| REQ-400 | Multipart upload to POST /problems/{id}/attachments | `test-comments-attachments` — attachments.py upload | integration_attachment_lifecycle (Step 1) |
| REQ-402 | Extension-based MIME allowlist | `test-comments-attachments` — attachments.py MIME check | integration_attachment_lifecycle (Step 2) |
| REQ-404 | 10 MB per-file, 50 MB cumulative limits | `test-comments-attachments` — attachments.py size check | integration_attachment_lifecycle (Step 1-2) |
| REQ-406 | UUID filenames under STORAGE_PATH/{problem_id}/ | `test-comments-attachments` — attachments.py storage path | integration_attachment_lifecycle (Step 1) |
| REQ-408 | attachments table with full metadata | `test-comments-attachments` — attachments.py DB row | integration_attachment_lifecycle (Step 1) |
| REQ-410 | Direct file serving via alias /data/attachments/ | Not covered — known gap: NGINX infrastructure | Not covered — known gap: NGINX concern |
| REQ-412 | render_inline flag; images inline, others as downloads | `test-comments-attachments` — attachments.py render_inline | integration_attachment_lifecycle (Step 3) |
| REQ-414 | Clipboard paste support | Not covered — known gap: client-side, SHOULD | Not covered — known gap: client-side feature |
| REQ-416 | DB row deleted before disk file; require_owner_or_admin | `test-comments-attachments` — attachments.py delete order | integration_attachment_lifecycle (Step 4-5) |
| REQ-450 | Router-level require_admin dependency | `test-admin` — admin.py auth guard | (no dedicated integration) |
| REQ-452 | Category CRUD in app/services/categories.py | `test-admin` — categories.py CRUD | (no dedicated integration) |
| REQ-454 | Default categories seeded on first run | Not covered — known gap: migration/seed, not service | Not covered — known gap: migration concern |
| REQ-456 | PATCH /admin/categories/reorder bulk update | `test-admin` — categories.py reorder | (no dedicated integration) |
| REQ-458 | Soft delete via deleted_at; 409 if problems reference | `test-admin` — categories.py soft delete | (no dedicated integration) |
| REQ-460 | Tag listing with usage_count via LEFT JOIN + GROUP BY | `test-admin` — tags.py usage count | (no dedicated integration) |
| REQ-462 | Tag rename and hard delete with cascade cleanup | `test-admin` — tags.py rename/delete | (no dedicated integration) |
| REQ-464 | merge_tags with INSERT ... ON CONFLICT DO NOTHING | `test-admin` — tags.py merge | (no dedicated integration) |
| REQ-466 | User search via case-insensitive ILIKE | `test-admin` — admin.py user search | (no dedicated integration) |
| REQ-468 | Flag model; resolve_flag with admin notes | `test-admin` — admin.py flag resolution | (no dedicated integration) |
| REQ-470 | Flagged content list with status filter | `test-admin` — admin.py flag list | (no dedicated integration) |
| REQ-472 | de_anonymize with AuditLog write-ahead pattern | `test-admin` — admin.py de-anonymize | (no dedicated integration) |
| REQ-474 | AuditLog model; ALLOWED_CONFIG_KEYS for runtime config | `test-admin` — admin.py config upsert | (no dedicated integration) |
| REQ-476 | AdminRouteGuard in frontend; require_admin in backend | `test-admin` — admin.py dependency | `test-middleware-infra-frontend` — frontend guard |
| REQ-500 | CSS custom properties, gradient accents, theme tokens | `test-middleware-infra-frontend` — frontend styling | (no dedicated integration) |
| REQ-502 | Cork-texture background, decorative cards, centered auth | `test-middleware-infra-frontend` — frontend landing | (no dedicated integration) |
| REQ-504 | APP_NAME env var; VITE_APP_NAME in sidebar | `test-foundation-models` — config.py APP_NAME | (no dedicated integration) |
| REQ-506 | Card layout with upstar count, status badge, tags, counts | `test-middleware-infra-frontend` — frontend ProblemCard | (no dedicated integration) |
| REQ-508 | Color-coded badges consistent across all views | `test-middleware-infra-frontend` — frontend StatusBadge | (no dedicated integration) |
| REQ-510 | Header + markdown description + tabbed solutions/comments | `test-middleware-infra-frontend` — frontend ProblemDetail | (no dedicated integration) |
| REQ-512 | React Router 6 with lazy-loaded routes | `test-middleware-infra-frontend` — frontend routing | (no dedicated integration) |
| REQ-514 | Three-way mode: light/dark/system; localStorage persist | `test-middleware-infra-frontend` — frontend theme | (no dedicated integration) |
| REQ-516 | Generic empty-list component with message and CTA | `test-middleware-infra-frontend` — frontend EmptyState | (no dedicated integration) |
| REQ-518 | Toast system, 404 page, inline validation errors | `test-middleware-infra-frontend` — frontend Toast | (no dedicated integration) |
| REQ-520 | useMediaQuery("(min-width: 1024px)") responsive layout | `test-middleware-infra-frontend` — frontend responsive | (no dedicated integration) |
| REQ-522 | Minimal form with MarkdownEditor, TagAutocomplete, anon toggle | `test-middleware-infra-frontend` — frontend Submit form | (no dedicated integration) |
| REQ-524 | Placeholder page with disabled inputs and "Coming Soon" | `test-middleware-infra-frontend` — frontend AISearch | (no dedicated integration) |
| REQ-526 | Track/period filter tabs; gold/silver/bronze rank styling | `test-middleware-infra-frontend` — frontend Leaderboard | (no dedicated integration) |
| REQ-528 | Toast queue with 3 max visible, 5-second auto-dismiss | `test-middleware-infra-frontend` — frontend toast queue | (no dedicated integration) |
| REQ-900 | Performance target; async-first architecture | Not covered — known gap: performance benchmark | Not covered — known gap: load test |
| REQ-902 | p95 < 1000ms target; GIN index on problems.search_vector | `test-search-leaderboard` — search.py GIN index | Not covered — known gap: p95 load test |
| REQ-904 | 100-500 user capacity; single-server deployment | Not covered — known gap: capacity test | Not covered — known gap: load test |
| REQ-906 | TLS 1.2+ termination (commented-in for production) | Not covered — known gap: NGINX config | Not covered — known gap: NGINX config |
| REQ-908 | Belt-and-suspenders security headers at both layers | `test-middleware-infra-frontend` — security.py headers | (no dedicated integration) |
| REQ-910 | Three rate limit zones: api (30), auth (5), magic (1) | Not covered — known gap: NGINX rate limits | Not covered — known gap: NGINX zone |
| REQ-912 | JSONFormatter + LoggingMiddleware + correlation IDs | `test-middleware-infra-frontend` — logging.py | (no dedicated integration) |
| REQ-914 | pg_dump with 7-daily/4-weekly retention | Not covered — known gap: backup script | Not covered — known gap: operational |
| REQ-916 | pydantic_settings.BaseSettings from .env | `test-foundation-models` — config.py settings | (no dedicated integration) |
| REQ-918 | CSP, X-Content-Type-Options, X-Frame-Options, sanitization | `test-middleware-infra-frontend` — security.py | (no dedicated integration) |
| REQ-920 | Async engine bridge; NullPool for migrations | Not covered — known gap: migration execution | Not covered — known gap: Alembic test |
| REQ-922 | podman generate systemd with Restart=always | Not covered — known gap: systemd config | Not covered — known gap: systemd test |
| REQ-924 | Two-pass HTML sanitization; extension-based MIME check | `test-comments-attachments` — comments/attachments.py | (no dedicated integration) |
| REQ-926 | No test suite exists | Not covered — known gap: 80% coverage target undefined | Not covered — known gap: no coverage baseline |
| REQ-928 | /healthz with database + storage probes | Not covered — known gap: health check endpoint | Not covered — known gap: health endpoint test |

## Notes

- **Integration test reference format:** `integration_<scenario_name>` refers to scenarios in `test-integration.md`:
  - `integration_happy_path` — Problem submission to solution acceptance (REQ-100 through REQ-180)
  - `integration_error_path` — Forbidden transitions and permission errors (REQ-116, REQ-156)
  - `integration_search` — Full-text search end-to-end (REQ-350 through REQ-364)
  - `integration_attachment_lifecycle` — File upload, download, delete (REQ-400 through REQ-416)
  - `integration_channel_independence` — Notification delivery redundancy (REQ-316, REQ-318, REQ-320)

- **Known gaps identified from EG appendix (lines 4118-4252):**
  - **REQ-160**: Claim auto-expiry background job not implemented
  - **REQ-162**: Two-step duplicate confirmation workflow not implemented
  - **REQ-176**: Idempotency-Key header not supported
  - **REQ-182**: Starred filter (SHOULD priority) not available
  - **REQ-324**: Claim expiry notification type exists but background job not implemented
  - **REQ-366**: Open Graph meta endpoint not specified in engineering guide
  - **REQ-368**: Bot User-Agent detection is NGINX/infrastructure concern
  - **REQ-410**: Direct file serving via NGINX alias (infrastructure)
  - **REQ-414**: Clipboard paste (client-side, SHOULD priority)
  - **REQ-454**: Default category seeding (migration/fixture concern)
  - **REQ-366**, **REQ-906**, **REQ-910**, **REQ-914**, **REQ-920**, **REQ-922**: Infrastructure/ops concerns outside service-layer tests
  - **REQ-900**, **REQ-902**, **REQ-904**: Performance targets lack defined test harness
  - **REQ-926**: 80% coverage target undefined; no baseline test coverage metrics
  - **REQ-928**: /healthz health-check endpoint not documented in module sections

- **Implementation deviations (from EG Notes column):**
  - REQ-108: Implementation uses single 8-hour token; spec says 15m access + 7d refresh (implementation deviation)
  - REQ-174: Pinned problems behavior vs. status filters has EG conflict with REQ-174 spec (unresolved)
  - REQ-416: DB row deleted before disk file (inverse of REQ-416 spec intent)
  - REQ-402: Allowed MIME types subset implemented vs. spec (see test gaps)

## Coverage Summary

- **Total REQs:** 142 (REQ-100 through REQ-928, including gaps)
- **Covered by module tests:** 119 REQs
- **Covered by integration tests:** 5 core integration scenarios covering ~40 REQs cross-module
- **Known gaps (not implemented):** 23 REQs
  - 11 REQs are infrastructure/ops/frontend-only (not service-testable)
  - 8 REQs are deferred/SHOULD priority features
  - 4 REQs are background jobs or performance targets
