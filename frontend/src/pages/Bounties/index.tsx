/**
 * Bounty space (v2.29-S4) — users post bounties (points reward) on
 * problems/tickets or standalone ideas; any user OR agent claims; the
 * poster awards. Awarded points are a team recognition signal.
 *
 * Minimal, clean page: status filter pills, bounty cards with a
 * prominent points badge, contextual claim/unclaim/award buttons, and
 * an inline "+ Post Bounty" form.
 */
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import {
  awardBounty,
  claimBounty,
  createBounty,
  listBounties,
  unclaimBounty,
  type Bounty,
  type BountyStatus,
} from "../../api/bounties";
import { EmptyState } from "../../components/EmptyState";
import { KindPill } from "../../components/KindPill";
import { useAuth } from "../../hooks/useAuth";
import "./Bounties.css";

type Filter = "all" | "open" | "claimed" | "awarded";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "open", label: "Open" },
  { key: "claimed", label: "Claimed" },
  { key: "awarded", label: "Awarded" },
];

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

interface BountyCardProps {
  bounty: Bounty;
  viewerId: string | null;
  onClaim: (b: Bounty) => void;
  onUnclaim: (b: Bounty) => void;
  onAward: (b: Bounty) => void;
}

function BountyCard({
  bounty,
  viewerId,
  onClaim,
  onUnclaim,
  onAward,
}: BountyCardProps) {
  const isPoster = viewerId !== null && bounty.poster_user_id === viewerId;
  const isClaimant =
    viewerId !== null &&
    bounty.claimant_type === "user" &&
    bounty.claimant_id === viewerId;

  return (
    <article className="bounty-card" data-testid="bounty-card">
      <div className="bounty-card__points" title={`${bounty.points} points`}>
        ★ {bounty.points}
      </div>
      <div className="bounty-card__main">
        <div className="bounty-card__header">
          <span
            className={`bounty-card__status bounty-card__status--${bounty.status}`}
          >
            {bounty.status}
          </span>
          {bounty.ticket_display_id && (
            <Link
              className="bounty-card__link"
              to={`/tickets/${bounty.ticket_display_id}`}
            >
              {bounty.ticket_display_id}
            </Link>
          )}
          <span className="bounty-card__time">
            {relativeTime(bounty.created_at)}
          </span>
        </div>
        <h2 className="bounty-card__title">{bounty.title}</h2>
        {bounty.description && (
          <p className="bounty-card__description">{bounty.description}</p>
        )}
        <div className="bounty-card__people">
          <span className="bounty-card__poster">{bounty.poster_label}</span>
          {bounty.claimant_label && (
            <>
              <span className="bounty-card__arrow" aria-hidden="true">
                →
              </span>
              {bounty.claimant_type === "agent" && <KindPill kind="agent" />}
              <span className="bounty-card__claimant">
                {bounty.claimant_label}
              </span>
            </>
          )}
        </div>
        <div className="bounty-card__actions">
          {bounty.status === "open" && (
            <button
              type="button"
              className="bounty-card__btn bounty-card__btn--claim"
              onClick={() => onClaim(bounty)}
            >
              Claim
            </button>
          )}
          {bounty.status === "claimed" && isClaimant && (
            <button
              type="button"
              className="bounty-card__btn"
              onClick={() => onUnclaim(bounty)}
            >
              Unclaim
            </button>
          )}
          {bounty.status === "claimed" && isPoster && (
            <button
              type="button"
              className="bounty-card__btn bounty-card__btn--award"
              onClick={() => onAward(bounty)}
            >
              Award {bounty.points} pts
            </button>
          )}
        </div>
      </div>
    </article>
  );
}

export default function BountiesPage() {
  const { user } = useAuth();
  const viewerId = user?.id ?? null;

  const [bounties, setBounties] = useState<Bounty[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");

  const [formOpen, setFormOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [points, setPoints] = useState("50");
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(async (f: Filter) => {
    setLoading(true);
    setError(null);
    try {
      const res = await listBounties(
        f === "all" ? {} : { status: f as BountyStatus },
      );
      setBounties(res.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load bounties");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(filter);
  }, [load, filter]);

  const replace = useCallback((updated: Bounty) => {
    setBounties((prev) =>
      prev.map((b) => (b.id === updated.id ? updated : b)),
    );
  }, []);

  const runTransition = useCallback(
    async (fn: (id: string) => Promise<Bounty>, b: Bounty) => {
      try {
        replace(await fn(b.id));
      } catch (err) {
        setError(err instanceof Error ? err.message : "Action failed");
      }
    },
    [replace],
  );

  const handleSubmit = useCallback(
    async (e: FormEvent) => {
      e.preventDefault();
      const pts = Number(points);
      if (!title.trim() || !Number.isInteger(pts) || pts < 1 || submitting) {
        return;
      }
      setSubmitting(true);
      try {
        const created = await createBounty({
          title: title.trim(),
          description: description.trim(),
          points: pts,
        });
        setBounties((prev) => [created, ...prev]);
        setTitle("");
        setDescription("");
        setPoints("50");
        setFormOpen(false);
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Failed to post bounty",
        );
      } finally {
        setSubmitting(false);
      }
    },
    [title, description, points, submitting],
  );

  return (
    <div className="bounties-page">
      <header className="bounties-page__header">
        <div>
          <h1 className="bounties-page__title">Bounties</h1>
          <p className="bounties-page__subtitle">
            Post a points reward on a problem or idea — anyone, human or
            agent, can claim it.
          </p>
        </div>
        <button
          type="button"
          className="bounties-page__new-btn"
          onClick={() => setFormOpen((o) => !o)}
        >
          + Post Bounty
        </button>
      </header>

      <div className="bounties-page__filters" role="tablist">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            type="button"
            role="tab"
            aria-selected={filter === f.key}
            className={
              "bounties-page__pill" +
              (filter === f.key ? " bounties-page__pill--active" : "")
            }
            onClick={() => setFilter(f.key)}
          >
            {f.label}
          </button>
        ))}
      </div>

      {formOpen && (
        <form
          className="bounty-form"
          onSubmit={handleSubmit}
          aria-label="New bounty"
        >
          <input
            className="bounty-form__input"
            placeholder="What needs doing?"
            value={title}
            maxLength={200}
            onChange={(e) => setTitle(e.target.value)}
            aria-label="Title"
          />
          <textarea
            className="bounty-form__textarea"
            placeholder="Describe the outcome you want."
            value={description}
            rows={4}
            onChange={(e) => setDescription(e.target.value)}
            aria-label="Description"
          />
          <div className="bounty-form__row">
            <label className="bounty-form__points-label">
              Points
              <input
                className="bounty-form__input bounty-form__points"
                type="number"
                min={1}
                max={1000}
                value={points}
                onChange={(e) => setPoints(e.target.value)}
                aria-label="Points"
              />
            </label>
            <div className="bounty-form__actions">
              <button
                type="submit"
                className="bounty-form__submit"
                disabled={submitting || !title.trim()}
              >
                {submitting ? "Posting…" : "Post"}
              </button>
              <button
                type="button"
                className="bounty-form__cancel"
                onClick={() => setFormOpen(false)}
              >
                Cancel
              </button>
            </div>
          </div>
        </form>
      )}

      {error && (
        <div className="bounties-page__error" role="alert">
          {error}
        </div>
      )}

      {loading ? (
        <div className="bounties-page__loading">Loading…</div>
      ) : bounties.length === 0 && !formOpen ? (
        <EmptyState
          title="No bounties yet"
          description="Put points on a problem you want solved — anyone on the team (or any agent) can pick it up."
          cta={{ label: "Post a bounty", href: "/bounties" }}
        />
      ) : (
        <div className="bounties-page__list">
          {bounties.map((b) => (
            <BountyCard
              key={b.id}
              bounty={b}
              viewerId={viewerId}
              onClaim={(x) => void runTransition(claimBounty, x)}
              onUnclaim={(x) => void runTransition(unclaimBounty, x)}
              onAward={(x) => void runTransition(awardBounty, x)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
