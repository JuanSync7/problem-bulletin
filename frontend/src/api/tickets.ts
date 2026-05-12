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
 */

export type TicketStatus =
  | "todo"
  | "in_progress"
  | "in_review"
  | "blocked"
  | "done"
  | "cancelled";

export type TicketPriority = "lowest" | "low" | "medium" | "high" | "highest";

export type TicketType = "epic" | "story" | "task" | "subtask" | "bug";

export type TicketLinkType =
  | "blocks"
  | "is_blocked_by"
  | "duplicates"
  | "is_duplicate_of"
  | "relates_to";

export interface TicketDTO {
  id: string;
  key?: string;
  project_id?: string;
  seq_number?: number;
  ticket_type?: TicketType;
  status: TicketStatus;
  priority?: TicketPriority;
  title: string;
  description?: string | null;
  parent_id?: string | null;
  assignee_id?: string | null;
  assignee_type?: string | null;
  labels?: string[];
  custom_fields?: Record<string, unknown> | null;
  story_points?: number | null;
  due_date?: string | null;
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
    let env: ErrorEnvelope | null = null;
    try {
      const body = await res.json();
      env = body?.error ?? null;
    } catch {
      /* non-json body */
    }
    throw new ApiError(res.status, env);
  }
  // 204 / empty
  if (res.status === 204) return undefined as unknown as T;
  return (await res.json()) as T;
}

// ---------------------------------------------------------------------------
// Read endpoints
// ---------------------------------------------------------------------------

export interface ListTicketsParams {
  status?: TicketStatus[];
  assignee_id?: string;
  parent_id?: string;
  label?: string[];
  limit?: number;
  offset?: number;
}

export async function listTickets(
  params: ListTicketsParams = {},
): Promise<{ items: TicketDTO[] }> {
  const usp = new URLSearchParams();
  for (const s of params.status ?? []) usp.append("status", s);
  for (const l of params.label ?? []) usp.append("label", l);
  if (params.assignee_id) usp.set("assignee_id", params.assignee_id);
  if (params.parent_id) usp.set("parent_id", params.parent_id);
  if (params.limit != null) usp.set("limit", String(params.limit));
  if (params.offset != null) usp.set("offset", String(params.offset));
  const qs = usp.toString();
  return request(`${BASE}${qs ? `?${qs}` : ""}`);
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
  ticket_type?: TicketType;
  priority?: TicketPriority;
  parent_id?: string;
  assignee_id?: string;
  assignee_type?: string;
  labels?: string[];
  custom_fields?: Record<string, unknown>;
  story_points?: number;
  due_date?: string;
  project_id?: string;
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
): Promise<CommentDTO> {
  return request(`${BASE}/${encodeURIComponent(idOrKey)}/comments`, {
    method: "POST",
    body: JSON.stringify({ body }),
  });
}

export async function linkTickets(
  sourceIdOrKey: string,
  targetId: string,
  linkType: TicketLinkType,
): Promise<LinkDTO> {
  return request(`${BASE}/${encodeURIComponent(sourceIdOrKey)}/links`, {
    method: "POST",
    body: JSON.stringify({ target_id: targetId, link_type: linkType }),
  });
}
