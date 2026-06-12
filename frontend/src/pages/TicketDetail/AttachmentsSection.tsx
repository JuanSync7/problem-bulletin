/**
 * AttachmentsSection — read-only file list for the standalone ticket page.
 * Uses the existing GET /tickets/:id/attachments endpoint.
 */
import { useEffect, useRef, useState } from "react";
import {
  listTicketAttachments,
  uploadTicketAttachment,
  type TicketAttachment,
} from "../../api/tickets";

interface Props {
  ticketIdOrKey: string;
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export function AttachmentsSection({ ticketIdOrKey }: Props) {
  const [items, setItems] = useState<TicketAttachment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const reload = () => {
    setLoading(true);
    listTicketAttachments(ticketIdOrKey)
      .then((res) => setItems(res.items ?? []))
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  };

  useEffect(reload, [ticketIdOrKey]);

  const onFile = async (ev: React.ChangeEvent<HTMLInputElement>) => {
    const f = ev.target.files?.[0];
    if (!f) return;
    setUploading(true);
    setError(null);
    try {
      await uploadTicketAttachment(ticketIdOrKey, f);
      reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  return (
    <section className="ticket-detail__attachments" data-testid="attachments-section">
      <div className="ticket-detail__section-header">
        <h2 className="ticket-detail__section-heading">Attachments</h2>
        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
          <span className="ticket-detail__count-pill">{items.length}</span>
          <label className="ticket-detail__btn" style={{ cursor: "pointer" }}>
            {uploading ? "Uploading…" : "+ Attach file"}
            <input
              ref={fileInputRef}
              type="file"
              onChange={onFile}
              disabled={uploading}
              style={{ display: "none" }}
              data-testid="attach-file-input"
            />
          </label>
        </div>
      </div>
      {error && <div className="ticket-detail__mutate-error" role="alert">{error}</div>}
      {loading && <div className="ticket-detail__empty-hint">Loading…</div>}
      {!loading && items.length === 0 && !error && (
        <div className="ticket-detail__empty-hint">No attachments.</div>
      )}
      {items.length > 0 && (
        <ul className="ticket-detail__attachment-list">
          {items.map((a) => (
            <li key={a.id} className="ticket-detail__attachment-item">
              <span className="ticket-detail__attachment-name">{a.filename}</span>
              <span className="ticket-detail__attachment-meta">
                {a.content_type} · {formatBytes(a.byte_size)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
