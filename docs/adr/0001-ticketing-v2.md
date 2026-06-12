# ADR 0001 — Ticketing v2

- Status: Accepted (WP1, 2026-05-17)
- Deciders: Orchestrator agent + WP1 design subagent
- Related: `docs/specs/ticketing-v2.md`

## Context

The repo just completed a 3-step migration that split the historical `Problem` (bulletin/bounty domain) from `Ticket` (agent-driven Kanban work-tracker). `tickets` is now a clean, flat table with `type ∈ {epic,story,task,subtask,bug}`, a global `TKT-N` display ID, and a single self-FK for hierarchy.

The agent-Kanban roadmap calls for true JIRA-equivalent project management: agents and users coordinate across multiple initiatives, each with its own backlog, sprints, components, and members. The current flat table cannot express that without a container concept.

We need to decide, before writing migrations:
1. Where Project lives (own table vs. another `type`).
2. How many workflows / states v2 supports.
3. How agent actions are attributed to the specific run-step that produced them.
4. How the hierarchy maps onto the existing `tickets.parent_id` self-FK.

## Decision

1. **Project is its own table (`projects`).** It owns members, components, sprints, the per-project display-ID sequence, and the default assignee. The five work-item types — Workpackage, Epic, Story, Task, Subtask (plus `bug`) — remain rows in `tickets`, distinguished by the `type` enum (Single-Table-Inheritance pattern), with a NOT NULL `project_id` FK.
2. **One standard workflow for v2**: `Backlog → To Do → In Progress → In Review → Done`, with `Blocked` and `Cancelled` as side-states reachable from any active state. Reopen from `done`/`cancelled` is allowed and audited. Per-project workflows are explicitly deferred to v2.1.
3. **Agent attribution is first-class**: every audit-producing table (transitions, comments, links, attachments, audit_log, ticket-create) carries `actor_type`, `actor_id`, and `agent_step_id` (nullable; required when `actor_type='agent'`). The agent tracer is one click away from any audit row.
4. **Hierarchy stays on `tickets.parent_id`** with denormalised `epic_id` for fast epic-rollup queries. Cross-project parenting is disallowed in v2; use `ticket_links` (`blocks`, `relates_to`, `clones`) for cross-project references.

## Alternatives Considered

- **(a) Project as a 7th value in the `ticket_type` enum.** Rejected. A project is a *container* with members, settings, sequences, and defaults; a work item is a unit of work with status / assignee / sprint. Conflating the two would force every Project-only column onto `tickets` and pollute every query with `WHERE type <> 'project'`. The schema cost (one more table, one more FK) is far cheaper than the query and validation cost.
- **(b) Per-project custom workflows in v2.** Rejected for v2 (deferred to v2.1). Custom workflows require a workflow-definition entity, transition rules per project, and a per-project state enum or state table. None of that is needed for the agent-Kanban use case today, and locking in a global workflow keeps the frontend and the agent prompts simple.
- **(c) Polymorphic actor via just the existing `actor_type` / `actor_id` pair.** Rejected as insufficient. `actor_type='agent'` tells you *which* agent acted but not *which step of which run* — and the value of agent attribution is precisely the ability to jump to the exact step. We extend the pair with `agent_step_id` rather than introducing a third table.
- **(d) Drop the `tickets` table and start fresh.** Rejected. The `a8_finalize_ticket_split` migration just completed; another full rewrite would invalidate work-in-progress branches. We backfill a "Default" project (§10 of the spec) and additively migrate.

## Consequences

### Positive
- Clean separation: container concerns (members, sequences, archive) on `projects`; work-item concerns on `tickets`. Queries are simple and indexable.
- Hierarchy queries stay O(depth) thanks to `parent_id` + denorm `epic_id`. JIRA-style "all stories under epic X" is a single indexed lookup.
- Agent attribution is uniform across every write surface — agent tracer integration is mechanical, not bespoke per surface.
- v2.1 promotions (fix-versions table, per-project workflows, worklogs) are additive — no rewrite required.

### Negative
- One more FK on every ticket write; one more required join for project-key resolution. Mitigated by `(project_id, status)` partial index.
- Display-ID sequences are per-project (one Postgres `SEQUENCE` per project). Operational cost: DDL on project-create. Mitigated by service-layer that creates the sequence in the same transaction as the project row.
- Backfill of `epic_id` denorm is an extra migration step; future parent-changes must also maintain the denorm in the service layer.

### Neutral
- The `ticket_links` enum changes (`parent_of`/`child_of` removed, `clones`/`is_cloned_by` added). Hierarchy is exclusively on `tickets.parent_id`; cross-project hierarchy is explicitly out of scope for v2.
