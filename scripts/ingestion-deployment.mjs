import { setTimeout as sleep } from 'node:timers/promises';

const releaseDelays = [2_000, 4_000, 8_000, 16_000, 30_000];
const retryableReleaseStatuses = new Set([401, 429, 502, 503, 504]);

// Maintenance and admission share a MongoDB lease: no job can enter between the check and replacement.
export async function ingestionExists(env, fetcher = fetch) {
  const response = await fetcher(`https://api.cloudflare.com/client/v4/accounts/${env.CLOUDFLARE_ACCOUNT_ID}/workers/scripts/finance-dashboard-production/settings`, {
    headers: { Authorization: `Bearer ${env.CLOUDFLARE_API_TOKEN}` }, signal: AbortSignal.timeout(15000), redirect: 'error',
  });
  if (response.status === 404) return false; // First deployment has no public job entry point.
  if (!response.ok) throw new Error(`Cannot inspect deployment bindings (HTTP ${response.status})`);
  const data = await response.json();
  if (!data.success) throw new Error('Cannot inspect deployment bindings');
  return !!data.result?.bindings?.some(binding => binding.name === 'SEC_INGESTION');
}
export async function setMaintenance(env, enabled, fetcher = fetch, wait = sleep) {
  const origin = `https://${env.CLOUDFLARE_HOSTNAME}`;
  const action = enabled ? 'acquire' : 'release';
  const delays = enabled ? [] : releaseDelays;
  for (let attempt = 0; ; attempt++) {
    let response;
    try {
      response = await fetcher(`${origin}/api/v1/sec/maintenance`, {
        method: 'POST', headers: { Origin: origin, 'Content-Type': 'application/json',
          'CF-Access-Client-Id': env.CF_ACCESS_CLIENT_ID, 'CF-Access-Client-Secret': env.CF_ACCESS_CLIENT_SECRET },
        body: JSON.stringify({ enabled }), redirect: 'manual', signal: AbortSignal.timeout(40_000),
      });
    } catch {
      if (attempt >= delays.length) throw new Error(`Cannot ${action} SEC deployment lock (request failed)`);
      await wait(delays[attempt]);
      continue;
    }
    // Releasing the lock sets a boolean and can be repeated while the new gateway propagates.
    if (attempt < delays.length && retryableReleaseStatuses.has(response.status)) {
      await response.body?.cancel();
      await wait(delays[attempt]);
      continue;
    }
    if (enabled && response.status === 409) throw new Error('SEC imports are queued or running. Finish or cancel them before replacing the scraper.');
    if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) throw new Error(`Cannot ${action} SEC deployment lock (HTTP ${response.status})`);
    const data = await response.json();
    if (data.data?.maintenance !== enabled) throw new Error('SEC deployment lock was not confirmed');
    return;
  }
}
