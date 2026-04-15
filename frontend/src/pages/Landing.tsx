import React, { useState, useMemo } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { AuthCard } from "../components/AuthCard";
import "./Landing.css";

const SAMPLE_PROBLEMS = [
  "Build log parsing too slow",
  "Test coverage gaps in auth module",
  "Deployment rollbacks take 30+ minutes",
  "Flaky integration tests in CI",
  "On-call alert fatigue",
  "Onboarding docs are outdated",
  "Cross-team dependency bottlenecks",
  "Incident postmortems rarely actioned",
];

export default function Landing() {
  const auth = useAuth();

  // Generate random rotation angles once on mount
  const [rotations] = useState(() =>
    SAMPLE_PROBLEMS.map(() => Math.random() * 8 - 4),
  );

  // Redirect if already authenticated
  if (!auth.isLoading && auth.isAuthenticated) {
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
        <p className="landing__tagline">
          Crowd-source solutions to workplace problems
        </p>
      </div>
    </div>
  );
}
