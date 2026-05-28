/**
 * Typed REST client for the agent-kanban ticket endpoints.
 *
 * All routes are mounted under `/api/v1/tickets/*` on the backend. The fetch
 * wrappers below carry session cookies (`credentials: "include"`) so they
 * behave the same as the existing auth code in `hooks/useAuth.ts`.
 *
 * Error envelopes from the backend follow:
 *   { error: { code, message, details, correlation_id } }
 * On a non-2xx response we throw an :class:`ApiError` that exposes the parsed
 * envelope so UI layers can render code-specific messages (e.g. "conflict" for
 * stale-version rollback).
 *
 * v2.13-WP03: error parsing routes through ``parseApiError`` so both the
 * unified envelope and any not-yet-migrated legacy ``{detail}`` body surface
 * a useful message.
 */
import { parseApiError } from "./errors";

export type TicketStatus =
  | "backlog"
  | "todo"
  | "in_progress"
  | "in_review"
  | "blocked"
  | "done"
  | "cancelled";

export type TicketPriority = "low" | "medium" | "high" | "urgent";

export type TicketType =
  | "workpackage"
  | "epic"
  | "story"
  | "task"
  | "subtask"
  | "bug";

/**
 * NOTE: `parent_of` and `child_of` are tombstoned in Ticketing v2 — they remain
 * in the enum for historical reads but the API rejects writes using them and the
 * frontend MUST NOT offer them in any "Add link" dropdown. Hierarchy lives on
 * `tickets.parent_id` only.
 */
export type TicketLinkType =
  | "blocks"
  | "is_blocked_by"
  | "duplicates"
  | "is_duplicate_of"
  | "relates_to"
  | "clones"
  | "is_cloned_by"
  | "parent_of"
  | "child_of";

/** Subset of TicketLinkType that is writable in v2 (excludes tombstoned values). */
export const WRITABLE_LINK_TYPES: TicketLinkType[] = [
  "blocks",
  "is_blocked_by",
  "duplicates",
  "is_duplicate_of",
  "relates_to",
  "clones",
  "is_cloned_by",
];

/** Refuses a tombstoned link type on the client side before hitting the API. */
export function assertWritableLinkType(t: TicketLinkType): void {
  if (t === "parent_of" || t === "child_of") {
    throw new Error(
      `Link type "${t}" is tombstoned in Ticketing v2. Use tickets.parent_id for hierarchy.`,
    );
  }
}

export interface TicketDTO {
  id: string;
  /**
   * Per-project display identifier: `<PROJECT_KEY>-<n>` (e.g. `DEF-42`).
   * In v2 this is no longer the global `TKT-N` form — it is sourced from the
   * per-project Postgres sequence and populated by the service layer.
   */
  display_id?: string;
  seq_number?: number;
  type?: TicketType;
  status: TicketStatus;
  priority?: TicketPriority;
  title: string;
  description?: string | null;
  parent_id?: string | null;
  reporter_id?: string | null;
  reporter_type?: string | null;
  assignee_id?: string | null;
  /**
   * v2.6-WP45: narrowed from `string` to the literal union so consumers
   * (PersonPicker chips, Kanban avatars, inline assignee display) can
   * distinguish human vs agent assignees without re-querying. The field
   * is optional to avoid regressions across the existing codebase; only
   * fixtures and code paths that produce/consume the field should depend
   * on it being set. Backend has emitted this since v2.1.
   */
  assignee_type?: "user" | "agent" | null;
  labels?: string[];
  custom_fields?: Record<string, unknown> | null;
  story_points?: number | null;
  due_date?: string | null;
  // v2 project-management additions
  project_id?: string | null;
  project_key?: string | null;
  sprint_id?: string | null;
  component_id?: string | null;
  epic_id?: string | null;
  fix_versions?: string[];
  resolution?: string | null;
  resolved_at?: string | null;
  // v2.1 WP6: "last touched by" aggregate. Source of truth for the
  // Kanban card's agent-activity badge (no more `reporter_type` fallback).
  last_actor_type?: "user" | "agent" | null;
  last_actor_id?: string | null;
  last_activity_at?: string | null;
  last_agent_step_id?: string | null;
  version: number;
  created_at?: string;
  updated_at?: string | null;
  // tolerate extra keys returned by .to_dict()
  [k: string]: unknown;
}

export interface CommentDTO {
  id: string;
  ticket_id: string;
  author_id: string;
  author_type: string;
  body: string;
  correlation_id?: string;
  created_at?: string;
}

export interface LinkDTO {
  id: string;
  source_id: string;
  target_id: string;
  link_type: TicketLinkType;
  created_by?: string | null;
  created_by_type?: string | null;
}

export interface SubtreeRow {
  depth: number;
  ticket: TicketDTO;
}

export interface ErrorEnvelope {
  code: string;
  message: string;
  details?: Record<string, unknown>;
  correlation_id?: string;
}

export class ApiError extends Error {
  status: number;
  envelope: ErrorEnvelope | null;
  constructor(status: number, envelope: ErrorEnvelope | null, message?: string) {
    super(message ?? envelope?.message ?? `HTTP ${status}`);
    this.status = status;
    this.envelope = envelope;
  }
}

const BASE = "/api/v1/tickets";

async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const res = await fetch(path, {
    credentials: "include",
    ...init,
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      ...(init.headers ?? {}),
    },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const parsed = parseApiError(res, body);
    const env: ErrorEnvelope = {
      code: parsed.code,
      message: parsed.message,
      details: (parsed.details ?? undefined) as Record<string, unknown> | undefined,
      correlation_id: parsed.correlation_id ?? undefined,
    };
    throw new ApiError(res.status, env);
  }
  // 204 / empty
  if (res.status === 204) return undefined as unknown as T;
  return (await res.json()) as T;
}

// ---------------------------------------------------------------------------
// Read endpoints
// ---------------------------------------------------------------------------

/**
 * Generic page envelope for v2.1-WP10 paginated list endpoints.
 * Mirrors the backend ``Page[T]`` shape: items + opaque ``next_cursor`` +
 * optional ``total``. ``next_cursor === null`` means terminal page.
 * ``total`` is set only when the backend can compute it cheaply.
 */
export interface Page<T> {
  items: T[];
  next_cursor: string | null;
  total: number | null;
}

/**
 * v2.1-WP11 — tickets list endpoint surfaces per-status counts.
 *
 * ``column_counts`` is populated when the request scopes by
 * ``project_id``; ``null`` otherwise. Keys are ``TicketStatus`` values;
 * all seven workflow statuses are always present (the backend seeds
 * zeros). The aggregate is independent of ``limit`` / ``cursor`` so
 * Load-more pagination never undercounts a Kanban column for the
 * WIP-limit chip display.
 */
export interface TicketsPage extends Page<TicketDTO> {
  column_counts?: Partial<Record<TicketStatus, number>> | null;
}

/**
 * v2.1-WP10: filter sentinels.
 *
 * The Kanban historically encoded "None"/"Unassigned" with client-side
 * sentinel strings (`__none__`, `__unassigned__`) and stripped them out
 * before hitting the API. WP10 promoted these to first-class backend
 * query syntax:
 *
 *  - `"null"` literal: match WHERE col IS NULL
 *  - `"me"` literal (assignee_id only): backend resolves to the
 *    authenticated actor's UUID
 *  - undefined / unset: filter not applied
 *  - UUID: straight equality
 *
 * The TS union type below documents the contract; the route validates.
 */
export type IdFilter = string | "null" | undefined;
export type AssigneeFilter = string | "null" | "me" | undefined;

export interface ListTicketsParams {
  status?: TicketStatus[];
  assignee_id?: AssigneeFilter;
  parent_id?: string;
  label?: string[];
  limit?: number;
  /** v2.1-WP10: cursor pagination. Opaque; pass through unchanged. */
  cursor?: string | null;
  /** Legacy offset — accepted but cursor is preferred. */
  offset?: number;
  // Ticketing v2 filters — spec §8.
  project_id?: string;
  project_key?: string;
  sprint_id?: IdFilter;
  component_id?: IdFilter;
  epic_id?: IdFilter;
  type?: TicketType[];
  /**
   * v2.3-WP22: sort column.
   * - ``"created_at"`` (default) — backward-compatible ordering.
   * - ``"last_activity_at"`` — orders by the most-recently-touched
   *   timestamp so terminal-status tickets (done/cancelled) stay
   *   surfaced past the 500-row fetch cap on busy projects.
   */
  order_by?: "created_at" | "last_activity_at";
}

export async function listTickets(
  params: ListTicketsParams = {},
): Promise<TicketsPage> {
  const usp = new URLSearchParams();
  for (const s of params.status ?? []) usp.append("status", s);
  for (const l of params.label ?? []) usp.append("label", l);
  for (const t of params.type ?? []) usp.append("type", t);
  if (params.assignee_id !== undefined)
    usp.set("assignee_id", params.assignee_id);
  if (params.parent_id) usp.set("parent_id", params.parent_id);
  if (params.project_id) usp.set("project_id", params.project_id);
  if (params.project_key) usp.set("project_key", params.project_key);
  if (params.sprint_id !== undefined) usp.set("sprint_id", params.sprint_id);
  if (params.component_id !== undefined)
    usp.set("component_id", params.component_id);
  if (params.epic_id !== undefined) usp.set("epic_id", params.epic_id);
  if (params.limit != null) usp.set("limit", String(params.limit));
  if (params.offset != null) usp.set("offset", String(params.offset));
  if (params.cursor) usp.set("cursor", params.cursor);
  if (params.order_by) usp.set("order_by", params.order_by);
  const qs = usp.toString();
  const raw = await request<{
    items: TicketDTO[];
    next_cursor?: string | null;
    total?: number | null;
    column_counts?: Partial<Record<TicketStatus, number>> | null;
  }>(`${BASE}${qs ? `?${qs}` : ""}`);
  return {
    items: raw.items ?? [],
    next_cursor: raw.next_cursor ?? null,
    total: raw.total ?? null,
    column_counts: raw.column_counts ?? null,
  };
}

export async function getTicket(idOrKey: string): Promise<TicketDTO> {
  return request(`${BASE}/${encodeURIComponent(idOrKey)}`);
}

export async function searchTickets(
  q: string,
  opts: { limit?: number; offset?: number } = {},
): Promise<{ items: TicketDTO[] }> {
  const usp = new URLSearchParams();
  if (q) usp.set("q", q);
  if (opts.limit != null) usp.set("limit", String(opts.limit));
  if (opts.offset != null) usp.set("offset", String(opts.offset));
  return request(`${BASE}/search?${usp.toString()}`);
}

export async function getSubtree(
  idOrKey: string,
  maxDepth = 5,
): Promise<{ items: SubtreeRow[] }> {
  return request(
    `${BASE}/${encodeURIComponent(idOrKey)}/subtree?max_depth=${maxDepth}`,
  );
}

// ---------------------------------------------------------------------------
// Write endpoints
// ---------------------------------------------------------------------------

export interface CreateTicketBody {
  title: string;
  description?: string;
  type?: TicketType;
  priority?: TicketPriority;
  parent_id?: string;
  assignee_id?: string;
  assignee_type?: string;
  labels?: string[];
  custom_fields?: Record<string, unknown>;
  story_points?: number;
  due_date?: string;
  // v2: one of project_id / project_key is required by the service.
  // WP3 resolves precedence project_id > project_key > DEF.
  project_id?: string;
  project_key?: string;
  sprint_id?: string | null;
  component_id?: string | null;
  fix_versions?: string[];
}

export async function createTicket(body: CreateTicketBody): Promise<TicketDTO> {
  return request(BASE, { method: "POST", body: JSON.stringify(body) });
}

export interface UpdateTicketBody {
  version: number;
  title?: string;
  description?: string;
  priority?: TicketPriority;
  parent_id?: string | null;
  labels?: string[];
  custom_fields?: Record<string, unknown>;
  story_points?: number;
  due_date?: string;
  assignee_id?: string | null;
  assignee_type?: string | null;
}

export async function updateTicket(
  idOrKey: string,
  body: UpdateTicketBody,
): Promise<TicketDTO> {
  return request(`${BASE}/${encodeURIComponent(idOrKey)}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export async function transitionTicket(
  idOrKey: string,
  toStatus: TicketStatus,
  reason?: string,
): Promise<TicketDTO> {
  return request(`${BASE}/${encodeURIComponent(idOrKey)}/transition`, {
    method: "POST",
    body: JSON.stringify({ to_status: toStatus, reason }),
  });
}

export async function claimTicket(idOrKey: string): Promise<TicketDTO> {
  return request(`${BASE}/${encodeURIComponent(idOrKey)}/claim`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export interface AssignBody {
  assignee_id?: string | null;
  assignee_type?: string | null;
  expected_version: number;
}

export async function assignTicket(
  idOrKey: string,
  body: AssignBody,
): Promise<TicketDTO> {
  return request(`${BASE}/${encodeURIComponent(idOrKey)}/assign`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function addComment(
  idOrKey: string,
  body: string,
  mentions?: string[],
): Promise<CommentDTO> {
  const payload: Record<string, unknown> = { body };
  if (mentions && mentions.length > 0) payload.mentions = mentions;
  return request(`${BASE}/${encodeURIComponent(idOrKey)}/comments`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// ---------------------------------------------------------------------------
// v2.1-WP7 — Activity feed (transitions ∪ comments ∪ links)
// ---------------------------------------------------------------------------

export interface TransitionActivityItem {
  kind: "transition";
  id: string;
  ticket_id: string;
  from_status: TicketStatus | null;
  to_status: TicketStatus;
  actor_type: "user" | "agent";
  actor_id: string;
  agent_step_id?: string | null;
  reason?: string | null;
  created_at: string;
}

export interface CommentActivityItem {
  kind: "comment";
  id: string;
  ticket_id: string;
  body: string;
  mentions?: string[];
  actor_type: "user" | "agent";
  actor_id: string;
  agent_step_id?: string | null;
  created_at: string;
  edited_at?: string | null;
}

export interface LinkActivityItem {
  kind: "link";
  id: string;
  source_ticket_id: string;
  target_ticket_id: string;
  link_type: TicketLinkType;
  actor_type: "user" | "agent";
  actor_id: string;
  agent_step_id?: string | null;
  created_at: string;
}

export type ActivityItem =
  | TransitionActivityItem
  | CommentActivityItem
  | LinkActivityItem;

export interface ActivityPage {
  items: ActivityItem[];
  next_cursor: string | null;
  /** Total unfiltered event count — present only on the first page (cursor=null). */
  total: number | null;
}

export interface ListActivityParams {
  /** CSV of additional sources to merge. */
  include?: ("comments" | "links")[];
  limit?: number;
  /** Opaque cursor from a previous ActivityPage.next_cursor (v2.2-WP16). */
  cursor?: string;
}

export async function listActivity(
  idOrKey: string,
  params: ListActivityParams = {},
): Promise<ActivityPage> {
  const usp = new URLSearchParams();
  if (params.include && params.include.length > 0) {
    usp.set("include", params.include.join(","));
  }
  if (params.limit != null) usp.set("limit", String(params.limit));
  if (params.cursor != null) usp.set("cursor", params.cursor);
  const qs = usp.toString();
  return request(
    `${BASE}/${encodeURIComponent(idOrKey)}/transitions${qs ? `?${qs}` : ""}`,
  );
}

// ---------------------------------------------------------------------------
// v2.23-WP03 — Typed consumer for GET /api/v1/tickets/{id_or_key}/watchers.
//
// Backend route returns ``Page[TicketWatcherRead]`` (see
// app/routes/tickets.py:713). The Pydantic schema is closed-with-extras
// (``extra="allow"``) — the TS interface below pins the 5 known fields;
// any backend-only additions slot into the wrapper's index-free shape.
//
// ``watcher_type`` discriminator mirrors the ``assignee_type`` pattern
// landed in WP47-WP49 (see PersonPicker chip rendering for the
// human-vs-agent visual cue).
// ---------------------------------------------------------------------------
export interface TicketWatcher {
  id: string;
  ticket_id: string;
  watcher_id: string;
  watcher_type: "user" | "agent";
  created_at: string;
}

export async function listTicketWatchers(
  idOrKey: string,
): Promise<Page<TicketWatcher>> {
  return request(`${BASE}/${encodeURIComponent(idOrKey)}/watchers`);
}

// ---------------------------------------------------------------------------
// v2.24-WP03 — Typed consumer for GET /api/v1/tickets/{id_or_key}/attachments.
//
// Backend route returns ``Page[TicketAttachmentRead]`` (see
// app/routes/tickets.py:786). The Pydantic schema is closed-with-extras
// (``extra="allow"``) — the TS interface below pins the 10 known fields;
// any backend-only additions slot into the wrapper's index-free shape.
//
// ``uploaded_by_type`` discriminator mirrors the ``watcher_type`` /
// ``assignee_type`` pattern. Net-new typed consumer — no existing call
// sites today (integration is a separate concern per the v2.23-WP03
// precedent).
// ---------------------------------------------------------------------------
export interface TicketAttachment {
  id: string;
  ticket_id: string;
  uploaded_by: string;
  uploaded_by_type: "user" | "agent";
  filename: string;
  content_type: string;
  byte_size: number;
  storage_path: string;
  agent_step_id: string | null;
  created_at: string;
}

export async function listTicketAttachments(
  idOrKey: string,
): Promise<Page<TicketAttachment>> {
  return request(`${BASE}/${encodeURIComponent(idOrKey)}/attachments`);
}

export async function linkTickets(
  sourceIdOrKey: string,
  targetId: string,
  linkType: TicketLinkType,
): Promise<LinkDTO> {
  assertWritableLinkType(linkType);
  return request(`${BASE}/${encodeURIComponent(sourceIdOrKey)}/links`, {
    method: "POST",
    body: JSON.stringify({ target_id: targetId, link_type: linkType }),
  });
}
