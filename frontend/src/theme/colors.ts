export const gradients = {
  primary: {
    light: { start: "#006400", end: "#32CD32" },
    dark: { start: "#FFD700", end: "#32CD32" },
  },
} as const;

export const lightColors = {
  bg: "#E4D9C5",
  surface: "#EDE4D4",
  text: "#1A1207",
  textSecondary: "#5A4E3A",
  border: "#C4B89E",
} as const;

export const darkColors = {
  bg: "#121212",
  surface: "#1E1E1E",
  text: "#E0E0E0",
  textSecondary: "#9CA3AF",
  border: "#374151",
} as const;

export const statusColors = {
  success: "#22C55E",
  warning: "#F59E0B",
  error: "#EF4444",
  info: "#3B82F6",
} as const;
