/**
 * CommentThread — recursive nested comments for tickets.
 *
 * v7a: matches the hierarchy semantics of problem comments
 * (`parent_comment_id`). Each comment shows a Reply button that toggles
 * an inline `MentionTextarea` and posts a child comment via
 * ``addComment(idOrKey, body, [], parentId)``.
 */
import { useMemo, useState } from "react";
import { addComment, type CommentDTO } from "../../api/tickets";
import { MentionTextarea } from "../MentionTextarea";

export interface CommentThreadProps {
  ticketIdOrKey: string;
  projectId?: string | null;
  comments: CommentDTO[];
  busy?: boolean;
  onChanged?: () => void;
}

interface TreeNode {
  comment: CommentDTO;
  children: TreeNode[];
}

function buildTree(items: CommentDTO[]): TreeNode[] {
  const byId = new Map<string, TreeNode>();
  for (const c of items) byId.set(c.id, { comment: c, children: [] });
  const roots: TreeNode[] = [];
  for (const c of items) {
    const node = byId.get(c.id)!;
    const pid = c.parent_comment_id ?? null;
    if (pid && byId.has(pid)) {
      byId.get(pid)!.children.push(node);
    } else {
      roots.push(node);
    }
  }
  // Stable chronological order at each level.
  const sortRec = (ns: TreeNode[]) => {
    ns.sort((a, b) => (a.comment.created_at ?? "").localeCompare(b.comment.created_at ?? ""));
    for (const n of ns) sortRec(n.children);
  };
  sortRec(roots);
  return roots;
}

function CommentNode({
  node,
  depth,
  ticketIdOrKey,
  projectId,
  onPosted,
  parentBusy,
}: {
  node: TreeNode;
  depth: number;
  ticketIdOrKey: string;
  projectId?: string | null;
  onPosted: () => void;
  parentBusy?: boolean;
}) {
  const [replying, setReplying] = useState(false);
  const [draft, setDraft] = useState("");
  const [posting, setPosting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onPostReply = async () => {
    const text = draft.trim();
    if (!text) return;
    setPosting(true);
    setError(null);
    try {
      await addComment(ticketIdOrKey, text, undefined, node.comment.id);
      setDraft("");
      setReplying(false);
      onPosted();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPosting(false);
    }
  };

  const agent = node.comment.author_type === "agent";

  return (
    <div
      className={`comment-thread__node comment-thread__node--depth-${Math.min(depth, 6)}`}
      data-testid="comment-thread-node"
    >
      <div className="comment-thread__bubble">
        <div className="comment-thread__meta">
          <span
            className={`actor-badge actor-badge--${agent ? "agent" : "user"}`}
            data-testid="comment-actor-badge"
          >
            {agent ? "🤖 agent" : "👤 user"}
          </span>
          <span className="comment-thread__author">
            {node.comment.author_id?.slice(0, 8)}
          </span>
          {node.comment.created_at && (
            <span className="comment-thread__when">{node.comment.created_at}</span>
          )}
        </div>
        <div className="comment-thread__body">{node.comment.body}</div>
        <div className="comment-thread__actions">
          <button
            type="button"
            className="comment-thread__reply-btn"
            onClick={() => setReplying((v) => !v)}
            disabled={parentBusy || posting}
          >
            {replying ? "Cancel" : "Reply"}
          </button>
        </div>
        {replying && (
          <div className="comment-thread__reply-form">
            <MentionTextarea
              rows={2}
              placeholder="Reply…"
              value={draft}
              onChange={setDraft}
              projectId={projectId ?? null}
              ariaLabel="Reply to comment"
            />
            <button
              type="button"
              className="comment-thread__post-btn"
              onClick={onPostReply}
              disabled={posting || !draft.trim()}
            >
              Post reply
            </button>
            {error && <div className="comment-thread__error">{error}</div>}
          </div>
        )}
      </div>
      {node.children.length > 0 && (
        <div className="comment-thread__children">
          {node.children.map((child) => (
            <CommentNode
              key={child.comment.id}
              node={child}
              depth={depth + 1}
              ticketIdOrKey={ticketIdOrKey}
              projectId={projectId}
              onPosted={onPosted}
              parentBusy={parentBusy}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export function CommentThread({
  ticketIdOrKey,
  projectId,
  comments,
  busy,
  onChanged,
}: CommentThreadProps) {
  const tree = useMemo(() => buildTree(comments), [comments]);
  if (tree.length === 0) {
    return (
      <div className="comment-thread__empty">No comments yet.</div>
    );
  }
  return (
    <div className="comment-thread" data-testid="comment-thread">
      {tree.map((root) => (
        <CommentNode
          key={root.comment.id}
          node={root}
          depth={0}
          ticketIdOrKey={ticketIdOrKey}
          projectId={projectId}
          parentBusy={busy}
          onPosted={() => onChanged?.()}
        />
      ))}
    </div>
  );
}
