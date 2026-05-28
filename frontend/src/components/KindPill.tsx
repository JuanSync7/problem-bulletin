/**
 * KindPill — colored pill rendering an entity-kind label.
 *
 * WP63: extracted from Search.tsx so future surfaces (filters, recent items,
 * cross-entity references) reuse the same palette. The slate `user`/`agent`
 * values intentionally match the `--agent-fg`/`--agent-bg` CSS tokens used
 * by PersonPicker, Kanban avatars, and TicketDetail's inline pill.
 */

const PALETTE: Record<string, string> = {
  problem: "#2563eb",
  ticket: "#7c3aed",
  component: "#0891b2",
  label: "#059669",
  user: "#475569",
  agent: "#475569",
};

const FALLBACK = "#6b7280";

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
      {kind}
    </span>
  );
}
