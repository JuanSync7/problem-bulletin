import React from "react";
import { EmptyState } from "../components/EmptyState";

interface UnauthorizedProps {
  statusCode?: 401 | 403;
}

export default function Unauthorized({ statusCode = 401 }: UnauthorizedProps) {
  const is403 = statusCode === 403;

  return (
    <EmptyState
      title={is403 ? "403 — Forbidden" : "401 — Unauthorized"}
      description={
        is403
          ? "You don't have permission to access this resource."
          : "You need to sign in to access this page."
      }
      icon={
        <svg
          width="64"
          height="64"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
          <path d="M7 11V7a5 5 0 0 1 10 0v4" />
        </svg>
      }
      cta={{ label: "Go to Home", href: "/" }}
    />
  );
}
