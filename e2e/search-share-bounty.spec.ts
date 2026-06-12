/**
 * v2.29-S6: Search — Share / Bounties arms + recent searches E2E spec.
 *
 * Preconditions:
 *  - `DEV_AUTH_BYPASS=true` is set in the environment (bypasses auth gate).
 *  - Dev stack running: vite :28173, uvicorn :28080, podman pb-pg :28432
 *    (`make up`), and the demo seeded (`make demo`).
 *  - seed_demo creates share posts / bounties keyed on title (see
 *    SHARE_POST_TITLES / BOUNTY_TITLES in app/scripts/seed_demo.py).
 *  - Recent searches are pushed by the chrome-level GlobalSearchBar on
 *    Enter (localStorage key `aion.search.recents.<userId>`) and read back
 *    by the /search empty state — both keyed on the same auth user, so a
 *    single browser context sees its own recents.
 *
 * Run with:
 *   DEV_AUTH_BYPASS=true npx playwright test e2e/search-share-bounty.spec.ts
 */
import { test, expect, type Page } from "@playwright/test";

const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:28173";

const SHARE_POST_TITLE = "How I use alice-coder for refactors";
const BOUNTY_TITLE = "Document our agent prompting patterns";

async function openSearch(page: Page) {
  await page.goto(`${BASE_URL}/search`);
  await expect(
    page.getByRole("heading", { name: "Search", exact: true }),
  ).toBeVisible({ timeout: 10_000 });
}

/** The search-page query input (distinct from the chrome GlobalSearchBar). */
function searchInput(page: Page) {
  return page.locator(".search-page__input");
}

test.describe("Search page — Share / Bounties tabs", () => {
  test("Share and Bounties tabs appear in the tablist", async ({ page }) => {
    await openSearch(page);

    const tablist = page.getByRole("tablist", { name: "Search scope" });
    await expect(
      tablist.getByRole("tab", { name: "Share" }),
    ).toBeVisible();
    await expect(
      tablist.getByRole("tab", { name: "Bounties" }),
    ).toBeVisible();
  });

  test("querying a seeded share post under the Share tab returns it", async ({
    page,
  }) => {
    await openSearch(page);

    await page.getByRole("tab", { name: "Share" }).click();
    await expect(page.getByRole("tab", { name: "Share" })).toHaveAttribute(
      "aria-selected",
      "true",
    );

    await searchInput(page).fill(SHARE_POST_TITLE);

    const result = page.locator(".search-result-card", {
      hasText: SHARE_POST_TITLE,
    });
    await expect(result.first()).toBeVisible({ timeout: 10_000 });
    // KindPill on the share arm renders the "share" display label.
    await expect(
      result.first().locator(".search-v2-kind-badge"),
    ).toHaveText("share");
  });

  test("querying a seeded bounty under the Bounties tab returns it", async ({
    page,
  }) => {
    await openSearch(page);

    await page.getByRole("tab", { name: "Bounties" }).click();
    await searchInput(page).fill(BOUNTY_TITLE);

    const result = page.locator(".search-result-card", {
      hasText: BOUNTY_TITLE,
    });
    await expect(result.first()).toBeVisible({ timeout: 10_000 });
    await expect(
      result.first().locator(".search-v2-kind-badge"),
    ).toHaveText("bounty");
  });

  test("the All tab shows Share and Bounties preview arms", async ({
    page,
  }) => {
    await openSearch(page);

    // entity=all is the default tab; query something both arms match.
    await searchInput(page).fill("agent");

    const grid = page.locator(".search-all-grid");
    await expect(grid).toBeVisible({ timeout: 10_000 });
    await expect(
      grid.locator(".search-all-arm__heading", { hasText: "Share" }),
    ).toBeVisible();
    await expect(
      grid.locator(".search-all-arm__heading", { hasText: "Bounties" }),
    ).toBeVisible();
  });
});

test.describe("Search page — recent searches", () => {
  test("a query submitted in the global search bar appears as a recent chip on revisit", async ({
    page,
  }) => {
    // 1. Push a recent via the chrome-level GlobalSearchBar (Enter on a
    //    non-empty query writes to localStorage; no direct match for a
    //    free-text query, so no navigation occurs).
    await page.goto(BASE_URL);
    await page.waitForSelector('[role="searchbox"]', { timeout: 10_000 });

    const box = page.getByRole("searchbox");
    await box.fill(SHARE_POST_TITLE);
    await box.press("Enter");

    // 2. Revisit /search with no query — the empty state shows the
    //    "Recent searches" chip group sourced from the same store.
    await openSearch(page);

    const recents = page.getByRole("group", { name: "Recent searches" });
    await expect(recents).toBeVisible({ timeout: 10_000 });
    const chip = recents.locator(".search-page__recent-chip", {
      hasText: SHARE_POST_TITLE,
    });
    await expect(chip).toBeVisible();

    // 3. Clicking the chip re-runs the query.
    await chip.click();
    await expect(
      page
        .locator(".search-result-card", { hasText: SHARE_POST_TITLE })
        .first(),
    ).toBeVisible({ timeout: 10_000 });
  });
});
