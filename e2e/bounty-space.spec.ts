/**
 * v2.29-S4/S7: Bounty space E2E spec (Playwright).
 *
 * Preconditions:
 *  - `DEV_AUTH_BYPASS=true` is set in the environment (bypasses auth gate).
 *  - Dev stack running: vite :28173, uvicorn :28080, podman pb-pg :28432
 *    (`make up`), and the demo seeded (`make demo`).
 *  - seed_demo creates 3 bounties (natural-keyed on title, see
 *    BOUNTY_TITLES in app/scripts/seed_demo.py), one per status:
 *      * open    →  50 pts  "Document our agent prompting patterns" (alice)
 *      * claimed → 120 pts  "Stress-test the severity classifier with
 *                            adversarial inputs" (bob → alice-reviewer agent)
 *      * awarded →  80 pts  "Write the kanban drag-and-drop walkthrough doc"
 *                            (alice → bob)
 *
 * NOTE: these tests are read-only by design — clicking Claim would walk a
 * seeded bounty out of `open` with no idempotent path back. We assert the
 * Claim button is present, not its effect.
 *
 * Run with:
 *   DEV_AUTH_BYPASS=true npx playwright test e2e/bounty-space.spec.ts
 */
import { test, expect, type Page } from "@playwright/test";

const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:28173";

const OPEN_BOUNTY = "Document our agent prompting patterns";
const CLAIMED_BOUNTY =
  "Stress-test the severity classifier with adversarial inputs";
const AWARDED_BOUNTY = "Write the kanban drag-and-drop walkthrough doc";

/** Locate a bounty card by its seeded title (seed-order resilient). */
function cardByTitle(page: Page, title: string) {
  return page.locator('[data-testid="bounty-card"]', { hasText: title });
}

async function openBounties(page: Page) {
  await page.goto(`${BASE_URL}/bounties`);
  await expect(
    page.getByRole("heading", { name: "Bounties", exact: true }),
  ).toBeVisible({ timeout: 10_000 });
  await expect(
    page.locator('[data-testid="bounty-card"]').first(),
  ).toBeVisible({ timeout: 10_000 });
}

test.describe("Bounty space — seeded cards", () => {
  test("renders the three seeded bounties under the All filter", async ({
    page,
  }) => {
    await openBounties(page);

    await expect(cardByTitle(page, OPEN_BOUNTY)).toBeVisible();
    await expect(cardByTitle(page, CLAIMED_BOUNTY)).toBeVisible();
    await expect(cardByTitle(page, AWARDED_BOUNTY)).toBeVisible();
  });

  test("each seeded bounty shows its status badge and points", async ({
    page,
  }) => {
    await openBounties(page);

    const open = cardByTitle(page, OPEN_BOUNTY);
    await expect(open.locator(".bounty-card__status")).toHaveText("open");
    await expect(open.locator(".bounty-card__points")).toContainText("50");

    const claimed = cardByTitle(page, CLAIMED_BOUNTY);
    await expect(claimed.locator(".bounty-card__status")).toHaveText(
      "claimed",
    );
    await expect(claimed.locator(".bounty-card__points")).toContainText(
      "120",
    );
    // Claimed by the alice-reviewer agent → bronze agent pill + label.
    await expect(claimed.locator(".search-v2-kind-badge")).toHaveText(
      "agent",
    );
    await expect(claimed.locator(".bounty-card__claimant")).toHaveText(
      "alice-reviewer",
    );

    const awarded = cardByTitle(page, AWARDED_BOUNTY);
    await expect(awarded.locator(".bounty-card__status")).toHaveText(
      "awarded",
    );
    await expect(awarded.locator(".bounty-card__points")).toContainText(
      "80",
    );
    await expect(awarded.locator(".bounty-card__claimant")).toHaveText("bob");
  });
});

test.describe("Bounty space — status filter pills", () => {
  test("Open / Claimed / Awarded pills narrow the list", async ({ page }) => {
    await openBounties(page);

    // Open
    await page.getByRole("tab", { name: "Open" }).click();
    await expect(cardByTitle(page, OPEN_BOUNTY)).toBeVisible({
      timeout: 10_000,
    });
    await expect(cardByTitle(page, CLAIMED_BOUNTY)).toHaveCount(0);
    await expect(cardByTitle(page, AWARDED_BOUNTY)).toHaveCount(0);
    await expect(page.getByRole("tab", { name: "Open" })).toHaveAttribute(
      "aria-selected",
      "true",
    );

    // Claimed
    await page.getByRole("tab", { name: "Claimed" }).click();
    await expect(cardByTitle(page, CLAIMED_BOUNTY)).toBeVisible({
      timeout: 10_000,
    });
    await expect(cardByTitle(page, OPEN_BOUNTY)).toHaveCount(0);

    // Awarded
    await page.getByRole("tab", { name: "Awarded" }).click();
    await expect(cardByTitle(page, AWARDED_BOUNTY)).toBeVisible({
      timeout: 10_000,
    });
    await expect(cardByTitle(page, OPEN_BOUNTY)).toHaveCount(0);

    // Back to All — all three return.
    await page.getByRole("tab", { name: "All" }).click();
    await expect(cardByTitle(page, OPEN_BOUNTY)).toBeVisible({
      timeout: 10_000,
    });
    await expect(cardByTitle(page, CLAIMED_BOUNTY)).toBeVisible();
    await expect(cardByTitle(page, AWARDED_BOUNTY)).toBeVisible();
  });
});

test.describe("Bounty space — claim affordance", () => {
  test("the open bounty shows a Claim button; settled bounties do not", async ({
    page,
  }) => {
    await openBounties(page);

    await expect(
      cardByTitle(page, OPEN_BOUNTY).getByRole("button", { name: "Claim" }),
    ).toBeVisible();

    // Claimed (by someone else) and awarded cards offer no Claim button to
    // this viewer.
    await expect(
      cardByTitle(page, CLAIMED_BOUNTY).getByRole("button", {
        name: "Claim",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      cardByTitle(page, AWARDED_BOUNTY).getByRole("button", {
        name: "Claim",
        exact: true,
      }),
    ).toHaveCount(0);
  });
});
