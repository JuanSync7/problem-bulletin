/**
 * v2.18-WP03 L3: LeaderboardRawEntry discriminated union + normaliser tests.
 *
 * Backend (`app/services/leaderboard.py`) returns two shapes:
 *   solvers   → { user_id, display_name, rank, accepted_count }
 *   reporters → { user_id, display_name, rank, upstar_count }
 *
 * The discriminator is the *request* track (no per-row tag), so the
 * normaliser is keyed off the active Track at fetch time.
 */
import { describe, expect, it } from "vitest";
import {
  normalizeLeaderboardEntry,
  type LeaderboardRawEntry,
  type LeaderboardSolverRaw,
  type LeaderboardReporterRaw,
} from "../Leaderboard";

describe("normalizeLeaderboardEntry — solvers track", () => {
  it("maps snake_case solver payload (accepted_count → score)", () => {
    const raw: LeaderboardSolverRaw = {
      user_id: "u-1",
      display_name: "Ada",
      rank: 1,
      accepted_count: 17,
    };
    expect(normalizeLeaderboardEntry(raw, "solvers", 0)).toEqual({
      rank: 1,
      userId: "u-1",
      displayName: "Ada",
      score: 17,
    });
  });

  it("falls back to camelCase fields when present", () => {
    const raw: LeaderboardSolverRaw = {
      userId: "u-2",
      displayName: "Babbage",
      rank: 2,
      accepted_count: 5,
    };
    expect(normalizeLeaderboardEntry(raw, "solvers", 0)).toEqual({
      rank: 2,
      userId: "u-2",
      displayName: "Babbage",
      score: 5,
    });
  });

  it("uses index+1 when rank missing, defaults score=0 + Unknown name", () => {
    const raw: LeaderboardSolverRaw = {
      user_id: "u-3",
    };
    expect(normalizeLeaderboardEntry(raw, "solvers", 4)).toEqual({
      rank: 5,
      userId: "u-3",
      displayName: "Unknown",
      score: 0,
    });
  });
});

describe("normalizeLeaderboardEntry — reporters track", () => {
  it("maps snake_case reporter payload (upstar_count → score)", () => {
    const raw: LeaderboardReporterRaw = {
      user_id: "u-9",
      display_name: "Lovelace",
      rank: 1,
      upstar_count: 42,
    };
    expect(normalizeLeaderboardEntry(raw, "reporters", 0)).toEqual({
      rank: 1,
      userId: "u-9",
      displayName: "Lovelace",
      score: 42,
    });
  });

  it("does NOT read accepted_count when track is reporters", () => {
    // If a stray accepted_count leaks through, it must be ignored —
    // only upstar_count counts for the reporters track.
    const raw = {
      user_id: "u-10",
      display_name: "Hopper",
      rank: 3,
      upstar_count: 7,
      accepted_count: 999,
    } as LeaderboardReporterRaw;
    expect(normalizeLeaderboardEntry(raw, "reporters", 0).score).toBe(7);
  });

  it("defaults score to 0 when upstar_count missing", () => {
    const raw: LeaderboardReporterRaw = {
      user_id: "u-11",
      display_name: "Turing",
      rank: 4,
    };
    expect(normalizeLeaderboardEntry(raw, "reporters", 3).score).toBe(0);
  });
});

describe("LeaderboardRawEntry union type wiring", () => {
  it("accepts both variants under the union", () => {
    const xs: LeaderboardRawEntry[] = [
      { user_id: "a", display_name: "A", rank: 1, accepted_count: 1 },
      { user_id: "b", display_name: "B", rank: 1, upstar_count: 2 },
    ];
    expect(xs).toHaveLength(2);
  });
});
