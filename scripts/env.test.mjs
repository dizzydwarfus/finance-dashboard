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
test('production uses only its file and overrides stale shell values', t => {
  const root = fixture(t, { '.env.staging': 'CLOUDFLARE_API_TOKEN=unused-token', '.env.production': 'CLOUDFLARE_API_TOKEN=production-token', '.env': 'CLOUDFLARE_HOSTNAME=wrong.example.com' });
  const env = { CLOUDFLARE_API_TOKEN: 'stale-token', CLOUDFLARE_HOSTNAME: 'wrong.example.com' };
  const loaded = loadEnvironment('production', { root, env });
  assert.equal(loaded.CLOUDFLARE_API_TOKEN, 'production-token');
  assert.equal(loaded.CLOUDFLARE_HOSTNAME, undefined);
  assert.throws(() => loadEnvironment('staging', { root, env }), /local or production/);
});
test('missing production file fails instead of using other files or exported credentials', t => {
  const root = fixture(t, { '.env.staging': 'CLOUDFLARE_API_TOKEN=unused-token', '.env': 'CLOUDFLARE_API_TOKEN=unused-token' });
  assert.throws(() => loadEnvironment('production', { root, env: { CLOUDFLARE_API_TOKEN: 'exported-token' } }), /Missing .env.production/);
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
  const root = fixture(t, { '.env.production': "MONGODB_URI='mongodb://user:p%24ss@host/db?x=1&y=2#fragment'" });
  assert.equal(loadEnvironment('production', { root, env: {} }).MONGODB_URI, 'mongodb://user:p%24ss@host/db?x=1&y=2#fragment');
});
test('production workflow Secrets use the canonical deployment keys', () => {
  const workflow = readFileSync(join(projectRoot, '.github/workflows/ci.yml'), 'utf8');
  const bindings = [...workflow.matchAll(/^      ([A-Z_]+): \$\{\{ secrets\.([A-Z_]+) \}\}/gm)];
  assert.deepEqual(bindings.map(match => match[1]).sort(), [...deploymentKeys].sort());
  for (const match of bindings) assert.equal(match[1], match[2]);
  assert.ok(!workflow.includes('vars.'));
});
test('preflight validates injected Secrets without invoking Wrangler or printing values', () => {
  const env = Object.fromEntries(deploymentKeys.map(key => [key, 'private-value']));
  Object.assign(env, { CI: 'true', ACCESS_TEAM_DOMAIN: 'example.cloudflareaccess.com', CLOUDFLARE_HOSTNAME: 'dashboard.example.com', SEC_MONGODB_DATABASE: 'SECIngestion', SEC_MONGODB_URI: 'mongodb://writer:private-value@localhost/SECIngestion', SEC_USER_AGENT: 'Ledger contact@ledger.invalid' });
  const result = spawnSync(process.execPath, [join(projectRoot, 'scripts/deploy.mjs'), '--check'], { env, encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr);
  assert.ok(!result.stdout.includes('private-value'));
});
test('preflight fails on absent or partial Secrets instead of skipping production', () => {
  const run = env => spawnSync(process.execPath, [join(projectRoot, 'scripts/deploy.mjs'), '--check'], { env: { CI: 'true', ...env }, encoding: 'utf8' });
  assert.notEqual(run({}).status, 0);
  const partial = run({ CLOUDFLARE_API_TOKEN: 'private-value' });
  assert.notEqual(partial.status, 0);
  assert.ok(!partial.stderr.includes('private-value'));
});
test('deployment rejects environment selection and invalid rollback versions', () => {
  for (const args of [['staging'], ['production'], ['--check', '--optional'], ['--rollback'], ['--rollback', '--check'], ['--rollback', 'not-a-version']]) {
    const result = spawnSync(process.execPath, [join(projectRoot, 'scripts/deploy.mjs'), ...args], { env: { CI: 'true' }, encoding: 'utf8' });
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /Usage:/);
  }
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
