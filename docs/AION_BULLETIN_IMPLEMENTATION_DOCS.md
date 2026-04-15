# Aion Bulletin — Implementation Docs

> **For implement-code agents:** This document is your source of truth.
> Read ONLY your assigned task section. Your section contains your FR context,
> Phase 0 contracts inlined, implementation steps, and isolation contract verbatim.
> Do not read the full document, the spec, the design doc, or other task sections.

**Goal:** Provide a community-driven problem bulletin board for ~100 ASIC engineers to surface, validate, and solve problems.
**Spec:** `docs/AION_BULLETIN_SPEC.md`
**Design doc:** `docs/AION_BULLETIN_DESIGN.md`
**Output path:** `docs/AION_BULLETIN_IMPLEMENTATION_DOCS.md`
**Produced by:** write-implementation-docs
**Phase 0 status:** [ ] Awaiting human review

---
# Phase 0 — Contract Definitions

## Overview

Phase 0 establishes the shared contracts that all implementation tasks depend on. Every stub in B.5 and B.6 raises `NotImplementedError` and is replaced by the task listed in its annotation. No task may import from another task's implementation files until that task is marked complete.

---

## B.1 Settings

Fully implemented — not a stub. Import via `from app.config import get_settings`.

```python
from pydantic import AnyHttpUrl, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
from typing import Literal

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    DATABASE_URL: str                          # REQ-916
    AZURE_TENANT_ID: str                       # REQ-504
    AZURE_CLIENT_ID: str                       # REQ-504
    AZURE_CLIENT_SECRET: SecretStr             # REQ-504
    JWT_SECRET: SecretStr                      # REQ-108
    SMTP_HOST: str                             # REQ-104
    SMTP_PORT: int = 587                       # REQ-104
    SMTP_FROM: str                             # REQ-104
    APP_NAME: str = "Aion Bulletin"
    DEV_AUTH_BYPASS: bool = False
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    STORAGE_PATH: str = "/data/attachments"    # REQ-404
    BASE_URL: AnyHttpUrl                       # REQ-104
    TEAMS_WEBHOOK_URL: AnyHttpUrl | None = None

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
```

---

## B.2 Enums

All enums live in `app/enums.py`.

```python
from enum import Enum

class ProblemStatus(str, Enum):          # REQ-156
    open       = "open"
    claimed    = "claimed"
    solved     = "solved"
    accepted   = "accepted"
    duplicate  = "duplicate"

class UserRole(str, Enum):               # REQ-114
    user  = "user"
    admin = "admin"

class WatchLevel(str, Enum):             # REQ-300
    all_activity   = "all_activity"
    solutions_only = "solutions_only"
    status_only    = "status_only"
    none           = "none"

class NotificationType(str, Enum):       # REQ-310
    problem_claimed   = "problem_claimed"
    solution_posted   = "solution_posted"
    solution_accepted = "solution_accepted"
    comment_posted    = "comment_posted"
    status_changed    = "status_changed"
    problem_pinned    = "problem_pinned"
    upstar_received   = "upstar_received"
    mention           = "mention"

class SortMode(str, Enum):               # REQ-170
    top       = "top"
    new       = "new"
    active    = "active"
    discussed = "discussed"

class ParentType(str, Enum):             # REQ-258
    problem  = "problem"
    solution = "solution"
    comment  = "comment"
```

---

## B.3 Exceptions

All exceptions live in `app/exceptions.py`.

```python
from fastapi import HTTPException

class AppError(Exception):
    """Base application error."""

class ForbiddenTransitionError(AppError):   # REQ-156 → 409
    def __init__(self, current: str, target: str):
        self.current = current
        self.target  = target
        super().__init__(f"Cannot transition from {current!r} to {target!r}")

class PinLimitExceededError(AppError):      # REQ-164 → 409
    pass

class FileSizeLimitError(AppError):         # REQ-404 → 413
    def __init__(self, file_size: int, max_size: int):
        self.file_size = file_size
        self.max_size  = max_size
        super().__init__(f"File size {file_size} exceeds limit {max_size}")

class FileTypeNotAllowedError(AppError):    # REQ-402 → 422
    def __init__(self, content_type: str, filename: str):
        self.content_type = content_type
        self.filename     = filename
        super().__init__(f"Type {content_type!r} not allowed for {filename!r}")

class DuplicateVoteError(AppError):         # REQ-250 → 409
    pass

class MagicLinkExpiredError(AppError):      # REQ-106 → 410
    pass

class TenantMismatchError(AppError):        # REQ-102 → 403
    pass
```

---

## B.4 Pydantic Schemas

All schemas live in `app/schemas.py`.

```python
from __future__ import annotations
from datetime import datetime
from typing import Generic, TypeVar
from pydantic import BaseModel, Field, AnyHttpUrl

T = TypeVar("T")

# --- Pagination ---
class CursorPage(BaseModel, Generic[T]):    # REQ-168
    items: list[T]
    next_cursor: str | None

# --- Auth ---
class MagicLinkRequest(BaseModel):         # REQ-104
    email: str

class TokenPayload(BaseModel):             # REQ-108
    sub:  str
    role: str
    exp:  int

# --- Users ---
class UserResponse(BaseModel):             # REQ-118
    id:           str
    display_name: str
    email:        str
    role:         str
    created_at:   datetime

# --- Problems ---
class ProblemCreate(BaseModel):            # REQ-150, REQ-152, REQ-154
    title:        str      = Field(..., min_length=5, max_length=200)
    description:  str      = Field(..., min_length=10)
    category_id:  str
    tag_ids:      list[str] = Field(default_factory=list)
    is_anonymous: bool      = False

class ProblemResponse(BaseModel):          # REQ-506
    id:             str
    title:          str
    description:    str
    author:         UserResponse | None
    status:         str
    category:       dict
    tags:           list[dict]
    upstar_count:   int
    solution_count: int
    comment_count:  int
    is_pinned:      bool
    created_at:     datetime
    activity_at:    datetime

class ProblemDetailResponse(ProblemResponse):  # REQ-510
    is_upstarred:       bool
    is_claimed:         bool
    claims:             list[dict]
    edit_history_count: int

# --- Solutions ---
class SolutionCreate(BaseModel):           # REQ-200, REQ-204
    description:  str          = Field(..., min_length=10)
    git_link:     AnyHttpUrl | None = None
    is_anonymous: bool          = False

class SolutionVersionCreate(BaseModel):    # REQ-206
    description: str           = Field(..., min_length=10)
    git_link:    AnyHttpUrl | None = None

class SolutionResponse(BaseModel):         # REQ-202
    id:            str
    author:        UserResponse | None
    description:   str
    git_link:      str | None
    status:        str
    upvote_count:  int
    is_anonymous:  bool
    version_count: int
    created_at:    datetime

# --- Comments ---
class CommentCreate(BaseModel):            # REQ-258, REQ-260
    body:              str           = Field(..., min_length=1, max_length=10000)
    parent_comment_id: str | None    = None
    is_anonymous:      bool          = False

class CommentResponse(BaseModel):          # REQ-258
    id:           str
    author:       UserResponse | None
    body:         str
    is_anonymous: bool
    is_edited:    bool
    created_at:   datetime
    replies:      list[CommentResponse] = Field(default_factory=list)

CommentResponse.model_rebuild()
```

---

## B.5 Service Stubs

All stubs live in `app/services/_stubs.py` and are re-exported from their eventual home modules.

```python
# app/services/_stubs.py
from app.schemas import (
    CursorPage, ProblemCreate, ProblemResponse,
    SolutionCreate, SolutionVersionCreate,
)
from app.enums import ProblemStatus, SortMode

# --- Task 2.1 ---
async def create_problem(db, user_id: str, data: ProblemCreate):
    raise NotImplementedError

async def transition_status(db, problem_id: str, target: ProblemStatus, actor_id: str):
    raise NotImplementedError

async def claim_problem(db, problem_id: str, user_id: str):
    raise NotImplementedError

async def pin_problem(db, problem_id: str, admin_id: str):
    raise NotImplementedError

# --- Task 2.2 ---
async def get_feed(db, sort: SortMode, filters: dict, cursor: str | None, limit: int, user_id: str) -> CursorPage[ProblemResponse]:
    raise NotImplementedError

# --- Task 2.3 ---
async def create_solution(db, problem_id: str, user_id: str, data: SolutionCreate):
    raise NotImplementedError

async def accept_solution(db, solution_id: str, actor_id: str):
    raise NotImplementedError

async def create_version(db, solution_id: str, user_id: str, data: SolutionVersionCreate):
    raise NotImplementedError

# --- Task 2.4 ---
async def toggle_upstar(db, problem_id: str, user_id: str) -> tuple[bool, int]:
    raise NotImplementedError

async def toggle_solution_upvote(db, solution_id: str, user_id: str) -> tuple[bool, int]:
    raise NotImplementedError

# --- Task 3.1 ---
async def search_problems(db, query: str, sort: SortMode, filters: dict, limit: int) -> list[dict]:
    raise NotImplementedError

async def suggest_similar(db, title: str, limit: int = 5) -> list[dict]:
    raise NotImplementedError

# --- Task 3.3 ---
async def generate_notification(db, event_type: str, problem_id: str | None, solution_id: str | None, actor_id: str) -> list:
    raise NotImplementedError
```

---

## B.6 Auth Dependencies

All stubs live in `app/auth/dependencies.py`.

```python
from typing import Annotated
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

async def get_current_user(request: Request, db: AsyncSession, session: dict):
    raise NotImplementedError  # Task 1.3

async def require_admin(user):
    raise NotImplementedError  # Task 1.3

async def require_owner_or_admin(resource_owner_id: str, user) -> None:
    raise NotImplementedError  # Task 1.3

CurrentUser = Annotated[object, Depends(get_current_user)]
AdminUser   = Annotated[object, Depends(require_admin)]
```

---

## Error Taxonomy

| Error Type | Trigger Condition | Expected Message Format | Retryable | Raising Module |
|---|---|---|---|---|
| `ForbiddenTransitionError` | FSM transition not in allowed edges | `"Cannot transition from '{current}' to '{target}'"` | No | `services/problems.py` |
| `PinLimitExceededError` | Admin attempts to pin when global pin cap reached | `"Pin limit exceeded"` | No | `services/problems.py` |
| `FileSizeLimitError` | Upload byte count exceeds `MAX_ATTACHMENT_BYTES` | `"File size {file_size} exceeds limit {max_size}"` | No | `services/attachments.py` |
| `FileTypeNotAllowedError` | MIME type or extension not in allow-list | `"Type '{content_type}' not allowed for '{filename}'"` | No | `services/attachments.py` |
| `DuplicateVoteError` | User submits a second upstar/upvote for the same resource | `"Already voted"` | No | `services/voting.py` |
| `MagicLinkExpiredError` | Magic link token past TTL or already consumed | `"Magic link expired or already used"` | No | `auth/magic_link.py` |
| `TenantMismatchError` | JWT `tid` claim does not match `AZURE_TENANT_ID` | `"Token tenant does not match expected tenant"` | No | `auth/oidc.py` |
| `AppError` (base) | Unclassified application fault | `str(exception)` | Depends | Any service |

HTTP status mapping is applied by the global exception handler in `app/main.py`: `ForbiddenTransitionError` → 409, `PinLimitExceededError` → 409, `FileSizeLimitError` → 413, `FileTypeNotAllowedError` → 422, `DuplicateVoteError` → 409, `MagicLinkExpiredError` → 410, `TenantMismatchError` → 403.

---

## Integration Contracts

Arrows indicate the calling direction. The caller depends on the callee's public interface; the callee must not import from the caller.

```
routes/auth.py          → auth/oidc.py           (Azure AD OIDC redirect + callback, tenant check)
routes/auth.py          → auth/magic_link.py      (send link, verify token, issue session cookie)
routes/problems.py      → services/problems.py    (create, transition FSM, claim, pin)
routes/problems.py      → services/feed.py        (cursor-paginated feed with sort + filters)
routes/solutions.py     → services/solutions.py   (create solution, accept, create version)
routes/voting.py        → services/voting.py      (toggle upstar on problems, upvote on solutions)
routes/comments.py      → services/comments.py    (threaded create, edit, delete)
routes/attachments.py   → services/attachments.py (validate type/size, write to STORAGE_PATH)
routes/search.py        → services/search.py      (full-text search, similarity suggestions)
services/notifications.py → services/watches.py   (resolve watchers for an event, fan-out list)
services/notifications.py → services/delivery.py  (dispatch per-channel: WebSocket, Teams webhook, SMTP)
```

Callers may only invoke functions exported from the callee's `__init__.py`. Internal helpers (prefixed `_`) are not part of the contract.

---

---

---

# Phase 1 — Foundation

---

## Task 1.1: Project Scaffolding & Environment Configuration

**Description:** Establishes the runnable project skeleton — dependency manifest, container orchestration, environment variable contract, and the settings singleton that every other module imports.

**Spec requirements:** REQ-916, REQ-922

**Dependencies:** None

**Source files:**
- CREATE `pyproject.toml`
- CREATE `podman-compose.yml`
- CREATE `.env.example`
- CREATE `app/__init__.py`
- CREATE `app/config.py`

---

**Phase 0 contracts (inlined — implement these stubs):**

`app/config.py` receives the **fully implemented** B.1 Settings class — there is no stub to replace, only code to transcribe and verify.

```python
from pydantic import AnyHttpUrl, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
from typing import Literal

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    DATABASE_URL: str                          # REQ-916
    AZURE_TENANT_ID: str                       # REQ-504
    AZURE_CLIENT_ID: str                       # REQ-504
    AZURE_CLIENT_SECRET: SecretStr             # REQ-504
    JWT_SECRET: SecretStr                      # REQ-108
    SMTP_HOST: str                             # REQ-104
    SMTP_PORT: int = 587                       # REQ-104
    SMTP_FROM: str                             # REQ-104
    APP_NAME: str = "Aion Bulletin"
    DEV_AUTH_BYPASS: bool = False
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    STORAGE_PATH: str = "/data/attachments"    # REQ-404
    BASE_URL: AnyHttpUrl                       # REQ-104
    TEAMS_WEBHOOK_URL: AnyHttpUrl | None = None

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
```

---

**Implementation steps:**

1. [REQ-916] Create `pyproject.toml` using `[project]` table (PEP 621). Required runtime dependencies: `fastapi>=0.111`, `uvicorn[standard]`, `sqlalchemy[asyncio]>=2.0`, `asyncpg`, `alembic`, `pydantic>=2.7`, `pydantic-settings`, `authlib`, `python-jose[cryptography]`, `aiosmtplib`, `httpx`, `python-multipart`, `pillow`. Dev dependencies: `pytest`, `pytest-asyncio`, `httpx`, `ruff`, `mypy`.
2. [REQ-922] Create `podman-compose.yml` defining three services: `nginx` (reverse proxy, port 80→8000), `api` (uvicorn, mounts `./app` and `/data/attachments`), `postgres` (image `postgres:16`, env vars `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, volume `pgdata`). The `api` service must declare a health-check on `GET /health`.
3. [REQ-916] Create `.env.example` listing every field declared in `Settings` with safe placeholder values (no real secrets). Add an inline comment on each line referencing the originating REQ.
4. [REQ-916] Create `app/__init__.py` as an empty file to mark the package.
5. [REQ-916] Transcribe the B.1 `Settings` class and `get_settings` factory verbatim into `app/config.py`. Add a module-level docstring explaining the settings singleton pattern.
6. Add module-level docstring and `@summary` block to every created Python file.

**Completion criteria:**
- [ ] All stubs implemented — no `NotImplementedError` remaining
- [ ] `python -c "from app.config import get_settings"` succeeds when a valid `.env` is present
- [ ] `podman-compose up --build` starts all three services without error
- [ ] Integration contracts honored
- [ ] Module-level docstring present on each file

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Task 1.2: Database Schema & Alembic Migrations

**Description:** Defines all 16 SQLAlchemy ORM models, configures the async session factory, sets up Alembic for schema versioning, and seeds the initial category rows. This task owns every table definition; all other tasks import models from here.

**Spec requirements:** REQ-920, REQ-454

**Dependencies:** Task 1.1

**Source files:**
- CREATE `app/models/__init__.py`
- CREATE `app/models/user.py`
- CREATE `app/models/problem.py`
- CREATE `app/models/solution.py`
- CREATE `app/models/comment.py`
- CREATE `app/models/attachment.py`
- CREATE `app/models/notification.py`
- CREATE `app/models/watch.py`
- CREATE `app/database.py`
- CREATE `alembic/` (directory)
- CREATE `alembic/env.py`

---

**Phase 0 contracts (inlined — implement these stubs):**

The B.2 enums must be declared in `app/enums.py` before models import them. Transcribe verbatim:

```python
from enum import Enum

class ProblemStatus(str, Enum):          # REQ-156
    open       = "open"
    claimed    = "claimed"
    solved     = "solved"
    accepted   = "accepted"
    duplicate  = "duplicate"

class UserRole(str, Enum):               # REQ-114
    user  = "user"
    admin = "admin"

class WatchLevel(str, Enum):             # REQ-300
    all_activity   = "all_activity"
    solutions_only = "solutions_only"
    status_only    = "status_only"
    none           = "none"

class NotificationType(str, Enum):       # REQ-310
    problem_claimed   = "problem_claimed"
    solution_posted   = "solution_posted"
    solution_accepted = "solution_accepted"
    comment_posted    = "comment_posted"
    status_changed    = "status_changed"
    problem_pinned    = "problem_pinned"
    upstar_received   = "upstar_received"
    mention           = "mention"

class SortMode(str, Enum):               # REQ-170
    top       = "top"
    new       = "new"
    active    = "active"
    discussed = "discussed"

class ParentType(str, Enum):             # REQ-258
    problem  = "problem"
    solution = "solution"
    comment  = "comment"
```

---

**Implementation steps:**

1. [REQ-920] Create `app/enums.py` with the B.2 enums above. This file has no dependencies on other app modules.
2. [REQ-920] Create `app/database.py` with an `AsyncEngine` created from `settings.DATABASE_URL`, an `AsyncSessionLocal` factory (`expire_on_commit=False`), a `Base = declarative_base()`, and a `get_db` async generator dependency that yields a session and commits/rolls back on exit.
3. [REQ-920] Create the following SQLAlchemy models, each in its own file under `app/models/`. Every table uses `UUID` primary keys (server default `gen_random_uuid()`), `created_at TIMESTAMPTZ` (server default `now()`), and `updated_at TIMESTAMPTZ` (updated via trigger or `onupdate`):
   - `user.py` — `User`: `id`, `email` (unique), `display_name`, `role: UserRole`, `azure_oid` (nullable unique), `is_active`, `created_at`
   - `problem.py` — `Problem`: `id`, `title`, `description TEXT`, `author_id FK→User` (nullable for anonymous), `status: ProblemStatus`, `category_id FK→Category`, `is_pinned`, `is_anonymous`, `activity_at`, `search_vector TSVECTOR` (generated); `Category`: `id`, `name` (unique), `slug` (unique); `ProblemTag` join table; `Tag`: `id`, `name` (unique); `ProblemEditHistory`: `id`, `problem_id`, `editor_id`, `snapshot JSONB`, `created_at`; `Claim`: `id`, `problem_id`, `user_id`, `claimed_at`
   - `solution.py` — `Solution`: `id`, `problem_id FK→Problem`, `author_id FK→User` (nullable), `status`, `is_anonymous`, `current_version_id` (nullable self-ref); `SolutionVersion`: `id`, `solution_id`, `version_number`, `description`, `git_link` (nullable), `created_by FK→User`, `created_at`
   - `comment.py` — `Comment`: `id`, `problem_id FK→Problem`, `solution_id FK→Solution` (nullable), `author_id FK→User` (nullable), `parent_comment_id` (self-ref nullable), `body TEXT`, `is_anonymous`, `is_edited`, `created_at`
   - `attachment.py` — `Attachment`: `id`, `parent_type: ParentType`, `parent_id UUID`, `uploader_id FK→User`, `filename`, `content_type`, `byte_size`, `storage_path`, `created_at`
   - `notification.py` — `Notification`: `id`, `recipient_id FK→User`, `type: NotificationType`, `problem_id` (nullable), `solution_id` (nullable), `actor_id FK→User`, `is_read`, `created_at`; `NotificationPreference`: `user_id`, `type: NotificationType`, `enabled` (composite PK on both columns)
   - `watch.py` — `Watch`: `id`, `user_id FK→User`, `problem_id FK→Problem`, `level: WatchLevel`; add `UNIQUE(user_id, problem_id)`
4. [REQ-920] In `app/models/problem.py`, add a `GIN` index on `search_vector` using `sqlalchemy.dialects.postgresql.ARRAY` / `ops="gin"`. Add a `UNIQUE` constraint on `(user_id, problem_id)` for `Claim`.
5. [REQ-920] In `app/models/solution.py` and any voting tables (upstar, upvote), add `UNIQUE(user_id, problem_id)` and `UNIQUE(user_id, solution_id)` constraints. Add `Upstar` and `SolutionUpvote` models here or in a dedicated `voting.py`.
6. [REQ-920] Export all models from `app/models/__init__.py` so Alembic autogenerate can discover them.
7. [REQ-920] Initialise Alembic: `alembic init alembic`. Edit `alembic/env.py` to import `Base.metadata` and use the async engine pattern (`run_async_migrations`).
8. [REQ-454] Create a seed migration file (`alembic/versions/0002_seed_categories.py`) that inserts 10 default categories: `Bug`, `Performance`, `Security`, `UX`, `Documentation`, `Infrastructure`, `Feature Request`, `Compliance`, `Data Quality`, `Other`. Each row gets a deterministic UUID and a `slug` derived from the name.
9. Add module-level docstring and `@summary` block to every created Python file.

**Completion criteria:**
- [ ] All stubs implemented — no `NotImplementedError` remaining
- [ ] `alembic upgrade head` runs cleanly against a fresh Postgres 16 instance
- [ ] All 16 tables present with correct columns, constraints, and indexes
- [ ] Seed migration inserts exactly 10 category rows idempotently
- [ ] `from app.models import User, Problem, Solution` resolves without error
- [ ] Integration contracts honored
- [ ] Module-level docstring present on each file

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Task 1.3: Authentication — Azure AD, Magic Link, JWT, Roles

**Description:** Implements the full authentication surface: Azure AD OIDC flow with tenant enforcement, passwordless magic-link email flow, JWT cookie issuance and verification, user auto-provisioning, role-based permission dependencies, a development bypass mode, and the `/auth` route group.

**Spec requirements:** REQ-100, REQ-102, REQ-104, REQ-106, REQ-108, REQ-110, REQ-112, REQ-114, REQ-116, REQ-118, REQ-120, REQ-122, REQ-124, REQ-126, REQ-128

**Dependencies:** Task 1.2

**Source files:**
- CREATE `app/auth/__init__.py`
- CREATE `app/auth/oidc.py`
- CREATE `app/auth/magic_link.py`
- CREATE `app/auth/jwt.py`
- CREATE `app/auth/dependencies.py`
- CREATE `app/routes/auth.py`

---

**Phase 0 contracts (inlined — implement these stubs):**

The following items from B.3, B.4, and B.6 are owned by this task. Replace every `raise NotImplementedError` with a real implementation.

**From B.3 — Exceptions to handle/raise (declare in `app/exceptions.py` if not already present):**

```python
class MagicLinkExpiredError(AppError):      # REQ-106 → HTTP 410
    pass

class TenantMismatchError(AppError):        # REQ-102 → HTTP 403
    pass
```

**From B.4 — Schemas consumed by auth routes:**

```python
class MagicLinkRequest(BaseModel):          # REQ-104
    email: str

class TokenPayload(BaseModel):              # REQ-108
    sub:  str
    role: str
    exp:  int

class UserResponse(BaseModel):              # REQ-118
    id:           str
    display_name: str
    email:        str
    role:         str
    created_at:   datetime
```

**From B.6 — Auth dependency stubs (replace `NotImplementedError` in `app/auth/dependencies.py`):**

```python
async def get_current_user(request: Request, db: AsyncSession, session: dict):
    raise NotImplementedError  # Task 1.3

async def require_admin(user) -> User:
    raise NotImplementedError  # Task 1.3

async def require_owner_or_admin(resource_owner_id: str, user) -> None:
    raise NotImplementedError  # Task 1.3

CurrentUser = Annotated[User, Depends(get_current_user)]
AdminUser   = Annotated[User, Depends(require_admin)]
```

---

**Implementation steps:**

1. [REQ-100, REQ-102] In `app/auth/oidc.py`, configure `authlib` `StarletteOAuth2App` pointing at `https://login.microsoftonline.com/{AZURE_TENANT_ID}/v2.0`. Implement `initiate_login(request)` that stores a `state` nonce in the session and redirects to Azure. Implement `handle_callback(request, db)` that exchanges the code for tokens, decodes the id_token, checks `tid == AZURE_TENANT_ID` (raise `TenantMismatchError` on mismatch — REQ-102), and calls `_provision_user`.
2. [REQ-110, REQ-112, REQ-116] Implement `_provision_user(db, oid, email, display_name)` in `oidc.py`: look up by `azure_oid`; if not found, look up by `email`; if still not found, `INSERT` a new `User` with `role=UserRole.user`; return the user. This enforces that the same email always maps to one account regardless of OID reuse.
3. [REQ-104, REQ-106] In `app/auth/magic_link.py`, implement `send_magic_link(db, email, settings)`: generate a cryptographically random token (`secrets.token_urlsafe(32)`), store a `MagicLinkToken` record (token hash, user_id, expires_at = now+15 min, consumed=False), send an email via `aiosmtplib` with the link `{BASE_URL}/auth/magic/verify?token=...`. Implement `verify_magic_link(db, raw_token)`: hash the token, fetch the record, raise `MagicLinkExpiredError` if expired or consumed (REQ-106), mark consumed, return the `User`.
4. [REQ-108] In `app/auth/jwt.py`, implement `create_access_token(user)` → signed JWT (HS256, `JWT_SECRET`, 8-hour expiry) with claims `sub=user.id`, `role=user.role`. Implement `decode_access_token(token)` → `TokenPayload`, raising `HTTPException(401)` on invalid/expired. Implement `set_auth_cookie(response, token)` and `clear_auth_cookie(response)` using `HttpOnly=True`, `Secure=(ENVIRONMENT != "development")`, `SameSite=lax`.
5. [REQ-108, REQ-120] In `app/auth/dependencies.py`, implement `get_current_user`: read the JWT from the `access_token` HttpOnly cookie (fall back to `Authorization: Bearer` header for API clients); decode via `decode_access_token`; if `settings.DEV_AUTH_BYPASS` is True and no token present, return a hardcoded dev user with `role=admin`. Fetch and return the `User` from DB; raise `HTTPException(401)` if not found or inactive.
6. [REQ-114] Implement `require_admin(user: CurrentUser)`: raise `HTTPException(403)` if `user.role != UserRole.admin`.
7. [REQ-122] Implement `require_owner_or_admin(resource_owner_id, user: CurrentUser)`: raise `HTTPException(403)` unless `user.id == resource_owner_id` or `user.role == UserRole.admin`.
8. [REQ-100, REQ-104, REQ-118, REQ-124, REQ-126, REQ-128] In `app/routes/auth.py`, create an `APIRouter(prefix="/auth")` with the following endpoints:
   - `GET /auth/login` — redirect to Azure AD (REQ-100)
   - `GET /auth/callback` — handle OIDC callback, issue cookie, redirect to `/` (REQ-100)
   - `POST /auth/magic/send` — accept `MagicLinkRequest`, call `send_magic_link`, return 204 (REQ-104)
   - `GET /auth/magic/verify` — verify token, issue cookie, redirect to `/` (REQ-106)
   - `POST /auth/logout` — clear cookie, return 204 (REQ-124)
   - `GET /auth/me` — return `UserResponse` for `CurrentUser` (REQ-118)
   - `PATCH /auth/me` — update `display_name` (REQ-126)
9. [REQ-128] Add structured audit log calls (`logger.info({"event": "login", "user_id": ..., "method": "oidc"|"magic_link"})`) at every successful authentication point. Use Python's `logging` module with a JSON formatter; do not use a third-party log library.
10. Add module-level docstring and `@summary` block to every created Python file.

**Completion criteria:**
- [ ] All stubs in B.6 implemented — no `NotImplementedError` remaining in `app/auth/dependencies.py`
- [ ] `GET /auth/login` redirects to `login.microsoftonline.com` with correct `client_id` and `state`
- [ ] `TenantMismatchError` raised and mapped to HTTP 403 when `tid` mismatches
- [ ] Magic link token expires after 15 minutes and cannot be reused (`MagicLinkExpiredError` → 410)
- [ ] JWT cookie is `HttpOnly`; `Secure` flag is set outside development environment
- [ ] `DEV_AUTH_BYPASS=True` returns a valid dev user without a token
- [ ] `require_admin` returns 403 for non-admin users
- [ ] `GET /auth/me` returns `UserResponse` JSON
- [ ] Audit log line emitted on every successful login
- [ ] Integration contracts honored
- [ ] Module-level docstring present on each file

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Phase 2 — Core Domain

## Task 2.1: Problem CRUD, Status FSM, Claiming, Pinning, Edit History, Duplicates

**Description:** Core problem lifecycle — creating problems with tags and categories, transitioning status through a defined FSM, claiming problems (with primary designation and 14-day expiry), pinning (max 3), edit history tracking, and duplicate suggestion/confirmation workflow.
**Spec requirements:** REQ-150, REQ-152, REQ-154, REQ-156, REQ-158, REQ-160, REQ-162, REQ-164, REQ-166
**Dependencies:** Task 1.3

**Source files:**
- CREATE `app/services/problems.py`
- CREATE `app/routes/problems.py`
- MODIFY `app/models/problem.py`

---

**Phase 0 contracts (inlined — implement these stubs):**

```python
def create_problem(db, user_id, data: ProblemCreate) -> Problem:
    """Persist a new Problem and tag associations. Raises IntegrityError if category/tags invalid. REQ-150,152,154"""
    raise NotImplementedError("Task 2.1")

def transition_status(db, problem_id, target: ProblemStatus, actor_id) -> Problem:
    """Apply FSM transition. Raises ForbiddenTransitionError on illegal. REQ-156"""
    raise NotImplementedError("Task 2.1")

def claim_problem(db, problem_id, user_id) -> Claim:
    """Create/toggle claim. First=primary. Idempotent. REQ-158"""
    raise NotImplementedError("Task 2.1")

def pin_problem(db, problem_id, admin_id) -> Problem:
    """Toggle pin, max 3. Raises PinLimitExceededError. REQ-164"""
    raise NotImplementedError("Task 2.1")
```

Also uses: `ProblemCreate`, `ProblemResponse`, `ProblemDetailResponse`, `ForbiddenTransitionError`, `PinLimitExceededError`, `ProblemStatus` enum

---

**Implementation steps:**
1. [REQ-150, REQ-152, REQ-154] Implement `create_problem`: validate that the referenced category exists, bulk-insert tag associations via join table, persist the `Problem` row, and re-raise `IntegrityError` for invalid FK references with a 422 response.
2. [REQ-156] Define the FSM transition table as a dict mapping `(current_status, target_status)` to a predicate (e.g., `lambda actor: actor.is_admin`). In `transition_status`, look up the pair and raise `ForbiddenTransitionError` if the pair is absent or the predicate fails, then commit the status update and append an edit-history record.
3. [REQ-158, REQ-160] Implement `claim_problem`: if an active claim already exists for this user, toggle it off (idempotent unclaim); otherwise insert a new `Claim` row, setting `is_primary=True` only if no other active claim exists for the problem.
4. [REQ-162] Add a scheduled job (APScheduler or Celery beat) that runs daily, queries claims where `created_at < now() - interval 14 days` and `is_primary=False`, and soft-deletes them; primary claims are not expired.
5. [REQ-166] Implement the duplicate workflow: a `suggest_duplicate(db, problem_id, target_id, user_id)` function that records a pending `DuplicateSuggestion`, and a `confirm_duplicate(db, suggestion_id, admin_id)` function that transitions the source problem to `DUPLICATE` status and links `duplicate_of_id`.
6. [REQ-164] Implement `pin_problem`: query the count of currently pinned problems; if count is already 3 and the target is not already pinned, raise `PinLimitExceededError`; otherwise toggle `is_pinned` on the target row.
7. [REQ-162] Implement edit history: on every field update to a `Problem`, insert an `EditHistory` row capturing `(problem_id, editor_id, field_name, old_value, new_value, edited_at)` before committing the update.
8. Create `app/routes/problems.py` with FastAPI router: `POST /problems`, `GET /problems/{id}`, `PATCH /problems/{id}`, `POST /problems/{id}/status`, `POST /problems/{id}/claim`, `POST /problems/{id}/pin`, `POST /problems/{id}/duplicate`.
9. Add module-level docstring to both `app/services/problems.py` and `app/routes/problems.py`.

**Completion criteria:**
- [ ] All stubs implemented — no `NotImplementedError` remaining
- [ ] Integration contracts honored
- [ ] Module-level docstring present

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**
> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries, the full spec, the full design doc, or the complete implementation docs.

---

## Task 2.2: Feed — Cursor Pagination, Sort, Filter

**Description:** Paginated problem feed with cursor-based pagination, four sort modes, composable filters, pinned-above-fold logic on page one, and activity tracking for the "recent activity" sort.
**Spec requirements:** REQ-168, REQ-170, REQ-172, REQ-174, REQ-176, REQ-178, REQ-180, REQ-182
**Dependencies:** Task 2.1

**Source files:**
- CREATE `app/services/feed.py`
- MODIFY `app/routes/problems.py`

---

**Phase 0 contracts (inlined — implement these stubs):**

```python
def get_feed(
    db,
    sort: SortMode,
    filters: dict,
    cursor: str | None,
    limit: int,
    user_id: int | None,
) -> CursorPage[ProblemResponse]:
    """Cursor-paginated, sorted, filtered feed. Pinned above first page. REQ-168,170,172,174"""
    raise NotImplementedError("Task 2.2")
```

Also uses: `CursorPage`, `ProblemResponse`, `SortMode` enum

---

**Implementation steps:**
1. [REQ-168] Implement opaque cursor encode/decode: serialize `(sort_key_value, id)` as a base64 JSON string; on decode, validate structure and raise `InvalidCursorError` (→ 400) on malformed input.
2. [REQ-170] Implement the four `SortMode` variants: `NEWEST` (order by `created_at DESC, id DESC`), `UPSTARS` (order by `upstar_count DESC, id DESC`), `RECENT_ACTIVITY` (order by `activity_at DESC, id DESC`), `CLAIMS` (order by `claim_count DESC, id DESC`). Each sort mode determines the cursor tuple fields.
3. [REQ-172] Build filter composition: accept optional query params `status`, `category_id`, `tag_ids` (multi), `claimed` (bool), `search` (full-text trigram). Each non-None filter appends a `WHERE` clause fragment; filters are ANDed together.
4. [REQ-174] Implement pinned-above logic: when `cursor` is `None` (first page), prepend all rows where `is_pinned=True` to the result list before applying the normal sort. Pinned rows do not consume slots from `limit`; set a `pinned` flag on each returned `ProblemResponse`.
5. [REQ-176] Construct the keyset pagination predicate from the decoded cursor and the active sort mode (e.g., `(activity_at, id) < (cursor_activity_at, cursor_id)`), then fetch `limit + 1` rows to determine whether a next page exists.
6. [REQ-178] Return a `CursorPage` with fields `items`, `next_cursor` (None if no further page), `total_count` (approximate via `COUNT(*)` on the filtered query without the cursor predicate).
7. [REQ-180] Add an `Idempotency-Key` header check on the feed `GET` endpoint: cache the response keyed by `(user_id, Idempotency-Key)` in Redis with a 60-second TTL, returning the cached response on repeat requests.
8. [REQ-182] Implement `activity_at` tracking: update `problems.activity_at = now()` whenever a comment, solution, or claim is added to the problem. Wire this update into the relevant service calls via a shared `touch_activity(db, problem_id)` helper.
9. Add `GET /problems` route to `app/routes/problems.py` wired to `get_feed`, exposing all filter and sort query params.
10. Add module-level docstring to `app/services/feed.py`.

**Completion criteria:**
- [ ] All stubs implemented — no `NotImplementedError` remaining
- [ ] Integration contracts honored
- [ ] Module-level docstring present

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**
> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries, the full spec, the full design doc, or the complete implementation docs.

---

## Task 2.3: Solutions — CRUD, Versioning, Acceptance

**Description:** Full solution lifecycle — creating solutions for problems, append-only versioning with immutable history, atomic acceptance swap (one accepted solution per problem), anonymous solution support, and default/newest-first sort toggle.
**Spec requirements:** REQ-200, REQ-202, REQ-204, REQ-206, REQ-208, REQ-210, REQ-212, REQ-214, REQ-216, REQ-218, REQ-220
**Dependencies:** Task 2.1

**Source files:**
- CREATE `app/services/solutions.py`
- CREATE `app/routes/solutions.py`
- MODIFY `app/models/solution.py`

---

**Phase 0 contracts (inlined — implement these stubs):**

```python
def create_solution(db, problem_id, user_id, data: SolutionCreate) -> Solution:
    """Persist new Solution. REQ-200,204"""
    raise NotImplementedError("Task 2.3")

def accept_solution(db, solution_id, actor_id) -> Solution:
    """Mark accepted. Previous→proposed atomically. REQ-210"""
    raise NotImplementedError("Task 2.3")

def create_version(db, solution_id, user_id, data: SolutionVersionCreate) -> SolutionVersion:
    """Append new version. Immutable. REQ-206"""
    raise NotImplementedError("Task 2.3")
```

Also uses: `SolutionCreate`, `SolutionVersionCreate`, `SolutionResponse`

---

**Implementation steps:**
1. [REQ-200, REQ-204] Implement `create_solution`: validate that the referenced `problem_id` exists and is not in a terminal status; if `user_id` is None, set `is_anonymous=True`; insert the `Solution` row; auto-create the first `SolutionVersion` row (version number 1) in the same transaction.
2. [REQ-206] Implement `create_version`: compute `next_version = MAX(version_number) + 1` for the solution within the transaction; insert a new immutable `SolutionVersion` row with the content snapshot; rely on a `UNIQUE(solution_id, version_number)` DB constraint to prevent races.
3. [REQ-208] Block `PATCH` and `PUT` on the solution body at the route layer — return `405 Method Not Allowed` with a message directing clients to `POST /solutions/{id}/versions` instead.
4. [REQ-212] Implement a `GET /solutions/{id}/versions` endpoint that returns the full ordered version history (`version_number ASC`).
5. [REQ-210] Implement `accept_solution`: within a single transaction, set `status = PROPOSED` on the currently accepted solution for this problem (if any), then set `status = ACCEPTED` on the target solution; raise `ForbiddenError` if `actor_id` is not the problem owner or an admin.
6. [REQ-214, REQ-216] Implement default sort (accepted first, then by `upvote_count DESC`) and a `?sort=newest` toggle (order by `created_at DESC`) on `GET /problems/{id}/solutions`.
7. [REQ-218] Implement anonymous solution masking: when returning `SolutionResponse`, replace `author_id` and `author_username` with `null` when `is_anonymous=True`, unless the requesting user is the author or an admin.
8. [REQ-220] Add solution count denormalization: increment `problems.solution_count` on insert and decrement on hard delete using DB triggers or service-layer calls.
9. Create `app/routes/solutions.py` with routes: `POST /problems/{id}/solutions`, `GET /problems/{id}/solutions`, `GET /solutions/{id}`, `POST /solutions/{id}/versions`, `GET /solutions/{id}/versions`, `POST /solutions/{id}/accept`.
10. Add module-level docstring to both `app/services/solutions.py` and `app/routes/solutions.py`.

**Completion criteria:**
- [ ] All stubs implemented — no `NotImplementedError` remaining
- [ ] Integration contracts honored
- [ ] Module-level docstring present

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**
> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries, the full spec, the full design doc, or the complete implementation docs.

---

## Task 2.4: Voting — Upstars and Solution Upvotes

**Description:** Toggle-based voting for problems (upstars) and solutions (upvotes), with atomic count updates, duplicate-vote prevention, and anonymous user exclusion from leaderboard tallies.
**Spec requirements:** REQ-250, REQ-252, REQ-254, REQ-256, REQ-270
**Dependencies:** Task 2.1, Task 2.3

**Source files:**
- CREATE `app/services/voting.py`
- CREATE `app/routes/voting.py`

---

**Phase 0 contracts (inlined — implement these stubs):**

```python
def toggle_upstar(db, problem_id, user_id) -> tuple[bool, int]:
    """Toggle upstar. Returns (is_active, new_count). REQ-250,252"""
    raise NotImplementedError("Task 2.4")

def toggle_solution_upvote(db, solution_id, user_id) -> tuple[bool, int]:
    """Toggle solution upvote. REQ-254,256"""
    raise NotImplementedError("Task 2.4")
```

Also uses: `DuplicateVoteError`

---

**Implementation steps:**
1. [REQ-250, REQ-252] Implement `toggle_upstar`: attempt an `INSERT INTO upstars (problem_id, user_id)` inside a `try/except IntegrityError` block; if the row already exists, `DELETE` it and decrement `problems.upstar_count`; on insert, increment the count. Return `(True, new_count)` when activated, `(False, new_count)` when deactivated. Use `SELECT ... FOR UPDATE` on the problem row to serialize concurrent toggles.
2. [REQ-254, REQ-256] Implement `toggle_solution_upvote` with the identical pattern against the `solution_upvotes` table and `solutions.upvote_count` column.
3. [REQ-252, REQ-256] Ensure both count columns are updated atomically with the insert/delete in the same transaction — never update the count in a separate query that could race.
4. [REQ-270] Implement anonymous exclusion for leaderboard: when computing ranked upstar counts for any leaderboard query, exclude votes cast by users where `users.is_anonymous=True`. Expose a `get_leaderboard_upstar_counts(db)` helper that applies this filter.
5. Create `app/routes/voting.py` with routes: `POST /problems/{id}/upstar` and `POST /solutions/{id}/upvote`. Both return `{"active": bool, "count": int}`.
6. Add module-level docstring to both `app/services/voting.py` and `app/routes/voting.py`.

**Completion criteria:**
- [ ] All stubs implemented — no `NotImplementedError` remaining
- [ ] Integration contracts honored
- [ ] Module-level docstring present

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**
> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries, the full spec, the full design doc, or the complete implementation docs.

---

## Task 2.5: Comments — Threaded, Anonymous, Markdown, Edit/Delete

**Description:** Threaded comment system supporting both problems and solutions as parents, anonymous posting with masked authorship, markdown rendering with sanitization, tombstone-aware deletion, and edit history.
**Spec requirements:** REQ-258, REQ-260, REQ-262, REQ-264, REQ-266
**Dependencies:** Task 2.1, Task 2.3

**Source files:**
- CREATE `app/services/comments.py`
- CREATE `app/routes/comments.py`
- MODIFY `app/models/comment.py`

---

**Phase 0 contracts (inlined — implement these stubs):**

Schemas to define (no service stubs — implement service functions from scratch):

```python
class CommentCreate(BaseModel):
    body: str
    parent_type: Literal["problem", "solution"]
    parent_id: int
    reply_to_id: int | None = None
    is_anonymous: bool = False

class CommentResponse(BaseModel):
    id: int
    body: str | None          # None when tombstoned
    is_tombstone: bool
    author_id: int | None     # None when anonymous or tombstoned
    author_username: str | None
    parent_type: str
    parent_id: int
    reply_to_id: int | None
    created_at: datetime
    updated_at: datetime
    replies: list["CommentResponse"] = []
```

---

**Implementation steps:**
1. [REQ-258] Implement `create_comment(db, user_id, data: CommentCreate) -> Comment`: validate that `parent_type`/`parent_id` resolve to an existing problem or solution; if `reply_to_id` is set, validate it belongs to the same parent; set `is_anonymous` on the row; insert and return.
2. [REQ-260] Implement anonymous masking in `CommentResponse` serialization: when `is_anonymous=True`, set `author_id=None` and `author_username=None` unless the requesting user is the comment author or an admin.
3. [REQ-262] Implement `delete_comment(db, comment_id, actor_id) -> Comment`: if the comment has no replies, hard-delete the row; if it has replies, set `is_tombstone=True`, replace `body` with `None`, and clear author fields — do not delete the row. Only the comment author or an admin may delete.
4. [REQ-264] Implement `edit_comment(db, comment_id, actor_id, new_body: str) -> Comment`: validate authorship; insert a `CommentEditHistory` row capturing `(comment_id, old_body, edited_at)`; update `body` and `updated_at` on the comment row.
5. [REQ-266] Implement markdown sanitization: use `bleach.clean()` with an allowlist of safe tags (`p`, `strong`, `em`, `code`, `pre`, `blockquote`, `ul`, `ol`, `li`, `a`) and strip all other HTML. Apply sanitization at write time (store sanitized HTML) and surface the result in `CommentResponse.body`.
6. Implement `get_comments(db, parent_type, parent_id) -> list[CommentResponse]`: fetch top-level comments (where `reply_to_id IS NULL`) and recursively nest replies up to a reasonable depth limit (e.g., 5 levels); tombstoned nodes are included in the tree with masked fields.
7. Create `app/routes/comments.py` with routes: `POST /comments`, `GET /problems/{id}/comments`, `GET /solutions/{id}/comments`, `PATCH /comments/{id}`, `DELETE /comments/{id}`.
8. Add module-level docstring to both `app/services/comments.py` and `app/routes/comments.py`.

**Completion criteria:**
- [ ] All stubs implemented — no `NotImplementedError` remaining
- [ ] Integration contracts honored
- [ ] Module-level docstring present

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**
> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries, the full spec, the full design doc, or the complete implementation docs.

---

## Task 2.6: Attachments — Upload, Validate, Store, Serve

**Description:** Multipart file upload pipeline with MIME-type and extension allowlist validation, per-file and per-problem size caps, UUID-based storage paths, atomic deletion, NGINX static serving, and inline image rendering support.
**Spec requirements:** REQ-400, REQ-402, REQ-404, REQ-406, REQ-408, REQ-410, REQ-412, REQ-414, REQ-416
**Dependencies:** Task 2.1

**Source files:**
- CREATE `app/services/attachments.py`
- CREATE `app/routes/attachments.py`
- MODIFY `app/models/attachment.py`
- MODIFY `nginx/nginx.conf`

---

**Phase 0 contracts (inlined — implement these stubs):**

Exceptions to define (no service stubs — implement service functions from scratch):

```python
class FileSizeLimitError(AppError):
    """Raised when a single file exceeds 10 MB or cumulative problem attachments exceed 50 MB."""

class FileTypeNotAllowedError(AppError):
    """Raised when the uploaded file's MIME type or extension is not on the allowlist."""
```

---

**Implementation steps:**
1. [REQ-400, REQ-402] Implement the upload endpoint handler in `app/routes/attachments.py`: accept `multipart/form-data` with fields `problem_id` and `file`. Stream the file into a temporary buffer; do not persist until validation passes.
2. [REQ-404] Implement type validation in `app/services/attachments.py`: define an allowlist of `(mime_type, extension)` pairs (e.g., `image/png .png`, `image/jpeg .jpg`, `application/pdf .pdf`, `text/plain .txt`). Use `python-magic` to detect MIME from the file header; also check the declared filename extension. Raise `FileTypeNotAllowedError` if either check fails.
3. [REQ-406] Implement size validation: raise `FileSizeLimitError` if the file exceeds 10 MB. Query the sum of `attachments.file_size` for the given `problem_id`; raise `FileSizeLimitError` if adding this file would push the total past 50 MB.
4. [REQ-408] Implement UUID storage: generate a `uuid4` filename preserving the original extension (e.g., `a3f2...d1.png`). Write the file to the configured `ATTACHMENTS_DIR` (e.g., `/var/attachments/{problem_id}/{uuid_filename}`). Insert an `Attachment` row with `(problem_id, original_filename, stored_path, file_size, mime_type, uploader_id)`.
5. [REQ-410] Implement atomic deletion in `delete_attachment(db, attachment_id, actor_id) -> None`: within a transaction, delete the `Attachment` DB row first; only after a successful commit, delete the file from disk. If the filesystem delete fails, log the error but do not roll back the DB transaction (orphaned files are acceptable; missing DB rows are not).
6. [REQ-412, REQ-414] Configure NGINX in `nginx/nginx.conf`: add a `location /attachments/` block that serves files directly from `ATTACHMENTS_DIR` using `alias`. Set `internal` or restrict access via `X-Accel-Redirect` so files are only served when the app sets the header, preventing unauthenticated direct access.
7. [REQ-416] Implement inline image rendering: when returning an `AttachmentResponse`, include a `render_inline: bool` field set to `True` for image MIME types. The frontend uses this flag to embed an `<img>` tag rather than a download link; no server-side rendering is needed.
8. Create `app/routes/attachments.py` with routes: `POST /problems/{id}/attachments`, `GET /problems/{id}/attachments`, `DELETE /attachments/{id}`, and a `GET /attachments/{id}/download` route that sets `X-Accel-Redirect` and returns a 200 with an empty body for NGINX to serve.
9. Add module-level docstring to both `app/services/attachments.py` and `app/routes/attachments.py`.

**Completion criteria:**
- [ ] All stubs implemented — no `NotImplementedError` remaining
- [ ] Integration contracts honored
- [ ] Module-level docstring present

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**
> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries, the full spec, the full design doc, or the complete implementation docs.

---

## Phase 3 — Search, Notifications & Engagement

## Task 3.1: Full-Text Search & Similar-Problem Suggestions
**Description:** Implements cross-entity full-text search over problems, solutions, and comments using PostgreSQL tsvector/GIN indexes and ts_rank scoring, plus a similar-problem suggestion endpoint.
**Spec requirements:** REQ-350, REQ-352, REQ-354, REQ-356, REQ-358, REQ-360, REQ-362, REQ-364
**Dependencies:** Task 2.1, Task 2.3, Task 2.5
**Source files:**
- CREATE `app/services/search.py`
- CREATE `app/routes/search.py`
---
**Phase 0 contracts (inlined — implement these stubs):**
```python
def search_problems(db, query: str, sort: str, filters: dict, limit: int) -> list[dict]:
    """Full-text search with cross-entity indexing and ts_rank. REQ-350,352,354"""
    raise NotImplementedError("Task 3.1")

def suggest_similar(db, title: str, limit: int = 5) -> list[dict]:
    """Return up to 5 similar problems. REQ-362"""
    raise NotImplementedError("Task 3.1")
```
---
**Implementation steps:**
1. [REQ-350] Add `tsvector` generated columns to `problems`, `solutions`, and `comments` tables; create GIN indexes on each.
2. [REQ-352] Implement `search_problems` using `plainto_tsquery` and `ts_rank` for ranked results against the problems tsvector column.
3. [REQ-354] Extend search with a UNION query across solutions and comments, rolling results up to their parent problem; deduplicate by problem ID before returning.
4. [REQ-356] Add `sort` parameter supporting `relevance` (ts_rank DESC), `upvotes` (upvote count DESC), and `newest` (created_at DESC) modes.
5. [REQ-358] Add `filters` parameter supporting category, tag, and status filtering applied before ranking.
6. [REQ-360] Return a structured empty-state message (`{"results": [], "message": "No results found for …"}`) when the result set is empty.
7. [REQ-362] Implement `suggest_similar` using ts_rank against the problem's title tokens; return at most 5 results excluding the source problem.
8. [REQ-364] Include a 120-character excerpt from the matched body text (trimmed at word boundary) in every suggestion result dict.

**Completion criteria:**
- [ ] All stubs implemented
- [ ] Integration contracts honored
- [ ] Module-level docstring present
---
**Agent isolation contract (copy verbatim into implement-code dispatch):**
> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries, the full spec, the full design doc, or the complete implementation docs.
---

## Task 3.2: Link Previews — Open Graph Meta Tags & Bot Detection
**Description:** Generates Open Graph HTML meta tags for problem links and routes social/crawler bot requests through NGINX to the meta endpoint so unfurled links display rich previews.
**Spec requirements:** REQ-366, REQ-368
**Dependencies:** Task 2.1
**Source files:**
- CREATE `app/routes/meta.py`
- MODIFY `nginx/nginx.conf`
---
**Phase 0 contracts (inlined — implement these stubs):**
None.
---
**Implementation steps:**
1. [REQ-366] Create `GET /api/problems/{id}/meta` that queries the problem by ID and returns a minimal HTML document containing `<meta property="og:*">` tags for title, description (first 200 chars of body), URL, and site name.
2. [REQ-366] Return HTTP 404 with a plain-text body when the problem ID does not exist.
3. [REQ-368] In `nginx/nginx.conf`, add a `map` block that matches known bot User-Agent substrings (Twitterbot, facebookexternalhit, Slackbot, LinkedInBot, Discordbot, TelegramBot, WhatsApp) to a flag variable.
4. [REQ-368] Add a location block (or `if` guard scoped to the SPA catch-all) that proxies requests to `/problems/{id}` to `GET /api/problems/{id}/meta` when the bot flag is set, leaving all other traffic unaffected.

**Completion criteria:**
- [ ] All stubs implemented
- [ ] Integration contracts honored
- [ ] Module-level docstring present
---
**Agent isolation contract (copy verbatim into implement-code dispatch):**
> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries, the full spec, the full design doc, or the complete implementation docs.
---

## Task 3.3: Watch System & Notification Generation
**Description:** Implements the watch subscription model (per-problem, per-user watch levels) and the fan-out logic that generates in-app Notification rows for qualifying watchers when problem lifecycle events occur.
**Spec requirements:** REQ-300, REQ-302, REQ-304, REQ-306, REQ-308, REQ-310, REQ-312, REQ-324
**Dependencies:** Task 2.1, Task 2.3
**Source files:**
- CREATE `app/services/watches.py`
- CREATE `app/services/notifications.py`
- MODIFY `app/models/watch.py`
- MODIFY `app/models/notification.py`
- CREATE `app/routes/watches.py`
---
**Phase 0 contracts (inlined — implement these stubs):**
```python
# Enums expected to exist in models (add if absent):
# class WatchLevel(str, Enum): all_activity, solutions_only, mentions_only
# class NotificationType(str, Enum): new_solution, solution_accepted, new_comment,
#     status_change, claim_assigned, claim_expired, upvote_milestone, mention

def generate_notification(
    db,
    event_type: NotificationType,
    problem_id: int,
    solution_id: int | None,
    actor_id: int,
) -> list[Notification]:
    """Fan out to qualifying watchers based on watch level routing.
    Excludes actor. REQ-310,312"""
    raise NotImplementedError("Task 3.3")
```
---
**Implementation steps:**
1. [REQ-300] Ensure `watches` table exists with columns `(id, user_id, problem_id, level: WatchLevel, created_at)`; add unique constraint on `(user_id, problem_id)`.
2. [REQ-302] Implement `POST /api/problems/{id}/watch` (upsert watch level) and `DELETE /api/problems/{id}/watch`; return 204.
3. [REQ-304] Implement `GET /api/problems/{id}/watch` returning the caller's current watch record or 404.
4. [REQ-306] Implement auto-watch side effects: set `all_activity` when a user posts a problem, claims it, or submits a solution; set `solutions_only` when a user comments.
5. [REQ-308] Allow user preference overrides to persist over auto-watch (do not downgrade an existing higher-level watch).
6. [REQ-310] Implement the routing matrix in `generate_notification`: `all_activity` receives all event types; `solutions_only` receives `new_solution`, `solution_accepted`, `upvote_milestone`; `mentions_only` receives only `mention`.
7. [REQ-312] Exclude the `actor_id` from the fan-out recipient list in `generate_notification`; bulk-insert resulting `Notification` rows and return them.
8. [REQ-324] Create a background job (`app/jobs/claim_expiry.py` or inline scheduler entry) that runs at most every 15 minutes, finds claims past their deadline, emits `claim_expired` events via `generate_notification`, and is idempotent (skip already-expired claims).

**Completion criteria:**
- [ ] All stubs implemented
- [ ] Integration contracts honored
- [ ] Module-level docstring present
---
**Agent isolation contract (copy verbatim into implement-code dispatch):**
> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries, the full spec, the full design doc, or the complete implementation docs.
---

## Task 3.4: Notification Delivery — In-App, WebSocket, Teams, Email
**Description:** Delivers generated notifications to users via four channels: paginated REST API, real-time WebSocket push, Microsoft Teams webhook, and daily email digest; includes milestone deduplication.
**Spec requirements:** REQ-314, REQ-316, REQ-318, REQ-320, REQ-322
**Dependencies:** Task 3.3
**Source files:**
- CREATE `app/services/delivery.py`
- CREATE `app/routes/notifications.py`
- CREATE `app/routes/ws.py`
---
**Phase 0 contracts (inlined — implement these stubs):**
None — implement all delivery logic from scratch.
---
**Implementation steps:**
1. [REQ-314] Implement `GET /api/notifications` returning paginated notification records for the authenticated user, ordered by `created_at DESC`; support `?unread_only=true` filter and include total unread count in the response envelope.
2. [REQ-314] Implement `PATCH /api/notifications/{id}/read` (mark single notification read) and `POST /api/notifications/read-all` (mark all read for caller); both return 204.
3. [REQ-316] In `app/routes/ws.py`, implement a `ConnectionManager` class with `connect`, `disconnect`, and `broadcast_to_user` methods backed by an in-memory dict keyed by user ID.
4. [REQ-316] Expose `GET /api/ws/notifications` as a WebSocket endpoint; authenticate via token query param; push new notification JSON to the caller's connection immediately upon `generate_notification` fan-out.
5. [REQ-318] In `app/services/delivery.py`, implement `send_teams_webhook(notification)` that posts an Adaptive Card payload to the user's configured Teams webhook URL; make the call non-blocking (fire-and-forget via `asyncio.create_task`); suppress and log errors without raising.
6. [REQ-320] Implement a daily email digest job that aggregates undelivered email-eligible notifications per user, renders a plain-text summary, and sends via configured SMTP; mark notifications as email-delivered after successful send.
7. [REQ-322] Implement milestone deduplication in `delivery.py`: for `upvote_milestone` events, only generate a notification at thresholds 10, 25, 50, and 100; suppress subsequent fan-out if the milestone was already delivered.

**Completion criteria:**
- [ ] All stubs implemented
- [ ] Integration contracts honored
- [ ] Module-level docstring present
---
**Agent isolation contract (copy verbatim into implement-code dispatch):**
> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries, the full spec, the full design doc, or the complete implementation docs.
---

## Task 3.5: Leaderboard
**Description:** Implements the leaderboard feature exposing ranked Top Solvers and Top Reporters tracks, filterable by time window, with anonymous contributions excluded.
**Spec requirements:** REQ-268, REQ-270
**Dependencies:** Task 2.4
**Source files:**
- CREATE `app/services/leaderboard.py`
- CREATE `app/routes/leaderboard.py`
---
**Phase 0 contracts (inlined — implement these stubs):**
None.
---
**Implementation steps:**
1. [REQ-268] Implement `GET /api/leaderboard` accepting a `time_filter` query parameter with values `all_time`, `this_month`, and `this_week`; apply the filter as a `created_at >=` cutoff on the aggregated events.
2. [REQ-268] Implement the **Top Solvers** track: rank users by count of accepted solutions within the time window; return `user_id`, `display_name`, `accepted_solution_count`, and `rank`.
3. [REQ-270] Implement the **Top Reporters** track: rank users by total upvotes received on problems they reported within the time window; return `user_id`, `display_name`, `total_upvotes_received`, and `rank`.
4. [REQ-270] Exclude any contributions where the problem or solution was posted anonymously (i.e., `anonymous=true`) from both tracks before ranking.

**Completion criteria:**
- [ ] All stubs implemented
- [ ] Integration contracts honored
- [ ] Module-level docstring present
---
**Agent isolation contract (copy verbatim into implement-code dispatch):**
> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries, the full spec, the full design doc, or the complete implementation docs.
---

## Phase 4 — Administration

## Task 4.1: Category Management — CRUD, Reorder, Soft-Delete
**Description:** Implements admin-gated category management including full CRUD, drag-and-drop reorder via a batch endpoint, and soft-delete with referential integrity protection.
**Spec requirements:** REQ-452, REQ-456, REQ-458
**Dependencies:** Task 1.2
**Source files:**
- CREATE `app/services/categories.py`
- CREATE `app/routes/admin/categories.py`
- CREATE `app/routes/admin/__init__.py`
---
**Phase 0 contracts (inlined — implement these stubs):**
None.
---
**Implementation steps:**
1. [REQ-452] Create `app/routes/admin/__init__.py` registering an `admin_router` with prefix `/api/admin`; apply the `require_admin` dependency (defined in Task 1.3) to the entire router.
2. [REQ-452] In `app/services/categories.py`, implement `create_category`, `update_category`, and `get_categories` (returns ordered list by `sort_order`).
3. [REQ-452] Expose `GET /api/admin/categories`, `POST /api/admin/categories`, and `PATCH /api/admin/categories/{id}` backed by the service functions above.
4. [REQ-456] Implement `PATCH /api/categories/reorder` accepting `[{id, sort_order}]`; apply all updates atomically in a single transaction.
5. [REQ-458] Implement soft-delete: `DELETE /api/admin/categories/{id}` sets `deleted_at = now()` rather than removing the row; return 409 if any non-deleted problem still references the category.

**Completion criteria:**
- [ ] All stubs implemented
- [ ] Integration contracts honored
- [ ] Module-level docstring present
---
**Agent isolation contract (copy verbatim into implement-code dispatch):**
> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries, the full spec, the full design doc, or the complete implementation docs.
---

## Task 4.2: Tag Management — CRUD, Merge, Usage Counts
**Description:** Implements admin tag management including usage-count-annotated listing, rename, full delete (strips tag from all problems), and atomic merge of two tags into one.
**Spec requirements:** REQ-460, REQ-462, REQ-464
**Dependencies:** Task 2.1
**Source files:**
- CREATE `app/services/tags.py`
- CREATE `app/routes/admin/tags.py`
---
**Phase 0 contracts (inlined — implement these stubs):**
None.
---
**Implementation steps:**
1. [REQ-460] Implement `GET /api/tags` returning all tags annotated with `usage_count` (number of non-deleted problems using the tag); support `?sort=usage` (desc by count) and `?sort=name` (alphabetical) query parameters.
2. [REQ-462] Implement `PATCH /api/admin/tags/{id}` for rename: update the tag's `name` field, enforce uniqueness, return 409 on conflict.
3. [REQ-462] Implement `DELETE /api/admin/tags/{id}`: remove the tag from all `problem_tags` join rows, then delete the tag record; wrap in a single transaction.
4. [REQ-464] Implement `POST /api/admin/tags/merge` accepting `{source_id, target_id}`: re-point all `problem_tags` rows from `source_id` to `target_id` (ignoring duplicates), then delete the source tag; the entire operation must be atomic.

**Completion criteria:**
- [ ] All stubs implemented
- [ ] Integration contracts honored
- [ ] Module-level docstring present
---
**Agent isolation contract (copy verbatim into implement-code dispatch):**
> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries, the full spec, the full design doc, or the complete implementation docs.
---

## Task 4.3: User Management & Moderation
**Description:** Implements admin user management (search, role/status changes with session invalidation), moderation tooling (flagged content queue, de-anonymize with audit log), and app configuration endpoint, all gated behind the require_admin dependency.
**Spec requirements:** REQ-450, REQ-466, REQ-468, REQ-470, REQ-472, REQ-474, REQ-476
**Dependencies:** Task 1.3
**Source files:**
- CREATE `app/services/admin.py`
- CREATE `app/routes/admin/users.py`
- CREATE `app/routes/admin/moderation.py`
- CREATE `app/routes/admin/config.py`
---
**Phase 0 contracts (inlined — implement these stubs):**
```python
# require_admin is defined in Task 1.3 (app/dependencies/auth.py).
# Import and apply it to every route in this task.
# Signature for reference:
# async def require_admin(current_user: User = Depends(get_current_user)) -> User: ...
```
---
**Implementation steps:**
1. [REQ-450] Apply `require_admin` as a router-level dependency to all routes defined in `users.py`, `moderation.py`, and `config.py`.
2. [REQ-466] Implement `GET /api/admin/users` with a `?q=` parameter performing case-insensitive partial match against `username` and `email`; return paginated results with `role` and `status` fields.
3. [REQ-468] Implement `PATCH /api/admin/users/{id}/role` and `PATCH /api/admin/users/{id}/status`; after persisting the change, invalidate all active sessions for the affected user (delete from sessions table or revoke tokens).
4. [REQ-470] Implement `GET /api/admin/moderation/flags` returning flagged problems and solutions ordered by flag count desc; support `?status=pending|resolved` filter.
5. [REQ-472] Implement `POST /api/admin/moderation/flags/{id}/resolve` marking a flag resolved with an optional `resolution_note`; return 204.
6. [REQ-474] Implement `POST /api/admin/moderation/de-anonymize/{problem_id}`: reveal the true author of an anonymous problem; write an immutable audit log row (admin_id, problem_id, timestamp, action="de-anonymize") before making any change.
7. [REQ-476] Implement `GET /api/admin/config` and `PATCH /api/admin/config` for reading and updating runtime app configuration key-value pairs stored in the database; validate keys against a hardcoded allowlist.

**Completion criteria:**
- [ ] All stubs implemented
- [ ] Integration contracts honored
- [ ] Module-level docstring present
---
**Agent isolation contract (copy verbatim into implement-code dispatch):**
> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries, the full spec, the full design doc, or the complete implementation docs.
---

## Phase 5 — Frontend

## Task 5.1: App Shell — Routing, Theme, Dark Mode, Responsive Layout
**Description:** Foundation layer providing React Router configuration with deep linking, CSS-in-JS theme system with yellow-to-lime gradient and status colors, OS-aware dark mode with localStorage persistence, and responsive grid layout (sidebar at ≥1024px, mobile nav <1024px). Vite configuration optimized for SPA.

**Spec requirements:** REQ-500, REQ-504, REQ-508, REQ-512, REQ-514, REQ-520

**Dependencies:** Task 1.1

**Source files:**
- CREATE `frontend/src/App.tsx`
- CREATE `frontend/src/theme/index.ts`
- CREATE `frontend/src/theme/colors.ts`
- CREATE `frontend/src/layouts/MainLayout.tsx`
- CREATE `frontend/src/layouts/Sidebar.tsx`
- CREATE `frontend/src/hooks/useDarkMode.ts`
- CREATE `frontend/vite.config.ts`
- CREATE `frontend/package.json`

---

**Phase 0 contracts (inlined):**
All theme tokens exported as TypeScript constants (no CSS files). Dark mode state managed via React context and `prefers-color-scheme` media query. Router uses React Router v6 with lazy code splitting. Layout components accept children as ReactNode. No environment variable defaults — all values required at build time.

---

**Implementation steps:**

1. [REQ-520] Initialize Vite + React 18 + TypeScript project with `npm create vite@latest frontend -- --template react-ts` and configure Vite to serve from `/`
2. [REQ-500] Create `theme/colors.ts` exporting primary gradient (start: #FFD700, end: #32CD32), neutral grays (light/dark variants), and status colors (success/warning/error/info) as TypeScript objects
3. [REQ-500] Create `theme/index.ts` exporting CSS variable names, theme tokens, and breakpoints (mobile: 0, tablet: 768px, desktop: 1024px)
4. [REQ-504] Implement `useDarkMode` hook detecting `prefers-color-scheme`, reading localStorage key `pb-theme`, and exposing `isDark` boolean and `toggle()` function
5. [REQ-508] Create MainLayout component with two-column grid (sidebar 250px on desktop, hidden <1024px) using CSS custom properties and `useMediaQuery` hook
6. [REQ-512] Build Sidebar component rendering nav links, user profile section, dark mode toggle, and hamburger trigger on mobile (display: none on desktop)
7. [REQ-514] Configure React Router in App.tsx with routes: `/`, `/problems`, `/problems/:id`, `/submit`, `/search`, `/ai-search`, `/leaderboard`, `/settings`, `/admin/*`, `*` (404), lazy-loading page components
8. [REQ-520] Inject APP_NAME from `import.meta.env.VITE_APP_NAME` into document title and Sidebar heading

**Completion criteria:**
- [ ] Vite dev server starts with `npm run dev` and serves at `http://localhost:5173`
- [ ] All theme tokens render correctly in light and dark modes
- [ ] Sidebar visible at 1280x800; hidden nav appears on mobile (640x800)
- [ ] Dark mode toggle persists across page refresh
- [ ] Router deep links resolve correctly; 404 page renders on unknown routes
- [ ] Module-level comments document theme structure and layout breakpoints

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**
> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, REQ-500/504/508/512/514/520, Phase 0 contracts inlined above, implementation steps)
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries, the full spec, the full design doc, or the complete implementation docs.

---

## Task 5.2: Landing Page & Auth Flow
**Description:** Public landing page featuring cork-texture background, decorative rotated cards at randomized angles (re-randomize on refresh), centered zero-tilt sign-in card with gradient border, tagline display, and integration with Azure AD and magic link authentication flows. Must render at 1280x800 viewport.

**Spec requirements:** REQ-502

**Dependencies:** Task 5.1, Task 1.3

**Source files:**
- CREATE `frontend/src/pages/Landing.tsx`
- CREATE `frontend/src/hooks/useAuth.ts`
- CREATE `frontend/src/components/AuthCard.tsx`

---

**Phase 0 contracts (inlined):**
Cork texture implemented as SVG pattern or CSS gradients (no image assets). Card rotation angles stored in component state (Math.random() * 8 - 4 range, 0 for auth card). useAuth hook returns `{ isAuthenticated, user, login, loginWithMagicLink, logout, isLoading }` matching Task 1.3 API shape. AuthCard accepts `onSuccess` callback firing post-login. No form submission — buttons only.

---

**Implementation steps:**

1. [REQ-502] Create useAuth hook wrapping Azure AD / magic link login functions from Task 1.3, exposing loading state and error messages
2. [REQ-502] Build AuthCard component with gradient border (yellow→lime), email/password inputs (or magic link input), sign-in button, and sign-up toggle, using `onSuccess` callback to redirect to `/problems`
3. [REQ-502] Implement Landing page with full-viewport cork-texture background (CSS + SVG pattern), grid of 6–8 decorative cards at random rotation angles (re-randomize state on component mount only)
4. [REQ-502] Center AuthCard on landing with `position: fixed` or flexbox overlay, z-index above decoration cards, zero tilt angle
5. [REQ-502] Display tagline ("Crowd-source solutions to workplace problems") below or beside auth card, responsive text size (clamp)
6. [REQ-502] Test viewport at 1280x800; verify cards remain visible and auth card readable

**Completion criteria:**
- [ ] Cork texture renders without external image files
- [ ] Decorative cards rotate at different angles each page load
- [ ] AuthCard renders centered, no tilt, with gradient border visible
- [ ] Tagline text scales smoothly from 1024px to 1920px
- [ ] Login button navigates to `/problems` on success
- [ ] Module-level docstring explains cork texture strategy and card randomization

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**
> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, REQ-502, Phase 0 contracts inlined above, implementation steps)
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries, the full spec, the full design doc, or the complete implementation docs.

---

## Task 5.3: Feed Page & Problem Detail
**Description:** Two-page experience: Feed displays sortable/filterable problem cards in a list with infinite scroll, each card showing upstar count, title, preview text, status badge, claimer name, category pill, tag badges, comment/solution counts, and timestamp. ProblemDetail page renders full markdown body with header (title, actions, metadata), and tabbed Solutions/Comments views controlled via URL query parameters.

**Spec requirements:** REQ-506, REQ-510

**Dependencies:** Task 5.1, Task 2.2

**Source files:**
- CREATE `frontend/src/pages/Feed.tsx`
- CREATE `frontend/src/pages/ProblemDetail.tsx`
- CREATE `frontend/src/components/ProblemCard.tsx`
- CREATE `frontend/src/components/StatusBadge.tsx`
- CREATE `frontend/src/components/SortFilterBar.tsx`

---

**Phase 0 contracts (inlined):**
ProblemCard accepts `problem: Problem` object matching Task 2.2 schema. StatusBadge maps status enum to color + label (open/claimed/resolved/archived). SortFilterBar exposes `onSort` and `onFilter` callbacks accepting sort key and filter object. Feed uses `useInfiniteQuery` (TanStack Query) with Task 2.2 GET /problems endpoint. ProblemDetail reads `?tab=solutions|comments` from URL; defaults to solutions. No markdown rendering library beyond basic sanitization.

---

**Implementation steps:**

1. [REQ-506] Create ProblemCard component displaying upstar icon + count (left), title (bold), 2-line preview text (truncated), status badge (right), claimer name (small), category pill (styled), comma-separated tag badges (monospace), metadata footer (solution/comment counts, relative timestamp)
2. [REQ-506] Build SortFilterBar with sort dropdown (recent/popular/trending/oldest) and filter checkboxes (by status, category, claimer), wired to parent callbacks
3. [REQ-506] Implement Feed page fetching problems via Task 2.2 endpoint with sort/filter state, rendering card grid with infinite scroll (fetch next page on scroll-to-bottom), loading/error states
4. [REQ-510] Create ProblemDetail page loading problem by `:id` from Task 2.2 endpoint, rendering header with title, status badge, actions (upstar/claim/flag), and full markdown body
5. [REQ-510] Implement tabbed navigation (Solutions | Comments) via URL query param (`?tab=solutions`), lazy-loading Solutions and Comments sub-components on tab switch
6. [REQ-510] Add back button linking to `/problems?...` (preserve sort/filter state in state manager or sessionStorage)

**Completion criteria:**
- [ ] ProblemCard renders all fields without horizontal scroll at 1024px
- [ ] Infinite scroll triggers fetch when user scrolls within 200px of bottom
- [ ] Sort and filter changes re-fetch with debounce (300ms)
- [ ] ProblemDetail header and body visible; tabs switch without page reload
- [ ] Back button restores previous Feed sort/filter state
- [ ] Module-level comments explain infinite scroll strategy and URL query handling

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**
> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, REQ-506/510, Phase 0 contracts inlined above, implementation steps)
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries, the full spec, the full design doc, or the complete implementation docs.

---

## Task 5.4: Forms — Submit Problem, Solution, Comment, Attachments
**Description:** Multi-form submission flow: Submit Problem page with title field, markdown editor with live preview (300ms debounce), category dropdown, tag autocomplete, and anonymous checkbox. MarkdownEditor component features side-by-side editor/preview. TagAutocomplete triggers after 2 characters. AttachmentDropZone supports drag-and-drop and Ctrl+V clipboard paste. All forms include client-side validation with inline error messages.

**Spec requirements:** REQ-522, REQ-414

**Dependencies:** Task 5.1, Task 2.6

**Source files:**
- CREATE `frontend/src/pages/Submit.tsx`
- CREATE `frontend/src/components/MarkdownEditor.tsx`
- CREATE `frontend/src/components/TagAutocomplete.tsx`
- CREATE `frontend/src/components/AttachmentDropZone.tsx`

---

**Phase 0 contracts (inlined):**
MarkdownEditor component accepts `value: string` and `onChange: (text) => void`, maintains internal preview state with 300ms debounce. TagAutocomplete queries Task 2.6 GET /tags endpoint when input length ≥ 2, debounced 200ms. AttachmentDropZone accepts `onFilesSelected: (File[]) => void`, displays file preview with size, and validates file types/size. Submit form posts to Task 2.6 POST /problems with `{ title, body, category, tags, anonymous, attachments }`. No Markdown renderer library assumption — use basic HTML escaping.

---

**Implementation steps:**

1. [REQ-522] Create MarkdownEditor component with two-pane layout (editor left, preview right on desktop; stacked on mobile), textarea input, and preview pane with debounced markdown rendering
2. [REQ-414] Implement TagAutocomplete component querying Task 2.6 /tags endpoint after 2 characters, rendering dropdown with matching tags, accepting selection via click or keyboard (Enter)
3. [REQ-414] Build AttachmentDropZone with drag-and-drop detection, click-to-upload fallback, and paste (Ctrl+V) handler capturing clipboard files, displaying file list with name/size and remove button
4. [REQ-522] Create Submit page form with title input (required, max 200 chars), MarkdownEditor (required, max 5000 chars), category select (required, query Task 2.2 for list), TagAutocomplete (optional, max 10 tags), anonymous checkbox, and submit button
5. [REQ-414] Implement client-side validation: title length, body length, tag count, file size (<10MB each), showing inline error messages next to fields
6. [REQ-522] Wire form submission to Task 2.6 POST /problems endpoint, disabling submit button while loading, showing success toast and redirecting to new problem detail page, or error toast on failure

**Completion criteria:**
- [ ] MarkdownEditor preview updates within 350ms of input (300ms debounce + render)
- [ ] TagAutocomplete dropdown appears after 2 chars; empty for <2 chars
- [ ] AttachmentDropZone accepts drag-and-drop and Ctrl+V paste
- [ ] Form validation shows inline errors without submission attempt
- [ ] Submit button disabled during POST; success redirects to `/problems/:id`
- [ ] Module-level comments document debounce timing and validation rules

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**
> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, REQ-522/414, Phase 0 contracts inlined above, implementation steps)
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries, the full spec, the full design doc, or the complete implementation docs.

---

## Task 5.5: Search, Notifications, Leaderboard, Settings, AI Placeholder
**Description:** Four-page feature set: Search page with results grid matching Feed and sort/filter bar. NotificationBell component in header showing unread count dropdown and WebSocket listener. Leaderboard page with dual-track tabs (Problem Solvers / Problem Identifiers) and time filter (This Week / This Month / All Time). Settings page with notification preferences and dark mode toggle. AI Search page (/ai-search) with disabled UI elements and "Coming Soon" messaging.

**Spec requirements:** REQ-524, REQ-526

**Dependencies:** Task 5.1, Task 3.1, Task 3.4, Task 3.5

**Source files:**
- CREATE `frontend/src/pages/Search.tsx`
- CREATE `frontend/src/pages/Leaderboard.tsx`
- CREATE `frontend/src/pages/AISearch.tsx`
- CREATE `frontend/src/pages/Settings.tsx`
- CREATE `frontend/src/components/NotificationBell.tsx`

---

**Phase 0 contracts (inlined):**
Search page queries Task 3.1 GET /search endpoint on route load and search input change (debounced 300ms). NotificationBell uses WebSocket connection from Task 3.4 to listen for new notifications, storing in React state and localStorage for persistence across sessions. Leaderboard fetches Task 3.5 GET /leaderboard with `?track=solvers|identifiers&period=week|month|all` query params. Settings page posts to Task 3.4 PATCH /users/me/notification-settings. AI Search page shows disabled search input, dropdown, and button with opacity 0.5 and cursor: not-allowed, plus centered "Coming Soon" text. No real-time leaderboard updates — page refresh required.

---

**Implementation steps:**

1. [REQ-524] Create Search page with search input bar (debounced 300ms query to Task 3.1), displaying results as ProblemCard grid matching Feed layout, with sort/filter bar from Task 5.3
2. [REQ-524] Build NotificationBell component in header (icon + unread count badge), onClick opens dropdown showing recent 5 notifications (timestamp, message, link), WebSocket listener updates on new notifications, mark-as-read button
3. [REQ-526] Implement Leaderboard page with two tabs (Problem Solvers / Problem Identifiers), time filter buttons (This Week / This Month / All Time), rendering leaderboard table (rank, user avatar, name, points, problem count) from Task 3.5 endpoint
4. [REQ-526] Create Settings page with sections: notification preferences (email on new comment/solution, push notifications toggle), dark mode toggle (via useDarkMode), save button, showing success toast on save
5. [REQ-524] Build AISearch page (/ai-search) with disabled search input (placeholder "Coming Soon..."), disabled dropdown filters, disabled search button (opacity 0.5, cursor: not-allowed), centered "Coming Soon" heading and description text
6. [REQ-526] Wire Settings notification toggles to Task 3.4 PATCH /users/me/notification-settings endpoint

**Completion criteria:**
- [ ] Search results appear within 400ms of input change (debounce + fetch + render)
- [ ] NotificationBell updates on WebSocket message without page refresh
- [ ] Leaderboard renders table with correct sort order (descending points)
- [ ] Settings form saves without page reload; success toast displayed
- [ ] AI Search page elements are visually disabled with "Coming Soon" messaging
- [ ] Module-level comments document WebSocket integration and leaderboard data shape

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**
> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, REQ-524/526, Phase 0 contracts inlined above, implementation steps)
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries, the full spec, the full design doc, or the complete implementation docs.

---

## Task 5.6: Admin Pages
**Description:** Admin-only feature set: protected routes require admin role; non-admin users redirect to `/`. Five admin pages: Dashboard (overview stats), Categories management (CRUD with drag reorder and color picker), Tags management (list/rename/merge dialog), Users management (search, role toggle, activate/deactivate), and Moderation queue (flagged content, de-anonymize with confirmation dialog). AdminRouteGuard component wraps admin routes.

**Spec requirements:** REQ-476

**Dependencies:** Task 5.1, Task 4.3

**Source files:**
- CREATE `frontend/src/pages/admin/Dashboard.tsx`
- CREATE `frontend/src/pages/admin/Categories.tsx`
- CREATE `frontend/src/pages/admin/Tags.tsx`
- CREATE `frontend/src/pages/admin/Users.tsx`
- CREATE `frontend/src/pages/admin/Moderation.tsx`
- CREATE `frontend/src/components/AdminRouteGuard.tsx`

---

**Phase 0 contracts (inlined):**
AdminRouteGuard checks `user.role === 'admin'` from useAuth hook; redirects non-admin to `/` and unauthenticated to `/login`. All CRUD operations use Task 4.3 endpoints. Categories page renders list with drag-handle reorder (via react-beautiful-dnd or manual), color picker input per category, edit/delete buttons. Tags page has search/filter table with rename modal and merge dialog. Users page has search table with role dropdown and activate/deactivate toggle. Moderation page lists flagged problems/comments with de-anonymize button opening confirmation modal. No bulk operations. Optimistic updates optional.

---

**Implementation steps:**

1. [REQ-476] Create AdminRouteGuard HOC/wrapper checking `user.role === 'admin'` from useAuth; redirect non-admin to `/`, unauthenticated to `/` (or login if not authenticated)
2. [REQ-476] Implement Dashboard page displaying summary stats (total problems, solutions, comments, users, flagged items count), pulling from Task 4.3 GET /admin/dashboard endpoint
3. [REQ-476] Build Categories page fetching list from Task 4.3, rendering table with category name, color preview, order position, edit/delete buttons, drag-handle for reorder, color picker modal on edit
4. [REQ-476] Create Tags page with search/filter, table listing tags (name, problem count, solution count), rename button (inline edit or modal), merge button (modal with target tag select, POST to Task 4.3)
5. [REQ-476] Implement Users page with search input (name/email), table listing users (avatar, name, email, role dropdown, status toggle), POST/PATCH to Task 4.3 /admin/users/* endpoints on change
6. [REQ-476] Build Moderation page listing flagged problems/comments from Task 4.3 GET /admin/moderation, with flagged reason, reporter count, de-anonymize button opening confirmation ("Reveal author?"), executing PATCH on confirm

**Completion criteria:**
- [ ] Non-admin users redirected to `/` when accessing `/admin/*`
- [ ] Unauthenticated users stay on `/` (or redirect to login if configured)
- [ ] Categories drag reorder updates server on drop
- [ ] Tags rename/merge execute PATCH/POST and refresh list
- [ ] Users role toggle executes immediately; status toggle shows loading state
- [ ] Moderation de-anonymize shows confirmation and updates on confirm
- [ ] Module-level comments document admin role requirements and CRUD patterns

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**
> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, REQ-476, Phase 0 contracts inlined above, implementation steps)
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries, the full spec, the full design doc, or the complete implementation docs.

---

## Task 5.7: Error States & Empty States
**Description:** Global error/empty state UX: reusable EmptyState component (title, description, CTA button), NotFound (404) page with link to Feed, Unauthorized (401/403) page with link to login, and Toast notification system (auto-dismiss 5s, stacked). Support light and dark modes for all components.

**Spec requirements:** REQ-516, REQ-518

**Dependencies:** Task 5.1

**Source files:**
- CREATE `frontend/src/components/EmptyState.tsx`
- CREATE `frontend/src/pages/NotFound.tsx`
- CREATE `frontend/src/pages/Unauthorized.tsx`
- CREATE `frontend/src/components/Toast.tsx`

---

**Phase 0 contracts (inlined):**
EmptyState component accepts `title: string`, `description: string`, `cta?: { label: string, href: string }`. NotFound page renders with 404 heading, message, link to `/problems`. Unauthorized page renders 401 or 403 heading, message, link to `/` (or login if unauthenticated). Toast component uses React context provider (ToastProvider) exposing `useToast()` hook with `toast.show(message, type?, duration?)` method. Toasts auto-dismiss after 5000ms, stack vertically (newest at bottom), support success/error/info types. All components respect dark mode via CSS variables from Task 5.1 theme.

---

**Implementation steps:**

1. [REQ-516] Create reusable EmptyState component accepting title, description, and optional CTA props, rendering centered layout with icon (magnifying glass, inbox, etc.), text, and button
2. [REQ-516] Build NotFound page rendering 404 message, optional illustration, "Return to Feed" link, styled to match app theme
3. [REQ-516] Implement Unauthorized page rendering 401/403 message based on auth status, "Go to Home" link, styled consistently
4. [REQ-518] Create Toast component with auto-dismiss (5000ms), success/error/info styling, optional close button, positioned at bottom-right corner with 16px margin
5. [REQ-518] Implement ToastProvider context and useToast hook exposing `toast.show(message, type, duration)` function, managing toast queue (limit 3 visible)
6. [REQ-518] Add inline validation error display to form components using Toast system or inline error text next to fields
7. [REQ-516, REQ-518] Test all components in light and dark modes; verify text contrast and color contrast meet WCAG AA

**Completion criteria:**
- [ ] EmptyState component renders without props errors; CTA button optional
- [ ] NotFound page displays at `/nonexistent`; link to Feed works
- [ ] Unauthorized page displays when accessing admin routes as non-admin
- [ ] Toasts appear at bottom-right; auto-dismiss after 5s
- [ ] Multiple toasts stack vertically without overlap
- [ ] Dark mode text contrast passes WCAG AA on all error states
- [ ] Module-level comments document Toast context setup and component prop signatures

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**
> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, REQ-516/518, Phase 0 contracts inlined above, implementation steps)
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries, the full spec, the full design doc, or the complete implementation docs.

---

## Phase 6 — Hardening & Operations

I'll write the 5 task sections for Phase 6 and the 3 supporting sections as requested.

```markdown
## Task 6.1: Security — Headers, CSP, XSS, MIME, TLS
**Description:** Implement defense-in-depth security controls: TLS enforcement, HTTP security headers, Content Security Policy, XSS prevention via markdown sanitization, MIME type validation on uploads, and secure defaults in reverse proxy.
**Spec requirements:** REQ-906, REQ-908, REQ-918, REQ-924
**Dependencies:** Task 1.1, Task 2.6
**Source files:**
- CREATE `app/middleware/security.py`
- MODIFY `nginx/nginx.conf`

---
**Phase 0 contracts (inlined):**
No stubs — infrastructure task.

---
**Implementation steps:**
1. [REQ-906] Configure NGINX: enable TLS 1.2+, set ssl_protocols, ssl_ciphers (strong suites only), enforce HTTP→HTTPS redirect via 301, implement HSTS header (max-age=31536000)
2. [REQ-908] Implement security headers middleware: X-Content-Type-Options: nosniff, X-Frame-Options: DENY, Referrer-Policy: strict-origin-when-cross-origin, apply to all responses
3. [REQ-918] Implement Content Security Policy: script-src 'self', style-src 'self' 'unsafe-inline', img-src 'self' data:, font-src 'self', frame-ancestors 'none', report-uri /api/csp-report
4. [REQ-924] Implement markdown sanitization: use bleach library to strip dangerous HTML tags on storage (Problem.description, Solution.description, Comment.content), re-validate on render before sending to frontend
5. [REQ-924] Implement MIME type validation on upload: check file extension + magic bytes (python-magic), whitelist: image/png, image/jpeg, image/webp, application/pdf, reject all others with 400 + validation error

**Completion criteria:**
- [ ] NGINX TLS configured with strong ciphers and HSTS
- [ ] All security headers present in all responses
- [ ] CSP policy enforced without errors in browser console
- [ ] Markdown sanitization applied to all user content fields
- [ ] Upload MIME validation blocks non-whitelisted types
- [ ] Module-level docstring present in security.py

---
**Agent isolation contract (copy verbatim into implement-code dispatch):**
> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries, the full spec, the full design doc, or the complete implementation docs.

---

## Task 6.2: Structured Logging & Observability
**Description:** Implement structured JSON logging with request/response correlation IDs, business event tracking, and observability hooks for debugging production issues.
**Spec requirements:** REQ-912
**Dependencies:** Task 1.1
**Source files:**
- CREATE `app/middleware/logging.py`
- CREATE `app/logging.py`

---
**Phase 0 contracts (inlined):**
No stubs — infrastructure task.

---
**Implementation steps:**
1. [REQ-912] Create logging.py: configure structlog with JSON formatter, UTC timestamps, set log level from environment (DEBUG/INFO/WARN/ERROR)
2. [REQ-912] Create middleware/logging.py: generate UUID correlation_id per request (from X-Correlation-ID header or generate new), inject into contextvars for thread-local access
3. [REQ-912] Implement request/response logging: log on entry (method, path, user_id, query params) and exit (status_code, duration_ms, response_size_bytes), include correlation_id in all logs
4. [REQ-912] Create business event logger: function log_event(event_type: str, entity_type: str, entity_id: str, user_id: str, action: str, metadata: dict) for audit trail (user created, problem solved, solution accepted)
5. [REQ-912] Ensure all middleware and service layers call business event logger for user actions; output to stdout for container log aggregation

**Completion criteria:**
- [ ] structlog configured with JSON output
- [ ] All requests include unique correlation_id
- [ ] Request/response logged with all required fields
- [ ] Business event logger integrated in auth, problems, solutions flows
- [ ] Log output parseable by ELK/CloudWatch
- [ ] Module-level docstrings present

---
**Agent isolation contract (copy verbatim into implement-code dispatch):**
> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries, the full spec, the full design doc, or the complete implementation docs.

---

## Task 6.3: Rate Limiting
**Description:** Implement multi-layer rate limiting to prevent abuse: NGINX-level global limits, per-endpoint throttling, and per-user magic link brute-force protection.
**Spec requirements:** REQ-910, REQ-128
**Dependencies:** Task 1.1
**Source files:**
- MODIFY `nginx/nginx.conf`
- CREATE `app/middleware/rate_limit.py`

---
**Phase 0 contracts (inlined):**
No stubs — infrastructure task.

---
**Implementation steps:**
1. [REQ-910] Configure NGINX: define limit_req_zone (30 requests per second per IP on /api/*, 5 req/s on /api/auth/*, 1 req/s on /api/auth/magic-link), use nodelay burst 10
2. [REQ-910] Return HTTP 429 Too Many Requests with Retry-After header (seconds until next slot available), include rate limit status in response headers (X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset)
3. [REQ-128] Implement per-email rate limit in middleware/rate_limit.py for magic link endpoint: 5 requests per 10 minutes per email, use Redis for distributed rate limit state, return 429 if exceeded
4. [REQ-128] Store magic link attempt metadata (email, IP, timestamp) in Redis for debugging; allow admin to reset rate limit per email via admin endpoint

**Completion criteria:**
- [ ] NGINX rate limiting active on all /api/ routes
- [ ] Global 30 req/s and auth 5 req/s enforced
- [ ] 429 responses include Retry-After header
- [ ] Per-email magic link limit (5 per 10 min) enforced
- [ ] Rate limit state persists across pod restarts (Redis)
- [ ] Module-level docstring present in rate_limit.py

---
**Agent isolation contract (copy verbatim into implement-code dispatch):**
> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries, the full spec, the full design doc, or the complete implementation docs.

---

## Task 6.4: Backup, Deployment & Health Check
**Description:** Implement database backup/restore automation, systemd unit generation for container orchestration, and health check endpoint for readiness probes.
**Spec requirements:** REQ-914, REQ-922, REQ-928
**Dependencies:** Task 1.1, Task 1.2
**Source files:**
- CREATE `scripts/backup.sh`
- CREATE `scripts/restore.sh`
- CREATE `app/routes/health.py`
- CREATE `scripts/generate-systemd.sh`

---
**Phase 0 contracts (inlined):**
No stubs — infrastructure task.

---
**Implementation steps:**
1. [REQ-914] Write backup.sh: pg_dump database to timestamped .sql.gz file, rsync to remote S3 bucket (or NFS mount), retain 7 daily + 4 weekly backups, run via cron daily at 02:00 UTC
2. [REQ-914] Write restore.sh: accept backup file path, restore via psql, verify row counts post-restore, exit with status code (0 = success, 1 = failure)
3. [REQ-922] Generate systemd units via podman generate systemd: create app.service and postgres.service in /etc/systemd/system/, enable auto-restart (Restart=always, StartLimitInterval=600s), socket activation for port 8000
4. [REQ-928] Implement /healthz endpoint in health.py: return 200 + {status: "ok"} on healthy (all checks pass), return 503 + {status: "degraded", checks: {...}} if any check fails, checks include: db connection, redis connection (if used), file storage writable

**Completion criteria:**
- [ ] backup.sh produces pg_dump with 7 daily + 4 weekly retention
- [ ] restore.sh successfully restores and verifies
- [ ] Systemd units generate without errors and start app + postgres
- [ ] /healthz endpoint returns 200 when healthy
- [ ] /healthz returns 503 when database unreachable
- [ ] Health check timeout < 2s (for k8s readiness probes)
- [ ] Module-level docstring present in health.py

---
**Agent isolation contract (copy verbatim into implement-code dispatch):**
> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries, the full spec, the full design doc, or the complete implementation docs.

---

## Task 6.5: Performance Validation & Test Coverage
**Description:** Establish comprehensive test infrastructure with pytest fixtures, factory-based test data generation, integration tests, load testing, and coverage targets to validate system meets latency and reliability requirements.
**Spec requirements:** REQ-900, REQ-902, REQ-904, REQ-926
**Dependencies:** All previous tasks
**Source files:**
- CREATE `tests/conftest.py`
- CREATE `tests/factories.py`
- CREATE `tests/load/locustfile.py`
- CREATE `pytest.ini`

---
**Phase 0 contracts (inlined):**
No stubs — infrastructure task.

---
**Implementation steps:**
1. [REQ-900] Create pytest.ini: configure pytest for async tests (asyncio mode), set testpaths to tests/, markers for unit/integration/load, coverage options (source=app, fail_under=80)
2. [REQ-900] Create conftest.py: implement fixtures for test database (separate from prod, auto-rollback after test), async event loop fixture, authenticated user fixture, mock Redis fixture (if applicable)
3. [REQ-902] Create factories.py using factory_boy: UserFactory, ProblemFactory, SolutionFactory, CommentFactory with faker-generated data; support relationships and state (user.solved_count = 5)
4. [REQ-902,REQ-904] Write integration tests for all routes: test_create_problem, test_vote_solution, test_get_feed, test_search_problems, test_rate_limit_magic_link, etc.; verify request/response contracts, status codes, and business logic
5. [REQ-926] Create locustfile.py for load testing: simulate user journey (login → browse feed → view problem → upvote solution), target p95 < 200ms and p99 < 500ms, measure throughput at 50/100/200 concurrent users

**Completion criteria:**
- [ ] pytest configured for async + rollback
- [ ] All route endpoints have integration tests
- [ ] Coverage >= 80% across app/ module
- [ ] Factories support relationship creation
- [ ] Load test passes p95/p99 latency targets
- [ ] Tests runnable in CI/CD pipeline
- [ ] Module-level docstrings present

---
**Agent isolation contract (copy verbatim into implement-code dispatch):**
> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries, the full spec, the full design doc, or the complete implementation docs.

---

---

## Module Boundary Map

| Task | Source File | Action | Purpose |
|------|-------------|--------|---------|
| 1.1 | pyproject.toml | CREATE | Project metadata, dependencies, build config |
| 1.1 | podman-compose.yml | CREATE | Container orchestration (app, postgres, redis, nginx) |
| 1.1 | .env.example | CREATE | Environment variable template |
| 1.1 | app/__init__.py | CREATE | Package init, FastAPI app factory |
| 1.1 | app/config.py | CREATE | Pydantic config from environment |
| 1.2 | app/models/user.py | CREATE | User model, auth identity, profile |
| 1.2 | app/models/problem.py | CREATE | Problem entity, description, tags, category |
| 1.2 | app/models/solution.py | CREATE | Solution entity, acceptance, vote count |
| 1.2 | app/models/comment.py | CREATE | Comment entity, nesting, moderation |
| 1.2 | app/models/attachment.py | CREATE | Attachment entity, file metadata |
| 1.2 | app/models/notification.py | CREATE | Notification entity, delivery status |
| 1.2 | app/models/watch.py | CREATE | Watch entity, user subscriptions |
| 1.2 | app/database.py | CREATE | SQLAlchemy engine, session factory |
| 1.2 | alembic/ | CREATE | Migration tool, initial schema |
| 1.3 | app/auth/oidc.py | CREATE | OIDC provider integration |
| 1.3 | app/auth/magic_link.py | CREATE | Magic link generation, validation |
| 1.3 | app/auth/jwt.py | CREATE | JWT token creation, verification |
| 1.3 | app/auth/dependencies.py | CREATE | FastAPI Depends for auth |
| 1.3 | app/routes/auth.py | CREATE | Auth endpoints (login, magic-link, callback) |
| 2.1 | app/services/problems.py | CREATE | Problem CRUD, listing, search interface |
| 2.1 | app/routes/problems.py | CREATE | Problem endpoints (GET, POST, PUT, DELETE) |
| 2.2 | app/services/feed.py | CREATE | Feed algorithm, ranking, pagination |
| 2.2 | app/routes/problems.py | MODIFY | Add /feed endpoint |
| 2.3 | app/services/solutions.py | CREATE | Solution CRUD, acceptance logic |
| 2.3 | app/routes/solutions.py | CREATE | Solution endpoints (GET, POST, PUT, DELETE) |
| 2.4 | app/services/voting.py | CREATE | Vote tracking, count updates |
| 2.4 | app/routes/voting.py | CREATE | Voting endpoints (/problems/{id}/vote, /solutions/{id}/vote) |
| 2.5 | app/services/comments.py | CREATE | Comment CRUD, nesting, moderation |
| 2.5 | app/routes/comments.py | CREATE | Comment endpoints (GET, POST, PUT, DELETE) |
| 2.6 | app/services/attachments.py | CREATE | File upload, storage, validation |
| 2.6 | app/routes/attachments.py | CREATE | Attachment endpoints (POST, GET, DELETE) |
| 2.6 | nginx/nginx.conf | MODIFY | Add /uploads static file serving |
| 3.1 | app/services/search.py | CREATE | Full-text search, filter + rank |
| 3.1 | app/routes/search.py | CREATE | Search endpoints (/search?q=, /search/ai) |
| 3.2 | app/routes/meta.py | CREATE | Meta endpoints (stats, categories, tags) |
| 3.2 | nginx/nginx.conf | MODIFY | Cache /meta endpoints (30s) |
| 3.3 | app/services/watches.py | CREATE | Watch CRUD, subscription logic |
| 3.3 | app/services/notifications.py | CREATE | Notification creation, state tracking |
| 3.3 | app/routes/watches.py | CREATE | Watch endpoints (POST, DELETE) |
| 3.4 | app/services/delivery.py | CREATE | Email/push notification dispatch |
| 3.4 | app/routes/notifications.py | CREATE | Notification endpoints (GET, PATCH, DELETE) |
| 3.4 | app/routes/ws.py | CREATE | WebSocket endpoint for real-time updates |
| 3.5 | app/services/leaderboard.py | CREATE | Ranking, aggregation, caching |
| 3.5 | app/routes/leaderboard.py | CREATE | Leaderboard endpoints (GET /leaderboard) |
| 4.1 | app/services/categories.py | CREATE | Category CRUD, constraints |
| 4.1 | app/routes/admin/categories.py | CREATE | Admin category endpoints |
| 4.2 | app/services/tags.py | CREATE | Tag CRUD, cleanup, frequency |
| 4.2 | app/routes/admin/tags.py | CREATE | Admin tag endpoints |
| 4.3 | app/services/admin.py | CREATE | Moderation, user management, config |
| 4.3 | app/routes/admin/users.py | CREATE | Admin user endpoints (suspend, delete) |
| 4.3 | app/routes/admin/moderation.py | CREATE | Moderation endpoints (flag, review, action) |
| 4.3 | app/routes/admin/config.py | CREATE | Config management endpoints |
| 5.1 | frontend/src/App.tsx | CREATE | Root component, routing, layout |
| 5.1 | frontend/src/theme/ | CREATE | Tailwind config, color tokens |
| 5.1 | frontend/src/layouts/ | CREATE | Base layout component (header, sidebar) |
| 5.2 | frontend/src/pages/Landing.tsx | CREATE | Landing page, hero, CTA |
| 5.2 | frontend/src/hooks/useAuth.ts | CREATE | Auth state, token refresh, OIDC logic |
| 5.3 | frontend/src/pages/Feed.tsx | CREATE | Feed page with infinite scroll |
| 5.3 | frontend/src/pages/ProblemDetail.tsx | CREATE | Problem detail + solutions view |
| 5.3 | frontend/src/components/ProblemCard.tsx | CREATE | Problem card (compact) |
| 5.4 | frontend/src/pages/Submit.tsx | CREATE | Submit problem form page |
| 5.4 | frontend/src/components/MarkdownEditor.tsx | CREATE | Markdown editor with preview |
| 5.5 | frontend/src/pages/Search.tsx | CREATE | Search results page |
| 5.5 | frontend/src/pages/Leaderboard.tsx | CREATE | Leaderboard page |
| 5.5 | frontend/src/pages/AISearch.tsx | CREATE | AI-powered search page |
| 5.5 | frontend/src/pages/Settings.tsx | CREATE | User settings page |
| 5.5 | frontend/src/components/NotificationBell.tsx | CREATE | Real-time notification indicator |
| 5.6 | frontend/src/pages/admin/*.tsx | CREATE | Admin dashboard pages (users, moderation, config) |
| 5.7 | frontend/src/components/EmptyState.tsx | CREATE | Empty state UI |
| 5.7 | frontend/src/pages/NotFound.tsx | CREATE | 404 page |
| 5.7 | frontend/src/pages/Unauthorized.tsx | CREATE | 401 page |
| 5.7 | frontend/src/components/Toast.tsx | CREATE | Toast notification component |
| 6.1 | app/middleware/security.py | CREATE | Security headers, CSP, XSS prevention |
| 6.1 | nginx/nginx.conf | MODIFY | TLS 1.2+, HSTS, redirect HTTP→HTTPS |
| 6.2 | app/middleware/logging.py | CREATE | Request correlation, structured logging |
| 6.2 | app/logging.py | CREATE | structlog configuration |
| 6.3 | nginx/nginx.conf | MODIFY | Rate limiting zones and limits |
| 6.3 | app/middleware/rate_limit.py | CREATE | Per-email magic link throttling |
| 6.4 | scripts/backup.sh | CREATE | PostgreSQL backup automation |
| 6.4 | scripts/restore.sh | CREATE | PostgreSQL restore script |
| 6.4 | app/routes/health.py | CREATE | Health check endpoint |
| 6.4 | scripts/generate-systemd.sh | CREATE | Systemd unit generation |
| 6.5 | tests/conftest.py | CREATE | pytest fixtures, test DB |
| 6.5 | tests/factories.py | CREATE | factory_boy factories |
| 6.5 | tests/load/locustfile.py | CREATE | Load testing scenarios |
| 6.5 | pytest.ini | CREATE | pytest configuration |

---

## Dependency Graph

```
1.1 (Setup)
├── 1.2 (Schema)
│   ├── 1.3 (Auth)
│   │   ├── 2.1 (Problems)
│   │   │   ├── 2.2 (Feed) ───────┐
│   │   │   ├── 2.3 (Solutions) ──┤
│   │   │   │   ├── 2.4 (Voting) ─┤
│   │   │   │   └── 2.5 (Comments) ┤
│   │   │   │                       ├── 3.1 (Search) ─────┐
│   │   │   ├── 2.6 (Attachments) ────────────────────────┤
│   │   │   └── 3.2 (Meta)                                 ├── 5.5 (Rich UI)
│   │   │                                                  ├── 6.5 (Tests)
│   │   └── 4.3 (Admin)                                    │
│   │                                                      │
│   └── 4.1 (Categories)                                   │
│                                                          │
├── 2.6 (Attachments) ───────────────────────────────────┤
│                                                          │
├── 3.3 (Watches) ────┐                                   │
│                     └── 3.4 (Delivery) ──────────────────┤
├── 3.5 (Leaderboard) ──────────────────────────────────┘
│
├── 5.1 (Frontend Setup)
│   ├── 5.2 (Auth UI) ──────┐
│   ├── 5.3 (Feed UI) ───────┤
│   ├── 5.4 (Submit UI) ─────┤
│   ├── 5.5 (Rich UI) ◄──────┤
│   ├── 5.6 (Admin UI) ◄─────┤
│   └── 5.7 (Errors/Toasts)  │
│                            │
├── 6.1 (Security) ──────────┤
├── 6.2 (Logging) ───────────┤
├── 6.3 (Rate Limiting) ─────┤
└── 6.4 (Backup/Health) ─────┴────────────────► 6.5 (Tests)

Legend: → = depends on,  ◄ = receives data from,  ┌─┴─┐ = fan-in

Critical path: 1.1 → 1.2 → 1.3 → 2.1 → 2.3 → 3.3 → 3.4 → 5.5 → 6.5
```

---

## Traceability Table

| REQ ID | Priority | Task | Domain |
|--------|----------|------|--------|
| REQ-100 | MUST | 1.3 | Auth |
| REQ-102 | MUST | 1.3 | Auth |
| REQ-104 | MUST | 1.3 | Auth |
| REQ-106 | MUST | 1.3 | Auth |
| REQ-108 | MUST | 1.3 | Auth |
| REQ-110 | MUST | 1.3 | Auth |
| REQ-112 | MUST | 1.3 | Auth |
| REQ-114 | MUST | 1.3 | Auth |
| REQ-116 | MUST | 1.3 | Auth |
| REQ-118 | MUST | 1.3 | Auth |
| REQ-120 | MUST | 1.3 | Auth |
| REQ-122 | MUST | 1.3 | Auth |
| REQ-124 | MUST | 1.3 | Auth |
| REQ-126 | SHOULD | 1.3 | Auth |
| REQ-128 | SHOULD | 1.3 | Auth |
| REQ-128 | SHOULD | 6.3 | Rate Limiting |
| REQ-150 | MUST | 2.1 | Problems |
| REQ-152 | MUST | 2.1 | Problems |
| REQ-154 | MUST | 2.1 | Problems |
| REQ-156 | MUST | 2.1 | Problems |
| REQ-158 | MUST | 2.1 | Problems |
| REQ-160 | MUST | 2.1 | Problems |
| REQ-162 | MUST | 2.1 | Problems |
| REQ-164 | MUST | 2.1 | Problems |
| REQ-166 | MUST | 2.1 | Problems |
| REQ-168 | MUST | 2.2 | Feed |
| REQ-170 | MUST | 2.2 | Feed |
| REQ-172 | MUST | 2.2 | Feed |
| REQ-174 | MUST | 2.2 | Feed |
| REQ-176 | SHOULD | 2.2 | Feed |
| REQ-178 | SHOULD | 2.2 | Feed |
| REQ-180 | SHOULD | 2.2 | Feed |
| REQ-182 | MAY | 2.2 | Feed |
| REQ-200 | MUST | 2.3 | Solutions |
| REQ-202 | MUST | 2.3 | Solutions |
| REQ-204 | MUST | 2.3 | Solutions |
| REQ-206 | MUST | 2.3 | Solutions |
| REQ-208 | MUST | 2.3 | Solutions |
| REQ-210 | MUST | 2.3 | Solutions |
| REQ-212 | MUST | 2.3 | Solutions |
| REQ-216 | MUST | 2.3 | Solutions |
| REQ-218 | MUST | 2.3 | Solutions |
| REQ-214 | SHOULD | 2.3 | Solutions |
| REQ-220 | SHOULD | 2.3 | Solutions |
| REQ-250 | MUST | 2.4 | Voting |
| REQ-252 | MUST | 2.4 | Voting |
| REQ-254 | MUST | 2.4 | Voting |
| REQ-256 | MUST | 2.4 | Voting |
| REQ-258 | MUST | 2.5 | Comments |
| REQ-260 | MUST | 2.5 | Comments |
| REQ-262 | MUST | 2.5 | Comments |
| REQ-264 | MUST | 2.5 | Comments |
| REQ-266 | MUST | 2.5 | Comments |
| REQ-268 | SHOULD | 3.5 | Leaderboard |
| REQ-270 | MUST | 2.4 | Voting |
| REQ-300 | MUST | 3.3 | Watches |
| REQ-302 | MUST | 3.3 | Watches |
| REQ-304 | MUST | 3.3 | Watches |
| REQ-308 | MUST | 3.3 | Watches |
| REQ-310 | MUST | 3.3 | Watches |
| REQ-312 | MUST | 3.3 | Watches |
| REQ-306 | SHOULD | 3.3 | Watches |
| REQ-314 | MUST | 3.4 | Delivery |
| REQ-316 | MUST | 3.4 | Delivery |
| REQ-318 | SHOULD | 3.4 | Delivery |
| REQ-320 | SHOULD | 3.4 | Delivery |
| REQ-322 | SHOULD | 3.4 | Delivery |
| REQ-324 | MUST | 3.3 | Watches |
| REQ-350 | MUST | 3.1 | Search |
| REQ-352 | MUST | 3.1 | Search |
| REQ-354 | MUST | 3.1 | Search |
| REQ-356 | MUST | 3.1 | Search |
| REQ-360 | MUST | 3.1 | Search |
| REQ-362 | MUST | 3.1 | Search |
| REQ-358 | SHOULD | 3.1 | Search |
| REQ-364 | SHOULD | 3.1 | Search |
| REQ-366 | SHOULD | 3.2 | Link Previews |
| REQ-368 | SHOULD | 3.2 | Link Previews |
| REQ-400 | MUST | 2.6 | Attachments |
| REQ-402 | MUST | 2.6 | Attachments |
| REQ-404 | MUST | 2.6 | Attachments |
| REQ-406 | MUST | 2.6 | Attachments |
| REQ-408 | MUST | 2.6 | Attachments |
| REQ-410 | MUST | 2.6 | Attachments |
| REQ-412 | MUST | 2.6 | Attachments |
| REQ-416 | MUST | 2.6 | Attachments |
| REQ-414 | SHOULD | 2.6 | Attachments |
| REQ-414 | SHOULD | 5.4 | Forms |
| REQ-450 | MUST | 4.3 | User Mgmt |
| REQ-452 | MUST | 4.1 | Categories |
| REQ-454 | MUST | 4.1 | Categories |
| REQ-456 | MUST | 4.1 | Categories |
| REQ-458 | MUST | 4.1 | Categories |
| REQ-454 | MUST | 1.2 | Schema |
| REQ-460 | MUST | 4.2 | Tags |
| REQ-462 | MUST | 4.2 | Tags |
| REQ-464 | MUST | 4.2 | Tags |
| REQ-466 | MUST | 4.3 | User Mgmt |
| REQ-468 | MUST | 4.3 | User Mgmt |
| REQ-470 | MUST | 4.3 | User Mgmt |
| REQ-472 | MUST | 4.3 | User Mgmt |
| REQ-474 | SHOULD | 4.3 | User Mgmt |
| REQ-476 | SHOULD | 4.3 | User Mgmt |
| REQ-476 | SHOULD | 5.6 | Admin Pages |
| REQ-500 | MUST | 5.1 | App Shell |
| REQ-504 | MUST | 5.1 | App Shell |
| REQ-508 | MUST | 5.1 | App Shell |
| REQ-512 | MUST | 5.1 | App Shell |
| REQ-514 | MUST | 5.1 | App Shell |
| REQ-520 | MUST | 5.1 | App Shell |
| REQ-502 | MUST | 5.2 | Landing |
| REQ-506 | MUST | 5.3 | Feed/Detail |
| REQ-510 | MUST | 5.3 | Feed/Detail |
| REQ-522 | SHOULD | 5.4 | Forms |
| REQ-524 | SHOULD | 5.5 | Search/Leaderboard UI |
| REQ-526 | SHOULD | 5.5 | Search/Leaderboard UI |
| REQ-516 | MUST | 5.7 | Error States |
| REQ-518 | MUST | 5.7 | Error States |
| REQ-900 | MUST | 6.5 | Performance/Testing |
| REQ-902 | MUST | 6.5 | Performance/Testing |
| REQ-904 | MUST | 6.5 | Performance/Testing |
| REQ-926 | SHOULD | 6.5 | Performance/Testing |
| REQ-906 | MUST | 6.1 | Security |
| REQ-908 | MUST | 6.1 | Security |
| REQ-918 | MUST | 6.1 | Security |
| REQ-924 | MUST | 6.1 | Security |
| REQ-910 | MUST | 6.3 | Rate Limiting |
| REQ-912 | MUST | 6.2 | Logging |
| REQ-914 | MUST | 6.4 | Backup/Deploy |
| REQ-922 | MUST | 6.4 | Backup/Deploy |
| REQ-928 | MAY | 6.4 | Backup/Deploy |
| REQ-916 | MUST | 1.1 | Scaffolding |
| REQ-920 | MUST | 1.2 | Schema |

