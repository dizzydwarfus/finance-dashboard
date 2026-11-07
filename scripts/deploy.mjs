// Run from any directory. Live secrets travel only through stdin to Wrangler.
import { readFile, writeFile, unlink, appendFile } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
import { loadEnvironment, deploymentKeys, requireKeys } from './env.mjs';
import { createRedactor } from './redact.mjs';
const root = fileURLToPath(new URL('../', import.meta.url));
const infra = resolve(root, 'infra');
const stage = process.argv[2];
if (!['staging', 'production'].includes(stage)) throw new Error('Usage: node scripts/deploy.mjs staging|production [--dry-run|--check [--optional]]');
const env = loadEnvironment(stage);
const redact = createRedactor(env);
const checking = process.argv.includes('--check');
if (checking && process.argv.includes('--optional') && !deploymentKeys.some(key => env[key])) {
  if (process.env.GITHUB_OUTPUT) await appendFile(process.env.GITHUB_OUTPUT, 'enabled=false\n');
  console.log('Deployment is not configured for this environment; skipping.');
  process.exit(0);
}
const dryRun = process.argv.includes('--dry-run');
const required = ['ACCESS_TEAM_DOMAIN', 'ACCESS_AUD', 'CLOUDFLARE_HOSTNAME', 'CLOUDFLARE_ACCOUNT_ID'];
if (!dryRun) required.push(...deploymentKeys);
requireKeys(env, [...new Set(required)]);
if (!/^[a-z0-9-]+\.cloudflareaccess\.com$/.test(env.ACCESS_TEAM_DOMAIN)) throw new Error('Invalid Access team domain');
if (!/^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}$/.test(env.CLOUDFLARE_HOSTNAME)) throw new Error('Supply a hostname without a scheme, path, or wildcard');
if (checking) {
  if (process.env.GITHUB_OUTPUT) await appendFile(process.env.GITHUB_OUTPUT, 'enabled=true\n');
  console.log(`Configuration for ${stage} is complete.`);
  process.exit(0);
}
const config = JSON.parse(await readFile(resolve(infra, 'wrangler.jsonc'), 'utf8'));
config.account_id = env.CLOUDFLARE_ACCOUNT_ID;
Object.assign(config.env[stage].vars, { ACCESS_TEAM_DOMAIN: env.ACCESS_TEAM_DOMAIN, ACCESS_AUD: env.ACCESS_AUD, MONGODB_DATABASE: env.MONGODB_DATABASE || 'FinanceApp' });
config.env[stage].routes = [{ pattern: env.CLOUDFLARE_HOSTNAME, custom_domain: true }];
const configPath = resolve(infra, `.wrangler.deploy.${stage}.json`);
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
  await run(['deploy', '--config', configPath, '--env', stage, ...(dryRun ? ['--dry-run'] : [])]);
  if (!dryRun) {
    await run(['secret', 'bulk', '--config', configPath, '--env', stage], JSON.stringify({ MONGODB_URI: env.MONGODB_URI }));
    console.log(`Deployed https://${env.CLOUDFLARE_HOSTNAME}. Run the authenticated smoke test before promotion.`);
  }
} finally { await unlink(configPath).catch(() => {}); }
