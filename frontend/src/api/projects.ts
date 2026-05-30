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
