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

test('release retries transient Access, startup, and transport errors', async () => {
  const delays = [];
  let attempt = 0;
  await setMaintenance(env, false, async (_url, options) => {
    assert.deepEqual(JSON.parse(options.body), { enabled: false });
    assert.equal(options.headers['CF-Access-Client-Id'], env.CF_ACCESS_CLIENT_ID);
    assert.equal(options.redirect, 'manual');
    switch (++attempt) {
      case 1: return new Response(null, { status: 401 });
      case 2: return new Response(null, { status: 503 });
      case 3: throw new TypeError('fetch failed');
      default: return Response.json({ data: { maintenance: false } });
    }
  }, async delay => { delays.push(delay); });
  assert.equal(attempt, 4);
  assert.deepEqual(delays, [2_000, 4_000, 8_000]);
});

test('release fails after bounded retries and acquisition fails closed immediately', async () => {
  let attempts = 0;
  const unauthorized = async () => {
    attempts++;
    return new Response(null, { status: 401 });
  };
  await assert.rejects(setMaintenance(env, false, unauthorized, async () => {}), /release.*401/);
  assert.equal(attempts, 6);
  attempts = 0;
  await assert.rejects(setMaintenance(env, true, unauthorized, async () => assert.fail('retried acquisition')), /acquire.*401/);
  assert.equal(attempts, 1);
  await assert.rejects(setMaintenance(env, false, async () => new Response(null, { status: 403 }),
    async () => assert.fail('retried forbidden release')), /release.*403/);
});
