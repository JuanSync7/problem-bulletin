/**
 * Typed REST client for v2.1-WP8 ``GET /api/v1/people/search``.
 *
 * Powers the Kanban assignee dropdown + the Create-Ticket assignee picker.
 * Backend service: ``app/services/people.py``.
 */

import { ApiError, type ErrorEnvelope } from "./tickets";
import { parseApiError } from "./errors";
import { parseJson } from "./_jsonParse";

export type PersonKind = "user" | "agent";

export interface PersonRef {
  kind: PersonKind;
  id: string;
  display_name: string;
  handle?: string | null;
  email?: string | null;
  avatar_url?: string | null;
}

export interface PeopleSearchResponse {
  items: PersonRef[];
}

export interface SearchPeopleParams {
  q?: string;
  kind?: PersonKind | PersonKind[];
  project_id?: string;
  limit?: number;
}

const BASE = "/api/v1/people";

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

export async function searchPeople(
  params: SearchPeopleParams = {},
): Promise<PeopleSearchResponse> {
  const usp = new URLSearchParams();
  if (params.q !== undefined && params.q !== "") usp.set("q", params.q);
  if (params.kind) {
    const kinds = Array.isArray(params.kind) ? params.kind : [params.kind];
    if (kinds.length > 0) usp.set("kind", kinds.join(","));
  }
  if (params.project_id) usp.set("project_id", params.project_id);
  if (params.limit !== undefined) usp.set("limit", String(params.limit));
  const qs = usp.toString();
  return request(`${BASE}/search${qs ? `?${qs}` : ""}`);
}
