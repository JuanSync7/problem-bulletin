# Problem Board — Design Reference

## Concept

An internal web app where team members post problems, the community validates them via upvoting ("upstar"), someone claims and solves them, and solutions are tracked with git links. Think Reddit + task claiming + git-linked solutions.

## Core Problem Being Solved

- Information is scattered across tools — no single place for visibility
- Key people miss problems they could help with
- People don't speak up or don't know where to post
- No recognition for people who solve problems
- Engineers don't use GitHub directly, so a friendly web UI is required

## Target Users

- Internal engineering team (primarily)
- Mixed technical comfort levels — many engineers don't use git/GitHub yet
- UI must be low-friction; GitHub-level complexity is too high a barrier

## Core Features (v1)

### Problems
- Any user can post a problem
- Title, description, category/tags
- Status workflow: **open -> claimed -> solved -> accepted**

### Upstar (Problem Validation)
- Upstar = "I agree this is a real problem"
- Separate from solution upvoting — these are two distinct voting axes
- Upstar count drives problem ranking/visibility

### Claiming
- Any user can claim an open problem (self-assign)
- One primary claimer, but others can also submit competing solutions

### Solutions
- Solutions are first-class objects, not just comments
- Multiple solutions per problem are allowed
- Each solution has:
  - Author
  - Description (human-written context)
  - Git link (PR, branch, commit, repo — freeform URL, not enforced)
  - Version history (v1, v2, v3... as author iterates)
  - Separate upvote count (community votes on solution quality)
- Solutions are not restricted to a single repo — different problems touch different repos
- The app does NOT manage git workflows (no branch creation, no merging)
- The app is the coordination/voting layer; git repos manage themselves

### Comments
- Threaded comments on both problems and solutions
- Users can point to existing solutions or external resources

### Recognition / Leaderboard
- Track who solved the most problems, who got the most solution upvotes
- Surfaced in the app as a leaderboard or profile stats

### Accepting a Solution
- Problem poster (or designated maintainers per area) can mark a solution as "accepted"
- Similar to Stack Overflow's green checkmark
- Actual code merging happens in the relevant git repo by repo owners — outside the app

## Architecture Decisions

### Frontend
- Standalone web app with a clean, low-friction UI
- AI-generated frontend (Cursor, Bolt, Lovable, v0, etc.)
- No dependency on GitHub's UI

### Backend
- Simple API server
- **Postgres database** as the backend (not GitHub Issues)
- Rationale: users never see GitHub, so using it as a backend adds indirection and auth complexity for no user-facing benefit

### Git Integration
- Git is an optional link field on solutions, not the backbone
- App stores the link + human-written description + version metadata
- App does NOT poll or sync with git — no periodic checks
- Richer git data (PR status, diff preview) via on-demand GitHub API calls is a nice-to-have, not v1

### Auth
- **Primary: Microsoft 365 / Azure AD OAuth** (company uses Microsoft 365)
- **Secondary: Magic link (email)** — fallback for contractors or anyone without M365
- Implementation: FastAPI + `authlib` (OAuth/OIDC) + `python-jose` (JWT)
- Tenant-restricted: only org members can sign in
- JWT tokens as HttpOnly cookies (access token 15min + refresh token 7 days)
- User record auto-provisioned in Postgres on first login
- No passwords, no "forgot password", no manual account creation

### Wiki
- **Deferred — not in v1**
- The app's archive of solved problems + discussions + linked solutions IS the knowledge base organically
- If needed later: simple markdown page feature backed by a DB table (not git wiki — same adoption problem)

## Data Model (Sketch)

### users
- id, name, email, avatar, role, created_at
- notification_prefs (JSONB) — global defaults for notification settings

### categories
- id, name, slug, description, color, sort_order, is_active

### tags
- id, name, slug, created_by, created_at

### problems
- id, author_id, category_id, title, description, status (open/claimed/solved/accepted/duplicate), is_anonymous (bool), duplicate_of_id (nullable FK → problems), created_at, updated_at

### problem_tags
- problem_id, tag_id

### problem_upstars
- id, problem_id, user_id, created_at

### solutions
- id, problem_id, author_id, status (proposed/accepted/rejected), is_anonymous (bool), created_at

### solution_versions
- id, solution_id, git_link, description, version_number (auto-increment per solution), created_at

### solution_upvotes
- id, solution_id, user_id, created_at

### comments
- id, parent_type (problem/solution), parent_id, author_id, body, is_anonymous (bool), created_at

### claims
- id, problem_id, user_id, is_primary (bool), claimed_at

### attachments
- id, parent_type (problem/solution/comment), parent_id, uploader_id
- filename, content_type, file_size, storage_path
- created_at

### notifications
- id, user_id, type (enum — see notification types below), problem_id (nullable), solution_id (nullable)
- title, body, is_read (bool), created_at

### watches
- id, user_id, problem_id
- level (enum: all / solutions_only / status_only / none)
- created_at

### notification types (enum)
- `new_comment` — someone commented on a problem/solution you watch
- `new_solution` — someone proposed a solution to a problem you watch
- `solution_accepted` — a solution was accepted on a problem you watch
- `problem_claimed` — someone claimed a problem you posted/watch
- `upstar_milestone` — your problem hit a milestone (10, 25, 50, 100 upstars)
- `solution_upvote_milestone` — your solution hit an upvote milestone
- `claim_expired` — a claim on your watched problem expired (see status rules)
- `duplicate_flagged` — your problem was flagged as duplicate

## File Attachments

### What Users Can Attach
- Screenshots, log files, waveform captures, EDA tool outputs, PDFs, text files
- Attach to: problems, solutions, comments
- Drag-and-drop or paste from clipboard (for screenshots)

### Storage
- **Local volume mount** (simplest for on-prem): files stored on the server filesystem under `/data/attachments/`
- Organized by: `/data/attachments/{year}/{month}/{uuid}_{filename}`
- UUID prefix prevents collisions and guessable paths
- Podman volume: `attachments:/data/attachments:Z`
- **Size limits:** 10 MB per file, 50 MB total per problem (prevents abuse, sufficient for screenshots/logs)
- **Allowed types:** Images (png, jpg, gif, svg, webp), documents (pdf, txt, md, log, csv), archives (zip, tar.gz). Block executables.

### API
```
POST   /api/attachments                → Upload file (multipart/form-data), returns attachment ID + URL
GET    /api/attachments/{id}           → Download/serve file
DELETE /api/attachments/{id}           → Delete (uploader or admin)
```

- Upload returns an attachment ID that gets linked to the problem/solution/comment on submit
- Images served inline (rendered in markdown/description), other files as download links
- NGINX serves static files directly from the attachment volume for performance (bypasses FastAPI)

### NGINX Addition for Attachments
```nginx
location /attachments/ {
    alias /data/attachments/;
    expires 7d;
    add_header Cache-Control "public, immutable";
}
```

## Anonymous Posting

### How It Works
- User is still authenticated (must be logged in to post)
- Checkbox on submit form: "Post anonymously"
- When anonymous: display name shows as "Anonymous" with a generic avatar
- The `author_id` is still stored in the database (admins can see who posted if needed for moderation)
- Applies to: problems, solutions, and comments independently (you can post a problem anonymously but comment non-anonymously)

### Why This Matters
- Core motivation: people "don't want to speak up" — removing social risk increases participation
- Junior engineers more likely to report problems senior engineers might dismiss
- Anonymous ≠ unaccountable: admins retain visibility for moderation/abuse cases

### UX
- Submit form: `[ ] Post anonymously` checkbox, unchecked by default
- Anonymous posts show: "Anonymous · 2h ago" with a gray placeholder avatar
- Author sees their own anonymous posts marked with "(You)" in their profile, but others cannot see this
- Leaderboard: anonymous contributions do NOT count toward public leaderboard (that's the tradeoff for anonymity)

### Admin Moderation
- Admins can reveal the author of an anonymous post if there is an abuse/HR issue
- This should be logged (audit trail) and rare — not a casual action
- Consider: require two admins to approve a de-anonymize action (prevents abuse of power)

## Status Transition Rules

### Status Flow
```
                    ┌──────────────┐
                    │              │
    ┌───────┐    ┌──▼───┐    ┌─────┴──┐    ┌──────────┐
    │ Open  │───►│Claimed│───►│ Solved │───►│ Accepted │
    └───┬───┘    └──┬────┘    └────────┘    └──────────┘
        │           │
        │     ┌─────▼─────┐
        └────►│ Duplicate │
              └───────────┘
```

### Who Can Transition What
| From | To | Who |
|---|---|---|
| Open | Claimed | Any user (claims it) |
| Open | Duplicate | Problem poster, admin |
| Claimed | Open | Claimer (unclaims), admin, auto-expire |
| Claimed | Solved | Claimer submits accepted solution |
| Solved | Accepted | Problem poster, admin |
| Any | Duplicate | Admin |

### Claiming Rules
- **Multiple claimers allowed** — "claim" = "I'm working on this" (a signal, not a lock)
- First claimer is marked as **primary claimer** (highlighted on the problem card)
- Others listed as "also working on this"
- Any claimer can unclaim themselves
- Admin can remove any claimer
- **Auto-expire:** if a claimer has no activity (no solution submitted, no comment, no version update) for **14 days**, the claim auto-expires and the user is notified. Prevents silent squatting.
- Problem status returns to "Open" only if ALL claims expire/are removed

### Duplicate Handling
- Any user can **suggest** a problem is a duplicate (button: "Flag as duplicate" → select the original problem)
- Problem poster or admin **confirms** the duplicate flag
- Confirmed duplicates:
  - Status changes to "Duplicate"
  - A link to the original problem is shown prominently: "Duplicate of: [Problem #42 — Title]"
  - Upstars from the duplicate are NOT merged (keeps it simple)
  - Comments remain visible (may contain useful context)
  - The duplicate is excluded from the main feed by default (filter toggle to show/hide)

## Notification System

### Watch Mechanism (GitHub-style)
- Users can **watch** a problem — button on the problem detail page
- Watch levels:
  - **All activity** — every comment, solution, status change, claim
  - **Solutions only** — new solutions and solution accepted
  - **Status only** — status changes (claimed, solved, accepted, duplicate)
  - **None / Unwatch**

### Auto-Watch Rules
- You automatically watch a problem when you:
  - Post it (default: all activity)
  - Claim it (default: all activity)
  - Submit a solution (default: all activity)
  - Comment on it (default: solutions only)
- Users can change or remove auto-watches at any time

### Global Notification Preferences (per user)
Stored as JSONB in users table:
```json
{
  "auto_watch_on_comment": true,
  "auto_watch_on_claim": true,
  "auto_watch_default_level": "all",
  "delivery": {
    "in_app": true,
    "teams": false,
    "email": false
  },
  "quiet_hours": null
}
```

### Delivery Channels
- **In-app** (always on): bell icon, WebSocket push, notification dropdown
- **Teams DM** (opt-in): personal Teams message via bot/webhook
- **Email digest** (opt-in): daily summary of watched activity, not per-event

## Backup Strategy

### PostgreSQL Backup
- **Automated daily backup** via `pg_dump` cron job on the host
- Retain: 7 daily backups, 4 weekly backups (rolling)
- Storage: separate volume or network mount (NOT on the same disk as the database)

```bash
# /etc/cron.d/problemboard-backup (or systemd timer)
0 2 * * * podman exec problemboard_db_1 pg_dump -U problemboard problemboard | gzip > /backups/problemboard_$(date +\%Y\%m\%d).sql.gz
# Cleanup: delete backups older than 30 days
0 3 * * * find /backups -name "problemboard_*.sql.gz" -mtime +30 -delete
```

### Attachment Backup
- Attachments volume: rsync to backup location on same schedule
- Or: if using a shared/network filesystem, it may already be backed up by IT

### Restore
```bash
gunzip < /backups/problemboard_20260414.sql.gz | podman exec -i problemboard_db_1 psql -U problemboard problemboard
```

## What This Is NOT

- Not a git workflow manager — no branch creation, no merge control, no repo enforcement
- Not a Jira replacement — this is bottom-up discovery, not top-down task management
- Not a wiki (yet)

## Alternatives Considered

| Option | Verdict |
|---|---|
| GitHub Issues + Projects + scripting | Engineers don't use GitHub — adoption problem |
| Jira | Top-down tool, bad voting UX, intimidating for casual use |
| Fider (open source) | Covers ~70% but no git links, no solution versioning, would outgrow it |
| Discourse + plugins | Heavier, closer to a forum than a task board |
| Retool / Appsmith over GitHub API | Viable but still needs GitHub accounts or proxy layer |
| Fork Lemmy/Reddit clone | Faster to v1 but inherit someone else's codebase |
| Custom build with AI-generated frontend | **Selected** — cleanest fit, full control, moderate effort |

## UI/UX Design

### Style & Theme
- **Company identity:** ASIC design company, yellow-to-lime-green brand colors
- **Design philosophy:** Clean, technical, professional — precision engineering feel, not playful/startup
- **Color system:**
  - Base: Light neutral (white / light gray) — with dark mode toggle (engineers love dark mode)
  - Accent: Yellow-to-lime-green gradient for primary actions (submit button, upstar highlights, active states, progress bars)
  - Status mapping (naturally aligns with brand gradient):
    - Gray = open (unvalidated)
    - Yellow/amber = claimed / in-progress
    - Lime green = solved/accepted
- **Typography:**
  - Body: Inter or IBM Plex Sans (clean, highly readable)
  - Accents: Monospace for tags, status badges, counts, code references (subtle engineering feel)
- **Surfaces:** Subtle borders, minimal shadows, generous whitespace — content-first, not decoration-first

### Global Layout
- **Top navbar:** Logo (left) | Search bar (center) | [Submit Problem] button (prominent) | Notifications bell | Leaderboard link | User avatar/menu (right)
- **Sidebar (desktop):** Collapsible, houses category filters and saved views
- **No sidebar on mobile** — responsive, content stacks vertically

### Page: Feed / Home (Most Important Page)
- Reddit-style vertical list — dense, scannable, information-rich
- Sort/filter bar at top:
  - Sort by: Most upstarred / Newest / Recently active / Most discussed
  - Filter by: Status (open/claimed/solved) / Category / My posts / Unclaimed
- Each problem card:
  ```
  [upstar count]  Problem Title                         [Status badge]
  [upstar btn ]   Preview text (first ~100 chars)...    [Claimed by: Avatar Name]
                  [Category pill] [#tag] [#tag]         3 solutions · 12 comments · 2h ago
  ```

### Page: Problem Detail
- **Top section:** Title, author + avatar, timestamp, status badge, upstar button + count, claim button (if unclaimed), category + tags
- **Description:** Full markdown-rendered body
- **Tabbed middle section:**
  - **Solutions tab:** List of proposed solutions, each showing:
    - Author + avatar
    - Description
    - Git link (clickable)
    - Version history dropdown (v1, v2, v3...)
    - Upvote button + count
    - "Accept" button (visible to problem owner / maintainers)
  - **Comments tab:** Threaded discussion
- Solutions are visually distinct from comments — first-class objects, not buried

### Page: Submit Problem
- Minimal form — lowest possible friction:
  - Title (required)
  - Description (markdown editor or rich text) (required)
  - Category (required — dropdown from fixed list)
  - Tags (optional — freeform, with autocomplete from existing tags)
- That's it. No other required fields.

### Page: Submit Solution (inline on Problem Detail)
- Expandable form or modal on the problem detail page:
  - Description of approach (required)
  - Git link (optional — not everyone has code yet when proposing)
  - Submit
- To iterate: "Submit new version" button on user's existing solution

### Page: Leaderboard
- Table or card view with columns: Rank, User, Problems Solved, Total Solution Upvotes, Problems Posted
- Time filter: This week / This month / All time
- Two tracks of recognition:
  - "Top Solvers" — most accepted solutions
  - "Top Reporters" — most upstarred problems (recognize people who find problems too)

### Page: User Profile
- User's stats summary
- Tabs: My Problems / My Solutions / Activity History

### Page: AI Search (v2 Placeholder — Grayed Out)
- **Navbar:** "AI Search" link visible from day one, with a subtle "Soon" badge
- **Page content:** Grayed-out, non-interactive mockup of a chat interface:
  ```
  ┌─────────────────────────────────────────────────┐
  │                  🔍 AI Search                    │
  │                                                  │
  │  ┌─────────────────────────────────────────┐     │
  │  │ (grayed out chat bubble mockup)         │     │
  │  │ "How have we handled timing closure     │     │
  │  │  failures on block X?"                  │     │
  │  └─────────────────────────────────────────┘     │
  │                                                  │
  │  ┌─────────────────────────────────────────┐     │
  │  │ (grayed out response mockup)            │     │
  │  │ Based on 3 solved problems:             │     │
  │  │ • #89 — Adjusted SDC constraints...     │     │
  │  │ • #134 — Modified clock tree...         │     │
  │  │ Sources: Problem #89, #134, #201        │     │
  │  └─────────────────────────────────────────┘     │
  │                                                  │
  │  ┌─────────────────────────────────────────┐     │
  │  │ 🔒 Coming Soon                          │     │
  │  │ AI-powered search across all problems   │     │
  │  │ and solutions. Ask questions in natural  │     │
  │  │ language and get answers with sources.   │     │
  │  └─────────────────────────────────────────┘     │
  │                                                  │
  │  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ [Send]    │
  │  (disabled input bar)                            │
  └─────────────────────────────────────────────────┘
  ```
- Everything has `pointer-events: none; opacity: 0.5` — visible but non-interactive
- No backend work needed — pure static HTML/CSS
- **Purpose:** signals the roadmap, builds anticipation, collects informal feedback ("when is this coming?")

### v2: AI Search (Future Implementation Notes)
When ready to build:
- **Backend:** pgvector extension for Postgres (no new infra), embed problems + solutions + comments
- **Embedding job:** runs on problem/solution create/update, stores vectors in a `_embedding` column
- **RAG flow:** user question → embed → vector similarity search → top-k results → LLM synthesizes answer with cited sources
- **Chat UI:** replace the grayed-out mockup with a real conversational interface
- **Display:** LLM response rendered as markdown, source citations link back to actual problem/solution pages in the app
- **Endpoint:** `POST /api/ai/search` (body: `{question: "..."}`, response: `{answer: "...", sources: [...]}`)
- Clean upgrade path — no v1 rearchitecture needed, just add pgvector column (one migration) + new endpoint + new page

### Page: Landing / Login
- Shown before authentication — the first thing anyone sees
- **App name is configurable** via environment variable (`APP_NAME=Aion Bulletin`)
- **Concept: Bulletin board with pinned note cards**
  - The landing page IS a bulletin board — visually communicates what the app does without explanation
  - Sign-in is a card pinned to the board, not a separate sterile login form

- **Visual Design:**
  - Background: cork board texture (subtle, warm tan — not cartoonish, keep it professional)
  - Decorative "pinned" note cards scattered at slightly different angles and sizes
  - Cards are static/fake — not real data, not clickable — just visual storytelling
  - Each sample card hints at the app's lifecycle:
    - Some show upstar counts (problem validation)
    - Some show "SOLVED" badge (completion)
    - Some show comment counts (discussion)
    - Content uses realistic ASIC-domain language so users immediately relate
  - Pushpin or tape graphic on each card corner (subtle, CSS-only or small SVG)

- **Layout:**
  ```
  ┌──────────────────────────────────────────────────────────────┐
  │ (cork board texture background)                               │
  │                                                               │
  │  ╔═══════════════════════════════════════════════╗            │
  │  ║  📌  Aion Bulletin                            ║            │
  │  ╚═══════════════════════════════════════════════╝            │
  │                                                               │
  │  ┌──────────────┐  ┌──────────────┐                          │
  │  │ Regression   │  │ Timing       │                          │
  │  │ farm keeps   │  │ closure on   │                          │
  │  │ timing out   │  │ block X      │  ┌────────────┐          │
  │  │ ⭐ 14        │  │ ⭐ 8         │  │ EDA tool   │          │
  │  │ 💬 3         │  │ 💬 12        │  │ license    │          │
  │  └──~2°tilt─────┘  └──-1°tilt────┘  │ conflict   │          │
  │                                       │ ⭐ 22      │          │
  │  ┌──────────────────────────────┐    │ 💬 7       │          │
  │  │ (sign-in card — prominent,  │    └──1°tilt────┘          │
  │  │  white, brand gradient      │                             │
  │  │  border, centered, larger)  │                             │
  │  │                              │                             │
  │  │  ┌────────────────────────┐ │    ┌────────────┐           │
  │  │  │ 🔑 Sign in with       │ │    │ ✅ SOLVED  │           │
  │  │  │    Microsoft           │ │    │ Coverage   │           │
  │  │  └────────────────────────┘ │    │ gap in     │           │
  │  │          ── or ──           │    │ DFT flow   │           │
  │  │  ┌────────────────────────┐ │    └──-2°tilt───┘           │
  │  │  │ ✉️ Sign in with       │ │                             │
  │  │  │    email link          │ │                             │
  │  │  └────────────────────────┘ │                             │
  │  └──────────────────────────────┘                             │
  │                                                               │
  │  ┌──────────────┐                                            │
  │  │ Script for   │     Surface problems.                      │
  │  │ auto-gen     │     Propose solutions.                     │
  │  │ SDC needs    │     Get recognized.                        │
  │  │ update       │                                            │
  │  │ ⭐ 5         │                                            │
  │  └──1.5°tilt────┘                                            │
  │                                                               │
  │  (footer: version · internal use only)                       │
  └──────────────────────────────────────────────────────────────┘
  ```

- **Sign-in card details:**
  - White background, slightly larger than decorative cards
  - Yellow-to-lime-green gradient border (brand accent)
  - Centered vertically and horizontally on the board
  - Two buttons stacked: "Sign in with Microsoft" (primary) and "Sign in with email link" (secondary)
  - No tilt — sits straight to signal "this is the real interactive element"

- **Decorative card details (CSS-only, no images needed):**
  - White/off-white background with subtle drop shadow
  - Slightly randomized rotation (-2° to +2° via CSS transform)
  - Slightly randomized position (CSS grid with small offsets)
  - Each card shows: short problem title (2-3 lines), upstar count, comment count
  - One card has a green "SOLVED" badge — shows the full lifecycle
  - Content is hardcoded/static — not fetched from the database

- **Tagline:** "Surface problems. Propose solutions. Get recognized." — pinned as its own card or floating text near bottom right

- **Responsive:** On mobile, reduce to 2-3 decorative cards, sign-in card takes more width

- **After successful auth** → redirect to Feed/Home

### Page: Search Results
- Triggered from the navbar search bar
- Results are **problems** (not solutions or comments as standalone cards)
- If the search matched within a solution or comment, the problem card shows which part matched:
  ```
  [upstar count]  Problem Title                         [Status badge]
  [upstar btn ]   Preview text...                       [Claimed by: Alice]
                  [Category] [#tag]                     3 solutions · 12 comments
                  ─────
                  Matched in solution by Bob:
                  "...adjusted the SDC constraints to fix the timing..."
  ```
- Sort: Relevance (default) / Most upstarred / Newest
- Filter: same as feed filters (status, category, tags)
- Empty search results: "No problems match your search. Try different keywords or [submit a new problem]."

### Page: Settings / Preferences
- Accessible from user avatar menu → "Settings"
- Sections:

**Profile**
- Display name (pulled from Microsoft, editable)
- Avatar (pulled from Microsoft, or upload custom)

**Notifications**
- Auto-watch defaults:
  - `[x] Watch problems I post` (default: on)
  - `[x] Watch problems I claim` (default: on)
  - `[x] Watch problems I submit solutions to` (default: on)
  - `[ ] Watch problems I comment on` (default: off)
- Default watch level: [All activity ▾] dropdown
- Delivery channels:
  - `[x] In-app notifications` (always on, not toggleable)
  - `[ ] Microsoft Teams DM` (opt-in)
  - `[ ] Email digest (daily summary)` (opt-in)

**Appearance**
- Theme: Light / Dark / System default

- All preferences sync to backend via `PATCH /api/users/me/preferences`
- Changes apply immediately (optimistic UI update)

### Page: Admin Panel
- **Not a separate app or API** — same FastAPI backend, same routers, endpoints gated by `Depends(require_admin)`
- Visible only to users with `role=admin` — navbar shows "Admin" link for admins only
- URL: `/admin/*`

**Admin: Categories**
```
┌─────────────────────────────────────────────────────┐
│ Categories                              [+ Add New] │
├─────────────────────────────────────────────────────┤
│ ■ RTL Design        "Coding, architecture..."  [Edit] [Deactivate] │
│ ■ Verification      "UVM, formal, sim..."      [Edit] [Deactivate] │
│ ■ Physical Design   "PnR, floorplanning..."    [Edit] [Deactivate] │
│ ...                                                  │
│ (drag to reorder)                                    │
└─────────────────────────────────────────────────────┘
```
- Add, edit name/description/color, reorder, deactivate (soft delete — don't delete categories with existing problems)

**Admin: Tags**
```
┌─────────────────────────────────────────────────────┐
│ Tags                                    [Merge Tags] │
├─────────────────────────────────────────────────────┤
│ #timing-closure     (used by 14 problems)    [Rename] [Delete] │
│ #timing_closure     (used by 3 problems)     [Rename] [Delete] │
│ #uvm-scoreboard     (used by 8 problems)     [Rename] [Delete] │
│ ...                                                  │
│ Search: [___________]                                │
└─────────────────────────────────────────────────────┘
```
- Merge: select 2+ tags → merge into one (all problems re-tagged automatically)
- Rename, delete (problems lose the tag)
- Sortable by: name, usage count

**Admin: Users**
```
┌─────────────────────────────────────────────────────┐
│ Users                                                │
├─────────────────────────────────────────────────────┤
│ Alice Wong    alice@company.com    [Admin ▾]  Active │
│ Bob Chen      bob@company.com      [User  ▾]  Active │
│ ...                                                  │
│ Search: [___________]                                │
└─────────────────────────────────────────────────────┘
```
- Promote/demote role via dropdown
- View user's activity
- Deactivate user (soft — preserves their content, blocks login)

**Admin: Flagged Content**
- List of problems flagged as duplicate (pending confirmation)
- List of anonymous posts flagged for moderation (if abuse reported)
- De-anonymize action (requires confirmation dialog, logged in audit trail)

### Empty States
Empty states are critical for day-one adoption. Every list view needs one.

**Feed (no problems yet):**
```
┌─────────────────────────────────────────────────┐
│                                                  │
│         (illustration or icon)                   │
│                                                  │
│      No problems posted yet.                     │
│      Be the first to surface something           │
│      the team should know about.                 │
│                                                  │
│      [ Submit the First Problem ]                │
│                                                  │
└─────────────────────────────────────────────────┘
```

**Problem detail — no solutions yet:**
```
┌─────────────────────────────────────────────────┐
│  Solutions (0)                                    │
│                                                  │
│      No solutions proposed yet.                  │
│      Know how to fix this? Be the first.         │
│                                                  │
│      [ Propose a Solution ]                      │
│                                                  │
└─────────────────────────────────────────────────┘
```

**Problem detail — no comments yet:**
```
  No comments yet. Start the discussion.
  [Write a comment...]
```

**Leaderboard — no activity yet:**
```
  No activity yet. Solve problems to appear here.
```

**User profile — no activity:**
```
  You haven't posted or solved anything yet.
  [Browse problems] to find something to work on.
```

**Notifications — empty:**
```
  All caught up. No new notifications.
```

Each empty state has: a short message, a clear call to action, and a link/button to the logical next step.

### Error States

**404 — Not Found (custom)**
```
┌─────────────────────────────────────────────────┐
│                                                  │
│      Problem not found.                          │
│      It may have been deleted or you              │
│      followed a broken link.                     │
│                                                  │
│      [ Back to Feed ]                            │
│                                                  │
└─────────────────────────────────────────────────┘
```

**401/403 — Unauthorized / Forbidden (custom)**
```
┌─────────────────────────────────────────────────┐
│                                                  │
│      Session expired.                            │
│      Please sign in again.                       │
│                                                  │
│      [ Sign In ]                                 │
│                                                  │
└─────────────────────────────────────────────────┘
```

**Network Error (toast notification)**
- Non-blocking toast at bottom of screen: "Something went wrong. [Retry]"
- Auto-dismiss after 5 seconds if no action

**Validation Error (inline)**
- Form field turns red, error message below the field: "Title must be at least 5 characters"
- Standard Pydantic validation errors mapped to field-level UI feedback

### Problem-Solution Relationship in UI
- **Problems are the primary entity** — the feed, search results, and cards are all problems
- **Solutions live inside problem cards** — they are children, not peers
- Solutions are never shown as standalone cards in the feed
- When search matches a solution's text, the parent problem is shown with a "Matched in solution by X" preview
- This keeps the UI clean: one entity type to browse, one hierarchy to understand

## Categories & Tags

### Approach: Hybrid (Fixed Categories + Freeform Tags)
- **Fixed top-level categories** — admin-managed, user must pick one when submitting. Provides structure.
- **Freeform tags** — user can add optional tags for specificity. Provides flexibility.
- Admins can merge/rename/retire tags periodically to prevent sprawl.

### Starting Categories (ASIC-Oriented)

| Category | Covers |
|---|---|
| RTL Design | Coding, architecture, microarchitecture |
| Verification | UVM, formal, simulation, coverage |
| Physical Design | PnR, floorplanning, timing closure |
| DFT | Scan, BIST, ATPG |
| EDA Tools | Tool bugs, licensing, setup, flow issues |
| Methodology | Coding standards, flow improvements, best practices |
| IT / Infra | Servers, compute farm, VPN, storage |
| Scripts / Automation | Internal scripts, CI/CD, regression flows |
| Documentation | Missing docs, outdated docs, knowledge gaps |
| Other | Catch-all |

These are starting suggestions — adjust to match actual team vocabulary.

## Auth Design (Detailed)

### Primary: Microsoft 365 / Azure AD OAuth
- "Sign in with Microsoft" button — one click, uses existing work account
- Restrict to company tenant (only org members can sign in)
- Pulls name, email, avatar from Microsoft profile automatically
- Implementation: FastAPI + `authlib` library (OIDC flow with Azure AD)
- Requires Azure App Registration (one-time setup in Azure Portal):
  1. Register app in Azure AD → get Client ID + Client Secret
  2. Set redirect URI to `https://yourapp.internal/api/auth/callback`
  3. Grant `openid`, `profile`, `email` permissions
  4. Restrict to single tenant

### Secondary: Magic Link (Email)
- For contractors, external collaborators, or anyone without M365
- User enters work email → receives login link with signed token → clicks → logged in
- Implementation: FastAPI generates a signed JWT link, sends via SMTP
- Email service: internal SMTP server (most ASIC companies have one), or Resend free tier as fallback

### Session Management
- JWT tokens issued by FastAPI after successful auth
- Stored as HttpOnly secure cookies (not localStorage — prevents XSS)
- Access token (short-lived, 15 min) + refresh token (7 days)
- Auto-provision user record in Postgres on first login
- No registration flow, no password management, no "forgot password"

### Roles (Simple)
- **User** — can post problems, upstar, comment, submit solutions, claim
- **Admin** — can manage categories, merge tags, accept solutions on any problem, manage users
- Role stored in users table, default = user, manually promoted by existing admin

### Permissions
- Accept a solution: problem poster OR any admin
- Delete/edit a problem: problem poster OR any admin
- Delete a comment: comment author OR any admin
- Everything else (post, vote, claim, comment): any authenticated user

## Backend Architecture

### Tech Stack
| Layer | Technology | Why |
|---|---|---|
| Reverse Proxy | **NGINX** | Serves frontend static files, proxies `/api/*` to FastAPI, handles TLS, rate limiting |
| API Server | **FastAPI** (Python 3.11+) | Async, fast, auto-generates OpenAPI docs, great ecosystem |
| ORM | **SQLAlchemy 2.0** + asyncpg | Async Postgres driver, mature ORM, Alembic for migrations |
| Database | **PostgreSQL 16** | Full-text search built-in, JSON support, best data integrity, standard for Python stacks |
| Auth | **authlib** + **python-jose** | OAuth2/OIDC for Azure AD, JWT handling |
| Migrations | **Alembic** | Schema versioning, rollback support |
| Validation | **Pydantic v2** | Already built into FastAPI, request/response schemas |
| Task Queue | **None for v1** | Not needed at this scale. If notifications become async-heavy later, add Celery + Redis |

### Why PostgreSQL (Not MySQL)
- Built-in full-text search (`tsvector`, `ts_rank`) — no need for Elasticsearch
- Better JSON/JSONB support for flexible metadata fields
- Better constraint enforcement and data integrity
- Standard pairing with SQLAlchemy + asyncpg in async Python
- Superior indexing options (GIN indexes for search, partial indexes)

### System Architecture

```
┌─────────────────────────────────────────────────────┐
│                      NGINX                          │
│  - Serves frontend static build (React/Vite)        │
│  - Reverse proxies /api/* → FastAPI (port 8000)     │
│  - TLS termination (self-signed or internal CA)     │
│  - Rate limiting, gzip compression                  │
│  - WebSocket proxy (for real-time notifications)    │
├─────────────────────────────────────────────────────┤
│                     FastAPI                         │
│  - REST API endpoints                               │
│  - Auth (Azure AD OAuth + magic link)               │
│  - Business logic                                   │
│  - WebSocket endpoint (notifications)               │
│  Port: 8000 (internal only, not exposed)            │
├─────────────────────────────────────────────────────┤
│                   PostgreSQL 16                      │
│  - All application data                             │
│  - Full-text search indexes                         │
│  Port: 5432 (internal only)                         │
└─────────────────────────────────────────────────────┘
```

### FastAPI Project Structure

```
backend/
├── app/
│   ├── main.py                  # FastAPI app, startup, middleware
│   ├── config.py                # Settings (env vars, secrets)
│   ├── database.py              # Async engine, session factory
│   ├── auth/
│   │   ├── router.py            # /auth/login, /auth/callback, /auth/magic-link
│   │   ├── dependencies.py      # get_current_user, require_admin
│   │   └── jwt.py               # Token creation/validation
│   ├── models/                  # SQLAlchemy ORM models
│   │   ├── __init__.py          # Public API: re-exports all models
│   │   ├── user.py
│   │   ├── problem.py
│   │   ├── solution.py
│   │   ├── comment.py
│   │   ├── vote.py
│   │   ├── category.py
│   │   ├── attachment.py
│   │   ├── notification.py
│   │   └── watch.py
│   ├── schemas/                 # Pydantic BaseModel request/response schemas
│   │   ├── __init__.py          # Public API: re-exports all schemas
│   │   ├── user.py
│   │   ├── problem.py
│   │   ├── solution.py
│   │   ├── comment.py
│   │   ├── attachment.py
│   │   ├── notification.py
│   │   └── watch.py
│   ├── routers/                 # API route handlers
│   │   ├── __init__.py          # Public API: collects all routers
│   │   ├── problems.py          # CRUD + search + upstar + claim + duplicate
│   │   ├── solutions.py         # CRUD + versioning + upvote
│   │   ├── comments.py          # CRUD, threaded
│   │   ├── users.py             # Profile, leaderboard, preferences
│   │   ├── categories.py        # Admin CRUD
│   │   ├── tags.py              # Autocomplete, admin merge
│   │   ├── attachments.py       # Upload, serve, delete
│   │   ├── watches.py           # Watch/unwatch problems
│   │   └── notifications.py     # List, mark read, WebSocket
│   ├── services/                # Business logic layer
│   │   ├── __init__.py          # Public API
│   │   ├── notification.py      # Teams webhook + in-app + email digest
│   │   ├── search.py            # Full-text search queries
│   │   ├── attachment.py        # File storage, validation
│   │   └── claim_expiry.py      # Auto-expire stale claims (14 day check)
│   └── common/                  # Shared utilities
│       ├── __init__.py          # Public API
│       ├── utils.py             # General helpers (slugify, pagination, etc.)
│       ├── exceptions.py        # Custom exception classes
│       ├── logging.py           # Structured logging setup
│       └── abc.py               # Abstract base classes (if needed)
├── alembic/                     # Database migrations
│   ├── alembic.ini
│   └── versions/
├── requirements.txt
├── Dockerfile
└── tests/
    ├── conftest.py              # Shared fixtures (test DB, test client, auth)
    ├── test_problems.py
    ├── test_solutions.py
    ├── test_comments.py
    ├── test_auth.py
    ├── test_attachments.py
    └── test_notifications.py
```

### API Endpoints (Key Routes)

```
Auth:
  POST   /api/auth/login              → Redirect to Azure AD
  GET    /api/auth/callback            → Handle OAuth callback, issue JWT
  POST   /api/auth/magic-link          → Send magic link email
  GET    /api/auth/magic-link/verify   → Verify magic link token
  POST   /api/auth/refresh             → Refresh access token
  GET    /api/auth/me                  → Current user profile

Problems:
  GET    /api/problems                 → List (paginated, filterable, sortable)
  POST   /api/problems                 → Create
  GET    /api/problems/{id}            → Detail
  PATCH  /api/problems/{id}            → Update (author/admin)
  DELETE /api/problems/{id}            → Delete (author/admin)
  POST   /api/problems/{id}/upstar     → Toggle upstar
  POST   /api/problems/{id}/claim      → Claim problem
  DELETE /api/problems/{id}/claim      → Unclaim (self or admin)
  POST   /api/problems/{id}/duplicate  → Flag as duplicate (provide original_id)
  GET    /api/problems/search?q=       → Full-text search

Solutions:
  GET    /api/problems/{id}/solutions          → List solutions for problem
  POST   /api/problems/{id}/solutions          → Submit solution
  POST   /api/solutions/{id}/versions          → Submit new version
  GET    /api/solutions/{id}/versions          → Version history
  POST   /api/solutions/{id}/upvote            → Toggle upvote
  POST   /api/solutions/{id}/accept            → Accept (author/admin)

Comments:
  GET    /api/{parent_type}/{id}/comments      → List comments
  POST   /api/{parent_type}/{id}/comments      → Create comment
  DELETE /api/comments/{id}                    → Delete (author/admin)

Users:
  GET    /api/users/{id}               → Profile + stats
  GET    /api/leaderboard              → Leaderboard (filterable by time range)
  PATCH  /api/users/me/preferences     → Update notification preferences

Categories & Tags:
  GET    /api/categories               → List all
  POST   /api/categories               → Create (admin)
  PATCH  /api/categories/{id}          → Update (admin)
  PATCH  /api/categories/reorder       → Reorder (admin, body: [{id, sort_order}])
  DELETE /api/categories/{id}          → Deactivate (admin, soft delete)
  GET    /api/tags                     → List all (with usage counts, admin)
  GET    /api/tags/autocomplete?q=     → Tag search for autocomplete
  PATCH  /api/tags/{id}               → Rename (admin)
  POST   /api/tags/merge               → Merge tags (admin)
  DELETE /api/tags/{id}               → Delete (admin)

Admin:
  GET    /api/admin/users              → List all users (admin)
  PATCH  /api/admin/users/{id}/role    → Promote/demote (admin)
  PATCH  /api/admin/users/{id}/status  → Activate/deactivate (admin)
  GET    /api/admin/flagged            → Flagged content (pending duplicates, reported posts)
  POST   /api/admin/deanonymize/{type}/{id} → Reveal anonymous author (admin, logged)
  GET    /api/admin/config             → App config (app name, etc.)
  PATCH  /api/admin/config             → Update app config (admin)

Attachments:
  POST   /api/attachments              → Upload file (multipart/form-data)
  GET    /api/attachments/{id}         → Download (or served directly via NGINX)
  DELETE /api/attachments/{id}         → Delete (uploader or admin)

Watches:
  POST   /api/problems/{id}/watch      → Watch a problem (body: {level})
  DELETE /api/problems/{id}/watch      → Unwatch
  GET    /api/users/me/watches         → List all watched problems

Notifications:
  GET    /api/notifications            → User's notifications (paginated)
  PATCH  /api/notifications/{id}/read  → Mark as read
  POST   /api/notifications/read-all   → Mark all as read
  WS     /api/ws/notifications         → Real-time via WebSocket
```

### NGINX Config (Key Parts)

```nginx
# Serves frontend SPA, proxies API to FastAPI
server {
    listen 443 ssl;
    server_name problemboard.internal;

    # TLS (internal CA or self-signed)
    ssl_certificate     /etc/nginx/certs/cert.pem;
    ssl_certificate_key /etc/nginx/certs/key.pem;

    # Frontend — serve static files, fallback to index.html for SPA routing
    location / {
        root /usr/share/nginx/html;
        try_files $uri $uri/ /index.html;
    }

    # API — proxy to FastAPI
    location /api/ {
        proxy_pass http://api:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # WebSocket — for real-time notifications
    location /api/ws/ {
        proxy_pass http://api:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

### Notifications
- **In-app:** WebSocket connection for real-time bell icon updates. Stored in a `notifications` table.
- **Microsoft Teams:** Outgoing webhook to a Teams channel for high-signal events (new problem posted, solution accepted). Uses Teams Incoming Webhook connector — simple POST request, no bot framework needed.
- **Email (optional):** Digest or per-event via internal SMTP. Not v1 unless easy to wire up.

### Search
- PostgreSQL full-text search using `tsvector` columns on problems (title + description) and comments (body)
- GIN index for fast lookups
- `ts_rank` for relevance scoring
- Search endpoint returns results across problems, solutions, and comments with highlighted matches

### Infrastructure Sizing (~100 users, expandable)
- Single server is more than enough: 4 CPU, 8 GB RAM, 50 GB disk
- PostgreSQL handles this trivially — no read replicas, no caching layer needed
- Comfortable headroom to 500+ users on this setup
- If the app grows beyond 500 concurrent users, add Redis for caching hot queries and session store

### Deployment (Podman Compose)

```yaml
# podman-compose.yml
services:
  nginx:
    image: docker.io/library/nginx:alpine
    ports:
      - "443:443"
      - "80:80"
    volumes:
      - ./frontend/dist:/usr/share/nginx/html:ro,Z
      - ./nginx.conf:/etc/nginx/nginx.conf:ro,Z
      - ./certs:/etc/nginx/certs:ro,Z
      - attachments:/data/attachments:ro,Z    # serve attachments directly
    depends_on:
      - api

  api:
    build: ./backend
    environment:
      - DATABASE_URL=postgresql+asyncpg://problemboard:${DB_PASSWORD}@db:5432/problemboard
      - AZURE_CLIENT_ID=${AZURE_CLIENT_ID}
      - AZURE_CLIENT_SECRET=${AZURE_CLIENT_SECRET}
      - AZURE_TENANT_ID=${AZURE_TENANT_ID}
      - JWT_SECRET=${JWT_SECRET}
      - SMTP_HOST=${SMTP_HOST}
      - ATTACHMENT_STORAGE_PATH=/data/attachments
      - ATTACHMENT_MAX_SIZE_MB=10
    volumes:
      - attachments:/data/attachments:Z       # write uploads here
    depends_on:
      - db
    expose:
      - "8000"

  db:
    image: docker.io/library/postgres:16-alpine
    environment:
      - POSTGRES_DB=problemboard
      - POSTGRES_USER=problemboard
      - POSTGRES_PASSWORD=${DB_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data:Z
    expose:
      - "5432"

volumes:
  pgdata:
  attachments:
```

Notes on Podman vs Docker:
- Use `podman-compose` (or `podman compose` with the compose plugin)
- `:Z` suffix on volume mounts for SELinux relabeling (common on RHEL/CentOS)
- Full image paths (`docker.io/library/...`) since Podman doesn't default to Docker Hub
- Rootless by default — better security posture for internal deployment
- Secrets via `.env` file (not hardcoded in compose file)
- `podman generate systemd` can create systemd services for auto-restart on reboot

## Decisions Log

| Question | Decision | Rationale |
|---|---|---|
| Team size | ~100 users, design for growth to 500+ | Current headcount, room to grow |
| Hosting | **Podman Compose**, on-prem | Rootless containers, no Docker daemon dependency, better security |
| Database | PostgreSQL 16 | Full-text search, JSON, data integrity, Python ecosystem standard |
| Notifications | Teams webhook + in-app (WebSocket) | Already on M365, low integration effort |
| Permissions | Problem poster + admins accept solutions | Simple, avoids politics |
| Search | Postgres full-text search | Built-in, no extra infra, sufficient for this scale |
| Mobile | Responsive web only | Internal tool, no native app needed |
| Task queue | None for v1 | Overkill at this scale, add Celery later if needed |
| Frontend framework | React + Vite (AI-generated) | Fast builds, AI tools generate React well |

## Azure AD App Registration (Step-by-Step for IT Team)

This is a one-time setup that gives the app permission to use "Sign in with Microsoft."
Hand these steps to whoever has Azure AD admin access:

1. Go to [Azure Portal](https://portal.azure.com) → Azure Active Directory → App registrations → New registration
2. Name: "Problem Board" (or whatever you want users to see on the login screen)
3. Supported account types: **"Accounts in this organizational directory only"** (single tenant)
4. Redirect URI: Select "Web" → enter `https://problemboard.internal/api/auth/callback`
5. Click Register
6. On the app's Overview page, copy:
   - **Application (client) ID** → this is `AZURE_CLIENT_ID`
   - **Directory (tenant) ID** → this is `AZURE_TENANT_ID`
7. Go to Certificates & secrets → New client secret → copy the value → this is `AZURE_CLIENT_SECRET`
8. Go to API permissions → Add a permission → Microsoft Graph → Delegated:
   - `openid`
   - `profile`
   - `email`
9. Click "Grant admin consent" for the org

That's it. Put those 3 values (`AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_CLIENT_SECRET`) in the app's `.env` file.

## Local Development Setup (No Azure Admin Required)

### Auth During Development

Three options, use whichever fits your situation:

**Option A: Dev Auth Bypass (recommended for daily dev)**
- Add a `DEV_AUTH_BYPASS=true` environment variable
- When enabled, a `/api/auth/dev-login` endpoint auto-creates and logs in a test user
- No real auth flow at all — just click "Dev Login" and you're in
- Frontend shows a dev banner so you never confuse it with prod
- **Must be disabled in production** — enforce via config check on startup

```python
# In auth/router.py (dev only)
@router.post("/auth/dev-login")
async def dev_login(role: str = "user"):
    if not settings.DEV_AUTH_BYPASS:
        raise HTTPException(403, "Dev login disabled")
    # Create/fetch test user, issue JWT, return cookie
```

**Option B: Magic Link with Console Output**
- Use magic link auth, but instead of sending email, print the link to the FastAPI console
- Set `SMTP_HOST=console` (or similar flag) to redirect emails to stdout
- You click the link from the terminal output — full auth flow, no SMTP server needed

**Option C: Personal Azure Account (for testing real Microsoft login)**
- Create a free Azure account at https://azure.microsoft.com/free with a personal Microsoft account
- You become the admin of your own tenant — full control
- Follow the same App Registration steps above, but:
  - Redirect URI: `http://localhost:8000/api/auth/callback` (http, not https)
  - Tenant: your personal tenant
- Swap to company tenant values when deploying to prod
- Only you can sign in (personal account only), but the OAuth flow is identical

### Dev Environment Compose

```yaml
# podman-compose.dev.yml
services:
  api:
    build: ./backend
    ports:
      - "8000:8000"           # exposed directly, no NGINX in dev
    environment:
      - DATABASE_URL=postgresql+asyncpg://problemboard:devpass@db:5432/problemboard
      - DEV_AUTH_BYPASS=true   # remove for real auth testing
      - JWT_SECRET=dev-secret-not-for-production
      - ENV=development
    volumes:
      - ./backend/app:/app/app:Z   # hot reload
    command: uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
    depends_on:
      - db

  db:
    image: docker.io/library/postgres:16-alpine
    ports:
      - "5432:5432"           # exposed for direct DB access during dev
    environment:
      - POSTGRES_DB=problemboard
      - POSTGRES_USER=problemboard
      - POSTGRES_PASSWORD=devpass
    volumes:
      - pgdata_dev:/var/lib/postgresql/data:Z

volumes:
  pgdata_dev:
```

Notes:
- No NGINX in dev — FastAPI serves directly on port 8000, frontend runs on Vite dev server (port 5173) with API proxy
- Postgres port exposed for direct access via `psql` or pgAdmin during dev
- Hot reload via mounted source + `--reload` flag
- Frontend dev: `cd frontend && npm run dev` (Vite proxies `/api/*` to `localhost:8000`)

### Dev Workflow Summary

```
1. podman-compose -f podman-compose.dev.yml up -d
2. cd frontend && npm run dev
3. Open http://localhost:5173
4. Click "Dev Login" → you're in
5. Edit backend code → auto-reloads
6. Edit frontend code → auto-reloads (Vite HMR)
```

## Code Conventions

### Module Structure
Every package/directory follows a consistent structure:

```python
# __init__.py — Public API
# Every directory exposes its public interface via __init__.py.
# Other modules import from the package, not from internal files.

# Example: app/models/__init__.py
from app.models.user import User
from app.models.problem import Problem, ProblemUpstar
from app.models.solution import Solution, SolutionVersion, SolutionUpvote
from app.models.comment import Comment
from app.models.category import Category, Tag
from app.models.attachment import Attachment
from app.models.notification import Notification
from app.models.watch import Watch

__all__ = [
    "User", "Problem", "ProblemUpstar",
    "Solution", "SolutionVersion", "SolutionUpvote",
    "Comment", "Category", "Tag",
    "Attachment", "Notification", "Watch",
]
```

### Schema Convention
- All request/response schemas live in `schemas/*.py` as **Pydantic `BaseModel`** (not stdlib `dataclass`)
- Pydantic is FastAPI's native validation/serialization layer — using `dataclass` would fight the framework
- Naming: `ProblemCreate`, `ProblemUpdate`, `ProblemResponse`, `ProblemListResponse`

```python
# Example: app/schemas/problem.py
from pydantic import BaseModel, Field
from datetime import datetime

class ProblemCreate(BaseModel):
    title: str = Field(..., min_length=5, max_length=200)
    description: str = Field(..., min_length=10)
    category_id: int
    tag_ids: list[int] = []
    is_anonymous: bool = False

class ProblemResponse(BaseModel):
    id: int
    title: str
    description: str
    status: str
    upstar_count: int
    author_name: str | None  # None if anonymous
    created_at: datetime

    model_config = {"from_attributes": True}
```

### Common / Utils
- `app/common/utils.py` — general helpers (slugify, pagination helpers, timestamp formatting)
- `app/common/exceptions.py` — custom HTTP exceptions with consistent error response format
- `app/common/logging.py` — structured logging configuration
- `app/common/abc.py` — abstract base classes for services if polymorphism is needed (e.g., `NotificationChannel` ABC with `TeamsChannel`, `EmailChannel`, `InAppChannel` implementations)

### Abstract Base Classes (When Needed)
```python
# app/common/abc.py
from abc import ABC, abstractmethod

class NotificationChannel(ABC):
    @abstractmethod
    async def send(self, user_id: int, title: str, body: str) -> None: ...

# app/services/notification.py
class TeamsChannel(NotificationChannel):
    async def send(self, user_id: int, title: str, body: str) -> None:
        # POST to Teams webhook
        ...

class InAppChannel(NotificationChannel):
    async def send(self, user_id: int, title: str, body: str) -> None:
        # Insert into notifications table + push via WebSocket
        ...
```

### Import Convention
```python
# Always import from the package public API, not internal files
from app.models import User, Problem          # YES
from app.models.user import User              # NO (internal)

from app.schemas import ProblemCreate         # YES
from app.schemas.problem import ProblemCreate # NO (internal)
```

### Logging
- Use Python's `structlog` or stdlib `logging` with structured JSON output
- Every request logged with: method, path, user_id, status_code, duration_ms
- Business events logged: problem created, solution submitted, claim made, solution accepted
- Log levels: DEBUG (dev), INFO (prod default), WARNING (degraded), ERROR (failures)
- Correlation ID per request (middleware injects UUID, propagated to all log entries)

```python
# Example log output (JSON, one line)
{"timestamp": "2026-04-14T10:30:00Z", "level": "info", "event": "problem_created",
 "user_id": 42, "problem_id": 187, "category": "verification", "request_id": "abc-123"}
```

## Idempotency

### Principle
Every API call should be safe to retry. Network failures, double-clicks, and client retries must not create duplicate data or corrupt state.

### Toggle Endpoints (Naturally Idempotent)
Upstar, upvote, watch — these check "does a record exist for this user + target?" and toggle:
- Exists → delete it (un-upstar/un-upvote/unwatch), return new state
- Doesn't exist → create it, return new state
- Calling twice in a row = no-op (back to original state). Safe.

### Claim (Naturally Idempotent)
- If user is already a claimer on this problem → return 200 with current claim, don't duplicate
- DB: unique constraint on `(problem_id, user_id)` in claims table prevents duplicates at the DB level

### Create Endpoints (Need Idempotency Key)
Problem creation, solution submission, comment posting — these are not naturally idempotent. Posting twice = two problems.

Solution: client sends an `Idempotency-Key` header (UUID generated client-side):

```python
# Middleware or dependency
async def check_idempotency(request: Request, db: AsyncSession):
    key = request.headers.get("Idempotency-Key")
    if not key:
        return None  # no key = no dedup (backwards compatible)
    existing = await db.get(IdempotencyRecord, key)
    if existing:
        return existing.cached_response  # return same response as first call
    return None  # first time, proceed normally

# After successful creation, store:
# IdempotencyRecord(key=key, cached_response=response_json, expires_at=now+24h)
```

### Data Model Addition
```
idempotency_records:
  - key (PK, string — the UUID from the header)
  - cached_response (JSONB)
  - created_at
  - expires_at (24h TTL, cleaned up periodically)
```

### DB-Level Safety Nets
Even without idempotency keys, unique constraints prevent the worst cases:
- `UNIQUE(problem_id, user_id)` on upstars, upvotes, claims
- `UNIQUE(user_id, problem_id)` on watches
- `UNIQUE(solution_id, version_number)` on solution versions (auto-increment prevents gaps)

## Duplicate Problem Detection

### Level 1: Manual Flagging (Primary Mechanism)
Already designed — any user flags, admin/poster confirms. See "Duplicate Handling" in Status Transition Rules.

### Level 2: Similar Problem Suggestions (Proactive)
When a user types a problem title in the submit form, show similar existing problems in real-time. Prevents duplicates before they're created.

**UX:**
```
┌─────────────────────────────────────────────┐
│ Title: [regression farm timing out on la... ]│
├─────────────────────────────────────────────┤
│ Similar existing problems:                   │
│  ⚡ #89 "Regression farm timeouts after      │
│         storage migration" (Solved, 14 ⭐)   │
│  ⚡ #134 "Long-running regressions killed    │
│          by farm scheduler" (Open, 8 ⭐)     │
│                                              │
│ Is your problem already listed above?        │
│ If so, upstar it instead of posting a new    │
│ one.                                         │
└─────────────────────────────────────────────┘
```

**Implementation:**
- Frontend debounces title input (300ms), calls existing search endpoint:
  `GET /api/problems/search?q={title_text}&limit=5`
- Same Postgres full-text search already built for the search feature — no new backend work
- Results shown as a dropdown below the title field
- Non-blocking — user can always dismiss and post anyway

**Why not automated blocking or ML matching:**
- Complexity not justified at ~100 users
- False positives are worse than duplicates (frustrating if the system blocks a legitimate new problem)
- Manual flagging + search suggestions catch 90% of duplicates with zero complexity

## Implementation Decisions

| Item | Decision | Notes |
|---|---|---|
| Pagination | Cursor-based for feeds, offset for admin/search | Cursor avoids skipped/duplicate items on active feeds |
| Rate limiting | NGINX `limit_req` — 30 req/s per IP for API, 5 req/s for auth | Prevents abuse, simple config |
| CORS | Not needed | Same domain via NGINX reverse proxy |
| Testing | pytest + httpx `AsyncClient` + factory_boy for fixtures | `conftest.py` with test DB, auto-rollback per test |
| Logging | Structured JSON via `structlog` | Correlation ID per request, business events logged |
| Markdown | `react-markdown` on frontend | Renders problem descriptions, comments, solution descriptions |
| Frontend framework | React 18 + Vite + TypeScript | AI-generated, fast builds |

## Frontend URL Routes

```
/                           → Landing/login page (unauthenticated)
/feed                       → Feed/home (default after login)
/problems/new               → Submit problem form
/problems/:id               → Problem detail (solutions, comments)
/problems/:id/solutions/new → Submit solution (or inline modal)
/search?q=                  → Search results
/leaderboard                → Leaderboard
/profile/:id                → User profile
/settings                   → User settings/preferences
/admin/categories           → Admin: manage categories
/admin/tags                 → Admin: manage tags
/admin/users                → Admin: manage users
/admin/flagged              → Admin: flagged content
/ai-search                  → AI search (v2 placeholder, grayed out)
```

- All routes except `/` require authentication — unauthenticated users redirect to `/`
- `/admin/*` routes require admin role — non-admins get 403 page
- Problem URLs are shareable: `problemboard.internal/problems/42` works as a direct link

## Link Previews (Open Graph)

When a problem URL is shared in Teams/email/Slack, it should render a rich preview card instead of a raw URL. This is critical for adoption in a Teams-heavy org — people share links constantly.

**Implementation:** Server-side rendered `<meta>` tags for problem pages:

```html
<!-- For problemboard.internal/problems/42 -->
<meta property="og:title" content="Regression farm keeps timing out" />
<meta property="og:description" content="⭐ 14 upstars · 3 solutions · Status: Claimed" />
<meta property="og:site_name" content="Aion Bulletin" />
<meta property="og:type" content="article" />
<meta property="og:url" content="https://problemboard.internal/problems/42" />
```

**How it works with a React SPA:**
- SPA alone can't do this (meta tags must be in the initial HTML response, before JS loads)
- Solution: NGINX or a lightweight middleware intercepts requests with a bot/crawler User-Agent (Teams link unfurler, Slack bot, etc.) and returns a minimal HTML page with the correct `<meta>` tags
- Regular users get the normal SPA — no SSR framework needed
- FastAPI endpoint: `GET /api/problems/{id}/meta` returns title, description, status for the preview

## Pinned Problems

Admins can pin important problems to the top of the feed. Pinned problems appear above the normal sorted list, visually distinct.

**UX:**
```
┌─────────────────────────────────────────────────────┐
│ 📌 PINNED                                           │
│ ┌─────────────────────────────────────────────────┐ │
│ │ Regression farm migration this weekend —         │ │
│ │ all teams read before Friday                     │ │
│ │ [IT / Infra] ⭐ 47 · 5 solutions · Pinned by Admin │
│ └─────────────────────────────────────────────────┘ │
│                                                      │
│ ALL PROBLEMS                                         │
│ ┌─────────────────────────────────────────────────┐ │
│ │ (normal feed below)                              │ │
```

**Rules:**
- Only admins can pin/unpin (button on problem detail page)
- Max 3 pinned problems at a time (prevents feed clutter)
- Pinned problems have a subtle highlight background and 📌 indicator
- Pinned status is a boolean + timestamp on the problems table: `is_pinned`, `pinned_at`

**Data model addition:**
```
problems table — add:
  - is_pinned (bool, default false)
  - pinned_at (timestamp, nullable)
  - pinned_by (FK → users, nullable)
```

**API addition:**
```
POST   /api/problems/{id}/pin      → Pin (admin only)
DELETE /api/problems/{id}/pin      → Unpin (admin only)
```

## Edit History

**Decision:** Allow editing, show "(edited)" label, store full edit history.

**Rules:**
- Problem poster can edit their own problem title/description at any time
- Comment author can edit their own comment at any time
- Edits show "(edited 2h ago)" next to the timestamp — clickable to view history
- Full edit history stored (prevents bait-and-switch: post something, get upstars, change content)
- Solutions are NOT directly editable — instead, submit a new version (already designed)
- Admins can edit any problem/comment (for moderation)

**Edit history UX:**
```
Problem Title (edited 2h ago)    ← clickable
                │
                ▼ (dropdown/modal)
┌─────────────────────────────────────────┐
│ Edit History                             │
│                                          │
│ Current (2h ago):                        │
│   "Regression farm keeps timing out      │
│    after storage migration"              │
│                                          │
│ Original (3 days ago):                   │
│   "Farm is slow"                         │
└─────────────────────────────────────────┘
```

**Data model addition:**
```
edit_history:
  - id
  - parent_type (problem/comment)
  - parent_id
  - editor_id (FK → users)
  - field_name (title/description/body)
  - old_value (text)
  - new_value (text)
  - edited_at
```

**API addition:**
```
GET /api/{parent_type}/{id}/history    → Edit history for a problem or comment
```

## Solution Sorting

Within a problem detail page, solutions are sorted by:

1. **Accepted first** — accepted solution always at the top, highlighted with green border
2. **Then by upvote count** (descending) — most upvoted surfaces next
3. **Then by creation date** (newest first) — tiebreaker

This mirrors Stack Overflow's approach: best answer on top, community-ranked below.

User can toggle to "Newest first" if they want chronological order (small toggle on the solutions tab).

## Remaining Setup Steps (Pre-Implementation)

1. **Azure AD App Registration** — follow steps above, hand to IT admin
2. **Server/VM allocation** — single machine, 4 CPU / 8 GB RAM / 50 GB disk, Podman installed
3. **Internal DNS entry** — e.g., `problemboard.internal` pointing to the server
4. **TLS certificate** — from internal CA, or self-signed for initial deployment
5. **Internal SMTP server address** — for magic link emails (ask IT for hostname + port)
6. **Teams channel + incoming webhook URL** — for notifications (any team member can create this in Teams → channel → Connectors → Incoming Webhook)
