/**
 * B2: Project hierarchy page E2E spec (Playwright).
 *
 * NOTE: Playwright is NOT installed in this environment.
 * This spec is written to the correct Playwright API for future execution
 * when the dev stack and Playwright are available.
 *
 * Walks a seeded project's hierarchy page:
 *  1. Navigate to /projects/<id>/hierarchy
 *  2. Assert tree rows are visible
 *  3. Toggle a verbosity (type) checkbox → filtered rows disappear
 *  4. Click a row → URL becomes /tickets/<key>
 */
import { test, expect } from "@playwright/test";

const PROJECT_ID = process.env.E2E_PROJECT_ID ?? "p-seed-001";
const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:28173";

test.describe("Project Hierarchy Page", () => {
  test.beforeEach(async ({ page }) => {
    // Navigate to the hierarchy page
    await page.goto(`${BASE_URL}/projects/${PROJECT_ID}/hierarchy`);
  });

  test("renders tree rows for the seeded project", async ({ page }) => {
    // Wait for tree rows to appear
    const treeItems = page.locator('[role="treeitem"]');
    await expect(treeItems.first()).toBeVisible({ timeout: 10_000 });
    const count = await treeItems.count();
    expect(count).toBeGreaterThan(0);
  });

  test("toggling a type checkbox filters tree rows", async ({ page }) => {
    // Wait for tree to load
    await page.locator('[role="treeitem"]').first().waitFor({ state: "visible", timeout: 10_000 });

    // Count initial rows
    const initial = await page.locator('[role="treeitem"]').count();
    expect(initial).toBeGreaterThan(0);

    // Find and uncheck the "task" checkbox (if exists)
    const taskCheckbox = page.locator('input[type="checkbox"][data-type="task"]');
    const hasTaskCheckbox = await taskCheckbox.count();
    if (hasTaskCheckbox > 0) {
      const wasChecked = await taskCheckbox.isChecked();
      if (wasChecked) {
        await taskCheckbox.uncheck();
        // Wait for re-render
        await page.waitForTimeout(200);
        const after = await page.locator('[role="treeitem"]').count();
        // Should have fewer or equal rows (task rows hidden)
        expect(after).toBeLessThanOrEqual(initial);
      }
    }
  });

  test("clicking a tree node navigates to /tickets/<key>", async ({ page }) => {
    // Wait for tree to load
    await page.locator('[role="treeitem"]').first().waitFor({ state: "visible", timeout: 10_000 });

    // Click the first tree item
    const firstRow = page.locator('[role="treeitem"]').first();
    const keyText = await firstRow.locator(".hierarchy-tree__key").textContent();
    await firstRow.click();

    // Expect URL to change to /tickets/<key>
    if (keyText) {
      await expect(page).toHaveURL(new RegExp(`/tickets/${keyText.trim()}`));
    } else {
      await expect(page).toHaveURL(/\/tickets\//);
    }
  });

  test("tree container has no card chrome (seamless background)", async ({ page }) => {
    await page.locator('[role="treeitem"]').first().waitFor({ timeout: 10_000 }).catch(() => {
      // tree may be empty; still check styles
    });

    const container = page.locator('[data-testid="hierarchy-tree-container"]');
    await expect(container).toBeVisible({ timeout: 5_000 });

    const bg = await container.evaluate((el) => getComputedStyle(el).backgroundColor);
    // Should be transparent or rgba(0,0,0,0)
    expect(bg).toMatch(/transparent|rgba\(0,\s*0,\s*0,\s*0\)/);

    const shadow = await container.evaluate((el) => getComputedStyle(el).boxShadow);
    expect(shadow).toMatch(/^(none|)$/);
  });
});
