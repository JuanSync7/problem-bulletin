import React, { useState, useEffect, useCallback, useRef } from "react";
import { parseApiError } from "../api/errors";
import "./Leaderboard.css";

export type Track = "solvers" | "reporters";
type Period = "this_week" | "this_month" | "all_time";

export interface LeaderboardEntry {
  rank: number;
  userId: string;
  displayName: string;
  score: number;
}

// ---------------------------------------------------------------------------
// v2.18-WP03 L3: Discriminated raw-payload union for /api/leaderboard.
//
// The backend (`app/services/leaderboard.py`) emits two row shapes; the
// natural discriminator is the *request* track, not a per-row tag, so the
// union is narrowed against `Track` at normalisation time rather than via
// runtime sniffing. Both variants share user_id / display_name / rank and
// carry one track-specific score column (accepted_count vs upstar_count).
// camelCase aliases remain accepted for legacy in-flight payloads.
// ---------------------------------------------------------------------------
interface LeaderboardEntryBase {
  user_id?: string;
  userId?: string;
  display_name?: string;
  displayName?: string;
  rank?: number;
}

export interface LeaderboardSolverRaw extends LeaderboardEntryBase {
  accepted_count?: number;
}

export interface LeaderboardReporterRaw extends LeaderboardEntryBase {
  upstar_count?: number;
}

export type LeaderboardRawEntry = LeaderboardSolverRaw | LeaderboardReporterRaw;

export function normalizeLeaderboardEntry(
  raw: LeaderboardRawEntry,
  track: Track,
  index: number,
): LeaderboardEntry {
  const userId = raw.userId ?? raw.user_id ?? "";
  const displayName = raw.displayName ?? raw.display_name ?? "Unknown";
  const rank = raw.rank ?? index + 1;

  let score: number;
  switch (track) {
    case "solvers":
      score = (raw as LeaderboardSolverRaw).accepted_count ?? 0;
      break;
    case "reporters":
      score = (raw as LeaderboardReporterRaw).upstar_count ?? 0;
      break;
    default: {
      // Exhaustiveness — if a new Track is added, TS errors here.
      const _exhaustive: never = track;
      return _exhaustive;
    }
  }

  return { rank, userId, displayName, score };
}

const TRACK_LABELS: Record<Track, string> = {
  solvers: "Top Solvers",
  reporters: "Top Reporters",
};

const PERIOD_LABELS: Record<Period, string> = {
  this_week: "This Week",
  this_month: "This Month",
  all_time: "All Time",
};

function rankClass(rank: number): string {
  if (rank === 1) return "leaderboard__rank leaderboard__rank--gold";
  if (rank === 2) return "leaderboard__rank leaderboard__rank--silver";
  if (rank === 3) return "leaderboard__rank leaderboard__rank--bronze";
  return "leaderboard__rank";
}

export default function Leaderboard() {
  const [track, setTrack] = useState<Track>("solvers");
  const [period, setPeriod] = useState<Period>("all_time");
  const [entries, setEntries] = useState<LeaderboardEntry[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const fetchLeaderboard = useCallback(async (t: Track, p: Period) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setIsLoading(true);
    setError(null);

    try {
      const res = await fetch(
        `/api/leaderboard?track=${t}&period=${p}`,
        { signal: controller.signal, credentials: "include" }
      );
      if (!res.ok) {
        // v2.14-WP04: route error message through parseApiError so the
        // backend's structured envelope (code/message/correlation_id) is
        // preserved when surfaced to the user.
        const body = await res.json().catch(() => null);
        const parsed = parseApiError(res, body);
        throw new Error(parsed.message);
      }
      const data = await res.json();
      if (!controller.signal.aborted) {
        const raw: LeaderboardRawEntry[] = Array.isArray(data.entries)
          ? (data.entries as LeaderboardRawEntry[])
          : Array.isArray(data)
            ? (data as LeaderboardRawEntry[])
            : [];
        setEntries(raw.map((e, i) => normalizeLeaderboardEntry(e, t, i)));
        setIsLoading(false);
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      if (!controller.signal.aborted) {
        setError(err instanceof Error ? err.message : "Failed to load leaderboard");
        setIsLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    fetchLeaderboard(track, period);
  }, [track, period, fetchLeaderboard]);

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  return (
    <div className="leaderboard">
      <h1 className="leaderboard__title">Leaderboard</h1>

      <div className="leaderboard__tabs">
        {(Object.keys(TRACK_LABELS) as Track[]).map((t) => (
          <button
            key={t}
            className={`leaderboard__tab${track === t ? " leaderboard__tab--active" : ""}`}
            onClick={() => setTrack(t)}
            type="button"
          >
            {TRACK_LABELS[t]}
          </button>
        ))}
      </div>

      <div className="leaderboard__filters">
        {(Object.keys(PERIOD_LABELS) as Period[]).map((p) => (
          <button
            key={p}
            className={`leaderboard__filter-btn${period === p ? " leaderboard__filter-btn--active" : ""}`}
            onClick={() => setPeriod(p)}
            type="button"
          >
            {PERIOD_LABELS[p]}
          </button>
        ))}
      </div>

      {isLoading && (
        <div className="leaderboard__loading">
          <div className="leaderboard__spinner" />
          Loading leaderboard...
        </div>
      )}

      {error && <div className="leaderboard__error">{error}</div>}

      {!isLoading && !error && entries.length === 0 && (
        <div className="leaderboard__empty">
          No entries yet for this period.
        </div>
      )}

      {!isLoading && !error && entries.length > 0 && (
        <div className="leaderboard__table-wrapper">
          <table className="leaderboard__table">
            <thead>
              <tr>
                <th>Rank</th>
                <th>User</th>
                <th>Score</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => (
                <tr key={entry.userId}>
                  <td className={rankClass(entry.rank)}>
                    {entry.rank <= 3 ? `${entry.rank}` : entry.rank}
                  </td>
                  <td className="leaderboard__user-name">{entry.displayName}</td>
                  <td className="leaderboard__score">{entry.score}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
