# Usability Audit — v2.29 (dev + user personas)

Read-only code-walk audit of the frontend (App.tsx, MainLayout, Sidebar, Feed,
Submit, CreateTicket, Kanban, TicketDetail, MeSpace, Activity, Projects,
Search). Feeds slices S2 (redesign) and S6 (search/filter cleanup) of
`v229-collab-spaces-plan.md`.

## P0 (breaks/blocks core flows)

### 1. Dual Submit/Create-Ticket path — confusing mental model
- **Where**: `frontend/src/App.tsx` (routes `/submit` + `/tickets/new`), `frontend/src/layouts/Sidebar.tsx`
- **Issue**: Sidebar lists both "Submit Problem" and "Create Ticket" top-level with no guidance on when to use which.
- **Fix**: Remove both from main nav; "Create Ticket" becomes a Kanban-toolbar/Projects CTA, "Submit Problem" becomes a Problems-feed CTA.
- **Acceptance**: Devs create tickets from the board; users discover problem submission from the Problems feed.

### 2. No agent-assignment affordance on Kanban card
- **Where**: `frontend/src/pages/Kanban/TicketCard.tsx`; drawer assign exists in `TicketDetailDrawer.tsx`
- **Fix**: Clickable assignee pill / mini PersonPicker on the card.
- **Acceptance**: Assign an agent in ≤1 click from the board.

### 3. Agent run status hidden until TicketDetail
- **Where**: `TicketCard.tsx` (only a 🤖 last-actor badge), `TicketDetail/AgentRunBanner.tsx`
- **Fix**: Run-status chip on the card (Done/Running/Failed, color-coded).
- **Acceptance**: Run health triagable from the board.

## P1 (significant friction)

4. **Sidebar has 14+ items** (`Sidebar.tsx`) → group into Browse / Work / Tools / Admin (conditional); ≤8 main items.
5. **Problems vs Tickets parallel hierarchies** (Feed vs Kanban) → "Create Ticket from Problem" on ProblemDetail; "Related problems" on TicketDetail; explicit mental model: Problems = reported issues, Tickets = work items.
6. **No visual status in MeSpace agent runs** (`MeSpace/index.tsx`) → colored status badges.
7. **Cmd/Ctrl-K not discoverable** (`GlobalSearchBar`) → shortcuts help affordance.
8. **Empty states lack CTAs** (Feed, MeSpace, Projects) → every empty state gets a primary CTA using the EmptyState component.
9. **Kanban toolbar wraps badly on mobile** (`Kanban/index.tsx` toolbar) → collapse controls into a Filters menu <1024px.
10. **Search results missing agent-kind badge** (`Search.tsx`) → render assignee_type chip.

## P2 (polish)

11. **Theme inconsistency**: warm tan/gold-lime main palette vs cool slate agent palette (`App.css`) → unify (also in scope for the S2 full redesign).
12. **Activity subtitle verbose** (`Activity/index.tsx`) → one line.
13. **TicketDetail lacks document.title** → `"<display_id> — <title>"`.
14. **Assignee chip shows ID slice not name** (`TicketDetailDrawer.tsx`) → resolve display name on load.
15. **No column count badges on Kanban** → "In Progress (12)", WIP-limit colored.
16. **Mentions lack context excerpt** (Activity/MeSpace) → inline 1-line excerpt.
17. **Search page doesn't surface recent searches** (`Search.tsx`) → reuse GlobalSearchBar's localStorage recents on empty state.

## Information architecture (recommended)

- **Browse**: Home, Problems, Projects, Leaderboard
- **Work**: Kanban Board, My Space, Activity, *(new)* Share, *(new)* Bounties
- **Tools**: AI Search, Settings
- **Admin** (admins only): Users, Moderation, Config
- Create actions move into context (board toolbar, feed CTA).
- Breadcrumb "Projects / KEY" on project-scoped pages.

## Disposition

- P0 1–3 + P1 4, 8, 9 + P2 11 → S2 (redesign slice)
- P1 5 → S2 (IA) + S5 (agents-as-users links)
- P1 6, P2 13–16 → S2/S5
- P1 7, 10, P2 12, 17 → S6 (search/filter slice)
