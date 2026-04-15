import React, { useState, useEffect, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import type { ProblemStatus } from "../components/StatusBadge";
import { StatusBadge } from "../components/StatusBadge";
import "./Search.css";

interface SearchResult {
  problem_id: string;
  title: string;
  excerpt: string;
  rank: number;
  match_source: string;
  upstar_count: number;
  created_at: string;
}

interface Category {
  id: string;
  name: string;
}

const STATUS_OPTIONS: ProblemStatus[] = ["open", "claimed", "solved", "accepted", "duplicate"];

export default function Search() {
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasSearched, setHasSearched] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [categoryFilter, setCategoryFilter] = useState<string>("");
  const [sortMode, setSortMode] = useState<string>("relevance");
  const [categories, setCategories] = useState<Category[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const navigate = useNavigate();

  // Fetch categories
  useEffect(() => {
    async function fetchCategories() {
      try {
        const res = await fetch("/api/admin/categories", { credentials: "include" });
        if (res.ok) {
          setCategories(await res.json());
        }
      } catch {
        // ignore
      }
    }
    fetchCategories();
  }, []);

  // Debounce query by 300ms
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedQuery(query.trim());
    }, 300);
    return () => clearTimeout(timer);
  }, [query]);

  const fetchResults = useCallback(async (q: string) => {
    if (!q) {
      setResults([]);
      setHasSearched(false);
      return;
    }

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setIsLoading(true);
    setError(null);
    setHasSearched(true);

    try {
      const params = new URLSearchParams({ q });
      if (statusFilter) params.set("status", statusFilter);
      if (categoryFilter) params.set("category_id", categoryFilter);
      if (sortMode !== "relevance") params.set("sort", sortMode);

      const res = await fetch(`/api/search?${params.toString()}`, {
        signal: controller.signal,
        credentials: "include",
      });
      if (!res.ok) {
        throw new Error(`Search failed (${res.status})`);
      }
      const data = await res.json();
      if (!controller.signal.aborted) {
        setResults(data.results ?? []);
        setIsLoading(false);
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      if (!controller.signal.aborted) {
        setError(err instanceof Error ? err.message : "Search failed");
        setIsLoading(false);
      }
    }
  }, [statusFilter, categoryFilter, sortMode]);

  useEffect(() => {
    fetchResults(debouncedQuery);
  }, [debouncedQuery, fetchResults]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

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

  return (
    <div className="search-page">
      <div className="search-page__header">
        <h1 className="search-page__title">Search Problems</h1>
        <div className="search-page__input-wrapper">
          <svg
            className="search-page__icon"
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            aria-hidden="true"
          >
            <circle cx="11" cy="11" r="8" />
            <path d="M21 21l-4.35-4.35" />
          </svg>
          <input
            className="search-page__input"
            type="text"
            placeholder="Search by title, description, or tags..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            autoFocus
          />
        </div>

        {/* Filters */}
        <div className="search-page__filters">
          <select
            className="search-page__filter-select"
            value={sortMode}
            onChange={(e) => setSortMode(e.target.value)}
          >
            <option value="relevance">Sort: Relevance</option>
            <option value="newest">Sort: Newest</option>
            <option value="upvotes">Sort: Most Upstars</option>
          </select>

          <select
            className="search-page__filter-select"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          >
            <option value="">All Statuses</option>
            {STATUS_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {s.charAt(0).toUpperCase() + s.slice(1)}
              </option>
            ))}
          </select>

          <select
            className="search-page__filter-select"
            value={categoryFilter}
            onChange={(e) => setCategoryFilter(e.target.value)}
          >
            <option value="">All Categories</option>
            {categories.map((cat) => (
              <option key={cat.id} value={cat.id}>
                {cat.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      {isLoading && (
        <div className="search-page__loading">
          <div className="search-page__spinner" />
          Searching...
        </div>
      )}

      {error && <div className="search-page__error">{error}</div>}

      {!isLoading && !error && hasSearched && results.length === 0 && (
        <div className="search-page__empty">
          <div className="search-page__empty-icon">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
              <circle cx="11" cy="11" r="8" />
              <path d="M21 21l-4.35-4.35" />
            </svg>
          </div>
          <h2 className="search-page__empty-title">No results found</h2>
          <p className="search-page__empty-description">
            Try a different search term or adjust your filters.
          </p>
        </div>
      )}

      {!isLoading && !error && results.length > 0 && (
        <div className="search-page__results">
          <p className="search-page__result-count">
            {results.length} result{results.length !== 1 ? "s" : ""} found
          </p>
          {results.map((r) => (
            <article
              key={r.problem_id}
              className="search-result-card"
              onClick={() => navigate(`/problems/${r.problem_id}`)}
              tabIndex={0}
              role="link"
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  navigate(`/problems/${r.problem_id}`);
                }
              }}
            >
              <div className="search-result-card__upstars">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                  <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
                </svg>
                <span>{r.upstar_count}</span>
              </div>
              <div className="search-result-card__body">
                <h3 className="search-result-card__title">{r.title}</h3>
                <p className="search-result-card__excerpt">{r.excerpt}</p>
                <div className="search-result-card__meta">
                  <span className="search-result-card__source">Matched in: {r.match_source}</span>
                  <span>{relativeTime(r.created_at)}</span>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}

      {!isLoading && !error && !hasSearched && (
        <div className="search-page__empty">
          <div className="search-page__empty-icon">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
              <circle cx="11" cy="11" r="8" />
              <path d="M21 21l-4.35-4.35" />
            </svg>
          </div>
          <h2 className="search-page__empty-title">Search for problems</h2>
          <p className="search-page__empty-description">
            Type a query above to find problems by title, description, or tags.
          </p>
        </div>
      )}
    </div>
  );
}
