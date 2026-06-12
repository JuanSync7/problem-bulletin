/**
 * v2.29-S3/S7: Share space E2E spec (Playwright).
 *
 * Preconditions:
 *  - `DEV_AUTH_BYPASS=true` is set in the environment (bypasses auth gate).
 *  - Dev stack running: vite :28173, uvicorn :28080, podman pb-pg :28432
 *    (`make up`), and the demo seeded (`make demo` — runs orchestrate_demo,
 *    which calls seed_demo.seed()).
 *  - seed_demo creates 3 share posts (natural-keyed on title, see
 *    SHARE_POST_TITLES in app/scripts/seed_demo.py):
 *      * alice  → "How I use alice-coder for refactors"
 *      * bob    → "Prompting tips that cut our LLM spend in half"
 *      * agent  → "Agent report: parser scaffold run results"
 *        (authored by alice-coder; renders the bronze `agent` KindPill)
 *
 * Run with:
 *   DEV_AUTH_BYPASS=true npx playwright test e2e/share-space.spec.ts
 */
import { test, expect, type Page } from "@playwright/test";

const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:28173";

const ALICE_POST = "How I use alice-coder for refactors";
const BOB_POST = "Prompting tips that cut our LLM spend in half";
const AGENT_POST = "Agent report: parser scaffold run results";

/** Locate a share card by its seeded title (seed-order resilient). */
function cardByTitle(page: Page, title: string) {
  return page.locator('[data-testid="share-card"]', { hasText: title });
}

async function openShare(page: Page) {
  await page.goto(`${BASE_URL}/share`);
  await expect(
    page.getByRole("heading", { name: "Share", exact: true }),
  ).toBeVisible({ timeout: 10_000 });
  // Wait for the list to load (seeded data ⇒ at least one card).
  await expect(
    page.locator('[data-testid="share-card"]').first(),
  ).toBeVisible({ timeout: 10_000 });
}

test.describe("Share space — seeded feed", () => {
  test("renders the three seeded posts", async ({ page }) => {
    await openShare(page);

    await expect(cardByTitle(page, ALICE_POST)).toBeVisible();
    await expect(cardByTitle(page, BOB_POST)).toBeVisible();
    await expect(cardByTitle(page, AGENT_POST)).toBeVisible();
  });

  test("alice's post shows her author label", async ({ page }) => {
    await openShare(page);

    const card = cardByTitle(page, ALICE_POST);
    await expect(card.locator(".share-card__author")).toHaveText("alice");
  });

  test("agent-authored post shows the bronze agent chip", async ({ page }) => {
    await openShare(page);

    const card = cardByTitle(page, AGENT_POST);
    // KindPill renders `.search-v2-kind-badge` with the raw kind label.
    const pill = card.locator(".search-v2-kind-badge");
    await expect(pill).toHaveText("agent");
    // Bronze palette: KindPill PALETTE.agent === #7A5A18.
    await expect(pill).toHaveCSS("color", "rgb(122, 90, 24)");
    // The agent post links back to its source ticket.
    await expect(card.locator(".share-card__link")).toBeVisible();
  });
});

test.describe("Share space — create post", () => {
  test("creating a post via the inline form prepends it to the feed", async ({
    page,
  }) => {
    await openShare(page);

    // Unique title so re-runs never collide with seeded/natural-keyed rows.
    const title = `E2E post ${Date.now()}`;

    await page.getByRole("button", { name: "+ Share" }).click();
    const form = page.getByRole("form", { name: "New post" });
    await expect(form).toBeVisible();

    await form.getByLabel("Title").fill(title);
    await form
      .getByLabel("Body")
      .fill("Posted by the share-space e2e spec. Safe to delete.");
    await form.getByLabel("Tags").fill("e2e");
    await form.getByRole("button", { name: "Post" }).click();

    // The new post is prepended — first card in the list.
    const firstCard = page.locator('[data-testid="share-card"]').first();
    await expect(firstCard).toContainText(title, { timeout: 10_000 });
    // And the form closed.
    await expect(form).toHaveCount(0);
  });
});

test.describe("Share space — vote toggle", () => {
  test("toggling the upvote changes the count and aria-pressed", async ({
    page,
  }) => {
    await openShare(page);

    const card = cardByTitle(page, ALICE_POST);
    const voteBtn = card.locator(".share-card__vote");
    await expect(voteBtn).toBeVisible();

    const before = Number(
      ((await voteBtn.textContent()) ?? "").replace(/[^\d]/g, ""),
    );
    const wasPressed = (await voteBtn.getAttribute("aria-pressed")) === "true";

    // First toggle: count moves by ±1 and pressed state flips.
    await voteBtn.click();
    const expected = wasPressed ? before - 1 : before + 1;
    await expect(voteBtn).toContainText(String(expected), { timeout: 5_000 });
    await expect(voteBtn).toHaveAttribute(
      "aria-pressed",
      String(!wasPressed),
    );

    // Second toggle: restore the original state so the dev DB stays stable.
    await voteBtn.click();
    await expect(voteBtn).toContainText(String(before), { timeout: 5_000 });
    await expect(voteBtn).toHaveAttribute("aria-pressed", String(wasPressed));
  });
});
