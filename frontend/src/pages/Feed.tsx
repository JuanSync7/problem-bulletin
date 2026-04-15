import React, { useState, useEffect, useRef, useCallback } from "react";
import { ProblemCard } from "../components/ProblemCard";
import { SortFilterBar } from "../components/SortFilterBar";
import { EmptyState } from "../components/EmptyState";
import type { ProblemSummary } from "../components/ProblemCard";
import type { SortOption } from "../components/SortFilterBar";
import type { ProblemStatus } from "../components/StatusBadge";
import "./Feed.css";

interface FeedResponse {
  items: ProblemSummary[];
  next_cursor: string | null;
}

function SkeletonCard() {
  return (
    <div className="problem-card-skeleton" aria-hidden="true">
      <div className="problem-card-skeleton__upstars">
        <div className="skeleton-pulse skeleton-circle" />
        <div className="skeleton-pulse skeleton-line skeleton-line--xs" />
      </div>
      <div className="problem-card-skeleton__body">
        <div className="skeleton-pulse skeleton-line skeleton-line--lg" />
        <div className="skeleton-pulse skeleton-line skeleton-line--full" />
        <div className="skeleton-pulse skeleton-line skeleton-line--md" />
        <div className="problem-card-skeleton__footer">
          <div className="skeleton-pulse skeleton-line skeleton-line--sm" />
          <div className="skeleton-pulse skeleton-line skeleton-line--sm" />
        </div>
      </div>
    </div>
  );
}

export default function Feed() {
  const [problems, setProblems] = useState<ProblemSummary[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(true);

  const [sort, setSort] = useState<SortOption>("new");
  const [statusFilters, setStatusFilters] = useState<ProblemStatus[]>([]);
  const [category, setCategory] = useState("");
  const [domain, setDomain] = useState("");

  const sentinelRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  const fetchProblems = useCallback(
    async (loadCursor: string | null, append: boolean) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      if (append) {
        setIsLoadingMore(true);
      } else {
        setIsLoading(true);
      }
      setError(null);

      try {
        const params = new URLSearchParams();
        params.set("sort", sort);
        if (statusFilters.length > 0) {
          params.set("status", statusFilters.join(","));
        }
        if (category) {
          params.set("category", category);
        }
        if (loadCursor) {
          params.set("cursor", loadCursor);
        }

        const res = await fetch(`/api/problems?${params.toString()}`, {
          credentials: "include",
          signal: controller.signal,
        });

        if (!res.ok) {
          throw new Error(`Failed to load problems (${res.status})`);
        }

        const data: FeedResponse = await res.json();

        if (append) {
          setProblems((prev) => [...prev, ...data.items]);
        } else {
          setProblems(data.items);
        }
        setCursor(data.next_cursor);
        setHasMore(data.next_cursor !== null);
      } catch (err) {
        if ((err as Error).name === "AbortError") return;
        setError((err as Error).message || "Something went wrong");
      } finally {
        setIsLoading(false);
        setIsLoadingMore(false);
      }
    },
    [sort, statusFilters, category, domain],
  );

  // Reset and fetch on filter/sort change
  useEffect(() => {
    setProblems([]);
    setCursor(null);
    setHasMore(true);
    fetchProblems(null, false);

    return () => {
      abortRef.current?.abort();
    };
  }, [fetchProblems]);

  // Infinite scroll via IntersectionObserver
  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && hasMore && !isLoading && !isLoadingMore) {
          fetchProblems(cursor, true);
        }
      },
      { rootMargin: "200px" },
    );

    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [hasMore, isLoading, isLoadingMore, cursor, fetchProblems]);

  return (
    <div className="feed">
      <div className="feed__header">
        <h1 className="feed__title">Problems</h1>
      </div>

      <SortFilterBar
        sort={sort}
        statusFilters={statusFilters}
        category={category}
        domain={domain}
        onSort={setSort}
        onStatusFilter={setStatusFilters}
        onCategoryFilter={setCategory}
        onDomainFilter={setDomain}
      />

      {error && (
        <div className="feed__error" role="alert">
          <p>{error}</p>
          <button
            className="feed__retry-btn"
            onClick={() => fetchProblems(null, false)}
          >
            Retry
          </button>
        </div>
      )}

      {isLoading && (
        <div className="feed__skeleton-list">
          {Array.from({ length: 5 }).map((_, i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      )}

      {!isLoading && !error && problems.length === 0 && (
        <EmptyState
          title="No problems found"
          description="Try adjusting your filters or be the first to submit a problem."
          cta={{ label: "Submit a Problem", href: "/submit" }}
        />
      )}

      {!isLoading && problems.length > 0 && (
        <div className="feed__list">
          {problems.map((p) => (
            <ProblemCard key={p.id} problem={p} />
          ))}
        </div>
      )}

      {isLoadingMore && (
        <div className="feed__loading-more">
          <div className="app-loading__spinner" />
        </div>
      )}

      <div ref={sentinelRef} className="feed__sentinel" aria-hidden="true" />
    </div>
  );
}
