// Run from any directory. Live secrets travel only through stdin to Wrangler.
import { readFile, writeFile, unlink, readdir } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
import { loadEnvironment, deploymentKeys, requireKeys } from './env.mjs';
import { createRedactor } from './redact.mjs';
import { createHash } from 'node:crypto';
import { ingestionExists, setMaintenance } from './ingestion-deployment.mjs';
const root = fileURLToPath(new URL('../', import.meta.url));
const infra = resolve(root, 'infra');
const args = process.argv.slice(2);
const checking = args.length === 1 && args[0] === '--check';
const dryRun = args.length === 1 && args[0] === '--dry-run';
const rollbackSEC = args[0] === '--rollback-sec';
const rollback = args.length === 2 && ['--rollback', '--rollback-sec'].includes(args[0]) && /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(args[1]) ? args[1] : undefined;
if (args.length && !checking && !dryRun && !rollback) throw new Error('Usage: node scripts/deploy.mjs [--check|--dry-run|--rollback VERSION_ID|--rollback-sec VERSION_ID]');
const env = loadEnvironment('production');
const redact = createRedactor(env);
const required = ['ACCESS_TEAM_DOMAIN', 'ACCESS_AUD', 'CLOUDFLARE_HOSTNAME', 'CLOUDFLARE_ACCOUNT_ID'];
if (!dryRun) required.push(...deploymentKeys);
requireKeys(env, rollback ? ['CLOUDFLARE_API_TOKEN', 'CLOUDFLARE_ACCOUNT_ID', ...(rollbackSEC ? ['CLOUDFLARE_HOSTNAME', 'CF_ACCESS_CLIENT_ID', 'CF_ACCESS_CLIENT_SECRET'] : [])] : [...new Set(required)]);
if (!rollback) {
  if (!/^[a-z0-9-]+\.cloudflareaccess\.com$/.test(env.ACCESS_TEAM_DOMAIN)) throw new Error('Invalid Access team domain');
  if (!/^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}$/.test(env.CLOUDFLARE_HOSTNAME)) throw new Error('Supply a hostname without a scheme, path, or wildcard');
}
if (!rollback && !dryRun) {
  if (env.SEC_MONGODB_DATABASE !== 'SECIngestion') throw new Error('SEC_MONGODB_DATABASE must be SECIngestion');
  if (!/^mongodb(?:\+srv)?:\/\//.test(env.SEC_MONGODB_URI)) throw new Error('Invalid SEC_MONGODB_URI');
  if (!/^[^\r\n]{3,160}\s[<(]?[^\s@<>()]+@[^\s@<>()]+\.[A-Za-z]{2,}[>)]?$/.test(env.SEC_USER_AGENT) || /example\.(com|org)|placeholder|apicaller|John Doe/i.test(env.SEC_USER_AGENT)) throw new Error('SEC_USER_AGENT needs your application name and real monitored contact email');
}
if (checking) {
  console.log('Production configuration is complete.');
  process.exit(0);
}
const config = JSON.parse(await readFile(resolve(infra, 'wrangler.jsonc'), 'utf8'));
config.account_id = env.CLOUDFLARE_ACCOUNT_ID;
if (!rollback) {
  Object.assign(config.env.production.vars, { ACCESS_TEAM_DOMAIN: env.ACCESS_TEAM_DOMAIN, ACCESS_AUD: env.ACCESS_AUD, MONGODB_DATABASE: env.MONGODB_DATABASE || 'FinanceApp', CLOUDFLARE_HOSTNAME: env.CLOUDFLARE_HOSTNAME });
  config.env.production.routes = [{ pattern: env.CLOUDFLARE_HOSTNAME, custom_domain: true }];
}
const configPath = resolve(infra, `.wrangler.deploy.production.${process.pid}.json`);
function run(args, input) {
  return new Promise((accept, reject) => {
    const child = spawn(process.execPath, [resolve(infra, 'node_modules/wrangler/bin/wrangler.js'), ...args], { cwd: infra, env, stdio: [input ? 'pipe' : 'ignore', 'pipe', 'pipe'] });
    let stdout = '', stderr = '';
    child.stdout.setEncoding('utf8'); child.stderr.setEncoding('utf8');
    child.stdout.on('data', chunk => { stdout += chunk; });
    child.stderr.on('data', chunk => { stderr += chunk; });
    child.on('error', () => reject(new Error('Could not launch Wrangler')));
    child.on('close', code => {
      process.stdout.write(redact(stdout)); process.stderr.write(redact(stderr));
      code === 0 ? accept() : reject(new Error(`Wrangler exited with status ${code}`));
    });
    if (input) { child.stdin.on('error', () => {}); child.stdin.end(input); }
  });
}
const secConfig = JSON.parse(await readFile(resolve(infra, 'wrangler.ingestion.jsonc'), 'utf8'));
secConfig.account_id = env.CLOUDFLARE_ACCOUNT_ID;
const secConfigPath = resolve(infra, `.wrangler.sec.production.${process.pid}.json`);
async function parserHash(directory, hash = createHash('sha256')) {
  for (const entry of (await readdir(directory, { withFileTypes: true })).sort((a,b) => a.name.localeCompare(b.name))) {
    const path = resolve(directory, entry.name);
    if (entry.isDirectory() && entry.name !== '__pycache__') await parserHash(path, hash);
    else if (entry.isFile() && (/\.(py|json)$/.test(entry.name) || entry.name === 'LICENSE')) hash.update(entry.name).update(await readFile(path));
  }
  return hash;
}
const hash = await parserHash(resolve(root, 'ingestion/sec_ingestion'));
hash.update(await readFile(resolve(root, 'ingestion/requirements.lock')));
Object.assign(secConfig.env.production.vars, { SEC_MONGODB_DATABASE: 'SECIngestion', SEC_PARSER_VERSION: `sec-${hash.digest('hex').slice(0,20)}` });
let locked = false;
try {
  await writeFile(configPath, JSON.stringify(config, null, 2));
  await writeFile(secConfigPath, JSON.stringify(secConfig, null, 2));
  if (!dryRun && (!rollback || rollbackSEC) && await ingestionExists(env)) {
    await setMaintenance(env, true); locked = true;
  }
  if (rollback) {
    await run(['rollback', rollback, '--config', rollbackSEC ? secConfigPath : configPath, '--env', 'production', '--yes', '--message', 'Restore known-good production version']);
    console.log(`${rollbackSEC ? 'SEC ingestion' : 'Dashboard'} rollback completed. Collected SEC data was preserved.`);
  } else {
    await run(['deploy', '--config', secConfigPath, '--env', 'production', ...(dryRun ? ['--dry-run'] : [])]);
    if (!dryRun) await run(['secret', 'bulk', '--config', secConfigPath, '--env', 'production'], JSON.stringify({ SEC_MONGODB_URI: env.SEC_MONGODB_URI, SEC_USER_AGENT: env.SEC_USER_AGENT }));
    await run(['deploy', '--config', configPath, '--env', 'production', ...(dryRun ? ['--dry-run'] : [])]);
    if (!dryRun) {
      await run(['secret', 'bulk', '--config', configPath, '--env', 'production'], JSON.stringify({ MONGODB_URI: env.MONGODB_URI }));
      console.log('Production deployment completed. Run node scripts/smoke.mjs.');
    }
  }
} finally {
  try { if (locked) await setMaintenance(env, false); }
  finally { await Promise.all([unlink(configPath).catch(() => {}), unlink(secConfigPath).catch(() => {})]); }
}
