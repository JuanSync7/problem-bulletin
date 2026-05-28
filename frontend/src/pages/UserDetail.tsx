/**
 * WP60 — Stub detail page for users / agents.
 *
 * The `<handle>` in the URL may belong to either a user or an agent
 * account. We resolve it via the existing
 * `GET /api/v1/people/search?q=<handle>` endpoint and match on exact
 * handle (case-insensitive). The activity feed isn't filterable by actor
 * yet, so we surface identity + a CTA into the global activity page.
 */
import React, { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { parseApiError } from "../api/errors";

interface PersonRef {
  kind: "user" | "agent";
  id: string;
  display_name: string;
  handle: string | null;
  email: string | null;
}

export default function UserDetail() {
  const { handle = "" } = useParams<{ handle: string }>();
  const [state, setState] = useState<
    | { kind: "loading" }
    | { kind: "ok"; person: PersonRef }
    | { kind: "missing" }
    | { kind: "error"; message: string }
  >({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;

    async function resolve() {
      try {
        const res = await fetch(
          `/api/v1/people/search?q=${encodeURIComponent(handle)}&limit=20`,
          { credentials: "include" },
        );
        if (!res.ok) {
          // v2.14-WP04: surface backend envelope message instead of
          // `People lookup failed (NNN)`.
          const body = await res.json().catch(() => null);
          const parsed = parseApiError(res, body);
          if (!cancelled) {
            setState({ kind: "error", message: parsed.message });
          }
          return;
        }
        const body = (await res.json()) as { items: PersonRef[] };
        const target = handle.toLowerCase();
        const hit = body.items.find(
          (p) => (p.handle ?? "").toLowerCase() === target,
        );
        if (!cancelled) {
          setState(hit ? { kind: "ok", person: hit } : { kind: "missing" });
        }
      } catch (err) {
        if (!cancelled) {
          setState({
            kind: "error",
            message: err instanceof Error ? err.message : "Failed to load user",
          });
        }
      }
    }

    setState({ kind: "loading" });
    resolve();
    return () => {
      cancelled = true;
    };
  }, [handle]);

  if (state.kind === "loading") {
    return (
      <div className="entity-detail-stub">
        <p>Loading user...</p>
      </div>
    );
  }

  if (state.kind === "missing") {
    return (
      <div className="entity-detail-stub">
        <h1>User not found</h1>
        <p>No user or agent matches <code>@{handle}</code>.</p>
        <p>
          <Link to="/">Back to home</Link>
        </p>
      </div>
    );
  }

  if (state.kind === "error") {
    return (
      <div className="entity-detail-stub">
        <h1>User unavailable</h1>
        <p>{state.message}</p>
      </div>
    );
  }

  const { person } = state;
  return (
    <div className="entity-detail-stub">
      <h1>{person.display_name}</h1>
      <dl className="entity-detail-stub__meta">
        <dt>Handle</dt>
        <dd>@{person.handle ?? handle}</dd>
        <dt>Kind</dt>
        <dd>{person.kind === "agent" ? "Agent" : "User"}</dd>
        {person.email && (
          <>
            <dt>Email</dt>
            <dd>{person.email}</dd>
          </>
        )}
      </dl>
      <p>
        <Link to="/activity">View recent activity</Link>
      </p>
    </div>
  );
}
