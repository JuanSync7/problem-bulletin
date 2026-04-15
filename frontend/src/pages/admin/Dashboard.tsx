import React, { useState, useEffect } from "react";
import { AdminRouteGuard } from "../../components/AdminRouteGuard";
import "./Admin.css";

interface Stats {
  totalProblems: number;
  totalSolutions: number;
  totalUsers: number;
  flaggedItems: number;
}

function DashboardContent() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchStats() {
      try {
        const res = await fetch("/api/admin/stats", { credentials: "include" });
        if (!res.ok) throw new Error("Failed to fetch stats");
        const data: Stats = await res.json();
        setStats(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load stats");
      } finally {
        setLoading(false);
      }
    }
    fetchStats();
  }, []);

  if (loading) {
    return (
      <div className="admin-page">
        <h1 className="admin-page__title">Dashboard</h1>
        <div className="admin-loading">
          <div className="admin-loading__spinner" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="admin-page">
        <h1 className="admin-page__title">Dashboard</h1>
        <div className="admin-error">{error}</div>
      </div>
    );
  }

  const cards = [
    { label: "Total Problems", value: stats?.totalProblems ?? 0 },
    { label: "Total Solutions", value: stats?.totalSolutions ?? 0 },
    { label: "Total Users", value: stats?.totalUsers ?? 0 },
    { label: "Flagged Items", value: stats?.flaggedItems ?? 0 },
  ];

  return (
    <div className="admin-page">
      <h1 className="admin-page__title">Dashboard</h1>
      <div className="admin-stats-grid">
        {cards.map((card) => (
          <div key={card.label} className="admin-stat-card">
            <span className="admin-stat-card__value">{card.value}</span>
            <span className="admin-stat-card__label">{card.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function Dashboard() {
  return (
    <AdminRouteGuard>
      <DashboardContent />
    </AdminRouteGuard>
  );
}
