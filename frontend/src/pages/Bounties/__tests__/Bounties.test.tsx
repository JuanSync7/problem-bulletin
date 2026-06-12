/**
 * v2.29-S4 — Bounties page tests.
 *
 * Covers:
 *  1. Renders bounty cards from the api (title, points, poster label).
 *  2. Status filter pills switch the listBounties call params.
 *  3. Claim button calls the api and updates the card.
 *  4. Award button visible only when the viewer is the poster.
 *  5. "+ Post Bounty" form submits via createBounty and prepends.
 *  6. Empty state renders with CTA.
 */
import "@testing-library/jest-dom";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../../../api/bounties";
import BountiesPage from "../index";

vi.mock("../../../api/bounties", () => ({
  listBounties: vi.fn(),
  createBounty: vi.fn(),
  getBounty: vi.fn(),
  claimBounty: vi.fn(),
  unclaimBounty: vi.fn(),
  awardBounty: vi.fn(),
  withdrawBounty: vi.fn(),
}));

// Same useAuth mock pattern as other page tests (e.g. Kanban, Settings).
vi.mock("../../../hooks/useAuth", () => ({
  useAuth: () => ({
    isAuthenticated: true,
    user: {
      id: "viewer-1",
      email: "viewer@x.test",
      displayName: "Viewer",
      role: "member",
    },
    isLoading: false,
    error: null,
  }),
}));

const listBounties = vi.mocked(api.listBounties);
const createBounty = vi.mocked(api.createBounty);
const claimBounty = vi.mocked(api.claimBounty);
const awardBounty = vi.mocked(api.awardBounty);

function fakeBounty(overrides: Partial<api.Bounty> = {}): api.Bounty {
  return {
    id: "b-1",
    title: "Fix the flaky deploy",
    description: "Make CI green again.",
    points: 100,
    status: "open",
    poster_user_id: "poster-1",
    poster_label: "Alice",
    claimant_id: null,
    claimant_type: null,
    claimant_label: null,
    ticket_id: null,
    ticket_display_id: null,
    problem_id: null,
    claimed_at: null,
    awarded_at: null,
    created_at: new Date().toISOString(),
    updated_at: null,
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter
      initialEntries={["/bounties"]}
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <BountiesPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("BountiesPage", () => {
  it("renders bounties from the api", async () => {
    listBounties.mockResolvedValue({
      items: [
        fakeBounty(),
        fakeBounty({ id: "b-2", title: "Write the runbook", points: 30 }),
      ],
      total: 2,
    });
    renderPage();
    expect(
      await screen.findByText("Fix the flaky deploy"),
    ).toBeInTheDocument();
    expect(screen.getByText("Write the runbook")).toBeInTheDocument();
    expect(screen.getByText("★ 100")).toBeInTheDocument();
    // Both seeded bounties default to poster "Alice", so there are two
    // poster labels — assert presence via the All-variant.
    expect(screen.getAllByText("Alice").length).toBe(2);
  });

  it("status filter pills change the list call params", async () => {
    listBounties.mockResolvedValue({ items: [fakeBounty()], total: 1 });
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Fix the flaky deploy");
    expect(listBounties).toHaveBeenLastCalledWith({});

    await user.click(screen.getByRole("tab", { name: "Open" }));
    await waitFor(() =>
      expect(listBounties).toHaveBeenLastCalledWith({ status: "open" }),
    );

    await user.click(screen.getByRole("tab", { name: "Awarded" }));
    await waitFor(() =>
      expect(listBounties).toHaveBeenLastCalledWith({ status: "awarded" }),
    );
  });

  it("claim button calls api and updates the card", async () => {
    listBounties.mockResolvedValue({ items: [fakeBounty()], total: 1 });
    claimBounty.mockResolvedValue(
      fakeBounty({
        status: "claimed",
        claimant_id: "viewer-1",
        claimant_type: "user",
        claimant_label: "Viewer",
        claimed_at: new Date().toISOString(),
      }),
    );
    const user = userEvent.setup();
    renderPage();

    await user.click(
      await screen.findByRole("button", { name: "Claim" }),
    );
    expect(claimBounty).toHaveBeenCalledWith("b-1");

    const card = (await screen.findByText("claimed")).closest(
      "[data-testid='bounty-card']",
    ) as HTMLElement;
    expect(within(card).getByText("Viewer")).toBeInTheDocument();
    expect(
      within(card).queryByRole("button", { name: "Claim" }),
    ).not.toBeInTheDocument();
    // Viewer is the claimant, so Unclaim shows.
    expect(
      within(card).getByRole("button", { name: "Unclaim" }),
    ).toBeInTheDocument();
  });

  it("award button visible only for the poster", async () => {
    listBounties.mockResolvedValue({
      items: [
        fakeBounty({
          id: "b-mine",
          title: "Mine to award",
          status: "claimed",
          poster_user_id: "viewer-1",
          poster_label: "Viewer",
          claimant_id: "someone-else",
          claimant_type: "agent",
          claimant_label: "FixBot",
        }),
        fakeBounty({
          id: "b-other",
          title: "Someone else's bounty",
          status: "claimed",
          poster_user_id: "poster-1",
          claimant_id: "someone-else",
          claimant_type: "user",
          claimant_label: "Bob",
        }),
      ],
      total: 2,
    });
    awardBounty.mockResolvedValue(
      fakeBounty({
        id: "b-mine",
        title: "Mine to award",
        status: "awarded",
        poster_user_id: "viewer-1",
        claimant_id: "someone-else",
        claimant_type: "agent",
        claimant_label: "FixBot",
        awarded_at: new Date().toISOString(),
      }),
    );
    const user = userEvent.setup();
    renderPage();

    const mine = (await screen.findByText("Mine to award")).closest(
      "[data-testid='bounty-card']",
    ) as HTMLElement;
    const other = screen
      .getByText("Someone else's bounty")
      .closest("[data-testid='bounty-card']") as HTMLElement;

    // Agent claimant shows the bronze chip on my card.
    expect(within(mine).getByText("agent")).toBeInTheDocument();

    const awardBtn = within(mine).getByRole("button", {
      name: "Award 100 pts",
    });
    expect(
      within(other).queryByRole("button", { name: /Award/ }),
    ).not.toBeInTheDocument();

    await user.click(awardBtn);
    expect(awardBounty).toHaveBeenCalledWith("b-mine");
    expect(await within(mine).findByText("awarded")).toBeInTheDocument();
  });

  it("create form submits and prepends the new bounty", async () => {
    listBounties.mockResolvedValue({ items: [fakeBounty()], total: 1 });
    createBounty.mockResolvedValue(
      fakeBounty({ id: "b-new", title: "Brand new bounty", points: 25 }),
    );
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Fix the flaky deploy");

    await user.click(screen.getByRole("button", { name: "+ Post Bounty" }));
    await user.type(screen.getByLabelText("Title"), "Brand new bounty");
    await user.type(screen.getByLabelText("Description"), "Do the thing.");
    const pointsInput = screen.getByLabelText("Points");
    await user.clear(pointsInput);
    await user.type(pointsInput, "25");
    await user.click(screen.getByRole("button", { name: "Post" }));

    await waitFor(() =>
      expect(createBounty).toHaveBeenCalledWith({
        title: "Brand new bounty",
        description: "Do the thing.",
        points: 25,
      }),
    );
    expect(await screen.findByText("Brand new bounty")).toBeInTheDocument();
    const cards = screen.getAllByTestId("bounty-card");
    expect(
      within(cards[0]).getByText("Brand new bounty"),
    ).toBeInTheDocument();
  });

  it("renders empty state with CTA when there are no bounties", async () => {
    listBounties.mockResolvedValue({ items: [], total: 0 });
    renderPage();
    expect(await screen.findByText("No bounties yet")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Post a bounty" }),
    ).toBeInTheDocument();
  });
});
