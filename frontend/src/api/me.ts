/**
 * Typed REST client for the /me ("My Space") endpoints — V3a.
 *
 * Currently only ``getMyInbox`` is exposed; it fetches the aggregate
 * shape used to render the 4-tab dashboard at ``/me``.
 */
import { parseApiError } from "./errors";
import { parseJson } from "./_jsonParse";

export interface PageEnvelope<T> {
  items: T[];
  next_cursor: string | null;
  total: number | null;
}

export interface AssignedTicket {
  id: string;
  display_id: string;
  title: string;
  status: string;
  priority: string;
  project_id: string;
  last_activity_at: string | null;
  created_at: string;
}

export interface AssignedProblem {
  id: string;
  title: string;
  status: string;
  created_at: string;
  activity_at: string | null;
}

export interface MentionItem {
  id: string;
  kind: string;
  target_type: "ticket";
  target_id: string;
  target_display_id: string | null;
  excerpt: string | null;
  is_read: boolean;
  created_at: string;
}

export interface AgentRunItem {
  id: string;
  agent_id: string;
  ticket_id: string;
  status: string;
  enqueued_at: string;
  started_at: string | null;
  finished_at: string | null;
  summary?: string | null;
  prompt_preview?: string | null;
  error?: string | null;
}

export interface InboxCounts {
  assigned_tickets: number;
  assigned_problems: number;
  mentions: number;
  my_agent_runs: number;
}

export interface MyInbox {
  assigned_tickets: PageEnvelope<AssignedTicket>;
  assigned_problems: PageEnvelope<AssignedProblem>;
  mentions: PageEnvelope<MentionItem>;
  my_agent_runs: PageEnvelope<AgentRunItem>;
  counts: InboxCounts;
}

export async function getMyInbox(): Promise<MyInbox> {
  const res = await fetch("/api/v1/me/inbox", { credentials: "include" });
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as unknown;
    const err = parseApiError(res, body);
    throw new Error(err.message);
  }
  return parseJson<MyInbox>(res);
}
