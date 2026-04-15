import React from "react";
import { NavLink } from "react-router-dom";
import { useTheme } from "../theme";
import { useAnonymousMode } from "../hooks/useAnonymousMode";

const APP_NAME = import.meta.env.VITE_APP_NAME || "Aion Bulletin";

interface SidebarProps {
  isOpen: boolean;
  onClose: () => void;
  isAdmin?: boolean;
}

interface NavItem {
  label: string;
  to: string;
}

const mainNavItems: NavItem[] = [
  { label: "Home", to: "/" },
  { label: "Problems", to: "/problems" },
  { label: "Submit", to: "/submit" },
  { label: "Search", to: "/search" },
  { label: "AI Search", to: "/ai-search" },
  { label: "Leaderboard", to: "/leaderboard" },
  { label: "Settings", to: "/settings" },
];

const adminNavItems: NavItem[] = [
  { label: "Users", to: "/admin/users" },
  { label: "Moderation", to: "/admin/moderation" },
  { label: "Config", to: "/admin/config" },
];

export function Sidebar({ isOpen, onClose, isAdmin = false }: SidebarProps) {
  const { isDark, toggle } = useTheme();
  const { isAnonymous, toggle: toggleAnon } = useAnonymousMode();

  return (
    <>
      {/* Mobile overlay */}
      {isOpen && (
        <div className="sidebar-overlay" onClick={onClose} aria-hidden="true" />
      )}

      <aside className={`sidebar ${isOpen ? "sidebar--open" : ""}`}>
        <div className="sidebar__header">
          <span className="sidebar__app-name">{APP_NAME}</span>
          <button
            className="sidebar__close-btn"
            onClick={onClose}
            aria-label="Close navigation"
          >
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M18 6L6 18M6 6l12 12" />
            </svg>
          </button>
        </div>

        <nav className="sidebar__nav">
          <ul className="sidebar__list">
            {mainNavItems.map((item) => (
              <li key={item.to}>
                <NavLink
                  to={item.to}
                  end={item.to === "/"}
                  className={({ isActive }) =>
                    `sidebar__link ${isActive ? "sidebar__link--active" : ""}`
                  }
                  onClick={onClose}
                >
                  {item.label}
                </NavLink>
              </li>
            ))}
          </ul>

          {isAdmin && (
            <>
              <div className="sidebar__divider" />
              <div className="sidebar__section-label">Admin</div>
              <ul className="sidebar__list">
                {adminNavItems.map((item) => (
                  <li key={item.to}>
                    <NavLink
                      to={item.to}
                      className={({ isActive }) =>
                        `sidebar__link ${isActive ? "sidebar__link--active" : ""}`
                      }
                      onClick={onClose}
                    >
                      {item.label}
                    </NavLink>
                  </li>
                ))}
              </ul>
            </>
          )}
        </nav>

        <div className="sidebar__footer">
          <button className="sidebar__theme-toggle" onClick={toggle} aria-label="Toggle dark mode">
            {isDark ? (
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="5" />
                <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" />
              </svg>
            ) : (
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z" />
              </svg>
            )}
            <span>{isDark ? "Light Mode" : "Dark Mode"}</span>
          </button>
          <button className="sidebar__theme-toggle" onClick={toggleAnon} aria-label="Toggle anonymous mode">
            <svg width="20" height="20" viewBox="0 0 24 24" fill={isAnonymous ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2">
              <path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2" />
              <circle cx="9" cy="7" r="4" />
              <path d="M23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75" />
            </svg>
            <span>{isAnonymous ? "Anonymous: On" : "Anonymous: Off"}</span>
          </button>
        </div>
      </aside>
    </>
  );
}
