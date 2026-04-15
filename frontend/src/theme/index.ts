import React, { createContext, useContext, useEffect, useMemo } from "react";
import { gradients, lightColors, darkColors, statusColors } from "./colors";
import { useDarkMode } from "../hooks/useDarkMode";

export const breakpoints = {
  mobile: 0,
  tablet: 768,
  desktop: 1024,
} as const;

interface ThemeContextValue {
  isDark: boolean;
  mode: string;
  toggle: () => void;
  setMode: (mode: "light" | "dark" | "system") => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) {
    throw new Error("useTheme must be used within a ThemeProvider");
  }
  return ctx;
}

function applyCssVariables(isDark: boolean) {
  const root = document.documentElement;
  const colors = isDark ? darkColors : lightColors;

  root.style.setProperty("--color-bg", colors.bg);
  root.style.setProperty("--color-surface", colors.surface);
  root.style.setProperty("--color-text", colors.text);
  root.style.setProperty("--color-text-secondary", colors.textSecondary);
  root.style.setProperty("--color-border", colors.border);

  root.style.setProperty(
    "--grid-line-color",
    isDark ? "rgba(255, 255, 255, 0.03)" : "rgba(0, 0, 0, 0.06)"
  );

  const grad = isDark ? gradients.primary.dark : gradients.primary.light;
  root.style.setProperty("--color-primary-start", grad.start);
  root.style.setProperty("--color-primary-end", grad.end);
  root.style.setProperty(
    "--gradient-primary",
    `linear-gradient(135deg, ${grad.start}, ${grad.end})`
  );

  root.style.setProperty("--color-star", isDark ? "#FFD700" : "#D4940A");

  root.style.setProperty("--color-success", statusColors.success);
  root.style.setProperty("--color-warning", statusColors.warning);
  root.style.setProperty("--color-error", statusColors.error);
  root.style.setProperty("--color-info", statusColors.info);
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const darkMode = useDarkMode();

  useEffect(() => {
    applyCssVariables(darkMode.isDark);
  }, [darkMode.isDark]);

  const value = useMemo(
    () => ({
      isDark: darkMode.isDark,
      mode: darkMode.mode,
      toggle: darkMode.toggle,
      setMode: darkMode.setMode,
    }),
    [darkMode.isDark, darkMode.mode, darkMode.toggle, darkMode.setMode]
  );

  return React.createElement(ThemeContext.Provider, { value }, children);
}

export { gradients, lightColors, darkColors, statusColors } from "./colors";
