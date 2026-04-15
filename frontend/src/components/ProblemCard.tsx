import React from "react";
import { useNavigate } from "react-router-dom";
import { StatusBadge } from "./StatusBadge";
import type { ProblemStatus } from "./StatusBadge";
import "./ProblemCard.css";

export interface ProblemSummary {
  id: string;
  display_id?: string;
  title: string;
  description: string;
  status: ProblemStatus;
  category: { id: string; name: string; slug: string } | null;
  tags: { id: string; name: string }[];
  upstar_count: number;
  solution_count: number;
  comment_count: number;
  created_at: string;
  author: {
    id: string;
    display_name: string;
  } | null;
}

interface ProblemCardProps {
  problem: ProblemSummary;
}

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

export function ProblemCard({ problem }: ProblemCardProps) {
  const navigate = useNavigate();

  function handleClick() {
    navigate(`/problems/${problem.id}`);
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      navigate(`/problems/${problem.id}`);
    }
  }

  return (
    <article
      className="problem-card"
      onClick={handleClick}
      onKeyDown={handleKeyDown}
      tabIndex={0}
      role="link"
      aria-label={`Problem: ${problem.title}`}
    >
      <div className="problem-card__upstars">
        <svg
          className="problem-card__star-icon"
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="currentColor"
          aria-hidden="true"
        >
          <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
        </svg>
        <span className="problem-card__upstar-count">{problem.upstar_count}</span>
      </div>

      <div className="problem-card__body">
        <div className="problem-card__header">
          <h3 className="problem-card__title">
            {problem.display_id && <span className="problem-card__display-id">{problem.display_id}</span>}
            {problem.title}
          </h3>
          <div className="problem-card__badges">
            <StatusBadge status={problem.status} />
            {problem.category && <span className="problem-card__category-pill">{problem.category.name}</span>}
          </div>
        </div>

        <p className="problem-card__description">{problem.description}</p>

        {problem.tags.length > 0 && (
          <div className="problem-card__tags">
            {problem.tags.map((tag) => (
              <span key={tag.id} className="problem-card__tag">
                {tag.name}
              </span>
            ))}
          </div>
        )}

        <div className="problem-card__footer">
          <span className="problem-card__meta">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <path d="M9 12h6m-3-3v6m-7 4h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
            </svg>
            {problem.solution_count} solution{problem.solution_count !== 1 ? "s" : ""}
          </span>
          <span className="problem-card__meta">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
            </svg>
            {problem.comment_count} comment{problem.comment_count !== 1 ? "s" : ""}
          </span>
          <span className="problem-card__timestamp">{relativeTime(problem.created_at)}</span>
        </div>
      </div>
    </article>
  );
}
