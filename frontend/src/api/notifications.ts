/**
 * Typed REST client for the ticket-notification inbox (v2.2-WP14).
 *
 * Targets `/api/v1/notifications/*` (the v2 ticket-notifications surface).
 * This is intentionally separate from the legacy `/api/notifications`
 * client (bulletin-domain notifications) — they consume different tables.
 */
import { ApiError, type ErrorEnvelope, type Page } from "./tickets";
import { parseApiError } from "./errors";

export type PersonRef = {
  kind: "user" | "agent";
  id: string;
  display_name: string;
  handle: string | null;
  email: string | null;
  avatar_url: string | null;
};

export interface TicketNotification {
  id: string;
  kind: string;
  recipient_type: "user" | "agent";
  recipient_id: string;
  actor: PersonRef;
  target_type: "ticket";
  target_id: string;
  target_display_id: string | null;
  comment_id: string | null;
  excerpt: string | null;
  is_read: boolean;
  created_at: string;
}

const BASE = "/api/v1/notifications";

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
    // v2.13-WP03: route errors through the unified-envelope adapter so
    // both the new {error:{...}} envelope and any legacy {detail} body
    // surface a useful message to UI layers.
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

export interface ListNotificationsParams {
  only_unread?: boolean;
  cursor?: string | null;
  limit?: number;
  /** "user" (default) fetches the caller's own inbox.
   *  "agent" fetches notifications addressed to the caller's agent accounts. */
  recipient_kind?: "user" | "agent";
}

export async function listNotifications(
  params: ListNotificationsParams = {},
): Promise<Page<TicketNotification>> {
  const usp = new URLSearchParams();
  if (params.only_unread) usp.set("only_unread", "true");
  if (params.cursor) usp.set("cursor", params.cursor);
  if (params.limit != null) usp.set("limit", String(params.limit));
  if (params.recipient_kind && params.recipient_kind !== "user") {
    usp.set("recipient_kind", params.recipient_kind);
  }
  const qs = usp.toString();
  const raw = await request<{
    items: TicketNotification[];
    next_cursor: string | null;
    total: number | null;
  }>(`${BASE}${qs ? `?${qs}` : ""}`);
  return {
    items: raw.items ?? [],
    next_cursor: raw.next_cursor ?? null,
    total: raw.total ?? null,
  };
}

export async function getUnreadCount(): Promise<number> {
  const raw = await request<{ count: number }>(`${BASE}/unread_count`);
  return raw.count ?? 0;
}

export async function markRead(id: string): Promise<void> {
  await request<void>(`${BASE}/${encodeURIComponent(id)}/read`, {
    method: "POST",
  });
}

export async function markAllRead(): Promise<number> {
  const raw = await request<{ updated: number }>(`${BASE}/read_all`, {
    method: "POST",
  });
  return raw.updated ?? 0;
}
