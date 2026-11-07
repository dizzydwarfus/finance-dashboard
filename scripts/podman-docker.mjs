#!/usr/bin/env node
// Optional local Wrangler adapter. CI and production builds use Docker directly.
import { spawn, spawnSync } from 'node:child_process';
import { mkdirSync, readFileSync, writeFileSync, mkdtempSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';
const args = process.argv.slice(2).filter(arg => arg !== '--load' && !arg.startsWith('--provenance='));
const stateDir = fileURLToPath(new URL('../.local/', import.meta.url));
const cachePath = join(stateDir, 'podman-registry-digests.json');
function cache() { try { return JSON.parse(readFileSync(cachePath, 'utf8')); } catch { return {}; } }
if (args[0] === 'build') args.splice(1, 0, '--format=docker');
if (args[0] === 'push' && args.length === 2) {
  const directory = mkdtempSync(join(tmpdir(), 'finance-registry-push-'));
  const digestFile = join(directory, 'digest');
  try {
    const pushed = spawnSync('podman', ['push', '--format=v2s2', '--retry=5', '--retry-delay=2s', '--digestfile', digestFile, args[1]], { stdio: 'inherit' });
    if (pushed.status !== 0) process.exit(pushed.status ?? 1);
    const digest = readFileSync(digestFile, 'utf8').trim();
    if (!/^sha256:[a-f0-9]{64}$/.test(digest)) throw new Error('Registry returned an invalid image digest');
    mkdirSync(stateDir, { recursive: true });
    const digests = cache(); digests[args[1]] = digest;
    writeFileSync(cachePath, JSON.stringify(digests), { mode: 0o600 });
  } finally { rmSync(directory, { recursive: true, force: true }); }
  process.exit(0);
}
if (args[0] === 'image' && args[1] === 'inspect' && args.includes('{{ json .RepoDigests }}')) {
  const reference = args[2];
  const digest = cache()[reference];
  if (digest) {
    const repository = reference.replace(/:[^/:]+$/, '');
    console.log(JSON.stringify([`${repository}@${digest}`]));
    process.exit(0);
  }
}
const child = spawn('podman', args, { stdio: 'inherit' });
child.on('error', () => process.exit(1));
child.on('exit', code => process.exit(code ?? 1));
