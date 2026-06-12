/**
 * Lightweight async-fetch hooks for Ticketing v2 project-scoped resources.
 *
 * These are deliberately tiny (no React Query — the rest of the codebase does
 * raw fetch + useState for its data hooks; matching style). WP5 should reuse
 * these rather than rolling its own listing logic for the Kanban v2 project
 * selector, sprint pill, and component filter.
 */

import { useCallback, useEffect, useState } from "react";
import { listProjects, listComponents, listMembers } from "../api/projects";
import type { ProjectDTO, ComponentDTO, ProjectMemberDTO } from "../api/projects";
import { listSprints } from "../api/sprints";
import type { SprintDTO, SprintState } from "../api/sprints";

interface AsyncState<T> {
  data: T;
  loading: boolean;
  error: Error | null;
  refresh: () => void;
}

export function useProjects(includeArchived = false): AsyncState<ProjectDTO[]> {
  const [data, setData] = useState<ProjectDTO[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    listProjects({ includeArchived })
      .then((res) => {
        if (!cancelled) setData(res.items ?? []);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e : new Error(String(e)));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [includeArchived, tick]);

  const refresh = useCallback(() => setTick((t) => t + 1), []);
  return { data, loading, error, refresh };
}

export function useSprintsByProject(
  projectId: string | null,
  states?: SprintState[],
): AsyncState<SprintDTO[]> {
  const [data, setData] = useState<SprintDTO[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [tick, setTick] = useState(0);
  const stateKey = (states ?? []).join(",");

  useEffect(() => {
    if (!projectId) {
      setData([]);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    listSprints(projectId, states)
      .then((res) => {
        if (!cancelled) setData(res.items ?? []);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e : new Error(String(e)));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // states is array — depend on a stable key
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, stateKey, tick]);

  const refresh = useCallback(() => setTick((t) => t + 1), []);
  return { data, loading, error, refresh };
}

export function useComponentsByProject(
  projectId: string | null,
): AsyncState<ComponentDTO[]> {
  const [data, setData] = useState<ComponentDTO[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!projectId) {
      setData([]);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    listComponents(projectId)
      .then((res) => {
        if (!cancelled) setData(res.items ?? []);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e : new Error(String(e)));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, tick]);

  const refresh = useCallback(() => setTick((t) => t + 1), []);
  return { data, loading, error, refresh };
}

export function useMembersByProject(
  projectId: string | null,
): AsyncState<ProjectMemberDTO[]> {
  const [data, setData] = useState<ProjectMemberDTO[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!projectId) {
      setData([]);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    listMembers(projectId)
      .then((res) => {
        if (!cancelled) setData(res.items ?? []);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e : new Error(String(e)));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, tick]);

  const refresh = useCallback(() => setTick((t) => t + 1), []);
  return { data, loading, error, refresh };
}
