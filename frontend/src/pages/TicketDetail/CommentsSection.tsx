/**
 * CommentsSection — nested comments on the standalone ticket page.
 * Uses the shared CommentThread component (problem-style hierarchy).
 */
import { useEffect, useState } from "react";
import {
  addComment,
  listComments,
  type CommentDTO,
} from "../../api/tickets";
import { CommentThread } from "../../components/CommentThread";
import "../../components/CommentThread/CommentThread.css";
import { MentionTextarea } from "../../components/MentionTextarea";

interface Props {
  ticketIdOrKey: string;
  projectId?: string | null;
  onChanged?: () => void;
}

export function CommentsSection({ ticketIdOrKey, projectId, onChanged }: Props) {
  const [items, setItems] = useState<CommentDTO[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [posting, setPosting] = useState(false);

  const reload = async () => {
    try {
      const res = await listComments(ticketIdOrKey);
      setItems(res.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  useEffect(() => {
    setLoading(true);
    setError(null);
    reload().finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticketIdOrKey]);

  const onPost = async () => {
    const text = draft.trim();
    if (!text) return;
    setPosting(true);
    setError(null);
    try {
      await addComment(ticketIdOrKey, text);
      setDraft("");
      await reload();
      onChanged?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPosting(false);
    }
  };

  return (
    <section
      className="ticket-detail__comments"
      data-testid="ticket-detail-comments-section"
    >
      <div className="ticket-detail__section-header">
        <h2 className="ticket-detail__section-heading">Comments</h2>
        <span className="ticket-detail__count-pill">{items.length}</span>
      </div>
      {loading && <div className="ticket-detail__empty-hint">Loading…</div>}
      {error && (
        <div className="ticket-detail__mutate-error" role="alert">{error}</div>
      )}
      {!loading && (
        <CommentThread
          ticketIdOrKey={ticketIdOrKey}
          projectId={projectId}
          comments={items}
          busy={posting}
          onChanged={() => {
            void reload();
            onChanged?.();
          }}
        />
      )}
      <div className="ticket-detail__comments-form">
        <MentionTextarea
          rows={3}
          placeholder="Add a comment…"
          value={draft}
          onChange={setDraft}
          projectId={projectId ?? null}
          ariaLabel="Add a comment"
        />
        <button
          type="button"
          className="ticket-detail__btn"
          onClick={onPost}
          disabled={posting || !draft.trim()}
        >
          Post comment
        </button>
      </div>
    </section>
  );
}
