/**
 * A4: ScopeChips — entity filter scope selector for GlobalSearchBar.
 *
 * Renders a chip row with "All" + one chip per arm key.
 * Active chip has aria-pressed="true" and the `gsb__scope-chip--active` class.
 *
 * Props:
 *   selected  — currently active arm key (or "all")
 *   onChange  — called when a chip is clicked; receives the new arm key or "all"
 */
import type { SearchArmKey } from "../../api/search";

export type ScopeChipValue = SearchArmKey | "all";

const CHIP_LABELS: { value: ScopeChipValue; label: string }[] = [
  { value: "all", label: "All" },
  { value: "tickets", label: "Tickets" },
  { value: "problems", label: "Problems" },
  { value: "components", label: "Components" },
  { value: "labels", label: "Labels" },
  { value: "users", label: "Users" },
];

export interface ScopeChipsProps {
  selected: ScopeChipValue;
  onChange: (value: ScopeChipValue) => void;
}

export function ScopeChips({ selected, onChange }: ScopeChipsProps) {
  return (
    <div className="gsb__scope-chips" role="group" aria-label="Search scope">
      {CHIP_LABELS.map(({ value, label }) => {
        const isActive = selected === value;
        return (
          <button
            key={value}
            className={[
              "gsb__scope-chip",
              isActive ? "gsb__scope-chip--active" : "",
            ]
              .filter(Boolean)
              .join(" ")}
            aria-pressed={isActive}
            onClick={() => onChange(value)}
            type="button"
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}
