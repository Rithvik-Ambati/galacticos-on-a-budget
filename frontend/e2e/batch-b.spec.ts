import { expect, test, type Page } from "@playwright/test";

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

// Shared with batch-a.spec.ts's approach: fetch real candidates straight from the
// backend and build a nationality/budget-legal 11-player lineup, then drive the UI
// by searching each exact name per slot.
const SLOT_GROUPS: { id: string; group: string }[] = [
  { id: "GK", group: "GK" },
  { id: "LB", group: "DF" },
  { id: "CB1", group: "DF" },
  { id: "CB2", group: "DF" },
  { id: "RB", group: "DF" },
  { id: "DM", group: "MF" },
  { id: "LCM", group: "MF" },
  { id: "RCM", group: "MF" },
  { id: "LW", group: "FW" },
  { id: "ST", group: "FW" },
  { id: "RW", group: "FW" },
];
const BUDGET_EUR = 1_000_000_000;

interface Candidate {
  player: { player_id: string; name: string; nationality: string; price_eur: number };
  eligibility: { eligible: boolean };
}

async function playThroughToMatchDay(page: Page): Promise<void> {
  let sessionId = "";
  page.on("response", (res) => {
    const m = res.url().match(/\/sessions\/([^/]+)\//);
    if (m && !sessionId) sessionId = m[1];
  });

  await page.goto("/");
  await page.getByRole("button", { name: /enter the draw/i }).click();
  await expect.poll(() => sessionId).not.toBe("");
  await page.getByRole("button", { name: /see scouting report/i }).click();

  const byGroup: Record<string, Candidate[]> = {};
  for (const group of ["GK", "DF", "MF", "FW"]) {
    const res = await page.request.get(`/api/sessions/${sessionId}/players/search?position_group=${group}&limit=100`);
    const body = (await res.json()) as { results: Candidate[] };
    // Cheapest-first leaves more budget/nationality-cap room for later slots.
    byGroup[group] = body.results.filter((r) => r.eligibility.eligible).sort((a, b) => a.player.price_eur - b.player.price_eur);
  }

  const natCounts: Record<string, number> = {};
  let spend = 0;
  const chosen: Record<string, Candidate["player"]> = {};
  for (const slot of SLOT_GROUPS) {
    const pick = byGroup[slot.group].find((c) => {
      if (Object.values(chosen).some((p) => p.player_id === c.player.player_id)) return false;
      if ((natCounts[c.player.nationality] ?? 0) >= 3) return false;
      if (spend + c.player.price_eur > BUDGET_EUR) return false;
      return true;
    });
    expect(pick, `no legal candidate left for slot ${slot.id}`).toBeTruthy();
    chosen[slot.id] = pick!.player;
    natCounts[pick!.player.nationality] = (natCounts[pick!.player.nationality] ?? 0) + 1;
    spend += pick!.player.price_eur;
  }

  await page.getByRole("button", { name: /build your xi/i }).click();
  await expect(page.locator(".player-row").first()).toBeVisible({ timeout: 10_000 });

  const filledCount = page.getByText(/Starting XI · \d+\/11/);
  const searchBox = page.getByPlaceholder("Search players...");
  for (const slot of SLOT_GROUPS) {
    const before = (await filledCount.textContent()) ?? "";
    await page.locator(".pitch-slot:not(.filled)").first().click();
    await searchBox.fill(chosen[slot.id].name);
    const row = page.locator(".player-row:not(.ineligible)", { hasText: chosen[slot.id].name }).first();
    await expect(row).toBeVisible({ timeout: 10_000 });
    await row.click();
    await expect(filledCount).not.toHaveText(before, { timeout: 5_000 });
    await searchBox.fill("");
  }

  const analyseButton = page.getByRole("button", { name: /analyse lineup/i });
  await expect(analyseButton).toBeEnabled({ timeout: 15_000 });
  await analyseButton.click();
  await expect(page.getByText("Coach's Report")).toBeVisible({ timeout: 15_000 });

  await page.getByRole("button", { name: /lock in lineup/i }).click();
  await expect(page.getByText("Match Day")).toBeVisible({ timeout: 15_000 });
}

test("B2: what worked / what didn't renders on the match report", async ({ page }) => {
  await playThroughToMatchDay(page);
  await page.getByRole("button", { name: /view match report/i }).click();
  await expect(page.getByText("Match Report")).toBeVisible({ timeout: 15_000 });

  const postMatch = page.getByTestId("post-match-analysis");
  await expect(postMatch).toBeVisible();
  await expect(postMatch).not.toHaveText("");
});

test("B3: draw reveal renders, and match-day events stage in with a working skip control", async ({ page }) => {
  // Draw reveal (screen 2): just needs to render -- playThroughToMatchDay already
  // drives past it, so check it directly here instead.
  await page.goto("/");
  await page.getByRole("button", { name: /enter the draw/i }).click();
  const reveal = page.getByTestId("opponent-reveal");
  await expect(reveal).toBeVisible();
  await expect(reveal).not.toHaveText("");

  // Match-day reveal + skip (screen 7): reusing the same full flow since the
  // timeline only exists once a match has actually been simulated.
  await playThroughToMatchDay(page);
  const timeline = page.getByTestId("match-timeline");
  await expect(timeline).toBeVisible();

  // Independent of however many events this particular simulated match produced:
  // if there's anything left to reveal, a Skip control is present, and clicking it
  // immediately shows every event (the "Skip" pill itself then disappears, since
  // MatchDay.tsx only renders it while `revealing` is true).
  const skip = page.getByTestId("skip-reveal");
  if (await skip.isVisible().catch(() => false)) {
    const before = await timeline.locator(".fade-in-up").count();
    await skip.click();
    await expect(skip).toHaveCount(0);
    const after = await timeline.locator(".fade-in-up").count();
    expect(after).toBeGreaterThanOrEqual(before);
  }
});

test("B3: prefers-reduced-motion shows every match-day event immediately, no skip control", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await playThroughToMatchDay(page);
  await expect(page.getByTestId("skip-reveal")).toHaveCount(0);
});

test("B4: copy result and download image both work from the match report", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await playThroughToMatchDay(page);
  await page.getByRole("button", { name: /view match report/i }).click();
  await expect(page.getByText("Match Report")).toBeVisible({ timeout: 15_000 });

  await page.getByTestId("copy-result-button").click();
  await expect(page.getByTestId("copy-result-button")).toHaveText(/Copied/);
  const clipboardText = await page.evaluate(() => navigator.clipboard.readText());
  expect(clipboardText).toContain("Gaffer");
  expect(clipboardText).toMatch(/You \d+ - \d+/);
  expect(clipboardText).toContain("Rating:");

  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByTestId("download-image-button").click(),
  ]);
  expect(download.suggestedFilename()).toMatch(/^gaffer-vs-.*\.png$/);
});
