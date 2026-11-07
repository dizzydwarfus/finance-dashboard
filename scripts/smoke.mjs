// Access service token values stay in request headers, never command arguments or output.
import { loadEnvironment, requireKeys } from './env.mjs';
const stage = process.argv[2];
if (!['staging', 'production'].includes(stage)) throw new Error('Usage: node scripts/smoke.mjs staging|production');
const env = loadEnvironment(stage);
requireKeys(env, ['CLOUDFLARE_HOSTNAME', 'CF_ACCESS_CLIENT_ID', 'CF_ACCESS_CLIENT_SECRET']);
if (!/^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}$/.test(env.CLOUDFLARE_HOSTNAME)) throw new Error('Invalid deployment hostname');
const origin = `https://${env.CLOUDFLARE_HOSTNAME}`;
const headers = { 'CF-Access-Client-Id': env.CF_ACCESS_CLIENT_ID, 'CF-Access-Client-Secret': env.CF_ACCESS_CLIENT_SECRET };
const unauthenticated = await fetch(`${origin}/api/v1/tickers`, { redirect: 'manual' });
if (![302, 303, 401, 403].includes(unauthenticated.status)) throw new Error('Unauthenticated endpoint is not protected');
for (const path of ['/', '/healthz', '/readyz', '/api/v1/tickers']) {
  const result = await fetch(`${origin}${path}`, { headers, redirect: 'manual', signal: AbortSignal.timeout(60_000) });
  if (!result.ok) throw new Error(`Smoke test failed: ${path} (${result.status})`);
  if (path.startsWith('/api/')) { const body = await result.json(); if (!Array.isArray(body.data) || !body.data.length) throw new Error('Expected existing ticker data'); }
  console.log(`PASS ${path}`);
}
