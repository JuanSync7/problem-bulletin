import React, { useState, useEffect } from "react";
import type { ProblemStatus } from "./StatusBadge";

export type SortOption = "new" | "top" | "active" | "discussed";

const SORT_OPTIONS: { value: SortOption; label: string }[] = [
  { value: "new", label: "New" },
  { value: "top", label: "Top" },
  { value: "active", label: "Active" },
  { value: "discussed", label: "Discussed" },
];

const STATUS_OPTIONS: ProblemStatus[] = ["open", "claimed", "solved", "accepted", "duplicate"];

interface Category {
  id: string;
  name: string;
}

interface Domain {
  id: string;
  name: string;
}

interface SortFilterBarProps {
  sort: SortOption;
  statusFilters: ProblemStatus[];
  category: string;
  domain: string;
  onSort: (sort: SortOption) => void;
  onStatusFilter: (statuses: ProblemStatus[]) => void;
  onCategoryFilter: (category: string) => void;
  onDomainFilter: (domain: string) => void;
}

export function SortFilterBar({
  sort,
  statusFilters,
  category,
  domain,
  onSort,
  onStatusFilter,
  onCategoryFilter,
  onDomainFilter,
}: SortFilterBarProps) {
  const [categories, setCategories] = useState<Category[]>([]);
  const [domains, setDomains] = useState<Domain[]>([]);

  useEffect(() => {
    let cancelled = false;
    async function fetchData() {
      try {
        const [catRes, domRes] = await Promise.all([
          fetch("/api/admin/categories", { credentials: "include" }),
          fetch("/api/domains", { credentials: "include" }),
        ]);
        if (catRes.ok && !cancelled) setCategories(await catRes.json());
        if (domRes.ok && !cancelled) setDomains(await domRes.json());
      } catch {
        // ignore
      }
    }
    fetchData();
    return () => { cancelled = true; };
  }, []);

  function handleStatusToggle(status: ProblemStatus) {
    if (statusFilters.includes(status)) {
      onStatusFilter(statusFilters.filter((s) => s !== status));
    } else {
      onStatusFilter([...statusFilters, status]);
    }
  }

  return (
    <div className="sort-filter-bar">
      <div className="sort-filter-bar__sort">
        <label className="sort-filter-bar__label" htmlFor="sort-select">
          Sort
        </label>
        <select
          id="sort-select"
          className="sort-filter-bar__select"
          value={sort}
          onChange={(e) => onSort(e.target.value as SortOption)}
        >
          {SORT_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>

      <div className="sort-filter-bar__statuses">
        <span className="sort-filter-bar__label">Status</span>
        <div className="sort-filter-bar__checkbox-group">
          {STATUS_OPTIONS.map((status) => (
            <label key={status} className="sort-filter-bar__checkbox-label">
              <input
                type="checkbox"
                checked={statusFilters.includes(status)}
                onChange={() => handleStatusToggle(status)}
                className="sort-filter-bar__checkbox"
              />
              <span className="sort-filter-bar__checkbox-text">{status}</span>
            </label>
          ))}
        </div>
      </div>

      <div className="sort-filter-bar__category">
        <label className="sort-filter-bar__label" htmlFor="category-select">
          Category
        </label>
        <select
          id="category-select"
          className="sort-filter-bar__select"
          value={category}
          onChange={(e) => onCategoryFilter(e.target.value)}
        >
          <option value="">All Categories</option>
          {categories.map((cat) => (
            <option key={cat.id} value={cat.id}>
              {cat.name}
            </option>
          ))}
        </select>
      </div>

      <div className="sort-filter-bar__category">
        <label className="sort-filter-bar__label" htmlFor="domain-select">
          Domain
        </label>
        <select
          id="domain-select"
          className="sort-filter-bar__select"
          value={domain}
          onChange={(e) => onDomainFilter(e.target.value)}
        >
          <option value="">All Domains</option>
          {domains.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
