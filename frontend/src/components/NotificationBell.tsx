import React, { useState, useEffect, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import "./NotificationBell.css";

interface Notification {
  id: string;
  type: "comment" | "solution" | "status" | string;
  message: string;
  problemId: string;
  read: boolean;
  createdAt: string;
}

function relativeTime(dateStr: string): string {
  const now = Date.now();
  const then = new Date(dateStr).getTime();
  const diffSec = Math.floor((now - then) / 1000);

  if (diffSec < 60) return "just now";
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.floor(diffHr / 24);
  if (diffDay < 30) return `${diffDay}d ago`;
  return `${Math.floor(diffDay / 30)}mo ago`;
}

function typeIconClass(type: string): string {
  switch (type) {
    case "comment":
      return "notification-bell__item-icon notification-bell__item-icon--comment";
    case "solution":
      return "notification-bell__item-icon notification-bell__item-icon--solution";
    case "status":
      return "notification-bell__item-icon notification-bell__item-icon--status";
    default:
      return "notification-bell__item-icon notification-bell__item-icon--default";
  }
}

function TypeIcon({ type }: { type: string }) {
  switch (type) {
    case "comment":
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
        </svg>
      );
    case "solution":
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <path d="M9 12l2 2 4-4" />
          <circle cx="12" cy="12" r="10" />
        </svg>
      );
    case "status":
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <path d="M12 2v4m0 12v4m-7-7H1m22 0h-4m-2.636-5.364l-2.828-2.828m9.9 9.9l-2.828-2.828M6.464 6.464L3.636 3.636m9.9 9.9l-2.828 2.828" />
        </svg>
      );
    default:
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <circle cx="12" cy="12" r="10" />
          <path d="M12 16v-4m0-4h.01" />
        </svg>
      );
  }
}

export function NotificationBell() {
  const navigate = useNavigate();
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);

  // Calculate unread count whenever notifications change
  useEffect(() => {
    setUnreadCount(notifications.filter((n) => !n.read).length);
  }, [notifications]);

  // WebSocket connection for real-time notifications
  useEffect(() => {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws/notifications`;

    function connect() {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onmessage = (event) => {
        try {
          const notification: Notification = JSON.parse(event.data);
          setNotifications((prev) => {
            const next = [notification, ...prev];
            // Keep only the 5 most recent
            return next.slice(0, 5);
          });
        } catch {
          // Ignore malformed messages
        }
      };

      ws.onclose = () => {
        // Attempt reconnect after 5 seconds
        setTimeout(() => {
          if (wsRef.current === ws) {
            connect();
          }
        }, 5000);
      };

      ws.onerror = () => {
        ws.close();
      };
    }

    connect();

    return () => {
      const ws = wsRef.current;
      wsRef.current = null;
      ws?.close();
    };
  }, []);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(e.target as Node)
      ) {
        setIsOpen(false);
      }
    }

    if (isOpen) {
      document.addEventListener("mousedown", handleClickOutside);
      return () => document.removeEventListener("mousedown", handleClickOutside);
    }
  }, [isOpen]);

  const handleToggle = useCallback(() => {
    setIsOpen((prev) => {
      const opening = !prev;
      if (opening) {
        // Mark all as read when opening
        setNotifications((ns) => ns.map((n) => ({ ...n, read: true })));
      }
      return opening;
    });
  }, []);

  function handleNotificationClick(notification: Notification) {
    setIsOpen(false);
    navigate(`/problems/${notification.problemId}`);
  }

  function handleMarkAllRead() {
    setNotifications((ns) => ns.map((n) => ({ ...n, read: true })));
  }

  return (
    <div className="notification-bell" ref={dropdownRef}>
      <button
        className="notification-bell__button"
        onClick={handleToggle}
        aria-label={`Notifications${unreadCount > 0 ? ` (${unreadCount} unread)` : ""}`}
        type="button"
      >
        <svg
          width="20"
          height="20"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          aria-hidden="true"
        >
          <path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.73 21a2 2 0 01-3.46 0" />
        </svg>
        {unreadCount > 0 && (
          <span className="notification-bell__badge">
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        )}
      </button>

      {isOpen && (
        <div className="notification-bell__dropdown">
          <div className="notification-bell__dropdown-header">
            <span className="notification-bell__dropdown-title">
              Notifications
            </span>
            {notifications.some((n) => !n.read) && (
              <button
                className="notification-bell__mark-read"
                onClick={handleMarkAllRead}
                type="button"
              >
                Mark all read
              </button>
            )}
          </div>

          {notifications.length === 0 ? (
            <div className="notification-bell__empty">
              No notifications yet
            </div>
          ) : (
            notifications.map((notification) => (
              <div
                key={notification.id}
                className={`notification-bell__item${!notification.read ? " notification-bell__item--unread" : ""}`}
                onClick={() => handleNotificationClick(notification)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    handleNotificationClick(notification);
                  }
                }}
              >
                <div className={typeIconClass(notification.type)}>
                  <TypeIcon type={notification.type} />
                </div>
                <div className="notification-bell__item-body">
                  <div className="notification-bell__item-message">
                    {notification.message}
                  </div>
                  <div className="notification-bell__item-time">
                    {relativeTime(notification.createdAt)}
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
