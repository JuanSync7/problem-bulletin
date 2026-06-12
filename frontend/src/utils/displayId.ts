/**
 * Display-ID parser for Ticketing v2.
 *
 * In v2 the per-ticket display string is `<PROJECT_KEY>-<n>` where:
 *   - PROJECT_KEY matches `^[A-Z][A-Z0-9]{1,9}$` (2-10 chars, first is a letter)
 *   - n is a positive integer (no leading zeros enforced by the producer, but
 *     this parser accepts any unsigned int run)
 *
 * Replaces the pre-v2 `TKT-\d+` regex; all frontend call sites that need to
 * detect/parse a display id should go through this helper.
 */

const DISPLAY_ID_RE = /^([A-Z][A-Z0-9]{1,9})-(\d+)$/;

export interface ParsedDisplayId {
  key: string;
  n: number;
}

export function parseDisplayId(s: string): ParsedDisplayId | null {
  if (typeof s !== "string") return null;
  const m = DISPLAY_ID_RE.exec(s.trim());
  if (!m) return null;
  const n = Number.parseInt(m[2], 10);
  if (!Number.isFinite(n) || n <= 0) return null;
  return { key: m[1], n };
}

export function isDisplayId(s: string): boolean {
  return parseDisplayId(s) !== null;
}

export function formatDisplayId(key: string, n: number): string {
  return `${key}-${n}`;
}
