import { test, expect } from '@playwright/test';

test('local containers serve SEC data and exports without starting an import', async ({ page }) => {
  test.skip(process.env.SEC_LIVE_TEST !== 'true','Requires the Compose SEC fixture database');
  await page.goto('http://127.0.0.1:3000/companies/DEMO');
  await expect(page.getByRole('heading', { name: 'Apple filing fixture DEMO' })).toBeVisible();
  await expect(page.getByText('478,834,000,000 USD')).toBeVisible();
  await page.getByRole('tab', { name: 'Statements' }).click();
  await expect(page.getByRole('link', { name: 'Download statement CSV' })).toBeVisible();
  await page.getByRole('tab', { name: 'Filings' }).click();
  await expect(page.getByRole('table', { name: 'SEC numeric facts and segment dimensions' })).toBeVisible();
});
