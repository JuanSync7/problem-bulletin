/**
 * WP57 — Tabbed multi-entity search page.
 *
 * Tabs: All / Problems / Tickets / Components / Labels / Users
 *
 * Query persists across tab switches; URL is synced via ?q=...&entity=...
 * Debounce: 300 ms. In-flight requests aborted on query change or tab switch.
 * Filters swap per tab (Problems: status + category; Tickets: status + project;
 * Components: project; Labels/Users: no filters; All: no filters).
 *
 * Tab idiom matches Settings.tsx (role="tablist" + settings__tab buttons).
 */

import { useState, useEffect, useCallback } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import type { ProblemStatus } from "../components/StatusBadge";
import { StatusBadge } from "../components/StatusBadge";
import { type SearchEntity, type SearchItem, type SearchV2Response } from "../api/search";
import type { ProjectDTO } from "../api/projects";
import { listProjects } from "../api/projects";
import { KindPill } from "../components/KindPill";
import { useSearchV2 } from "../hooks/useSearchV2";
import { useRecentSearches } from "../components/GlobalSearchBar/useRecentSearches";
import { useAuth } from "../hooks/useAuth";
import "./Search.css";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PROBLEM_STATUSES: ProblemStatus[] = ["open", "claimed", "solved", "accepted", "duplicate"];
const TICKET_STATUSES = ["todo", "in_progress", "in_review", "blocked", "done", "cancelled"] as const;
type TicketStatus = (typeof TICKET_STATUSES)[number];

const TABS: { id: SearchEntity; label: string }[] = [
  { id: "all", label: "All" },
  { id: "problems", label: "Problems" },
  { id: "tickets", label: "Tickets" },
  { id: "components", label: "Components" },
  { id: "labels", label: "Labels" },
  { id: "users", label: "Users" },
  // v2.29-S6: Share / Bounty spaces
  { id: "share_posts", label: "Share" },
  { id: "bounties", label: "Bounties" },
];

// WP11: validated entity IDs for URL→state seeding.
const VALID_ENTITIES: ReadonlySet<SearchEntity> = new Set(TABS.map((t) => t.id));
const VALID_PROBLEM_STATUSES: ReadonlySet<string> = new Set(PROBLEM_STATUSES);
const VALID_TICKET_STATUSES: ReadonlySet<string> = new Set(TICKET_STATUSES);

/**
 * WP11: parse an unknown URL param into a SearchEntity; unknown values
 * fall back to "all". `searchParams.get("entity") as SearchEntity` was a
 * lie — values like ?entity=pizza slipped through and broke arm rendering.
 */
function parseEntity(value: string | null): SearchEntity {
  if (value && VALID_ENTITIES.has(value as SearchEntity)) return value as SearchEntity;
  return "all";
}

function parseProblemStatus(value: string | null): string {
  return value && VALID_PROBLEM_STATUSES.has(value) ? value : "";
}

function parseTicketStatus(value: string | null): TicketStatus | "" {
  return value && VALID_TICKET_STATUSES.has(value) ? (value as TicketStatus) : "";
}

// Top-N items shown per arm in the "All" overview tab.
const ALL_TAB_PREVIEW_LIMIT = 5;

interface Category {
  id: string;
  name: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function TicketStatusBadge({ status }: { status: string | null }) {
  if (!status) return null;
  const labels: Record<string, string> = {
    todo: "To Do",
    in_progress: "In Progress",
    in_review: "In Review",
    blocked: "Blocked",
    done: "Done",
    cancelled: "Cancelled",
  };
  return (
    <span className={`search-v2-ticket-status search-v2-ticket-status--${status}`}>
      {labels[status] ?? status}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Result card components
// ---------------------------------------------------------------------------

interface CardProps {
  item: SearchItem;
  onClick: () => void;
}

function ResultCard({ item, onClick }: CardProps) {
  return (
    <article
      className="search-result-card search-result-card--v2"
      onClick={onClick}
      tabIndex={0}
      role="link"
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClick();
        }
      }}
    >
      <div className="search-result-card__body">
        <div className="search-result-card__top-row">
          <KindPill kind={item.kind} />
          {item.display_id && (
            <span className="search-result-card__display-id">{item.display_id}</span>
          )}
          {item.status && item.kind === "problem" && (
            <StatusBadge status={item.status as ProblemStatus} />
          )}
          {item.status && item.kind === "ticket" && (
            <TicketStatusBadge status={item.status} />
          )}
        </div>
        <h3 className="search-result-card__title">{item.title}</h3>
        {item.subtitle && (
          <p className="search-result-card__excerpt">{item.subtitle}</p>
        )}
      </div>
    </article>
  );
}

// ---------------------------------------------------------------------------
// Empty / loading states
// ---------------------------------------------------------------------------

function EmptyState({ tabLabel }: { tabLabel: string }) {
  return (
    <div className="search-page__empty">
      <div className="search-page__empty-icon">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
          <circle cx="11" cy="11" r="8" />
          <path d="M21 21l-4.35-4.35" />
        </svg>
      </div>
      <h2 className="search-page__empty-title">No {tabLabel.toLowerCase()} found</h2>
      <p className="search-page__empty-description">
        Try a different search term or adjust your filters.
      </p>
    </div>
  );
}

function Loader() {
  return (
    <div className="search-page__loading">
      <div className="search-page__spinner" />
      Searching...
    </div>
  );
}

// ---------------------------------------------------------------------------
// All tab — side-by-side preview arms
// ---------------------------------------------------------------------------

interface AllTabProps {
  data: SearchV2Response;
  onNavigate: (href: string, item: SearchItem) => void;
}

function AllTabView({ data, onNavigate }: AllTabProps) {
  const arms: { key: keyof SearchV2Response; label: string }[] = [
    { key: "problems", label: "Problems" },
    { key: "tickets", label: "Tickets" },
    { key: "components", label: "Components" },
    { key: "labels", label: "Labels" },
    { key: "users", label: "Users" },
    { key: "share_posts", label: "Share" },
    { key: "bounties", label: "Bounties" },
  ];

  return (
    <div className="search-all-grid">
      {arms.map(({ key, label }) => {
        const arm = data[key];
        const items = arm?.items ?? [];
        const total = arm?.total ?? 0;
        return (
          <section key={key} className="search-all-arm">
            <h3 className="search-all-arm__heading">
              {label}
              <span className="search-all-arm__total">{total}</span>
            </h3>
            {items.length === 0 ? (
              <p className="search-all-arm__none">No results</p>
            ) : (
              <ul className="search-all-arm__list">
                {items.slice(0, ALL_TAB_PREVIEW_LIMIT).map((item) => (
                  <li key={item.id}>
                    <ResultCard item={item} onClick={() => onNavigate(item.href, item)} />
                  </li>
                ))}
              </ul>
            )}
          </section>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Single-arm paginated view
// ---------------------------------------------------------------------------

interface ArmViewProps {
  items: SearchItem[];
  total: number;
  tabLabel: string;
  onNavigate: (href: string, item: SearchItem) => void;
  hasPrev: boolean;
  hasNext: boolean;
  onPrev: () => void;
  onNext: () => void;
}

/**
 * WP08: cursor-driven Next/Prev. No page-number widget — the backend uses
 * seek pagination on (rank, created_at, id) per arm, and the hook maintains
 * the cursor stack. `total` is still rendered for orientation; "Showing N
 * of T" is good enough without paging arithmetic.
 */
function ArmView({ items, total, tabLabel, onNavigate, hasPrev, hasNext, onPrev, onNext }: ArmViewProps) {
  if (items.length === 0) return <EmptyState tabLabel={tabLabel} />;

  return (
    <div className="search-page__results">
      <p className="search-page__result-count">
        {total} result{total !== 1 ? "s" : ""} found
      </p>
      {items.map((item) => (
        <ResultCard key={item.id} item={item} onClick={() => onNavigate(item.href, item)} />
      ))}
      {(hasPrev || hasNext) && (
        <div className="search-v2-pagination">
          <button
            className="search-v2-pagination__btn"
            disabled={!hasPrev}
            onClick={onPrev}
            aria-label="Previous page"
          >
            Previous
          </button>
          <button
            className="search-v2-pagination__btn"
            disabled={!hasNext}
            onClick={onNext}
            aria-label="Next page"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Search page
// ---------------------------------------------------------------------------

const PAGE_SIZE = 20;

export default function Search() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  // v2.29-S6 (audit P2#17): recent searches share the same localStorage
  // store as GlobalSearchBar (key: aion.search.recents.<userId>).
  const { user } = useAuth();
  const { recents } = useRecentSearches(user?.id ?? "anon");

  // WP11: derive initial state from URL params (seed once on mount; later
  // edits flow state → URL via the sync effect below). Invalid enum values
  // (entity=pizza, problem_status=banana) are dropped to safe defaults.
  const initialQ = searchParams.get("q") ?? "";
  const initialEntity = parseEntity(searchParams.get("entity"));

  const [query, setQuery] = useState(initialQ);
  const [debouncedQuery, setDebouncedQuery] = useState(initialQ);
  const [activeTab, setActiveTab] = useState<SearchEntity>(initialEntity);
  const [page, setPage] = useState(0);

  // Per-tab filter state — WP11 seeds from URL (snake_case keys matching the
  // /api/search/v2 query string contract).
  const [problemStatus, setProblemStatus] = useState<string>(
    parseProblemStatus(searchParams.get("problem_status")),
  );
  const [problemCategoryId, setProblemCategoryId] = useState<string>(
    searchParams.get("problem_category_id") ?? "",
  );
  const [ticketStatus, setTicketStatus] = useState<TicketStatus | "">(
    parseTicketStatus(searchParams.get("ticket_status")),
  );
  const [ticketProjectId, setTicketProjectId] = useState<string>(
    searchParams.get("ticket_project_id") ?? "",
  );
  const [componentProjectId, setComponentProjectId] = useState<string>(
    searchParams.get("component_project_id") ?? "",
  );

  // Search data — sourced from the useSearchV2 hook (WP64, WP08 cursor,
  // WP10 v2.12 totalAuthority/refreshTotal).
  const {
    data,
    isLoading,
    error,
    hasSearched,
    hasNext,
    hasPrev,
    loadNext,
    loadPrev,
    totalAuthority,
    refreshTotal,
  } = useSearchV2({
    query: debouncedQuery,
    entity: activeTab,
    filters: {
      problemStatus,
      problemCategoryId,
      ticketStatus,
      ticketProjectId,
      componentProjectId,
    },
    page,
    pageSize: PAGE_SIZE,
    allTabPreviewLimit: ALL_TAB_PREVIEW_LIMIT,
  });

  // Support data
  const [categories, setCategories] = useState<Category[]>([]);
  const [projects, setProjects] = useState<ProjectDTO[]>([]);

  // Fetch categories (for problems filter)
  useEffect(() => {
    async function fetchCategories() {
      try {
        const res = await fetch("/api/admin/categories", { credentials: "include" });
        if (res.ok) setCategories(await res.json());
      } catch {
        // ignore
      }
    }
    fetchCategories();
  }, []);

  // Fetch projects (for tickets / components filter)
  useEffect(() => {
    listProjects()
      .then((page) => setProjects(page.items))
      .catch(() => {
        // ignore — project filter degrades gracefully
      });
  }, []);

  // Debounce 300ms
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedQuery(query.trim());
      setPage(0); // reset pagination on new query
    }, 300);
    return () => clearTimeout(timer);
  }, [query]);

  // WP11: bidirectional URL sync — write every non-empty filter to the URL.
  // `replace: true` keeps the history clean (debounced query edits don't
  // each create a back-button entry). Empty filters are omitted entirely
  // rather than serialised as ?key= — keeps URLs short and avoids signalling
  // to bots/crawlers that empty-string is a meaningful value.
  // Cursors are deliberately NOT synced (security: HMAC payloads leak via
  // Referer; ergonomics: cursors are session-scoped and reset on every
  // filter change anyway).
  useEffect(() => {
    const params: Record<string, string> = {};
    if (debouncedQuery) params.q = debouncedQuery;
    if (activeTab !== "all") params.entity = activeTab;
    if (problemStatus) params.problem_status = problemStatus;
    if (problemCategoryId) params.problem_category_id = problemCategoryId;
    if (ticketStatus) params.ticket_status = ticketStatus;
    if (ticketProjectId) params.ticket_project_id = ticketProjectId;
    if (componentProjectId) params.component_project_id = componentProjectId;
    setSearchParams(params, { replace: true });
  }, [
    debouncedQuery,
    activeTab,
    problemStatus,
    problemCategoryId,
    ticketStatus,
    ticketProjectId,
    componentProjectId,
    setSearchParams,
  ]);

  // Navigate helper — derives the correct path from item data
  const handleNavigate = useCallback((href: string, item: SearchItem) => {
    // Prefer the backend-supplied href; for labels, compose a search URL.
    if (item.kind === "label") {
      navigate(`/search?q=${encodeURIComponent(item.title)}&entity=labels`);
      return;
    }
    navigate(href);
  }, [navigate]);

  // Tab switch: reset page. The useSearchV2 hook handles aborting the
  // in-flight request when `entity` changes.
  function switchTab(tab: SearchEntity) {
    setActiveTab(tab);
    setPage(0);
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const activeTabLabel = TABS.find((t) => t.id === activeTab)?.label ?? "Results";

  const activeArm =
    activeTab !== "all" && data ? data[activeTab as keyof SearchV2Response] : null;
  const armItems = activeArm?.items ?? [];
  const armTotal = activeArm?.total ?? 0;

  return (
    <div className="search-page">
      {/* Header */}
      <div className="search-page__header">
        <h1 className="search-page__title">Search</h1>
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
            placeholder="Search problems, tickets, components, labels, users..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            autoFocus
          />
        </div>
      </div>

      {/* Tabs — Settings.tsx idiom: role="tablist", role="tab", aria-selected */}
      <div className="search-v2-tablist" role="tablist" aria-label="Search scope">
        {TABS.map((tab) => {
          const count = getTabCount(tab.id, data);
          return (
            <button
              key={tab.id}
              role="tab"
              aria-selected={activeTab === tab.id}
              className={`search-v2-tab${activeTab === tab.id ? " search-v2-tab--active" : ""}`}
              onClick={() => switchTab(tab.id)}
            >
              {tab.label}
              {count !== null && hasSearched && (
                <span className="search-v2-tab__count" aria-hidden="true">{count}</span>
              )}
            </button>
          );
        })}
      </div>

      {/* Per-tab filters */}
      {activeTab === "problems" && (
        <div className="search-page__filters" data-testid="filters-problems">
          <select
            className="search-page__filter-select"
            value={problemStatus}
            onChange={(e) => { setProblemStatus(e.target.value); setPage(0); }}
            aria-label="Problem status"
          >
            <option value="">All Statuses</option>
            {PROBLEM_STATUSES.map((s) => (
              <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</option>
            ))}
          </select>
          <select
            className="search-page__filter-select"
            value={problemCategoryId}
            onChange={(e) => { setProblemCategoryId(e.target.value); setPage(0); }}
            aria-label="Problem category"
          >
            <option value="">All Categories</option>
            {categories.map((cat) => (
              <option key={cat.id} value={cat.id}>{cat.name}</option>
            ))}
          </select>
        </div>
      )}

      {activeTab === "tickets" && (
        <div className="search-page__filters" data-testid="filters-tickets">
          <select
            className="search-page__filter-select"
            value={ticketStatus}
            onChange={(e) => { setTicketStatus(e.target.value as TicketStatus | ""); setPage(0); }}
            aria-label="Ticket status"
          >
            <option value="">All Statuses</option>
            {TICKET_STATUSES.map((s) => (
              <option key={s} value={s}>
                {s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
              </option>
            ))}
          </select>
          <select
            className="search-page__filter-select"
            value={ticketProjectId}
            onChange={(e) => { setTicketProjectId(e.target.value); setPage(0); }}
            aria-label="Ticket project"
          >
            <option value="">All Projects</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </div>
      )}

      {activeTab === "components" && (
        <div className="search-page__filters" data-testid="filters-components">
          <select
            className="search-page__filter-select"
            value={componentProjectId}
            onChange={(e) => { setComponentProjectId(e.target.value); setPage(0); }}
            aria-label="Component project"
          >
            <option value="">All Projects</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </div>
      )}

      {/* WP10 (v2.12) + WP06 (v2.13): snapshot-total banner. Rendered above
          the loader so the "Refreshing…" disabled state is visible during
          the refresh fetch.
          - Single arm: shown after advancing ≥1 page while authority is
            still snapshot (the WP10 contract).
          - All tab (WP06): shown whenever any present arm is still
            snapshot. There is no cursor chain on entity=all, so the
            `hasPrev` predicate doesn't apply — the trigger is purely
            "any arm has a snapshot total worth refreshing". Clicking
            the button fires one request with refresh_total=true and the
            backend broadcasts the recount to every arm.
          Banner disappears once backend returns live across the board. */}
      {totalAuthority === "snapshot" &&
        (activeTab === "all" ? true : hasPrev) && (
          <div
            className="search-snapshot-banner"
            role="status"
            aria-live="polite"
          >
            <span className="search-snapshot-banner__text">
              {activeTab === "all"
                ? "Showing snapshot counts — refresh to update"
                : "Showing snapshot count — refresh to update"}
            </span>
            <button
              type="button"
              className="search-snapshot-banner__btn"
              onClick={refreshTotal}
              disabled={isLoading}
            >
              {isLoading
                ? "Refreshing…"
                : activeTab === "all"
                  ? "Refresh counts"
                  : "Refresh count"}
            </button>
          </div>
        )}

      {/* Content area */}
      {isLoading && <Loader />}

      {error && <div className="search-page__error">{error}</div>}

      {!isLoading && !error && !hasSearched && (
        <div className="search-page__empty">
          <div className="search-page__empty-icon">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
              <circle cx="11" cy="11" r="8" />
              <path d="M21 21l-4.35-4.35" />
            </svg>
          </div>
          <h2 className="search-page__empty-title">Search across everything</h2>
          <p className="search-page__empty-description">
            Type a query above to find problems, tickets, components, labels, and users.
          </p>
          {recents.length > 0 && (
            <div
              className="search-page__recents"
              role="group"
              aria-label="Recent searches"
            >
              <span className="search-page__recents-label">Recent searches</span>
              <div className="search-page__recents-chips">
                {recents.map((q) => (
                  <button
                    key={q}
                    type="button"
                    className="search-page__recent-chip"
                    onClick={() => setQuery(q)}
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {!isLoading && !error && hasSearched && data && (
        <>
          {activeTab === "all" ? (
            <AllTabView data={data} onNavigate={handleNavigate} />
          ) : (
            <ArmView
              items={armItems}
              total={armTotal}
              tabLabel={activeTabLabel}
              onNavigate={handleNavigate}
              hasPrev={hasPrev}
              hasNext={hasNext}
              onPrev={loadPrev}
              onNext={loadNext}
            />
          )}
        </>
      )}

      {!isLoading && !error && hasSearched && !data && (
        <EmptyState tabLabel={activeTabLabel} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

function getTabCount(tab: SearchEntity, data: SearchV2Response | null): number | null {
  if (!data) return null;
  if (tab === "all") {
    const total =
      (data.problems?.total ?? 0) +
      (data.tickets?.total ?? 0) +
      (data.components?.total ?? 0) +
      (data.labels?.total ?? 0) +
      (data.users?.total ?? 0) +
      (data.share_posts?.total ?? 0) +
      (data.bounties?.total ?? 0);
    return total;
  }
  return data[tab as keyof SearchV2Response]?.total ?? null;
}
