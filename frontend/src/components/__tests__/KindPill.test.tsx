/**
 * WP63 — KindPill unit tests.
 *
 * Covers: known-kind palette lookup, unknown-kind fallback, agent/user share
 * the same slate colour (so they visually match the CSS `--agent-fg` palette
 * used elsewhere), and the rendered class name matches the existing CSS
 * selector so prior styling rules keep applying.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { KindPill } from "../KindPill";

describe("KindPill", () => {
  it("renders the kind label as text", () => {
    render(<KindPill kind="problem" />);
    expect(screen.getByText("problem")).toBeInTheDocument();
  });

  it.each(["problem", "ticket", "component", "label", "user", "agent"])(
    "applies the search-v2-kind-badge class for kind=%s",
    (kind) => {
      const { container } = render(<KindPill kind={kind} />);
      const span = container.querySelector("span");
      expect(span).toHaveClass("search-v2-kind-badge");
    },
  );

  it("falls back to neutral grey for unknown kinds", () => {
    const { container } = render(<KindPill kind="totally-unknown" />);
    const span = container.querySelector("span")!;
    // Fallback #6b7280 → JSDOM normalises to rgb(107, 114, 128).
    expect(span.getAttribute("style")).toContain("rgb(107, 114, 128)");
  });

  it("uses the same bronze foreground for user and agent kinds", () => {
    const { container: userC } = render(<KindPill kind="user" />);
    const { container: agentC } = render(<KindPill kind="agent" />);
    const userStyle = userC.querySelector("span")!.getAttribute("style") ?? "";
    const agentStyle =
      agentC.querySelector("span")!.getAttribute("style") ?? "";
    // Bronze #7A5A18 → rgb(122, 90, 24); must match the CSS --agent-fg token.
    expect(userStyle).toContain("rgb(122, 90, 24)");
    expect(agentStyle).toContain("rgb(122, 90, 24)");
  });
});
