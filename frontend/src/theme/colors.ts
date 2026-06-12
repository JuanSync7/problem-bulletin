/* "Instrument" palette (v2.29 redesign) — warm paper / graphite ink,
   single deep-viridian accent. Minimal, precise, quiet. */

export const gradients = {
  primary: {
    light: { start: "#156B5E", end: "#1F8A77" },
    dark: { start: "#2BA08C", end: "#3DBFA8" },
  },
} as const;

export const lightColors = {
  bg: "#F7F5F0",
  surface: "#FFFFFF",
  text: "#1C1B17",
  textSecondary: "#5C594F",
  border: "#E3E0D6",
} as const;

export const darkColors = {
  bg: "#131312",
  surface: "#1B1B19",
  text: "#E8E6DF",
  textSecondary: "#A8A496",
  border: "#33322D",
} as const;

export const statusColors = {
  success: "#1F8A4C",
  warning: "#B07A0C",
  error: "#C2453A",
  info: "#2D6FB0",
} as const;
