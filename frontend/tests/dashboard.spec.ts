import { test, expect, type Page } from '@playwright/test';
const company = { symbol: 'DEMO', name: 'Example Industries', description: 'A synthetic company for browser verification.', sector: 'Industrials', industry: 'Manufacturing', country: 'US', exchange: 'DEMO', website: 'https://example.com', currency: 'USD', ceo: 'Alex Example', price: 12.55, marketCap: 125500000, employees: 1200, asOf: '2025-01-15T12:00:00Z' };
async function mock(page: Page, missingPrices = false) {
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url()); let data: unknown = [];
    if (url.pathname.endsWith('/tickers')) data = [{ symbol: 'DEMO', coverage: ['income_statement', 'company_profile'] }, { symbol: 'EMPTY', coverage: ['income_statement'] }].filter(t => t.symbol.includes(url.searchParams.get('q')?.toUpperCase() || ''));
    else if (url.pathname.endsWith('/DEMO')) data = company;
    else if (url.pathname.endsWith('/EMPTY')) data = { ...company, symbol: 'EMPTY', name: 'EMPTY', price: null, asOf: null };
    else if (url.pathname.endsWith('/metrics')) data = { definitions: [{ key: 'revenue', label: 'Revenue', format: 'currency' }, { key: 'netIncome', label: 'Net income', format: 'currency' }], points: [{ date: '2024-12-31', year: '2024', period: 'FY', currency: 'USD', values: { revenue: 125500000, netIncome: 15000000 }, growth: { revenue: .255, netIncome: null } }] };
    else if (url.pathname.includes('/statements/')) data = url.searchParams.get('period') === 'Q1' ? [] : [{ date: '2024-12-31', year: '2024', period: 'FY', currency: 'USD', values: { revenue: 125500000, netIncome: 15000000 } }];
    else if (url.pathname.endsWith('/prices')) { if (missingPrices) return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { message: 'Unavailable' } }) }); data = [{ date: '2024-12-30', open: 12, high: 13, low: 11.5, close: 12.55, volume: 12345 }]; }
    else if (url.pathname.endsWith('/splits')) data = [{ date: '2024-12-30', numerator: 2, denominator: 1 }];
    return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ data }) });
  });
}
test('company navigation, deep links, history and search', async ({ page }) => {
  await mock(page); await page.goto('/companies/DEMO');
  await expect(page.getByRole('heading', { name: 'Example Industries DEMO', exact: true })).toBeVisible();
  await expect(page.getByRole('article').filter({ hasText: 'Revenue' }).getByText('$125.5M', { exact: true })).toBeVisible();
  await page.getByRole('link', { name: /EMPTY/ }).click(); await expect(page).toHaveURL(/companies\/EMPTY/);
  await page.goBack(); await expect(page.getByRole('heading', { name: 'Example Industries DEMO', exact: true })).toBeVisible();
  await page.getByRole('textbox', { name: 'Search tickers' }).fill('nomatch'); await expect(page.getByText('No matching companies.')).toBeVisible();
});
test('statement selection, reporting filters and empty periods', async ({ page }) => {
  await mock(page); await page.goto('/companies/DEMO'); await page.getByRole('tab', { name: 'Statements' }).click();
  await expect(page.getByRole('table')).toBeVisible(); await expect(page.getByRole('cell', { name: '$125,500,000.00' })).toBeVisible();
  await page.getByLabel('Statement type').selectOption('balance'); await expect(page.getByRole('table')).toBeVisible();
  await page.getByLabel('Reporting period').selectOption('Q1'); await expect(page.getByText('No statements for this reporting period.')).toBeVisible();
});
test('charts, stock splits, price dates and theme persist', async ({ page }) => {
  await mock(page); await page.goto('/companies/DEMO');
  await expect(page.getByRole('img', { name: 'Financial metrics and year-over-year growth' })).toBeVisible();
  await page.getByRole('checkbox', { name: 'Net income' }).uncheck();
  await page.getByRole('tab', { name: 'Price history' }).click();
  await expect(page.getByRole('img', { name: /Historical candlestick/ })).toBeVisible();
  await page.getByText('Stock split history', { exact: false }).click(); await expect(page.getByText('2 : 1', { exact: true })).toBeVisible();
  await page.getByLabel('Price from date').fill('2025-01-01'); await page.getByLabel('Price to date').fill('2024-01-01');
  await expect(page.getByText('Choose an end date on or after the start date.')).toBeVisible();
  await page.getByRole('button', { name: 'Reset' }).click();
  const themeButton = page.getByRole('button', { name: /Switch to .* theme/ }).filter({ visible: true });
  await themeButton.click(); const theme = await page.locator('html').getAttribute('data-theme'); await page.reload(); await expect(page.locator('html')).toHaveAttribute('data-theme', theme!);
});
test('price failures do not block financial statements', async ({ page }) => {
  await mock(page, true); await page.goto('/companies/DEMO'); await page.getByRole('tab', { name: 'Price history' }).click();
  await expect(page.getByText('Price history unavailable. Other financial views are still available.')).toBeVisible();
  await page.getByRole('tab', { name: 'Statements' }).click(); await expect(page.getByRole('table')).toBeVisible();
});
test('mobile layout avoids horizontal overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 }); await mock(page); await page.goto('/companies/DEMO');
  await expect(page.getByRole('heading', { name: 'Example Industries DEMO', exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: 'test-results/dashboard-mobile.png', fullPage: true });
});
