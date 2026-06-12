/**
 * API client for /api/v1/bounties (v2.29-S4 "Bounty" space).
 *
 * Users post bounties (points reward) on problems/tickets or standalone
 * ideas; any user OR agent can claim; the poster awards. All fetches go
 * through parseJson<T> + parseApiError per the v2.26 C2 seam conventions.
 */
import { ApiError, type ErrorEnvelope } from "./tickets";
import { parseApiError } from "./errors";
import { parseJson } from "./_jsonParse";

export type BountyStatus = "open" | "claimed" | "awarded" | "withdrawn";

export interface Bounty {
  id: string;
  title: string;
  description: string;
  points: number;
  status: BountyStatus;
  poster_user_id: string | null;
  poster_label: string;
  claimant_id: string | null;
  claimant_type: "user" | "agent" | null;
  claimant_label: string | null;
  ticket_id: string | null;
  ticket_display_id: string | null;
  problem_id: string | null;
  claimed_at: string | null;
  awarded_at: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface BountyList {
  items: Bounty[];
  total: number;
}

export interface BountyCreate {
  title: string;
  description?: string;
  points: number;
  ticket_id?: string | null;
  problem_id?: string | null;
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

export interface ListBountiesParams {
  status?: BountyStatus;
  limit?: number;
  offset?: number;
  signal?: AbortSignal;
}

export async function listBounties(
  params: ListBountiesParams = {},
): Promise<BountyList> {
  const usp = new URLSearchParams();
  if (params.status) usp.set("status", params.status);
  if (params.limit !== undefined) usp.set("limit", String(params.limit));
  if (params.offset !== undefined) usp.set("offset", String(params.offset));
  const qs = usp.toString();

  const res = await fetch(`/api/v1/bounties${qs ? `?${qs}` : ""}`, {
    credentials: "include",
    signal: params.signal,
  });
  if (!res.ok) await throwApiError(res);
  return await parseJson<BountyList>(res);
}

export async function createBounty(payload: BountyCreate): Promise<Bounty> {
  const res = await fetch("/api/v1/bounties", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) await throwApiError(res);
  return await parseJson<Bounty>(res);
}

export async function getBounty(id: string): Promise<Bounty> {
  const res = await fetch(`/api/v1/bounties/${id}`, {
    credentials: "include",
  });
  if (!res.ok) await throwApiError(res);
  return await parseJson<Bounty>(res);
}

async function transition(id: string, action: string): Promise<Bounty> {
  const res = await fetch(`/api/v1/bounties/${id}/${action}`, {
    method: "POST",
    credentials: "include",
  });
  if (!res.ok) await throwApiError(res);
  return await parseJson<Bounty>(res);
}

export async function claimBounty(id: string): Promise<Bounty> {
  return transition(id, "claim");
}

export async function unclaimBounty(id: string): Promise<Bounty> {
  return transition(id, "unclaim");
}

export async function awardBounty(id: string): Promise<Bounty> {
  return transition(id, "award");
}

export async function withdrawBounty(id: string): Promise<Bounty> {
  return transition(id, "withdraw");
}
