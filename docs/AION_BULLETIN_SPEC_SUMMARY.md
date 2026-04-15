## 1) Generic System Overview

### Purpose

This system is an internal problem bulletin board — a community-driven platform where any team member can surface problems they encounter, and others validate, claim, and propose solutions. It exists because engineering knowledge is fragmented across communication tools, critical problems go unseen by the people best equipped to solve them, and there is no recognition mechanism for those who contribute solutions. Without it, problems are raised ad-hoc in scattered channels, duplicated unknowingly, and resolved without institutional memory.

### How It Works

A user authenticates via their corporate identity provider or a fallback email-based login. Once signed in, they can post a problem — a titled, categorized description of something that needs solving — optionally anonymously. Other users browse a sortable, filterable feed of problems and can "upstar" ones they consider important, signaling community validation. Any user may claim a problem to indicate they are actively working on it; multiple claimers are supported, with the first marked as primary. Claims auto-expire after a configurable inactivity window to prevent indefinite blocking.

Solutions are first-class entities submitted against a problem, each with its own description, optional external code reference, version history, and independent upvote count. Solutions are immutable — revisions create new versions rather than overwriting. The problem poster or an administrator can accept a single solution, marking the problem as resolved. Threaded comments allow discussion on both problems and solutions.

A notification subsystem lets users subscribe ("watch") to problems at varying granularity — all activity, solutions only, status changes only, or none. Notifications are delivered in-app in real time, with optional delivery to the team messaging platform and as a daily email digest. A full-text search system indexes problems, solutions, and comments, and surfaces similar-problem suggestions during problem creation to reduce duplicates. Administrators manage categories, tags, user roles, flagged content, and can de-anonymize posts with an auditable action.

### Tunable Knobs

Operators can configure authentication behavior — which identity provider is active, magic link validity windows, and whether a development bypass is enabled for testing. Notification delivery channels are user-configurable per channel. Feed pagination size, rate-limiting thresholds, and file upload limits (per-file and cumulative) are adjustable. The application name itself is configurable for rebranding across environments. Auto-watch behavior — whether the system automatically subscribes users to problems they interact with, and at what granularity — can be overridden per user.

### Design Rationale

The system is designed around low-friction participation: minimal required fields, anonymous posting, and one-click voting remove barriers that historically silenced contributors. Problem validation is bottom-up — community upstars determine importance rather than management assignment — which inverts the typical top-down task management model. Solutions are versioned and immutable to preserve auditability, preventing retroactive rewrites that would invalidate prior discussion. External code references are tracked as freeform links rather than deeply integrated, reflecting the reality that solutions span heterogeneous repositories and workflows the system should not govern. Two independent voting axes — problem validation and solution quality — ensure that a well-stated problem with a poor first solution is not penalized, and vice versa.

### Boundary Semantics

The system is triggered when a user navigates to the web application and authenticates. Its inputs are user-authored content (problems, solutions, comments, votes, file attachments) and identity assertions from the corporate identity provider. Its outputs are the rendered bulletin board, notification events across three delivery channels, and structured audit logs. The system maintains all application state — user records, content, votes, watches, notifications, and files — persistently. It does not manage external code repositories, trigger CI/CD pipelines, or integrate with project management tools. Responsibility ends at the application boundary: link previews are served for external consumers, but the system does not control how those consumers render them.

---

# Aion Bulletin — Specification Summary

**Companion document to:** `AION_BULLETIN_SPEC.md` (v1.0)
**Purpose:** Requirements-level digest for stakeholders, reviewers, and implementers.
**See also:** `DESIGN_REF.md` — Complete design decisions, data model, UI/UX, architecture

---

## 2) Scope and Boundaries

**Entry point:** User accesses the web application via browser, authenticated via Microsoft 365 OAuth or magic link email.
**Exit points:**

- Problems posted, validated, claimed, solved, and accepted through their lifecycle
- Notifications delivered via in-app WebSocket, Teams webhook, and email digest
- Structured audit logs emitted for all operations

### In scope

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

### Out of scope for this spec

- Wiki/knowledge base (deferred, not v1)
- AI-powered semantic search / RAG (v2 — placeholder page only in v1)
- Git workflow management (no branch creation, merging, or repo enforcement)
- Native mobile app (responsive web only)
- Real-time git sync or polling
- Task queue (not needed at this scale)

### Out of scope for this project

- Jira replacement or top-down task management
- Payment/bounty system
- External-facing public access

---

## 3) Architecture / Pipeline Overview

```
    Browser (SPA)
         │ HTTPS
         ▼
    ┌─────────────────────────┐
    │  Reverse Proxy          │
    │  - Static file serving  │
    │  - API proxy            │
    │  - Attachment serving   │
    │  - TLS termination      │
    │  - Rate limiting        │
    │  - WebSocket proxy      │
    │  - Bot detection (OG)   │
    └────────────┬────────────┘
                 │
                 ▼
    ┌─────────────────────────┐
    │  API Server             │
    │  - REST + WebSocket     │
    │  - Auth (OAuth + magic) │
    │  - Business logic       │
    │  - Structured logging   │
    └────────────┬────────────┘
                 │
          ┌──────┴──────┐
          ▼             ▼
    ┌───────────┐ ┌──────────────┐
    │  Database │ │  File Volume │
    │  (FTS,    │ │  (uploads)   │
    │   JSONB)  │ └──────────────┘
    └───────────┘

    External: Identity Provider, Team Messaging Webhook, SMTP
```

Three-tier on-premises deployment with a single reverse proxy, application server, and database. The reverse proxy handles TLS, rate limiting, static assets, and direct file serving. The API server handles all business logic, auth flows, and WebSocket connections. External integrations are outbound-only (identity, messaging, email).

---

## 4) Requirement Framework

- **ID scheme:** `REQ-xxx`, grouped by section (REQ-1xx for Auth through REQ-9xx for NFRs), with gaps between IDs for future insertion
- **Priority keywords:** RFC 2119 — MUST, SHOULD, MAY
- **Requirement structure:** Each requirement includes Description, Rationale, and Acceptance Criteria in blockquote format
- **Traceability:** Full matrix in Section 14, with priority tally (103 MUST, 24 SHOULD, 2 MAY — 129 total)

---

## 5) Functional Requirement Domains

The 129 requirements span 10 functional and non-functional domains:

- **Authentication & Authorization** (`REQ-100–128`) — OAuth, magic link, JWT sessions, roles, permissions, dev bypass
- **Problems & Feed** (`REQ-150–182`) — Submission, status FSM, claiming, duplicates, pinning, edit history, pagination, sort/filter
- **Solutions & Versioning** (`REQ-200–220`) — First-class solutions, immutable versioning, git links, acceptance, anonymous solutions
- **Voting, Comments & Engagement** (`REQ-250–270`) — Upstars, solution upvotes (separate axes), threaded comments, leaderboard
- **Notifications & Watches** (`REQ-300–324`) — Watch levels, auto-watch, 8 event types, WebSocket push, Teams, email digest
- **Search & Discovery** (`REQ-350–368`) — Full-text search with ranking, cross-entity indexing, similar-problem suggestions, link previews
- **File Attachments** (`REQ-400–416`) — Upload, type/size limits, UUID storage, inline rendering, clipboard paste
- **Administration** (`REQ-450–476`) — Categories, tags (merge/rename), user management, flagged queue, de-anonymize with audit
- **UI/UX & Frontend** (`REQ-500–526`) — Theme, landing page, feed cards, detail page, dark mode, responsive layout, error/empty states
- **Non-Functional** (`REQ-900–928`) — Performance, security, logging, backup, deployment, testing

---

## 6) Non-Functional and Security Themes

### Non-functional areas (`REQ-9xx`)

- **Performance** — API p95 ≤ 500ms, search p95 ≤ 1000ms, 100–500 user capacity
- **Reliability** — Automated backup/restore, auto-restart on reboot, zero data loss on component restart
- **Observability** — Structured JSON logging with correlation IDs, business event logging
- **Deployment** — Containerized on-premises, environment-variable configuration, migration management
- **Testing** — 80%+ line coverage, async test client with auto-rollback

### Security

- TLS 1.2+ on all traffic
- JWT tokens in HttpOnly/Secure/SameSite=Strict cookies only
- Rate limiting on API and auth endpoints
- Security headers (CSP, X-Frame-Options, nosniff, Referrer-Policy)
- Dual-layer XSS prevention (storage sanitization + render sanitization)
- MIME content inspection on uploads
- Minimum-privilege OAuth scopes

---

## 7) Design Principles

- **Low-friction first**: Every decision minimizes barriers to participation — fewer fields, one-click auth, anonymous option
- **Bottom-up discovery**: Problems surface from anyone; community validates via upstars — not top-down assignment
- **Git as a link, not a backbone**: Track references, don't manage repositories or workflows
- **Separation of voting axes**: Problem validation (upstars) and solution quality (upvotes) scored independently
- **Idempotency by default**: Every endpoint safe to retry — toggles, unique constraints, idempotency keys

---

## 8) Key Decisions Captured by the Spec

- Two independent voting systems (upstars vs upvotes) rather than a single vote type
- Solutions are immutable with explicit versioning — no in-place edits
- Anonymous posting with retained author identity for admin moderation
- Multiple claimers per problem with primary designation and 14-day auto-expiry
- Cursor-based pagination for feeds, not offset-based
- Full-text search via database-native indexing rather than an external search service
- Single accepted solution per problem with automatic demotion of prior accepted
- Watch-level notification routing with 4 granularity levels
- Bulletin board metaphor for landing page (cork texture, decorative cards)
- v2 AI search placeholder present in navigation but non-functional

---

## 9) Acceptance, Evaluation, and Feedback

The spec defines system-level acceptance criteria covering:

- **Requirement verification** — 100% of MUST requirements, ≥ 90% of SHOULD requirements
- **Performance benchmarks** — API and search latency under concurrent load
- **Resilience** — Zero data loss on single-component restart, verified backup restore
- **Security** — Automated header scan, XSS injection test suite
- **Code quality** — ≥ 80% line coverage

Individual requirements include per-requirement acceptance criteria with concrete positive and negative test cases.

---

## 10) Companion Documents

| Document | Role |
|----------|------|
| `AION_BULLETIN_SPEC.md` | Authoritative requirements baseline (129 requirements) |
| `DESIGN_REF.md` | Complete design decisions, data model, UI/UX, architecture |
| `AION_BULLETIN_SPEC_SUMMARY.md` | This document — requirements digest |

---

## 11) Sync Status

Aligned to `AION_BULLETIN_SPEC.md` v1.0 as of 2026-04-14.
