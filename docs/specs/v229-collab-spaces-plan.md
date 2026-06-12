# v2.29 — Collaboration Spaces & Agents-as-Users: Slice Plan

Goal: evolve problem-bulletin into a small JIRA replacement for human+agent
collaboration — minimal/clean UI, a sharing space for agent/AI/LLM usage, a
bounty space, first-class agent teammates, clean search/filter, and a full
demo. Delivered as sequential TDD vertical slices, each with a validatable
end goal. Subagents are fanned out per slice.

## Slices

| Slice | Scope | Validatable end goal |
|---|---|---|
| S0 | Baseline verification of dirty tree (+2661 lines prior work) | Test suites at/above prior baseline (306F/691P backend per STATE.md; 86 frontend); checkpoint commit |
| S1 | Usability audit (dev + user personas) | `docs/specs/usability-audit-v229.md` with P0/P1/P2 findings + acceptance criteria |
| S2 | UI/UX redesign — minimal & clean, functionality intact | Frontend tests green; visual smoke via `make up` |
| S3 | Shared space (`/share`) for agent/AI/LLM usage posts | Create/list/vote post end-to-end; pytest + vitest green |
| S4 | Bounty space (`/bounties`) | Post→claim→award flow end-to-end; tests green |
| S5 | Agents-as-users: assign→auto-enqueue run→structured summary comment | Integration test of full loop passes |
| S6 | Search/filter cleanup incl. new entities | Search e2e specs green |
| S7 | Demo seed across all surfaces | `make demo` populates every main page coherently |
| S8 | System verification (unit/integration/e2e/system) | All suites green vs baseline; walkthrough doc |

## S3 — SharePost schema (draft)

Follows the `ProjectLesson` dual-author pattern (`app/models/project_lesson.py`):

- `share_posts`: id (uuid pk, gen_random_uuid), title TEXT NOT NULL,
  body TEXT NOT NULL (markdown), `author_user_id` FK users SET NULL /
  `author_agent_id` FK agent_accounts SET NULL + `source IN ('user','agent')`
  CHECK, tags TEXT[] DEFAULT '{}', `ticket_id` FK tickets SET NULL (optional
  link), `agent_run_id` FK agent_run SET NULL (optional link),
  upvotes INT NOT NULL DEFAULT 0 (denormalized; votes in join table),
  created_at/updated_at timestamptz.
- `share_post_votes`: (post_id, voter_id, voter_type) unique — mirrors the
  voting service pattern.
- Comments: reuse polymorphic pattern? No — keep slice thin: v1 ships
  without threaded comments; link to a ticket for discussion instead.
- Routes: `GET/POST /api/v1/share-posts`, `GET /api/v1/share-posts/{id}`,
  `PUT /api/v1/share-posts/{id}/vote`. Audit events via `AuditService`.

## S4 — Bounty schema (draft)

- `bounties`: id, title, description, `points` INT > 0, status
  `open|claimed|awarded|withdrawn` CHECK, target: `ticket_id` FK nullable
  XOR `problem_id` FK nullable (or neither = standalone idea),
  poster (user FK), claimant_id/claimant_type (user|agent, co-null pair —
  mirrors ticket assignee constraint), awarded_at, created_at.
- Award flow only by poster; claim by any actor incl. agents.
- Leaderboard integration: awarded bounty points feed existing
  `LeaderboardService`.

## S5 — Agents-as-users gap closure

Existing: AgentAccount, AgentRun queue (idempotent), audit feed, mentions,
notifications (`ticket_assigned` kind, WP25). Gaps to close:

1. `TicketService.assign()` to an agent → auto-enqueue `AgentRun`
   (today runs are enqueued separately).
2. Run completion → structured `TicketComment` from the agent: summary,
   file/location pointers, links (response_body → formatted body) + optional
   status transition.
3. Frontend: assignee picker surfaces agents (people service already unified);
   TicketDetail shows run status timeline inline.

## Conventions

- TDD: failing test first per WP; ralph-loop style WP commits
  (`v2.29-WPxx: ...`).
- No regressions vs S0 baseline; legacy bulletin failures (~306) are
  out of scope.
- Each slice executed by a dedicated subagent with a self-contained prompt;
  main agent verifies the slice's end goal before unblocking the next.
