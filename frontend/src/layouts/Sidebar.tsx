import React from "react";
import { NavLink } from "react-router-dom";
import { useTheme } from "../theme";
import { useAnonymousMode } from "../hooks/useAnonymousMode";
import { useAuth } from "../hooks/useAuth";
import { getUnreadCount } from "../api/notifications";
import { useRealtimeNotifications } from "../realtime/useRealtimeNotifications";
import type { RealtimePayload } from "../realtime/useRealtimeNotifications";

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

// v2.29 IA (usability audit P1#4): grouped sections, ≤8 primary items.
// "Submit Problem" / "Create Ticket" moved into page-context CTAs
// (Problems feed header, Kanban toolbar) — see usability-audit-v229.md P0#1.
interface NavSection {
  label: string | null;
  items: NavItem[];
}

const navSections: NavSection[] = [
  {
    label: "Browse",
    items: [
      { label: "Home", to: "/" },
      { label: "Problems", to: "/problems" },
      { label: "Projects", to: "/projects" },
      { label: "Leaderboard", to: "/leaderboard" },
    ],
  },
  {
    label: "Work",
    items: [
      { label: "Kanban Board", to: "/board" },
      { label: "My Space", to: "/me" },
      { label: "Activity", to: "/activity" },
      { label: "Share", to: "/share" },
      { label: "Bounties", to: "/bounties" },
    ],
  },
  {
    label: "Tools",
    items: [
      { label: "AI Search", to: "/ai-search" },
      { label: "Settings", to: "/settings" },
    ],
  },
];

const adminNavItems: NavItem[] = [
  { label: "Users", to: "/admin/users" },
  { label: "Moderation", to: "/admin/moderation" },
  { label: "Config", to: "/admin/config" },
];

export function Sidebar({ isOpen, onClose, isAdmin = false }: SidebarProps) {
  const { isDark, toggle } = useTheme();
  const { isAnonymous, toggle: toggleAnon } = useAnonymousMode();
  const { user } = useAuth();
  // v2.2-WP14: cheap one-shot fetch of unread mentions for the Activity badge.
  const [unread, setUnread] = React.useState<number>(0);
  React.useEffect(() => {
    let cancelled = false;
    getUnreadCount()
      .then((n) => {
        if (!cancelled) setUnread(n);
      })
      .catch(() => {
        /* silent — badge stays 0 */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // v2.4-WP31: realtime WS fanout — increment/decrement badge without polling.
  // v2.5-WP34: agent_id field signals an agent-inbox read event, not a
  // user-inbox read. The sidebar badge tracks the user's own inbox, so
  // agent-kind read events must NOT decrement it. The WS connection
  // subscribes to both user and agent channels; without this guard, an
  // agent-inbox mark-read would double-decrement (once via the agent
  // channel, once via the user-channel re-publish added in WP34 Part B).
  const handleRealtimePayload = React.useCallback((payload: RealtimePayload) => {
    if (payload.type === "ticket_notification") {
      // Only increment for user-inbox notifications (no agent_id).
      if (!payload.agent_id) {
        setUnread((prev) => prev + 1);
      }
    } else if (payload.type === "notification_read") {
      // Skip agent-inbox reads — they don't affect the user-inbox badge.
      if (!payload.agent_id) {
        setUnread((prev) => Math.max(0, prev - 1));
      }
    } else if (payload.type === "notification_read_all") {
      // Skip agent-inbox bulk reads.
      if (!payload.agent_id) {
        const count = typeof payload.count === "number" ? payload.count : 1;
        setUnread((prev) => Math.max(0, prev - count));
      }
    }
  }, []);

  useRealtimeNotifications(handleRealtimePayload);

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
          {navSections.map((section, idx) => (
            <React.Fragment key={section.label ?? idx}>
              {section.label && (
                <div className="sidebar__section-label">{section.label}</div>
              )}
              <ul className="sidebar__list">
                {section.items.map((item) => (
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
                      {item.to === "/activity" && unread > 0 && (
                        <span
                          className="sidebar__link-badge"
                          aria-label={`${unread} unread mentions`}
                        >
                          {unread}
                        </span>
                      )}
                    </NavLink>
                  </li>
                ))}
              </ul>
            </React.Fragment>
          ))}

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
          {user && (
            <div
              style={{
                padding: "0.5rem 0.75rem",
                marginBottom: "0.5rem",
                fontSize: 12,
                lineHeight: 1.4,
                borderRadius: 6,
                background: "rgba(0,0,0,0.06)",
              }}
              title={user.email}
            >
              <div style={{ fontWeight: 600 }}>{user.displayName}</div>
              <div style={{ opacity: 0.75 }}>{user.email}</div>
              <div style={{ marginTop: 2 }}>
                <span
                  style={{
                    display: "inline-block",
                    padding: "1px 6px",
                    borderRadius: 4,
                    background: user.role === "admin" ? "#C2453A" : "#8B8779",
                    color: "white",
                    fontSize: 10,
                    textTransform: "uppercase",
                    letterSpacing: 0.5,
                  }}
                >
                  {user.role}
                </span>
              </div>
            </div>
          )}
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
