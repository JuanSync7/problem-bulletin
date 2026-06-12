/**
 * V6a — LessonsTab
 *
 * Lists project lessons newest-first with an inline add-form for project
 * members. Append-only — no edit/delete UI.
 *
 * v2.29: structured categorisation (category / severity / tags) is encoded
 * as a one-line `meta:` JSON prefix in the lesson body so we don't need a
 * schema migration. Older lessons without the prefix render as "Uncategorised"
 * and the body shows verbatim.
 */
import { useEffect, useMemo, useState } from "react";
import {
  createProjectLesson,
  listProjectLessons,
  type ProjectLessonDTO,
} from "../../api/projects";

interface LessonsTabProps {
  projectId: string;
}

type Category = "bug" | "decision" | "process" | "tech" | "people" | "other";
type Severity = "low" | "medium" | "high" | "critical";

const CATEGORIES: Category[] = ["bug", "decision", "process", "tech", "people", "other"];
const SEVERITIES: Severity[] = ["low", "medium", "high", "critical"];

interface LessonMeta {
  category?: Category;
  severity?: Severity;
  tags?: string[];
}

const META_PREFIX = "meta:";

function parseLessonBody(body: string): { meta: LessonMeta; text: string } {
  const lines = body.split("\n");
  if (lines.length === 0 || !lines[0].startsWith(META_PREFIX)) {
    return { meta: {}, text: body };
  }
  try {
    const meta = JSON.parse(lines[0].slice(META_PREFIX.length).trim()) as LessonMeta;
    return { meta, text: lines.slice(1).join("\n").trimStart() };
  } catch (err) {
    // Malformed meta prefix — treat the row as legacy (uncategorised) and
    // render the verbatim body. The error is logged but not surfaced to the
    // user because a bad prefix on one row should not block the whole tab.
    if (typeof console !== "undefined") {
      console.warn("LessonsTab: ignoring malformed meta prefix:", err);
    }
    return { meta: {}, text: body };
  }
}

function encodeLessonBody(meta: LessonMeta, text: string): string {
  const hasMeta = meta.category || meta.severity || (meta.tags && meta.tags.length > 0);
  if (!hasMeta) return text;
  return `${META_PREFIX}${JSON.stringify(meta)}\n${text}`;
}

export function LessonsTab({ projectId }: LessonsTabProps) {
  const [items, setItems] = useState<ProjectLessonDTO[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [category, setCategory] = useState<Category>("decision");
  const [severity, setSeverity] = useState<Severity>("medium");
  const [tagsInput, setTagsInput] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [search, setSearch] = useState("");
  const [filterCategory, setFilterCategory] = useState<Category | "all">("all");
  const [filterSeverity, setFilterSeverity] = useState<Severity | "all">("all");
  const [expandedId, setExpandedId] = useState<string | null>(null);

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    listProjectLessons(projectId)
      .then((res) => {
        if (!cancelled) setItems(res.items);
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : String(e));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  async function handleSubmit(ev: React.FormEvent) {
    ev.preventDefault();
    if (!title.trim() || !body.trim() || submitting) return;
    setSubmitting(true);
    setError(null);
    const tags = tagsInput.split(",").map((t) => t.trim()).filter(Boolean);
    const encoded = encodeLessonBody({ category, severity, tags }, body.trim());
    try {
      const created = await createProjectLesson(projectId, {
        title: title.trim(),
        body: encoded,
      });
      setItems((prev) => [created, ...prev]);
      setTitle("");
      setBody("");
      setTagsInput("");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  }

  const decorated = useMemo(
    () =>
      items.map((l) => {
        const parsed = parseLessonBody(l.body);
        return { ...l, ...parsed };
      }),
    [items],
  );

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    return decorated.filter((l) => {
      if (filterCategory !== "all" && l.meta.category !== filterCategory) return false;
      if (filterSeverity !== "all" && l.meta.severity !== filterSeverity) return false;
      if (q) {
        const hay = `${l.title} ${l.text} ${(l.meta.tags ?? []).join(" ")}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [decorated, search, filterCategory, filterSeverity]);

  return (
    <div className="lessons-tab">
      <form className="lessons-tab__form" onSubmit={handleSubmit}>
        <div className="lessons-tab__form-row">
          <label className="lessons-tab__field">
            <span>Title</span>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              maxLength={200}
              required
            />
          </label>
        </div>
        <div className="lessons-tab__form-row lessons-tab__form-row--inline">
          <label className="lessons-tab__field">
            <span>Category</span>
            <select value={category} onChange={(e) => setCategory(e.target.value as Category)}>
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </label>
          <label className="lessons-tab__field">
            <span>Severity</span>
            <select value={severity} onChange={(e) => setSeverity(e.target.value as Severity)}>
              {SEVERITIES.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </label>
          <label className="lessons-tab__field lessons-tab__field--grow">
            <span>Tags (comma-separated)</span>
            <input
              type="text"
              value={tagsInput}
              onChange={(e) => setTagsInput(e.target.value)}
              placeholder="auth, retro, postmortem"
            />
          </label>
        </div>
        <label className="lessons-tab__field">
          <span>Body</span>
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            maxLength={20000}
            rows={3}
            required
          />
        </label>
        <button
          type="submit"
          disabled={submitting || !title.trim() || !body.trim()}
        >
          Add lesson
        </button>
      </form>

      <div className="lessons-tab__controls">
        <input
          type="search"
          placeholder="Search lessons…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          aria-label="Search lessons"
          className="lessons-tab__search"
        />
        <select
          value={filterCategory}
          onChange={(e) => setFilterCategory(e.target.value as Category | "all")}
          aria-label="Filter by category"
        >
          <option value="all">All categories</option>
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
        <select
          value={filterSeverity}
          onChange={(e) => setFilterSeverity(e.target.value as Severity | "all")}
          aria-label="Filter by severity"
        >
          <option value="all">All severities</option>
          {SEVERITIES.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </div>

      {loading && <div aria-busy="true">Loading lessons…</div>}
      {error && (
        <div role="alert" style={{ color: "var(--color-error, red)" }}>
          {error}
        </div>
      )}
      {!loading && visible.length === 0 && (
        <div className="lessons-tab__empty">No lessons match the current filter.</div>
      )}

      <ul className="lessons-tab__list">
        {visible.map((lesson) => {
          const isOpen = expandedId === lesson.id;
          return (
            <li
              key={lesson.id}
              data-testid="lesson-item"
              className={`lessons-tab__item${isOpen ? " lessons-tab__item--open" : ""}`}
              onClick={() => setExpandedId(isOpen ? null : lesson.id)}
              tabIndex={0}
              role="button"
              aria-expanded={isOpen}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  setExpandedId(isOpen ? null : lesson.id);
                }
              }}
            >
              <div className="lessons-tab__item-header">
                <div className="lessons-tab__item-title">{lesson.title}</div>
                <div className="lessons-tab__item-chips">
                  {lesson.meta.category && (
                    <span className={`lessons-chip lessons-chip--cat lessons-chip--cat-${lesson.meta.category}`}>
                      {lesson.meta.category}
                    </span>
                  )}
                  {lesson.meta.severity && (
                    <span className={`lessons-chip lessons-chip--sev lessons-chip--sev-${lesson.meta.severity}`}>
                      {lesson.meta.severity}
                    </span>
                  )}
                  {(lesson.meta.tags ?? []).map((t) => (
                    <span key={t} className="lessons-chip lessons-chip--tag">#{t}</span>
                  ))}
                </div>
              </div>
              <div className="lessons-tab__item-body">
                {isOpen ? lesson.text : (lesson.text.split("\n")[0] ?? "").slice(0, 160)}
                {!isOpen && lesson.text.length > 160 ? "…" : ""}
              </div>
              <div className="lessons-tab__item-meta">
                <span>{lesson.source}</span>
                <span>{lesson.created_at}</span>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export default LessonsTab;
