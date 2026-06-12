/**
 * Typed REST client for Ticketing v2 project endpoints.
 *
 * Mirrors the route surface added by WP3:
 *   GET    /api/v1/projects
 *   POST   /api/v1/projects
 *   GET    /api/v1/projects/{idOrKey}
 *   GET    /api/v1/projects/{id}/members
 *   GET    /api/v1/projects/{id}/components
 *   POST   /api/v1/projects/{id}/components
 *
 * Uses the same fetch envelope conventions as `api/tickets.ts` (session cookies,
 * ApiError on non-2xx). Imports `ApiError` from there to avoid duplication.
 */

import { ApiError, type ErrorEnvelope, type Page } from "./tickets";
import { parseApiError } from "./errors";
import { parseJson } from "./_jsonParse";

export interface ProjectDTO {
  id: string;
  key: string;
  name: string;
  description?: string | null;
  lead_id?: string | null;
  lead_type?: "user" | "agent" | null;
  default_assignee_id?: string | null;
  default_assignee_type?: string | null;
  icon?: string | null;
  archived?: boolean;
  archived_at?: string | null;
  created_by?: string;
  created_by_type?: string;
  created_at?: string;
  updated_at?: string | null;
  version?: number;
  /** v2.1-WP11: per-status WIP limits, e.g. ``{ todo: 5, in_progress: 3 }``. */
  wip_limits?: Record<string, number>;
  [k: string]: unknown;
}

export interface ProjectMemberDTO {
  id: string;
  project_id: string;
  member_id: string;
  member_type: "user" | "agent";
  role: "lead" | "member" | "viewer";
  added_by?: string;
  added_by_type?: string;
  added_at?: string;
  created_at: string;
}

export interface ComponentDTO {
  id: string;
  project_id: string;
  name: string;
  description?: string | null;
  lead_id?: string | null;
  lead_type?: string | null;
  created_at?: string;
  updated_at?: string | null;
}

const BASE = "/api/v1/projects";

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
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
    // v2.13-WP03: tolerate both unified envelope + legacy {detail}.
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
  if (res.status === 204) return undefined as unknown as T;
  return parseJson<T>(res);
}

export interface ListProjectsParams {
  includeArchived?: boolean;
  memberOfMe?: boolean;
}

export async function listProjects(
  params: ListProjectsParams = {},
): Promise<Page<ProjectDTO>> {
  const usp = new URLSearchParams();
  if (params.includeArchived) usp.set("archived", "true");
  if (params.memberOfMe) usp.set("member_of", "me");
  const qs = usp.toString();
  const raw = await request<{
    items: ProjectDTO[];
    next_cursor?: string | null;
    total?: number | null;
  }>(`${BASE}${qs ? `?${qs}` : ""}`);
  return {
    items: raw.items ?? [],
    next_cursor: raw.next_cursor ?? null,
    total: raw.total ?? null,
  };
}

export async function getProject(idOrKey: string): Promise<ProjectDTO> {
  return request(`${BASE}/${encodeURIComponent(idOrKey)}`);
}

export interface CreateProjectBody {
  key: string;
  name: string;
  description?: string;
  lead_id?: string;
  default_assignee_id?: string;
  default_assignee_type?: "user" | "agent";
  icon?: string;
}

export async function createProject(body: CreateProjectBody): Promise<ProjectDTO> {
  return request(BASE, { method: "POST", body: JSON.stringify(body) });
}

/**
 * v2.1-WP11 — generic project patch.
 *
 * The backend ``PATCH /api/v1/projects/{id}`` is OCC-gated: the caller
 * must supply the current ``version``. A mismatch raises ``ApiError``
 * with HTTP 409 (envelope ``code === "conflict"``); callers should
 * refetch and retry.
 */
export interface UpdateProjectPatch {
  name?: string;
  description?: string | null;
  lead_id?: string | null;
  lead_type?: "user" | "agent" | null;
  wip_limits?: Record<string, number>;
}

export async function updateProject(
  id: string,
  patch: UpdateProjectPatch,
  version: number,
): Promise<ProjectDTO> {
  return request(`${BASE}/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify({ ...patch, version }),
  });
}

export async function listMembers(
  projectId: string,
): Promise<{ items: ProjectMemberDTO[] }> {
  return request(`${BASE}/${encodeURIComponent(projectId)}/members`);
}

export async function listComponents(
  projectId: string,
): Promise<{ items: ComponentDTO[] }> {
  return request(`${BASE}/${encodeURIComponent(projectId)}/components`);
}

// ---------------------------------------------------------------------------
// B1 — Project hierarchy types, guards, and client helper
// ---------------------------------------------------------------------------

/**
 * Minimal ticket shape needed for the hierarchy guard.
 * Uses the same TicketDTO wire format (open interface via index signature).
 */
export interface HierarchyTicketDTO {
  id: string;
  seq_number: number;
  display_id: string;
  title: string;
  type: string;
  status: string;
  priority: string;
  reporter_id: string;
  reporter_type: "user" | "agent";
  version: number;
  created_at: string;
  labels: string[];
  fix_versions: string[];
  custom_fields: Record<string, unknown>;
  [k: string]: unknown;
}

/**
 * One node in the project hierarchy tree.
 *
 * Fields mirror ``HierarchyRow`` in ``app/schemas/hierarchy.py``.
 */
export interface HierarchyRow {
  ticket: HierarchyTicketDTO;
  depth: number;
  parent_id: string | null;
  ordinal: number;
}

/**
 * Response envelope for ``GET /api/v1/projects/{project_id}/hierarchy``.
 */
export interface ProjectHierarchyResponse {
  items: HierarchyRow[];
}

/**
 * Runtime predicate guard for ``HierarchyRow``.
 *
 * Checks required scalar fields: ticket (with id:string), depth, parent_id, ordinal.
 * Parent_id must be null or string. Accepts extra fields (open interface).
 */
export function isHierarchyRow(x: unknown): x is HierarchyRow {
  if (x === null || typeof x !== "object") return false;
  const o = x as Record<string, unknown>;
  if (typeof o["depth"] !== "number") return false;
  if (typeof o["ordinal"] !== "number") return false;
  if (o["parent_id"] !== null && typeof o["parent_id"] !== "string") return false;
  const ticket = o["ticket"];
  if (ticket === null || typeof ticket !== "object") return false;
  const t = ticket as Record<string, unknown>;
  if (typeof t["id"] !== "string") return false;
  return true;
}

/**
 * Runtime predicate guard for ``ProjectHierarchyResponse``.
 *
 * Checks that ``items`` is an array of valid ``HierarchyRow`` entries.
 */
export function isProjectHierarchyResponse(x: unknown): x is ProjectHierarchyResponse {
  if (x === null || typeof x !== "object") return false;
  const o = x as Record<string, unknown>;
  if (!Array.isArray(o["items"])) return false;
  for (const item of o["items"] as unknown[]) {
    if (!isHierarchyRow(item)) return false;
  }
  return true;
}

export interface GetProjectHierarchyParams {
  max_depth?: number;
  types?: string[];
}

/**
 * GET /api/v1/projects/{projectId}/hierarchy
 *
 * Returns the full ticket hierarchy for ``projectId``, optionally filtered
 * by ``max_depth`` (1..8) and ticket ``types``.
 */
/**
 * V5b — one row in the kanban-friendly flattened hierarchy.
 *
 * ``epic_id`` / ``epic_key`` point at the root epic of this ticket's
 * subtree (``null`` when the ticket is itself an epic root or has no
 * epic ancestor). ``parent_key`` is the immediate parent's display_id
 * (``null`` for roots), retained so the swimlane / chip layer can
 * render parent-of-parent context if it wants to.
 *
 * The flatten is depth-first over the already-depth-ordered hierarchy
 * payload — we walk roots in payload order, recursing into children
 * before siblings. That order matches what a human reading the tree
 * top-to-bottom expects, and is what the kanban swimlane "by epic"
 * mode consumes when grouping descendants under their root.
 */
export interface FlatHierarchyRow {
  ticket: HierarchyTicketDTO;
  depth: number;
  parent_key: string | null;
  epic_id: string | null;
  epic_key: string | null;
}

/**
 * Walk a ``ProjectHierarchyResponse`` depth-first and produce
 * ``FlatHierarchyRow`` records the kanban lanes can consume.
 *
 * Algorithm:
 *   1. Index rows by ticket id so we can look up parents in O(1).
 *   2. For each row, climb ``parent_id`` until we hit an epic — that
 *      root is the row's ``epic_id`` (``null`` if no ancestor is an
 *      epic / the row is the epic itself).
 *   3. Group children by parent_id and walk roots in the order they
 *      appeared in the input (depth=0 rows are already ordinal-sorted
 *      by the backend).
 */
export function flattenHierarchyForKanban(
  response: ProjectHierarchyResponse,
): FlatHierarchyRow[] {
  const rows = response.items;
  if (rows.length === 0) return [];
  const byId = new Map<string, HierarchyRow>();
  for (const row of rows) byId.set(row.ticket.id, row);

  const childrenByParent = new Map<string, HierarchyRow[]>();
  const roots: HierarchyRow[] = [];
  for (const row of rows) {
    const pid = row.parent_id;
    if (pid === null || !byId.has(pid)) {
      roots.push(row);
    } else {
      const bucket = childrenByParent.get(pid) ?? [];
      bucket.push(row);
      childrenByParent.set(pid, bucket);
    }
  }

  function rootEpicOf(row: HierarchyRow): HierarchyRow | null {
    let cursor: HierarchyRow | null = row;
    let lastEpic: HierarchyRow | null = null;
    while (cursor !== null) {
      if (cursor.ticket.type === "epic") lastEpic = cursor;
      const pid: string | null = cursor.parent_id;
      cursor = pid !== null ? (byId.get(pid) ?? null) : null;
    }
    return lastEpic;
  }

  const flat: FlatHierarchyRow[] = [];

  function visit(row: HierarchyRow): void {
    const parent = row.parent_id !== null ? byId.get(row.parent_id) ?? null : null;
    const parentKey = parent
      ? ((parent.ticket as { display_id?: string }).display_id ?? null)
      : null;
    const epic = rootEpicOf(row);
    // Don't tag the epic ticket itself with its own id as the chip target
    // — the chip is for descendants only.
    const epicId = epic && epic.ticket.id !== row.ticket.id ? epic.ticket.id : null;
    const epicKey = epicId !== null
      ? ((epic?.ticket as { display_id?: string } | undefined)?.display_id ?? null)
      : null;
    flat.push({
      ticket: row.ticket,
      depth: row.depth,
      parent_key: parentKey,
      epic_id: epicId,
      epic_key: epicKey,
    });
    const kids = childrenByParent.get(row.ticket.id) ?? [];
    for (const kid of kids) visit(kid);
  }

  for (const root of roots) visit(root);
  return flat;
}

export async function getProjectHierarchy(
  projectId: string,
  params: GetProjectHierarchyParams = {},
): Promise<ProjectHierarchyResponse> {
  const usp = new URLSearchParams();
  if (params.max_depth !== undefined) {
    usp.set("max_depth", String(params.max_depth));
  }
  if (params.types && params.types.length > 0) {
    for (const t of params.types) {
      usp.append("types", t);
    }
  }
  const qs = usp.toString();
  const url = `${BASE}/${encodeURIComponent(projectId)}/hierarchy${qs ? `?${qs}` : ""}`;
  const res = await fetch(url, {
    credentials: "include",
    headers: { Accept: "application/json" },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const parsed = parseApiError(res, body);
    const env: import("./tickets").ErrorEnvelope = {
      code: parsed.code,
      message: parsed.message,
      details: (parsed.details ?? undefined) as Record<string, unknown> | undefined,
      correlation_id: parsed.correlation_id ?? undefined,
    };
    throw new ApiError(res.status, env);
  }
  return parseJson<ProjectHierarchyResponse>(res, isProjectHierarchyResponse);
}

// ---------------------------------------------------------------------------
// V2a — @mention autocomplete candidates client.
// ---------------------------------------------------------------------------

/**
 * One row in the @mention autocomplete dropdown.
 *
 * Matches the backend ``MentionCandidate`` schema 1:1. The ``type``
 * discriminator carries 'user' for project-member humans and 'agent'
 * for project-member agent accounts.
 */
export interface MentionCandidate {
  type: "user" | "agent";
  id: string;
  handle: string;
  display_name: string;
}

export interface MentionCandidatesResponse {
  items: MentionCandidate[];
}

function isMentionCandidate(x: unknown): x is MentionCandidate {
  if (typeof x !== "object" || x === null) return false;
  const r = x as Record<string, unknown>;
  if (r.type !== "user" && r.type !== "agent") return false;
  if (typeof r.id !== "string") return false;
  if (typeof r.handle !== "string") return false;
  if (typeof r.display_name !== "string") return false;
  return true;
}

export function isMentionCandidatesResponse(
  x: unknown,
): x is MentionCandidatesResponse {
  if (typeof x !== "object" || x === null) return false;
  const r = x as Record<string, unknown>;
  if (!Array.isArray(r.items)) return false;
  return r.items.every(isMentionCandidate);
}

// ---------------------------------------------------------------------------
// V6a — Project lessons (append-only)
// ---------------------------------------------------------------------------

export interface ProjectLessonDTO {
  id: string;
  project_id: string;
  author_user_id: string | null;
  author_agent_id: string | null;
  source: "user" | "agent";
  title: string;
  body: string;
  created_at: string;
}

export interface ProjectLessonsPage {
  items: ProjectLessonDTO[];
  next_cursor: string | null;
  total: number | null;
}

function isProjectLessonDTO(x: unknown): x is ProjectLessonDTO {
  if (x === null || typeof x !== "object") return false;
  const o = x as Record<string, unknown>;
  if (typeof o.id !== "string") return false;
  if (typeof o.project_id !== "string") return false;
  if (typeof o.title !== "string") return false;
  if (typeof o.body !== "string") return false;
  if (o.source !== "user" && o.source !== "agent") return false;
  if (typeof o.created_at !== "string") return false;
  return true;
}

function isProjectLessonsPage(x: unknown): x is ProjectLessonsPage {
  if (x === null || typeof x !== "object") return false;
  const o = x as Record<string, unknown>;
  if (!Array.isArray(o.items)) return false;
  return o.items.every(isProjectLessonDTO);
}

export async function listProjectLessons(
  projectId: string,
  params: { limit?: number; offset?: number } = {},
): Promise<ProjectLessonsPage> {
  const usp = new URLSearchParams();
  if (params.limit !== undefined) usp.set("limit", String(params.limit));
  if (params.offset !== undefined) usp.set("offset", String(params.offset));
  const qs = usp.toString();
  const url = `${BASE}/${encodeURIComponent(projectId)}/lessons${qs ? `?${qs}` : ""}`;
  const res = await fetch(url, {
    credentials: "include",
    headers: { Accept: "application/json" },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const parsed = parseApiError(res, body);
    const env: import("./tickets").ErrorEnvelope = {
      code: parsed.code,
      message: parsed.message,
      details: (parsed.details ?? undefined) as Record<string, unknown> | undefined,
      correlation_id: parsed.correlation_id ?? undefined,
    };
    throw new ApiError(res.status, env);
  }
  const page = await parseJson<ProjectLessonsPage>(res, isProjectLessonsPage);
  return {
    items: page.items ?? [],
    next_cursor: page.next_cursor ?? null,
    total: page.total ?? null,
  };
}

export interface CreateProjectLessonBody {
  title: string;
  body: string;
}

export async function createProjectLesson(
  projectId: string,
  payload: CreateProjectLessonBody,
): Promise<ProjectLessonDTO> {
  const url = `${BASE}/${encodeURIComponent(projectId)}/lessons`;
  const res = await fetch(url, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const parsed = parseApiError(res, body);
    const env: import("./tickets").ErrorEnvelope = {
      code: parsed.code,
      message: parsed.message,
      details: (parsed.details ?? undefined) as Record<string, unknown> | undefined,
      correlation_id: parsed.correlation_id ?? undefined,
    };
    throw new ApiError(res.status, env);
  }
  return parseJson<ProjectLessonDTO>(res, isProjectLessonDTO);
}

export async function listMentionCandidates(
  projectId: string,
  prefix: string,
  limit = 20,
): Promise<MentionCandidatesResponse> {
  const usp = new URLSearchParams();
  usp.set("prefix", prefix);
  usp.set("limit", String(limit));
  const url = `${BASE}/${encodeURIComponent(projectId)}/mention-candidates?${usp.toString()}`;
  const res = await fetch(url, {
    credentials: "include",
    headers: { Accept: "application/json" },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const parsed = parseApiError(res, body);
    const env: import("./tickets").ErrorEnvelope = {
      code: parsed.code,
      message: parsed.message,
      details: (parsed.details ?? undefined) as Record<string, unknown> | undefined,
      correlation_id: parsed.correlation_id ?? undefined,
    };
    throw new ApiError(res.status, env);
  }
  return parseJson<MentionCandidatesResponse>(res, isMentionCandidatesResponse);
}
