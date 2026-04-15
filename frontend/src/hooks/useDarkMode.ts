import { useState, useEffect, useCallback, useMemo } from "react";
import { useMediaQuery } from "./useMediaQuery";

const STORAGE_KEY = "pb-theme";

type ThemeMode = "light" | "dark" | "system";

function getStoredMode(): ThemeMode {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark" || stored === "system") {
      return stored;
    }
  } catch {
    // localStorage unavailable
  }
  return "system";
}

export function useDarkMode() {
  const [mode, setModeState] = useState<ThemeMode>(getStoredMode);
  const prefersColorSchemeDark = useMediaQuery("(prefers-color-scheme: dark)");

  const isDark = mode === "dark" || (mode === "system" && prefersColorSchemeDark);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", isDark ? "dark" : "light");
  }, [isDark]);

  const setMode = useCallback((newMode: ThemeMode) => {
    setModeState(newMode);
    try {
      localStorage.setItem(STORAGE_KEY, newMode);
    } catch {
      // localStorage unavailable
    }
  }, []);

  const toggle = useCallback(() => {
    setMode(isDark ? "light" : "dark");
  }, [isDark, setMode]);

  return useMemo(
    () => ({ isDark, mode, toggle, setMode }),
    [isDark, mode, toggle, setMode]
  );
}
