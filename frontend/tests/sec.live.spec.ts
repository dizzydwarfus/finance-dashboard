import { test, expect } from '@playwright/test';
test('real container routes show SEC facts and preserve the legacy dashboard', async ({page}) => {
  test.skip(process.env.SEC_LIVE_TEST !== 'true','Requires synthetic SECX fixture and local three-container stack');
  await page.goto('http://127.0.0.1:3000/companies/SECX?view=sec');
  await expect(page.getByRole('heading',{name:'Synthetic SEC issuer SECX',exact:true})).toBeVisible();
  await expect(page.getByRole('table',{name:'SEC numeric facts and segment dimensions'})).toBeVisible();
  await expect(page.getByRole('cell',{name:'123,456,789,012,345,678.00',exact:true})).toBeVisible();
  await page.screenshot({path:'test-results/sec-container-desktop.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
  await page.screenshot({path:'test-results/sec-container-mobile.png',fullPage:true});
  await page.goto('http://127.0.0.1:3000/companies/DEMO');
  await expect(page.getByRole('tab',{name:'Statements',exact:true})).toBeVisible();
});
