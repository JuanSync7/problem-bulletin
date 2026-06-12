/**
 * B2: ProjectHierarchyPage
 *
 * Route: /projects/:projectId/hierarchy
 *
 * Drives:
 *  - URL params as source of truth for projectId
 *  - HierarchyFilters (hiddenTypes + maxDepth) in component state
 *  - Calls getProjectHierarchy on mount and when maxDepth changes
 *  - Renders <FiltersBar /> + <ProjectHierarchyTree />
 *
 * The tree container is explicitly seamless (background: transparent;
 * border: none; box-shadow: none) — see ProjectHierarchy.css.
 *
 * V6a: adds a minimal tab strip ("Hierarchy" | "Lessons"). The
 * Hierarchy tab is the default; the tree container's seamless-background
 * invariant is preserved — the tab strip lives in the page header, not
 * inside the tree container.
 */
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { getProjectHierarchy, type HierarchyRow } from "../../api/projects";
import { FiltersBar, type HierarchyFilters } from "./FiltersBar";
import { LessonsTab } from "./LessonsTab";
import { ProjectHierarchyTree } from "./ProjectHierarchyTree";
import "./ProjectHierarchy.css";

const DEFAULT_FILTERS: HierarchyFilters = {
  hiddenTypes: [],
  maxDepth: 4,
};

type TabKey = "hierarchy" | "lessons";

export default function ProjectHierarchyPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();

  const [rows, setRows] = useState<HierarchyRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<HierarchyFilters>(DEFAULT_FILTERS);
  const [activeTab, setActiveTab] = useState<TabKey>("hierarchy");

  const effectiveProjectId = projectId ?? "";

  useEffect(() => {
    if (!effectiveProjectId) return;
    if (activeTab !== "hierarchy") return;
    let cancelled = false;
    setLoading(true);
    setError(null);

    getProjectHierarchy(effectiveProjectId, { max_depth: filters.maxDepth })
      .then((res) => {
        if (!cancelled) setRows(res.items);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [effectiveProjectId, filters.maxDepth, activeTab]);

  // Derive all unique ticket types from the data
  const allTypes = useMemo(() => {
    const seen = new Set<string>();
    for (const row of rows) seen.add(row.ticket.type);
    return Array.from(seen).sort();
  }, [rows]);

  function handleProjectChange(newProjectId: string) {
    navigate(`/projects/${newProjectId}/hierarchy`);
  }

  return (
    <div className="project-hierarchy-page">
      <div className="project-hierarchy-page__header">
        <h1 className="project-hierarchy-page__title">Project Hierarchy</h1>
      </div>

      <div
        className="project-hierarchy-page__tabs"
        role="tablist"
        aria-label="Project Hierarchy sections"
      >
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === "hierarchy"}
          className={
            "project-hierarchy-page__tab" +
            (activeTab === "hierarchy"
              ? " project-hierarchy-page__tab--active"
              : "")
          }
          onClick={() => setActiveTab("hierarchy")}
        >
          Hierarchy
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === "lessons"}
          className={
            "project-hierarchy-page__tab" +
            (activeTab === "lessons"
              ? " project-hierarchy-page__tab--active"
              : "")
          }
          onClick={() => setActiveTab("lessons")}
        >
          Lessons
        </button>
      </div>

      {activeTab === "hierarchy" && (
        <>
          <FiltersBar
            projectId={effectiveProjectId}
            allTypes={allTypes}
            filters={filters}
            onChange={setFilters}
            onProjectChange={handleProjectChange}
          />

          {loading && <div aria-busy="true">Loading hierarchy…</div>}
          {error && (
            <div role="alert" style={{ color: "var(--color-error, red)" }}>
              {error}
            </div>
          )}

          {!loading && (
            <ProjectHierarchyTree
              rows={rows}
              hiddenTypes={filters.hiddenTypes}
              projectId={effectiveProjectId}
            />
          )}
        </>
      )}

      {activeTab === "lessons" && (
        <LessonsTab projectId={effectiveProjectId} />
      )}
    </div>
  );
}
