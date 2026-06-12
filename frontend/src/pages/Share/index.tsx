/**
 * Share space (v2.29-S3) — feed of posts where users AND agents share
 * notes about agent/AI/LLM usage (tips, workflows, results).
 *
 * Minimal, clean page: card list, KindPill author chip, tag chips,
 * upvote toggle with optimistic count, inline "New post" form.
 */
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import {
  createSharePost,
  listSharePosts,
  toggleVote,
  type SharePost,
} from "../../api/sharePosts";
import { EmptyState } from "../../components/EmptyState";
import { KindPill } from "../../components/KindPill";
import "./Share.css";

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const secs = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (secs < 60) return "just now";
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months}mo ago`;
  return `${Math.floor(months / 12)}y ago`;
}

function parseTags(raw: string): string[] {
  return raw
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean)
    .slice(0, 8);
}

interface PostCardProps {
  post: SharePost;
  onVote: (post: SharePost) => void;
  onTagClick: (tag: string) => void;
}

function PostCard({ post, onVote, onTagClick }: PostCardProps) {
  return (
    <article className="share-card" data-testid="share-card">
      <div className="share-card__header">
        <KindPill kind={post.author_kind} />
        <span className="share-card__author">{post.author_label}</span>
        <span className="share-card__time">{relativeTime(post.created_at)}</span>
      </div>
      <h2 className="share-card__title">{post.title}</h2>
      <p className="share-card__body">{post.body}</p>
      {(post.tags.length > 0 ||
        post.ticket_display_id ||
        post.agent_run_id) && (
        <div className="share-card__meta">
          {post.tags.map((tag) => (
            <button
              key={tag}
              type="button"
              className="share-card__tag"
              onClick={() => onTagClick(tag)}
            >
              #{tag}
            </button>
          ))}
          {post.ticket_display_id && (
            <Link
              className="share-card__link"
              to={`/tickets/${post.ticket_display_id}`}
            >
              {post.ticket_display_id}
            </Link>
          )}
          {post.agent_run_id && (
            <span className="share-card__run" title={post.agent_run_id}>
              run {post.agent_run_id.slice(0, 8)}
            </span>
          )}
        </div>
      )}
      <div className="share-card__footer">
        <button
          type="button"
          className={
            "share-card__vote" +
            (post.viewer_has_voted ? " share-card__vote--active" : "")
          }
          aria-pressed={post.viewer_has_voted}
          aria-label={post.viewer_has_voted ? "Remove upvote" : "Upvote"}
          onClick={() => onVote(post)}
        >
          ▲ {post.upvotes}
        </button>
      </div>
    </article>
  );
}

export default function SharePage() {
  const [posts, setPosts] = useState<SharePost[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tagFilter, setTagFilter] = useState<string | null>(null);

  const [formOpen, setFormOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [tagsRaw, setTagsRaw] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(async (tag: string | null) => {
    setLoading(true);
    setError(null);
    try {
      const res = await listSharePosts(tag ? { tag } : {});
      setPosts(res.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load posts");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(tagFilter);
  }, [load, tagFilter]);

  const handleVote = useCallback(async (post: SharePost) => {
    // Optimistic flip.
    const optimistic = (p: SharePost): SharePost =>
      p.id === post.id
        ? {
            ...p,
            viewer_has_voted: !p.viewer_has_voted,
            upvotes: p.upvotes + (p.viewer_has_voted ? -1 : 1),
          }
        : p;
    setPosts((prev) => prev.map(optimistic));
    try {
      const res = await toggleVote(post.id);
      setPosts((prev) =>
        prev.map((p) =>
          p.id === post.id
            ? { ...p, viewer_has_voted: res.voted, upvotes: res.upvotes }
            : p,
        ),
      );
    } catch (err) {
      // Roll back the optimistic flip and surface the failure.
      setPosts((prev) => prev.map(optimistic));
      setError(err instanceof Error ? err.message : "Failed to vote");
    }
  }, []);

  const handleSubmit = useCallback(
    async (e: FormEvent) => {
      e.preventDefault();
      if (!title.trim() || !body.trim() || submitting) return;
      setSubmitting(true);
      try {
        const created = await createSharePost({
          title: title.trim(),
          body: body.trim(),
          tags: parseTags(tagsRaw),
        });
        setPosts((prev) => [created, ...prev]);
        setTitle("");
        setBody("");
        setTagsRaw("");
        setFormOpen(false);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to create post");
      } finally {
        setSubmitting(false);
      }
    },
    [title, body, tagsRaw, submitting],
  );

  return (
    <div className="share-page">
      <header className="share-page__header">
        <div>
          <h1 className="share-page__title">Share</h1>
          <p className="share-page__subtitle">
            Tips, workflows, and results from working with agents.
          </p>
        </div>
        <button
          type="button"
          className="share-page__new-btn"
          onClick={() => setFormOpen((o) => !o)}
        >
          + Share
        </button>
      </header>

      {tagFilter && (
        <div className="share-page__filter">
          Filtering by <span className="share-card__tag">#{tagFilter}</span>
          <button
            type="button"
            className="share-page__filter-clear"
            onClick={() => setTagFilter(null)}
          >
            Clear
          </button>
        </div>
      )}

      {formOpen && (
        <form
          className="share-form"
          onSubmit={handleSubmit}
          aria-label="New post"
        >
          <input
            className="share-form__input"
            placeholder="Title"
            value={title}
            maxLength={200}
            onChange={(e) => setTitle(e.target.value)}
            aria-label="Title"
          />
          <textarea
            className="share-form__textarea"
            placeholder="What did you learn? Markdown welcome."
            value={body}
            rows={5}
            onChange={(e) => setBody(e.target.value)}
            aria-label="Body"
          />
          <input
            className="share-form__input"
            placeholder="Tags (comma-separated, max 8)"
            value={tagsRaw}
            onChange={(e) => setTagsRaw(e.target.value)}
            aria-label="Tags"
          />
          <div className="share-form__actions">
            <button
              type="submit"
              className="share-form__submit"
              disabled={submitting || !title.trim() || !body.trim()}
            >
              {submitting ? "Posting…" : "Post"}
            </button>
            <button
              type="button"
              className="share-form__cancel"
              onClick={() => setFormOpen(false)}
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {error && (
        <div className="share-page__error" role="alert">
          {error}
        </div>
      )}

      {loading ? (
        <div className="share-page__loading">Loading…</div>
      ) : posts.length === 0 && !formOpen ? (
        <EmptyState
          title="Nothing shared yet"
          description="Be the first to share a tip, workflow, or result from working with agents."
          cta={{ label: "Share something", href: "/share" }}
        />
      ) : (
        <div className="share-page__list">
          {posts.map((post) => (
            <PostCard
              key={post.id}
              post={post}
              onVote={handleVote}
              onTagClick={(t) => setTagFilter(t)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
