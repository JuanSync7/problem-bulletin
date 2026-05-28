/**
 * Typed REST client for Ticketing v2 sprint endpoints.
 *
 *   GET  /api/v1/sprints?project_id=<uuid>&state=<state>
 *   GET  /api/v1/sprints/{id}
 *
 * Sprint state values per WP3: "planned" | "active" | "closed".
 * (The spec referenced "completed" but the shipped enum is "closed".)
 */

import { ApiError, type ErrorEnvelope } from "./tickets";
import { parseApiError } from "./errors";

export type SprintState = "planned" | "active" | "closed";

export interface SprintDTO {
  id: string;
  project_id: string;
  name: string;
  goal?: string | null;
  state: SprintState;
  start_date?: string | null;
  end_date?: string | null;
  completed_at?: string | null;
  created_by?: string;
  created_by_type?: string;
  created_at?: string;
  updated_at?: string | null;
}

const BASE = "/api/v1/sprints";

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
  return (await res.json()) as T;
}

export async function listSprints(
  projectId: string,
  state?: SprintState | SprintState[],
): Promise<{ items: SprintDTO[] }> {
  const usp = new URLSearchParams();
  usp.set("project_id", projectId);
  if (state) {
    const states = Array.isArray(state) ? state : [state];
    for (const s of states) usp.append("state", s);
  }
  return request(`${BASE}?${usp.toString()}`);
}

export async function getSprint(id: string): Promise<SprintDTO> {
  return request(`${BASE}/${encodeURIComponent(id)}`);
}
