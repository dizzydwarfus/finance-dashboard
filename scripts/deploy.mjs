// Run from any directory. Live secrets travel only through stdin to Wrangler.
import { readFile, writeFile, unlink } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
import { loadEnvironment, deploymentKeys, requireKeys } from './env.mjs';
import { createRedactor } from './redact.mjs';
const root = fileURLToPath(new URL('../', import.meta.url));
const infra = resolve(root, 'infra');
const args = process.argv.slice(2);
const checking = args.length === 1 && args[0] === '--check';
const dryRun = args.length === 1 && args[0] === '--dry-run';
const rollback = args.length === 2 && args[0] === '--rollback' && /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(args[1]) ? args[1] : undefined;
if (args.length && !checking && !dryRun && !rollback) throw new Error('Usage: node scripts/deploy.mjs [--check|--dry-run|--rollback VERSION_ID]');
const env = loadEnvironment('production');
const redact = createRedactor(env);
const required = ['ACCESS_TEAM_DOMAIN', 'ACCESS_AUD', 'CLOUDFLARE_HOSTNAME', 'CLOUDFLARE_ACCOUNT_ID'];
if (!dryRun) required.push(...deploymentKeys);
requireKeys(env, rollback ? ['CLOUDFLARE_API_TOKEN', 'CLOUDFLARE_ACCOUNT_ID'] : [...new Set(required)]);
if (!rollback) {
  if (!/^[a-z0-9-]+\.cloudflareaccess\.com$/.test(env.ACCESS_TEAM_DOMAIN)) throw new Error('Invalid Access team domain');
  if (!/^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}$/.test(env.CLOUDFLARE_HOSTNAME)) throw new Error('Supply a hostname without a scheme, path, or wildcard');
}
if (checking) {
  console.log('Production configuration is complete.');
  process.exit(0);
}
const config = JSON.parse(await readFile(resolve(infra, 'wrangler.jsonc'), 'utf8'));
config.account_id = env.CLOUDFLARE_ACCOUNT_ID;
if (!rollback) {
  Object.assign(config.env.production.vars, { ACCESS_TEAM_DOMAIN: env.ACCESS_TEAM_DOMAIN, ACCESS_AUD: env.ACCESS_AUD, MONGODB_DATABASE: env.MONGODB_DATABASE || 'FinanceApp' });
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
try {
  await writeFile(configPath, JSON.stringify(config, null, 2));
  if (rollback) {
    await run(['rollback', rollback, '--config', configPath, '--env', 'production', '--yes', '--message', 'Restore known-good production version']);
    console.log('Production rollback completed. Run node scripts/smoke.mjs.');
  } else {
    await run(['deploy', '--config', configPath, '--env', 'production', ...(dryRun ? ['--dry-run'] : [])]);
    if (!dryRun) {
      await run(['secret', 'bulk', '--config', configPath, '--env', 'production'], JSON.stringify({ MONGODB_URI: env.MONGODB_URI }));
      console.log(`Deployed https://${env.CLOUDFLARE_HOSTNAME}. Run node scripts/smoke.mjs.`);
    }
  }
} finally { await unlink(configPath).catch(() => {}); }
