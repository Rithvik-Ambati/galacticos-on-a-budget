import { expect, test } from "@playwright/test";

// Final check (project owner's instructions): a fresh session end to end against
// the live, real-data Postgres app -- draw -> build -> analyse -> counter ->
// simulate -> 5 real chat questions -- covering the whole loop in one continuous
// Playwright run, not just the individual screen checks batch-a/batch-b already
// cover. Lineup-building reuses batch-a's exact approach: fetch real, eligible
// candidates straight from the backend and pick a nationality/budget-legal 11,
// then drive the UI by exact player name per slot.

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
const BUDGET_EUR = 500_000_000;

interface Candidate {
  player: { player_id: string; name: string; nationality: string; price_eur: number };
  eligibility: { eligible: boolean };
}

const CHAT_QUESTIONS = [
  "Which of my players has the most assists",
  "from my squad not in overall",
  "Why did we win?",
  "Who are the best rated players?",
  "What are the odds?",
];

test("full session: draw -> build -> analyse -> counter -> simulate -> 5 chat questions", async ({ page }) => {
  let sessionId = "";
  page.on("response", (res) => {
    const m = res.url().match(/\/sessions\/([^/]+)\//);
    if (m && !sessionId) sessionId = m[1];
  });

  await page.goto("/");
  await page.getByRole("button", { name: /enter the draw/i }).click();
  await expect.poll(() => sessionId).not.toBe("");

  await page.getByRole("button", { name: /see scouting report/i }).click();
  await expect(page.getByTestId("opponent-weak-zone")).toBeVisible();

  const byGroup: Record<string, Candidate[]> = {};
  for (const group of ["GK", "DF", "MF", "FW"]) {
    const res = await page.request.get(
      `/api/sessions/${sessionId}/players/search?position_group=${group}&limit=100`,
    );
    const body = (await res.json()) as { results: Candidate[] };
    byGroup[group] = body.results.filter((r) => r.eligibility.eligible).reverse();
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

  // Counter leg: at least one round before locking in.
  const counterButton = page.getByRole("button", { name: /counter again/i });
  await expect(counterButton).toBeEnabled({ timeout: 15_000 });
  await counterButton.click();
  await expect(page.getByRole("button", { name: /see updated report/i })).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: /see updated report/i }).click();
  await expect(page.getByText("Coach's Report")).toBeVisible({ timeout: 15_000 });

  await page.getByRole("button", { name: /lock in lineup/i }).click();
  await page.getByRole("button", { name: /view match report/i }).click();

  const motm = page.getByTestId("man-of-the-match");
  await expect(motm).toBeVisible();
  await expect(motm).not.toHaveText("");

  // 5 real chat questions, one at a time -- each must get a real, non-empty answer
  // (never stuck on the streaming placeholder, never a raw error).
  const chatInput = page.getByPlaceholder("Ask about any player, stat or decision...");
  const sendButton = page.getByRole("button", { name: /^send$/i });
  for (let i = 0; i < CHAT_QUESTIONS.length; i++) {
    await chatInput.fill(CHAT_QUESTIONS[i]);
    await sendButton.click();
    const bubble = page.locator(".chat-bubble.assistant").nth(i);
    await expect(bubble).toBeVisible({ timeout: 10_000 });
    await expect(bubble).not.toHaveText("", { timeout: 20_000 });
    await expect(bubble).not.toHaveText("…", { timeout: 20_000 });
    const text = (await bubble.textContent()) ?? "";
    expect(text.toLowerCase().startsWith("error:")).toBe(false);
  }
});
