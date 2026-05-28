/**
 * TicketFields component — v2.4-WP26
 *
 * Covers:
 *  1. Renders all standard fields from a TicketDTO.
 *  2. layout="drawer" uses ticket-fields--drawer class (vertical stacked).
 *  3. layout="page" uses ticket-fields--page class (dl grid).
 *  4. Renders markdown description as HTML.
 *  5. Handles absent optional fields gracefully.
 */
import "@testing-library/jest-dom";
import { describe, it, expect } from "vitest";
import React from "react";
import { render, screen } from "@testing-library/react";

import { TicketFields } from "../index";
import type { TicketDTO } from "../../../api/tickets";

function makeTicket(overrides: Partial<TicketDTO> = {}): TicketDTO {
  return {
    id: "uuid-abc",
    display_id: "PRJ-1",
    title: "Sample ticket",
    status: "in_progress",
    priority: "high",
    assignee_id: "user-999",
    reporter_id: "user-111",
    project_key: "PRJ",
    story_points: 5,
    due_date: "2026-06-01",
    labels: ["frontend", "bug"],
    description: "**Bold** text",
    created_at: "2026-01-10T12:00:00Z",
    updated_at: "2026-05-01T08:00:00Z",
    version: 3,
    ...overrides,
  };
}

describe("TicketFields", () => {
  it("renders status badge with correct text", () => {
    render(<TicketFields ticket={makeTicket()} />);
    expect(screen.getByTestId("tf-status")).toHaveTextContent(/in progress/i);
  });

  it("renders priority badge", () => {
    render(<TicketFields ticket={makeTicket()} />);
    expect(screen.getByTestId("tf-priority")).toHaveTextContent(/high/i);
  });

  it("renders assignee", () => {
    render(<TicketFields ticket={makeTicket()} />);
    expect(screen.getByTestId("tf-assignee")).toHaveTextContent("user-999");
  });

  it("renders reporter", () => {
    render(<TicketFields ticket={makeTicket()} />);
    expect(screen.getByTestId("tf-reporter")).toHaveTextContent("user-111");
  });

  it("renders project key", () => {
    render(<TicketFields ticket={makeTicket()} />);
    expect(screen.getByTestId("tf-project")).toHaveTextContent("PRJ");
  });

  it("renders story points", () => {
    render(<TicketFields ticket={makeTicket()} />);
    expect(screen.getByTestId("tf-story-points")).toHaveTextContent("5");
  });

  it("renders due date", () => {
    render(<TicketFields ticket={makeTicket()} />);
    expect(screen.getByTestId("tf-due-date")).toHaveTextContent("2026-06-01");
  });

  it("renders labels", () => {
    render(<TicketFields ticket={makeTicket()} />);
    const labelsCell = screen.getByTestId("tf-labels");
    expect(labelsCell).toHaveTextContent("frontend");
    expect(labelsCell).toHaveTextContent("bug");
  });

  it("renders description as markdown HTML", () => {
    render(<TicketFields ticket={makeTicket()} />);
    const descCell = screen.getByTestId("tf-description");
    expect(descCell.innerHTML).toContain("<strong>Bold</strong>");
  });

  it("renders version", () => {
    render(<TicketFields ticket={makeTicket()} />);
    expect(screen.getByTestId("tf-version")).toHaveTextContent("3");
  });

  it("layout='drawer' adds ticket-fields--drawer class on wrapper", () => {
    render(<TicketFields ticket={makeTicket()} layout="drawer" />);
    const wrapper = screen.getByTestId("ticket-fields");
    expect(wrapper).toHaveClass("ticket-fields--drawer");
    expect(wrapper).not.toHaveClass("ticket-fields--page");
  });

  it("layout='page' (default) adds ticket-fields--page class on wrapper", () => {
    render(<TicketFields ticket={makeTicket()} />);
    const wrapper = screen.getByTestId("ticket-fields");
    expect(wrapper).toHaveClass("ticket-fields--page");
    expect(wrapper).not.toHaveClass("ticket-fields--drawer");
  });

  it("drawer layout renders as div (not dl)", () => {
    render(<TicketFields ticket={makeTicket()} layout="drawer" />);
    const wrapper = screen.getByTestId("ticket-fields");
    expect(wrapper.tagName.toLowerCase()).toBe("div");
  });

  it("page layout renders as dl", () => {
    render(<TicketFields ticket={makeTicket()} layout="page" />);
    const wrapper = screen.getByTestId("ticket-fields");
    expect(wrapper.tagName.toLowerCase()).toBe("dl");
  });

  it("shows 'Unassigned' when assignee_id is absent", () => {
    render(<TicketFields ticket={makeTicket({ assignee_id: null })} />);
    expect(screen.getByTestId("tf-assignee")).toHaveTextContent(/unassigned/i);
  });

  it("omits reporter row when reporter_id is absent", () => {
    render(<TicketFields ticket={makeTicket({ reporter_id: null })} />);
    expect(screen.queryByTestId("tf-reporter")).not.toBeInTheDocument();
  });

  it("omits description row when description is absent", () => {
    render(<TicketFields ticket={makeTicket({ description: null })} />);
    expect(screen.queryByTestId("tf-description")).not.toBeInTheDocument();
  });

  it("omits priority row when priority is absent", () => {
    render(<TicketFields ticket={makeTicket({ priority: undefined })} />);
    expect(screen.queryByTestId("tf-priority")).not.toBeInTheDocument();
  });
});
