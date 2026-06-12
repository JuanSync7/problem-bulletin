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
import { parseJson } from "./_jsonParse";

export type SearchEntity =
  | "all"
  | "problems"
  | "tickets"
  | "components"
  | "labels"
  | "users"
  | "share_posts"
  | "bounties";

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

/**
 * The entity-arm keys on SearchV2Response.
 * Exported for consumers (Search.tsx, useSearchV2.ts) that need to index only
 * arm fields so TypeScript can narrow the value to SearchArm | null | undefined.
 */
export type SearchArmKey =
  | "problems"
  | "tickets"
  | "components"
  | "labels"
  | "users"
  | "share_posts"
  | "bounties";

/**
 * Standard multi-entity search response (mode=v2, the default).
 * Contains only the five entity arms — all values are SearchArm.
 * Consumers can safely index with `keyof SearchV2Response` or `SearchArmKey`.
 */
export interface SearchV2Response {
  problems?: SearchArm | null;
  tickets?: SearchArm | null;
  components?: SearchArm | null;
  labels?: SearchArm | null;
  users?: SearchArm | null;
  /** v2.29-S6: Share space posts arm. */
  share_posts?: SearchArm | null;
  /** v2.29-S6: Bounty space arm. */
  bounties?: SearchArm | null;
}

/**
 * A-FR-002: Typeahead response — extends SearchV2Response with metadata fields
 * that are only present in typeahead mode or when searching by AION-N key.
 *
 * - `direct_match`: A-FR-001, populated when query matches AION-N ticket ID.
 *   Key absent (omitted by backend model_serializer) means no match.
 * - `combined`: merged globally-ranked list (≤ 15 items), present only when
 *   mode=typeahead. Key absent in mode=v2.
 */
export interface TypeaheadResponse extends SearchV2Response {
  /**
   * A-FR-001: populated when the query matches an AION-N ticket ID.
   * Key is absent (omitted by backend model_serializer) when there is no match.
   * Treat absent key as null — both forms are valid.
   */
  direct_match?: SearchItem | null;
  /**
   * A-FR-002: merged globally-ranked list of length ≤ 15, present only in
   * typeahead mode. Key is absent in mode=v2 (default).
   */
  combined?: SearchItem[];
}

/**
 * Runtime predicate guard for TypeaheadResponse.
 *
 * Accepts direct_match as absent (key omitted) OR null (explicit null) OR a
 * valid SearchItem. All other arm fields (tickets, problems, …) are loosely
 * typed — their shape is validated downstream by SearchArm guards when needed.
 */
function isSearchItem(x: unknown): x is SearchItem {
  if (x === null || typeof x !== "object") return false;
  const o = x as Record<string, unknown>;
  return (
    typeof o["id"] === "string" &&
    typeof o["title"] === "string" &&
    typeof o["subtitle"] === "string" &&
    typeof o["kind"] === "string" &&
    typeof o["href"] === "string"
    // display_id, project_id, status are nullable — not checked for type beyond object guard
  );
}

export function isTypeaheadResponse(x: unknown): x is TypeaheadResponse {
  if (x === null || typeof x !== "object") return false;
  const o = x as Record<string, unknown>;
  // direct_match is optional — absent (undefined) or null both mean no match.
  const dm = o["direct_match"];
  if (dm !== undefined && dm !== null && !isSearchItem(dm)) return false;
  // combined is optional — absent in mode=v2; array of SearchItem in mode=typeahead.
  const combined = o["combined"];
  if (combined !== undefined) {
    if (!Array.isArray(combined)) return false;
    for (const item of combined) {
      if (!isSearchItem(item)) return false;
    }
  }
  return true;
}

/**
 * A2b: Stable iteration order for typeahead arms — groups appear in the
 * dropdown in this sequence (descending entity weight).
 *
 * ticket > problem > component > label > user > agent
 */
export const TYPEAHEAD_ARM_ORDER: SearchArmKey[] = [
  "tickets",
  "problems",
  "components",
  "labels",
  "users",
];

/**
 * A1b: Typeahead search helper. Calls /api/search/v2 with a guard-validated
 * response. Used by GlobalSearchBar for Cmd-K direct-match navigation.
 *
 * @param q - Search query string.
 * @param signal - AbortSignal to cancel in-flight requests.
 * @param entity - A4: optional entity scope filter. Defaults to "all".
 */
export async function searchTypeahead(
  q: string,
  signal?: AbortSignal,
  entity: SearchEntity = "all",
): Promise<TypeaheadResponse> {
  const usp = new URLSearchParams();
  usp.set("q", q);
  usp.set("mode", "typeahead");
  usp.set("entity", entity);
  usp.set("limit", "5");

  const res = await fetch(`/api/search/v2?${usp.toString()}`, {
    credentials: "include",
    signal,
  });

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const { parseApiError } = await import("./errors");
    const { ApiError } = await import("./tickets");
    const parsed = parseApiError(res, body);
    throw new ApiError(res.status, {
      code: parsed.code,
      message: parsed.message,
      details: (parsed.details ?? undefined) as Record<string, unknown> | undefined,
      correlation_id: parsed.correlation_id ?? undefined,
    });
  }

  return await parseJson<TypeaheadResponse>(res, isTypeaheadResponse);
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

  return await parseJson<SearchV2Response>(res);
}
