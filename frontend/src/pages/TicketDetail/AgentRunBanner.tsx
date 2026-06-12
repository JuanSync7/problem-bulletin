/**
 * V4b — AgentRunBanner (extended v2.29 S5).
 *
 * Shows a small pill on TicketDetail reflecting the LATEST agent_run for
 * the ticket:
 *
 *   pending → "⏳ {handle} queued"
 *   running → pulsing "🤖 {handle} working…"
 *   error   → "⚠️ {handle} failed" (error excerpt in the title attr)
 *   done    → "🤖 {handle} responded" + link to the posted comment
 *
 * While the latest run is pending/running the banner re-polls the
 * agent-runs endpoint every 5 s; the poll stops on done/error and is
 * cleared on unmount.
 */
import { useEffect, useState } from "react";
import { listAgentRuns, type AgentRunDTO } from "../../api/agent_runs";

interface Props {
  ticketId: string;
}

const POLL_MS = 5000;

export function AgentRunBanner({ ticketId }: Props) {
  const [run, setRun] = useState<AgentRunDTO | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: number | null = null;

    const tick = () => {
      listAgentRuns(ticketId)
        .then((page) => {
          if (cancelled) return;
          const latest = page.items[0] ?? null; // newest first
          setRun(latest);
          // Keep polling only while the run is in-flight.
          if (
            latest &&
            (latest.status === "pending" || latest.status === "running")
          ) {
            timer = window.setTimeout(tick, POLL_MS);
          }
        })
        .catch(() => {
          // Silent — the banner is non-essential.
          if (!cancelled) setRun(null);
        });
    };
    tick();

    return () => {
      cancelled = true;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [ticketId]);

  if (!run) return null;

  const handle = run.agent_handle ?? "agent";

  if (run.status === "pending") {
    return (
      <div
        className="agent-run-banner agent-run-banner--pending"
        data-testid="agent-run-banner"
        role="status"
      >
        <span className="agent-run-banner__icon" aria-hidden="true">
          {"⏳"}
        </span>
        <span className="agent-run-banner__text">
          <strong>{handle}</strong> queued
        </span>
      </div>
    );
  }

  if (run.status === "running") {
    return (
      <div
        className="agent-run-banner agent-run-banner--running"
        data-testid="agent-run-banner"
        role="status"
      >
        <span className="agent-run-banner__icon" aria-hidden="true">
          {"\u{1F916}"}
        </span>
        <span className="agent-run-banner__text">
          <strong>{handle}</strong> working…
        </span>
      </div>
    );
  }

  if (run.status === "error") {
    const excerpt = (run.error ?? "").slice(0, 200);
    return (
      <div
        className="agent-run-banner agent-run-banner--error"
        data-testid="agent-run-banner"
        role="status"
        title={excerpt || undefined}
      >
        <span className="agent-run-banner__icon" aria-hidden="true">
          {"⚠️"}
        </span>
        <span className="agent-run-banner__text">
          <strong>{handle}</strong> failed
        </span>
      </div>
    );
  }

  // done — unchanged V4b shape (needs the posted comment to link to).
  if (run.status !== "done" || !run.comment_id) return null;

  return (
    <div
      className="agent-run-banner"
      data-testid="agent-run-banner"
      role="status"
    >
      <span className="agent-run-banner__icon" aria-hidden="true">
        {"\u{1F916}"}
      </span>
      <span className="agent-run-banner__text">
        <strong>{handle}</strong> responded
      </span>
      <a
        className="agent-run-banner__link"
        data-testid="agent-run-banner-link"
        href={`#comment-${run.comment_id}`}
      >
        View comment
      </a>
    </div>
  );
}
