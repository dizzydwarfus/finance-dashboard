export function secMethod(path: string): 'GET' | 'POST' | undefined {
  if (/^\/api\/v1\/sec\/(?:companies(?:\/[A-Za-z0-9.-]+(?:\/(?:filings|company-facts))?)?|filings\/[0-9-]+\/facts|jobs\/[a-f0-9-]+)$/.test(path)) return 'GET';
  if (path === '/api/v1/sec/jobs' || path === '/api/v1/sec/maintenance' || /^\/api\/v1\/sec\/jobs\/[a-f0-9-]+\/(?:cancel|retry)$/.test(path)) return 'POST';
  return undefined;
}
