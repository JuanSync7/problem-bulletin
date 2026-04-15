import React, { useState } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { AuthCard } from "../components/AuthCard";
import "./Landing.css";

// Check if we're in demo mode by looking at the hostname
function useIsDemoMode(): boolean {
  return window.location.hostname.includes("github.io") ||
    window.location.hostname.includes("pages.dev") ||
    window.location.protocol === "file:";
}

interface BountyNote {
  title: string;
  tag: string;
  stars: number;
  color: string; // pin color
}

const BOUNTIES: BountyNote[] = [
  { title: "Timing closure failure on ALU critical path", tag: "P0", stars: 12, color: "#EF4444" },
  { title: "DRC violations in metal fill around analog block", tag: "DRC", stars: 8, color: "#3B82F6" },
  { title: "Scan chain reorder causing coverage drop", tag: "DFT", stars: 5, color: "#22C55E" },
  { title: "UVM scoreboard mismatch on AXI burst transactions", tag: "UVM", stars: 15, color: "#F59E0B" },
  { title: "Power grid IR drop exceeding 5% target", tag: "Power", stars: 9, color: "#EF4444" },
  { title: "Clock tree insertion delay too high", tag: "CTS", stars: 6, color: "#8B5CF6" },
  { title: "Floorplan congestion near IO ring", tag: "PD", stars: 4, color: "#3B82F6" },
  { title: "Hold violations after CTS", tag: "Timing", stars: 7, color: "#22C55E" },
  { title: "ESD clamp sizing for 2kV HBM", tag: "Analog", stars: 3, color: "#F59E0B" },
  { title: "SRAM bit-cell stability at 0.7V", tag: "Memory", stars: 11, color: "#8B5CF6" },
];

// Pre-computed scattered positions so they don't shift on re-render
const POSITIONS = [
  { top: "3%", left: "2%", rotate: -3 },
  { top: "5%", left: "30%", rotate: 2 },
  { top: "2%", left: "62%", rotate: -1.5 },
  { top: "8%", left: "78%", rotate: 3 },
  { top: "38%", left: "0%", rotate: -2 },
  { top: "55%", left: "2%", rotate: 1.5 },
  { top: "40%", left: "72%", rotate: -2.5 },
  { top: "58%", left: "75%", rotate: 2 },
  { top: "75%", left: "5%", rotate: 3 },
  { top: "78%", left: "68%", rotate: -1 },
];

export default function Landing() {
  const auth = useAuth();
  const isDemo = useIsDemoMode();
  const [enteringDemo, setEnteringDemo] = useState(false);

  // Only auto-redirect if real backend and authenticated (not demo)
  if (!auth.isLoading && auth.isAuthenticated && isDemo === false) {
    return <Navigate to="/problems" replace />;
  }

  if (enteringDemo) {
    return <Navigate to="/problems" replace />;
  }

  return (
    <div className="landing">
      <div className="landing__board">
        {/* Scattered bounty notes */}
        {BOUNTIES.map((bounty, i) => {
          const pos = POSITIONS[i];
          return (
            <div
              key={bounty.title}
              className="landing__bounty"
              style={{
                top: pos.top,
                left: pos.left,
                transform: `rotate(${pos.rotate}deg)`,
              }}
            >
              <div
                className="landing__bounty-pin"
                style={{ backgroundColor: bounty.color }}
              />
              <span className="landing__bounty-tag">{bounty.tag}</span>
              <span className="landing__bounty-title">{bounty.title}</span>
              <span className="landing__bounty-stars">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" stroke="none">
                  <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
                </svg>
                {bounty.stars}
              </span>
            </div>
          );
        })}

        {/* Welcome card — pinned center of the board */}
        <div className="landing__welcome-card">
          <div className="landing__welcome-pin" />
          <AuthCard
            isLoading={auth.isLoading}
            error={auth.error}
            onMicrosoftLogin={auth.login}
            onMagicLink={auth.loginWithMagicLink}
            onClearError={auth.clearError}
          />
          <button
            className="landing__demo-btn"
            onClick={() => setEnteringDemo(true)}
          >
            Enter Demo
          </button>
          <p className="landing__tagline">
            Crowd-source solutions to engineering problems
          </p>
        </div>
      </div>
    </div>
  );
}
