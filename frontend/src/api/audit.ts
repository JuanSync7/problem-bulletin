/**
 * Audit / agent-activity REST client.
 *
 * The backend exposes a filtered projection of the audit_log at
 * ``/api/agents/activity`` (Phase B3). The endpoint may not yet be deployed in
 * every environment, so the client tolerates a 404 by returning an empty list
 * instead of throwing — the activity panel will then simply show "no recent
 * activity" until the backend ships.
 */
import { ApiError, type ErrorEnvelope } from "./tickets";
import { parseApiError } from "./errors";
import { parseJson } from "./_jsonParse";

export interface ActivityEntry {
  id: string;
  occurred_at: string;
  actor_id: string;
  actor_type: string;
  actor_name?: string | null;
  action: string;
  entity_type: string;
  entity_id: string;
  ticket_key?: string | null;
  correlation_id?: string | null;
  details?: Record<string, unknown> | null;
}

/**
 * v2.27-WP02 (C2): runtime predicate for ActivityEntry. Checks required
 * string fields; optional fields are only constrained when present.
 */
export function isActivityEntry(x: unknown): x is ActivityEntry {
  if (!x || typeof x !== "object") return false;
  const r = x as Record<string, unknown>;
  return (
    typeof r.id === "string" &&
    typeof r.occurred_at === "string" &&
    typeof r.actor_id === "string" &&
    typeof r.actor_type === "string" &&
    typeof r.action === "string" &&
    typeof r.entity_type === "string" &&
    typeof r.entity_id === "string"
  );
}

/**
 * v2.27-WP02: accept canonical {items:[...]} OR legacy bare-array payload.
 */
export function isActivityPage(
  x: unknown,
): x is { items: ActivityEntry[] } | ActivityEntry[] {
  if (Array.isArray(x)) return x.every(isActivityEntry);
  if (!x || typeof x !== "object") return false;
  const items = (x as { items?: unknown }).items;
  return Array.isArray(items) && items.every(isActivityEntry);
}

export interface ListActivityParams {
  project_id?: string;
  actor_type?: "agent" | "user";
  limit?: number;
}

export async function listAgentActivity(
  params: ListActivityParams = {},
): Promise<ActivityEntry[]> {
  const usp = new URLSearchParams();
  if (params.project_id) usp.set("project_id", params.project_id);
  if (params.actor_type) usp.set("actor_type", params.actor_type);
  usp.set("limit", String(params.limit ?? 50));
  try {
    const res = await fetch(`/api/agents/activity?${usp.toString()}`, {
      credentials: "include",
      headers: { Accept: "application/json" },
    });
    if (res.status === 404) return [];
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
    const body = await parseJson(res, isActivityPage);
    // accept either {items:[...]} or a bare array
    if (Array.isArray(body)) return body;
    return body.items;
  } catch (e) {
    if (e instanceof ApiError) throw e;
    return [];
  }
}
