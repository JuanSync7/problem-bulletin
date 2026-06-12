/**
 * A3: E2E spec — GlobalSearchBar "View all" row navigates to /search?q=…
 *
 * Preconditions:
 *  - `DEV_AUTH_BYPASS=true` is set in the environment (bypasses auth gate).
 *  - Dev stack running: vite :28173, uvicorn :28080, podman pb-pg :28432.
 *
 * Run with:
 *   DEV_AUTH_BYPASS=true npx playwright test e2e/global-search.viewall.spec.ts
 *
 * NOTE (A3 closeout): Playwright is not installed in this repo.
 * Install with: npm install --save-dev @playwright/test && npx playwright install
 * This spec is written and ready to run once Playwright is installed.
 *
 * Walk:
 *  1. Open page → wait for GlobalSearchBar trigger button (Cmd-K hint).
 *  2. Press Cmd-K → assert search input is focused.
 *  3. Type "foo" → wait for dropdown panel to appear.
 *  4. Navigate to the "View all results" row:
 *       Option A — press End (jump to last item) then verify row is highlighted.
 *       Option B — press ArrowDown until the "View all" row is highlighted.
 *  5. Press Enter.
 *  6. Assert URL is /search?q=foo.
 *  7. Assert the Search page rendered (heading or input with value "foo").
 *
 * Also covers a direct click path (no keyboard):
 *  8. Open a fresh page → Cmd-K → type "bar" → click "View all results for bar".
 *  9. Assert URL is /search?q=bar.
 */
import { test, expect, type Page } from "@playwright/test";

const BASE_URL = process.env.APP_URL ?? "http://localhost:28173";

async function openSearchBar(page: Page): Promise<void> {
  await page.goto(BASE_URL);
  // Trigger GlobalSearchBar via keyboard shortcut.
  const isMac = process.platform === "darwin";
  if (isMac) {
    await page.keyboard.press("Meta+k");
  } else {
    await page.keyboard.press("Control+k");
  }
  // Wait for the search input to be focused.
  await page.waitForSelector('[data-testid="global-search-input"]:focus', {
    timeout: 3000,
  });
}

test.describe("A3: GlobalSearchBar → View all → /search route", () => {
  test("keyboard path: End → Enter navigates to /search?q=foo", async ({ page }) => {
    await openSearchBar(page);

    await page.keyboard.type("foo");

    // Wait for dropdown to appear.
    await page.waitForSelector('[data-testid="global-search-dropdown"]', {
      timeout: 3000,
    });

    // Press End to jump focus to the last item ("View all results for foo").
    await page.keyboard.press("End");

    // Confirm the "View all" row is highlighted.
    const viewAllRow = page.getByRole("option", { name: /view all results for foo/i });
    await expect(viewAllRow).toHaveAttribute("aria-selected", "true");

    // Press Enter to navigate.
    await page.keyboard.press("Enter");

    // Assert URL and Search page rendered.
    await expect(page).toHaveURL(/\/search\?q=foo/);
    const searchInput = page.getByRole("textbox");
    await expect(searchInput).toHaveValue("foo");
  });

  test("mouse path: clicking 'View all' navigates to /search?q=bar", async ({ page }) => {
    await openSearchBar(page);

    await page.keyboard.type("bar");

    await page.waitForSelector('[data-testid="global-search-dropdown"]', {
      timeout: 3000,
    });

    const viewAllRow = page.getByRole("option", { name: /view all results for bar/i });
    await viewAllRow.click();

    await expect(page).toHaveURL(/\/search\?q=bar/);
    const searchInput = page.getByRole("textbox");
    await expect(searchInput).toHaveValue("bar");
  });

  test("Search nav entry is absent from the sidebar", async ({ page }) => {
    await page.goto(BASE_URL);

    // Wait for sidebar to appear.
    await page.waitForSelector("nav.sidebar__nav", { timeout: 3000 });

    // There must be no link labelled "Search" pointing to /search.
    const searchLink = page.getByRole("link", { name: /^Search$/ });
    await expect(searchLink).not.toBeVisible();
  });

  test("/search?q=foo deep-link still loads Search page with query pre-filled", async ({ page }) => {
    await page.goto(`${BASE_URL}/search?q=foo`);

    // Search page renders a textbox pre-filled with the query.
    const searchInput = page.getByRole("textbox");
    await expect(searchInput).toHaveValue("foo");
  });
});
