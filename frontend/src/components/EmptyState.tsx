import React from "react";
import { Link } from "react-router-dom";

interface EmptyStateCta {
  label: string;
  href: string;
}

interface EmptyStateProps {
  title: string;
  description: string;
  icon?: React.ReactNode;
  cta?: EmptyStateCta;
}

export function EmptyState({ title, description, icon, cta }: EmptyStateProps) {
  return (
    <div className="empty-state">
      {icon && <div className="empty-state__icon">{icon}</div>}
      <h2 className="empty-state__title">{title}</h2>
      <p className="empty-state__description">{description}</p>
      {cta && (
        <Link to={cta.href} className="empty-state__cta">
          {cta.label}
        </Link>
      )}
    </div>
  );
}
