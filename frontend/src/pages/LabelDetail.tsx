/**
 * WP60 — Stub detail page for labels (tags).
 *
 * Looks up the tag via the existing public `GET /api/tags?q=<name>`
 * endpoint and picks the exact case-insensitive match. Recent activity
 * filtered by tag isn't exposed by the API yet — we surface the usage
 * count and a CTA into the tag-scoped search.
 */
import React, { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { parseApiError } from "../api/errors";

interface Tag {
  id: string;
  name: string;
  created_at: string;
  usage_count: number;
}

export default function LabelDetail() {
  const { name = "" } = useParams<{ name: string }>();
  const [state, setState] = useState<
    | { kind: "loading" }
    | { kind: "ok"; tag: Tag }
    | { kind: "missing" }
    | { kind: "error"; message: string }
  >({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;

    async function resolve() {
      try {
        const res = await fetch(`/api/tags?q=${encodeURIComponent(name)}`, {
          credentials: "include",
        });
        if (!res.ok) {
          // v2.14-WP04: surface backend envelope message instead of
          // `Tag lookup failed (NNN)`.
          const body = await res.json().catch(() => null);
          const parsed = parseApiError(res, body);
          if (!cancelled) {
            setState({ kind: "error", message: parsed.message });
          }
          return;
        }
        const body = (await res.json()) as Tag[];
        const target = name.toLowerCase();
        const hit = body.find((t) => t.name.toLowerCase() === target);
        if (!cancelled) {
          setState(hit ? { kind: "ok", tag: hit } : { kind: "missing" });
        }
      } catch (err) {
        if (!cancelled) {
          setState({
            kind: "error",
            message: err instanceof Error ? err.message : "Failed to load label",
          });
        }
      }
    }

    setState({ kind: "loading" });
    resolve();
    return () => {
      cancelled = true;
    };
  }, [name]);

  if (state.kind === "loading") {
    return (
      <div className="entity-detail-stub">
        <p>Loading label...</p>
      </div>
    );
  }

  if (state.kind === "missing") {
    return (
      <div className="entity-detail-stub">
        <h1>Label not found</h1>
        <p>No label matches <code>{name}</code>.</p>
        <p>
          <Link to="/">Back to home</Link>
        </p>
      </div>
    );
  }

  if (state.kind === "error") {
    return (
      <div className="entity-detail-stub">
        <h1>Label unavailable</h1>
        <p>{state.message}</p>
      </div>
    );
  }

  const { tag } = state;
  return (
    <div className="entity-detail-stub">
      <h1>{tag.name}</h1>
      <dl className="entity-detail-stub__meta">
        <dt>Usage count</dt>
        <dd>{tag.usage_count}</dd>
        <dt>Created</dt>
        <dd>{new Date(tag.created_at).toLocaleDateString()}</dd>
      </dl>
      <p>
        <Link to={`/search?q=${encodeURIComponent(tag.name)}&entity=problems`}>
          See problems tagged with this label
        </Link>
      </p>
    </div>
  );
}
