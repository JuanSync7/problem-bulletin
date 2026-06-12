/**
 * LinkedIssuesSection — Jira-style "Linked Issues" panel for the standalone
 * ticket page. Read-only display grouped by link type, with an inline
 * "Add link" form that POSTs to /tickets/:id/links.
 */
import { useEffect, useState } from "react";
import {
  WRITABLE_LINK_TYPES,
  linkTickets,
  listTicketLinks,
  type LinkDTO,
  type TicketLinkType,
} from "../../api/tickets";

const LINK_LABEL: Record<TicketLinkType, string> = {
  blocks: "blocks",
  is_blocked_by: "is blocked by",
  duplicates: "duplicates",
  is_duplicate_of: "is duplicate of",
  relates_to: "relates to",
  clones: "clones",
  is_cloned_by: "is cloned by",
  parent_of: "parent of",
  child_of: "child of",
};

interface Props {
  ticketIdOrKey: string;
  onChanged?: () => void;
}

export function LinkedIssuesSection({ ticketIdOrKey, onChanged }: Props) {
  const [outgoing, setOutgoing] = useState<LinkDTO[]>([]);
  const [incoming, setIncoming] = useState<LinkDTO[]>([]);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [linkType, setLinkType] = useState<TicketLinkType>("relates_to");
  const [target, setTarget] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () => {
    setLoading(true);
    listTicketLinks(ticketIdOrKey)
      .then((res) => {
        setOutgoing(res.outgoing ?? []);
        setIncoming(res.incoming ?? []);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
  }, [ticketIdOrKey]);

  const onAdd = async () => {
    if (!target.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await linkTickets(ticketIdOrKey, target.trim(), linkType);
      setTarget("");
      setAdding(false);
      load();
      onChanged?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  // Group all links by type, combining outgoing + incoming with direction labels
  const groups = new Map<string, { lt: TicketLinkType; items: { target: string; from: "out" | "in" }[] }>();
  for (const l of outgoing) {
    const key = l.link_type;
    if (!groups.has(key)) groups.set(key, { lt: l.link_type, items: [] });
    groups.get(key)!.items.push({ target: l.target_id, from: "out" });
  }
  for (const l of incoming) {
    const key = `in:${l.link_type}`;
    if (!groups.has(key)) groups.set(key, { lt: l.link_type, items: [] });
    groups.get(key)!.items.push({ target: l.source_id ?? "", from: "in" });
  }

  return (
    <section className="ticket-detail__links" data-testid="linked-issues-section">
      <div className="ticket-detail__section-header">
        <h2 className="ticket-detail__section-heading">Linked Issues</h2>
        <button
          type="button"
          className="ticket-detail__btn"
          onClick={() => setAdding((v) => !v)}
        >
          {adding ? "Cancel" : "+ Link issue"}
        </button>
      </div>

      {adding && (
        <div className="ticket-detail__link-form">
          <select
            value={linkType}
            onChange={(e) => setLinkType(e.target.value as TicketLinkType)}
            disabled={busy}
          >
            {WRITABLE_LINK_TYPES.map((t) => (
              <option key={t} value={t}>{LINK_LABEL[t]}</option>
            ))}
          </select>
          <input
            type="text"
            placeholder="Target ticket key (e.g. PB-12)"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            disabled={busy}
          />
          <button
            type="button"
            className="ticket-detail__btn"
            onClick={onAdd}
            disabled={busy || !target.trim()}
          >
            Link
          </button>
        </div>
      )}

      {error && <div className="ticket-detail__mutate-error" role="alert">{error}</div>}
      {loading && <div className="ticket-detail__empty-hint">Loading links…</div>}
      {!loading && groups.size === 0 && (
        <div className="ticket-detail__empty-hint">No linked issues.</div>
      )}

      {Array.from(groups.entries()).map(([key, g]) => (
        <div key={key} className="ticket-detail__link-group">
          <div className="ticket-detail__link-label">
            {LINK_LABEL[g.lt]}{g.items[0]?.from === "in" ? " (incoming)" : ""}
          </div>
          <ul className="ticket-detail__link-list">
            {g.items.map((it, i) => (
              <li key={i}>
                <a href={`/tickets/${encodeURIComponent(it.target)}`}>
                  {it.target.slice(0, 12)}
                </a>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </section>
  );
}
