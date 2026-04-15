/**
 * Mock API layer for GitHub Pages demo mode.
 * Wraps fetch() — if the real API is unreachable, returns mock data.
 */

import {
  MOCK_PROBLEMS,
  MOCK_SOLUTIONS,
  MOCK_COMMENTS,
  MOCK_CATEGORIES,
  MOCK_DOMAINS,
  MOCK_LEADERBOARD,
  MOCK_USERS,
} from "./data";

// Capture the real fetch before any overrides
const _realFetch = window.fetch.bind(window);

let _demoMode: boolean | null = null;

async function isDemoMode(): Promise<boolean> {
  if (_demoMode !== null) return _demoMode;
  try {
    const res = await _realFetch("/api/health", { signal: AbortSignal.timeout(3000) });
    _demoMode = !res.ok;
  } catch {
    _demoMode = true;
  }
  return _demoMode;
}

function matchRoute(url: string): { route: string; params: Record<string, string> } | null {
  const path = url.replace(/\?.*$/, "");

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
    [/^\/api\/domains$/, "domains"],
    [/^\/api\/search$/, "search"],
    [/^\/api\/leaderboard\/solvers$/, "leaderboard_solvers"],
    [/^\/api\/leaderboard\/reporters$/, "leaderboard_reporters"],
    [/^\/api\/tags$/, "empty_array"],
    [/^\/api\/notifications$/, "empty_array"],
  ];

  for (const [regex, route] of patterns) {
    const match = path.match(regex);
    if (match) {
      return { route, params: { id: match[1] || "" } };
    }
  }
  return null;
}

function getMockResponse(route: string, params: Record<string, string>, url: string): any {
  switch (route) {
    case "problems_list": {
      return { items: MOCK_PROBLEMS, next_cursor: null };
    }
    case "problem_detail": {
      const p = MOCK_PROBLEMS.find((p) => p.id === params.id);
      return p || null;
    }
    case "problem_solutions": {
      return MOCK_SOLUTIONS[params.id] || [];
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
    case "search": {
      const q = new URL(url, window.location.origin).searchParams.get("q") || "";
      const results = MOCK_PROBLEMS
        .filter((p) => p.title.toLowerCase().includes(q.toLowerCase()) || p.description.toLowerCase().includes(q.toLowerCase()))
        .map((p) => ({
          problem_id: p.id,
          title: p.title,
          excerpt: p.description.slice(0, 150) + "...",
          rank: 1,
          match_source: "title",
          upstar_count: p.upstar_count,
          created_at: p.created_at,
          display_id: p.display_id,
        }));
      return { results };
    }
    case "leaderboard_solvers": {
      return MOCK_LEADERBOARD.top_solvers;
    }
    case "leaderboard_reporters": {
      return MOCK_LEADERBOARD.top_reporters;
    }
    case "empty_array": {
      return [];
    }
    case "empty_object": {
      return {};
    }
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

  // Demo mode — return mock data
  const matched = matchRoute(url);
  if (!matched) {
    // For mutations (POST/DELETE/PATCH) in demo mode, return success
    const method = init?.method?.toUpperCase() || "GET";
    if (method !== "GET") {
      return new Response(JSON.stringify({ ok: true, detail: "Demo mode — changes not persisted" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
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
