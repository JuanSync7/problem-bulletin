/**
 * KindPill — colored pill rendering an entity-kind label.
 *
 * WP63: extracted from Search.tsx so future surfaces (filters, recent items,
 * cross-entity references) reuse the same palette. The bronze `user`/`agent`
 * values intentionally match the `--agent-fg`/`--agent-bg` CSS tokens used
 * by PersonPicker, Kanban avatars, and TicketDetail's inline pill
 * (v2.29 "Instrument" palette).
 */

const PALETTE: Record<string, string> = {
  problem: "#2D6FB0",
  ticket: "#156B5E",
  component: "#0891b2",
  label: "#1F8A4C",
  user: "#7A5A18",
  agent: "#7A5A18",
  // v2.29-S6: Share / Bounty spaces (Instrument palette:
  // --color-primary-start / --color-star).
  share_post: "#156B5E",
  bounty: "#B07A0C",
};

const FALLBACK = "#6b7280";

/** Display overrides for kinds whose raw value reads poorly in a pill. */
const LABELS: Record<string, string> = {
  share_post: "share",
};

export function KindPill({ kind }: { kind: string }) {
  const color = PALETTE[kind] ?? FALLBACK;
  return (
    <span
      className="search-v2-kind-badge"
      style={{
        backgroundColor: color + "22",
        color,
        border: `1px solid ${color}55`,
      }}
    >
      {LABELS[kind] ?? kind}
    </span>
  );
}
