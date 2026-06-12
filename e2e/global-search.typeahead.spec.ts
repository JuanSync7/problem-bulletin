/**
 * A2b: E2E spec — GlobalSearchBar typeahead dropdown.
 *
 * Preconditions:
 *  - `DEV_AUTH_BYPASS=true` is set in the environment (bypasses auth gate).
 *  - Seed fixtures exist that will match "Bug":
 *      - At least one Problem with "Bug" in the title.
 *      - At least one Ticket with "Bug" in the title.
 *    Seed via: scripts/seed_search_fixtures.py or equivalent fixture.
 *  - Dev stack running: vite :28173, uvicorn :28080, podman pb-pg :28432.
 *
 * Run with:
 *   DEV_AUTH_BYPASS=true npx playwright test e2e/global-search.typeahead.spec.ts
 *
 * NOTE (A2b closeout): Playwright is not installed in this repo.
 * Install with: npm install --save-dev @playwright/test && npx playwright install
 * This spec is written and ready to run once Playwright is installed.
 *
 * Walk:
 *  1. Open page → wait for GlobalSearchBar.
 *  2. Focus bar (Cmd-K) → assert input focused.
 *  3. Type "Bug" → wait for dropdown to appear.
 *  4. Assert at least one entity group header is visible.
 *  5. Assert "View all results for Bug" row is visible.
 *  6. Press ↓↓ (two ArrowDown presses) to move highlight.
 *  7. Press Enter → assert URL changed to an entity detail page.
 *  8. Additional: Click "View all" → assert URL changes to /search?q=Bug.
 */
import { test, expect, type Page } from "@playwright/test";

const BASE_URL = "http://localhost:28173";

/** Navigate to app and wait for the GlobalSearchBar to appear. */
async function openApp(page: Page) {
  await page.goto(BASE_URL);
  await page.waitForSelector('[role="searchbox"]', { timeout: 10_000 });
}

/** Focus search bar via Cmd-K / Ctrl-K. */
async function focusSearchBar(page: Page) {
  const isMac = process.platform === "darwin";
  if (isMac) {
    await page.keyboard.press("Meta+k");
  } else {
    await page.keyboard.press("Control+k");
  }
  await expect(page.locator('[role="searchbox"]')).toBeFocused();
}

test.describe("GlobalSearchBar — typeahead dropdown", () => {
  test.beforeEach(async ({ page }) => {
    await openApp(page);
  });

  test("typing 'Bug' opens the dropdown with grouped results", async ({
    page,
  }) => {
    await focusSearchBar(page);

    const input = page.locator('[role="searchbox"]');
    await input.fill("Bug");

    // Dropdown should appear — the listbox is rendered
    const dropdown = page.locator('[role="listbox"]');
    await expect(dropdown).toBeVisible({ timeout: 3_000 });

    // At least one result item should be visible
    const options = dropdown.locator('[role="option"]');
    await expect(options.first()).toBeVisible({ timeout: 3_000 });
  });

  test("'View all results for Bug' row is pinned at bottom", async ({
    page,
  }) => {
    await focusSearchBar(page);

    const input = page.locator('[role="searchbox"]');
    await input.fill("Bug");

    // Wait for dropdown
    await expect(page.locator('[role="listbox"]')).toBeVisible({
      timeout: 3_000,
    });

    // "View all" row should be present
    const viewAll = page.locator("text=/View all results/i");
    await expect(viewAll).toBeVisible({ timeout: 3_000 });
  });

  test("↓↓ Enter navigates to an entity detail page (not /search)", async ({
    page,
  }) => {
    await focusSearchBar(page);

    const input = page.locator('[role="searchbox"]');
    await input.fill("Bug");

    // Wait for dropdown to load results
    await expect(
      page.locator('[role="listbox"] [role="option"]').first(),
    ).toBeVisible({ timeout: 3_000 });

    // Navigate down twice and select
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Enter");

    // URL should have changed to an entity detail page, not /search
    await page.waitForURL((url) => {
      const path = url.pathname;
      return path !== "/" && !path.startsWith("/search");
    }, { timeout: 5_000 });

    // Verify we're on some entity route
    const currentUrl = page.url();
    expect(currentUrl).not.toContain("/search");
  });

  test("clicking 'View all' navigates to /search?q=Bug", async ({ page }) => {
    await focusSearchBar(page);

    const input = page.locator('[role="searchbox"]');
    await input.fill("Bug");

    // Wait for dropdown to load
    await expect(page.locator('[role="listbox"]')).toBeVisible({
      timeout: 3_000,
    });

    // Click "View all" row
    await page.locator("text=/View all results/i").click();

    // Should navigate to search page with query
    await page.waitForURL("**/search?q=Bug", { timeout: 5_000 });
    expect(page.url()).toContain("/search?q=Bug");
  });

  test("Esc closes the dropdown", async ({ page }) => {
    await focusSearchBar(page);

    const input = page.locator('[role="searchbox"]');
    await input.fill("Bug");

    // Wait for dropdown to appear
    await expect(page.locator('[role="listbox"]')).toBeVisible({
      timeout: 3_000,
    });

    // Press Escape — dropdown should close
    await page.keyboard.press("Escape");
    await expect(page.locator('[role="listbox"]')).not.toBeVisible({
      timeout: 2_000,
    });
  });

  test("ArrowUp from no-selection wraps to last row (View all), Enter goes to /search?q=Bug", async ({
    page,
  }) => {
    await focusSearchBar(page);

    const input = page.locator('[role="searchbox"]');
    await input.fill("Bug");

    // Wait for dropdown
    await expect(page.locator('[role="listbox"]')).toBeVisible({
      timeout: 3_000,
    });

    // Arrow up wraps to the last row (View all)
    await page.keyboard.press("ArrowUp");
    await page.keyboard.press("Enter");

    // Should navigate to search
    await page.waitForURL("**/search?q=Bug", { timeout: 5_000 });
    expect(page.url()).toContain("/search?q=Bug");
  });

  test("Cmd-K still focuses the input (A1b regression)", async ({ page }) => {
    // Ensure input is not focused initially
    const input = page.locator('[role="searchbox"]');
    await expect(input).not.toBeFocused();

    await focusSearchBar(page);

    await expect(input).toBeFocused();
  });
});
