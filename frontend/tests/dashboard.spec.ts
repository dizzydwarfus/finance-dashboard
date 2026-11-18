import { test, expect, type Page } from '@playwright/test';

const companies = [
  { id: '0000000001', cik: '0000000001', symbol: 'DEMO', name: 'Example Industries', imported: true },
  { id: '0000000002', cik: '0000000002', symbol: 'RAW', name: 'Raw filings only', imported: true },
];
const field = { key: 'revenue', label: 'Revenue', format: 'money' };
const source = { accession: '0000000001-26-000001', url: 'https://www.sec.gov/Archives/example.htm', form: '10-K' };
const table = { fields: [field], rows: [{ period: { mode: 'annual', start: '2025-09-28', end: '2026-09-26', fiscalYear: '2026', fiscalPeriod: 'FY' },
  values: { revenue: { value: '125500000', unit: 'USD', sources: [source] } }, growth: { revenue: .255 } }] };

async function mock(page: Page) {
  await page.route('**/api/v1/**', async route => {
    const { pathname, searchParams } = new URL(route.request().url());
    let data: unknown = [];
    if (pathname === '/api/v1/sec/companies') data = companies.filter(c => c.symbol.includes((searchParams.get('q') || '').toUpperCase()));
    if (pathname === '/api/v1/sec/companies/DEMO') data = companies[0];
    if (pathname === '/api/v1/sec/companies/RAW') data = companies[1];
    if (pathname.endsWith('/metrics')) data = pathname.includes('/RAW/') ? { ...table, rows: [] } : table;
    if (pathname.includes('/statements/')) data = searchParams.get('period') === 'annual' ? table : { ...table, rows: [] };
    if (pathname.endsWith('/related')) data = [{ cik: '0000000002', name: 'Raw filings only', symbols: ['RAW'] }];
    return route.fulfill({ json: { data } });
  });
}

test('company navigation defaults to trends or filings based on coverage', async ({ page }) => {
  await mock(page);
  await page.goto('/companies/DEMO');
  await expect(page.getByRole('heading', { name: 'Example Industries DEMO' })).toBeVisible();
  await expect(page.getByRole('img', { name: 'Revenue trend' })).toBeVisible();
  await expect(page.getByRole('tab', { name: 'Overview' })).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByRole('heading', { name: 'Related SEC issuers' })).toBeVisible();
  await page.getByRole('navigation', { name: 'Company navigation' }).getByRole('link', { name: /RAW/ }).click();
  await expect(page).toHaveURL(/companies\/RAW/);
  await expect(page.getByRole('tab', { name: 'Filings' })).toHaveAttribute('aria-selected', 'true');
  await page.goBack();
  await expect(page.getByRole('heading', { name: 'Example Industries DEMO' })).toBeVisible();
  await page.getByRole('textbox', { name: 'Search companies' }).fill('nomatch');
  await expect(page.getByText('No imported companies match.')).toBeVisible();
});

test('statements preserve dates and provenance, and exports respect filters', async ({ page }) => {
  await mock(page);
  await page.goto('/companies/DEMO?view=statements');
  await expect(page.getByRole('table')).toBeVisible();
  await expect(page.getByText('125,500,000 USD')).toBeVisible();
  await expect(page.getByRole('columnheader', { name: '2026 FY · 2026-09-26' })).toBeVisible();
  await expect(page.getByRole('link', { name: '10-K ↗' })).toHaveAttribute('href', source.url);
  await page.getByLabel('Statement', { exact: true }).selectOption('cash-flow');
  await page.getByLabel('Reporting period').selectOption('ytd');
  await expect(page.getByText('No mapped values for this statement and reporting period.')).toBeVisible();
  await expect(page.getByRole('link', { name: 'Download statement CSV' })).toHaveAttribute('href', /cash-flow\?period=ytd&limit=10&format=csv$/);
});

test('financial views fit on mobile and keep the theme on reload', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mock(page);
  await page.goto('/companies/DEMO');
  await expect(page.getByRole('heading', { name: 'Example Industries DEMO' })).toBeVisible();
  const button = page.locator('.theme-toggle');
  await button.click();
  const theme = await page.locator('html').getAttribute('data-theme');
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-theme', theme!);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
});

test('analyst explores a breakdown, exports peers and reopens a frozen model', async ({page})=>{
  await mock(page);
  let saved:Record<string,unknown>|undefined;
  let revisionRevenue='125500000';
  await page.route('**/api/v1/companies/DEMO/metrics*',route=>route.fulfill({json:{data:{...table,rows:[{...table.rows[0],values:{revenue:{...table.rows[0].values.revenue,value:revisionRevenue}}}]}}}));
  const slice={id:'a'.repeat(64),concept:'Revenue',label:'Revenue',axis:'Geography',fixed:[],unit:'USD',mode:'annual'};
  await page.route('**/dimensions?*',route=>route.fulfill({json:{data:[slice]}}));
  await page.route('**/pivot?*',route=>new URL(route.request().url()).searchParams.has('format')?
    route.fulfill({headers:{'Content-Disposition':'attachment; filename="pivot.csv"'},contentType:'text/csv',body:'member,value\nEurope,125'}):
    route.fulfill({json:{data:{periods:[table.rows[0].period],members:[{name:'Europe',cells:[table.rows[0].values.revenue]}]}}}));
  await page.route('**/api/v1/compare?*',route=>route.fulfill({json:{data:[{symbol:'DEMO',misaligned:false,rows:table.rows}]}}));
  await page.route('**/api/v1/workspaces**',route=>{
    const req=route.request();
    if(req.method()==='POST')saved={...req.postDataJSON(),id:'b'.repeat(24),revision:1};
    return route.fulfill({json:{data:req.method()==='POST'||req.url().includes('/workspaces/')?saved:saved?[saved]:[]}});
  });
  await page.route('**/model/evaluate',route=>{
    expect(route.request().postDataJSON().scenarios.base.years[4].margin).toBe('20');
    const forecast={pv:'50',terminalPV:'80',ev:'130',years:Array(5).fill({}),grid:Array(5).fill(Array(5).fill('130')),issue:''};
    return route.fulfill({json:{data:{version:'fcff-1',forecasts:{base:forecast,bear:forecast,bull:forecast}}}});
  });
  await page.goto('/companies/DEMO?view=explore');
  await page.getByLabel('Reported breakdown').selectOption(slice.id);
  await expect(page.getByRole('rowheader',{name:'Europe'})).toBeVisible();
  const csv=await page.getByText('Download pivot CSV').evaluate(async link=> (await fetch((link as HTMLAnchorElement).href)).text()); expect(csv).toContain('Europe,125');
  await page.getByRole('tab',{name:'Compare'}).click();await page.getByRole('button',{name:'Add SIC peer RAW'}).click();
  await expect(page.getByText('Download comparison CSV')).toHaveAttribute('href',/symbols=DEMO%2CRAW/);
  await page.getByRole('tab',{name:'Model'}).click();
  await page.getByRole('button',{name:'Use selected baseline'}).click();
  await page.getByLabel('Operating margin year 1',{exact:true}).fill('20');
  await page.getByRole('button',{name:'Apply Year 1 to all years'}).click();
  await page.getByRole('button',{name:'Evaluate scenarios'}).click();
  await page.getByRole('textbox',{name:'Name',exact:true}).fill('Investment case');
  await page.getByRole('button',{name:'Save',exact:true}).click();await expect(page.getByText('Saved revision 1.')).toBeVisible();
  revisionRevenue='200000000';await page.reload();
  await page.getByLabel('Open saved item').selectOption('b'.repeat(24));
  await expect(page.getByText('125,500,000 USD')).toBeVisible();await expect(page.getByText('Enterprise value sensitivity · base')).toBeVisible();
  await page.getByRole('button',{name:'Rebase on selected filing'}).click();await expect(page.getByText('200,000,000 USD')).toBeVisible();
});
