/**
 * Mock API layer for GitHub Pages demo mode.
 * Wraps fetch() — if the real API is unreachable, returns mock data.
 * Tracks upstar/upvote state in memory for interactive demo.
 */

import {
  MOCK_PROBLEMS,
  MOCK_SOLUTIONS,
  MOCK_COMMENTS,
  MOCK_CATEGORIES,
  MOCK_DOMAINS,
  MOCK_USERS,
} from "./data";

// Capture the real fetch before any overrides
const _realFetch = window.fetch.bind(window);

let _demoMode: boolean | null = null;

// In-memory state for interactive demo
const _upstarred = new Set<string>(["p2"]); // p2 starts upstarred per mock data
const _upvoted = new Set<string>();
const _upstarCounts: Record<string, number> = {};
const _upvoteCounts: Record<string, number> = {};

// Initialize counts from mock data
for (const p of MOCK_PROBLEMS) {
  _upstarCounts[p.id] = p.upstar_count;
}
for (const [, sols] of Object.entries(MOCK_SOLUTIONS)) {
  for (const s of sols) {
    _upvoteCounts[s.id] = s.upvote_count;
    if (s.is_upvoted) _upvoted.add(s.id);
  }
}

// Leaderboard data in the shape the frontend expects
const LEADERBOARD_SOLVERS = [
  { rank: 1, userId: "u2", displayName: "Bob Martinez", score: 8, problemCount: 4 },
  { rank: 2, userId: "u1", displayName: "Alice Chen", score: 6, problemCount: 12 },
  { rank: 3, userId: "u4", displayName: "Dave Patel", score: 5, problemCount: 9 },
  { rank: 4, userId: "u3", displayName: "Carol Kim", score: 3, problemCount: 7 },
];

const LEADERBOARD_REPORTERS = [
  { rank: 1, userId: "u1", displayName: "Alice Chen", score: 12, problemCount: 12 },
  { rank: 2, userId: "u4", displayName: "Dave Patel", score: 9, problemCount: 9 },
  { rank: 3, userId: "u3", displayName: "Carol Kim", score: 7, problemCount: 7 },
  { rank: 4, userId: "u2", displayName: "Bob Martinez", score: 4, problemCount: 4 },
];

async function isDemoMode(): Promise<boolean> {
  if (_demoMode !== null) return _demoMode;
  try {
    const res = await _realFetch("/api/health", { signal: AbortSignal.timeout(3000) });
    const contentType = res.headers.get("content-type") || "";
    // Must be JSON and 200 — GitHub Pages returns 200 HTML for all paths
    _demoMode = !res.ok || !contentType.includes("application/json");
  } catch {
    _demoMode = true;
  }
  return _demoMode;
}

interface RouteMatch {
  route: string;
  params: Record<string, string>;
}

function matchRoute(url: string, method: string): RouteMatch | null {
  const path = url.replace(/\?.*$/, "");

  // POST/mutation routes first
  if (method === "POST") {
    let m = path.match(/^\/api\/problems\/([^/]+)\/upstar$/);
    if (m) return { route: "upstar_toggle", params: { id: m[1] } };

    m = path.match(/^\/api\/solutions\/([^/]+)\/upvote$/);
    if (m) return { route: "upvote_toggle", params: { id: m[1] } };

    m = path.match(/^\/api\/solutions\/([^/]+)\/status$/);
    if (m) return { route: "solution_status", params: { id: m[1] } };
  }

  // GET routes
  const patterns: [RegExp, string][] = [
    [/^\/api\/auth\/me$/, "auth_me"],
    [/^\/api\/problems\/([^/]+)\/solutions$/, "problem_solutions"],
    [/^\/api\/problems\/([^/]+)\/comments$/, "problem_comments"],
    [/^\/api\/problems\/([^/]+)\/attachments$/, "empty_array"],
    [/^\/api\/problems\/([^/]+)\/edit-suggestions$/, "empty_array"],
    [/^\/api\/problems\/([^/]+)\/watches$/, "empty_object"],
    [/^\/api\/problems\/([^/]+)$/, "problem_detail"],
    [/^\/api\/problems$/, "problems_list"],
    [/^\/api\/categories$/, "categories"],
    [/^\/api\/admin\/categories$/, "categories"],
    [/^\/api\/domains$/, "domains"],
    [/^\/api\/leaderboard$/, "leaderboard"],
    [/^\/api\/search$/, "search"],
    [/^\/api\/tags$/, "empty_array"],
    [/^\/api\/notifications$/, "empty_array"],
    [/^\/api\/health$/, "health"],
  ];

  for (const [regex, route] of patterns) {
    const m = path.match(regex);
    if (m) return { route, params: { id: m[1] || "" } };
  }
  return null;
}

function handleMutation(route: string, params: Record<string, string>, body: any): any {
  switch (route) {
    case "upstar_toggle": {
      const id = params.id;
      const wasActive = _upstarred.has(id);
      if (wasActive) {
        _upstarred.delete(id);
        _upstarCounts[id] = (_upstarCounts[id] ?? 1) - 1;
      } else {
        _upstarred.add(id);
        _upstarCounts[id] = (_upstarCounts[id] ?? 0) + 1;
      }
      return { active: !wasActive, count: _upstarCounts[id] };
    }
    case "upvote_toggle": {
      const id = params.id;
      const wasActive = _upvoted.has(id);
      if (wasActive) {
        _upvoted.delete(id);
        _upvoteCounts[id] = (_upvoteCounts[id] ?? 1) - 1;
      } else {
        _upvoted.add(id);
        _upvoteCounts[id] = (_upvoteCounts[id] ?? 0) + 1;
      }
      return { active: !wasActive };
    }
    case "solution_status": {
      return { ok: true, status: body?.status ?? "pending" };
    }
    default:
      return { ok: true, detail: "Demo mode — changes not persisted" };
  }
}

function getMockResponse(route: string, params: Record<string, string>, url: string): any {
  switch (route) {
    case "problems_list": {
      // Return problems with live upstar state
      const items = MOCK_PROBLEMS.map((p) => ({
        ...p,
        upstar_count: _upstarCounts[p.id] ?? p.upstar_count,
        is_upstarred: _upstarred.has(p.id),
      }));
      return { items, next_cursor: null };
    }
    case "problem_detail": {
      const p = MOCK_PROBLEMS.find((p) => p.id === params.id);
      if (!p) return null;
      return {
        ...p,
        upstar_count: _upstarCounts[p.id] ?? p.upstar_count,
        is_upstarred: _upstarred.has(p.id),
      };
    }
    case "problem_solutions": {
      const sols = MOCK_SOLUTIONS[params.id] || [];
      return sols.map((s: any) => ({
        ...s,
        upvote_count: _upvoteCounts[s.id] ?? s.upvote_count,
        is_upvoted: _upvoted.has(s.id),
      }));
    }
    case "problem_comments": {
      return MOCK_COMMENTS[params.id] || [];
    }
    case "categories": {
      return MOCK_CATEGORIES;
    }
    case "domains": {
      return MOCK_DOMAINS;
    }
    case "leaderboard": {
      const searchParams = new URL(url, window.location.origin).searchParams;
      const track = searchParams.get("track") || "solvers";
      return track === "reporters" ? LEADERBOARD_REPORTERS : LEADERBOARD_SOLVERS;
    }
    case "search": {
      const q = new URL(url, window.location.origin).searchParams.get("q") || "";
      const results = MOCK_PROBLEMS
        .filter(
          (p) =>
            p.title.toLowerCase().includes(q.toLowerCase()) ||
            p.description.toLowerCase().includes(q.toLowerCase()) ||
            (p.display_id && p.display_id.toLowerCase().includes(q.toLowerCase()))
        )
        .map((p) => ({
          problem_id: p.id,
          title: p.title,
          excerpt: p.description.slice(0, 150) + "...",
          rank: 1,
          match_source: "title",
          upstar_count: _upstarCounts[p.id] ?? p.upstar_count,
          created_at: p.created_at,
          display_id: p.display_id,
        }));
      return { results };
    }
    case "empty_array":
      return [];
    case "empty_object":
      return {};
    case "health":
      return { status: "ok" };
    case "auth_me": {
      return {
        id: MOCK_USERS[0].id,
        email: MOCK_USERS[0].email,
        displayName: MOCK_USERS[0].display_name,
        display_name: MOCK_USERS[0].display_name,
        role: MOCK_USERS[0].role,
      };
    }
    default:
      return null;
  }
}

/**
 * Drop-in replacement for fetch() that returns mock data in demo mode.
 */
export async function demoFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;

  // Only intercept API calls
  if (!url.startsWith("/api/")) {
    return _realFetch(input, init);
  }

  // Try real API first
  if (!(await isDemoMode())) {
    return _realFetch(input, init);
  }

  const method = init?.method?.toUpperCase() || "GET";

  // Match route (method-aware)
  const matched = matchRoute(url, method);

  // Handle mutations with specific routes
  if (method !== "GET" && matched) {
    let body: any = null;
    if (init?.body) {
      try {
        body = JSON.parse(init.body as string);
      } catch {
        /* ignore */
      }
    }
    const data = handleMutation(matched.route, matched.params, body);
    return new Response(JSON.stringify(data), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }

  // Handle unmatched mutations
  if (method !== "GET") {
    return new Response(JSON.stringify({ ok: true, detail: "Demo mode" }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }

  // Handle GET
  if (!matched) {
    return new Response(JSON.stringify([]), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }

  const data = getMockResponse(matched.route, matched.params, url);
  if (data === null) {
    return new Response(JSON.stringify({ detail: "Not found" }), { status: 404 });
  }

  return new Response(JSON.stringify(data), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}
