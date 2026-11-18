import { test, expect } from '@playwright/test';

const fixtureURL=process.env.FIXTURE_VITE==='true'?'http://127.0.0.1:5173':'http://127.0.0.1:3000';

test('local containers serve SEC data and exports without starting an import', async ({ page }) => {
  test.skip(process.env.SEC_LIVE_TEST !== 'true','Requires the Compose SEC fixture database');
  await page.goto(fixtureURL+'/companies/DEMO');
  await expect(page.getByRole('heading', { name: 'Apple filing fixture DEMO' })).toBeVisible();
  await expect(page.getByText('478,834,000,000 USD')).toBeVisible();
  await page.getByRole('tab', { name: 'Statements' }).click();
  await expect(page.getByRole('link', { name: 'Download statement CSV' })).toBeVisible();
  await page.getByRole('tab', { name: 'Filings' }).click();
  await expect(page.getByRole('table', { name: 'SEC numeric facts and segment dimensions' })).toBeVisible();
});

test('an analyst opens reported data, exports a pivot and persists a calculated model',async({page})=>{
  test.skip(process.env.SEC_LIVE_TEST!=='true','Disposable local fixture only');
  await page.goto(fixtureURL+'/companies/DEMO?view=explore');
  await expect(page.getByRole('heading',{name:'Apple filing fixture DEMO'})).toBeVisible();
  const breakdown=page.getByLabel('Reported breakdown');
  await expect(breakdown.locator('option')).toHaveCount(2);
  await breakdown.selectOption({index:1});
  await expect(page.getByRole('rowheader',{name:'GreaterChinaSegmentMember'})).toBeVisible();
  const download=page.waitForEvent('download');
  await page.getByRole('link',{name:'Download pivot CSV'}).click();
  expect((await download).suggestedFilename()).toBe('DEMO-pivot.csv');
  await page.getByRole('tab',{name:'Compare'}).click();
  await page.getByRole('button',{name:'Add SIC peer PEER'}).click();
  await expect(page.getByText('No annual coverage')).toBeVisible();
  await page.getByRole('tab',{name:'Model'}).click();
  await page.getByRole('button',{name:'Use selected baseline'}).click();
  for(const [key,value] of Object.entries({'Opening working capital / baseline revenue':'10','WACC':'10','Terminal growth':'0','Revenue growth':'0','Operating margin':'20','Tax on operating income':'25','D&A / revenue':'2','Capex / revenue':'4','Non-cash working capital / revenue':'10'})){
    const label=['WACC','Terminal growth','Opening working capital / baseline revenue'].includes(key)?key:key+' year 1';
    await page.getByRole('spinbutton',{name:label,exact:true}).fill(value);
  }
  await page.getByRole('button',{name:'Apply Year 1 to all years'}).click();
  await page.getByRole('button',{name:'Evaluate scenarios'}).click();
  await expect(page.getByText('622,484,200,000.0000').first()).toBeVisible();
  const title='Fixture model '+Date.now();await page.getByRole('textbox',{name:'Name',exact:true}).fill(title);
  await page.getByRole('button',{name:'Save',exact:true}).click();await expect(page.getByText('Saved revision 1.')).toBeVisible();
  await page.reload();await page.getByLabel('Open saved item').selectOption({label:title+' · v1'});
  await expect(page.getByText('622,484,200,000.0000').first()).toBeVisible();
  page.once('dialog',dialog=>dialog.accept());await page.getByRole('button',{name:'Delete',exact:true}).click();
  await expect(page.getByText('Deleted saved item.')).toBeVisible();
});
