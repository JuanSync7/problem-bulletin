import { useState, useEffect, useCallback, useMemo } from "react";

export interface User {
  id: string;
  email: string;
  displayName: string;
  role: string;
}

export interface AuthState {
  isAuthenticated: boolean;
  user: User | null;
  isLoading: boolean;
  error: string | null;
}

export function useAuth() {
  const [state, setState] = useState<AuthState>({
    isAuthenticated: false,
    user: null,
    isLoading: true,
    error: null,
  });

  const fetchMe = useCallback(async () => {
    setState((prev) => ({ ...prev, isLoading: true, error: null }));
    try {
      const res = await fetch("/api/auth/me", { credentials: "include" });
      if (res.ok) {
        const user: User = await res.json();
        setState({ isAuthenticated: true, user, isLoading: false, error: null });
      } else {
        setState({ isAuthenticated: false, user: null, isLoading: false, error: null });
      }
    } catch {
      setState({ isAuthenticated: false, user: null, isLoading: false, error: null });
    }
  }, []);

  useEffect(() => {
    fetchMe();
  }, [fetchMe]);

  const login = useCallback(() => {
    window.location.href = "/api/auth/login";
  }, []);

  const loginWithMagicLink = useCallback(async (email: string) => {
    setState((prev) => ({ ...prev, isLoading: true, error: null }));
    try {
      const res = await fetch("/api/auth/magic/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
        credentials: "include",
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ message: "Failed to send magic link" }));
        throw new Error(body.message || "Failed to send magic link");
      }
      setState((prev) => ({ ...prev, isLoading: false, error: null }));
      return true;
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to send magic link";
      setState((prev) => ({ ...prev, isLoading: false, error: message }));
      return false;
    }
  }, []);

  const logout = useCallback(async () => {
    setState((prev) => ({ ...prev, isLoading: true }));
    try {
      await fetch("/api/auth/logout", {
        method: "POST",
        credentials: "include",
      });
    } catch {
      // proceed with local logout even if request fails
    }
    setState({ isAuthenticated: false, user: null, isLoading: false, error: null });
  }, []);

  const clearError = useCallback(() => {
    setState((prev) => ({ ...prev, error: null }));
  }, []);

  return useMemo(
    () => ({ ...state, login, loginWithMagicLink, logout, fetchMe, clearError }),
    [state, login, loginWithMagicLink, logout, fetchMe, clearError],
  );
}
