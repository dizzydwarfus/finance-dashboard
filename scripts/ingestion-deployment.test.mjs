import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ingestionExists, setMaintenance } from './ingestion-deployment.mjs';
const env = { CLOUDFLARE_ACCOUNT_ID: 'account', CLOUDFLARE_API_TOKEN: 'token', CLOUDFLARE_HOSTNAME: 'ledger.invalid', CF_ACCESS_CLIENT_ID: 'client', CF_ACCESS_CLIENT_SECRET: 'secret' };
test('first deployment has no ingress; existing service binding requires a guard', async () => {
  assert.equal(await ingestionExists(env, async () => new Response(null, {status:404})), false);
  assert.equal(await ingestionExists(env, async () => Response.json({success:true,result:{bindings:[{name:'SEC_INGESTION'}]}})), true);
  await assert.rejects(ingestionExists(env, async () => new Response(null,{status:403})), /inspect deployment/);
});
test('busy, unavailable, and redirected guard checks stop replacement', async () => {
  for (const status of [409,503,302]) await assert.rejects(setMaintenance(env,true,async () => new Response(null,{status})), /imports|lock/);
});
test('guard sends same-origin authenticated JSON without following Access redirects', async () => {
  await setMaintenance(env,true,async (url,options) => {
    assert.equal(url,'https://ledger.invalid/api/v1/sec/maintenance');
    assert.equal(options.headers.Origin,'https://ledger.invalid');
    assert.equal(options.redirect,'manual');
    assert.deepEqual(JSON.parse(options.body),{enabled:true});
    return Response.json({data:{maintenance:true}});
  });
  await assert.rejects(setMaintenance(env,false,async () => Response.json({data:{maintenance:true}})), /not confirmed/);
});
