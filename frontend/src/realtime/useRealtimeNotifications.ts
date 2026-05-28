/**
 * useRealtimeNotifications — WebSocket hook for realtime notification delivery (WP31).
 *
 * Connects to /api/v1/realtime/ws using the browser's cookie auth
 * (the access_token HttpOnly cookie is sent automatically on same-origin
 * connections — no JS token access required).
 *
 * Features:
 *  - Auto-reconnect with exponential backoff (1s, 2s, 4s, 8s, max 30s).
 *  - Page-visible only: pauses reconnect when document.hidden; resumes on
 *    visibilitychange.
 *  - Graceful degradation: if WebSocket is unavailable (SSR/test env),
 *    status stays "closed" and onNotification is never called.
 *  - Heartbeat pings from server are silently ignored (no-op).
 *
 * Cross-WP rule #11: if the WS can't connect, the existing fetch-based UX
 * keeps working unchanged.
 */

import { useEffect, useRef, useState, useCallback } from "react";

export type WsStatus = "connecting" | "open" | "closed";

export type RealtimePayload = {
  type: string;
  [key: string]: unknown;
};

const WS_PATH = "/api/v1/realtime/ws";
const BACKOFF_INITIAL = 1000;
const BACKOFF_MAX = 30_000;

function buildWsUrl(): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}${WS_PATH}`;
}

export function useRealtimeNotifications(
  onNotification: (payload: RealtimePayload) => void,
): { status: WsStatus } {
  const [status, setStatus] = useState<WsStatus>("closed");
  const wsRef = useRef<WebSocket | null>(null);
  const backoffRef = useRef(BACKOFF_INITIAL);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);
  const onNotificationRef = useRef(onNotification);

  // Keep callback ref current without re-triggering effects.
  useEffect(() => {
    onNotificationRef.current = onNotification;
  });

  const clearRetry = useCallback(() => {
    if (retryTimerRef.current !== null) {
      clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }
  }, []);

  const connect = useCallback(() => {
    // Graceful degradation: SSR or environments without WebSocket.
    if (typeof WebSocket === "undefined") return;
    if (!mountedRef.current) return;
    if (document.hidden) return; // defer until visible

    clearRetry();

    // Don't open a second connection while one is alive.
    if (wsRef.current) {
      const s = wsRef.current.readyState;
      if (s === WebSocket.CONNECTING || s === WebSocket.OPEN) return;
    }

    setStatus("connecting");
    const ws = new WebSocket(buildWsUrl());
    wsRef.current = ws;

    ws.onopen = () => {
      if (!mountedRef.current) {
        ws.close();
        return;
      }
      backoffRef.current = BACKOFF_INITIAL; // reset on successful connect
      setStatus("open");
    };

    ws.onmessage = (event: MessageEvent) => {
      if (!mountedRef.current) return;
      try {
        const payload = JSON.parse(event.data as string) as RealtimePayload;
        // Server heartbeat — ignore.
        if (payload.type === "ping" || payload.type === "ready") return;
        onNotificationRef.current(payload);
      } catch {
        // Malformed message — ignore.
      }
    };

    ws.onclose = () => {
      if (!mountedRef.current) return;
      setStatus("closed");
      wsRef.current = null;

      if (!document.hidden) {
        scheduleReconnect();
      }
    };

    ws.onerror = () => {
      // onclose fires after onerror — reconnect logic lives there.
    };
  }, [clearRetry]);

  const scheduleReconnect = useCallback(() => {
    if (!mountedRef.current) return;
    const delay = backoffRef.current;
    backoffRef.current = Math.min(backoffRef.current * 2, BACKOFF_MAX);
    retryTimerRef.current = setTimeout(() => {
      if (mountedRef.current && !document.hidden) {
        connect();
      }
    }, delay);
  }, [connect]);

  useEffect(() => {
    mountedRef.current = true;
    connect();

    const handleVisibility = () => {
      if (!document.hidden) {
        // Page became visible — (re)connect if not already open.
        if (
          wsRef.current === null ||
          wsRef.current.readyState === WebSocket.CLOSED ||
          wsRef.current.readyState === WebSocket.CLOSING
        ) {
          backoffRef.current = BACKOFF_INITIAL; // fresh start on visibility
          connect();
        }
      }
      // If hidden: do nothing — onclose will skip scheduling a retry.
    };

    document.addEventListener("visibilitychange", handleVisibility);

    return () => {
      mountedRef.current = false;
      document.removeEventListener("visibilitychange", handleVisibility);
      clearRetry();
      if (wsRef.current) {
        wsRef.current.onclose = null; // prevent reconnect on unmount-close
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [connect, clearRetry]);

  return { status };
}
