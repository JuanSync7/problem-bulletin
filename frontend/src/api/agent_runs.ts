/**
 * Typed REST client for the V4b agent_runs endpoints.
 *
 * Endpoints:
 *   POST /api/v1/agent-runs/process-next   admin-only: process one pending run
 *   GET  /api/v1/agent-runs?ticket_id=...  list runs (newest first)
 */
import { parseApiError } from "./errors";
import { parseJson } from "./_jsonParse";

export interface AgentRunDTO {
  id: string;
  agent_id: string;
  agent_handle: string | null;
  ticket_id: string;
  comment_id: string | null;
  status: "pending" | "running" | "done" | "error";
  response_body: string | null;
  error: string | null;
  enqueued_at: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface AgentRunList {
  items: AgentRunDTO[];
  total: number;
}

export interface ProcessNextResult {
  run_id: string | null;
  status: "done" | "error" | "empty";
}

const BASE = "/api/v1/agent-runs";

interface ErrorEnvelope {
  code: string;
  message: string;
  details?: Record<string, unknown>;
  correlation_id?: string;
}

export class AgentRunsApiError extends Error {
  status: number;
  envelope: ErrorEnvelope | null;
  constructor(
    status: number,
    envelope: ErrorEnvelope | null,
    message?: string,
  ) {
    super(message ?? envelope?.message ?? `HTTP ${status}`);
    this.status = status;
    this.envelope = envelope;
  }
}

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
    const body = await res.json().catch(() => null);
    const parsed = parseApiError(res, body);
    const env: ErrorEnvelope = {
      code: parsed.code,
      message: parsed.message,
      details: (parsed.details ?? undefined) as
        | Record<string, unknown>
        | undefined,
      correlation_id: parsed.correlation_id ?? undefined,
    };
    throw new AgentRunsApiError(res.status, env);
  }
  if (res.status === 204) return undefined as unknown as T;
  return parseJson<T>(res);
}

export async function listAgentRuns(
  ticketId: string,
): Promise<AgentRunList> {
  const qs = new URLSearchParams({ ticket_id: ticketId }).toString();
  return request<AgentRunList>(`${BASE}?${qs}`);
}

export async function processNext(): Promise<ProcessNextResult> {
  return request<ProcessNextResult>(`${BASE}/process-next`, {
    method: "POST",
  });
}
