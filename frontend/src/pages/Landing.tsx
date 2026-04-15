import React, { useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { AuthCard } from "../components/AuthCard";
import "./Landing.css";

const SAMPLE_PROBLEMS = [
  "Timing closure failure on critical path",
  "DRC violations in metal fill",
  "Scan chain reorder causing coverage drop",
  "UVM scoreboard mismatch on AXI burst",
  "Power grid IR drop exceeding target",
  "Clock tree insertion delay too high",
  "Floorplan congestion near IO ring",
  "Hold violations after CTS",
];

export default function Landing() {
  const auth = useAuth();
  const navigate = useNavigate();
  const [enteringDemo, setEnteringDemo] = useState(false);

  // Generate random rotation angles once on mount
  const [rotations] = useState(() =>
    SAMPLE_PROBLEMS.map(() => Math.random() * 8 - 4),
  );

  // Redirect if authenticated (real backend)
  if (!auth.isLoading && auth.isAuthenticated && !enteringDemo) {
    return <Navigate to="/problems" replace />;
  }

  if (enteringDemo) {
    return <Navigate to="/problems" replace />;
  }

  return (
    <div className="landing">
      {/* Decorative background cards */}
      <div className="landing__cards">
        {SAMPLE_PROBLEMS.map((title, i) => (
          <div
            key={title}
            className="landing__deco-card"
            style={{ transform: `rotate(${rotations[i]}deg)` }}
          >
            <span className="landing__deco-card-title">{title}</span>
          </div>
        ))}
      </div>

      {/* Auth overlay */}
      <div className="landing__auth-overlay">
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
  );
}
