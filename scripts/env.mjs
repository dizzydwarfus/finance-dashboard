import { readFileSync } from 'node:fs';
import { parseEnv } from 'node:util';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
export const projectRoot = fileURLToPath(new URL('../', import.meta.url));
export const deploymentKeys = [
  'CLOUDFLARE_API_TOKEN', 'CLOUDFLARE_ACCOUNT_ID', 'CLOUDFLARE_HOSTNAME',
  'ACCESS_TEAM_DOMAIN', 'ACCESS_AUD', 'MONGODB_URI', 'MONGODB_DATABASE',
  'CF_ACCESS_CLIENT_ID', 'CF_ACCESS_CLIENT_SECRET',
];
const localKeys = ['MONGODB_URI', 'MONGODB_DATABASE', 'LISTEN_ADDR', 'API_PROXY_TARGET'];
// Local files override stale exported credentials. CI uses injected Secrets exclusively.
// Production never falls back to local files or exported deployment credentials.
export function loadEnvironment(stage, { root = projectRoot, env = process.env } = {}) {
  if (!['local', 'production'].includes(stage)) throw new Error('Environment must be local or production');
  const result = { ...env };
  if (env.CI === 'true') return result;
  const candidates = stage === 'local' ? ['.env.local', '.env'] : [`.env.${stage}`];
  for (const name of candidates) {
    let contents;
    try { contents = readFileSync(resolve(root, name), 'utf8'); }
    catch (error) { if (error.code === 'ENOENT') continue; throw new Error(`Cannot read ${name}`); }
    let parsed;
    try { parsed = parseEnv(contents); } catch { throw new Error(`Cannot parse ${name}`); }
    for (const key of stage === 'local' ? localKeys : deploymentKeys) {
      if (Object.hasOwn(parsed, key)) result[key] = parsed[key];
      else if (stage !== 'local') delete result[key];
    }
    return result;
  }
  if (stage !== 'local') throw new Error('Missing .env.production; see docs/deployment.md');
  return result;
}
export function requireKeys(env, keys) {
  const missing = keys.filter(key => !env[key]);
  if (missing.length) throw new Error(`Missing ${missing.join(', ')}; see docs/deployment.md`);
}
