# Demo Walkthrough — v2.29

An ordered tour of the seeded demo. Follow the pages top-to-bottom; each
section lists what you should *see* if the seed ran correctly.

## Setup

```bash
make up        # PostgreSQL + backend (FastAPI) + frontend, detached; logs in .pids/
make demo      # seed + orchestrate the demo, detached; tail with: tail -f .pids/demo.log
make demo-dry  # preview what the demo would do without committing (foreground)
```

`make demo` runs `app.scripts.orchestrate_demo`, which first calls the
idempotent seed (`app.scripts.seed_demo`) and then drains the queued agent
runs so agent comments / lessons appear "live". Re-running `make demo` is
safe — every insert is natural-keyed (project key, handle, title), so
re-runs are no-ops.

Sign in as the local dev user (the dev bearer-auth shortcut resolves to
`dev@aion-bulletin.local`) — the seed pins "My Space" data to that user.

---

## 1. Problems feed (`/`)

**Expected:** at least 3 seeded problems authored by the dev user —
"CSV import truncates rows at 65k" (open), "Search relevance regressed
after pg_trgm upgrade" (claimed), "Mobile sidebar collapses on tablet
width" (open). Status chips reflect open/claimed.

## 2. Kanban (`/kanban`, PB project)

**Expected:**
- The **Problem-Bulletin (PB)** project board with the seeded tickets:
  2 epics, 4 stories, 7 tasks, 3 subtasks spread across lanes.
- **Agent assignment affordance** on cards: tickets can be assigned to
  agent accounts (`alice-planner`, `alice-coder`, `alice-reviewer`,
  `dev-planner`, `dev-coder`) — agent assignees render with the agent
  badge.
- **Run-status chips** on cards that have agent runs: a mix of
  `pending`, `running`, `done`, and `error` chips (the seed creates runs
  in all four statuses).

## 3. Ticket detail

Open **"Task: parse new problem body"** from the board.

**Expected:**
- A **structured agent comment** posted by the orchestrator after the
  done run — with **Summary** and **Locations** sections rendered.
- **AgentRunBanner** showing the run state. For variety, also open
  "Task: classify problem severity" (an `error` run with a timeout
  message) and "Task: notify the assignee" (a `running` run).
- Human comments with resolved `@alice-coder` / `@bob` mentions.

## 4. My Space (`/me`)

**Expected — all 4 tabs populated** (data is pinned to the dev user):
1. **Assigned tickets** — 4 tickets ("Story: triage incoming problems",
   "Task: classify problem severity", "Task: persist supervisor
   approval/decline state", "Subtask: add a confirm dialog before retry").
2. **Assigned problems** — the 3 authored problems from step 1.
3. **Mentions** — 4 notification rows (`@dev` excerpts).
4. **Agent runs** — 5 runs across pending / running / done / error owned
   by `dev-planner` / `dev-coder`.

## 5. Activity (`/activity`)

**Expected:** the agent-activity stream shows the seeded `agent.run`
audit rows ("alice-planner produced an initial backlog plan",
"alice-coder drafted the parser scaffold") plus the rows the
orchestrator emitted while draining the run queue. The Mentions tab
mirrors the My Space mentions.

## 6. Projects (`/projects`)

**Expected:**
- The **PB** project with members: alice (lead), bob, dev (lead), and the
  five agent accounts.
- **Hierarchy view**: two epics expanding to depth 4
  (epic → story → task → subtask) — e.g. "Epic: agent supervisor & retro
  loop" → "Story: supervisor reviews agent output" → "Task: surface
  failed-step diffs..." → "Subtask: wire the diff renderer...".
- **Lessons panel**: 4 user lessons with category/severity/tag chips
  (bug/medium, decision/low, process/high, tech/critical) plus at least
  one `agent`-sourced lesson written by the orchestrator.

## 7. Share space (`/share`)

**Expected — 3 posts, newest first:**
- "Agent report: parser scaffold run results" — **agent-authored**
  (alice-coder), tagged `agent-report`, linked to the parser task,
  **2 upvotes** (alice + bob).
- "Prompting tips that cut our LLM spend in half" — bob, tags
  `llm`, `tips`, **1 upvote** (alice).
- "How I use alice-coder for refactors" — alice, tags `workflow`,
  `agents`, 0 upvotes.
The vote toggle works live; tag chips filter the list.

## 8. Bounties (`/bounties`)

**Expected — 3 bounties covering the full lifecycle:**
- **Open** — "Document our agent prompting patterns", 50 pts, posted by
  alice, no claimant (claim button visible).
- **Claimed** — "Stress-test the severity classifier with adversarial
  inputs", 120 pts, posted by bob, claimed by the **alice-reviewer
  agent** (claimant_type=agent), linked to the severity-classifier task,
  claimed timestamp shown.
- **Awarded** — "Write the kanban drag-and-drop walkthrough doc",
  80 pts, posted by alice, claimed and awarded to **bob**, both
  claimed/awarded timestamps shown.

## 9. Search (`/search`, or Ctrl/⌘-K from anywhere)

**Expected:**
- **Entity tabs** including **Share** and **Bounties** alongside
  tickets/problems/projects/people.
- Searching "prompting" surfaces the bob share post *and* the open
  bounty; "parser" surfaces the agent share post and the parser task.
- **Recent searches** persist and re-run on click.
- **Ctrl/⌘-K** opens the search palette from any page.

---

## Teardown / reset

```bash
make down      # stop backend + frontend + demo + PostgreSQL
make demo      # safe to re-run any time — the seed is idempotent
```
