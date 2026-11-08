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
export async function setMaintenance(env, enabled, fetcher = fetch) {
  const origin = `https://${env.CLOUDFLARE_HOSTNAME}`;
  const response = await fetcher(`${origin}/api/v1/sec/maintenance`, {
    method: 'POST', headers: { Origin: origin, 'Content-Type': 'application/json',
      'CF-Access-Client-Id': env.CF_ACCESS_CLIENT_ID, 'CF-Access-Client-Secret': env.CF_ACCESS_CLIENT_SECRET },
    body: JSON.stringify({ enabled }), redirect: 'manual', signal: AbortSignal.timeout(40000),
  });
  if (response.status === 409) throw new Error('SEC imports are queued or running. Finish or cancel them before replacing the scraper.');
  if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) throw new Error(`Cannot ${enabled ? 'acquire' : 'release'} SEC deployment lock (HTTP ${response.status}). No unguarded replacement is allowed.`);
  const data = await response.json();
  if (data.data?.maintenance !== enabled) throw new Error('SEC deployment lock was not confirmed');
}
