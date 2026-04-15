import React from "react";

export type ProblemStatus = "open" | "claimed" | "solved" | "accepted" | "duplicate";

const STATUS_CONFIG: Record<ProblemStatus, { label: string; cssClass: string }> = {
  open: { label: "Open", cssClass: "status-badge--open" },
  claimed: { label: "Claimed", cssClass: "status-badge--claimed" },
  solved: { label: "Solved", cssClass: "status-badge--solved" },
  accepted: { label: "Accepted", cssClass: "status-badge--accepted" },
  duplicate: { label: "Duplicate", cssClass: "status-badge--duplicate" },
};

interface StatusBadgeProps {
  status: ProblemStatus;
  className?: string;
}

export function StatusBadge({ status, className }: StatusBadgeProps) {
  const config = STATUS_CONFIG[status] ?? STATUS_CONFIG.open;
  return (
    <span className={`status-badge ${config.cssClass}${className ? ` ${className}` : ""}`}>
      {config.label}
    </span>
  );
}
