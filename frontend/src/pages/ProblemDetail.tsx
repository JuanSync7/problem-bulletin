import React, { useState, useEffect, useCallback, lazy, Suspense } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { StatusBadge } from "../components/StatusBadge";
import { useAuth } from "../hooks/useAuth";
import { useAnonymousMode } from "../hooks/useAnonymousMode";
import { renderMarkdown } from "../components/MarkdownEditor";
const RichEditor = lazy(() => import("../components/RichEditor"));
import type { ProblemStatus } from "../components/StatusBadge";
import { parseApiError } from "../api/errors";
import "./ProblemDetail.css";

/**
 * v2.15-WP03 (C1) — file-local helper that converts a non-2xx Response
 * into a thrown Error carrying the unified envelope's `message`. Used by
 * every action/hydration fetch in this page so non-2xx surfaces via
 * `setActionError` instead of being silently swallowed by `if (res.ok)`
 * branches with no else.
 */
async function throwParsed(res: Response, fallback: string): Promise<never> {
  const body = await res.json().catch(() => null);
  const parsed = parseApiError(res, body);
  throw new Error(parsed.message || fallback);
}

/* ===========================
   Types
   =========================== */

interface Author {
  id: string;
  display_name: string;
}

interface Solution {
  id: string;
  description: string;
  upvote_count: number;
  is_upvoted: boolean;
  version_count: number;
  status: string;
  author: Author | null;
  created_at: string;
}

interface Comment {
  id: string;
  body: string;
  author: Author | null;
  is_edited: boolean;
  created_at: string;
  replies?: Comment[];
}

/**
 * v2.18-WP02 — local OpenAPI-mirror of `EditSuggestionResponse`
 * (`app/routes/edit_suggestions.py`). Pinned via consumer usage only;
 * if the backend response shape evolves, the parity work-package will
 * surface the drift via the OpenAPI parity lint when these types are
 * promoted to `frontend/src/api/`.
 */
interface EditSuggestionRead {
  id: string;
  problem_id: string;
  author: Author | null;
  suggested_description: string;
  reason: string | null;
  status: string;
  created_at: string;
}

/**
 * v2.18-WP02 — local OpenAPI-mirror of `AttachmentResponse`
 * (`app/routes/attachments.py`).
 */
interface AttachmentRead {
  id: string;
  parent_type: string;
  parent_id: string;
  uploader_id: string;
  filename: string;
  content_type: string;
  byte_size: number;
  storage_path: string;
  render_inline: boolean;
  created_at: string;
}

type WatchLevel = "all_activity" | "solutions_only" | "status_only" | "none";

interface ProblemFull {
  id: string;
  display_id?: string;
  title: string;
  description: string;
  description_html?: string;
  status: ProblemStatus;
  category: { id: string; name: string; slug: string } | null;
  tags: { id: string; name: string }[];
  upstar_count: number;
  is_upstarred: boolean;
  is_claimed: boolean;
  claims: unknown[];
  solution_count: number;
  comment_count: number;
  author: Author | null;
  created_at: string;
  activity_at: string;
}

/* ===========================
   Helpers
   =========================== */

function relativeTime(dateStr: string): string {
  const now = Date.now();
  const then = new Date(dateStr).getTime();
  const diffSec = Math.floor((now - then) / 1000);
  if (diffSec < 60) return "just now";
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.floor(diffHr / 24);
  if (diffDay < 30) return `${diffDay}d ago`;
  const diffMonth = Math.floor(diffDay / 30);
  if (diffMonth < 12) return `${diffMonth}mo ago`;
  return `${Math.floor(diffMonth / 12)}y ago`;
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

const WATCH_LABELS: Record<WatchLevel, string> = {
  all_activity: "All Activity",
  solutions_only: "Solutions Only",
  status_only: "Status Only",
  none: "None",
};

const ALL_STATUSES: { value: ProblemStatus; label: string }[] = [
  { value: "open", label: "Open" },
  { value: "claimed", label: "Claimed" },
  { value: "solved", label: "Solved" },
  { value: "accepted", label: "Accepted" },
  { value: "duplicate", label: "Duplicate" },
];

const SOLUTION_STATUSES = [
  { value: "pending", label: "Pending", color: "#8B8779" },
  { value: "under_review", label: "Under Review", color: "#B07A0C" },
  { value: "verified", label: "Verified", color: "#2D6FB0" },
  { value: "accepted", label: "Accepted", color: "#1F8A4C" },
  { value: "rejected", label: "Rejected", color: "#C2453A" },
];

/* ===========================
   Sub-components
   =========================== */

function SolutionCard({
  solution,
  isAuthenticated,
  isUpvoted,
  currentUserId,
  canChangeStatus,
  onUpvote,
  onEdit,
  onDelete,
  onStatusChange,
}: {
  solution: Solution;
  isAuthenticated: boolean;
  isUpvoted: boolean;
  currentUserId: string | null;
  canChangeStatus: boolean;
  onUpvote: (id: string) => void;
  onEdit: (id: string, description: string) => void;
  onDelete: (id: string) => void;
  onStatusChange: (id: string, status: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState(solution.description);
  const [showStatusMenu, setShowStatusMenu] = useState(false);
  const isOwner = currentUserId && solution.author?.id === currentUserId;

  const statusInfo = SOLUTION_STATUSES.find((s) => s.value === solution.status) || SOLUTION_STATUSES[0];

  function handleSaveEdit() {
    if (editText.trim().length >= 10) {
      onEdit(solution.id, editText.trim());
      setEditing(false);
    }
  }

  return (
    <div className="solution-card">
      <div className="solution-card__votes">
        <button
          className={`solution-card__upvote-btn${isUpvoted ? " solution-card__upvote-btn--active" : ""}`}
          onClick={() => onUpvote(solution.id)}
          disabled={!isAuthenticated}
          aria-label={isUpvoted ? "Remove upvote" : "Upvote solution"}
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill={isUpvoted ? "currentColor" : "none"}
            stroke="currentColor"
            strokeWidth="2"
            aria-hidden="true"
          >
            <path d="M12 19V5m-7 7l7-7 7 7" />
          </svg>
        </button>
        <span className="solution-card__vote-count">{solution.upvote_count ?? 0}</span>
      </div>
      <div className="solution-card__body">
        {editing ? (
          <div className="solution-card__edit-form">
            <textarea
              className="problem-detail__textarea"
              value={editText}
              onChange={(e) => setEditText(e.target.value)}
              rows={3}
            />
            <div className="solution-card__edit-actions">
              <button
                className="problem-detail__submit-btn"
                onClick={handleSaveEdit}
                disabled={editText.trim().length < 10}
              >
                Save
              </button>
              <button
                className="problem-detail__status-btn"
                onClick={() => { setEditing(false); setEditText(solution.description); }}
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <>
            <p className="solution-card__desc">{solution.description}</p>
            <div className="solution-card__meta">
              <span>by {solution.author?.display_name ?? "Anonymous"}</span>
              <span>{relativeTime(solution.created_at)}</span>
              {canChangeStatus ? (
                <div className="solution-card__status-wrapper">
                  <button
                    className="solution-card__status-badge"
                    style={{ backgroundColor: statusInfo.color, color: "#fff" }}
                    onClick={() => setShowStatusMenu(!showStatusMenu)}
                  >
                    {statusInfo.label}
                  </button>
                  {showStatusMenu && (
                    <div className="solution-card__status-menu">
                      {SOLUTION_STATUSES.filter((s) => s.value !== solution.status).map((s) => (
                        <button
                          key={s.value}
                          className="solution-card__status-option"
                          onClick={() => { onStatusChange(solution.id, s.value); setShowStatusMenu(false); }}
                        >
                          <span className="solution-card__status-dot" style={{ backgroundColor: s.color }} />
                          {s.label}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              ) : (
                <span
                  className="solution-card__status-badge"
                  style={{ backgroundColor: statusInfo.color, color: "#fff" }}
                >
                  {statusInfo.label}
                </span>
              )}
              {isOwner && (
                <>
                  <button className="comment-item__action-btn" onClick={() => setEditing(true)}>
                    Edit
                  </button>
                  <button className="comment-item__action-btn comment-item__action-btn--danger" onClick={() => onDelete(solution.id)}>
                    Delete
                  </button>
                </>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function CommentItem({
  comment,
  depth = 0,
  isAuthenticated,
  currentUserId,
  problemId,
  onReplySubmitted,
  onEditSubmitted,
  onDelete,
  onActionError,
}: {
  comment: Comment;
  depth?: number;
  isAuthenticated: boolean;
  currentUserId: string | null;
  problemId: string;
  onReplySubmitted: () => void;
  onEditSubmitted: () => void;
  onDelete: (id: string) => void;
  // v2.15-WP03: surface non-2xx reply/edit errors to the page banner.
  onActionError: (msg: string) => void;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const [showAllReplies, setShowAllReplies] = useState(false);
  const [showReply, setShowReply] = useState(false);
  const [replyText, setReplyText] = useState("");
  const [submittingReply, setSubmittingReply] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState(comment.body);
  const [savingEdit, setSavingEdit] = useState(false);

  const replies = comment.replies ?? [];
  const REPLY_LIMIT = 3;
  const visibleReplies = showAllReplies ? replies : replies.slice(0, REPLY_LIMIT);
  const hiddenCount = replies.length - REPLY_LIMIT;
  const isOwner = currentUserId && comment.author?.id === currentUserId;

  async function handleSubmitReply() {
    if (!replyText.trim() || submittingReply) return;
    setSubmittingReply(true);
    try {
      const res = await fetch(`/api/problems/${problemId}/comments`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ body: replyText.trim(), parent_comment_id: comment.id }),
      });
      if (!res.ok) {
        await throwParsed(res, "Failed to submit reply");
      }
      setReplyText("");
      setShowReply(false);
      onReplySubmitted();
    } catch (err) {
      onActionError((err as Error).message || "Failed to submit reply");
    } finally {
      setSubmittingReply(false);
    }
  }

  async function handleSaveEdit() {
    if (!editText.trim() || savingEdit) return;
    setSavingEdit(true);
    try {
      const res = await fetch(`/api/comments/${comment.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ body: editText.trim() }),
      });
      if (!res.ok) {
        await throwParsed(res, "Failed to save edit");
      }
      setEditing(false);
      onEditSubmitted();
    } catch (err) {
      onActionError((err as Error).message || "Failed to save edit");
    } finally {
      setSavingEdit(false);
    }
  }

  return (
    <div className="comment-item">
      {/* Clickable thread line (Reddit-style) */}
      <div
        className={`comment-item__thread-line${collapsed ? " comment-item__thread-line--collapsed" : ""}`}
        onClick={() => setCollapsed(!collapsed)}
        role="button"
        tabIndex={0}
        aria-label={collapsed ? "Expand thread" : "Collapse thread"}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setCollapsed(!collapsed); } }}
      />
      <div className="comment-item__content">
      <div className="comment-item__header">
        <span className="comment-item__author">{comment.author?.display_name ?? "Anonymous"}</span>
        <span className="comment-item__time">
          {relativeTime(comment.created_at)}
          {comment.is_edited && " (edited)"}
        </span>
        {collapsed && replies.length > 0 && (
          <span className="comment-item__collapsed-hint">
            [{replies.length} {replies.length === 1 ? "reply" : "replies"}]
          </span>
        )}
      </div>

      {editing ? (
        <div className="comment-item__edit-form">
          <textarea
            className="problem-detail__textarea"
            value={editText}
            onChange={(e) => setEditText(e.target.value)}
            rows={2}
          />
          <div className="comment-item__edit-actions">
            <button
              className="problem-detail__submit-btn"
              onClick={handleSaveEdit}
              disabled={!editText.trim() || savingEdit}
            >
              {savingEdit ? "Saving..." : "Save"}
            </button>
            <button
              className="problem-detail__status-btn"
              onClick={() => { setEditing(false); setEditText(comment.body); }}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <p className="comment-item__body">{comment.body}</p>
      )}

      <div className="comment-item__actions">
        {isAuthenticated && !editing && (
          <button
            className="comment-item__action-btn"
            onClick={() => setShowReply(!showReply)}
          >
            Reply
          </button>
        )}
        {isOwner && !editing && (
          <>
            <button
              className="comment-item__action-btn"
              onClick={() => setEditing(true)}
            >
              Edit
            </button>
            <button
              className="comment-item__action-btn comment-item__action-btn--danger"
              onClick={() => onDelete(comment.id)}
            >
              Delete
            </button>
          </>
        )}
      </div>

      {showReply && (
        <div className="comment-item__reply-form">
          <textarea
            className="problem-detail__textarea"
            placeholder="Write a reply..."
            value={replyText}
            onChange={(e) => setReplyText(e.target.value)}
            rows={2}
          />
          <div className="comment-item__reply-actions">
            <button
              className="problem-detail__submit-btn"
              onClick={handleSubmitReply}
              disabled={!replyText.trim() || submittingReply}
            >
              {submittingReply ? "Posting..." : "Reply"}
            </button>
            <button
              className="problem-detail__status-btn"
              onClick={() => { setShowReply(false); setReplyText(""); }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {!collapsed && (
        <>
          {visibleReplies.map((reply) => (
            <CommentItem
              key={reply.id}
              comment={reply}
              depth={depth + 1}
              isAuthenticated={isAuthenticated}
              currentUserId={currentUserId}
              problemId={problemId}
              onReplySubmitted={onReplySubmitted}
              onEditSubmitted={onEditSubmitted}
              onDelete={onDelete}
              onActionError={onActionError}
            />
          ))}
          {!showAllReplies && hiddenCount > 0 && (
            <button
              className="comment-item__show-more"
              onClick={() => setShowAllReplies(true)}
            >
              Show {hiddenCount} more {hiddenCount === 1 ? "reply" : "replies"}
            </button>
          )}
        </>
      )}
      </div>{/* end comment-item__content */}
    </div>
  );
}

/* ===========================
   ProblemDetail Page
   =========================== */

type TabId = "solutions" | "comments";

export default function ProblemDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { isAuthenticated, user } = useAuth();
  const { isAnonymous } = useAnonymousMode();

  const activeTab: TabId =
    searchParams.get("tab") === "comments" ? "comments" : "solutions";

  const [problem, setProblem] = useState<ProblemFull | null>(null);
  const [solutions, setSolutions] = useState<Solution[]>([]);
  const [comments, setComments] = useState<Comment[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // v2.15-WP03: separate surface for action/hydration errors so they
  // don't replace the entire page like `error` (full-page replace) does.
  const [actionError, setActionError] = useState<string | null>(null);
  const [upstarring, setUpstarring] = useState(false);
  const [claiming, setClaiming] = useState(false);
  const [newComment, setNewComment] = useState("");
  const [submittingComment, setSubmittingComment] = useState(false);
  const [newSolution, setNewSolution] = useState("");
  const [submittingSolution, setSubmittingSolution] = useState(false);
  const [watchLevel, setWatchLevel] = useState<WatchLevel | null>(null);
  const [watchLoading, setWatchLoading] = useState(false);
  const [showWatchMenu, setShowWatchMenu] = useState(false);
  const [transitioning, setTransitioning] = useState(false);
  const [showStatusMenu, setShowStatusMenu] = useState(false);
  const [upvotedSolutions, setUpvotedSolutions] = useState<Set<string>>(new Set());
  const [showSuggestEdit, setShowSuggestEdit] = useState(false);
  const [suggestText, setSuggestText] = useState("");
  const [suggestReason, setSuggestReason] = useState("");
  const [submittingSuggest, setSubmittingSuggest] = useState(false);
  const [editSuggestions, setEditSuggestions] = useState<EditSuggestionRead[]>([]);
  const [editingDescription, setEditingDescription] = useState(false);
  const [editDescText, setEditDescText] = useState("");
  const [savingDesc, setSavingDesc] = useState(false);
  const [attachments, setAttachments] = useState<AttachmentRead[]>([]);

  const currentUserId = user?.id ?? null;

  const fetchProblem = useCallback(async (showLoading = false) => {
    if (showLoading) setIsLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/problems/${id}`, { credentials: "include" });
      if (!res.ok) {
        // v2.14-WP04: route through parseApiError so the structured
        // envelope's `message` (and code/correlation_id transit) is
        // surfaced instead of `Failed to load problem (NNN)`.
        const body = await res.json().catch(() => null);
        const parsed = parseApiError(res, body);
        throw new Error(parsed.message);
      }
      const data: ProblemFull = await res.json();
      setProblem(data);
    } catch (err) {
      setError((err as Error).message || "Something went wrong");
    } finally {
      if (showLoading) setIsLoading(false);
    }
  }, [id]);

  const fetchSolutions = useCallback(async () => {
    try {
      const res = await fetch(`/api/problems/${id}/solutions`, { credentials: "include" });
      if (!res.ok) {
        await throwParsed(res, "Failed to load solutions");
      }
      const data = await res.json();
      const list: Solution[] = Array.isArray(data) ? data : data.items ?? data.solutions ?? [];
      setSolutions(list);
      // Hydrate upvoted set from API response
      const upvoted = new Set<string>();
      for (const s of list) {
        if (s.is_upvoted) upvoted.add(s.id);
      }
      setUpvotedSolutions(upvoted);
    } catch (err) {
      setActionError((err as Error).message || "Failed to load solutions");
    }
  }, [id]);

  const fetchComments = useCallback(async () => {
    try {
      const res = await fetch(`/api/problems/${id}/comments`, { credentials: "include" });
      if (!res.ok) {
        await throwParsed(res, "Failed to load comments");
      }
      const data = await res.json();
      const list = Array.isArray(data) ? data : data.items ?? data.comments ?? [];
      // Reverse top-level so newest first
      setComments(list.reverse());
    } catch (err) {
      setActionError((err as Error).message || "Failed to load comments");
    }
  }, [id]);

  const fetchWatch = useCallback(async () => {
    try {
      const res = await fetch(`/api/problems/${id}/watch`, { credentials: "include" });
      if (!res.ok) {
        // 404 here means "no watch set" — preserve legacy null behavior;
        // surface other non-2xx via setActionError.
        if (res.status === 404) {
          setWatchLevel(null);
          return;
        }
        await throwParsed(res, "Failed to load watch state");
      }
      const data = await res.json();
      setWatchLevel(data.level ?? null);
    } catch (err) {
      setWatchLevel(null);
      setActionError((err as Error).message || "Failed to load watch state");
    }
  }, [id]);

  const fetchAttachments = useCallback(async () => {
    try {
      const res = await fetch(`/api/problems/${id}/attachments`, { credentials: "include" });
      if (!res.ok) {
        await throwParsed(res, "Failed to load attachments");
      }
      setAttachments(await res.json());
    } catch (err) {
      setActionError((err as Error).message || "Failed to load attachments");
    }
  }, [id]);

  const fetchEditSuggestions = useCallback(async () => {
    try {
      const res = await fetch(`/api/problems/${id}/edit-suggestions`, { credentials: "include" });
      if (!res.ok) {
        await throwParsed(res, "Failed to load edit suggestions");
      }
      setEditSuggestions(await res.json());
    } catch (err) {
      setActionError((err as Error).message || "Failed to load edit suggestions");
    }
  }, [id]);

  useEffect(() => {
    fetchProblem(true);
    fetchSolutions();
    fetchComments();
    fetchAttachments();
    fetchEditSuggestions();
    if (isAuthenticated) fetchWatch();
  }, [fetchProblem, fetchSolutions, fetchComments, fetchAttachments, fetchEditSuggestions, fetchWatch, isAuthenticated]);

  function setTab(tab: TabId) {
    setSearchParams({ tab }, { replace: true });
  }

  async function handleUpstar() {
    if (!isAuthenticated || !problem || upstarring) return;
    setUpstarring(true);
    try {
      // Backend is a toggle — always POST
      const res = await fetch(`/api/problems/${id}/upstar`, {
        method: "POST",
        credentials: "include",
      });
      if (!res.ok) {
        await throwParsed(res, "Failed to upstar");
      }
      const data = await res.json();
      setProblem((prev) =>
        prev
          ? {
              ...prev,
              is_upstarred: data.active,
              upstar_count: data.count,
            }
          : prev,
      );
    } catch (err) {
      setActionError((err as Error).message || "Failed to upstar");
    } finally {
      setUpstarring(false);
    }
  }

  async function handleClaim() {
    if (!isAuthenticated || !problem || claiming) return;
    setClaiming(true);
    try {
      const res = await fetch(`/api/problems/${id}/claim`, {
        method: "POST",
        credentials: "include",
      });
      if (!res.ok) {
        await throwParsed(res, "Failed to claim");
      }
      fetchProblem();
    } catch (err) {
      setActionError((err as Error).message || "Failed to claim");
    } finally {
      setClaiming(false);
    }
  }

  async function handleSetWatch(level: WatchLevel) {
    setWatchLoading(true);
    setShowWatchMenu(false);
    try {
      if (level === "none" && watchLevel !== null) {
        const res = await fetch(`/api/problems/${id}/watch`, {
          method: "DELETE",
          credentials: "include",
        });
        if (!res.ok && res.status !== 204) {
          await throwParsed(res, "Failed to update watch");
        }
        setWatchLevel(null);
      } else {
        const res = await fetch(`/api/problems/${id}/watch`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({ level }),
        });
        if (!res.ok) {
          await throwParsed(res, "Failed to update watch");
        }
        setWatchLevel(level);
      }
    } catch (err) {
      setActionError((err as Error).message || "Failed to update watch");
    } finally {
      setWatchLoading(false);
    }
  }

  async function handleUpvoteSolution(solutionId: string) {
    if (!isAuthenticated) return;
    try {
      const res = await fetch(`/api/solutions/${solutionId}/upvote`, {
        method: "POST",
        credentials: "include",
      });
      if (!res.ok) {
        await throwParsed(res, "Failed to upvote");
      }
      const data = await res.json();
      setUpvotedSolutions((prev) => {
        const next = new Set(prev);
        if (data.active) {
          next.add(solutionId);
        } else {
          next.delete(solutionId);
        }
        return next;
      });
      fetchSolutions();
    } catch (err) {
      setActionError((err as Error).message || "Failed to upvote");
    }
  }

  async function handleEditSolution(solutionId: string, description: string) {
    try {
      const res = await fetch(`/api/solutions/${solutionId}/versions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ description }),
      });
      if (!res.ok) {
        await throwParsed(res, "Failed to edit solution");
      }
      fetchSolutions();
    } catch (err) {
      setActionError((err as Error).message || "Failed to edit solution");
    }
  }

  async function handleSolutionStatus(solutionId: string, newStatus: string) {
    try {
      const res = await fetch(`/api/solutions/${solutionId}/status`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ status: newStatus }),
      });
      if (!res.ok) {
        await throwParsed(res, "Failed to update solution status");
      }
      setSolutions((prev) =>
        prev.map((s) => (s.id === solutionId ? { ...s, status: newStatus } : s))
      );
    } catch (err) {
      setActionError((err as Error).message || "Failed to update solution status");
    }
  }

  async function handleDeleteProblem() {
    if (!confirm("Are you sure you want to delete this problem? This cannot be undone.")) return;
    try {
      const res = await fetch(`/api/problems/${id}`, {
        method: "DELETE",
        credentials: "include",
      });
      if (!res.ok && res.status !== 204) {
        await throwParsed(res, "Failed to delete problem");
      }
      navigate("/problems");
    } catch (err) {
      setActionError((err as Error).message || "Failed to delete problem");
    }
  }

  async function handleDeleteSolution(solutionId: string) {
    if (!confirm("Delete this solution?")) return;
    try {
      const res = await fetch(`/api/solutions/${solutionId}`, {
        method: "DELETE",
        credentials: "include",
      });
      if (!res.ok && res.status !== 204) {
        await throwParsed(res, "Failed to delete solution");
      }
      setSolutions((prev) => prev.filter((s) => s.id !== solutionId));
      fetchProblem();
    } catch (err) {
      setActionError((err as Error).message || "Failed to delete solution");
    }
  }

  async function handleDeleteComment(commentId: string) {
    if (!confirm("Delete this comment?")) return;
    try {
      const res = await fetch(`/api/comments/${commentId}`, {
        method: "DELETE",
        credentials: "include",
      });
      if (!res.ok && res.status !== 204) {
        await throwParsed(res, "Failed to delete comment");
      }
      fetchComments();
      fetchProblem();
    } catch (err) {
      setActionError((err as Error).message || "Failed to delete comment");
    }
  }

  async function handleSubmitComment(e: React.FormEvent) {
    e.preventDefault();
    if (!newComment.trim() || submittingComment) return;
    setSubmittingComment(true);
    try {
      const res = await fetch(`/api/problems/${id}/comments`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ body: newComment.trim(), is_anonymous: isAnonymous }),
      });
      if (!res.ok) {
        await throwParsed(res, "Failed to submit comment");
      }
      setNewComment("");
      fetchComments();
      fetchProblem();
    } catch (err) {
      setActionError((err as Error).message || "Failed to submit comment");
    } finally {
      setSubmittingComment(false);
    }
  }

  async function handleSubmitSolution(e: React.FormEvent) {
    e.preventDefault();
    if (!newSolution.trim() || submittingSolution) return;
    setSubmittingSolution(true);
    try {
      const res = await fetch(`/api/problems/${id}/solutions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ description: newSolution.trim(), is_anonymous: isAnonymous }),
      });
      if (!res.ok) {
        await throwParsed(res, "Failed to submit solution");
      }
      setNewSolution("");
      fetchSolutions();
      fetchProblem();
    } catch (err) {
      setActionError((err as Error).message || "Failed to submit solution");
    } finally {
      setSubmittingSolution(false);
    }
  }

  async function handleSaveDescription(e: React.FormEvent) {
    e.preventDefault();
    if (!editDescText.trim() || savingDesc) return;
    setSavingDesc(true);
    try {
      const res = await fetch(`/api/problems/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ description: editDescText.trim() }),
      });
      if (!res.ok) {
        await throwParsed(res, "Failed to save description");
      }
      setEditingDescription(false);
      fetchProblem();
    } catch (err) {
      setActionError((err as Error).message || "Failed to save description");
    } finally {
      setSavingDesc(false);
    }
  }

  async function handleUploadAttachment(e: React.ChangeEvent<HTMLInputElement>) {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    const failed: string[] = [];
    for (const file of Array.from(files)) {
      const formData = new FormData();
      formData.append("file", file);
      try {
        const res = await fetch(`/api/problems/${id}/attachments`, {
          method: "POST",
          credentials: "include",
          body: formData,
        });
        if (!res.ok) {
          failed.push(file.name);
        }
      } catch {
        failed.push(file.name);
      }
    }
    if (failed.length > 0) {
      setActionError(`Failed to upload: ${failed.join(", ")}`);
    }
    fetchAttachments();
    e.target.value = "";
  }

  async function handleSubmitSuggestEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!suggestText.trim() || submittingSuggest) return;
    setSubmittingSuggest(true);
    try {
      const res = await fetch(`/api/problems/${id}/edit-suggestions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          suggested_description: suggestText.trim(),
          reason: suggestReason.trim() || null,
        }),
      });
      if (!res.ok) {
        await throwParsed(res, "Failed to submit suggestion");
      }
      setSuggestText("");
      setSuggestReason("");
      setShowSuggestEdit(false);
      fetchEditSuggestions();
    } catch (err) {
      setActionError((err as Error).message || "Failed to submit suggestion");
    } finally {
      setSubmittingSuggest(false);
    }
  }

  async function handleAcceptSuggestion(suggestionId: string) {
    try {
      const res = await fetch(`/api/edit-suggestions/${suggestionId}/accept`, {
        method: "POST",
        credentials: "include",
      });
      if (!res.ok) {
        await throwParsed(res, "Failed to accept suggestion");
      }
      fetchProblem();
      fetchEditSuggestions();
    } catch (err) {
      setActionError((err as Error).message || "Failed to accept suggestion");
    }
  }

  async function handleRejectSuggestion(suggestionId: string) {
    try {
      const res = await fetch(`/api/edit-suggestions/${suggestionId}/reject`, {
        method: "POST",
        credentials: "include",
      });
      if (!res.ok) {
        await throwParsed(res, "Failed to reject suggestion");
      }
      fetchEditSuggestions();
    } catch (err) {
      setActionError((err as Error).message || "Failed to reject suggestion");
    }
  }

  /* --- Render --- */

  if (isLoading) {
    return (
      <div className="problem-detail">
        <div className="problem-detail__loading">
          <div className="app-loading__spinner" />
        </div>
      </div>
    );
  }

  if (error || !problem) {
    return (
      <div className="problem-detail">
        <div className="problem-detail__error" role="alert">
          <p>{error || "Problem not found"}</p>
          <button className="problem-detail__retry-btn" onClick={() => fetchProblem()}>
            Retry
          </button>
        </div>
      </div>
    );
  }

  const canManageProblem = isAuthenticated && (currentUserId === problem.author?.id || user?.role === "admin");

  return (
    <div className="problem-detail">
      <main className="problem-detail__main">
      {/* v2.15-WP03: inline action-error banner — dismissible, non-blocking. */}
      {actionError && (
        <div
          className="problem-detail__action-error"
          role="alert"
          data-testid="problem-detail-action-error"
        >
          <span>{actionError}</span>
          <button
            type="button"
            className="problem-detail__action-error-dismiss"
            onClick={() => setActionError(null)}
            aria-label="Dismiss error"
          >
            ×
          </button>
        </div>
      )}
      {/* Header */}
      <header className="problem-detail__header">
        <h1 className="problem-detail__title">
          {problem.display_id && <span className="problem-detail__display-id">{problem.display_id}</span>}
          {problem.title}
        </h1>
      </header>

      {/* Description */}
      <section className="problem-detail__description">
        <div className="problem-detail__section-header">
          <h2 className="problem-detail__section-title">Description</h2>
          <div className="comment-item__actions">
            {isAuthenticated && currentUserId === problem.author?.id && !editingDescription && (
              <button
                className="comment-item__action-btn"
                onClick={() => { setEditingDescription(true); setEditDescText(problem.description); }}
              >
                Edit
              </button>
            )}
            {isAuthenticated && currentUserId !== problem.author?.id && (
              <button
                className="comment-item__action-btn"
                onClick={() => { setShowSuggestEdit(!showSuggestEdit); setSuggestText(problem.description); }}
              >
                Suggest Edit
              </button>
            )}
          </div>
        </div>

        {editingDescription ? (
          <form className="problem-detail__suggest-form" onSubmit={handleSaveDescription}>
            <Suspense fallback={<div className="problem-detail__editor-loading">Loading editor…</div>}>
              <RichEditor
                value={editDescText}
                onChange={setEditDescText}
                minHeight="20rem"
                placeholder="Edit description..."
              />
            </Suspense>
            <div className="comment-item__reply-actions">
              <button
                type="submit"
                className="problem-detail__submit-btn"
                disabled={savingDesc || editDescText.trim().length < 10}
              >
                {savingDesc ? "Saving..." : "Save"}
              </button>
              <button
                type="button"
                className="problem-detail__status-btn"
                onClick={() => setEditingDescription(false)}
              >
                Cancel
              </button>
            </div>
          </form>
        ) : (
          <div
            className="problem-detail__html-content"
            dangerouslySetInnerHTML={{ __html: renderMarkdown(problem.description) }}
          />
        )}

        {showSuggestEdit && (
          <form className="problem-detail__suggest-form" onSubmit={handleSubmitSuggestEdit}>
            <textarea
              className="problem-detail__textarea"
              placeholder="Suggested description..."
              value={suggestText}
              onChange={(e) => setSuggestText(e.target.value)}
              rows={4}
            />
            <input
              className="problem-detail__textarea"
              placeholder="Reason for edit (optional)"
              value={suggestReason}
              onChange={(e) => setSuggestReason(e.target.value)}
              style={{ padding: "0.5rem 0.75rem" }}
            />
            <div className="comment-item__reply-actions">
              <button
                type="submit"
                className="problem-detail__submit-btn"
                disabled={submittingSuggest || suggestText.trim().length < 10}
              >
                {submittingSuggest ? "Submitting..." : "Submit Suggestion"}
              </button>
              <button
                type="button"
                className="problem-detail__status-btn"
                onClick={() => setShowSuggestEdit(false)}
              >
                Cancel
              </button>
            </div>
          </form>
        )}

        {/* Pending edit suggestions — visible to problem author/admin */}
        {editSuggestions.length > 0 && (currentUserId === problem.author?.id || user?.role === "admin") && (
          <div className="problem-detail__suggestions">
            <h3 className="problem-detail__section-title" style={{ marginTop: "1rem" }}>
              Pending Edit Suggestions ({editSuggestions.length})
            </h3>
            {editSuggestions.map((s) => (
              <div key={s.id} className="problem-detail__suggestion-card">
                <div className="problem-detail__suggestion-header">
                  <span className="comment-item__author">{s.author?.display_name ?? "Anonymous"}</span>
                  {s.reason && <span className="comment-item__time">Reason: {s.reason}</span>}
                </div>
                <p className="problem-detail__suggestion-text">{s.suggested_description}</p>
                <div className="comment-item__reply-actions">
                  <button
                    className="problem-detail__submit-btn"
                    onClick={() => handleAcceptSuggestion(s.id)}
                  >
                    Accept
                  </button>
                  <button
                    className="problem-detail__status-btn"
                    onClick={() => handleRejectSuggestion(s.id)}
                  >
                    Reject
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Supporting Documents */}
      {(attachments.length > 0 || (isAuthenticated && currentUserId === problem.author?.id)) && (
        <section className="problem-detail__attachments">
          <div className="problem-detail__section-header">
            <h2 className="problem-detail__section-title">Supporting Documents</h2>
            {isAuthenticated && currentUserId === problem.author?.id && (
              <label className="comment-item__action-btn" style={{ cursor: "pointer", fontSize: "1.5rem", lineHeight: 1, padding: 0, width: "2rem", height: "2rem", display: "inline-flex", alignItems: "center", justifyContent: "center" }} aria-label="Add file" title="Add file">
                +
                <input
                  type="file"
                  accept="image/*,.pdf,.txt"
                  multiple
                  onChange={handleUploadAttachment}
                  style={{ display: "none" }}
                />
              </label>
            )}
          </div>
          {attachments.length === 0 ? (
            <p className="problem-detail__empty-tab" style={{ padding: "0.5rem 0", fontSize: "0.8125rem" }}>
              No documents attached.
            </p>
          ) : (
            <div className="problem-detail__attachment-list">
              {attachments.map((att) => {
                const viewUrl = `/api/attachments/${att.id}/download`;
                const isImage = att.content_type?.startsWith("image/");
                const isPdf = att.content_type === "application/pdf";
                return (
                  <a
                    key={att.id}
                    href={viewUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="problem-detail__attachment-card"
                  >
                    {/* Compact preview */}
                    {isImage && (
                      <img
                        src={viewUrl}
                        alt={att.filename}
                        className="problem-detail__attachment-thumb"
                      />
                    )}
                    {isPdf && (
                      <div className="problem-detail__attachment-pdf-icon">PDF</div>
                    )}
                    {!isImage && !isPdf && (
                      <div className="problem-detail__attachment-pdf-icon">TXT</div>
                    )}
                    <span className="problem-detail__attachment-name">{att.filename}</span>
                  </a>
                );
              })}
            </div>
          )}
        </section>
      )}

      {/* Tabs */}
      <div className="problem-detail__tabs" role="tablist">
        <button
          className={`problem-detail__tab${activeTab === "solutions" ? " problem-detail__tab--active" : ""}`}
          role="tab"
          aria-selected={activeTab === "solutions"}
          onClick={() => setTab("solutions")}
        >
          Solutions ({problem.solution_count})
        </button>
        <button
          className={`problem-detail__tab${activeTab === "comments" ? " problem-detail__tab--active" : ""}`}
          role="tab"
          aria-selected={activeTab === "comments"}
          onClick={() => setTab("comments")}
        >
          Comments ({problem.comment_count})
        </button>
      </div>

      {/* Tab Content */}
      <div className="problem-detail__tab-content" role="tabpanel">
        {activeTab === "solutions" && (
          <div className="problem-detail__solutions">
            {isAuthenticated && (
              <form className="problem-detail__add-form" onSubmit={handleSubmitSolution}>
                <textarea
                  className="problem-detail__textarea"
                  placeholder="Describe your solution (min 10 characters)..."
                  value={newSolution}
                  onChange={(e) => setNewSolution(e.target.value)}
                  rows={3}
                />
                <div className="problem-detail__form-row">
                  {isAnonymous && <span className="problem-detail__anon-indicator">Posting anonymously</span>}
                  <button
                    type="submit"
                    className="problem-detail__submit-btn"
                    disabled={submittingSolution || newSolution.trim().length < 10}
                  >
                    {submittingSolution ? "Submitting..." : "Submit Solution"}
                  </button>
                </div>
              </form>
            )}
            {solutions.length === 0 ? (
              <p className="problem-detail__empty-tab">No solutions yet. Be the first to propose one.</p>
            ) : (
              solutions.map((s) => (
                <SolutionCard
                  key={s.id}
                  solution={s}
                  isAuthenticated={isAuthenticated}
                  isUpvoted={upvotedSolutions.has(s.id)}
                  currentUserId={currentUserId}
                  canChangeStatus={isAuthenticated && (currentUserId === problem.author?.id || user?.role === "admin")}
                  onUpvote={handleUpvoteSolution}
                  onEdit={handleEditSolution}
                  onDelete={handleDeleteSolution}
                  onStatusChange={handleSolutionStatus}
                />
              ))
            )}
          </div>
        )}

        {activeTab === "comments" && (
          <div className="problem-detail__comments">
            {isAuthenticated && (
              <form className="problem-detail__add-form" onSubmit={handleSubmitComment}>
                <textarea
                  className="problem-detail__textarea"
                  placeholder="Add a comment..."
                  value={newComment}
                  onChange={(e) => setNewComment(e.target.value)}
                  rows={2}
                />
                <div className="problem-detail__form-row">
                  {isAnonymous && <span className="problem-detail__anon-indicator">Posting anonymously</span>}
                  <button
                    type="submit"
                    className="problem-detail__submit-btn"
                    disabled={submittingComment || !newComment.trim()}
                  >
                    {submittingComment ? "Posting..." : "Post Comment"}
                  </button>
                </div>
              </form>
            )}
            {comments.length === 0 ? (
              <p className="problem-detail__empty-tab">No comments yet. Start the conversation.</p>
            ) : (
              comments.map((c) => (
                <CommentItem
                  key={c.id}
                  comment={c}
                  isAuthenticated={isAuthenticated}
                  currentUserId={currentUserId}
                  problemId={id!}
                  onReplySubmitted={() => { fetchComments(); fetchProblem(); }}
                  onEditSubmitted={() => fetchComments()}
                  onDelete={handleDeleteComment}
                  onActionError={setActionError}
                />
              ))
            )}
          </div>
        )}
      </div>
      </main>

      {/* Right details panel */}
      <aside className="problem-detail__sidebar" aria-label="Details">
        <div className="problem-detail__sidebar-status">
          {canManageProblem ? (
            <div className="problem-detail__status-wrap">
              <button
                className={`status-badge status-badge--${problem.status} problem-detail__status-trigger`}
                onClick={() => setShowStatusMenu(!showStatusMenu)}
                disabled={transitioning}
              >
                {ALL_STATUSES.find((s) => s.value === problem.status)?.label ?? problem.status}
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginLeft: 6 }}>
                  <path d="M6 9l6 6 6-6" />
                </svg>
              </button>
              {showStatusMenu && (
                <div className="problem-detail__status-menu">
                  {ALL_STATUSES.map((s) => (
                    <button
                      key={s.value}
                      className={`problem-detail__status-menu-item status-badge status-badge--${s.value}${s.value === problem.status ? " problem-detail__status-menu-item--current" : ""}`}
                      onClick={async () => {
                        setShowStatusMenu(false);
                        if (s.value === problem.status) return;
                        setTransitioning(true);
                        try {
                          const res = await fetch(`/api/problems/${id}/status`, {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            credentials: "include",
                            body: JSON.stringify({ status: s.value }),
                          });
                          if (!res.ok) {
                            await throwParsed(res, "Status transition failed");
                          }
                          fetchProblem();
                        } catch (err) {
                          setActionError((err as Error).message || "Status transition failed");
                        } finally {
                          setTransitioning(false);
                        }
                      }}
                    >
                      {s.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <StatusBadge status={problem.status} />
          )}
          {/* v2.29 S5 (audit P1#5) — Problem→Ticket bridge. Prefills the
              ticket form with the problem title and a back-link so the
              ticket stays traceable to its originating problem. */}
          <Link
            className="problem-detail__create-ticket-link"
            data-testid="create-ticket-from-problem"
            to={`/tickets/new?title=${encodeURIComponent(problem.title)}&description=${encodeURIComponent(
              `Created from problem: ${window.location.origin}/problems/${problem.id}\n\n${problem.description ?? ""}`,
            )}`}
          >
            Create Ticket from Problem
          </Link>
        </div>

        <div className="problem-detail__sidebar-actions">
          <button
            className={`problem-detail__upstar-btn${problem.is_upstarred ? " problem-detail__upstar-btn--active" : ""}`}
            onClick={handleUpstar}
            disabled={upstarring || !isAuthenticated}
            aria-label={problem.is_upstarred ? "Remove upstar" : "Upstar this problem"}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
              <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
            </svg>
            <span>{problem.upstar_count}</span>
          </button>

          {(problem.status === "open" || problem.status === "claimed") && (
            <button
              className={`problem-detail__claim-btn${problem.is_claimed ? " problem-detail__claim-btn--active" : ""}`}
              onClick={handleClaim}
              disabled={claiming || !isAuthenticated}
            >
              {problem.is_claimed ? "Unclaim" : "Claim"}
            </button>
          )}

          {isAuthenticated && (
            <div className="problem-detail__watch-wrap">
              <button
                className={`problem-detail__watch-btn${watchLevel && watchLevel !== "none" ? " problem-detail__watch-btn--active" : ""}`}
                onClick={() => setShowWatchMenu(!showWatchMenu)}
                disabled={watchLoading}
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                  <path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9M13.73 21a2 2 0 01-3.46 0" />
                </svg>
                <span>{watchLevel && watchLevel !== "none" ? WATCH_LABELS[watchLevel] : "Watch"}</span>
              </button>
              {showWatchMenu && (
                <div className="problem-detail__watch-menu">
                  {(Object.keys(WATCH_LABELS) as WatchLevel[]).map((level) => (
                    <button
                      key={level}
                      className={`problem-detail__watch-option${watchLevel === level ? " problem-detail__watch-option--active" : ""}`}
                      onClick={() => handleSetWatch(level)}
                    >
                      {WATCH_LABELS[level]}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        <div className="problem-detail__sidebar-section">
          <div className="problem-detail__field">
            <div className="problem-detail__field-label">Reporter</div>
            <div className="problem-detail__field-value">{problem.author?.display_name ?? "Anonymous"}</div>
          </div>

          <div className="problem-detail__field">
            <div className="problem-detail__field-label">Created</div>
            <div className="problem-detail__field-value" title={formatDate(problem.created_at)}>
              {relativeTime(problem.created_at)}
            </div>
          </div>

          {problem.category && (
            <div className="problem-detail__field">
              <div className="problem-detail__field-label">Category</div>
              <div className="problem-detail__field-value">
                <span className="problem-detail__category-pill">{problem.category.name}</span>
              </div>
            </div>
          )}

          {problem.tags.length > 0 && (
            <div className="problem-detail__field">
              <div className="problem-detail__field-label">Tags</div>
              <div className="problem-detail__field-value problem-detail__tags">
                {problem.tags.map((tag) => (
                  <span key={tag.id} className="problem-detail__tag">{tag.name}</span>
                ))}
              </div>
            </div>
          )}
        </div>

        {canManageProblem && (
          <div className="problem-detail__sidebar-actions">
            <button className="problem-detail__delete-btn" onClick={handleDeleteProblem}>
              Delete
            </button>
          </div>
        )}
      </aside>
    </div>
  );
}
