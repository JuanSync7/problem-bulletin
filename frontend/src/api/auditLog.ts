/**
 * Audit-log REST client — WP33.
 *
 * Calls ``GET /api/v1/audit-log`` (admin-only). Non-admins will receive
 * a 403 from the backend; this client surfaces it as a thrown Error so
 * callers can gate the fetch on role rather than error-handling.
 */

import { parseJson } from "./_jsonParse";

export interface AuditLogActor {
  kind: "user" | "agent";
  id: string;
  display_name: string;
  handle: string | null;
  email?: string | null;
  avatar_url?: string | null;
}

export interface AuditLogEntry {
  id: string;
  event: string;
  actor_user_id: string | null;
  actor: AuditLogActor | null;
  target_type: string | null;
  target_id: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface AuditLogPage {
  items: AuditLogEntry[];
  next_cursor: string | null;
  total: number | null;
}

export interface ListAuditLogParams {
  cursor?: string | null;
  limit?: number;
  event?: string | null;
  actor_user_id?: string | null;
  target_type?: string | null;
}

export async function listAuditLog(
  params: ListAuditLogParams = {}
): Promise<AuditLogPage> {
  const usp = new URLSearchParams();
  if (params.cursor) usp.set("cursor", params.cursor);
  if (params.limit != null) usp.set("limit", String(params.limit));
  if (params.event) usp.set("event", params.event);
  if (params.actor_user_id) usp.set("actor_user_id", params.actor_user_id);
  if (params.target_type) usp.set("target_type", params.target_type);

  const res = await fetch(`/api/v1/audit-log?${usp.toString()}`, {
    credentials: "include",
    headers: { Accept: "application/json" },
  });

  if (!res.ok) {
    // v2.12-WP09: parse through the unified-envelope adapter so we
    // pick up the new ``{error:{message}}`` shape while still tolerating
    // legacy ``{detail}`` bodies.
    const { parseApiError } = await import("./errors");
    const body = await res.json().catch(() => null);
    const parsed = parseApiError(res, body);
    throw Object.assign(new Error(parsed.message || `HTTP ${res.status}`), {
      status: res.status,
      code: parsed.code,
      correlation_id: parsed.correlation_id,
    });
  }

  return parseJson<AuditLogPage>(res);
}
