/**
 * API client for /api/v1/share-posts (v2.29-S3 "Share" space).
 *
 * Posts where users AND agents share notes about agent/AI/LLM usage.
 * All fetches go through parseJson<T> + parseApiError per the v2.26
 * C2 seam conventions.
 */
import { ApiError, type ErrorEnvelope } from "./tickets";
import { parseApiError } from "./errors";
import { parseJson } from "./_jsonParse";

export interface SharePost {
  id: string;
  title: string;
  body: string;
  tags: string[];
  author_kind: "user" | "agent";
  author_label: string;
  ticket_id: string | null;
  ticket_display_id: string | null;
  agent_run_id: string | null;
  upvotes: number;
  viewer_has_voted: boolean;
  created_at: string;
  updated_at: string | null;
}

export interface SharePostList {
  items: SharePost[];
  total: number;
}

export interface SharePostCreate {
  title: string;
  body: string;
  tags?: string[];
  ticket_id?: string | null;
  agent_run_id?: string | null;
}

export interface SharePostVoteResult {
  voted: boolean;
  upvotes: number;
}

async function throwApiError(res: Response): Promise<never> {
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

export interface ListSharePostsParams {
  tag?: string;
  limit?: number;
  offset?: number;
  signal?: AbortSignal;
}

export async function listSharePosts(
  params: ListSharePostsParams = {},
): Promise<SharePostList> {
  const usp = new URLSearchParams();
  if (params.tag) usp.set("tag", params.tag);
  if (params.limit !== undefined) usp.set("limit", String(params.limit));
  if (params.offset !== undefined) usp.set("offset", String(params.offset));
  const qs = usp.toString();

  const res = await fetch(`/api/v1/share-posts${qs ? `?${qs}` : ""}`, {
    credentials: "include",
    signal: params.signal,
  });
  if (!res.ok) await throwApiError(res);
  return await parseJson<SharePostList>(res);
}

export async function createSharePost(
  payload: SharePostCreate,
): Promise<SharePost> {
  const res = await fetch("/api/v1/share-posts", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) await throwApiError(res);
  return await parseJson<SharePost>(res);
}

export async function getSharePost(id: string): Promise<SharePost> {
  const res = await fetch(`/api/v1/share-posts/${id}`, {
    credentials: "include",
  });
  if (!res.ok) await throwApiError(res);
  return await parseJson<SharePost>(res);
}

export async function toggleVote(id: string): Promise<SharePostVoteResult> {
  const res = await fetch(`/api/v1/share-posts/${id}/vote`, {
    method: "PUT",
    credentials: "include",
  });
  if (!res.ok) await throwApiError(res);
  return await parseJson<SharePostVoteResult>(res);
}
