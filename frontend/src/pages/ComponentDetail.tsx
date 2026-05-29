/**
 * WP60 — Stub detail page for components.
 *
 * Search results (WP56/WP57) link to `/components/<id>`. The backend has
 * no GET-by-id route for a single component — the only read surface is
 * `GET /api/v1/projects/{id}/components`. To stay within v2.9-WP60
 * scope ("use what's there, do NOT add new backend routes") we fan out:
 * list projects, then read components per project until the id matches.
 *
 * For small project counts this is fine; if it ever grows hot, the
 * obvious follow-up is to add `GET /api/v1/components/{id}` server-side.
 */
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  listProjects,
  listComponents,
  type ComponentDTO,
  type ProjectDTO,
} from "../api/projects";

interface Resolved {
  component: ComponentDTO;
  project: ProjectDTO | null;
}

export default function ComponentDetail() {
  const { id = "" } = useParams<{ id: string }>();
  const [state, setState] = useState<
    | { kind: "loading" }
    | { kind: "ok"; data: Resolved }
    | { kind: "missing" }
    | { kind: "error"; message: string }
  >({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;

    async function resolve() {
      try {
        const projects = await listProjects({ includeArchived: true });
        for (const proj of projects.items) {
          if (cancelled) return;
          try {
            const comps = await listComponents(proj.id);
            const hit = comps.items.find((c) => c.id === id);
            if (hit) {
              if (!cancelled) {
                setState({ kind: "ok", data: { component: hit, project: proj } });
              }
              return;
            }
          } catch {
            // ignore per-project failure — keep scanning
          }
        }
        if (!cancelled) setState({ kind: "missing" });
      } catch (err) {
        if (!cancelled) {
          setState({
            kind: "error",
            message: err instanceof Error ? err.message : "Failed to load component",
          });
        }
      }
    }

    setState({ kind: "loading" });
    resolve();
    return () => {
      cancelled = true;
    };
  }, [id]);

  if (state.kind === "loading") {
    return (
      <div className="entity-detail-stub">
        <p>Loading component...</p>
      </div>
    );
  }

  if (state.kind === "missing") {
    return (
      <div className="entity-detail-stub">
        <h1>Component not found</h1>
        <p>No component matches <code>{id}</code>.</p>
        <p>
          <Link to="/">Back to home</Link>
        </p>
      </div>
    );
  }

  if (state.kind === "error") {
    return (
      <div className="entity-detail-stub">
        <h1>Component unavailable</h1>
        <p>{state.message}</p>
      </div>
    );
  }

  const { component, project } = state.data;
  return (
    <div className="entity-detail-stub">
      <h1>{component.name}</h1>
      {component.description && <p>{component.description}</p>}
      <dl className="entity-detail-stub__meta">
        <dt>Project</dt>
        <dd>{project ? project.name : component.project_id}</dd>
        <dt>Component ID</dt>
        <dd><code>{component.id}</code></dd>
      </dl>
      <p>
        <Link to={`/search?q=${encodeURIComponent(component.name)}&entity=tickets`}>
          Find tickets touching this component
        </Link>
      </p>
    </div>
  );
}
