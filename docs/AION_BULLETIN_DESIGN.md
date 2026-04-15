# Aion Bulletin — Design Document

| Field | Value |
|-------|-------|
| **Document** | Aion Bulletin Design Document |
| **Version** | 0.1 |
| **Status** | Draft |
| **Spec Reference** | `docs/AION_BULLETIN_SPEC.md` (REQ-100–REQ-928) |
| **Companion Documents** | `docs/AION_BULLETIN_SPEC.md`, `docs/AION_BULLETIN_SPEC_SUMMARY.md`, `docs/DESIGN_REF.md` |
| **Output Path** | `docs/AION_BULLETIN_DESIGN.md` |
| **Produced by** | write-design-docs |
| **Task Decomposition Status** | [x] Approved |

> **Document Intent.** This document provides a technical design with task decomposition
> and contract-grade code appendix for the Aion Bulletin problem board specified in
> `docs/AION_BULLETIN_SPEC.md`. Every task references the requirements it satisfies.
> Part B contract entries are consumed verbatim by the companion implementation docs.

---

# Part A: Task-Oriented Overview

## Phase 1 — Foundation

### Task 1.1: Project Scaffolding & Environment Configuration

**Description:** Initialize a production-ready FastAPI project with Pydantic v2 settings, Podman Compose orchestration for three services (nginx, api, postgres), and comprehensive environment variable configuration. This task establishes the foundational project structure, dependency management via pyproject.toml, and development/production environment separation using .env files with Pydantic-based validation.

**Requirements Covered:** REQ-916, REQ-922

**Dependencies:** None

**Complexity:** M

**Subtasks:**
1. Create pyproject.toml with FastAPI, Pydantic v2, SQLAlchemy 2.0, asyncpg, structlog, and dev dependencies (pytest, ruff, mypy)
2. Implement Pydantic Settings class in app/config.py with environment variable parsing and validation (database URL, Azure AD config, JWT secret, SMTP settings, storage paths)
3. Create podman-compose.yml defining nginx, api, and postgres services with volume mounts, environment passing, and health checks
4. Generate .env.example with all required variables (database credentials, JWT secret template, Azure AD client ID/secret/tenant, SMTP config, API base URL)
5. Initialize app/__init__.py with version and core package exports
6. Configure podman generate systemd integration for auto-restart and dependency ordering

**Risks:**
- Secret leakage: mitigation via strict .env.example (no real secrets) and .gitignore enforcement
- Cross-service networking: mitigation via explicit service names and internal DNS in podman-compose

**Testing Strategy:** Spin up full stack via podman-compose, verify all services reach healthy state within 10s, validate config loading with missing/invalid env vars

---

### Task 1.2: Database Schema & Alembic Migrations

**Description:** Define complete SQLAlchemy 2.0 models for users, problems, solutions, comments, voting, attachments, and operational tables (notifications, watches, claims, edit history, idempotency records). Implement Alembic schema versioning with automatic migration on startup and seed script to provision 10 default problem categories. All models use async-compatible session factories and advanced PostgreSQL features (JSONB, tsvector with GIN indexing, unique constraints for voting integrity).

**Requirements Covered:** REQ-920, REQ-454

**Dependencies:** Task 1.1

**Complexity:** L

**Subtasks:**
1. Define SQLAlchemy 2.0 models (users, categories, tags, problems, problem_tags, problem_upstars, solutions, solution_versions, solution_upvotes, comments, claims, attachments, notifications, watches, edit_history, idempotency_records) with relationships and constraints
2. Add JSONB column for users.notification_prefs and tsvector with GIN index on problems (title, description) for full-text search
3. Implement UNIQUE constraints on problem_upstars(problem_id, user_id) and solution_upvotes(solution_id, user_id) to prevent duplicate voting
4. Create app/database.py with async session factory (AsyncSession), engine initialization, and session scoping for request context
5. Initialize Alembic migrations directory and auto-generate initial migration from models; create migration hook in app startup
6. Write seed script to insert 10 default categories (RTL Design, Verification, Physical Design, DFT, EDA Tools, Methodology, IT/Infra, Scripts/Automation, Documentation, Other) on first run via migration context

**Risks:**
- Migration lock contention under high concurrency: mitigation via explicit lock timeout and advisory lock cleanup
- Tsvector indexing overhead on large tables: mitigation via async index creation during off-hours migration window
- Data loss during schema refactoring: mitigation via dry-run migrations and backup restore procedure

**Testing Strategy:** Generate migrations from clean models, verify Alembic version tracking, test downgrade/upgrade cycle, confirm seed categories exist post-migration

---

### Task 1.3: Authentication — Azure AD, Magic Link, JWT, Roles

**Description:** Implement multi-mode authentication via Azure AD OIDC (single-tenant), magic links with signed JWT tokens, and HttpOnly Secure SameSite=Strict JWT cookies. Auto-provision users on first login with User role; support manual Admin promotion. Enforce fine-grained permission rules (solution acceptance, problem/comment deletion) based on user roles and authorship. Include dev bypass for local testing and audit logging for auth events.

**Requirements Covered:** REQ-100, REQ-102, REQ-104, REQ-106, REQ-108, REQ-110, REQ-112, REQ-114, REQ-116, REQ-118, REQ-120, REQ-122, REQ-124, REQ-126, REQ-128

**Dependencies:** Task 1.2

**Complexity:** L

**Subtasks:**
1. Configure authlib with Azure AD OIDC provider, implement POST /api/auth/login (redirect to Azure AD), GET /api/auth/callback (token exchange, tenant verification via tid claim)
2. Implement magic link flow: POST /api/auth/magic-link (generate signed JWT URL, send via SMTP with 15-min expiry), GET /api/auth/magic-link/verify (validate signature, one-time use via cache)
3. Create JWT cookie handler (access 15m, refresh 7d; HttpOnly, Secure, SameSite=Strict), implement POST /api/auth/refresh for token rotation
4. Build user auto-provisioning on first login: create user record with email, name, role=User; propagate to database
5. Implement role and permission dependency system: User default role, Admin manual promotion only; enforce rules for solution acceptance (poster/admin), problem edit/delete (poster/admin), comment deletion (author/admin)
6. Add dev auth bypass (DEV_AUTH_BYPASS=true skips auth, returns 404 in prod); implement GET /api/auth/me; add POST /api/auth/logout with cookie clearing
7. Create auth event audit log (login attempt, magic link request, token refresh); implement 5 req/email/10 min rate limit on magic link

**Risks:**
- OIDC token leak via HTTP: mitigation via Secure/SameSite cookie flags and strict HTTPS enforcement in prod
- Magic link reuse: mitigation via single-use cache expiry and signed token validation
- Privilege escalation via role tampering: mitigation via server-side role storage in user table, never client-controlled

**Testing Strategy:** Test Azure AD callback with valid/invalid tenants, verify magic link URL signing and expiry, confirm JWT rotation, validate permission rules (attempt unauthorized solution acceptance), test dev bypass disabled in prod mode

---

## Phase 2 — Core Domain

### Task 2.1: Problem CRUD, Status FSM, Claiming, Pinning, Edit History, Duplicates

**Description:** Implement complete problem lifecycle management including CRUD operations, status state machine (Open→Claimed→Solved→Accepted, with Duplicate branch), claiming system with auto-expiry after 14 days, duplicate workflow (suggest → confirm), pinning (up to 3 per admin), and immutable edit history. Support anonymous posting with admin visibility, comprehensive validation, and idempotent status transitions with 409 conflict responses.

**Requirements Covered:** REQ-150, REQ-152, REQ-154, REQ-156, REQ-158, REQ-160, REQ-162, REQ-164, REQ-166

**Dependencies:** Task 1.3

**Complexity:** L

**Subtasks:**
1. Create POST /api/problems endpoint with validation (title 5-200 chars, description ≥10 chars, valid category ID, optional tags); support is_anonymous flag; return 422 on validation failure
2. Implement problem status FSM in service layer: Open (initial), Claimed, Solved, Accepted, Duplicate; enforce state transitions; return 409 on forbidden transitions
3. Build claiming system: multiple claimers with first-claimer as primary, idempotent toggle (POST /api/problems/{id}/claim), atomic update of primary claimer on claim/unclaim
4. Create scheduled job for 14-day claim auto-expiry; revert status to Open atomically if all claims removed
5. Implement two-step duplicate workflow: any user suggests duplicate, poster/admin confirms; confirmed problems excluded from feed
6. Add admin pinning endpoint (POST /api/problems/{id}/pin, max 3), return 409 on 4th pin
7. Create edit history system: every edit creates immutable record; display "(edited N ago)" on detail

**Risks:**
- Race condition on claim expiry and status revert: mitigation via SELECT FOR UPDATE and transactional guarantee
- FSM state corruption: mitigation via explicit state validation on every transition

**Testing Strategy:** Test all FSM transitions (valid/invalid), verify claim expiry reverts status to Open, confirm duplicate workflow blocks duplicates from feed, test pin limit enforcement, validate edit history immutability

---

### Task 2.2: Feed — Cursor Pagination, Sort, Filter

**Description:** Build paginated problem feed with cursor-based navigation (default 25, max 100), four sort modes (top/upstars, new, active, discussed), and combinable filters (status, category, mine, unclaimed). Pinned problems appear above first page without consuming pagination slots. Support idempotency keys for POST operations and activity timestamp tracking.

**Requirements Covered:** REQ-168, REQ-170, REQ-172, REQ-174, REQ-176, REQ-178, REQ-180, REQ-182

**Dependencies:** Task 2.1

**Complexity:** M

**Subtasks:**
1. Implement cursor-based pagination query builder: encode/decode (sort_key, id) as base64 cursor, fetch limit+1 to detect last page, return next_cursor (null on last page)
2. Add four sort modes: top (upstars DESC), new (created_at DESC, default), active (activity_at DESC), discussed (comment_count DESC)
3. Build composable filters: status, category ID, mine, unclaimed; apply AND logic; exclude duplicates by default
4. Implement pinned-above logic: fetch up to 3 pinned problems unconditionally, append paginated results
5. Add Idempotency-Key header support: cache POST results for 24h, return cached response on duplicate
6. Implement activity_at timestamp updates on claim, comment, upstar, status change, and edit events

**Risks:**
- Cursor deserialization attacks: mitigation via HMAC-signed cursor tokens
- Pagination offset drift with real-time inserts: mitigation via keyset pagination

**Testing Strategy:** Paginate through 150+ problems across sort modes, verify pinned problems appear first, test filter combinations, confirm cursor handles deletions/inserts

---

### Task 2.3: Solutions — CRUD, Versioning, Acceptance

**Description:** Implement multi-solution architecture per problem with immutable versioning (POST creates new version, no direct edits), acceptance workflow (single accepted per problem, atomic swap), and comprehensive sorting. Solutions are first-class entities with author, description, optional git links, anonymous posting, and upvote tracking.

**Requirements Covered:** REQ-200, REQ-202, REQ-204, REQ-206, REQ-208, REQ-210, REQ-212, REQ-214, REQ-216, REQ-218, REQ-220

**Dependencies:** Task 2.1

**Complexity:** M

**Subtasks:**
1. Create POST /api/solutions endpoint; GET /api/problems/{id}/solutions returns all solutions with default sort (accepted first, then upvotes DESC, then created_at DESC)
2. Implement immutable versioning: POST /api/solutions/{id}/versions creates new version (UNIQUE constraint), PATCH/PUT return 405; GET versions returns ascending history
3. Build solution acceptance workflow: POST /api/solutions/{id}/accept (poster/admin only) atomically transitions previous accepted→proposed
4. Add solution upvote endpoint (POST /api/solutions/{id}/upvote, idempotent toggle)
5. Implement "newest first" sort toggle
6. Support anonymous solutions with identity hiding from non-admins

**Risks:**
- Lost acceptance during concurrent updates: mitigation via SELECT FOR UPDATE on solution row during acceptance transaction

**Testing Strategy:** Create multiple solutions per problem, verify version history ordering, test acceptance swap, confirm upvote toggle idempotency, validate anonymous masking

---

### Task 2.4: Voting — Upstars + Solution Upvotes

**Description:** Implement dual voting axes: upstars on problems and upvotes on solutions. Both use idempotent toggle semantics (second call removes vote). Enforce UNIQUE constraints to prevent duplicate votes and exclude anonymous contributions from leaderboard aggregations.

**Requirements Covered:** REQ-250, REQ-252, REQ-254, REQ-256, REQ-270

**Dependencies:** Task 2.1, Task 2.3

**Complexity:** S

**Subtasks:**
1. Create POST /api/problems/{id}/upstar endpoint with idempotent toggle; enforce UNIQUE(problem_id, user_id)
2. Create POST /api/solutions/{id}/upvote endpoint with idempotent toggle; enforce UNIQUE(solution_id, user_id)
3. Implement atomic vote count tracking on parent tables
4. Filter anonymous votes from leaderboard queries
5. Return (is_active, new_count) from both toggle endpoints

**Testing Strategy:** Toggle upstar twice (adds then removes), verify UNIQUE constraint, confirm vote counts update atomically, validate anonymous exclusion from leaderboard

---

### Task 2.5: Comments — Threaded, Anonymous, Markdown, Edit/Delete

**Description:** Build threaded comment system on problems and solutions with optional anonymity, markdown rendering with HTML sanitization, and granular edit/delete permissions. Support tombstone deletion for comments with replies and immutable edit history for admins.

**Requirements Covered:** REQ-258, REQ-260, REQ-262, REQ-264, REQ-266

**Dependencies:** Task 2.1, Task 2.3

**Complexity:** M

**Subtasks:**
1. Create comment model with parent_type, parent_id, parent_comment_id for threading, author_id, body, is_anonymous
2. Implement POST /api/comments; GET returns structured tree
3. Build anonymous comment masking for non-admin users
4. Implement deletion: tombstone if has replies, remove entirely if leaf
5. Add comment editing with edit_history record; display "(edited)" indicator
6. Add markdown rendering with HTML sanitization (bleach allowlist)

**Risks:**
- Comment tree traversal explosion on deep nesting: mitigation via max depth limit
- XSS via markdown: mitigation via bleach allowlist

**Testing Strategy:** Create nested replies, verify anonymous masking, test tombstone deletion, validate markdown rendering, confirm HTML sanitization blocks script tags

---

### Task 2.6: Attachments — Upload, Validate, Store, Serve

**Description:** Implement drag-and-drop and multipart file upload for problems/solutions/comments with strict validation (allowlist: images, docs, archives), size limits (10MB/file, 50MB/problem), and UUID-based storage. Files served directly via NGINX with immutable caching headers. Atomic deletion removes both database record and disk file.

**Requirements Covered:** REQ-400, REQ-402, REQ-404, REQ-406, REQ-408, REQ-410, REQ-412, REQ-414, REQ-416

**Dependencies:** Task 2.1

**Complexity:** M

**Subtasks:**
1. Create attachments table with parent_type, parent_id, uploader_id, filename, content_type, file_size, storage_path
2. Implement POST /api/attachments multipart endpoint with type allowlist validation
3. Add file size validation: reject ≥10MB/file before write, aggregate parent check for 50MB/problem
4. Implement UUID-based storage: /data/attachments/{year}/{month}/{uuid}_{filename}
5. Configure NGINX to serve /attachments/* directly with Cache-Control: public, max-age=604800, immutable
6. Add DELETE /api/attachments/{id} (uploader/admin): atomic removal of DB row + disk file
7. Implement inline markdown image embedding and download links for non-images

**Risks:**
- Disk space exhaustion: mitigation via enforced 50MB/problem quota
- Path traversal via filename: mitigation via UUID prefixing and extension validation only

**Testing Strategy:** Upload image (pass), upload .exe (fail 422), upload >10MB (fail), test NGINX serving with cache headers, verify atomic deletion

---

## Phase 3 — Search, Notifications & Engagement

### Task 3.1: Full-Text Search & Similar-Problem Suggestions

**Description:** Implement PostgreSQL full-text search with tsvector and GIN indexing on problem titles and descriptions, supporting cross-entity search across comments and solutions. Provide ranked results via a REST API with filtering and sorting, plus a real-time similar-problem suggestion endpoint triggered during title input with debouncing.

**Requirements Covered:** REQ-350, REQ-352, REQ-354, REQ-356, REQ-358, REQ-360, REQ-362, REQ-364

**Dependencies:** Task 2.1, Task 2.3, Task 2.5

**Complexity:** M

**Subtasks:**
1. Create tsvector columns and GIN indexes on problems.title and problems.description, and add tsvector columns to comments and solutions tables
2. Implement search service with to_tsquery parsing, ts_rank ranking, and cross-entity result merging with match_context field
3. Build GET /api/problems/search endpoint with q parameter, sort (relevance/upstars/newest), and filter support
4. Implement empty search state returning "No problems match your search" with link to submit
5. Create similar-problem suggestion endpoint triggered on title input returning up to 5 results
6. Build suggestion UI displaying links with 120-char description excerpts

**Risks:** Cross-entity result merging could exceed sub-200ms p95 — optimize with strategic index placement and query pagination.

**Testing Strategy:** Integration test sub-200ms p95 on 10k-row dataset. Test cross-entity results include correct match_context. Test filter combinations.

---

### Task 3.2: Link Previews — Open Graph Meta Tags & Bot Detection

**Description:** Create an endpoint returning Open Graph meta tags for rich link previews, including problem title, description with upstars/solution count, and status. Implement NGINX bot detection to serve meta HTML instead of SPA shell for Teams, Slack, and crawler User-Agents.

**Requirements Covered:** REQ-366, REQ-368

**Dependencies:** Task 2.1

**Complexity:** S

**Subtasks:**
1. Create GET /api/problems/{id}/meta endpoint returning HTML with og:title, og:description, og:url, og:type, og:site_name
2. Format og:description to include upstars count and solution count
3. Add NGINX bot detection matching Teams, Slack, and crawler User-Agents
4. Configure bot detection to return meta HTML instead of SPA shell

**Testing Strategy:** Test meta tag endpoint with curl. Simulate bot User-Agents. Verify non-bot requests receive SPA shell.

---

### Task 3.3: Watch System & Notification Generation

**Description:** Build a watch system allowing users to subscribe to problem activity at configurable levels (all_activity, solutions_only, status_only, none), with auto-watch logic triggered by post, claim, solution, and comment actions. Implement notification generation for eight event types routed based on watch level, and create an idempotent background job for claim expiry notifications.

**Requirements Covered:** REQ-300, REQ-302, REQ-304, REQ-306, REQ-308, REQ-310, REQ-312, REQ-324

**Dependencies:** Task 2.1, Task 2.3

**Complexity:** M

**Subtasks:**
1. Create watches table with user_id, problem_id, level, UNIQUE(user_id, problem_id)
2. Implement watch CRUD: POST /api/problems/{id}/watch, DELETE, GET /api/users/me/watches
3. Build auto-watch: all_activity on post/claim/solution, solutions_only on comment; upgrade if lower
4. Add notification_prefs JSONB to users with auto_watch overrides
5. Implement notification generation with eight types and watch-level routing matrix
6. Create background job (≤15 min interval) for claim expiry notifications, idempotent

**Risks:** Auto-watch race conditions — use upsert patterns. Complex routing — use clear routing matrix.

**Testing Strategy:** Unit test auto-watch upgrade logic. Test notification generation against routing matrix. Test background job idempotency.

---

### Task 3.4: Notification Delivery — In-App, WebSocket, Teams, Email

**Description:** Implement multi-channel notification delivery: in-app via REST API with bell icon dropdown, real-time WebSocket push, Teams direct message via incoming webhook, and daily email digest aggregating unread notifications from the past 24 hours. Include milestone notification batching at thresholds 10, 25, 50, 100.

**Requirements Covered:** REQ-314, REQ-316, REQ-318, REQ-320, REQ-322

**Dependencies:** Task 3.3

**Complexity:** L

**Subtasks:**
1. Build REST API: GET /api/notifications (paginated), PATCH /api/notifications/{id}/read, POST /api/notifications/read-all
2. Implement WebSocket at WS /api/ws/notifications, push JSON within 2s
3. Create Teams webhook delivery with opt-in, non-blocking failure handling
4. Implement daily email digest job aggregating past 24h unread
5. Build milestone notification deduplication (10/25/50/100 thresholds)
6. Add delivery preference tracking (teams/email opt-in flags)

**Risks:** WebSocket drops — accept transient loss per spec. Email digest timing — use job status table with atomic check-and-set.

**Testing Strategy:** Integration test all four delivery channels. Mock Teams webhook. Test WebSocket push latency. Verify milestone deduplication.

---

### Task 3.5: Leaderboard

**Description:** Create a dual-track leaderboard ranking users by accepted solution count (Top Solvers) and total upstars received (Top Reporters), with time filtering options (week, month, all_time) and exclusion of anonymous contributions.

**Requirements Covered:** REQ-268, REQ-270

**Dependencies:** Task 2.4

**Complexity:** S

**Subtasks:**
1. Create GET /api/leaderboard endpoint accepting time_filter parameter
2. Implement Top Solvers track (accepted solution count, sorted descending)
3. Implement Top Reporters track (total upstars received, sorted descending)
4. Filter out anonymous contributions from both tracks
5. Apply time filtering using created_at bounds

**Testing Strategy:** Verify anonymous exclusion from both tracks. Test all three time filters. Verify ranking correctness.

---

## Phase 4 — Administration

### Task 4.1: Category Management — CRUD, Reorder, Soft-Delete

**Description:** Implement full category lifecycle management allowing admins to create, edit (name, description, color), and deactivate categories via REST API. Support ordered reordering and enforce soft-delete constraints preventing hard-deletion of categories with associated problems.

**Requirements Covered:** REQ-452, REQ-456, REQ-458

**Dependencies:** Task 1.2

**Complexity:** S

**Subtasks:**
1. Implement GET, POST, PATCH, DELETE endpoints for /api/categories gated to admins
2. Add is_active boolean with soft-delete semantics
3. Implement PATCH /api/categories/reorder accepting ordered array of IDs; 422 if omitted/duplicated
4. Build hard-delete protection: 409 if category has problems

**Testing Strategy:** Test CRUD as admin/non-admin. Test reorder with valid/invalid arrays. Verify soft-delete protection.

---

### Task 4.2: Tag Management — CRUD, Merge, Usage Counts

**Description:** Build tag management allowing admins to view tags with usage counts, rename, delete, and atomically merge multiple tags into a target tag.

**Requirements Covered:** REQ-460, REQ-462, REQ-464

**Dependencies:** Task 2.1

**Complexity:** S

**Subtasks:**
1. Implement GET /api/tags with usage_count and sort_by (name/usage)
2. Build PATCH /api/tags/{id} for rename
3. Implement DELETE /api/tags/{id} removing from all problems
4. Create POST /api/tags/merge: atomic re-tagging, source tags removed; <2 sources → 422

**Testing Strategy:** Test usage count accuracy. Test merge atomicity. Verify 422 for invalid merge requests.

---

### Task 4.3: User Management & Moderation

**Description:** Build comprehensive admin backend with user search and role/status management, moderation queue for flagged content and duplicate confirmations, de-anonymization with immutable audit logs, and configurable app name. Enforce admin-only access and invalidate sessions on deactivation.

**Requirements Covered:** REQ-450, REQ-466, REQ-468, REQ-470, REQ-472, REQ-474, REQ-476

**Dependencies:** Task 1.3

**Complexity:** M

**Subtasks:**
1. Create require_admin dependency: 401 if unauth, 403 if non-admin
2. Implement GET /api/admin/users with search (case-insensitive, partial match) and pagination
3. Build PATCH role and status endpoints; session invalidation on deactivation
4. Create GET /api/admin/flagged: combined queue of pending duplicates + flagged anonymous posts
5. Implement POST /api/admin/deanonymize with confirmation and immutable audit log
6. Add GET/PATCH /api/admin/config for app_name (DB overrides env var)

**Risks:** Deactivation must invalidate sessions atomically. De-anonymization is irreversible — create audit log in same transaction.

**Testing Strategy:** Test require_admin dependency. Test user search. Test deactivation invalidates sessions. Test de-anonymize audit log immutability.

---

## Phase 5 — Frontend

### Task 5.1: App Shell — Routing, Theme, Dark Mode, Responsive Layout

**Description:** Build the React application shell with client-side routing, a comprehensive theme system supporting the yellow-to-lime-green gradient with monospace badges, dark mode toggle with OS preference detection and session persistence, and a responsive layout with desktop sidebar and mobile alternative navigation.

**Requirements Covered:** REQ-500, REQ-504, REQ-508, REQ-512, REQ-514, REQ-520

**Dependencies:** Task 1.1

**Complexity:** M

**Subtasks:**
1. Set up React Router with client-side routing, deep linking, and 404 fallback
2. Create theme provider with CSS variables for gradient, typography, and status badge colors
3. Implement dark mode toggle: read OS preference, persist to localStorage, apply consistently
4. Build responsive layout with collapsible sidebar (≥1024px) and mobile nav (<1024px)
5. Create APP_NAME configuration from environment variable
6. Validate deep linking and no horizontal overflow at all breakpoints

**Risks:** Sidebar collapse state must sync with responsive breakpoint — mitigation: CSS media queries alongside JS state.

**Testing Strategy:** Component tests for theme, dark mode persistence, sidebar at breakpoint; E2E for deep linking.

---

### Task 5.2: Landing Page & Auth Flow

**Description:** Create a cork-textured bulletin board themed landing page with decorative note cards at randomized angles, centered sign-in card with gradient border, and integrated Azure AD + magic link authentication flows.

**Requirements Covered:** REQ-502

**Dependencies:** Task 5.1, Task 1.3

**Complexity:** S

**Subtasks:**
1. Apply cork-texture background
2. Generate decorative note cards with randomized rotation
3. Build centered sign-in card with gradient border and zero tilt
4. Display tagline "Surface problems. Propose solutions. Get recognized."
5. Verify layout visible at 1280x800 without scrolling

**Testing Strategy:** Visual regression at 1280x800. Test dark mode rendering.

---

### Task 5.3: Feed Page & Problem Detail

**Description:** Implement a vertical card-based feed page with sort/filter controls and a problem detail page with markdown rendering, tabbed solutions/comments, and action buttons.

**Requirements Covered:** REQ-506, REQ-510

**Dependencies:** Task 5.1, Task 2.2

**Complexity:** M

**Subtasks:**
1. Create ProblemCard component with all data points (upstar, title, status badge, claimer, category, tags, counts, timestamp)
2. Build Feed page with card list, sort bar, filter bar
3. Implement infinite scroll or pagination
4. Create ProblemDetail with header (title, author, status, upstar/claim buttons)
5. Implement markdown rendering with sanitization
6. Build tabbed "Solutions" and "Comments" with URL parameter-based switching

**Risks:** Infinite scroll performance — mitigation: virtual scrolling if needed.

**Testing Strategy:** Component tests for card rendering. Integration tests for sort/filter. E2E for tab switching via URL.

---

### Task 5.4: Forms — Submit Problem, Solution, Comment, Attachments

**Description:** Develop content creation forms with markdown editor, live preview, tag autocomplete, file upload zones with clipboard paste support, and client-side validation.

**Requirements Covered:** REQ-522, REQ-414

**Dependencies:** Task 5.1, Task 2.6

**Complexity:** M

**Subtasks:**
1. Build submit problem form (title, markdown editor, category, tag autocomplete, anonymous checkbox)
2. Create MarkdownEditor with live preview within 300ms
3. Implement tag autocomplete after 2 characters
4. Design attachment drop zones with drag-and-drop and visual feedback
5. Add clipboard paste capture (Ctrl+V/Cmd+V) with upload validation
6. Implement client-side validation with inline errors

**Risks:** Live preview lag — mitigation: debounce. Tag autocomplete spam — mitigation: debounce and cache.

**Testing Strategy:** Unit tests for preview timing. Component tests for validation. Integration for tag autocomplete and file upload.

---

### Task 5.5: Search, Notifications, Leaderboard, Settings, AI Placeholder

**Description:** Implement search results page, notification bell with WebSocket live updates, leaderboard with dual tracks and time filtering, settings page, and non-interactive AI search placeholder.

**Requirements Covered:** REQ-524, REQ-526

**Dependencies:** Task 5.1, Task 3.1, Task 3.4, Task 3.5

**Complexity:** M

**Subtasks:**
1. Create search results page with sort/filter controls
2. Build NotificationBell with unread count badge, dropdown, and WebSocket listener
3. Implement Leaderboard page with ranked table and time filter tabs
4. Add dual-track tab switching (solvers/reporters)
5. Create Settings page with notification preferences and dark mode toggle
6. Build /ai-search placeholder with disabled elements and "Coming Soon" banner

**Risks:** WebSocket reconnection — mitigation: exponential backoff.

**Testing Strategy:** Component tests for notification bell. Integration for WebSocket. E2E for leaderboard. Verify AI search is non-interactive.

---

### Task 5.6: Admin Pages

**Description:** Build admin dashboard pages with role-based route guards, category/tag/user management UIs, moderation queue, and app configuration.

**Requirements Covered:** REQ-476

**Dependencies:** Task 5.1, Task 4.3

**Complexity:** M

**Subtasks:**
1. Create role-based route guards (non-admins → /, unauth → login)
2. Build category management UI (CRUD, drag-to-reorder, color picker)
3. Implement tag management UI (list, rename, merge dialog, delete)
4. Design user management page (search, role toggle, activate/deactivate)
5. Create moderation queue with de-anonymize confirmation dialog
6. Build app config section

**Risks:** De-anonymization is irreversible — mitigation: confirmation dialog with warning.

**Testing Strategy:** Integration tests for route guards. E2E for CRUD workflows. Test de-anonymization confirmation flow.

---

### Task 5.7: Error States & Empty States

**Description:** Develop reusable empty state component, custom error pages (404, 401/403), toast notification system with auto-dismiss, and inline form validation.

**Requirements Covered:** REQ-516, REQ-518

**Dependencies:** Task 5.1

**Complexity:** S

**Subtasks:**
1. Create reusable EmptyState component with title, description, and CTA props
2. Build custom 404 page with link to feed
3. Build custom 401/403 page
4. Implement toast system with auto-dismiss after 5s
5. Add inline validation error display on form fields
6. Test all components in light and dark mode

**Testing Strategy:** Component tests for empty states. Visual regression for error pages. Integration for toast notifications.

---

## Phase 6 — Hardening & Operations

### Task 6.1: Security — Headers, CSP, XSS Prevention, MIME Inspection, TLS

**Description:** Implement TLS 1.2+ at NGINX, HTTP→HTTPS redirect, security response headers (CSP, X-Content-Type-Options, X-Frame-Options, Referrer-Policy), markdown sanitization at storage and render time, and MIME content inspection on uploads.

**Requirements Covered:** REQ-906, REQ-908, REQ-918, REQ-924

**Dependencies:** Task 1.1, Task 2.6

**Complexity:** M

**Subtasks:**
1. Configure NGINX with TLS 1.2+ and HTTP → HTTPS 301 redirect
2. Implement JWT cookie middleware enforcing HttpOnly, Secure, SameSite=Strict
3. Add security response headers via middleware
4. Implement markdown sanitization at storage and render time
5. Build MIME content inspection on uploads (magic bytes), reject executables with 422
6. Create configurable file type allowlist

**Risks:** Overly strict CSP could break scripts — mitigation: test thoroughly.

**Testing Strategy:** Security scanning with OWASP tools. Unit tests for sanitizer with XSS payloads. Integration for header presence.

---

### Task 6.2: Structured Logging & Observability

**Description:** Implement structured JSON logging with correlation IDs per request, capturing method, path, user_id, status_code, duration_ms. Add business event logging for domain events.

**Requirements Covered:** REQ-912

**Dependencies:** Task 1.1

**Complexity:** S

**Subtasks:**
1. Create logging middleware generating UUID correlation_id per request
2. Configure structlog for JSON output with all required fields
3. Log request/response lifecycle with correlation ID
4. Create business event logger for domain events (problem_created, solution_submitted, etc.)

**Testing Strategy:** Unit tests for correlation ID generation. Integration for JSON format and fields.

---

### Task 6.3: Rate Limiting

**Description:** Enforce NGINX rate limiting (30 req/s on /api/*, 5 req/s on /api/auth/*) and application-level per-email rate limiting for magic link endpoint (5 req/email/10 min).

**Requirements Covered:** REQ-910, REQ-128

**Dependencies:** Task 1.1

**Complexity:** S

**Subtasks:**
1. Configure NGINX rate limiting with 429 on excess
2. Implement per-email rate limiting middleware for magic link
3. Return Retry-After header on 429

**Testing Strategy:** Integration tests for NGINX rate limiting. Test magic link per-email limits. Load tests.

---

### Task 6.4: Backup, Deployment & Health Check

**Description:** Establish daily database backups (pg_dump + attachment rsync) with 7-daily + 4-weekly retention, systemd service units for auto-restart, and a /healthz endpoint.

**Requirements Covered:** REQ-914, REQ-922, REQ-928

**Dependencies:** Task 1.1, Task 1.2

**Complexity:** M

**Subtasks:**
1. Write backup.sh with pg_dump and rsync
2. Implement rotation (7 daily + 4 weekly)
3. Create restore.sh with documented procedure
4. Generate systemd units via podman generate systemd
5. Configure auto-restart on reboot within 2 min
6. Implement /healthz returning {status, db} at 200/503

**Risks:** Backup storage fill — mitigation: space monitoring. Restore untested — mitigation: staging drills.

**Testing Strategy:** Test backup/restore cycle. Verify systemd restart. Performance test /healthz latency.

---

### Task 6.5: Performance Validation & Test Coverage

**Description:** Establish test infrastructure with pytest, httpx.AsyncClient, factory_boy, and load test scripts. Validate p95 ≤ 500ms, p99 ≤ 2000ms at 100 concurrent users, search p95 ≤ 1000ms at 10k+ problems, and ≥ 80% line coverage.

**Requirements Covered:** REQ-900, REQ-902, REQ-904, REQ-926

**Dependencies:** All above

**Complexity:** M

**Subtasks:**
1. Set up pytest with conftest.py, fixtures for test DB, async client, and factories
2. Create test factories for problems, solutions, comments, users
3. Write unit tests for all service functions targeting ≥80% coverage
4. Write integration tests for route handlers with auto-rollback
5. Implement load test scripts (locust or similar) validating latency targets
6. Create search load test with 10k+ problems

**Risks:** Load test results may differ from production — document environment specs.

**Testing Strategy:** Coverage threshold enforced by CI. Load tests in staging before production.

---

## Task Dependency Graph

```
                        ┌─────────────┐
                        │  1.1 [CR]   │
                        └──────┬──────┘
              ┌────────────────┼────────────────────────────┐
              │                │                            │
              ▼                ▼                            ▼
        ┌───────────┐   ┌───────────┐              ┌─────────────┐
        │  1.2 [CR] │   │    5.1    │              │  6.2, 6.3   │
        └─────┬─────┘   └─────┬─────┘              └─────────────┘
              │          ┌─────┼──────────┬──────┐
              │          │     │          │      │
              ▼          ▼     ▼          ▼      ▼
        ┌───────────┐  5.7   5.2*       5.4*   5.6*
        │  1.3 [CR] │
        └─────┬─────┘
              │
     ┌────────┼────────┐
     │        │        │
     ▼        ▼        ▼
   4.3      5.2*   ┌───────────┐
                   │  2.1 [CR] │
                   └─────┬─────┘
        ┌────────┬───────┼────────┬────────┐
        │        │       │        │        │
        ▼        ▼       ▼        ▼        ▼
      2.2      2.3     2.6      3.2      4.2
        │      / \       │
        │     /   \      │
        ▼    ▼     ▼     ▼
      5.3*  2.4   2.5   5.4*
              │     │
              ▼     │
             3.5    │
              │     ▼
              │    3.1
              │     │
              ▼     │
              ├─────┘
              │
        ┌─────┴─────┐
        │  3.3 [CR] │
        └─────┬─────┘
              │
              ▼
        ┌───────────┐
        │  3.4 [CR] │
        └─────┬─────┘
              │
              ▼
        ┌───────────┐
        │  5.5 [CR] │
        └─────┬─────┘
              │
              ▼
        ┌───────────┐
        │  6.5 [CR] │
        └───────────┘

  [CR] = Critical Path
  * = has additional dependencies (see task details)

  Critical Path: 1.1 → 1.2 → 1.3 → 2.1 → 2.3 → 3.3 → 3.4 → 5.5 → 6.5
```

---

## Task-to-Requirement Traceability

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
| REQ-128 | SHOULD | 1.3, 6.3 | Auth |
| REQ-150 | MUST | 2.1 | Problems |
| REQ-152 | MUST | 2.1 | Problems |
| REQ-154 | MUST | 2.1 | Problems |
| REQ-156 | MUST | 2.1 | Problems |
| REQ-158 | MUST | 2.1 | Problems |
| REQ-160 | MUST | 2.1 | Problems |
| REQ-162 | MUST | 2.1 | Problems |
| REQ-164 | MUST | 2.1 | Problems |
| REQ-166 | MUST | 2.1 | Problems |
| REQ-168 | MUST | 2.2 | Problems |
| REQ-170 | MUST | 2.2 | Problems |
| REQ-172 | MUST | 2.2 | Problems |
| REQ-174 | MUST | 2.2 | Problems |
| REQ-176 | SHOULD | 2.2 | Problems |
| REQ-178 | SHOULD | 2.2 | Problems |
| REQ-180 | SHOULD | 2.2 | Problems |
| REQ-182 | MAY | 2.2 | Problems |
| REQ-200 | MUST | 2.3 | Solutions |
| REQ-202 | MUST | 2.3 | Solutions |
| REQ-204 | MUST | 2.3 | Solutions |
| REQ-206 | MUST | 2.3 | Solutions |
| REQ-208 | MUST | 2.3 | Solutions |
| REQ-210 | MUST | 2.3 | Solutions |
| REQ-212 | MUST | 2.3 | Solutions |
| REQ-214 | SHOULD | 2.3 | Solutions |
| REQ-216 | MUST | 2.3 | Solutions |
| REQ-218 | MUST | 2.3 | Solutions |
| REQ-220 | SHOULD | 2.3 | Solutions |
| REQ-250 | MUST | 2.4 | Engagement |
| REQ-252 | MUST | 2.4 | Engagement |
| REQ-254 | MUST | 2.4 | Engagement |
| REQ-256 | MUST | 2.4 | Engagement |
| REQ-258 | MUST | 2.5 | Engagement |
| REQ-260 | MUST | 2.5 | Engagement |
| REQ-262 | MUST | 2.5 | Engagement |
| REQ-264 | MUST | 2.5 | Engagement |
| REQ-266 | MUST | 2.5 | Engagement |
| REQ-268 | SHOULD | 3.5 | Engagement |
| REQ-270 | MUST | 2.4 | Engagement |
| REQ-300 | MUST | 3.3 | Notifications |
| REQ-302 | MUST | 3.3 | Notifications |
| REQ-304 | MUST | 3.3 | Notifications |
| REQ-306 | SHOULD | 3.3 | Notifications |
| REQ-308 | MUST | 3.3 | Notifications |
| REQ-310 | MUST | 3.3 | Notifications |
| REQ-312 | MUST | 3.3 | Notifications |
| REQ-314 | MUST | 3.4 | Notifications |
| REQ-316 | MUST | 3.4 | Notifications |
| REQ-318 | SHOULD | 3.4 | Notifications |
| REQ-320 | SHOULD | 3.4 | Notifications |
| REQ-322 | SHOULD | 3.4 | Notifications |
| REQ-324 | MUST | 3.3 | Notifications |
| REQ-350 | MUST | 3.1 | Search |
| REQ-352 | MUST | 3.1 | Search |
| REQ-354 | MUST | 3.1 | Search |
| REQ-356 | MUST | 3.1 | Search |
| REQ-358 | SHOULD | 3.1 | Search |
| REQ-360 | MUST | 3.1 | Search |
| REQ-362 | MUST | 3.1 | Search |
| REQ-364 | SHOULD | 3.1 | Search |
| REQ-366 | SHOULD | 3.2 | Search |
| REQ-368 | SHOULD | 3.2 | Search |
| REQ-400 | MUST | 2.6 | Attachments |
| REQ-402 | MUST | 2.6 | Attachments |
| REQ-404 | MUST | 2.6 | Attachments |
| REQ-406 | MUST | 2.6 | Attachments |
| REQ-408 | MUST | 2.6 | Attachments |
| REQ-410 | MUST | 2.6 | Attachments |
| REQ-412 | MUST | 2.6 | Attachments |
| REQ-414 | SHOULD | 2.6, 5.4 | Attachments |
| REQ-416 | MUST | 2.6 | Attachments |
| REQ-450 | MUST | 4.3 | Admin |
| REQ-452 | MUST | 4.1 | Admin |
| REQ-454 | MUST | 1.2 | Admin |
| REQ-456 | MUST | 4.1 | Admin |
| REQ-458 | MUST | 4.1 | Admin |
| REQ-460 | MUST | 4.2 | Admin |
| REQ-462 | MUST | 4.2 | Admin |
| REQ-464 | MUST | 4.2 | Admin |
| REQ-466 | MUST | 4.3 | Admin |
| REQ-468 | MUST | 4.3 | Admin |
| REQ-470 | MUST | 4.3 | Admin |
| REQ-472 | MUST | 4.3 | Admin |
| REQ-474 | SHOULD | 4.3 | Admin |
| REQ-476 | SHOULD | 4.3, 5.6 | Admin |
| REQ-500 | MUST | 5.1 | UI/UX |
| REQ-502 | MUST | 5.2 | UI/UX |
| REQ-504 | MUST | 5.1 | UI/UX |
| REQ-506 | MUST | 5.3 | UI/UX |
| REQ-508 | MUST | 5.1 | UI/UX |
| REQ-510 | MUST | 5.3 | UI/UX |
| REQ-512 | MUST | 5.1 | UI/UX |
| REQ-514 | MUST | 5.1 | UI/UX |
| REQ-516 | MUST | 5.7 | UI/UX |
| REQ-518 | MUST | 5.7 | UI/UX |
| REQ-520 | MUST | 5.1 | UI/UX |
| REQ-522 | SHOULD | 5.4 | UI/UX |
| REQ-524 | SHOULD | 5.5 | UI/UX |
| REQ-526 | SHOULD | 5.5 | UI/UX |
| REQ-900 | MUST | 6.5 | NFR |
| REQ-902 | MUST | 6.5 | NFR |
| REQ-904 | MUST | 6.5 | NFR |
| REQ-906 | MUST | 6.1 | NFR |
| REQ-908 | MUST | 6.1 | NFR |
| REQ-910 | MUST | 6.3 | NFR |
| REQ-912 | MUST | 6.2 | NFR |
| REQ-914 | MUST | 6.4 | NFR |
| REQ-916 | MUST | 1.1 | NFR |
| REQ-918 | MUST | 6.1 | NFR |
| REQ-920 | MUST | 1.2 | NFR |
| REQ-922 | MUST | 6.4 | NFR |
| REQ-924 | SHOULD | 6.1 | NFR |
| REQ-926 | SHOULD | 6.5 | NFR |
| REQ-928 | MAY | 6.4 | NFR |

**Summary:** 129 requirements (103 MUST, 24 SHOULD, 2 MAY) — all covered.

---

# Part B: Code Appendix

## B.1: Application Configuration — Contract

Pydantic Settings class for all environment-driven configuration. Used by every service and middleware.

**Tasks:** Task 1.1
**Requirements:** REQ-916, REQ-504
**Type:** Contract (exact — copied to implementation docs Phase 0)

```python
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Central application configuration loaded from environment variables.

    All fields map 1-to-1 to environment variable names (case-insensitive).
    Sensitive fields use SecretStr to prevent accidental logging.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Database --- REQ-916
    DATABASE_URL: str = Field(
        ...,
        description="asyncpg DSN, e.g. postgresql+asyncpg://user:pass@host/db",
    )  # REQ-916

    # --- Azure AD OIDC --- REQ-504
    AZURE_TENANT_ID: str = Field(..., description="Azure AD tenant UUID")  # REQ-504
    AZURE_CLIENT_ID: str = Field(..., description="App registration client UUID")  # REQ-504
    AZURE_CLIENT_SECRET: SecretStr = Field(..., description="App registration secret")  # REQ-504

    # --- JWT --- REQ-108
    JWT_SECRET: SecretStr = Field(..., description="HS256 signing secret, min 32 chars")  # REQ-108

    # --- SMTP --- REQ-104
    SMTP_HOST: str = Field(..., description="SMTP relay hostname")  # REQ-104
    SMTP_PORT: int = Field(587, ge=1, le=65535, description="SMTP port")  # REQ-104
    SMTP_FROM: str = Field(..., description="Envelope From address")  # REQ-104

    # --- Application identity ---
    APP_NAME: str = Field("Aion Bulletin", description="Display name used in emails/UI")

    # --- Developer escape hatches ---
    DEV_AUTH_BYPASS: bool = Field(
        False,
        description="When True, auth middleware accepts any Bearer token as user_id=1. "
        "MUST be False in production.",
    )
    ENVIRONMENT: Literal["development", "staging", "production"] = Field("development")

    # --- File storage --- REQ-404
    STORAGE_PATH: str = Field("/data/attachments", description="Absolute path for attachment blobs")  # REQ-404

    # --- URLs ---
    BASE_URL: AnyHttpUrl = Field(..., description="Public base URL, used for magic-link hrefs")  # REQ-104

    # --- Optional integrations ---
    TEAMS_WEBHOOK_URL: AnyHttpUrl | None = Field(None, description="MS Teams incoming webhook")

    @field_validator("JWT_SECRET", mode="after")
    @classmethod
    def jwt_secret_min_length(cls, v: SecretStr) -> SecretStr:
        if len(v.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters")
        return v

    @field_validator("DATABASE_URL", mode="after")
    @classmethod
    def database_url_must_be_async(cls, v: str) -> str:
        if not v.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must use the postgresql+asyncpg:// scheme")
        return v

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton Settings instance. Use get_settings.cache_clear() in tests."""
    return Settings()
```

**Key design decisions:**
- `SecretStr` on secrets prevents accidental logging via structlog repr.
- `@lru_cache` gives process-level singleton; tests call `cache_clear()`.
- `field_validator` catches misconfiguration at startup (fail-fast).
- `TEAMS_WEBHOOK_URL` optional — zero-config add-on.

---

## B.2: Enum Types — Contract

All domain enums used across models, schemas, and services.

**Tasks:** Task 1.2
**Requirements:** REQ-156, REQ-114, REQ-300, REQ-310, REQ-170, REQ-258
**Type:** Contract (exact — copied to implementation docs Phase 0)

```python
from __future__ import annotations

from enum import Enum


class ProblemStatus(str, Enum):
    """
    Finite states for a Problem record.
    Legal FSM transitions enforced by transition_status service.
    REQ-156
    """
    open = "open"           # REQ-156: default state on creation
    claimed = "claimed"     # REQ-156: a user has taken ownership
    solved = "solved"       # REQ-156: solver marked their solution complete
    accepted = "accepted"   # REQ-156: problem author accepted a solution
    duplicate = "duplicate" # REQ-156: admin flagged as duplicate


class UserRole(str, Enum):
    """Authorization roles. REQ-114"""
    user = "user"   # REQ-114: default role
    admin = "admin" # REQ-114: elevated role


class WatchLevel(str, Enum):
    """Notification granularity for problem watches. REQ-300"""
    all_activity = "all_activity"       # REQ-300
    solutions_only = "solutions_only"   # REQ-300
    status_only = "status_only"         # REQ-300
    none = "none"                       # REQ-300


class NotificationType(str, Enum):
    """Discriminator for Notification records. REQ-310"""
    new_comment = "new_comment"                                    # REQ-310
    new_solution = "new_solution"                                  # REQ-310
    solution_accepted = "solution_accepted"                        # REQ-310
    problem_claimed = "problem_claimed"                            # REQ-310
    upvote_milestone = "upvote_milestone"                          # REQ-310
    solution_upvote_milestone = "solution_upvote_milestone"        # REQ-310
    claim_expired = "claim_expired"                                # REQ-310
    duplicate_flagged = "duplicate_flagged"                        # REQ-310


class SortMode(str, Enum):
    """Feed ordering strategies. REQ-170"""
    top = "top"             # REQ-170: descending upstar count
    new = "new"             # REQ-170: descending created_at
    active = "active"       # REQ-170: descending activity_at
    discussed = "discussed" # REQ-170: descending comment_count


class ParentType(str, Enum):
    """Polymorphic parent discriminator. REQ-258, REQ-408"""
    problem = "problem"     # REQ-258
    solution = "solution"   # REQ-258
    comment = "comment"     # REQ-258
```

**Key design decisions:**
- All enums inherit `(str, Enum)` for direct JSON serialization and SQLAlchemy Enum columns.
- `WatchLevel.none` uses string `"none"` (not Python `None`) for non-nullable DB column.

---

## B.3: Exception Types — Contract

Custom exception hierarchy for all domain errors.

**Tasks:** Task 2.1, Task 2.4, Task 2.6, Task 1.3
**Requirements:** REQ-156, REQ-164, REQ-404, REQ-402, REQ-250, REQ-106, REQ-102
**Type:** Contract (exact — copied to implementation docs Phase 0)

```python
from __future__ import annotations

from http import HTTPStatus


class AppError(Exception):
    """Base class for all application-domain exceptions."""
    status_code: int = HTTPStatus.INTERNAL_SERVER_ERROR
    detail: str = "An unexpected error occurred."

    def __init__(self, detail: str | None = None) -> None:
        if detail is not None:
            self.detail = detail
        super().__init__(self.detail)


class ForbiddenTransitionError(AppError):
    """Raised when Problem FSM rejects a status transition. REQ-156"""
    status_code: int = HTTPStatus.CONFLICT

    def __init__(self, current_status: str, target_status: str) -> None:
        self.current_status = current_status  # REQ-156
        self.target_status = target_status    # REQ-156
        super().__init__(f"Cannot transition from '{current_status}' to '{target_status}'.")


class PinLimitExceededError(AppError):
    """Raised when admin tries to pin a 4th problem. REQ-164"""
    status_code: int = HTTPStatus.CONFLICT
    detail: str = "Pin limit reached: at most 3 problems may be pinned at once."


class FileSizeLimitError(AppError):
    """Raised when upload exceeds 10MB/file or 50MB/problem. REQ-404"""
    status_code: int = HTTPStatus.REQUEST_ENTITY_TOO_LARGE

    def __init__(self, file_size: int, max_size: int) -> None:
        self.file_size = file_size  # REQ-404
        self.max_size = max_size    # REQ-404
        super().__init__(f"File size {file_size:,} bytes exceeds {max_size:,} bytes limit.")


class FileTypeNotAllowedError(AppError):
    """Raised when MIME type or extension not on allowlist. REQ-402"""
    status_code: int = HTTPStatus.UNPROCESSABLE_ENTITY

    def __init__(self, content_type: str, filename: str) -> None:
        self.content_type = content_type  # REQ-402
        self.filename = filename          # REQ-402
        super().__init__(f"File '{filename}' ({content_type}) is not permitted.")


class DuplicateVoteError(AppError):
    """Raised on duplicate vote UNIQUE constraint violation. REQ-250, REQ-254"""
    status_code: int = HTTPStatus.CONFLICT
    detail: str = "You have already voted on this item."


class MagicLinkExpiredError(AppError):
    """Raised when magic link token expired or already used. REQ-106"""
    status_code: int = HTTPStatus.GONE
    detail: str = "This magic link has expired or has already been used."


class TenantMismatchError(AppError):
    """Raised when Azure AD tid doesn't match configured tenant. REQ-102"""
    status_code: int = HTTPStatus.FORBIDDEN
    detail: str = "Azure AD tenant does not match the configured organisation."
```

**Key design decisions:**
- All inherit `AppError` so the global exception handler catches a single type.
- Error-carrying attributes (`current_status`, `file_size`, etc.) enable structured logging.
- `ForbiddenTransitionError` uses HTTP 409 (conflict) to distinguish from 422 (validation).

---

## B.4: Pydantic Schemas — Contract

Request/response models for all core API endpoints.

**Tasks:** Task 2.1, Task 2.2, Task 2.3, Task 2.5, Task 1.3
**Requirements:** REQ-150, REQ-152, REQ-154, REQ-168, REQ-200, REQ-204, REQ-206, REQ-258, REQ-104, REQ-118
**Type:** Contract (exact — copied to implementation docs Phase 0)

```python
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Generic, TypeVar

from pydantic import AnyHttpUrl, BaseModel, EmailStr, Field

from .enums import ProblemStatus, UserRole

T = TypeVar("T")


class CursorPage(BaseModel, Generic[T]):
    """Cursor-based pagination envelope. REQ-168"""
    items: list[T]                   # REQ-168
    next_cursor: str | None = None   # REQ-168: None = last page


# --- Auth ---

class MagicLinkRequest(BaseModel):
    """POST /auth/magic-link. REQ-104"""
    email: EmailStr  # REQ-104


class TokenPayload(BaseModel):
    """Decoded JWT claims. REQ-108"""
    sub: int            # REQ-108: internal user PK
    role: str           # REQ-108
    exp: datetime       # REQ-108


class UserResponse(BaseModel):
    """Public user representation. REQ-118"""
    model_config = {"from_attributes": True}
    id: int                      # REQ-118
    display_name: str            # REQ-118
    email: EmailStr              # REQ-118
    role: UserRole               # REQ-118
    created_at: datetime         # REQ-118


# --- Problems ---

class ProblemCreate(BaseModel):
    """POST /problems. REQ-150, REQ-152, REQ-154"""
    title: Annotated[str, Field(min_length=5, max_length=200)]   # REQ-152
    description: Annotated[str, Field(min_length=10)]            # REQ-152
    category_id: int                                             # REQ-150
    tag_ids: list[int] = Field(default_factory=list)             # REQ-150
    is_anonymous: bool = False                                   # REQ-154


class ProblemResponse(BaseModel):
    """Feed card representation. REQ-506"""
    model_config = {"from_attributes": True}
    id: int                          # REQ-506
    title: str                       # REQ-506
    description: str                 # REQ-506
    author: UserResponse | None      # REQ-506: None when anonymous
    status: ProblemStatus            # REQ-506
    category: str                    # REQ-506
    tags: list[str]                  # REQ-506
    upstar_count: int                # REQ-506
    solution_count: int              # REQ-506
    comment_count: int               # REQ-506
    is_pinned: bool                  # REQ-506
    created_at: datetime             # REQ-506
    activity_at: datetime            # REQ-506


class ProblemDetailResponse(ProblemResponse):
    """Full problem with viewer-specific state. REQ-510"""
    is_upstarred: bool               # REQ-510
    is_claimed: bool                 # REQ-510
    claims: list[UserResponse]       # REQ-510
    edit_history_count: int          # REQ-510


# --- Solutions ---

class SolutionCreate(BaseModel):
    """POST /problems/{id}/solutions. REQ-200, REQ-204"""
    description: Annotated[str, Field(min_length=10)]  # REQ-200
    git_link: AnyHttpUrl | None = None                  # REQ-204
    is_anonymous: bool = False                          # REQ-200


class SolutionVersionCreate(BaseModel):
    """POST /solutions/{id}/versions. REQ-206"""
    description: Annotated[str, Field(min_length=10)]  # REQ-206
    git_link: AnyHttpUrl | None = None                  # REQ-206


class SolutionResponse(BaseModel):
    """Solution representation. REQ-202"""
    model_config = {"from_attributes": True}
    id: int                      # REQ-202
    author: UserResponse | None  # REQ-202
    description: str             # REQ-202
    git_link: AnyHttpUrl | None  # REQ-202
    status: str                  # REQ-202
    upvote_count: int            # REQ-202
    is_anonymous: bool           # REQ-202
    version_count: int           # REQ-202
    created_at: datetime         # REQ-202


# --- Comments ---

class CommentCreate(BaseModel):
    """POST /comments. REQ-258, REQ-260"""
    body: Annotated[str, Field(min_length=1, max_length=10_000)]  # REQ-258
    parent_comment_id: int | None = None                           # REQ-260
    is_anonymous: bool = False                                     # REQ-258


class CommentResponse(BaseModel):
    """Threaded comment. REQ-258"""
    model_config = {"from_attributes": True}
    id: int                              # REQ-258
    author: UserResponse | None          # REQ-258
    body: str                            # REQ-258
    is_anonymous: bool                   # REQ-258
    is_edited: bool                      # REQ-258
    created_at: datetime                 # REQ-258
    replies: list["CommentResponse"]     # REQ-258, REQ-260


CommentResponse.model_rebuild()
```

**Key design decisions:**
- `CursorPage[T]` uses `Generic[T]` for accurate OpenAPI schema generation.
- `author: UserResponse | None` preserves anonymity at serialization layer.
- `CommentResponse.model_rebuild()` resolves self-referential forward reference.
- `ProblemDetailResponse` extends `ProblemResponse` to share validation logic.

---

## B.5: Service Function Stubs — Contract

Key service interfaces with full signatures, docstrings, and NotImplementedError bodies.

**Tasks:** Task 2.1, Task 2.2, Task 2.3, Task 2.4, Task 3.1, Task 3.3
**Requirements:** REQ-150, REQ-156, REQ-158, REQ-164, REQ-168, REQ-200, REQ-210, REQ-206, REQ-250, REQ-350, REQ-310
**Type:** Contract (exact — copied to implementation docs Phase 0)

```python
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from .enums import NotificationType, ProblemStatus, SortMode
from .exceptions import ForbiddenTransitionError, PinLimitExceededError
from .models import Claim, Notification, Problem, Solution, SolutionVersion
from .schemas import (
    CursorPage, ProblemCreate, ProblemResponse,
    SolutionCreate, SolutionVersionCreate,
)


# --- Problem service ---

async def create_problem(
    db: AsyncSession, user_id: int, data: ProblemCreate,
) -> Problem:
    """Persist a new Problem and tag associations.
    Args: db, user_id (author PK), data (validated payload).
    Returns: Created Problem with relationships loaded.
    Raises: IntegrityError if category_id or tag_ids invalid.
    REQ-150, REQ-152, REQ-154
    """
    raise NotImplementedError("Task 2.1")


async def transition_status(
    db: AsyncSession, problem_id: int, target: ProblemStatus, actor_id: int,
) -> Problem:
    """Apply FSM transition, enforcing adjacency rules.
    Raises: ForbiddenTransitionError on illegal transition. HTTPException(403) on unauthorized.
    REQ-156
    """
    raise NotImplementedError("Task 2.1")


async def claim_problem(
    db: AsyncSession, problem_id: int, user_id: int,
) -> Claim:
    """Create/toggle claim. First claimer = primary. Idempotent.
    Raises: ForbiddenTransitionError if problem not claimable.
    REQ-158
    """
    raise NotImplementedError("Task 2.1")


async def pin_problem(
    db: AsyncSession, problem_id: int, admin_id: int,
) -> Problem:
    """Toggle pin, respecting 3-pin limit.
    Raises: PinLimitExceededError if already 3 pinned.
    REQ-164
    """
    raise NotImplementedError("Task 2.1")


# --- Feed service ---

async def get_feed(
    db: AsyncSession, sort: SortMode, filters: dict,
    cursor: str | None, limit: int, user_id: int | None,
) -> CursorPage[ProblemResponse]:
    """Cursor-paginated, sorted, filtered feed. Pinned above first page.
    REQ-168, REQ-170, REQ-172, REQ-174
    """
    raise NotImplementedError("Task 2.2")


# --- Solution service ---

async def create_solution(
    db: AsyncSession, problem_id: int, user_id: int, data: SolutionCreate,
) -> Solution:
    """Persist a new Solution for a problem.
    REQ-200, REQ-204
    """
    raise NotImplementedError("Task 2.3")


async def accept_solution(
    db: AsyncSession, solution_id: int, actor_id: int,
) -> Solution:
    """Mark solution accepted. Previous accepted → proposed atomically.
    Raises: HTTPException(403) if not problem author. ForbiddenTransitionError if terminal.
    REQ-210
    """
    raise NotImplementedError("Task 2.3")


async def create_version(
    db: AsyncSession, solution_id: int, user_id: int, data: SolutionVersionCreate,
) -> SolutionVersion:
    """Append new version. Immutable — no in-place edits.
    Raises: HTTPException(403) if not solution author.
    REQ-206
    """
    raise NotImplementedError("Task 2.3")


# --- Voting service ---

async def toggle_upstar(
    db: AsyncSession, problem_id: int, user_id: int,
) -> tuple[bool, int]:
    """Toggle upstar. Returns (is_active, new_count).
    REQ-250, REQ-252
    """
    raise NotImplementedError("Task 2.4")


async def toggle_solution_upvote(
    db: AsyncSession, solution_id: int, user_id: int,
) -> tuple[bool, int]:
    """Toggle solution upvote. Returns (is_active, new_count).
    REQ-254, REQ-256
    """
    raise NotImplementedError("Task 2.4")


# --- Search service ---

async def search_problems(
    db: AsyncSession, query: str, sort: str, filters: dict, limit: int,
) -> list[dict]:
    """Full-text search with cross-entity indexing and ts_rank ranking.
    REQ-350, REQ-352, REQ-354
    """
    raise NotImplementedError("Task 3.1")


async def suggest_similar(
    db: AsyncSession, title: str, limit: int = 5,
) -> list[dict]:
    """Return up to 5 similar problems for duplicate prevention.
    REQ-362
    """
    raise NotImplementedError("Task 3.1")


# --- Notification service ---

async def generate_notification(
    db: AsyncSession, event_type: NotificationType,
    problem_id: int, solution_id: int | None, actor_id: int,
) -> list[Notification]:
    """Fan out notifications to qualifying watchers based on watch level routing.
    Excludes actor_id from recipients.
    REQ-310, REQ-312
    """
    raise NotImplementedError("Task 3.3")
```

**Key design decisions:**
- All functions are `async` with `AsyncSession` as first argument for testability.
- `toggle_*` return `(bool, int)` tuples so endpoints return new state without extra SELECT.
- `generate_notification` excludes `actor_id` internally — callers don't manage this.

---

## B.6: Auth Dependencies — Contract

FastAPI dependency functions for authentication and authorization.

**Tasks:** Task 1.3
**Requirements:** REQ-108, REQ-116, REQ-450
**Type:** Contract (exact — copied to implementation docs Phase 0)

```python
from __future__ import annotations

from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .database import get_db
from .models import User

_COOKIE_NAME = "session"


async def get_current_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    session: Annotated[str | None, Cookie(alias=_COOKIE_NAME)] = None,
) -> User:
    """Extract and validate JWT from HttpOnly cookie, return authenticated User.
    Auto-provisions user on first login. Supports DEV_AUTH_BYPASS.
    Raises: HTTPException(401) if absent, invalid, or expired.
    REQ-108, REQ-112, REQ-118, REQ-122
    """
    raise NotImplementedError("Task 1.3")


async def require_admin(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Verify admin role. Used on /api/admin/* endpoints.
    Raises: HTTPException(403) if not admin.
    REQ-450
    """
    raise NotImplementedError("Task 1.3")


async def require_owner_or_admin(
    resource_owner_id: int,
    user: Annotated[User, Depends(get_current_user)],
) -> None:
    """Assert requesting user is resource owner or admin.
    Raises: HTTPException(403) otherwise.
    REQ-116
    """
    raise NotImplementedError("Task 1.3")


# Convenience aliases
CurrentUser = Annotated[User, Depends(get_current_user)]
AdminUser = Annotated[User, Depends(require_admin)]
```

**Key design decisions:**
- Token from HttpOnly cookie (not Authorization header) to mitigate XSS.
- `require_owner_or_admin` takes `resource_owner_id` as plain parameter, not Depends.
- `CurrentUser` / `AdminUser` aliases keep endpoint signatures concise.

---

## B.7: Problem Status FSM — Pattern

Illustrates the state machine enforcement pattern using a transition table.

**Tasks:** Task 2.1
**Requirements:** REQ-156
**Type:** Pattern (illustrative — for implement-code only, never test agents)

```python
# Illustrative pattern — not the final implementation
from enum import StrEnum
from typing import Callable

class ProblemStatus(StrEnum):
    OPEN = "open"
    CLAIMED = "claimed"
    SOLVED = "solved"
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"

ActorCheck = Callable[["Actor", "Problem"], bool]

def _is_admin(actor, problem) -> bool:
    return actor.role == "admin"

def _is_any(_actor, _problem) -> bool:
    return True

# Transition table: (from, to) → permission predicate
TRANSITIONS: dict[tuple[ProblemStatus, ProblemStatus], ActorCheck] = {
    (ProblemStatus.OPEN,    ProblemStatus.CLAIMED):   _is_any,
    (ProblemStatus.OPEN,    ProblemStatus.DUPLICATE):  _is_any,
    (ProblemStatus.CLAIMED, ProblemStatus.OPEN):       _is_any,
    (ProblemStatus.CLAIMED, ProblemStatus.SOLVED):     _is_any,
    (ProblemStatus.SOLVED,  ProblemStatus.ACCEPTED):   _is_any,
}

def apply_transition(problem, to_status, actor) -> ProblemStatus:
    from_status = problem.status

    # Admin duplicate override takes precedence
    if to_status == ProblemStatus.DUPLICATE and _is_admin(actor, problem):
        problem.status = to_status
        return to_status

    key = (from_status, to_status)
    permission_check = TRANSITIONS.get(key)

    if permission_check is None:
        raise ForbiddenTransitionError(from_status, to_status)
    if not permission_check(actor, problem):
        raise ForbiddenTransitionError(from_status, to_status)

    problem.status = to_status
    return to_status
```

**Key design decisions:**
- Transition table replaces if/elif chains — adding a transition is a single dict entry.
- Permission predicates are composable and independently testable.
- Admin duplicate override resolved before table lookup.
- `apply_transition` is pure (no I/O) — unit-testable in isolation.

---

## B.8: Cursor-Based Pagination — Pattern

Illustrates keyset pagination with multi-sort support and pinned-above logic.

**Tasks:** Task 2.2
**Requirements:** REQ-168, REQ-170, REQ-174
**Type:** Pattern (illustrative — for implement-code only, never test agents)

```python
# Illustrative pattern — not the final implementation
import base64, json
from sqlalchemy import select, or_

SORT_CONFIG = {
    "top":       (Problem.upstar_count,     "desc"),
    "new":       (Problem.created_at,       "desc"),
    "active":    (Problem.last_activity_at, "desc"),
    "discussed": (Problem.comment_count,    "desc"),
}

def encode_cursor(sort_value, row_id: int) -> str:
    return base64.urlsafe_b64encode(
        json.dumps({"v": str(sort_value), "id": row_id}).encode()
    ).decode()

def decode_cursor(cursor: str) -> tuple:
    payload = json.loads(base64.urlsafe_b64decode(cursor.encode()))
    return payload["v"], int(payload["id"])

async def paginate_problems(db, sort_mode, limit, cursor=None, include_pinned=False):
    sort_col, direction = SORT_CONFIG[sort_mode]
    order_expr = sort_col.desc() if direction == "desc" else sort_col.asc()

    stmt = select(Problem).where(Problem.status != "duplicate")

    if cursor:
        sort_val, last_id = decode_cursor(cursor)
        if direction == "desc":
            stmt = stmt.where(or_(
                sort_col < sort_val,
                (sort_col == sort_val) & (Problem.id < last_id),
            ))

    stmt = stmt.order_by(order_expr, Problem.id.desc()).limit(limit + 1)
    rows = (await db.execute(stmt)).scalars().all()

    has_next = len(rows) > limit
    items = list(rows[:limit])
    next_cursor = encode_cursor(getattr(items[-1], sort_col.key), items[-1].id) if has_next else None

    if include_pinned and cursor is None:
        pinned = await _fetch_pinned(db)
        items = pinned + [p for p in items if not p.pinned]

    return CursorPage(items=items, has_next=has_next, next_cursor=next_cursor)
```

**Key design decisions:**
- Cursor encodes `(sort_key_value, id)` — stable under concurrent inserts, avoids O(n) OFFSET.
- `limit + 1` fetch for has-next detection without COUNT query.
- `SORT_CONFIG` dict makes adding sort modes a single-line change.
- Pinned problems spliced in only on first page, excluded from keyset flow.

---

## B.9: Watch-Level Notification Routing — Pattern

Illustrates the routing matrix and auto-watch upgrade pattern.

**Tasks:** Task 3.3
**Requirements:** REQ-310, REQ-312, REQ-304
**Type:** Pattern (illustrative — for implement-code only, never test agents)

```python
# Illustrative pattern — not the final implementation
from enum import StrEnum

class WatchLevel(StrEnum):
    ALL_ACTIVITY   = "all_activity"
    SOLUTIONS_ONLY = "solutions_only"
    STATUS_ONLY    = "status_only"
    NONE           = "none"

# Routing matrix: watch level → set of event types delivered
WATCH_ROUTING = {
    WatchLevel.ALL_ACTIVITY: frozenset(NotificationType),
    WatchLevel.SOLUTIONS_ONLY: frozenset({
        "new_solution", "solution_accepted", "solution_upvote_milestone",
    }),
    WatchLevel.STATUS_ONLY: frozenset({
        "problem_claimed", "claim_expired", "duplicate_flagged", "solution_accepted",
    }),
    WatchLevel.NONE: frozenset(),
}

LEVEL_RANK = [WatchLevel.NONE, WatchLevel.STATUS_ONLY,
              WatchLevel.SOLUTIONS_ONLY, WatchLevel.ALL_ACTIVITY]

async def ensure_auto_watch(db, user_id, problem_id, action):
    """Upsert watch; only upgrade if new level is broader."""
    desired = {"post": WatchLevel.ALL_ACTIVITY,
               "claim": WatchLevel.ALL_ACTIVITY,
               "solution": WatchLevel.ALL_ACTIVITY,
               "comment": WatchLevel.SOLUTIONS_ONLY}[action]
    existing = await _get_watch(db, user_id, problem_id)
    if existing is None:
        db.add(Watch(user_id=user_id, problem_id=problem_id, level=desired))
    elif LEVEL_RANK.index(desired) > LEVEL_RANK.index(existing.level):
        existing.level = desired
    await db.flush()

async def route_notification(db, problem_id, event_type, payload, exclude_user_id=None):
    """Fan out event to qualifying watchers."""
    watchers = await _get_watchers(db, problem_id)
    records = []
    for watch in watchers:
        if watch.user_id == exclude_user_id:
            continue
        if event_type not in WATCH_ROUTING[watch.level]:
            continue
        n = Notification(user_id=watch.user_id, type=event_type,
                         problem_id=problem_id, payload=payload)
        db.add(n)
        records.append(n)
    await db.flush()
    return records
```

**Key design decisions:**
- `WATCH_ROUTING` is a plain dict of frozensets — O(1) membership test, readable in one place.
- Rank-based upgrade prevents regression (posting gives all_activity, later solution doesn't downgrade).
- `route_notification` excludes actor so authors aren't notified of their own actions.
- Notifications flushed in same transaction — atomic with triggering event.

---

## B.10: WebSocket Notification Delivery — Pattern

Illustrates the in-process connection manager for real-time push.

**Tasks:** Task 3.4
**Requirements:** REQ-316
**Type:** Pattern (illustrative — for implement-code only, never test agents)

```python
# Illustrative pattern — not the final implementation
import json
from collections import defaultdict
from fastapi import WebSocket, WebSocketDisconnect

class ConnectionManager:
    """In-process WebSocket registry. One user may hold multiple tabs."""

    def __init__(self):
        self._connections: dict[int, set[WebSocket]] = defaultdict(set)

    async def connect(self, user_id: int, ws: WebSocket):
        await ws.accept()
        self._connections[user_id].add(ws)

    def disconnect(self, user_id: int, ws: WebSocket):
        self._connections[user_id].discard(ws)
        if not self._connections[user_id]:
            del self._connections[user_id]

    async def send_to_user(self, user_id: int, payload: dict):
        """Best-effort push. Dead connections pruned silently. No retry."""
        dead = []
        for ws in list(self._connections.get(user_id, [])):
            try:
                await ws.send_text(json.dumps(payload))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(user_id, ws)

manager = ConnectionManager()

@router.websocket("/ws/notifications")
async def notifications_ws(ws: WebSocket, current_user=Depends(get_current_user_ws)):
    await manager.connect(current_user.id, ws)
    try:
        while True:
            await ws.receive_text()  # keep-alive
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(current_user.id, ws)
```

**Key design decisions:**
- In-process singleton; can swap to Redis pub/sub for multi-process without changing interface.
- No retry on disconnect per spec — client re-fetches on reconnect.
- Multi-tab via `user_id → set[WebSocket]`.
- Keep-alive loop detects client-initiated closes.

---

## B.11: Full-Text Search with Cross-Entity Results — Pattern

Illustrates UNION ALL search across problems, solutions, and comments with deduplication.

**Tasks:** Task 3.1
**Requirements:** REQ-350, REQ-352, REQ-354, REQ-356
**Type:** Pattern (illustrative — for implement-code only, never test agents)

```python
# Illustrative pattern — not the final implementation
from sqlalchemy import select, func, literal, union_all

def _build_search_union(query_str):
    tsq = func.plainto_tsquery("english", query_str)

    # Branch 1: problems (GIN-indexed tsvector)
    p = select(
        Problem.id.label("problem_id"), Problem.title, Problem.status,
        Problem.upstar_count, Problem.created_at,
        func.ts_rank(Problem.search_vector, tsq).label("rank"),
        literal("problem").label("match_context"),
        func.ts_headline("english", Problem.title, tsq).label("headline"),
    ).where(Problem.search_vector.op("@@")(tsq))

    # Branch 2: solutions → parent problem
    s = select(
        Problem.id.label("problem_id"), Problem.title, Problem.status,
        Problem.upstar_count, Problem.created_at,
        func.ts_rank(func.to_tsvector("english", Solution.description), tsq).label("rank"),
        literal("solution").label("match_context"),
        func.ts_headline("english", Solution.description, tsq).label("headline"),
    ).join(Problem, Solution.problem_id == Problem.id
    ).where(func.to_tsvector("english", Solution.description).op("@@")(tsq))

    # Branch 3: comments → parent problem
    c = select(
        Problem.id.label("problem_id"), Problem.title, Problem.status,
        Problem.upstar_count, Problem.created_at,
        func.ts_rank(func.to_tsvector("english", Comment.body), tsq).label("rank"),
        literal("comment").label("match_context"),
        func.ts_headline("english", Comment.body, tsq).label("headline"),
    ).join(Problem, Comment.problem_id == Problem.id
    ).where(func.to_tsvector("english", Comment.body).op("@@")(tsq))

    return union_all(p, s, c)

async def search_problems(db, query_str, sort_mode, limit=20):
    union = _build_search_union(query_str).subquery("matches")
    # De-duplicate: highest-rank row per problem_id
    dedup = select(union).distinct(union.c.problem_id).order_by(
        union.c.problem_id, union.c.rank.desc()
    ).subquery("deduped")

    order = {"relevance": dedup.c.rank.desc(),
             "upstars": dedup.c.upstar_count.desc(),
             "newest": dedup.c.created_at.desc()}[sort_mode]

    rows = (await db.execute(select(dedup).order_by(order).limit(limit))).mappings().all()
    return rows
```

**Key design decisions:**
- UNION ALL in single round-trip; each branch ranks independently, outer query deduplicates by problem_id.
- `match_context` literal per branch tells UI where the match occurred.
- `plainto_tsquery` (not `to_tsquery`) prevents syntax errors from user input.
- `ts_headline` computed per branch on the correct source text.

---

## B.12: JWT Cookie Auth Middleware — Pattern

Illustrates the cookie-based JWT auth flow with auto-provisioning and dev bypass.

**Tasks:** Task 1.3
**Requirements:** REQ-108, REQ-110, REQ-112, REQ-122
**Type:** Pattern (illustrative — for implement-code only, never test agents)

```python
# Illustrative pattern — not the final implementation
from fastapi import Depends, Request, HTTPException, status
from jose import JWTError, ExpiredSignatureError, jwt

def _decode_token(token, config):
    try:
        data = jwt.decode(token, config.jwt_secret, algorithms=["HS256"])
        return TokenPayload(**data)
    except ExpiredSignatureError:
        raise  # caller handles refresh
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

async def _auto_provision(db, payload):
    """Create user on first OIDC login; update name/email on subsequent."""
    user = await db.scalar(select(User).where(User.external_sub == payload.sub))
    if user is None:
        user = User(external_sub=payload.sub, email=payload.email,
                    display_name=payload.name, role="user")
        db.add(user)
        await db.flush()
    else:
        user.email = payload.email
        user.display_name = payload.name
    return user

async def get_current_user(request, db=Depends(get_db), config=Depends(get_config)):
    # Dev bypass
    if config.dev_auth_bypass:
        return await db.get(User, 1)

    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = _decode_token(token, config)
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired",
                            headers={"X-Token-Expired": "true"})
    return await _auto_provision(db, payload)
```

**Key design decisions:**
- Token from HttpOnly cookie, not Authorization header — prevents JS access.
- `ExpiredSignatureError` caught separately with `X-Token-Expired` header for client refresh logic.
- Auto-provisioning on every request keeps email/name current.
- Dev bypass guarded by config flag — returns 404 in production.

---

## B.13: Idempotent Toggle Voting — Pattern

Illustrates the check-then-act toggle with atomic count updates.

**Tasks:** Task 2.4
**Requirements:** REQ-250, REQ-252, REQ-254, REQ-256
**Type:** Pattern (illustrative — for implement-code only, never test agents)

```python
# Illustrative pattern — not the final implementation
from sqlalchemy import select, delete, func, update
from sqlalchemy.exc import IntegrityError

async def toggle_upstar(db, user_id, problem_id):
    existing = await db.scalar(
        select(Upstar).where(
            Upstar.user_id == user_id, Upstar.problem_id == problem_id
        )
    )
    if existing:
        await db.execute(delete(Upstar).where(
            Upstar.user_id == user_id, Upstar.problem_id == problem_id
        ))
        count = await _decrement_count(db, Problem, problem_id, "upstar_count")
        return (False, count)

    try:
        db.add(Upstar(user_id=user_id, problem_id=problem_id))
        await db.flush()
    except IntegrityError:
        await db.rollback()
        count = await _read_count(db, Problem, problem_id, "upstar_count")
        return (True, count)

    count = await _increment_count(db, Problem, problem_id, "upstar_count")
    return (True, count)

async def _increment_count(db, model, row_id, col):
    result = await db.execute(
        update(model).where(model.id == row_id)
        .values({col: getattr(model, col) + 1})
        .returning(getattr(model, col))
    )
    return result.scalar_one()

async def _decrement_count(db, model, row_id, col):
    result = await db.execute(
        update(model).where(model.id == row_id)
        .values({col: func.greatest(getattr(model, col) - 1, 0)})
        .returning(getattr(model, col))
    )
    return result.scalar_one()
```

**Key design decisions:**
- Single endpoint handles add/remove — no client state tracking needed.
- `UPDATE ... RETURNING` is atomic at DB level — no lost-update race.
- UNIQUE constraint as safety net; `IntegrityError` catches concurrent-insert race.
- `func.greatest(..., 0)` prevents negative counts from data inconsistency.
