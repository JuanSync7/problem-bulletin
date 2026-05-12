/**
 * WebSocket subscription hook for ticket / agent.activity events.
 *
 * Backend exposes ``/ws/notifications`` (legacy) plus the ticket-events
 * channel described in design §6. The path is configurable via
 * ``VITE_TICKET_WS_PATH`` and defaults to ``/api/ws`` (the route Phase B1 will
 * mount). If the connection drops the hook reconnects with exponential
 * back-off capped at 30 s. Inbound messages are decoded as the WS envelope
 * from design §6 and dispatched to the supplied callback.
 */
import { useEffect, useRef } from "react";

export interface WSEvent {
  event: string;
  project_id?: string;
  ticket_id?: string | null;
  correlation_id?: string;
  occurred_at?: string;
  payload?: Record<string, unknown>;
}

interface UseTicketStreamOptions {
  projectId?: string;
  onEvent: (evt: WSEvent) => void;
  enabled?: boolean;
}

function resolveWsUrl(): string {
  const path =
    (import.meta as { env?: Record<string, string> }).env?.VITE_TICKET_WS_PATH ||
    "/api/ws";
  if (typeof window === "undefined") return path;
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}${path}`;
}

export function useTicketStream({
  projectId,
  onEvent,
  enabled = true,
}: UseTicketStreamOptions): void {
  const cbRef = useRef(onEvent);
  cbRef.current = onEvent;

  useEffect(() => {
    if (!enabled) return;
    let attempt = 0;
    let closedByCleanup = false;
    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    const connect = () => {
      try {
        ws = new WebSocket(resolveWsUrl());
      } catch {
        scheduleReconnect();
        return;
      }
      ws.onopen = () => {
        attempt = 0;
        if (projectId && ws?.readyState === WebSocket.OPEN) {
          try {
            ws.send(JSON.stringify({ op: "subscribe", project_id: projectId }));
          } catch {
            /* ignore */
          }
        }
      };
      ws.onmessage = (msg) => {
        // Tolerate plain ping/pong frames from legacy /ws/notifications.
        if (typeof msg.data !== "string") return;
        if (msg.data === "ping" || msg.data === "pong") return;
        try {
          const parsed = JSON.parse(msg.data) as WSEvent;
          if (parsed && typeof parsed.event === "string") {
            cbRef.current(parsed);
          }
        } catch {
          /* ignore non-JSON traffic */
        }
      };
      ws.onclose = () => {
        if (closedByCleanup) return;
        scheduleReconnect();
      };
      ws.onerror = () => {
        // onclose will fire and handle reconnection.
      };
    };

    const scheduleReconnect = () => {
      attempt += 1;
      const delay = Math.min(30000, 500 * 2 ** Math.min(attempt, 6));
      reconnectTimer = setTimeout(connect, delay);
    };

    connect();
    return () => {
      closedByCleanup = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      try {
        ws?.close();
      } catch {
        /* ignore */
      }
    };
  }, [projectId, enabled]);
}
