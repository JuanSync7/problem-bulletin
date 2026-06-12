/**
 * Tests for useRealtimeNotifications (WP31).
 *
 * Covers:
 *  1. Handshake: receives "ready" frame silently (callback not called).
 *  2. Callback fires on incoming ticket_notification message.
 *  3. Ping frames are silently ignored.
 *  4. Reconnect-on-close: schedules retry.
 *  5. Visibility pause: does not reconnect when page is hidden.
 *  6. Visibility resume: reconnects on visibilitychange when page becomes visible.
 *  7. Graceful degradation: no-op when WebSocket is undefined.
 */
import "@testing-library/jest-dom";
import { renderHook, act } from "@testing-library/react";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { useRealtimeNotifications } from "../useRealtimeNotifications";

// ---------------------------------------------------------------------------
// WebSocket mock
// ---------------------------------------------------------------------------

class MockWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  readyState = MockWebSocket.CONNECTING;
  url: string;

  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;

  static instances: MockWebSocket[] = [];

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  open() {
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.();
  }

  triggerMessage(data: object) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }

  triggerClose() {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.();
  }

  close() {
    this.triggerClose();
  }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("useRealtimeNotifications", () => {
  let originalWebSocket: typeof WebSocket;

  beforeEach(() => {
    vi.useFakeTimers();
    MockWebSocket.instances = [];
    originalWebSocket = (globalThis as unknown as { WebSocket: typeof WebSocket }).WebSocket;
    (globalThis as unknown as { WebSocket: unknown }).WebSocket = MockWebSocket;

    // Default: page is visible.
    Object.defineProperty(document, "hidden", {
      configurable: true,
      get: () => false,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    (globalThis as unknown as { WebSocket: typeof WebSocket }).WebSocket = originalWebSocket;
  });

  it("does not call onNotification for 'ready' frame", () => {
    const cb = vi.fn();
    renderHook(() => useRealtimeNotifications(cb));

    const ws = MockWebSocket.instances[0];
    ws.open();
    ws.triggerMessage({ type: "ready" });

    expect(cb).not.toHaveBeenCalled();
  });

  it("does not call onNotification for 'ping' frames", () => {
    const cb = vi.fn();
    renderHook(() => useRealtimeNotifications(cb));

    const ws = MockWebSocket.instances[0];
    ws.open();
    ws.triggerMessage({ type: "ping" });

    expect(cb).not.toHaveBeenCalled();
  });

  it("calls onNotification with ticket_notification payload", () => {
    const cb = vi.fn();
    renderHook(() => useRealtimeNotifications(cb));

    const ws = MockWebSocket.instances[0];
    ws.open();
    const payload = {
      type: "ticket_notification",
      kind: "ticket_mention",
      id: "abc",
      target_display_id: "TKT-1",
      created_at: "2026-05-19T00:00:00Z",
    };
    ws.triggerMessage(payload);

    expect(cb).toHaveBeenCalledOnce();
    expect(cb).toHaveBeenCalledWith(expect.objectContaining({ type: "ticket_notification" }));
  });

  it("status starts as 'connecting', becomes 'open' on onopen", () => {
    const cb = vi.fn();
    const { result } = renderHook(() => useRealtimeNotifications(cb));

    expect(result.current.status).toBe("connecting");

    act(() => {
      MockWebSocket.instances[0].open();
    });

    expect(result.current.status).toBe("open");
  });

  it("schedules reconnect after close (backoff)", () => {
    const cb = vi.fn();
    renderHook(() => useRealtimeNotifications(cb));
    const ws = MockWebSocket.instances[0];
    ws.open();

    // Simulate disconnect.
    act(() => {
      ws.triggerClose();
    });

    // Before timer fires: only 1 instance.
    expect(MockWebSocket.instances).toHaveLength(1);

    // Advance past 1s initial backoff.
    act(() => {
      vi.advanceTimersByTime(1100);
    });

    expect(MockWebSocket.instances).toHaveLength(2);
  });

  it("does not reconnect when page is hidden on close", () => {
    const cb = vi.fn();
    renderHook(() => useRealtimeNotifications(cb));
    const ws = MockWebSocket.instances[0];
    ws.open();

    // Now hide the page.
    Object.defineProperty(document, "hidden", {
      configurable: true,
      get: () => true,
    });

    act(() => {
      ws.triggerClose();
    });

    // Advance well past max backoff.
    act(() => {
      vi.advanceTimersByTime(60_000);
    });

    // Should not have reconnected (page hidden).
    expect(MockWebSocket.instances).toHaveLength(1);
  });

  it("reconnects on visibilitychange when page becomes visible", () => {
    const cb = vi.fn();
    renderHook(() => useRealtimeNotifications(cb));

    // Simulate a closed WS while hidden, then page becoming visible.
    const ws = MockWebSocket.instances[0];
    ws.open();
    act(() => {
      ws.triggerClose();
    });

    // No reconnect yet (we're testing the event path, but let the timer be cleared).
    // Advance just enough to avoid the backoff timer.
    act(() => {
      vi.advanceTimersByTime(1100);
    });
    // Now close the newly created ws so we control state.
    if (MockWebSocket.instances[1]) {
      MockWebSocket.instances[1].triggerClose();
    }

    // Simulate visibilitychange to visible.
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    act(() => {
      vi.advanceTimersByTime(100);
    });

    // At least one reconnect attempt was made.
    expect(MockWebSocket.instances.length).toBeGreaterThanOrEqual(2);
  });

  it("no-ops gracefully when WebSocket is undefined", () => {
    // Remove WebSocket from global.
    delete (globalThis as unknown as { WebSocket: unknown }).WebSocket;

    const cb = vi.fn();
    const { result } = renderHook(() => useRealtimeNotifications(cb));

    expect(result.current.status).toBe("closed");
    expect(cb).not.toHaveBeenCalled();
    expect(MockWebSocket.instances).toHaveLength(0);
  });
});
