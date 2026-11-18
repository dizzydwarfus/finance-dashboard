// Access service token values stay in request headers.
import { loadEnvironment, requireKeys } from './env.mjs';
const env = loadEnvironment('production');
requireKeys(env, ['CLOUDFLARE_HOSTNAME', 'CF_ACCESS_CLIENT_ID', 'CF_ACCESS_CLIENT_SECRET']);
if (!/^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}$/.test(env.CLOUDFLARE_HOSTNAME)) throw new Error('Invalid deployment hostname');
const origin = `https://${env.CLOUDFLARE_HOSTNAME}`;
const headers = { 'CF-Access-Client-Id': env.CF_ACCESS_CLIENT_ID, 'CF-Access-Client-Secret': env.CF_ACCESS_CLIENT_SECRET };

async function get(path) {
  const result = await fetch(origin + path, { headers, redirect: 'manual', signal: AbortSignal.timeout(60_000) });
  if (!result.ok) throw new Error(`Smoke test failed: ${path} (${result.status})`);
  console.log(`PASS ${path}`);
  return result;
}
const deniedRead = await fetch(origin + '/api/v1/sec/companies', { redirect: 'manual' });
const deniedPost = await fetch(origin + '/api/v1/sec/jobs', {
  method: 'POST', headers: { Origin: origin, 'Content-Type': 'application/json' }, body: '{}', redirect: 'manual',
});
if (![deniedRead, deniedPost].every(result => [302, 303, 401, 403].includes(result.status))) throw new Error('Cloudflare Access protection failed');
for (const path of ['/', '/healthz', '/readyz']) await (await get(path)).body?.cancel();
const { data: issuers } = await (await get('/api/v1/sec/companies?limit=100')).json();
if (!Array.isArray(issuers)) throw new Error('Expected SEC company results');
const issuer = issuers.find(row => row.symbol === 'AAPL') || issuers[0];
if (issuer) {
  const symbol = encodeURIComponent(issuer.symbol);
  const [{ data: metrics }, { data: filings }] = await Promise.all([
    get(`/api/v1/companies/${symbol}/metrics`).then(result => result.json()),
    get(`/api/v1/sec/companies/${symbol}/filings`).then(result => result.json()),
  ]);
  if (!Array.isArray(metrics?.rows) || !Array.isArray(filings) || !filings.length) throw new Error('Expected financial results and published filings');
  const csv = await get(`/api/v1/companies/${symbol}/statements/income?format=csv`);
  if (!csv.headers.get('content-type')?.includes('text/csv')) throw new Error('Expected statement CSV');
  if (!(await csv.text()).startsWith('field,period,')) throw new Error('Invalid statement CSV');
  const accr = encodeURIComponent(filings[0].accession);
  await (await get(`/api/v1/sec/filings/${accr}/facts?limit=1`)).body?.cancel();
} else {
  console.log('No imported issuer is available for statement and filing checks.');
}
