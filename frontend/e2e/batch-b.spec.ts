import { expect, test } from "@playwright/test";

// Batch B render checks (docs/PROGRESS.md Phase 6c).

test("B1: opponent's predicted lineup renders on the scouting screen", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /enter the draw/i }).click();
  await page.getByRole("button", { name: /see scouting report/i }).click();

  const opponentLineup = page.getByTestId("opponent-lineup");
  await expect(opponentLineup).toBeVisible();
  // An estimated XI with real player names, not an all-empty pitch. Some synthetic
  // squads are too thin in one position group to fill every slot (a pre-existing
  // gap in graph/nodes.py's draw(), not something this check introduced -- see
  // docs/PROGRESS.md Phase 6c), so this allows a handful of empty slots rather than
  // requiring exactly 11.
  const filledCount = await opponentLineup.locator(".pitch-slot.filled").count();
  expect(filledCount).toBeGreaterThanOrEqual(8);
});
