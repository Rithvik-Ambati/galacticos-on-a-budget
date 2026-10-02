import { expect, test } from "@playwright/test";

// Part 2a guard (docs/DECISIONS.md "Synthetic data is no longer the silent
// default"): when the backend's /health reports synthetic data, a persistent
// "DEMO DATA" banner must appear on every screen -- this run's dev.db was
// re-seeded with DATA_SOURCE=synthetic specifically so this is exercised for real,
// not assumed from the component code alone.

test("synthetic data source shows a persistent demo-data banner", async ({ page }) => {
  const health = await (await page.request.get("/api/health")).json();
  expect(health.data_source).toBe("synthetic");

  await page.goto("/");
  const banner = page.getByTestId("demo-data-banner");
  await expect(banner).toBeVisible();
  await expect(banner).toContainText("DEMO DATA");

  // Still visible after navigating off the welcome screen -- "every screen", not
  // just the first one.
  await page.getByRole("button", { name: /enter the draw/i }).click();
  await expect(banner).toBeVisible();
});
