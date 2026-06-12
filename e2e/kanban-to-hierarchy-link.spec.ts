/**
 * B3: Kanban → hierarchy page link E2E spec (Playwright).
 *
 * NOTE: Playwright is NOT installed in this environment.
 * This spec is written to the correct Playwright API for future execution
 * when the dev stack and Playwright are available.
 *
 * Steps:
 *  1. Navigate to the Kanban board (/board?project=<key>).
 *  2. Assert the old "Hierarchy" toggle button is absent.
 *  3. Assert the "View full hierarchy" link is visible in the toolbar.
 *  4. Click "View full hierarchy" → URL becomes /projects/<id>/hierarchy.
 *  5. Assert the hierarchy tree is visible on the new page.
 */
import { test, expect } from "@playwright/test";

const PROJECT_KEY = process.env.E2E_PROJECT_KEY ?? "DEF";
const PROJECT_ID = process.env.E2E_PROJECT_ID ?? "p-seed-001";
const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:28173";

test.describe("Kanban → View full hierarchy link (B3)", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(`${BASE_URL}/board?project=${PROJECT_KEY}`);
    // Wait for the toolbar to settle (project load, filters render).
    await page.waitForSelector('[aria-label="Kanban filters"]', { timeout: 10_000 });
  });

  test("the old 'Hierarchy' toggle button is not present", async ({ page }) => {
    // The old view-toggle was a <button> labelled exactly "Hierarchy".
    const oldBtn = page.getByRole("button", { name: /^hierarchy$/i });
    await expect(oldBtn).toHaveCount(0);
  });

  test("'View full hierarchy' link is visible and navigates to the hierarchy page", async ({ page }) => {
    const link = page.getByRole("link", { name: /view full hierarchy/i });
    await expect(link).toBeVisible({ timeout: 5_000 });

    // The href should point to /projects/<id>/hierarchy.
    const href = await link.getAttribute("href");
    expect(href).toMatch(/\/projects\/.+\/hierarchy/);

    // Click the link and assert the page navigated correctly.
    await link.click();
    await page.waitForURL(`**/projects/${PROJECT_ID}/hierarchy`, { timeout: 10_000 });

    // The hierarchy tree container should be visible.
    const treeContainer = page.locator(".project-hierarchy-tree, [role='tree']");
    await expect(treeContainer.first()).toBeVisible({ timeout: 10_000 });
  });
});
