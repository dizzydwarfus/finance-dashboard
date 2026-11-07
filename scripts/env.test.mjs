import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, rmSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { loadEnvironment, deploymentKeys, projectRoot } from './env.mjs';
import { createRedactor } from './redact.mjs';
function fixture(t, files) {
  const root = mkdtempSync(join(tmpdir(), 'finance-env-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  for (const [file, contents] of Object.entries(files)) writeFileSync(join(root, file), contents);
  return root;
}
test('each stage uses only its matching file and overrides stale shell values', t => {
  const root = fixture(t, { '.env.staging': "CLOUDFLARE_API_TOKEN='staging-token'\nMONGODB_DATABASE=StagingFinance", '.env.production': 'CLOUDFLARE_API_TOKEN=production-token', '.env': 'CLOUDFLARE_HOSTNAME=wrong.example.com' });
  const env = { CLOUDFLARE_API_TOKEN: 'stale-token', CLOUDFLARE_HOSTNAME: 'wrong-production.example.com' };
  assert.equal(loadEnvironment('staging', { root, env }).CLOUDFLARE_API_TOKEN, 'staging-token');
  assert.equal(loadEnvironment('production', { root, env }).CLOUDFLARE_API_TOKEN, 'production-token');
  assert.equal(loadEnvironment('staging', { root, env }).CLOUDFLARE_HOSTNAME, undefined);
});
test('missing cloud file fails instead of using exported credentials', t => {
  const root = fixture(t, { '.env.production': 'CLOUDFLARE_API_TOKEN=production-token' });
  assert.throws(() => loadEnvironment('staging', { root, env: { CLOUDFLARE_API_TOKEN: 'exported-token' } }), /Missing .env.staging/);
});
test('local prefers .env.local and falls back to .env without loading cloud credentials', t => {
  const root = fixture(t, { '.env.local': "MONGODB_URI='mongodb://local'\nAPI_PROXY_TARGET=http://127.0.0.1:8081\nCLOUDFLARE_API_TOKEN=ignored", '.env': 'MONGODB_URI=mongodb://fallback' });
  assert.equal(loadEnvironment('local', { root, env: {} }).MONGODB_URI, 'mongodb://local');
  assert.equal(loadEnvironment('local', { root, env: {} }).CLOUDFLARE_API_TOKEN, undefined);
  rmSync(join(root, '.env.local'));
  assert.equal(loadEnvironment('local', { root, env: {} }).MONGODB_URI, 'mongodb://fallback');
});
test('CI ignores dotenv files and preserves exact injected values', t => {
  const root = fixture(t, { '.env.production': 'CLOUDFLARE_API_TOKEN=wrong-token' });
  assert.equal(loadEnvironment('production', { root, env: { CI: 'true', CLOUDFLARE_API_TOKEN: 'github-secret' } }).CLOUDFLARE_API_TOKEN, 'github-secret');
});
test('dotenv quoting preserves URI punctuation literally', t => {
  const root = fixture(t, { '.env.staging': "MONGODB_URI='mongodb://user:p%24ss@host/db?x=1&y=2#fragment'" });
  assert.equal(loadEnvironment('staging', { root, env: {} }).MONGODB_URI, 'mongodb://user:p%24ss@host/db?x=1&y=2#fragment');
});
test('workflow Secrets use the canonical nine keys', () => {
  for (const stage of ['staging', 'production']) {
    const workflow = readFileSync(join(projectRoot, '.github/workflows', stage === 'staging' ? 'ci.yml' : 'promote.yml'), 'utf8');
    const bindings = [...workflow.matchAll(/^      ([A-Z_]+): \$\{\{ secrets\.([A-Z_]+) \}\}/gm)];
    assert.deepEqual(bindings.map(match => match[1]).sort(), [...deploymentKeys].sort());
    for (const match of bindings) assert.equal(match[1], match[2]);
    assert.ok(!workflow.includes('vars.'));
  }
});
test('preflight can validate injected Secrets without invoking Wrangler or printing values', () => {
  const env = Object.fromEntries(deploymentKeys.map(key => [key, 'private-value']));
  Object.assign(env, { CI: 'true', ACCESS_TEAM_DOMAIN: 'example.cloudflareaccess.com', CLOUDFLARE_HOSTNAME: 'staging.example.com' });
  const result = spawnSync(process.execPath, [join(projectRoot, 'scripts/deploy.mjs'), 'staging', '--check'], { env, encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr);
  assert.ok(!result.stdout.includes('private-value'));
});
test('optional preflight skips only when all Secrets are absent; partial config fails', () => {
  const run = env => spawnSync(process.execPath, [join(projectRoot, 'scripts/deploy.mjs'), 'staging', '--check', '--optional'], { env: { CI: 'true', ...env }, encoding: 'utf8' });
  assert.equal(run({}).status, 0);
  const partial = run({ CLOUDFLARE_API_TOKEN: 'private-value' });
  assert.notEqual(partial.status, 0);
  assert.ok(!partial.stderr.includes('private-value'));
});

test('deployment log redaction masks credentials, URI fragments, and escaped values', () => {
  const env = { CLOUDFLARE_API_TOKEN: 'private-token', ACCESS_AUD: 'private-audience', MONGODB_URI: 'mongodb://private-user:p%40ssword@db.example/FinanceApp', CF_ACCESS_CLIENT_SECRET: 'private-secret' };
  const redact = createRedactor(env);
  const output = redact(['private-', 'token private-audience private-secret p@ssword p%40ssword private-user ', env.MONGODB_URI].join(''));
  for (const value of [...Object.values(env), 'p@ssword', 'p%40ssword', 'private-user']) assert.ok(!output.includes(value));
  assert.ok(output.includes('[REDACTED]'));
});

test('redaction also masks Wrangler abbreviated identifiers', () => {
  const secret = 'synthetic-long-application-audience-identifier';
  const redact = createRedactor({ ACCESS_AUD: secret });
  for (const length of [8, 16, 32, 36]) {
    for (const ellipsis of ['...', '…']) assert.equal(redact(secret.slice(0, length) + ellipsis), '[REDACTED]');
  }
});
