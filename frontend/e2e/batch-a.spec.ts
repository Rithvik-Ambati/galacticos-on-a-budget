import { expect, test } from "@playwright/test";

// Batch A render checks (docs/PROGRESS.md Phase 6c): each new UI element actually
// appears during a real playthrough against a real, seeded backend -- not just that
// the underlying API returns the right JSON (that's what the pytest suite already
// covers). One continuous session is used throughout since each screen only exists
// after the previous step's real API call.
//
// Filling the XI is done by first fetching real candidates straight from the backend
// (the same data the UI itself would show, just not capped to the UI's top-25
// ability-sorted slice) and picking a nationality-and-budget-legal set of 11, then
// driving the UI by searching each exact player name per slot -- clicking blind
// through the ability-sorted list alone can starve a less-glamorous position (e.g.
// CB) once the nationality cap bites on earlier, flashier picks.

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

test("A1-A4: weak zone, strengths, man of the match, and play again all render", async ({ page }) => {
  let sessionId = "";
  page.on("response", (res) => {
    const m = res.url().match(/\/sessions\/([^/]+)\//);
    if (m && !sessionId) sessionId = m[1];
  });

  await page.goto("/");
  await page.getByRole("button", { name: /enter the draw/i }).click();
  await expect.poll(() => sessionId).not.toBe("");

  await page.getByRole("button", { name: /see scouting report/i }).click();

  // A1: opponent's weak zone, with evidence numbers, on the scouting screen.
  const weakZone = page.getByTestId("opponent-weak-zone");
  await expect(weakZone).toBeVisible();
  await expect(weakZone).not.toHaveText("");

  // Fetch real candidates per position group directly from the backend and build a
  // nationality/budget-legal 11-player lineup.
  const byGroup: Record<string, Candidate[]> = {};
  for (const group of ["GK", "DF", "MF", "FW"]) {
    const res = await page.request.get(
      `/api/sessions/${sessionId}/players/search?position_group=${group}&limit=100`,
    );
    const body = (await res.json()) as { results: Candidate[] };
    byGroup[group] = body.results
      .filter((r) => r.eligibility.eligible)
      .sort((a, b) => b.player.price_eur - a.player.price_eur) // cheap-ish first isn't needed; any legal order works
      .reverse();
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

  // A2: strengths section on the coach's report (a near-top-ability XI reliably
  // triggers at least one zone_advantage/role_coverage strength -- see
  // tests/test_strengths.py for the same property against the demo fixtures).
  await expect(page.getByText("Coach's Report")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("strengths-section")).toBeVisible();

  await page.getByRole("button", { name: /lock in lineup/i }).click();
  await page.getByRole("button", { name: /view match report/i }).click();

  // A3: Man of the Match on the match report.
  const motm = page.getByTestId("man-of-the-match");
  await expect(motm).toBeVisible();
  await expect(motm).not.toHaveText("");

  // A4: Play Again -> a new session, landing back on Build XI with the lineup
  // already prefilled (the "Analyse Lineup" button is enabled immediately, with no
  // player picks made in this fresh page load).
  const playAgain = page.getByTestId("play-again-button");
  await expect(playAgain).toBeVisible();
  await playAgain.click();
  await expect(page.getByRole("button", { name: /analyse lineup/i })).toBeEnabled({ timeout: 15_000 });
});
