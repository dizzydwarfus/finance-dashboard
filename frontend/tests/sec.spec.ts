import { test, expect, type Page } from '@playwright/test';
const id = '11111111-1111-4111-8111-111111111111';
const company = { id: '0000000001', cik: '0000000001', symbol: 'NEW', symbols: ['NEW'], name: 'New SEC Company', exchanges: ['TEST'], sicDescription: 'Synthetic issuer', lastUpdated: '2026-01-01T00:00:00Z', lastSuccessfullyScrapedAt: '2026-01-01T00:00:00Z', coverage: ['sec_filings'] };
const filing = { id: '0000000001-25-000001', accession: '0000000001-25-000001', form: '10-K', filingDate: '2025-11-01', reportDate: '2025-09-27', sourceUrl: 'https://www.sec.gov/Archives/edgar/data/1/filing.htm', factCount: 102, lastUpdated: '2026-01-01T00:00:00Z', sourceAvailability: 'available' };
async function setup(page: Page, options: { complete?: boolean; failed?: boolean; listError?: boolean; hold?: boolean } = {}) {
  const state = { imported: !!options.complete, submitted: 0, legacyReads: 0, phase: options.complete ? 'completed' : 'queued', polls: 0, allowComplete: !options.hold, received: [] as unknown[] };
  await page.route('**/api/v1/**', async route => {
    const request = route.request(); const url = new URL(request.url()); const path = url.pathname;
    let data: unknown = []; let status = 200; let meta: unknown;
    if (path === '/api/v1/tickers') data = [];
    else if (!path.startsWith('/api/v1/sec/')) { state.legacyReads++; status = 404; }
    else if (path === '/api/v1/sec/companies') {
      if (options.listError) return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { message: 'SEC database unavailable' } }) });
      data = state.imported ? [{ ...company, imported: true }] : []; meta = { suggestions: [], registryUpdatedAt: null };
    }
    else if (path === '/api/v1/sec/companies/NEW') {
      if (state.imported) data = company;
      else return route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ error: { message: 'No imported SEC company' } }) });
    }
    else if (path === '/api/v1/sec/jobs' && request.method() === 'POST') {
      state.submitted++; state.received.push(request.postDataJSON());
      expect(request.headers()['idempotency-key']).toBeTruthy();
      status = 202;
      data = job();
    }
    else if (path.endsWith('/cancel')) { state.phase = 'cancelled'; data = job(); }
    else if (path.endsWith('/retry')) { state.phase = 'queued'; state.polls = 0; data = job(); }
    else if (path === `/api/v1/sec/jobs/${id}`) {
      state.polls++;
      if (options.failed) state.phase = 'blocked';
      else if (state.allowComplete && state.polls >= 2 && state.phase === 'queued') { state.phase = 'completed'; state.imported = true; }
      data = job();
    }
    else if (path.endsWith('/filings')) { data = [filing]; meta = { total: 1, offset: 0, limit: 100 }; }
    else if (path.endsWith('/facts')) {
      const offset = Number(url.searchParams.get('offset') || 0);
      data = [{ id: `fact-${offset}`, concept: '{https://example.invalid}Revenue', label: 'Revenue and sales', value: '123456789012345678.00', nil: false,
        unitRef: 'USD', unit: { numerator: ['{http://www.xbrl.org/2003/iso4217}USD'], denominator: [] }, startDate: '2024-09-29', endDate: '2025-09-27', dimensions: [{ axis: '{https://example.invalid}ProductAxis', member: '{https://example.invalid}HardwareMember' }] }];
      meta = { total: 102, offset, limit: 100 };
    }
    return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify({ data, ...(meta ? { meta } : {}) }) });
    function job() { return { id, cik: '0000000001', symbol: 'NEW', status: state.phase, stage: state.phase === 'queued' ? 'downloading' : state.phase, completed: state.phase === 'completed' ? 1 : 0, total: 1, warnings: [], failures: [], error: state.phase === 'blocked' ? { code: 'sec_blocked', message: 'SEC denied access; review identity before retrying' } : null, updatedAt: `2026-01-01T00:00:${String(state.polls).padStart(2, '0')}Z`, createdAt: '2026-01-01T00:00:00Z' }; }
  });
  return state;
}
test('unknown ticker imports from the app and opens SEC facts without legacy API queries', async ({ page }) => {
  const state = await setup(page);
  await page.goto('/');
  await page.getByRole('textbox', { name: 'Search tickers' }).fill('NEW');
  const start = page.getByRole('button', { name: 'Scrape NEW from SEC' });
  await expect(start).toBeVisible(); await start.click();
  await expect(page).toHaveURL(new RegExp(`/companies/NEW\\?view=sec&job=${id}`));
  await expect(page.getByText('1 / 1 filings completed')).toBeVisible({ timeout: 15000 });
  await expect(page.getByRole('heading', { name: 'New SEC Company NEW' })).toBeVisible();
  await expect(page.getByRole('table', { name: 'SEC numeric facts and segment dimensions' })).toBeVisible();
  await expect(page.getByRole('cell', { name: '123,456,789,012,345,678.00', exact: true })).toBeVisible();
  await expect(page.getByText('ProductAxis: HardwareMember')).toBeVisible();
  expect(state.submitted).toBe(1); expect(state.legacyReads).toBe(0);
  await expect(page.getByRole('tab', { name: 'Statements', exact: true })).toHaveCount(0);
  await page.screenshot({path:'test-results/sec-filings.png',fullPage:true});
  await page.getByLabel('SEC concept filter').fill('Revenue');
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await expect(page.getByText('101–102 of 102')).toBeVisible();
});
test('job deep link reconnects after reload without submitting again', async ({ page }) => {
  const state = await setup(page, { hold: true });
  await page.goto(`/companies/NEW?view=sec&job=${id}`);
  await expect(page.getByText('0 / 1 filings completed')).toBeVisible();
  await page.reload();
  state.allowComplete = true;
  await expect(page.getByText('1 / 1 filings completed')).toBeVisible({ timeout: 15000 });
  expect(state.submitted).toBe(0); expect(state.legacyReads).toBe(0);
});
test('blocked imports explain the problem and expose an explicit retry', async ({ page }) => {
  await setup(page, { failed: true });
  await page.goto(`/companies/NEW?view=sec&job=${id}`);
  await expect(page.getByText('SEC denied access; review identity before retrying')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Retry saved import' })).toBeVisible();
});
test('database errors do not offer a missing-company scrape action', async ({ page }) => {
  await setup(page, { listError: true }); await page.goto('/');
  await page.getByRole('textbox', { name: 'Search tickers' }).fill('NEW');
  await expect(page.getByText('SEC company search unavailable.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Scrape NEW from SEC' })).toHaveCount(0);
});
test('existing issuer refresh is explicit and supports company-facts snapshots', async ({ page }) => {
  const state = await setup(page, { complete: true }); await page.goto('/companies/NEW?view=sec');
  await expect(page.getByRole('button', { name: 'Refresh SEC data' })).toBeVisible();
  await page.getByLabel('SEC import selection').selectOption('company-facts');
  await page.getByRole('button', { name: 'Refresh SEC data' }).click();
  expect(state.received[0]).toEqual({ symbol: 'NEW', action: 'refresh', selection: 'company-facts' });
});
test('a running import can be cancelled while retaining its reconnect URL', async ({ page }) => {
  const state=await setup(page,{hold:true});
  await page.goto(`/companies/NEW?view=sec&job=${id}`);
  await page.getByRole('button',{name:'Cancel import',exact:true}).click();
  await expect(page.getByRole('button',{name:'Retry saved import',exact:true})).toBeVisible();
  expect(state.phase).toBe('cancelled');
  await expect(page).toHaveURL(new RegExp(`job=${id}`));
});
test('partial success keeps completed filing facts available and shows failures', async ({ page }) => {
  await setup(page,{complete:true});
  await page.route(`**/api/v1/sec/jobs/${id}`,route => route.fulfill({contentType:'application/json',body:JSON.stringify({data:{id,symbol:'NEW',cik:'0000000001',status:'partial_failed',stage:'partial_failed',completed:1,total:2,warnings:['An amendment contains no XBRL'],failures:[{accession:'0000000001-25-000002',code:'source_unavailable',message:'Source temporarily unavailable'}],updatedAt:'2026-11-08T00:00:00Z'}})}));
  await page.goto(`/companies/NEW?view=sec&job=${id}`);
  await expect(page.getByText('1 / 2 filings completed')).toBeVisible();
  await expect(page.getByText('0000000001-25-000002: Source temporarily unavailable')).toBeVisible();
  await expect(page.getByRole('table',{name:'SEC numeric facts and segment dimensions'})).toBeVisible();
});

test('SEC-only unknown deep link offers import only after successful lookups', async ({ page }) => {
  await setup(page,{hold:true}); await page.goto('/companies/NEW');
  await expect(page.getByRole('button',{name:'Scrape NEW from SEC',exact:true})).toBeVisible();
  await expect(page.getByRole('tab',{name:'Statements',exact:true})).toHaveCount(0);
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(() => document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
});

test('a failed first import can explicitly change its saved selection', async ({page}) => {
  const state=await setup(page,{failed:true});
  await page.goto(`/companies/NEW?view=sec&job=${id}`);
  await page.getByRole('button',{name:'Start updated import',exact:true}).waitFor();
  await page.getByLabel('SEC import selection').selectOption('range');
  await page.getByLabel('SEC filed from').fill('2025-01-01');
  await page.getByLabel('SEC filed to').fill('2025-12-31');
  await page.getByRole('button',{name:'Start updated import',exact:true}).click();
  expect(state.received[0]).toEqual({symbol:'NEW',action:'refresh',selection:'range',fromDate:'2025-01-01',toDate:'2025-12-31'});
});
test('a queued import exposes explicit recovery when SEC blocked the shared queue', async ({page}) => {
  await setup(page,{hold:true}); let blocked=true;
  const job=()=>({id,symbol:'NEW',cik:'0000000001',status:'queued',stage:'queued',completed:0,total:1,warnings:[],failures:[],accessBlocked:blocked});
  await page.route(`**/api/v1/sec/jobs/${id}`,route=>route.fulfill({contentType:'application/json',body:JSON.stringify({data:job()})}));
  await page.route(`**/api/v1/sec/jobs/${id}/retry`,route=>{blocked=false;return route.fulfill({contentType:'application/json',body:JSON.stringify({data:job()})});});
  await page.goto(`/companies/NEW?view=sec&job=${id}`);
  await expect(page.getByText(/SEC access is blocked for the queue/)).toBeVisible();
  await page.getByRole('button',{name:'Retry SEC access after diagnosis',exact:true}).click();
  await expect(page.getByText(/SEC access is blocked for the queue/)).toHaveCount(0);
  await expect(page.getByRole('button',{name:'Cancel import',exact:true})).toBeVisible();
});
test('non-JSON server errors are reported as service failures rather than expired sessions', async ({page}) => {
  await setup(page);
  await page.route('**/api/v1/sec/jobs',route=>route.fulfill({status:500,contentType:'text/plain',body:'Internal Server Error'}));
  await page.goto('/companies/NEW?view=sec');
  await page.getByRole('button',{name:'Scrape NEW from SEC',exact:true}).click();
  await expect(page.getByText('The SEC service returned an unexpected response (HTTP 500). Please retry.')).toBeVisible();
  await expect(page.getByText('Your session has expired. Reload to sign in again.')).toHaveCount(0);
});
test('real unauthorized API responses still request sign-in', async ({page}) => {
  await setup(page);
  await page.route('**/api/v1/sec/jobs',route=>route.fulfill({status:401,contentType:'text/html',body:'Sign in'}));
  await page.goto('/companies/NEW?view=sec');
  await page.getByRole('button',{name:'Scrape NEW from SEC',exact:true}).click();
  await expect(page.getByText('Your session has expired. Reload to sign in again.')).toBeVisible();
});
test('completion replaces a delayed initial missing-company response', async ({page}) => {
  await setup(page); let first=true; let release!:()=>void;
  const delayed=new Promise<void>(resolve=>{release=resolve;});
  await page.route('**/api/v1/sec/companies/NEW',async route=>{
    if(first){first=false;await delayed;try{await route.fulfill({status:404,contentType:'application/json',body:JSON.stringify({error:{message:'Not imported'}})});}catch{/* Initial fetch was cancelled. */}}
    else await route.fulfill({contentType:'application/json',body:JSON.stringify({data:company})});
  });
  try{
    await page.goto(`/companies/NEW?view=sec&job=${id}`);
    await expect(page.getByText('1 / 1 filings completed')).toBeVisible({timeout:15000});
    release();
    await expect(page.getByRole('heading',{name:'New SEC Company NEW'})).toBeVisible();
    await expect(page.getByRole('table',{name:'SEC numeric facts and segment dimensions'})).toBeVisible();
  }finally{release();}
});
