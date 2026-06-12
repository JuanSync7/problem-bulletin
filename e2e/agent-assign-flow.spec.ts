/**
 * v2.29-S5: Agent assign flow E2E spec (Playwright).
 *
 * Preconditions:
 *  - `DEV_AUTH_BYPASS=true` is set in the environment (bypasses auth gate).
 *  - Dev stack running: vite :28173, uvicorn :28080, podman pb-pg :28432
 *    (`make up`), and the demo orchestrated (`make demo` — seeds the PB
 *    project AND drains the agent-run queue, which posts the structured
 *    "**Summary**:" agent comments).
 *  - The orchestrated anchor ticket is the FIRST ticket by seq_number in
 *    PB — the seed creates the epic "Demo epic: showcase agent
 *    collaboration" first, so this is PB-1 (override via
 *    E2E_ORCHESTRATED_TICKET if your dev DB has drifted).
 *  - "Task: pick a default assignee" is seeded unassigned and carries a
 *    `done` agent_run (dev-coder), so assigning an agent to it makes the
 *    run-status chip appear without further orchestration.
 *
 * Run with:
 *   DEV_AUTH_BYPASS=true npx playwright test e2e/agent-assign-flow.spec.ts
 */
import { test, expect, type Page } from "@playwright/test";

const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:28173";
const PROJECT_KEY = process.env.E2E_PROJECT_KEY ?? "PB";
const ORCHESTRATED_TICKET =
  process.env.E2E_ORCHESTRATED_TICKET ?? "PB-1";

/** Ticket that is seeded unassigned but already has a done agent_run. */
const ASSIGN_TARGET_TITLE = "Task: pick a default assignee";
const AGENT_HANDLE = "alice-coder";

async function openBoard(page: Page) {
  await page.goto(`${BASE_URL}/board?project=${PROJECT_KEY}`);
  await page.waitForSelector(".ticket-card", { timeout: 10_000 });
}

test.describe("Kanban — agent assignment surfaces the run-status chip", () => {
  test("assigning an agent to a ticket with runs shows the run chip", async ({
    page,
  }) => {
    await openBoard(page);

    const card = page.locator(".ticket-card", {
      hasText: ASSIGN_TARGET_TITLE,
    });
    await expect(card).toBeVisible({ timeout: 10_000 });

    // Idempotent across re-runs: only perform the assignment when the
    // ticket is not already agent-assigned.
    const alreadyAgent = await card
      .locator('[data-testid="ticket-avatar-agent"]')
      .count();
    if (alreadyAgent === 0) {
      // Open the inline assign popover — "Assign" button when unassigned,
      // the avatar button when a user currently holds it.
      const assignBtn = card.locator('[data-testid="ticket-assign-btn"]');
      if ((await assignBtn.count()) > 0) {
        await assignBtn.click();
      } else {
        await card.locator('[data-testid="ticket-avatar-user"]').click();
      }

      const pop = card.locator('[data-testid="ticket-assign-pop"]');
      await expect(pop).toBeVisible({ timeout: 5_000 });

      // PersonPicker: role="combobox" input → role="option" rows.
      await pop
        .locator('[data-testid="person-picker-input"]')
        .fill(AGENT_HANDLE);
      await page
        .getByRole("option", { name: new RegExp(AGENT_HANDLE) })
        .first()
        .click();
    }

    // After assignment the board refreshes, the agent-run lookup fetches
    // the ticket's runs, and the chip renders the latest status.
    const refreshedCard = page.locator(".ticket-card", {
      hasText: ASSIGN_TARGET_TITLE,
    });
    const chip = refreshedCard.locator('[data-testid="ticket-run-chip"]');
    await expect(chip).toBeVisible({ timeout: 15_000 });
    await expect(chip).toHaveText(/queued|working…|done|failed/);
    // The avatar is now the bronze agent variant.
    await expect(
      refreshedCard.locator('[data-testid="ticket-avatar-agent"]'),
    ).toBeVisible();
  });
});

test.describe("Ticket detail — AgentRunBanner + structured agent comment", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(`${BASE_URL}/tickets/${ORCHESTRATED_TICKET}`);
    // Wait for the comments section so the page is fully hydrated.
    await page.waitForSelector(
      '[data-testid="ticket-detail-comments-section"]',
      { timeout: 10_000 },
    );
  });

  test("the orchestrated ticket shows the AgentRunBanner", async ({
    page,
  }) => {
    const banner = page.locator('[data-testid="agent-run-banner"]');
    await expect(banner).toBeVisible({ timeout: 10_000 });
    // Post-`make demo` the latest run is done → "<handle> responded" with a
    // link to the posted comment; tolerate in-flight states if the queue is
    // re-draining.
    await expect(banner).toHaveText(
      /responded|working…|queued|failed/,
    );
    if (/responded/.test((await banner.textContent()) ?? "")) {
      await expect(
        page.locator('[data-testid="agent-run-banner-link"]'),
      ).toHaveText("View comment");
    }
  });

  test("an agent comment with a **Summary**: section exists", async ({
    page,
  }) => {
    const comments = page.locator(
      '[data-testid="ticket-detail-comments-section"]',
    );
    // agent_run_queue._format_structured_comment posts:
    //   @{handle} finished on {display_id}
    //   **Summary**: ...
    // Comment bodies render as raw text (CommentThread does not run
    // markdown), so the literal "**Summary**:" marker is visible.
    await expect(
      comments.locator(".comment-thread__body", { hasText: "**Summary**:" })
        .first(),
    ).toBeVisible({ timeout: 10_000 });
    await expect(
      comments
        .locator(".comment-thread__body", {
          hasText: `finished on ${ORCHESTRATED_TICKET}`,
        })
        .first(),
    ).toBeVisible();
  });
});
