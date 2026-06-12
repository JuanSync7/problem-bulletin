/**
 * A1b: E2E spec — GlobalSearchBar direct-match navigation.
 *
 * Preconditions:
 *  - `DEV_AUTH_BYPASS=true` is set in the environment (bypasses auth gate).
 *  - A fixture ticket with display_id "AION-1" exists in the database.
 *    Seed it via: INSERT INTO tickets ... display_id = 'AION-1'
 *    (or via the existing fixtures/seed scripts).
 *  - Dev stack running: vite :28173, uvicorn :28080, podman pb-pg :28432.
 *
 * Run with:
 *   DEV_AUTH_BYPASS=true npx playwright test e2e/global-search.directmatch.spec.ts
 *
 * NOTE (A1b closeout): Playwright is not yet installed in this repo.
 * Install with: npm install --save-dev @playwright/test && npx playwright install
 * This spec is written and ready to run once Playwright is installed.
 * Project key regex: ^[A-Z][A-Z0-9]{1,9}$ (no underscores — verified against A1a).
 */
import { test, expect, type Page } from "@playwright/test";

const BASE_URL = "http://localhost:28173";

/** Navigate to app and wait for the GlobalSearchBar to appear. */
async function openApp(page: Page) {
  await page.goto(BASE_URL);
  // The GlobalSearchBar input is always mounted at chrome level.
  await page.waitForSelector('[role="searchbox"]', { timeout: 10_000 });
}

test.describe("GlobalSearchBar — direct-match navigation", () => {
  test("Cmd-K focuses the search input (Mac)", async ({ page }) => {
    await openApp(page);

    const input = page.getByRole("searchbox");
    await expect(input).not.toBeFocused();

    await page.keyboard.press("Meta+k");
    await expect(input).toBeFocused();
  });

  test("Ctrl-K focuses the search input (Windows/Linux)", async ({ page }) => {
    await openApp(page);

    const input = page.getByRole("searchbox");
    await page.keyboard.press("Control+k");
    await expect(input).toBeFocused();
  });

  test("typing AION-1 shows direct-match row", async ({ page }) => {
    await openApp(page);

    await page.keyboard.press("Control+k");
    await page.getByRole("searchbox").fill("AION-1");

    // Wait for the direct-match dropdown to appear.
    await expect(page.getByText("Direct match")).toBeVisible({ timeout: 5_000 });
    // The fixture ticket row should appear.
    await expect(page.getByText("AION-1")).toBeVisible();
  });

  test("pressing Enter on direct-match navigates to /tickets/AION-1", async ({
    page,
  }) => {
    await openApp(page);

    await page.keyboard.press("Control+k");
    const input = page.getByRole("searchbox");
    await input.fill("AION-1");

    // Wait for direct-match row.
    await expect(page.getByText("Direct match")).toBeVisible({ timeout: 5_000 });

    await input.press("Enter");

    // Should navigate to the ticket detail page.
    await expect(page).toHaveURL(/\/tickets\/AION-1/, { timeout: 5_000 });
  });

  test("clicking the direct-match row navigates to /tickets/AION-1", async ({
    page,
  }) => {
    await openApp(page);

    await page.keyboard.press("Control+k");
    await page.getByRole("searchbox").fill("AION-1");
    await expect(page.getByText("Direct match")).toBeVisible({ timeout: 5_000 });

    // Click the result item button.
    await page.getByRole("option", { name: /AION-1/ }).click();

    await expect(page).toHaveURL(/\/tickets\/AION-1/, { timeout: 5_000 });
  });
});
