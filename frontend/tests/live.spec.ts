import { test, expect } from '@playwright/test';
// Opt-in only: requires the Go API running against an accessible MongoDB database.
test('live Go-to-MongoDB dashboard smoke', async ({ page }) => {
  test.skip(process.env.DASHBOARD_LIVE_CHECK !== '1', 'Requires the live Go API');
  await page.goto('/');
  await expect(page.getByRole('heading', { level: 1 })).not.toContainText('Your next insight', { timeout: 20_000 });
  await expect(page.getByRole('img', { name: 'Financial metrics and year-over-year growth', exact: true })).toBeVisible();
  await page.screenshot({ path: 'test-results/live-dashboard.png', fullPage: false });
  await page.getByRole('tab', { name: 'Statements' }).click();
  await expect(page.getByRole('table')).toBeVisible();
  await page.getByRole('tab', { name: 'Price history' }).click();
  await expect(page.getByRole('img', { name: /Historical candlestick/ }).or(page.getByText('No stored prices for this date range.'))).toBeVisible();
});
