import React, { useState, useEffect, useCallback, useRef } from "react";
import "./Leaderboard.css";

type Track = "solvers" | "reporters";
type Period = "this_week" | "this_month" | "all_time";

interface LeaderboardEntry {
  rank: number;
  userId: string;
  displayName: string;
  score: number;
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
        throw new Error(`Failed to load leaderboard (${res.status})`);
      }
      const data = await res.json();
      if (!controller.signal.aborted) {
        const raw: any[] = data.entries ?? data ?? [];
        setEntries(raw.map((e: any, i: number) => ({
          rank: e.rank ?? i + 1,
          userId: e.userId ?? e.user_id ?? "",
          displayName: e.displayName ?? e.display_name ?? "Unknown",
          score: e.score ?? e.accepted_count ?? e.upstar_count ?? e.problem_count ?? 0,
        })));
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
