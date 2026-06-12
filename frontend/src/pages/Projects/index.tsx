import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listProjects, type ProjectDTO } from "../../api/projects";
import "./Projects.css";

export default function ProjectsPage() {
  const [projects, setProjects] = useState<ProjectDTO[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    // eslint-disable-next-line no-console
    console.log("[ProjectsPage] effect mounted, calling listProjects()");
    listProjects()
      .then((page) => {
        // eslint-disable-next-line no-console
        console.log("[ProjectsPage] listProjects resolved:", page);
        if (!cancelled) setProjects(page.items);
      })
      .catch((e: unknown) => {
        // eslint-disable-next-line no-console
        console.error("[ProjectsPage] listProjects rejected:", e);
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="projects-page">
      <header className="projects-page__header">
        <h1 className="projects-page__title">Projects</h1>
        <p className="projects-page__subtitle">
          Open a project to see its full ticket hierarchy.
        </p>
      </header>

      {loading && <div aria-busy="true">Loading projects…</div>}
      {error && (
        <div role="alert" className="projects-page__error">
          {error}
        </div>
      )}

      {!loading && !error && projects.length === 0 && (
        <div className="projects-page__empty">No projects yet.</div>
      )}

      <ul className="projects-page__grid">
        {projects.map((p) => (
          <li key={p.id} className="projects-page__card">
            <Link
              to={`/projects/${p.id}/hierarchy`}
              className="projects-page__card-link"
            >
              <div className="projects-page__card-key">{p.key}</div>
              <div className="projects-page__card-name">{p.name}</div>
              {p.description && (
                <div className="projects-page__card-desc">{p.description}</div>
              )}
              <div className="projects-page__card-cta">View hierarchy →</div>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
