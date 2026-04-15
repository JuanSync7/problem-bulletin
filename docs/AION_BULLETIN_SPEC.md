# Aion Bulletin — Requirements Specification

| Version | Date | Author | Status |
|---------|------|--------|--------|
| 1.0 | 2026-04-14 | Engineering | Draft |

---

## 1. Scope & Definitions

### 1.1 Problem Statement
Information is scattered across tools at the company — no single place for visibility. Key engineers miss problems they could help with. People don't speak up or don't know where to post. There is no recognition for people who solve problems. Engineers don't use GitHub directly, so a friendly web UI is required. This is a bottom-up discovery tool (anyone surfaces a problem → community validates → someone volunteers), NOT top-down task management.

### 1.2 Scope
**Entry point:** User accesses the web application via browser (authenticated via Microsoft 365 OAuth or magic link email).
**Exit point:** Problems are posted, validated via upstars, claimed, solved with git-linked solutions, and accepted. Notifications delivered via in-app, Teams webhook, and email digest.

**In scope for this spec:**
- Problem posting, upstarring, claiming, solving lifecycle
- Solution submission with git link tracking and versioning
- Threaded comments on problems and solutions
- Anonymous posting
- File attachments (screenshots, logs, documents)
- Full-text search with similar-problem suggestions
- Notification system (in-app WebSocket, Teams, email digest) with configurable watches
- Leaderboard and user recognition
- Admin panel (categories, tags, users, flagged content)
- Authentication (Azure AD OAuth + magic link)
- Idempotency for all API operations
- Edit history for problems and comments
- Pinned problems
- Duplicate problem detection and flagging
- Link previews (Open Graph meta tags)
- Landing page with bulletin board theme

**Out of scope for this spec:**
- Wiki/knowledge base (deferred, not v1)
- AI-powered semantic search / RAG (v2 — placeholder page only in v1)
- Git workflow management (no branch creation, merging, or repo enforcement)
- Native mobile app (responsive web only)
- Real-time git sync or polling
- Task queue (Celery/Redis — not needed at this scale)

**Out of scope for this project:**
- Jira replacement or top-down task management
- Payment/bounty system
- External-facing public access

### 1.3 Terminology

| Term | Definition |
|------|-----------|
| Problem | A user-submitted issue or challenge posted to the bulletin board for community visibility |
| Upstar | A vote indicating agreement that a problem is real and worth solving (distinct from solution upvotes) |
| Solution | A first-class proposed fix for a problem, with description, optional git link, and version history |
| Solution Version | An iteration of a solution — each update creates a new version (v1, v2, v3...) rather than overwriting |
| Claim | A signal that a user is actively working on a problem — multiple claims allowed per problem |
| Primary Claimer | The first user to claim a problem — highlighted on the problem card |
| Watch | A subscription to notifications on a specific problem, with configurable granularity |
| Category | An admin-managed top-level classification (e.g., RTL Design, Verification) — required on every problem |
| Tag | A freeform user-created label for specificity — optional, with autocomplete |
| Anonymous Post | Content posted by an authenticated user but displayed as "Anonymous" — author_id stored for admin moderation |
| Accepted Solution | A solution marked as the recommended fix by the problem poster or an admin |
| Pinned Problem | A problem promoted to the top of the feed by an admin — max 3 at a time |

### 1.4 Requirement Priority Levels

This specification uses RFC 2119 priority levels:

| Level | Meaning |
|-------|---------|
| MUST | Absolute requirement — the system is non-conformant without it |
| SHOULD | Recommended — may be omitted only with documented justification |
| MAY | Optional — included at implementor's discretion |

### 1.5 Requirement Format

Requirements use the REQ-xxx identifier scheme, grouped by section:

| Section | ID Range | Domain |
|---------|----------|--------|
| Section 3 | REQ-100–REQ-149 | Authentication & Authorization |
| Section 4 | REQ-150–REQ-199 | Problems & Feed |
| Section 5 | REQ-200–REQ-249 | Solutions & Versioning |
| Section 6 | REQ-250–REQ-299 | Voting, Comments & Engagement |
| Section 7 | REQ-300–REQ-349 | Notifications & Watches |
| Section 8 | REQ-350–REQ-399 | Search & Discovery |
| Section 9 | REQ-400–REQ-449 | File Attachments |
| Section 10 | REQ-450–REQ-499 | Administration |
| Section 11 | REQ-500–REQ-549 | UI/UX & Frontend |
| Section 12 | REQ-900–REQ-999 | Non-Functional Requirements |

### 1.6 Assumptions & Constraints

| # | Assumption / Constraint |
|---|------------------------|
| A1 | The company uses Microsoft 365 — Azure AD is available as the identity provider |
| A2 | ~100 concurrent users initially, scaling to 500+ |
| A3 | Deployment is on-premises using Podman Compose (rootless containers) |
| A4 | An internal SMTP server is available for magic link emails |
| A5 | Engineers have mixed technical comfort levels — many do not use git/GitHub directly |
| A6 | A Microsoft Teams incoming webhook can be configured for notifications |
| A7 | The server has at minimum 4 CPU, 8 GB RAM, 50 GB disk |
| A8 | TLS certificates are available from the internal CA or self-signed |
| C1 | No external cloud services — all data stays on-premises |
| C2 | No dependency on GitHub accounts for end users |
| C3 | Single-tenant Azure AD restriction — only org members can authenticate |

### 1.7 Design Principles

| Principle | Description |
|-----------|-------------|
| Low-friction first | Every design decision prioritizes minimizing barriers to participation — fewer required fields, one-click auth, anonymous option |
| Bottom-up discovery | Problems surface from any team member, not assigned top-down — the community validates importance through upstars |
| Git as a link, not a backbone | The app tracks git references but does not manage git workflows — repos govern themselves |
| Separation of voting axes | Problem validation (upstars) and solution quality (upvotes) are independent voting systems |
| Idempotency by default | Every API endpoint is safe to retry — toggle operations, unique constraints, and idempotency keys prevent duplicate state |

---

## 2. System Overview

### 2.1 Architecture Diagram

The system is a three-tier web application deployed via Podman Compose on-premises.

```
┌──────────────────────────────────────────────────────────────────┐
│                          CLIENT                                   │
│  React 18 + Vite + TypeScript SPA                                │
│  Served as static build by NGINX                                  │
│  Communicates via REST API + WebSocket                            │
└───────────────────────────┬──────────────────────────────────────┘
                            │ HTTPS (port 443)
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│                          NGINX                                    │
│  - Serves frontend static build (React/Vite)                     │
│  - Reverse proxies /api/* → FastAPI (port 8000)                  │
│  - Serves /attachments/* directly from volume                    │
│  - TLS termination (internal CA or self-signed)                  │
│  - Rate limiting: 30 req/s API, 5 req/s auth                    │
│  - WebSocket proxy for /api/ws/*                                 │
│  - Open Graph meta tag injection for bot User-Agents             │
│  - Gzip compression                                              │
├──────────────────────────────────────────────────────────────────┤
│                          FastAPI                                  │
│  Python 3.11+ | SQLAlchemy 2.0 + asyncpg | Pydantic v2           │
│  - REST API endpoints (problems, solutions, comments, etc.)      │
│  - Auth: Azure AD OAuth (authlib) + magic link + JWT (python-jose)│
│  - WebSocket endpoint for real-time notifications                 │
│  - Business logic layer (services/)                               │
│  - Structured logging (structlog, JSON, correlation IDs)          │
│  Port: 8000 (internal only, not exposed to clients)              │
├──────────────────────────────────────────────────────────────────┤
│                       PostgreSQL 16                               │
│  - All application data (users, problems, solutions, etc.)       │
│  - Full-text search (tsvector + GIN indexes)                     │
│  - JSONB for notification preferences and flexible metadata       │
│  - Schema migrations via Alembic                                  │
│  Port: 5432 (internal only)                                      │
├──────────────────────────────────────────────────────────────────┤
│                    File System Volume                              │
│  - /data/attachments/ — uploaded files (screenshots, logs, docs) │
│  - Shared between NGINX (read-only) and FastAPI (read-write)     │
│  - Organized: /data/attachments/{year}/{month}/{uuid}_{filename} │
└──────────────────────────────────────────────────────────────────┘

External Integrations:
  ┌───────────────┐    ┌────────────────┐    ┌──────────────┐
  │  Azure AD     │    │ Teams Webhook  │    │ SMTP Server  │
  │  (OAuth/OIDC) │    │ (notifications)│    │ (magic links)│
  └───────────────┘    └────────────────┘    └──────────────┘
```

### 2.2 Data Flow Summary

| Flow | Source | Destination | Protocol | Description |
|------|--------|-------------|----------|-------------|
| User authentication (primary) | Browser | Azure AD → FastAPI | HTTPS (OIDC) | OAuth2 authorization code flow; FastAPI issues JWT on callback |
| User authentication (secondary) | Browser | FastAPI → SMTP → Browser | HTTPS + SMTP | Magic link: FastAPI generates signed JWT URL, sends via SMTP, user clicks to auth |
| Problem lifecycle | Browser | FastAPI → PostgreSQL | HTTPS → SQL | Create, update, upstar, claim, flag duplicate, pin/unpin |
| Solution lifecycle | Browser | FastAPI → PostgreSQL | HTTPS → SQL | Submit solution, add version, upvote, accept |
| Comments | Browser | FastAPI → PostgreSQL | HTTPS → SQL | Create, delete threaded comments on problems or solutions |
| File upload | Browser | FastAPI → File System | HTTPS (multipart) | Upload stored to /data/attachments, metadata in PostgreSQL |
| File download | Browser | NGINX → File System | HTTPS | NGINX serves directly from volume, bypassing FastAPI |
| Full-text search | Browser | FastAPI → PostgreSQL | HTTPS → SQL | tsvector query with ts_rank scoring, GIN index |
| Real-time notifications | FastAPI | Browser | WebSocket | Push notification events to connected clients |
| Teams notifications | FastAPI | Teams Webhook | HTTPS POST | JSON payload to Teams Incoming Webhook connector |
| Link preview | Teams/Slack bot | NGINX → FastAPI | HTTPS | Bot User-Agent detected, returns HTML with OG meta tags |
| Database backup | Cron (host) | PostgreSQL → Backup volume | pg_dump | Daily automated backup, 7-day retention |

### 2.3 Tech Stack Summary

| Layer | Technology | Version |
|-------|-----------|---------|
| Frontend | React + Vite + TypeScript | React 18 |
| Reverse Proxy | NGINX | Alpine |
| API Server | FastAPI (Python) | 3.11+ |
| ORM | SQLAlchemy + asyncpg | 2.0 |
| Database | PostgreSQL | 16 |
| Auth | authlib + python-jose | Latest |
| Migrations | Alembic | Latest |
| Validation | Pydantic | v2 |
| Containerization | Podman Compose | Rootless |
| Logging | structlog | JSON output |

---

## 3. Authentication & Authorization

> **REQ-100** | Priority: MUST
>
> **Description:** The system shall authenticate users via Microsoft 365 / Azure AD using the OpenID Connect (OIDC) authorization code flow, implemented through authlib. Initiating login shall redirect the user to the Azure AD authorization endpoint via `POST /api/auth/login`, and the OAuth callback shall be handled at `GET /api/auth/callback`.
>
> **Rationale:** Azure AD is the canonical identity provider for the organization. Using OIDC over a managed provider eliminates credential storage, enforces MFA policies set by IT, and ties user identity to existing directory membership.
>
> **Acceptance Criteria:** A user navigating to the login page is redirected to the Microsoft login prompt. After successful Azure AD authentication, the callback endpoint issues session tokens and redirects the user to the application. The full round-trip completes without error for any valid tenant member.

---

> **REQ-102** | Priority: MUST
>
> **Description:** The system shall restrict Azure AD authentication to the company's single Azure AD tenant. The App Registration shall be configured as single-tenant, and the callback handler shall reject tokens whose `tid` claim does not match the configured `AZURE_TENANT_ID` environment variable.
>
> **Rationale:** Without tenant restriction, any Microsoft account holder could authenticate. The bulletin board contains internal engineering discussions that must not be accessible to external parties.
>
> **Acceptance Criteria:** An account belonging to the correct tenant successfully authenticates. An account from a different Microsoft tenant is rejected with HTTP 401 at the callback endpoint, and no session is issued.

---

> **REQ-104** | Priority: MUST
>
> **Description:** The system shall support magic link authentication as a secondary method. A user shall submit their company email address to `POST /api/auth/magic-link`; the backend shall generate a short-lived signed JWT, embed it in a login URL, and deliver it via SMTP. The recipient clicks the link, which is verified at `GET /api/auth/magic-link/verify`, and a session is issued on success.
>
> **Rationale:** Magic links provide a fallback path for engineers who encounter Azure AD SSO issues without introducing passwords.
>
> **Acceptance Criteria:** Submitting a valid company email address results in exactly one email delivered containing a login link. Clicking the link within its validity window authenticates the user and establishes a session. Submitting a non-company email address returns HTTP 400 or 422 with no email sent.

---

> **REQ-106** | Priority: MUST
>
> **Description:** Magic link tokens shall expire after a maximum of 15 minutes from issuance and shall be single-use. The verify endpoint shall reject any token that is expired or has already been consumed, returning HTTP 401 in both cases.
>
> **Rationale:** Long-lived or reusable magic links in email inboxes represent a persistent credential. Bounding validity and enforcing single-use limits the window of exploitation if an email is forwarded or an inbox is compromised.
>
> **Acceptance Criteria:** A link used within 15 minutes succeeds on first use and returns HTTP 401 on a second attempt with the same token. A link used after 15 minutes returns HTTP 401 regardless of prior use. Server logs record the rejection reason.

---

> **REQ-108** | Priority: MUST
>
> **Description:** Upon successful authentication by either method, the system shall issue two JWTs delivered as HttpOnly, Secure, SameSite=Strict cookies: an access token with a 15-minute expiry and a refresh token with a 7-day expiry. No tokens shall be returned in the response body or exposed in URLs.
>
> **Rationale:** HttpOnly cookies are inaccessible to JavaScript, eliminating XSS-based token theft. Secure and SameSite=Strict attributes prevent transmission over plaintext connections and mitigate CSRF.
>
> **Acceptance Criteria:** After login, browser DevTools show both tokens set as cookies with HttpOnly, Secure, and SameSite=Strict attributes. No token value appears in the JSON response body or in the redirect URL.

---

> **REQ-110** | Priority: MUST
>
> **Description:** The system shall provide a token refresh endpoint at `POST /api/auth/refresh`. When a request is made with a valid, unexpired refresh token cookie, the endpoint shall issue a new access token cookie (15-minute expiry). The refresh token shall retain its original expiry until re-authentication is required.
>
> **Rationale:** A 15-minute access token window limits the blast radius of token leakage but would require re-authentication every 15 minutes without a refresh mechanism.
>
> **Acceptance Criteria:** After an access token expires, calling `POST /api/auth/refresh` with a valid refresh token cookie returns HTTP 200 and sets a new access token cookie. Calling the endpoint with an expired or absent refresh token returns HTTP 401.

---

> **REQ-112** | Priority: MUST
>
> **Description:** The system shall auto-provision a user record in PostgreSQL on first successful authentication via either method. The provisioned record shall capture at minimum: user ID, display name, email address, role (defaulting to `User`), and first-login timestamp. Subsequent logins shall update the last-login timestamp but shall not overwrite role assignments.
>
> **Rationale:** The application requires a persistent user identity for authorship, permissions, and audit trails. Provisioning must happen at runtime on first contact since there is no pre-registration step.
>
> **Acceptance Criteria:** After a user's first login, a corresponding row exists in the `users` table with correct display name, email, role set to `User`, and a non-null `first_login_at`. A second login does not change the role. No duplicate user records are created under concurrent first-login conditions.

---

> **REQ-114** | Priority: MUST
>
> **Description:** The system shall enforce a two-role model: `User` (default) and `Admin`. All authenticated users shall hold the `User` role at minimum. The `Admin` role shall be assigned manually by an existing admin via the admin interface; there is no self-service elevation path.
>
> **Rationale:** A two-role model is the minimum necessary structure for content ownership and board maintenance without introducing excessive complexity.
>
> **Acceptance Criteria:** A newly provisioned user has role `User`. An admin can promote a user to `Admin` via the admin interface. There is no API endpoint or UI affordance that allows a non-admin user to change their own or another user's role.

---

> **REQ-116** | Priority: MUST
>
> **Description:** The system shall enforce the following permission rules on content operations, evaluated server-side on every request:
> - **Accept a solution:** problem poster or `Admin`
> - **Edit or delete a problem:** problem poster or `Admin`
> - **Delete a comment:** comment author or `Admin`
> - **All other write operations** (post problem, post comment, vote): any authenticated user
> - **All read operations:** any authenticated user
>
> **Rationale:** Content ownership permissions protect engineers from having their problem statements altered or resolved without consent while still allowing admins to maintain board hygiene.
>
> **Acceptance Criteria:** A `User` attempting to edit another user's problem receives HTTP 403. An `Admin` performing the same operation receives HTTP 200. The problem poster performing operations on their own content receives HTTP 200. All permission checks are enforced in the API layer.

---

> **REQ-118** | Priority: MUST
>
> **Description:** The system shall expose a `GET /api/auth/me` endpoint that returns the authenticated user's profile (display name, email, role) when called with a valid access token cookie. Unauthenticated requests shall receive HTTP 401.
>
> **Rationale:** The frontend requires a reliable mechanism to determine the current user's identity and role in order to conditionally render permission-gated UI elements.
>
> **Acceptance Criteria:** A request to `/api/auth/me` with a valid access token returns HTTP 200 with a JSON body containing `display_name`, `email`, and `role`. A request with no cookie or an expired token returns HTTP 401.

---

> **REQ-120** | Priority: MUST
>
> **Description:** The system shall provide a logout mechanism that clears both the access token and refresh token cookies server-side by overwriting them with expired Set-Cookie directives.
>
> **Rationale:** Relying on the client to delete cookies is not enforceable. Server-initiated expiry ensures the session is terminated.
>
> **Acceptance Criteria:** After calling the logout endpoint, both token cookies are absent from subsequent requests. A refresh token that was valid before logout returns HTTP 401 when submitted to `POST /api/auth/refresh`. The user is redirected to the login page.

---

> **REQ-122** | Priority: MUST
>
> **Description:** The system shall provide a development authentication bypass, enabled exclusively when the environment variable `DEV_AUTH_BYPASS=true` is set. When active, `POST /api/auth/dev-login` shall issue a session without Azure AD or magic link verification. This endpoint shall return HTTP 404 when `DEV_AUTH_BYPASS` is absent or set to any value other than `true`.
>
> **Rationale:** Local development and automated testing require the ability to simulate authenticated sessions without a live Azure AD connection.
>
> **Acceptance Criteria:** With `DEV_AUTH_BYPASS=true`, `POST /api/auth/dev-login` returns HTTP 200 and issues session cookies. With `DEV_AUTH_BYPASS` unset or `false`, the endpoint returns HTTP 404. A startup assertion confirms `DEV_AUTH_BYPASS` is not `true` when `ENVIRONMENT=production`, halting startup if violated.

---

> **REQ-124** | Priority: MUST
>
> **Description:** The Azure AD App Registration shall be configured with the minimum required permissions: `openid`, `profile`, and `email` scopes. No additional permissions shall be requested unless explicitly required by a future feature.
>
> **Rationale:** Principle of least privilege applied to the OAuth client. Requesting unnecessary scopes increases the blast radius of a compromised client secret.
>
> **Acceptance Criteria:** The App Registration shows only `openid`, `profile`, and `email` under configured permissions, all with admin consent granted. The OIDC token request does not include any additional scope strings.

---

> **REQ-126** | Priority: SHOULD
>
> **Description:** The system should record an audit log entry for each authentication event, including: event type, timestamp, user identifier, source IP address, and outcome (success or failure with reason code).
>
> **Rationale:** Authentication audit trails are essential for incident response and detecting credential abuse.
>
> **Acceptance Criteria:** After each authentication event, a corresponding structured log entry exists with all specified fields populated. Failed authentication attempts are logged with a non-null `failure_reason`.

---

> **REQ-128** | Priority: SHOULD
>
> **Description:** The system should enforce a rate limit on the `POST /api/auth/magic-link` endpoint, allowing no more than 5 requests per email address per 10-minute window. Requests exceeding this limit shall return HTTP 429 with a `Retry-After` header.
>
> **Rationale:** Without rate limiting, the magic link endpoint can be used to spam a target's inbox or enumerate valid company email addresses.
>
> **Acceptance Criteria:** Submitting 5 magic link requests for the same email within 10 minutes succeeds. The 6th request returns HTTP 429. After the window resets, a new request succeeds.

---

## 4. Problems & Feed

> **REQ-150** | Priority: MUST
>
> **Description:** The system shall allow any authenticated user to submit a new problem by providing a title, description, and category. Tags are optional. Unauthenticated users shall not be permitted to post.
>
> **Rationale:** Problem submission is the core input action of the board. Authentication gates ensure accountability and enable moderation.
>
> **Acceptance Criteria:** An authenticated user submitting a valid title, description, and category receives a 201 response with the created problem. An unauthenticated request returns 401.

---

> **REQ-152** | Priority: MUST
>
> **Description:** The system shall enforce the following field constraints on problem submission: title must be between 5 and 200 characters (inclusive); description must be at least 10 characters; category must reference a valid, existing category ID. Any violation shall return a 422 response with field-level error details.
>
> **Rationale:** Minimum lengths prevent low-quality or empty submissions. The upper bound on title preserves feed readability. Category validation maintains referential integrity.
>
> **Acceptance Criteria:** Submitting a title of 4 characters, a description of 9 characters, or a non-existent category ID each independently returns 422 with the offending field identified. Valid boundary values (title = 5, title = 200, description = 10) are accepted.

---

> **REQ-154** | Priority: MUST
>
> **Description:** The system shall support anonymous problem posting. When a user submits with the "Post anonymously" flag set to true, the problem's display author shall render as "Anonymous" to all non-admin users. The authenticated user's `author_id` shall be stored in the database and remain visible to administrators.
>
> **Rationale:** Anonymity lowers the barrier for surfacing sensitive or politically difficult problems. Retaining `author_id` preserves the ability to moderate abuse.
>
> **Acceptance Criteria:** A problem posted with `is_anonymous: true` returns "Anonymous" in the author field for non-admin users. An admin-authenticated request exposes the real `author_id`.

---

> **REQ-156** | Priority: MUST
>
> **Description:** The system shall maintain problem status as a finite state machine with the following permitted transitions: Open → Claimed (any authenticated user), Open → Duplicate (poster or admin), Claimed → Open (all claims removed or expiry), Claimed → Solved (accepted solution submitted), Solved → Accepted (poster or admin), Any → Duplicate (admin only). Any attempt to perform a forbidden transition shall be rejected with 409.
>
> **Rationale:** Explicit state transitions enforce workflow integrity and prevent problems from entering inconsistent states.
>
> **Acceptance Criteria:** Each permitted transition succeeds when triggered by an authorized actor. Each forbidden transition returns 409. Unauthorized actors attempting permitted transitions receive 403.

---

> **REQ-158** | Priority: MUST
>
> **Description:** The system shall allow multiple authenticated users to claim a single problem simultaneously. The first user to claim shall be designated the primary claimer and visually distinguished. Subsequent claimers shall be recorded as secondary claimers. Claiming is idempotent: a user re-claiming a problem they already hold returns 200 without creating a duplicate claim record.
>
> **Rationale:** Collaborative claiming supports parallelism on hard problems. Primary claimer designation signals who took initiative. Idempotency prevents duplicate rows.
>
> **Acceptance Criteria:** Two users claiming the same problem both appear in the claims list; the earlier claimer is flagged as primary. A second claim from the same user returns 200 without incrementing the count. The primary claimer designation does not change when secondary claims are added.

---

> **REQ-160** | Priority: MUST
>
> **Description:** The system shall automatically expire claims on a problem if no activity is recorded for 14 consecutive days. Upon expiry, all claims shall be removed. If and only if all claims are removed — whether by expiry or manual unclaim — the problem status shall revert to Open.
>
> **Rationale:** Auto-expiry prevents problems from being indefinitely blocked by inactive claimers.
>
> **Acceptance Criteria:** A scheduled job removes claims on problems with no activity for ≥ 14 days and sets status to Open. A problem with two claimers where one unclaims remains in Claimed status. A problem with one claimer who unclaims reverts to Open immediately.

---

> **REQ-162** | Priority: MUST
>
> **Description:** The system shall support duplicate problem designation through a two-step confirmation workflow. Any user may suggest a problem is a duplicate by calling `POST /api/problems/{id}/duplicate` with a `duplicate_of_id`. The designation is confirmed only when the poster or admin approves. Once confirmed, the problem is excluded from the default feed and displays "Duplicate of: [Problem #N]".
>
> **Rationale:** Community-sourced duplicate detection keeps the feed clean without requiring admin involvement for every case. Confirmation prevents malicious suppression.
>
> **Acceptance Criteria:** A duplicate suggestion does not immediately change status. After confirmation, the problem status becomes Duplicate and `duplicate_of_id` is persisted. The default feed excludes it. The problem detail page renders a "Duplicate of" notice with a working link.

---

> **REQ-164** | Priority: MUST
>
> **Description:** The system shall allow administrators to pin up to 3 problems at a time. Pinned problems appear above the normal feed with a visual highlight. Attempting to pin a fourth returns 409. Only administrators may pin or unpin.
>
> **Rationale:** Pinning enables admins to surface high-priority or time-sensitive problems regardless of organic ranking. The cap prevents abuse.
>
> **Acceptance Criteria:** An admin pinning a problem sets `is_pinned = true` and the problem appears at the top of the feed. A non-admin pin request returns 403. A fourth pin attempt returns 409. Unpinning clears pin fields and removes from the pinned section.

---

> **REQ-166** | Priority: MUST
>
> **Description:** The system shall allow the original poster to edit a problem's title and description. Every edit shall create an immutable record in the `edit_history` table. The detail view shall display "(edited N ago)" when edit history exists; clicking this label opens the full history.
>
> **Rationale:** Edits correct mistakes and add context, but visible and auditable history prevents retroactive rewriting that invalidates existing claims or solutions.
>
> **Acceptance Criteria:** A poster editing title or description receives 200. The `edit_history` table gains one row per edit. The detail view shows "(edited Xh ago)" after the first edit. A non-poster, non-admin PATCH returns 403.

---

> **REQ-168** | Priority: MUST
>
> **Description:** The system shall present the problems feed as a cursor-based paginated list. Default page size shall be 25; clients may request up to 100. The response includes a `next_cursor` value when additional results exist and null when the final page is reached.
>
> **Rationale:** Cursor-based pagination provides stable results under concurrent inserts and is more performant than offset pagination.
>
> **Acceptance Criteria:** GET /api/problems returns at most 25 items and a `next_cursor` by default. Passing that cursor returns the next non-overlapping page. Requesting `limit=101` returns 422.

---

> **REQ-170** | Priority: MUST
>
> **Description:** The system shall support feed sort modes selectable via a `sort` query parameter: `top` (most upstars), `new` (creation date, descending), `active` (most recent activity), `discussed` (comment count). Default is `new`.
>
> **Rationale:** Different users have different discovery needs — newcomers benefit from `new`, stakeholders seek `top`, responders prefer `active`.
>
> **Acceptance Criteria:** Each sort mode returns results in the documented order. An unsupported `sort` value returns 422. Omitting `sort` produces the same result as `sort=new`.

---

> **REQ-172** | Priority: MUST
>
> **Description:** The system shall support feed filter parameters combinable with any sort mode: `status` (one or more of: open, claimed, solved, accepted), `category` (category ID), `mine` (boolean), `unclaimed` (boolean). Duplicate-status problems are excluded unless `status=duplicate` is explicitly requested.
>
> **Rationale:** Filters allow users to scope the feed to actionable or personally relevant subsets.
>
> **Acceptance Criteria:** Each filter applied independently returns only matching problems. Combined filters apply as AND conditions. Default feed excludes Duplicates. `status=duplicate` includes them.

---

> **REQ-174** | Priority: MUST
>
> **Description:** Pinned problems shall render above the first cursor page in all sort and filter contexts, without consuming pagination slots. The first page may return up to 28 items (25 paginated + 3 pinned).
>
> **Rationale:** Pinned items must remain visible regardless of sort order. Excluding them from pagination prevents the effective page size from shrinking.
>
> **Acceptance Criteria:** The first page includes up to 3 pinned problems before paginated results. Subsequent pages do not repeat pinned problems. Pinned problems appear even when a `status` filter would otherwise exclude them.

---

> **REQ-176** | Priority: SHOULD
>
> **Description:** The system shall accept an `Idempotency-Key` header on problem creation. If a request matches a key from the past 24 hours, the system shall return the original response without creating a duplicate.
>
> **Rationale:** Network retries without idempotency protection result in duplicate problems.
>
> **Acceptance Criteria:** Two identical POST requests with the same key within 24 hours result in exactly one problem. After 24 hours, the same key may be reused. Requests without a key are processed normally.

---

> **REQ-178** | Priority: SHOULD
>
> **Description:** The system shall support full-text search at `GET /api/problems/search?q=` matching against problem titles and descriptions, returning results in relevance order with duplicate-exclusion default.
>
> **Rationale:** Users who know a problem exists but cannot locate it in the feed need a direct search path.
>
> **Acceptance Criteria:** A search for a word present in a title or description returns that problem. An absent term returns empty results. Duplicate problems are excluded unless `status=duplicate` is passed.

---

> **REQ-180** | Priority: SHOULD
>
> **Description:** The system shall record and expose an `activity_at` timestamp on each problem, updated on: new claim, claim removal, new comment, upstar action, status transition, or edit. This field is used for the `active` sort mode.
>
> **Rationale:** A dedicated activity timestamp decouples user activity from system-triggered `updated_at` changes.
>
> **Acceptance Criteria:** Each listed event updates `activity_at`. Background jobs do not update `activity_at`. The `active` sort mode orders by `activity_at` descending.

---

> **REQ-182** | Priority: MAY
>
> **Description:** The system may allow users to filter the feed to only problems they have personally upstarred, using a `starred` boolean filter parameter.
>
> **Rationale:** Users who upstar problems to track them later need a retrieval mechanism.
>
> **Acceptance Criteria:** `starred=true` returns only problems the user has upstarred. Results respect cursor-based pagination and all sort modes.

---

## 5. Solutions & Versioning

> **REQ-200** | Priority: MUST
>
> **Description:** The system shall allow one or more solutions to be submitted against any problem, treating each solution as a first-class object with its own author, description, upvote count, status, version history, and anonymity flag.
>
> **Rationale:** Problems frequently have competing or complementary resolutions; reducing solutions to comments would lose structured metadata needed for triage and decision-making.
>
> **Acceptance Criteria:** Each solution record exposes: `author`, `description`, `git_link`, `status`, `upvote_count`, `is_anonymous`, and `created_at`. Submitting two solutions to the same problem creates two distinct records with independent vote counts.

---

> **REQ-202** | Priority: MUST
>
> **Description:** The system shall persist every solution in a `solutions` table and expose it via `GET /api/problems/{id}/solutions`, returning the full list of solutions for the given problem.
>
> **Rationale:** A stable, problem-scoped list endpoint is the authoritative read path for clients rendering the solution panel.
>
> **Acceptance Criteria:** `GET /api/problems/{id}/solutions` returns HTTP 200 with an array of solution objects for a problem that has solutions, and an empty array for a problem with none.

---

> **REQ-204** | Priority: MUST
>
> **Description:** The system shall accept a `git_link` field on solution creation and on new version submission; the field shall be treated as a freeform URL string with no enforcement of repository host, branch, commit, or pull-request format. The field is optional.
>
> **Rationale:** Solutions span unrelated repositories and may reference a PR, branch, commit, or plain repository URL; structural validation would break valid cross-repo links.
>
> **Acceptance Criteria:** A solution with a GitHub PR URL, GitLab branch URL, raw commit SHA URL, and plain repo URL are each accepted. A solution without a `git_link` is accepted (stored as NULL). The stored URL is returned verbatim.

---

> **REQ-206** | Priority: MUST
>
> **Description:** The system shall prohibit direct edits to an existing solution record; to revise a solution the submitter shall call `POST /api/solutions/{id}/versions`, which creates a new row in `solution_versions` with an auto-incremented `version_number`. A UNIQUE constraint on `(solution_id, version_number)` shall be enforced.
>
> **Rationale:** Immutable solution records preserve auditable history; direct mutation would silently overwrite the record visible to voters who upvoted an earlier description.
>
> **Acceptance Criteria:** `PATCH` or `PUT` requests to a solution return HTTP 405. `POST /api/solutions/{id}/versions` returns HTTP 201 with the new version. After two version submissions, `GET /api/solutions/{id}/versions` returns exactly three records ordered by version number ascending.

---

> **REQ-208** | Priority: MUST
>
> **Description:** The system shall expose `GET /api/solutions/{id}/versions` to return the full version history of a solution, ordered by `version_number` ascending.
>
> **Rationale:** Reviewers need to audit how a solution evolved before casting a vote or accepting it.
>
> **Acceptance Criteria:** Response is an ordered array where `version_number` values are strictly ascending. Each version record includes `id`, `solution_id`, `version_number`, `description`, `git_link`, and `created_at`.

---

> **REQ-210** | Priority: MUST
>
> **Description:** The problem poster or any admin may mark a solution as `accepted` via `POST /api/solutions/{id}/accept`. When a solution is accepted, any previously accepted solution on the same problem shall be automatically set to `proposed`.
>
> **Rationale:** A single accepted solution per problem prevents ambiguous resolution state. Restricting acceptance authority prevents third-party hijacking.
>
> **Acceptance Criteria:** The problem author accepting a solution returns HTTP 200 and sets `status = accepted`. A non-author, non-admin call returns HTTP 403. When solution B is accepted while A was accepted, A reverts to `proposed` atomically. Exactly one solution per problem has `status = accepted`.

---

> **REQ-212** | Priority: MUST
>
> **Description:** Solutions on the problem detail page shall be sorted by default: accepted first, then by `upvote_count` descending, with ties broken by `created_at` descending.
>
> **Rationale:** Surfacing the accepted solution at the top lets visitors immediately see the confirmed resolution; ranking the rest by votes surfaces community-endorsed options.
>
> **Acceptance Criteria:** Given solutions A (accepted, 3 upvotes), B (proposed, 10 upvotes), and C (proposed, 10 upvotes, older than B), the order is A → B → C. The endpoint returns solutions in this order by default.

---

> **REQ-214** | Priority: SHOULD
>
> **Description:** The system shall provide a "Newest first" sort toggle that re-orders all solutions by `created_at` descending regardless of status or upvote count.
>
> **Rationale:** Users investigating recent activity need a chronological view not distorted by votes.
>
> **Acceptance Criteria:** Activating "Newest first" reorders solutions chronologically. The toggle state is reflected in the URL query parameter for shareability. Returning to default restores the ordering from REQ-212.

---

> **REQ-216** | Priority: MUST
>
> **Description:** The system shall allow a solution to be submitted anonymously by setting `is_anonymous = true`; the author's identity shall be withheld from all client-facing responses, displaying "Anonymous" instead.
>
> **Rationale:** Contributors may have legitimate reasons to propose a solution without attribution, mirroring the anonymity mechanism for problems.
>
> **Acceptance Criteria:** A solution with `is_anonymous: true` returns `"author": "Anonymous"` in all GET responses. The real identity is never exposed except via privileged admin endpoints. A non-anonymous solution by the same user displays the real name.

---

> **REQ-218** | Priority: MUST
>
> **Description:** `POST /api/solutions/{id}/upvote` shall be an idempotent toggle: first call adds an upvote, second call removes it, and so on.
>
> **Rationale:** Toggle semantics prevent repeated inflation through double-taps or retries.
>
> **Acceptance Criteria:** Calling twice by the same user results in a net upvote count change of zero. The response includes `upvote_count` and `upvoted` boolean. Two different users each calling once increases count by 2.

---

> **REQ-220** | Priority: SHOULD
>
> **Description:** The accepted solution shall be displayed with a visually distinct green border and an "Accepted" badge, shown first regardless of sort mode (unless "Newest first" is explicitly selected).
>
> **Rationale:** Visual differentiation reduces cognitive load for identifying the confirmed resolution.
>
> **Acceptance Criteria:** The accepted solution card renders with a green border and "Accepted" label. No other solution renders with the same treatment. When acceptance reverts, the styling is removed without a page reload.

---

## 6. Voting, Comments & Engagement

> **REQ-250** | Priority: MUST
>
> **Description:** The system shall allow authenticated users to cast an "Upstar" on any problem, stored as a unique record keyed on `(problem_id, user_id)`.
>
> **Rationale:** Upstars are the primary signal for problem validation and drive ranking. Uniqueness prevents vote inflation.
>
> **Acceptance Criteria:** A POST creates a record and increments the count by 1. A duplicate `(problem_id, user_id)` pair is handled idempotently. The database enforces a UNIQUE constraint.

---

> **REQ-252** | Priority: MUST
>
> **Description:** Upstar toggling: if a user who already holds an Upstar submits the action again, the record is deleted and the count decremented by 1.
>
> **Rationale:** Toggle mechanics allow retraction without a separate "remove" affordance.
>
> **Acceptance Criteria:** A user with an existing Upstar submitting again deletes the record and decrements the count. Rapid repeated toggles leave the system in a consistent state.

---

> **REQ-254** | Priority: MUST
>
> **Description:** The system shall allow authenticated users to upvote any solution, tracked independently of problem Upstars, stored as unique records keyed on `(solution_id, user_id)`.
>
> **Rationale:** Solution upvotes measure perceived solution quality rather than problem validity. Keeping the two axes separate ensures accurate scoring.
>
> **Acceptance Criteria:** Solution upvotes and problem Upstars are stored in separate tables. The database enforces a UNIQUE constraint on `(solution_id, user_id)`.

---

> **REQ-256** | Priority: MUST
>
> **Description:** Solution upvote toggling shall use the same mechanism as Upstars: create on first action, delete on second.
>
> **Rationale:** Consistency between voting axes reduces cognitive overhead.
>
> **Acceptance Criteria:** Toggle behavior mirrors REQ-252. Concurrent toggles from the same user are handled idempotently. No negative upvote counts are possible.

---

> **REQ-258** | Priority: MUST
>
> **Description:** The system shall support threaded comments on both problems and solutions, with `parent_type`, `parent_id`, `author_id`, `body`, `is_anonymous`, and `created_at`. Replies may reference a `parent_comment_id` for threading.
>
> **Rationale:** Threaded discussion allows nuanced conversation about specific problems or solutions without conflating discourse levels.
>
> **Acceptance Criteria:** `GET /api/{parent_type}/{id}/comments` returns a structured tree. POST with `parent_comment_id` creates a reply. Comments on a problem are not visible in a solution's comment thread.

---

> **REQ-260** | Priority: MUST
>
> **Description:** Any authenticated user may post a comment anonymously by setting `is_anonymous: true`. The author's identity shall not be disclosed to non-admin users.
>
> **Rationale:** Anonymous commenting lowers the social cost of honest feedback on sensitive workplace problems.
>
> **Acceptance Criteria:** An anonymous comment returns `null` or "Anonymous" for the author field to non-admin callers. The `is_anonymous` flag cannot be changed after posting.

---

> **REQ-262** | Priority: MUST
>
> **Description:** A comment's author or any admin may delete a comment via `DELETE /api/comments/{id}`. Deleted comments with replies shall be replaced with a tombstone preserving thread structure. Leaf comments shall be removed entirely.
>
> **Rationale:** Authors must be able to retract statements, and admins must remove policy-violating content without orphaning replies.
>
> **Acceptance Criteria:** Author delete succeeds with 200/204. Non-author, non-admin delete returns 403. Deleted comments with replies show a tombstone marker. Leaf deletes remove the comment entirely.

---

> **REQ-264** | Priority: MUST
>
> **Description:** A comment's author may edit the body after posting. Edited comments display "(edited)" and full edit history is maintained and accessible to admins.
>
> **Rationale:** Edits improve quality and correct errors. Displaying "(edited)" preserves conversational integrity. History supports moderation.
>
> **Acceptance Criteria:** A PATCH by the author updates the body and appends an edit history entry. Non-authors receive 403. Public payload includes `is_edited: true` when edited. Anonymous comments remain anonymous when edited.

---

> **REQ-266** | Priority: MUST
>
> **Description:** Comment bodies shall be rendered as Markdown. At minimum: bold, italic, inline code, code blocks, blockquotes, lists, and hyperlinks. Raw HTML shall be sanitized to prevent XSS.
>
> **Rationale:** Markdown enables richer technical discussion. Sanitization prevents stored XSS.
>
> **Acceptance Criteria:** Standard Markdown syntax is rendered correctly. A body containing `<script>` tags does not execute JavaScript. Rendering is consistent across problem and solution comment threads.

---

> **REQ-268** | Priority: SHOULD
>
> **Description:** The system shall expose a leaderboard via `GET /api/leaderboard` with two tracks: "Top Solvers" (accepted solution count) and "Top Reporters" (total Upstars received). Both tracks support `time_filter` (week, month, all_time).
>
> **Rationale:** A leaderboard surfaces contributors who drive the most value, reinforcing participation.
>
> **Acceptance Criteria:** Each track returns an ordered list of users ranked by the specified metric for the given time filter. Invalid parameters return 400.

---

> **REQ-270** | Priority: MUST
>
> **Description:** Anonymous contributions shall be excluded from public leaderboard calculations. Anonymous problems do not count toward "Top Reporters"; anonymous solutions do not count toward "Top Solvers".
>
> **Rationale:** Counting anonymous contributions could inadvertently de-anonymize authors through leaderboard rank correlation.
>
> **Acceptance Criteria:** An anonymous problem with 50 upstars does not increment the author's reporter count. An anonymous accepted solution does not increment the solver count.

---

## 7. Notifications & Watches

> **REQ-300** | Priority: MUST
>
> **Description:** The system shall maintain a `watches` table with `id`, `user_id`, `problem_id`, `level`, and `created_at`, enforcing UNIQUE on `(user_id, problem_id)`. The `level` column accepts: `all_activity`, `solutions_only`, `status_only`, `none`.
>
> **Rationale:** A uniqueness constraint prevents duplicate watch records and enforces controlled vocabulary for subscription granularity.
>
> **Acceptance Criteria:** A duplicate `(user_id, problem_id)` insert returns a constraint violation. A `level` value outside the four permitted values is rejected. All four valid levels insert without error.

---

> **REQ-302** | Priority: MUST
>
> **Description:** `POST /api/problems/{id}/watch` creates or updates a watch, `DELETE /api/problems/{id}/watch` removes one. `GET /api/users/me/watches` returns all active watches for the user. All require authentication.
>
> **Rationale:** Explicit endpoints give clients a stable contract for managing watch state.
>
> **Acceptance Criteria:** POST upserts and returns HTTP 200. DELETE removes and returns HTTP 204. Unauthenticated requests return 401.

---

> **REQ-304** | Priority: MUST
>
> **Description:** The system shall auto-create a watch at `all_activity` when a user posts a problem, claims a problem, or submits a solution. If a watch exists at a lower level, it shall be upgraded.
>
> **Rationale:** Users who take active roles have strong implicit interest in subsequent activity.
>
> **Acceptance Criteria:** After each action, a watch exists at `all_activity`. A pre-existing `solutions_only` watch is upgraded. No duplicate rows are created.

---

> **REQ-306** | Priority: SHOULD
>
> **Description:** The system shall auto-create a watch at `solutions_only` when a user comments on a problem they are not already watching. Existing watches are preserved.
>
> **Rationale:** Commenters have expressed interest but may not need granular activity updates.
>
> **Acceptance Criteria:** A user with no watch who comments gets `solutions_only`. A user with `all_activity` retains it. A user with `none` retains `none`.

---

> **REQ-308** | Priority: MUST
>
> **Description:** Users shall be able to override auto-watch behavior through notification preferences (`auto_watch_on_comment`, `auto_watch_on_claim`, `auto_watch_default_level`) stored as JSONB in the `users` table. Preferences are managed via `PATCH /api/users/me/preferences`.
>
> **Rationale:** Auto-watch defaults would be intrusive for power users who manage many problems.
>
> **Acceptance Criteria:** With `auto_watch_on_comment: false`, commenting does not create a watch. With `auto_watch_default_level: "solutions_only"`, posting a problem creates a watch at that level. PATCH returns 200 and reflects changes.

---

> **REQ-310** | Priority: MUST
>
> **Description:** The system shall generate a notification record for each event type: `new_comment`, `new_solution`, `solution_accepted`, `problem_claimed`, `upvote_milestone`, `solution_upvote_milestone`, `claim_expired`, `duplicate_flagged`. Each record includes `user_id`, `type`, `problem_id`, `solution_id` (nullable), `title`, `body`, `is_read` (default false), `created_at`. Notifications are only generated for qualifying watchers per REQ-312.
>
> **Rationale:** Stored notifications enable reliable delivery, audit trails, and read-state tracking.
>
> **Acceptance Criteria:** After each event, exactly one notification row is inserted per qualifying watcher. No notification for watchers at `none`.

---

> **REQ-312** | Priority: MUST
>
> **Description:** Watch-level-to-event routing: `all_activity` receives all 8 types. `solutions_only` receives `new_solution`, `solution_accepted`, `solution_upvote_milestone`. `status_only` receives `problem_claimed`, `claim_expired`, `duplicate_flagged`, `solution_accepted`. `none` receives nothing.
>
> **Rationale:** Explicit routing ensures watch levels carry meaningful semantic contracts.
>
> **Acceptance Criteria:** For three watchers at different levels, each event generates the correct subset of notifications per the mapping.

---

> **REQ-314** | Priority: MUST
>
> **Description:** All notifications shall be delivered in-app via a bell icon and dropdown. In-app delivery is always-on and not suppressible. `GET /api/notifications` returns paginated notifications. `PATCH /api/notifications/{id}/read` marks one as read. `POST /api/notifications/read-all` marks all as read.
>
> **Rationale:** In-app delivery is the guaranteed baseline channel.
>
> **Acceptance Criteria:** Bell icon shows unread count. GET returns descending by `created_at`. PATCH sets `is_read = true`. POST read-all updates all unread rows.

---

> **REQ-316** | Priority: MUST
>
> **Description:** The system shall push notifications in real time over `WS /api/ws/notifications`. The server emits a JSON payload to the target user's open connection within 2 seconds. No retry if disconnected; notification remains accessible via REST.
>
> **Rationale:** Real-time push eliminates polling and allows the bell badge to update without page refresh.
>
> **Acceptance Criteria:** With a WebSocket connected, a qualifying event delivers the payload within 2 seconds. The bell badge increments without page reload. Disconnection does not cause server errors.

---

> **REQ-318** | Priority: SHOULD
>
> **Description:** The system shall deliver notifications via Teams DM when the user has opted in (`delivery.teams: true`). Delivery failures shall be logged but shall not block in-app delivery.
>
> **Rationale:** Teams is the primary communication surface for many internal teams.
>
> **Acceptance Criteria:** With Teams enabled and valid webhook, a notification arrives within 30 seconds. With invalid webhook, failure is logged but in-app delivery completes. With Teams disabled, no message is sent.

---

> **REQ-320** | Priority: SHOULD
>
> **Description:** The system shall deliver a daily email digest to users who opt in (`delivery.email: true`), aggregating unread notifications from the past 24 hours. No per-event emails. No email if no unread notifications.
>
> **Rationale:** A digest avoids inbox flooding while surfacing accumulated activity.
>
> **Acceptance Criteria:** A user with 5 unread notifications receives one email. A user with zero receives none. Running the digest job twice does not produce duplicates.

---

> **REQ-322** | Priority: SHOULD
>
> **Description:** The system shall generate milestone notifications when upstar/upvote counts cross thresholds 10, 25, 50, 100. Each threshold triggers at most one notification per problem or solution.
>
> **Rationale:** Milestone notifications provide positive reinforcement and signal traction.
>
> **Acceptance Criteria:** Incrementing from 9 to 10 inserts one milestone notification. Incrementing from 10 to 11 inserts none. Decrementing and re-crossing does not re-trigger.

---

> **REQ-324** | Priority: MUST
>
> **Description:** The system shall generate `claim_expired` notifications to the former claimant and qualifying watchers when a claim expires. A background job runs at least every 15 minutes.
>
> **Rationale:** Expired claims leave problems in ambiguous state; proactive notification enables re-claiming or handoff.
>
> **Acceptance Criteria:** A claim expiring at T generates notifications by T + 15 minutes. The former claimant and `all_activity`/`status_only` watchers receive them. Running the job twice does not produce duplicates.

---

## 8. Search & Discovery

> **REQ-350** | Priority: MUST
>
> **Description:** The system shall implement full-text search using PostgreSQL `tsvector` columns indexing problem titles and descriptions, with a GIN index.
>
> **Rationale:** GIN-indexed `tsvector` columns provide sub-linear lookup without an external search service.
>
> **Acceptance Criteria:** A `tsvector` column exists on the `problems` table. A GIN index is confirmed. Search against 10,000 rows completes in under 200ms at p95.

---

> **REQ-352** | Priority: MUST
>
> **Description:** `GET /api/problems/search?q={query}` shall execute a `to_tsquery` match and return results ranked by `ts_rank` descending by default.
>
> **Rationale:** A single endpoint serves both search results page and similar-problem suggestions.
>
> **Acceptance Criteria:** A valid `q` returns HTTP 200 with ranked results. An empty `q` returns 400. The endpoint is documented in OpenAPI.

---

> **REQ-354** | Priority: MUST
>
> **Description:** Full-text indexing shall extend to comments and solutions. When a match originates from a solution or comment, the parent problem is returned with a `match_context` field indicating the source.
>
> **Rationale:** Users should find the problem thread regardless of where the keyword appears.
>
> **Acceptance Criteria:** A query matching only a solution body returns the parent problem with `match_context: "solution"` and author name. A problem-only match has no `match_context`.

---

> **REQ-356** | Priority: MUST
>
> **Description:** Search results shall support `sort` parameter: `relevance` (default), `upstars`, `newest`.
>
> **Rationale:** Users may prefer chronological or social-signal ordering beyond relevance.
>
> **Acceptance Criteria:** Each sort mode returns correctly ordered results. Sort state is reflected in the URL.

---

> **REQ-358** | Priority: SHOULD
>
> **Description:** Search results shall accept the same filter parameters as the feed (`status`, `category`, `tags`).
>
> **Rationale:** Reusing feed filters provides a consistent mental model.
>
> **Acceptance Criteria:** Filters narrow results correctly. Active filters are reflected in the URL.

---

> **REQ-360** | Priority: MUST
>
> **Description:** When search returns no results, the system shall display: "No problems match your search. Try different keywords or submit a new problem." with a link to the submission form.
>
> **Rationale:** An empty state with a CTA prevents dead ends.
>
> **Acceptance Criteria:** A zero-result query renders the specified message. The link navigates to the submit form.

---

> **REQ-362** | Priority: MUST
>
> **Description:** When typing a problem title in the submit form, the system shall display up to 5 similar problems after a 300ms debounce, using the search endpoint.
>
> **Rationale:** Surfacing near-duplicates at authorship time is the lowest-friction duplicate prevention.
>
> **Acceptance Criteria:** No request fires until 300ms after the last keystroke. Up to 5 suggestions shown. The panel does not block form submission. Panel disappears when the title field is cleared.

---

> **REQ-364** | Priority: SHOULD
>
> **Description:** Each suggestion in the similar-problem panel shall be a link (opens in new tab) with a description excerpt (up to 120 chars, truncated with ellipsis).
>
> **Rationale:** A title alone may be insufficient to distinguish similarly worded problems.
>
> **Acceptance Criteria:** Clicking opens the correct problem. Descriptions > 120 chars are truncated. Markdown syntax is stripped before truncation.

---

> **REQ-366** | Priority: SHOULD
>
> **Description:** The system shall serve Open Graph meta tags for each problem via `GET /api/problems/{id}/meta`, including `og:title`, `og:description` (upstars, solutions, status), `og:url`, `og:type`, `og:site_name`.
>
> **Rationale:** Rich link previews in Teams/email increase click-through and reduce manual context.
>
> **Acceptance Criteria:** The endpoint returns HTML with all 5 meta tags. `og:description` includes upstar count, solution count, and status. Non-existent problem returns 404.

---

> **REQ-368** | Priority: SHOULD
>
> **Description:** NGINX or middleware shall detect bot User-Agents (Teams, Slack, crawlers) on problem URLs and return the OG meta HTML instead of the SPA shell.
>
> **Rationale:** Link-preview crawlers don't execute JavaScript; serving the SPA produces blank previews.
>
> **Acceptance Criteria:** A request with bot User-Agent returns meta HTML. A browser User-Agent receives the SPA shell. The logic is covered by automated test.

---

## 9. File Attachments

> **REQ-400** | Priority: MUST
>
> **Description:** The system shall allow users to attach files to problems, solutions, and comments via drag-and-drop or multipart/form-data POST to `POST /api/attachments`.
>
> **Rationale:** Engineers must associate supporting evidence (screenshots, logs, waveform captures) directly with the artifact they describe.
>
> **Acceptance Criteria:** Drag-and-drop uploads succeed and return an attachment ID and URL. Programmatic `multipart/form-data` POST also succeeds.

---

> **REQ-402** | Priority: MUST
>
> **Description:** Accepted file types shall be restricted to: images (png, jpg, gif, svg, webp), documents (pdf, txt, md, log, csv), and archives (zip, tar.gz). All other types shall be rejected with HTTP 422.
>
> **Rationale:** An explicit allowlist prevents code-execution and malware distribution vectors.
>
> **Acceptance Criteria:** Uploading `.exe`, `.sh`, `.py`, `.dll` returns 422. Each allowed extension succeeds. A file renamed to `.txt` but with executable MIME type is rejected.

---

> **REQ-404** | Priority: MUST
>
> **Description:** Maximum file size: 10 MB per file, 50 MB cumulative per problem. Uploads exceeding either limit are rejected before writing to storage.
>
> **Rationale:** Unbounded uploads exhaust disk space and can cause denial-of-service.
>
> **Acceptance Criteria:** A 10.1 MB file is rejected with 413. A problem with 48 MB rejects an additional 3 MB file. Files at exactly the limits are accepted.

---

> **REQ-406** | Priority: MUST
>
> **Description:** Attachments shall be stored at `/data/attachments/{year}/{month}/{uuid}_{original_filename}`, where `uuid` is a v4 UUID generated at upload time.
>
> **Rationale:** UUID prefix eliminates filename collisions and prevents path enumeration.
>
> **Acceptance Criteria:** After upload, exactly one file exists at the matching path. Two simultaneous uploads with identical filenames produce distinct paths.

---

> **REQ-408** | Priority: MUST
>
> **Description:** An `attachments` table row shall be created for each upload containing: `id`, `parent_type`, `parent_id`, `uploader_id`, `filename`, `content_type`, `file_size`, `storage_path`, `created_at`.
>
> **Rationale:** The database record is the authoritative index linking files to application entities.
>
> **Acceptance Criteria:** A successful upload creates exactly one row with all columns non-null. `parent_type` is constrained to `problem`, `solution`, `comment`.

---

> **REQ-410** | Priority: MUST
>
> **Description:** NGINX shall serve attachments directly from the volume at `location /attachments/` with `Cache-Control: public, max-age=604800, immutable`. FastAPI shall not proxy content.
>
> **Rationale:** NGINX serves static content with negligible overhead. UUID paths guarantee uniqueness for immutable caching.
>
> **Acceptance Criteria:** GET requests return the file with correct cache headers. Response originates from NGINX. Deleting an attachment removes the file from disk.

---

> **REQ-412** | Priority: MUST
>
> **Description:** Image attachments (png, jpg, gif, svg, webp) shall be rendered inline in markdown content. Non-image attachments shall be rendered as download links.
>
> **Rationale:** Inline images eliminate click-to-open for common diagnostic attachments. Non-image types have no safe inline rendering path.
>
> **Acceptance Criteria:** A PNG renders as an `<img>` tag. A PDF renders as an `<a>` with `download` attribute. SVG files do not execute embedded scripts.

---

> **REQ-414** | Priority: SHOULD
>
> **Description:** Users shall be able to paste screenshots from clipboard (Ctrl+V / Cmd+V) in attachment drop zones. Pasted images are subject to the same type and size validation.
>
> **Rationale:** Screenshots are the most frequent attachment for hardware defect reports. Clipboard paste removes friction.
>
> **Acceptance Criteria:** Pasting a clipboard screenshot initiates upload and inserts the image reference. Pasting non-image data does not trigger upload. Oversize pasted images are rejected.

---

> **REQ-416** | Priority: MUST
>
> **Description:** Attachment deletion shall be permitted only by the uploader or an admin. `DELETE /api/attachments/{id}` shall remove both the database row and the on-disk file atomically.
>
> **Rationale:** Restricting deletion prevents accidental removal. Atomic cleanup prevents orphaned rows or orphaned files.
>
> **Acceptance Criteria:** A non-uploader, non-admin DELETE returns 403. Uploader DELETE returns 204 and removes both DB row and file. A simulated disk failure leaves the DB row intact.

---

## 10. Administration

> **REQ-450** | Priority: MUST
>
> **Description:** All endpoints under `/api/admin/*` shall be gated by a `require_admin` dependency that rejects non-admin requests with HTTP 403.
>
> **Rationale:** Administrative operations mutate user roles, expose private content, and alter configuration.
>
> **Acceptance Criteria:** A non-admin JWT returns 403. An unauthenticated request returns 401. An admin JWT grants access.

---

> **REQ-452** | Priority: MUST
>
> **Description:** The system shall provide category management endpoints (GET, POST, PATCH, DELETE `/api/categories`) allowing admins to create, edit name/description/color, and deactivate categories.
>
> **Rationale:** Categories must evolve as team problem domains change without requiring code deployment.
>
> **Acceptance Criteria:** Admin POST creates a category (201). PATCH updates supplied fields. Changes are reflected immediately in the category list.

---

> **REQ-454** | Priority: MUST
>
> **Description:** The system shall provision 10 default categories on first run: RTL Design, Verification, Physical Design, DFT, EDA Tools, Methodology, IT/Infra, Scripts/Automation, Documentation, Other.
>
> **Rationale:** A curated ASIC-oriented starting set eliminates bootstrap burden.
>
> **Acceptance Criteria:** A fresh deployment returns all 10 categories via GET without admin action.

---

> **REQ-456** | Priority: MUST
>
> **Description:** Categories shall be reorderable via `PATCH /api/categories/reorder` accepting an ordered array of IDs.
>
> **Rationale:** Display order communicates priority; admins must control it without recreating categories.
>
> **Acceptance Criteria:** After reorder, GET returns categories in the submitted order. An array with omitted or duplicated IDs returns 422.

---

> **REQ-458** | Priority: MUST
>
> **Description:** Category deletion shall be soft-delete (marking inactive). A category with existing problems shall not be hard-deleted; the system returns 409 if attempted.
>
> **Rationale:** Deleting a category with problems would orphan content.
>
> **Acceptance Criteria:** Deleting a category with no problems sets it inactive and excludes it from public list. Deleting one with problems returns 409. Soft-deleted categories remain accessible to admin endpoints.

---

> **REQ-460** | Priority: MUST
>
> **Description:** `GET /api/tags` shall return each tag with a `usage_count` and support `sort_by=name` and `sort_by=usage`.
>
> **Rationale:** Admins need usage data to identify redundant or misspelled tags.
>
> **Acceptance Criteria:** `sort_by=usage` returns descending by count. `sort_by=name` returns alphabetical. Counts match actual problem counts.

---

> **REQ-462** | Priority: MUST
>
> **Description:** Tags shall be renameable via `PATCH /api/tags/{id}` and deletable via `DELETE /api/tags/{id}`. Deleting removes the tag from all problems without deleting the problems.
>
> **Rationale:** Tag hygiene requires cleanup. Deletion must not cascade destructively.
>
> **Acceptance Criteria:** After rename, all tagged problems reflect the new name. After delete, no problem returns the tag. The deleted tag disappears from GET.

---

> **REQ-464** | Priority: MUST
>
> **Description:** `POST /api/tags/merge` shall merge 2+ tags into a canonical target tag, atomically re-tagging all problems. Source tags are removed.
>
> **Rationale:** Organic tag creation produces synonyms and typos; merging consolidates without manual re-tagging.
>
> **Acceptance Criteria:** After merge, all source-tagged problems carry exactly the target tag. Source tags disappear. The operation is atomic. Fewer than 2 source IDs returns 422.

---

> **REQ-466** | Priority: MUST
>
> **Description:** `GET /api/admin/users` shall return all users with search by display name or email (case-insensitive, partial match).
>
> **Rationale:** Admins must locate specific users quickly in growing installations.
>
> **Acceptance Criteria:** `search=alice` returns matching users. Without search, all users are returned. Response is paginated.

---

> **REQ-468** | Priority: MUST
>
> **Description:** Admins shall promote/demote roles via `PATCH /api/admin/users/{id}/role` and activate/deactivate via `PATCH /api/admin/users/{id}/status`. Deactivated users have sessions invalidated and receive 401 on subsequent requests. Content is preserved.
>
> **Rationale:** Access control lifecycle must be manageable without database access.
>
> **Acceptance Criteria:** Role change is reflected on next login. Status deactivation rejects existing tokens. Content remains visible.

---

> **REQ-470** | Priority: MUST
>
> **Description:** `GET /api/admin/flagged` shall return a combined queue of pending duplicate confirmations and flagged anonymous posts, in reverse-chronological order.
>
> **Rationale:** A single review queue prevents moderators from polling multiple views.
>
> **Acceptance Criteria:** Items include `type`, `content_id`, `content_preview` (200 chars), `flagged_at`. Queue count decrements when resolved.

---

> **REQ-472** | Priority: MUST
>
> **Description:** `POST /api/admin/deanonymize/{type}/{id}` shall reveal the author of anonymous content. The action shall require confirmation in the UI. Every de-anonymize action shall be recorded in an immutable audit log.
>
> **Rationale:** The ability to unmask authors must exist for abuse cases while remaining accountable and traceable.
>
> **Acceptance Criteria:** The admin UI presents a confirmation dialog. A successful call returns the revealed author. The audit log entry is created atomically. Audit entries cannot be modified or deleted via API.

---

> **REQ-474** | Priority: SHOULD
>
> **Description:** The application name shall be configurable via `GET/PATCH /api/admin/config` and via `APP_NAME` environment variable, with the database value taking precedence.
>
> **Rationale:** Deployments may need rebranding without source code changes or redeployment.
>
> **Acceptance Criteria:** PATCH updates the name, reflected immediately in UI and GET. Setting `APP_NAME` env and clearing DB value reverts to env.

---

> **REQ-476** | Priority: SHOULD
>
> **Description:** Admin frontend routes (`/admin/*`) shall be accessible only to admin users. Non-admins are redirected to the main board. Unauthenticated users are redirected to login.
>
> **Rationale:** Frontend route guards prevent non-admins from seeing broken admin UI.
>
> **Acceptance Criteria:** A non-admin navigating to `/admin/users` is redirected to `/`. An unauthenticated user is redirected to login. An admin reaches all admin routes.

---

## 11. UI/UX & Frontend

> **REQ-500** | Priority: MUST
>
> **Description:** The system shall implement a consistent visual theme with yellow-to-lime-green gradient as the primary accent, Inter or IBM Plex Sans as body typeface, and monospace for tags, badges, and code-adjacent elements.
>
> **Rationale:** A cohesive typographic and color system communicates technical precision and reinforces the ASIC design company's brand identity.
>
> **Acceptance Criteria:** All pages render with designated typefaces. Gradient accent appears on primary CTAs, active navigation, and border highlights. Tags and badges use monospace.

---

> **REQ-502** | Priority: MUST
>
> **Description:** The landing page shall render with a cork-texture background, decorative note cards at randomized angles, and a centered sign-in card with gradient border and zero tilt. The tagline "Surface problems. Propose solutions. Get recognized." shall be visible.
>
> **Rationale:** The bulletin board metaphor makes the app's purpose legible at first contact.
>
> **Acceptance Criteria:** Cork texture visible on `/`. At least 4 decorative cards with distinct rotations. Sign-in card centered with gradient border. Tagline visible without scrolling at 1280x800.

---

> **REQ-504** | Priority: MUST
>
> **Description:** The application name in the nav bar, browser tab, and landing page shall be configurable via `APP_NAME` environment variable, defaulting to "Aion Bulletin".
>
> **Rationale:** Deploy-time configuration supports environment-specific branding without code changes.
>
> **Acceptance Criteria:** Setting `APP_NAME=Foo Board` causes all three surfaces to display "Foo Board". Unsetting reverts to "Aion Bulletin".

---

> **REQ-506** | Priority: MUST
>
> **Description:** The feed page shall present problems as a vertically stacked card list. Each card displays: upstar count/button, title, preview, status badge, claimer, category pill, tags, solution count, comment count, relative timestamp. Sort bar and filter bar appear above.
>
> **Rationale:** A scannable, information-dense layout matches the mental model of community feed interfaces.
>
> **Acceptance Criteria:** Each card renders all data points when present. Sort bar has at minimum "Newest", "Most Upstarred", "Most Active". Filter bar supports status and category. Updates happen without full page reload.

---

> **REQ-508** | Priority: MUST
>
> **Description:** Status badges shall use: gray for open, yellow/amber for claimed, lime green for solved/accepted. Colors shall be consistent across feed, detail, search, and admin views.
>
> **Rationale:** Consistent color semantics enable at-a-glance board state parsing.
>
> **Acceptance Criteria:** Problems in each state render with the specified colors across all views. No other element uses these colors as primary fill in a confusable way.

---

> **REQ-510** | Priority: MUST
>
> **Description:** The problem detail page shall display title, author, status, upstar button, claim button in the header, followed by markdown-rendered description. Below, two tabs: "Solutions" and "Comments".
>
> **Rationale:** Separating solutions and comments keeps the view focused as engagement grows.
>
> **Acceptance Criteria:** Markdown renders correctly (headings, code blocks, lists). Tab switching loads only the selected content. Tabs are reachable via URL parameter for direct linking.

---

> **REQ-512** | Priority: MUST
>
> **Description:** The application shall implement client-side routing for all defined routes without full page reloads between navigations.
>
> **Rationale:** Client-side routing provides fast, app-like navigation and enables code splitting.
>
> **Acceptance Criteria:** Navigation between routes triggers no full page load. Deep-linking to any route resolves correctly. Unknown routes render the 404 page.

---

> **REQ-514** | Priority: MUST
>
> **Description:** The application shall support dark mode, toggleable from Settings and optionally from the nav bar. Dark mode preserves accent gradient and status badge colors.
>
> **Rationale:** Dark mode reduces eye strain in low-light environments and is a standard expectation.
>
> **Acceptance Criteria:** Toggle applies immediately without page reload and persists across sessions. No white backgrounds in dark mode. The preference defaults to OS-level `prefers-color-scheme`.

---

> **REQ-516** | Priority: MUST
>
> **Description:** Every list view shall display a contextually appropriate empty state with a message and CTA button when no items are present.
>
> **Rationale:** Empty states prevent the UI from appearing broken and guide users toward productive actions.
>
> **Acceptance Criteria:** Each list view renders a non-blank UI with context-specific message and CTA when empty. Verified in both light and dark modes.

---

> **REQ-518** | Priority: MUST
>
> **Description:** The application shall implement: custom 404 page, custom 401/403 page, non-blocking network error toast (auto-dismiss 5s), and inline validation errors on form fields.
>
> **Rationale:** Well-designed error states prevent confusion and maintain trust.
>
> **Acceptance Criteria:** Nonexistent route renders 404 with link to feed. Unauthorized access renders 401/403. Simulated network error triggers toast. Invalid form data shows inline field errors.

---

> **REQ-520** | Priority: MUST
>
> **Description:** Desktop viewports (≥ 1024px) shall use a collapsible sidebar. Mobile viewports (< 1024px) shall use alternative navigation with no persistent sidebar.
>
> **Rationale:** Sidebar provides efficient desktop navigation; removing it on mobile preserves horizontal real estate.
>
> **Acceptance Criteria:** At 1280px, sidebar visible with collapse control. At 375px, no sidebar; navigation via alternative pattern. No horizontal overflow at either breakpoint.

---

> **REQ-522** | Priority: SHOULD
>
> **Description:** The submit problem page shall present: title input, markdown editor with live preview, category dropdown, tag autocomplete, and anonymous checkbox. No extraneous fields.
>
> **Rationale:** A minimal form lowers the barrier to posting.
>
> **Acceptance Criteria:** All five elements are functional. Live preview updates within 300ms. Tag autocomplete fires after 2 characters. Anonymous checkbox causes "Anonymous" display. Client-side validation shows inline errors.

---

> **REQ-524** | Priority: SHOULD
>
> **Description:** The AI Search page (`/ai-search`) shall render as a non-interactive mockup with all elements disabled and a "Coming Soon" banner. No backend API calls.
>
> **Rationale:** A placeholder communicates the product roadmap and allows UX evaluation before backend is built.
>
> **Acceptance Criteria:** The route renders without errors. All inputs/buttons are disabled. "Coming Soon" visible without scrolling. No network requests. Accessible from main navigation.

---

> **REQ-526** | Priority: SHOULD
>
> **Description:** The leaderboard page shall display a ranked table with rank, username, problems solved, total upvotes, and problems posted. Time filter (all time, month, week) and two tracks (solvers/reporters) via tabs.
>
> **Rationale:** Dual tracks ensure both problem surfacers and problem solvers receive recognition.
>
> **Acceptance Criteria:** Table renders with all columns from live data. Time filter updates rankings without page reload. Track switching updates data and labels. Ranks are sequential with no gaps.

---

## 12. Non-Functional Requirements

> **REQ-900** | Priority: MUST
>
> **Description:** The system shall respond to 95% of API requests within 500ms and 99% within 2000ms under a load of 100 concurrent users on the target hardware (4 CPU, 8 GB RAM).
>
> **Rationale:** Engineers expect near-interactive response times. Latency above 2 seconds degrades perceived reliability.
>
> **Acceptance Criteria:** A load test with 100 virtual users for 5 minutes shows p95 ≤ 500ms and p99 ≤ 2000ms with zero 5xx responses.

---

> **REQ-902** | Priority: MUST
>
> **Description:** Full-text search queries shall return results within 1000ms at p95, supported by GIN indexes on indexed text columns.
>
> **Rationale:** Slow search degrades the board's value and pushes engineers toward ad-hoc channels.
>
> **Acceptance Criteria:** With 10,000+ problems, `EXPLAIN ANALYZE` confirms index scans and 200 sequential searches return p95 ≤ 1000ms.

---

> **REQ-904** | Priority: MUST
>
> **Description:** The system shall support 100 simultaneous users without degradation and remain operational under bursts of 500 with graceful degradation.
>
> **Rationale:** Growth to 500 users must not require redesign. Burst events must not cause outages.
>
> **Acceptance Criteria:** At 100 users: 0% error rate. At 500 users: ≤ 1% error rate (excluding 429s). CPU and memory below 90%.

---

> **REQ-906** | Priority: MUST
>
> **Description:** All client-server traffic shall be encrypted via TLS 1.2+, terminated at NGINX. HTTP shall redirect to HTTPS with 301.
>
> **Rationale:** The application handles internal engineering data requiring confidentiality.
>
> **Acceptance Criteria:** HTTP request returns 301 with HTTPS location. `openssl s_client` confirms TLS 1.2+.

---

> **REQ-908** | Priority: MUST
>
> **Description:** JWT tokens shall be stored exclusively in HttpOnly, Secure, SameSite=Strict cookies. Tokens shall never appear in response bodies, URLs, or JavaScript-accessible storage.
>
> **Rationale:** Defense-in-depth against XSS given user-supplied markdown rendering.
>
> **Acceptance Criteria:** `Set-Cookie` includes all three attributes. No JWT in JSON bodies or URLs. `document.cookie` returns empty.

---

> **REQ-910** | Priority: MUST
>
> **Description:** NGINX shall enforce 30 req/s on `/api/*` and 5 req/s on `/api/auth/*`. Excess requests receive 429.
>
> **Rationale:** Rate limiting prevents brute-force and request flooding on a single-server deployment.
>
> **Acceptance Criteria:** 60 req/s to `/api/problems` results in ~50% 429s. 10 req/s to `/api/auth/login` results in ~50% 429s. Limits are configurable in NGINX config.

---

> **REQ-912** | Priority: MUST
>
> **Description:** Every request shall receive a UUID correlation ID (via middleware) and produce a structured JSON log entry with: `correlation_id`, `method`, `path`, `user_id`, `status_code`, `duration_ms`. Business events shall emit dedicated entries.
>
> **Rationale:** Structured logs with correlation IDs are the primary observability tool on a single-server deployment.
>
> **Acceptance Criteria:** A POST to `/api/problems` produces one request log entry and one `problem_created` event entry, both valid JSON parseable by `jq`.

---

> **REQ-914** | Priority: MUST
>
> **Description:** Automated daily backups via `pg_dump` and attachment `rsync`. Retention: 7 daily + 4 weekly. A tested restore procedure shall exist.
>
> **Rationale:** On-prem deployments have no managed backup. Data loss must be recoverable within one business day.
>
> **Acceptance Criteria:** After 14 days, backup directory contains 7 daily + 4 weekly files. A restore drill on staging succeeds with matching row counts. Procedure is documented.

---

> **REQ-916** | Priority: MUST
>
> **Description:** All runtime configuration shall be supplied via environment variables from a `.env` file. No secrets or environment-specific values shall be hardcoded.
>
> **Rationale:** External configuration enables same images across environments and prevents secret exposure in version control.
>
> **Acceptance Criteria:** Fresh deployment with `.env` reaches healthy state. Removing `DATABASE_URL` causes clear startup error. `grep` for credential values across source returns no matches.

---

> **REQ-918** | Priority: MUST
>
> **Description:** All responses shall include: `Content-Security-Policy` (scripts from `'self'` only), `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`. User-supplied markdown shall be sanitized at both storage and render time.
>
> **Rationale:** CSP and sanitization prevent stored XSS. X-Frame-Options prevents clickjacking.
>
> **Acceptance Criteria:** `curl -I` shows all four headers. A `<script>alert(1)</script>` injection does not execute. Security header scanner grades A or above.

---

> **REQ-920** | Priority: MUST
>
> **Description:** Database schema changes shall be managed exclusively through Alembic migrations, applied automatically on container startup.
>
> **Rationale:** Alembic provides auditable, repeatable, reversible schema history. Startup application ensures consistency.
>
> **Acceptance Criteria:** Deploying to a blank database creates all tables. Adding a migration and redeploying applies it without data loss. `alembic downgrade -1` reverts cleanly.

---

> **REQ-922** | Priority: MUST
>
> **Description:** All containers shall restart automatically on host reboot or crash via systemd units generated by `podman generate systemd`.
>
> **Rationale:** On-prem infrastructure experiences reboots; the service must recover without operator intervention.
>
> **Acceptance Criteria:** After host reboot, all 3 containers return to running within 2 minutes. `systemctl status` shows `active (running)`.

---

> **REQ-924** | Priority: SHOULD
>
> **Description:** File uploads shall be validated against both MIME type (content inspection) and extension. Files with executable MIME types or extensions shall be rejected with 422.
>
> **Rationale:** Content inspection guards against extension spoofing.
>
> **Acceptance Criteria:** A file named `.png` with ELF binary content is rejected. A valid PNG succeeds. The allowlist is configurable via environment variable.

---

> **REQ-926** | Priority: SHOULD
>
> **Description:** The test suite shall maintain ≥ 80% line coverage across route handlers, services, and utilities. Tests use `httpx.AsyncClient` with test DB and auto-rollback.
>
> **Rationale:** 80% coverage catches regressions. Auto-rollback ensures test isolation.
>
> **Acceptance Criteria:** `pytest --cov=app --cov-fail-under=80` exits 0. Two tests writing to the same table run in any order without interference.

---

> **REQ-928** | Priority: MAY
>
> **Description:** The system may expose a `/healthz` endpoint returning liveness and PostgreSQL reachability, responding within 200ms without authentication.
>
> **Rationale:** Enables NGINX upstream checks, systemd watchdog, and monitoring integration.
>
> **Acceptance Criteria:** Returns `{"status": "ok", "db": "reachable"}` at HTTP 200 when DB is up. Returns `{"status": "degraded", "db": "unreachable"}` at HTTP 503 when DB is down.

---

## 13. System-Level Acceptance Criteria

| Criterion | Threshold |
|-----------|-----------|
| All MUST requirements pass verification | 100% |
| All SHOULD requirements pass verification | ≥ 90% |
| API response time p95 | ≤ 500ms at 100 concurrent users |
| Full-text search p95 | ≤ 1000ms |
| Zero data loss on single-component restart | Verified via kill/restart of each container |
| Backup restore completes without error | Verified on staging |
| Security headers present on all responses | Verified via automated scan |
| No XSS execution from stored user content | Verified via injection test suite |
| Test coverage | ≥ 80% line coverage |

---

## 14. Requirements Traceability Matrix

| REQ ID | Section | Domain | Priority | Description (Summary) |
|--------|---------|--------|----------|----------------------|
| REQ-100 | 3 | Auth | MUST | Azure AD OIDC authentication |
| REQ-102 | 3 | Auth | MUST | Single-tenant restriction |
| REQ-104 | 3 | Auth | MUST | Magic link authentication |
| REQ-106 | 3 | Auth | MUST | Magic link token expiry (15 min, single-use) |
| REQ-108 | 3 | Auth | MUST | JWT HttpOnly cookies (access 15m, refresh 7d) |
| REQ-110 | 3 | Auth | MUST | Token refresh endpoint |
| REQ-112 | 3 | Auth | MUST | User auto-provisioning on first login |
| REQ-114 | 3 | Auth | MUST | Two-role model (User/Admin) |
| REQ-116 | 3 | Auth | MUST | Permission enforcement on content operations |
| REQ-118 | 3 | Auth | MUST | GET /api/auth/me endpoint |
| REQ-120 | 3 | Auth | MUST | Logout with server-side cookie clearing |
| REQ-122 | 3 | Auth | MUST | Dev auth bypass with production safety |
| REQ-124 | 3 | Auth | MUST | Minimum Azure AD scopes |
| REQ-126 | 3 | Auth | SHOULD | Authentication audit logging |
| REQ-128 | 3 | Auth | SHOULD | Magic link rate limiting |
| REQ-150 | 4 | Problems | MUST | Problem submission |
| REQ-152 | 4 | Problems | MUST | Field validation constraints |
| REQ-154 | 4 | Problems | MUST | Anonymous problem posting |
| REQ-156 | 4 | Problems | MUST | Status state machine |
| REQ-158 | 4 | Problems | MUST | Multiple claimers with primary designation |
| REQ-160 | 4 | Problems | MUST | 14-day claim auto-expiry |
| REQ-162 | 4 | Problems | MUST | Two-step duplicate confirmation |
| REQ-164 | 4 | Problems | MUST | Pinned problems (max 3, admin-only) |
| REQ-166 | 4 | Problems | MUST | Edit history for problems |
| REQ-168 | 4 | Problems | MUST | Cursor-based pagination |
| REQ-170 | 4 | Problems | MUST | Feed sort modes |
| REQ-172 | 4 | Problems | MUST | Feed filter parameters |
| REQ-174 | 4 | Problems | MUST | Pinned problems above pagination |
| REQ-176 | 4 | Problems | SHOULD | Idempotency-Key on creation |
| REQ-178 | 4 | Problems | SHOULD | Full-text search endpoint |
| REQ-180 | 4 | Problems | SHOULD | Activity timestamp tracking |
| REQ-182 | 4 | Problems | MAY | Starred filter |
| REQ-200 | 5 | Solutions | MUST | Solutions as first-class objects |
| REQ-202 | 5 | Solutions | MUST | Solution listing endpoint |
| REQ-204 | 5 | Solutions | MUST | Freeform git link field |
| REQ-206 | 5 | Solutions | MUST | Immutable solutions with versioning |
| REQ-208 | 5 | Solutions | MUST | Version history endpoint |
| REQ-210 | 5 | Solutions | MUST | Solution acceptance (single per problem) |
| REQ-212 | 5 | Solutions | MUST | Default solution sort order |
| REQ-214 | 5 | Solutions | SHOULD | Newest-first sort toggle |
| REQ-216 | 5 | Solutions | MUST | Anonymous solutions |
| REQ-218 | 5 | Solutions | MUST | Upvote toggle idempotency |
| REQ-220 | 5 | Solutions | SHOULD | Accepted solution visual distinction |
| REQ-250 | 6 | Engagement | MUST | Upstar uniqueness and creation |
| REQ-252 | 6 | Engagement | MUST | Upstar toggle |
| REQ-254 | 6 | Engagement | MUST | Solution upvote (separate from Upstar) |
| REQ-256 | 6 | Engagement | MUST | Solution upvote toggle |
| REQ-258 | 6 | Engagement | MUST | Threaded comments |
| REQ-260 | 6 | Engagement | MUST | Anonymous comments |
| REQ-262 | 6 | Engagement | MUST | Comment deletion with tombstoning |
| REQ-264 | 6 | Engagement | MUST | Comment editing with history |
| REQ-266 | 6 | Engagement | MUST | Markdown rendering with XSS sanitization |
| REQ-268 | 6 | Engagement | SHOULD | Dual-track leaderboard |
| REQ-270 | 6 | Engagement | MUST | Anonymous exclusion from leaderboard |
| REQ-300 | 7 | Notifications | MUST | Watches table with level enum |
| REQ-302 | 7 | Notifications | MUST | Watch CRUD endpoints |
| REQ-304 | 7 | Notifications | MUST | Auto-watch on post/claim/solution |
| REQ-306 | 7 | Notifications | SHOULD | Auto-watch on comment |
| REQ-308 | 7 | Notifications | MUST | Configurable auto-watch preferences |
| REQ-310 | 7 | Notifications | MUST | Notification generation for 8 event types |
| REQ-312 | 7 | Notifications | MUST | Watch-level-to-event routing |
| REQ-314 | 7 | Notifications | MUST | In-app notification delivery |
| REQ-316 | 7 | Notifications | MUST | WebSocket real-time push |
| REQ-318 | 7 | Notifications | SHOULD | Teams DM delivery |
| REQ-320 | 7 | Notifications | SHOULD | Daily email digest |
| REQ-322 | 7 | Notifications | SHOULD | Milestone notifications |
| REQ-324 | 7 | Notifications | MUST | Claim expiry notifications |
| REQ-350 | 8 | Search | MUST | PostgreSQL full-text search with GIN |
| REQ-352 | 8 | Search | MUST | Search endpoint with ts_rank |
| REQ-354 | 8 | Search | MUST | Cross-entity search (solutions, comments) |
| REQ-356 | 8 | Search | MUST | Search sort modes |
| REQ-358 | 8 | Search | SHOULD | Search filters (status, category, tags) |
| REQ-360 | 8 | Search | MUST | Empty search state with CTA |
| REQ-362 | 8 | Search | MUST | Similar problem suggestions on submit |
| REQ-364 | 8 | Search | SHOULD | Suggestion excerpts and links |
| REQ-366 | 8 | Search | SHOULD | Open Graph meta tags |
| REQ-368 | 8 | Search | SHOULD | Bot User-Agent detection for link previews |
| REQ-400 | 9 | Attachments | MUST | File upload via drag-and-drop / POST |
| REQ-402 | 9 | Attachments | MUST | File type allowlist |
| REQ-404 | 9 | Attachments | MUST | Size limits (10 MB/file, 50 MB/problem) |
| REQ-406 | 9 | Attachments | MUST | UUID-based storage path |
| REQ-408 | 9 | Attachments | MUST | Attachments table metadata |
| REQ-410 | 9 | Attachments | MUST | NGINX direct file serving |
| REQ-412 | 9 | Attachments | MUST | Inline images, download links for others |
| REQ-414 | 9 | Attachments | SHOULD | Clipboard paste for screenshots |
| REQ-416 | 9 | Attachments | MUST | Atomic attachment deletion |
| REQ-450 | 10 | Admin | MUST | Admin role gating |
| REQ-452 | 10 | Admin | MUST | Category CRUD |
| REQ-454 | 10 | Admin | MUST | Default categories on first run |
| REQ-456 | 10 | Admin | MUST | Category reordering |
| REQ-458 | 10 | Admin | MUST | Category soft-delete |
| REQ-460 | 10 | Admin | MUST | Tag listing with usage counts |
| REQ-462 | 10 | Admin | MUST | Tag rename and delete |
| REQ-464 | 10 | Admin | MUST | Tag merge |
| REQ-466 | 10 | Admin | MUST | User listing with search |
| REQ-468 | 10 | Admin | MUST | Role and status management |
| REQ-470 | 10 | Admin | MUST | Flagged content queue |
| REQ-472 | 10 | Admin | MUST | De-anonymize with audit trail |
| REQ-474 | 10 | Admin | SHOULD | Configurable app name |
| REQ-476 | 10 | Admin | SHOULD | Admin frontend route guards |
| REQ-500 | 11 | UI/UX | MUST | Visual theme (gradient, typography) |
| REQ-502 | 11 | UI/UX | MUST | Bulletin board landing page |
| REQ-504 | 11 | UI/UX | MUST | Configurable app name in UI |
| REQ-506 | 11 | UI/UX | MUST | Feed card layout |
| REQ-508 | 11 | UI/UX | MUST | Status badge color coding |
| REQ-510 | 11 | UI/UX | MUST | Problem detail with tabs |
| REQ-512 | 11 | UI/UX | MUST | Client-side routing |
| REQ-514 | 11 | UI/UX | MUST | Dark mode |
| REQ-516 | 11 | UI/UX | MUST | Empty states with CTAs |
| REQ-518 | 11 | UI/UX | MUST | Error states (404, 401/403, toast, inline) |
| REQ-520 | 11 | UI/UX | MUST | Responsive layout (sidebar/mobile) |
| REQ-522 | 11 | UI/UX | SHOULD | Submit problem form (minimal) |
| REQ-524 | 11 | UI/UX | SHOULD | AI Search placeholder page |
| REQ-526 | 11 | UI/UX | SHOULD | Leaderboard page |
| REQ-900 | 12 | NFR | MUST | API response time (p95 ≤ 500ms) |
| REQ-902 | 12 | NFR | MUST | Search performance (p95 ≤ 1000ms) |
| REQ-904 | 12 | NFR | MUST | 100-500 user capacity |
| REQ-906 | 12 | NFR | MUST | TLS 1.2+ encryption |
| REQ-908 | 12 | NFR | MUST | JWT cookie security |
| REQ-910 | 12 | NFR | MUST | Rate limiting |
| REQ-912 | 12 | NFR | MUST | Structured logging with correlation IDs |
| REQ-914 | 12 | NFR | MUST | Automated backup and restore |
| REQ-916 | 12 | NFR | MUST | Configuration externalization |
| REQ-918 | 12 | NFR | MUST | Security headers and XSS prevention |
| REQ-920 | 12 | NFR | MUST | Alembic migration management |
| REQ-922 | 12 | NFR | MUST | Auto-restart on reboot |
| REQ-924 | 12 | NFR | SHOULD | MIME content inspection |
| REQ-926 | 12 | NFR | SHOULD | 80% test coverage |
| REQ-928 | 12 | NFR | MAY | Health check endpoint |

### Priority Tally

| Priority | Count |
|----------|-------|
| MUST | 103 |
| SHOULD | 24 |
| MAY | 2 |
| **Total** | **129** |

---

## Appendix A: Glossary

See Section 1.3 (Terminology) for all domain-specific term definitions.

## Appendix B: Document References

| Document | Location | Purpose |
|----------|----------|---------|
| Design Reference | `docs/DESIGN_REF.md` | Complete design decisions, data model, UI/UX, architecture |
| This Specification | `docs/AION_BULLETIN_SPEC.md` | Authoritative requirements |

## Appendix C: Open Questions

1. Exact Azure AD tenant ID and app registration credentials (IT dependency)
2. Internal SMTP server hostname and port (IT dependency)
3. TLS certificate provisioning process (internal CA or self-signed)
4. Teams incoming webhook URL for notification channel
5. Server/VM allocation timeline
6. Internal DNS entry for the application
