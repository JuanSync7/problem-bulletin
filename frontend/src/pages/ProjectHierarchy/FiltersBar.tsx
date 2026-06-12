/**
 * B2: FiltersBar — project-hierarchy page filters.
 *
 * Controls:
 *  - Project select (from listProjects)
 *  - Type checkboxes (one per type found in the data)
 *  - Depth slider 1..8 (triggers re-fetch via parent)
 */
import { useEffect, useState } from "react";
import { listProjects, type ProjectDTO } from "../../api/projects";

export interface HierarchyFilters {
  hiddenTypes: string[];
  maxDepth: number;
}

interface FiltersBarProps {
  projectId: string;
  allTypes: string[];
  filters: HierarchyFilters;
  onChange: (next: HierarchyFilters) => void;
  onProjectChange: (newProjectId: string) => void;
}

export function FiltersBar({
  projectId,
  allTypes,
  filters,
  onChange,
  onProjectChange,
}: FiltersBarProps) {
  const [projects, setProjects] = useState<ProjectDTO[]>([]);

  useEffect(() => {
    let cancelled = false;
    listProjects()
      .then((res) => {
        if (!cancelled) setProjects(res.items);
      })
      .catch(() => {
        // silently ignore — project selector degrades gracefully
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function toggleType(type: string) {
    const hidden = filters.hiddenTypes.includes(type)
      ? filters.hiddenTypes.filter((t) => t !== type)
      : [...filters.hiddenTypes, type];
    onChange({ ...filters, hiddenTypes: hidden });
  }

  function handleDepth(e: React.ChangeEvent<HTMLInputElement>) {
    const val = parseInt(e.target.value, 10);
    onChange({ ...filters, maxDepth: val });
  }

  return (
    <div className="hierarchy-filters">
      {/* Project selector */}
      {projects.length > 0 && (
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          <label className="hierarchy-filters__label" htmlFor="hierarchy-project-select">
            Project:
          </label>
          <select
            id="hierarchy-project-select"
            value={projectId}
            onChange={(e) => onProjectChange(e.target.value)}
            style={{ fontSize: "0.85rem" }}
          >
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.key} — {p.name}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Type filter checkboxes */}
      {allTypes.length > 0 && (
        <div className="hierarchy-filters__checkboxes">
          <span className="hierarchy-filters__label">Show:</span>
          {allTypes.map((type) => (
            <label key={type} className="hierarchy-filters__checkbox-label">
              <input
                type="checkbox"
                data-type={type}
                checked={!filters.hiddenTypes.includes(type)}
                onChange={() => toggleType(type)}
              />
              {type}
            </label>
          ))}
        </div>
      )}

      {/* Depth slider */}
      <div className="hierarchy-filters__depth">
        <span className="hierarchy-filters__label">Max depth:</span>
        <input
          type="range"
          min={1}
          max={8}
          step={1}
          value={filters.maxDepth}
          onChange={handleDepth}
          aria-label="Max hierarchy depth"
        />
        <span>{filters.maxDepth}</span>
      </div>
    </div>
  );
}
