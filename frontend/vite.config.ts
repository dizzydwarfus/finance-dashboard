import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { readFileSync } from 'node:fs';
import { parseEnv } from 'node:util';
function proxyTarget() {
  const fallback = process.env.API_PROXY_TARGET || 'http://127.0.0.1:8080';
  if (process.env.CI === 'true') return fallback;
  for (const name of ['.env.local', '.env']) {
    try {
      const values = parseEnv(readFileSync(new URL(`../${name}`, import.meta.url), 'utf8'));
      return values.API_PROXY_TARGET || fallback;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw new Error(`Cannot read local proxy setting from ${name}`);
    }
  }
  return fallback;
}
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy: { '/api': proxyTarget() } },
});
