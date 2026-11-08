import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { readFileSync } from 'node:fs';
import { parseEnv } from 'node:util';
function proxyTarget(key = 'API_PROXY_TARGET', defaultTarget = 'http://127.0.0.1:8080') {
  const fallback = process.env[key] || defaultTarget;
  if (process.env.CI === 'true') return fallback;
  for (const name of ['.env.local', '.env']) {
    try {
      const values = parseEnv(readFileSync(new URL(`../${name}`, import.meta.url), 'utf8'));
      return values[key] || fallback;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw new Error(`Cannot read local proxy setting from ${name}`);
    }
  }
  return fallback;
}
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy: { '/api/v1/sec': proxyTarget('SEC_PROXY_TARGET', 'http://127.0.0.1:8081'), '/api': proxyTarget() } },
});
