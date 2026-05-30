/**
 * Typed REST client for user-profile endpoints (v2.4-WP29).
 *
 * Mounted at /api/v1/users/* on the backend.
 *
 * v2.12-WP09: error parsing now goes through ``parseApiError`` which
 * accepts both the unified ``{error:{code,message,...}}`` envelope and
 * the legacy ``{detail}`` shape. The ``UpdateHandleError`` interface is
 * preserved for the existing call-site contract (``.detail`` /
 * ``.next_allowed_at`` consumers in ``pages/Settings.tsx``); both are
 * populated from whichever envelope shape the backend returns.
 */

import { parseApiError } from "./errors";
import { parseJson } from "./_jsonParse";

export interface UpdateHandleResponse {
  id: string;
  email: string;
  display_name: string;
  handle: string;
  role: string;
  is_active: boolean;
}

export interface UpdateHandleError {
  status: number;
  detail: string;
  next_allowed_at?: string; // ISO timestamp, present on 429
  /** v2.12-WP09: machine-stable code (e.g. ``handle_taken``,
   *  ``handle_change_too_soon``, ``profane_handle``, ``validation``). */
  code?: string;
  /** v2.12-WP09: correlation id from the unified envelope, if any. */
  correlation_id?: string | null;
}

/**
 * PATCH /api/v1/users/me/handle
 *
 * On success resolves with the updated user object.
 * On error throws an ``UpdateHandleError``.
 */
export async function updateMyHandle(
  newHandle: string
): Promise<UpdateHandleResponse> {
  const res = await fetch("/api/v1/users/me/handle", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ handle: newHandle }),
  });

  if (res.ok) {
    return parseJson<UpdateHandleResponse>(res);
  }

  let body: unknown = null;
  try {
    body = await parseJson<unknown>(res);
  } catch {
    // empty body
  }

  const parsed = parseApiError(res, body);
  // ``next_allowed_at`` lives in the unified envelope's ``details``
  // under WP09; fall back to the legacy top-level key for back-compat
  // with any path still on the old shape.
  let nextAllowedAt: string | undefined;
  if (res.status === 429) {
    const detailsObj =
      parsed.details && typeof parsed.details === "object"
        ? (parsed.details as Record<string, unknown>)
        : null;
    if (detailsObj && typeof detailsObj.next_allowed_at === "string") {
      nextAllowedAt = detailsObj.next_allowed_at;
    } else if (
      body &&
      typeof body === "object" &&
      typeof (body as Record<string, unknown>).next_allowed_at === "string"
    ) {
      nextAllowedAt = (body as Record<string, string>).next_allowed_at;
    }
  }

  const err: UpdateHandleError = {
    status: res.status,
    detail: parsed.message,
    next_allowed_at: nextAllowedAt,
    code: parsed.code,
    correlation_id: parsed.correlation_id,
  };
  throw err;
}
