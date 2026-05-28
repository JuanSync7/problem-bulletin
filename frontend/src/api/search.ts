/**
 * API client for GET /api/search/v2 (WP56 multi-entity search).
 *
 * Exposes searchV2() as the single fetch point; the Search page must not
 * call fetch() directly.
 *
 * v2.13-WP03: error parsing goes through ``parseApiError`` so both the
 * unified ``{error:{...}}`` envelope and any legacy ``{detail}`` body
 * surface a useful message instead of the bare ``HTTP N`` text.
 */
import { ApiError, type ErrorEnvelope } from "./tickets";
import { parseApiError } from "./errors";

export type SearchEntity = "all" | "problems" | "tickets" | "components" | "labels" | "users";

/** Common shape for every result item returned by the backend. */
export interface SearchItem {
  id: string;
  display_id: string | null;
  title: string;
  subtitle: string;
  kind: string;
  href: string;
  rank: number;
  project_id: string | null;
  status: string | null;
  [key: string]: unknown;
}

export interface SearchArm {
  items: SearchItem[];
  total: number;
  /**
   * WP62/WP08: opaque HMAC-signed cursor for the next page of this arm.
   * `null` when there are no more rows.
   */
  next_cursor?: string | null;
  /**
   * v2.11-WP14 (F1): indicates whether `total` reflects the WP10 first-page
   * pinned snapshot (`"snapshot"`) or a live re-count triggered by the
   * client passing `refresh_total=true` (`"live"`). Optional — older
   * backends omit the field; treat absence as `"snapshot"`.
   */
  total_authority?: "snapshot" | "live" | null;
}

export interface SearchV2Response {
  problems?: SearchArm | null;
  tickets?: SearchArm | null;
  components?: SearchArm | null;
  labels?: SearchArm | null;
  users?: SearchArm | null;
}

export interface SearchV2Params {
  q: string;
  entity?: SearchEntity;
  problem_status?: string;
  problem_category_id?: string;
  ticket_status?: string;
  ticket_project_id?: string;
  component_project_id?: string;
  limit?: number;
  offset?: number;
  /**
   * WP08: per-arm HMAC-signed cursor. Only valid when `entity` is a single
   * arm (problems / tickets / components / labels / users). When set, the
   * backend ignores `offset` and seeks from the cursor position.
   */
  cursor?: string;
  /**
   * v2.11-WP14 (F2): when true, force the backend to re-count the matching
   * set on the current page instead of honouring the WP10 cursor-pinned
   * snapshot. The arm's `total_authority` will read `"live"` on the
   * response. Default false (snapshot behaviour, no UI change).
   */
  refresh_total?: boolean;
  signal?: AbortSignal;
}

export async function searchV2(params: SearchV2Params): Promise<SearchV2Response> {
  const { signal, ...rest } = params;

  const usp = new URLSearchParams();
  usp.set("q", rest.q);
  if (rest.entity) usp.set("entity", rest.entity);
  if (rest.problem_status) usp.set("problem_status", rest.problem_status);
  if (rest.problem_category_id) usp.set("problem_category_id", rest.problem_category_id);
  if (rest.ticket_status) usp.set("ticket_status", rest.ticket_status);
  if (rest.ticket_project_id) usp.set("ticket_project_id", rest.ticket_project_id);
  if (rest.component_project_id) usp.set("component_project_id", rest.component_project_id);
  if (rest.limit !== undefined) usp.set("limit", String(rest.limit));
  if (rest.offset !== undefined) usp.set("offset", String(rest.offset));
  if (rest.cursor) usp.set("cursor", rest.cursor);
  if (rest.refresh_total) usp.set("refresh_total", "1");

  const res = await fetch(`/api/search/v2?${usp.toString()}`, {
    credentials: "include",
    signal,
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

  return (await res.json()) as SearchV2Response;
}
