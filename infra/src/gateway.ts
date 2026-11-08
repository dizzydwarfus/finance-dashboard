import { secMethod } from './sec-routes';
import { verifyAccess, type AccessConfig } from './auth';
export interface Env extends AccessConfig {
  SEC_INGESTION?: Fetcher;
  CLOUDFLARE_HOSTNAME?: string;
  API: DurableObjectNamespace;
  WEB: DurableObjectNamespace;
  MONGODB_URI: string;
  MONGODB_DATABASE: string;
}
export function routeTarget(path: string): 'API' | 'WEB' {
  return path === '/api' || path.startsWith('/api/') || path === '/healthz' || path === '/readyz' ? 'API' : 'WEB';
}
export async function gateway(request: Request, env: Env, authenticate = verifyAccess): Promise<Response> {
  try { await authenticate(request, env); }
  catch { return Response.json({ error: { code: 'unauthorized', message: 'Sign in through Cloudflare Access to continue.' } }, { status: 401, headers: { 'Cache-Control': 'no-store' } }); }
  const path = new URL(request.url).pathname;
  const sec = path === '/api/v1/sec' || path.startsWith('/api/v1/sec/');
  if (sec) {
    const expected = secMethod(path);
    if (!expected || request.method !== expected) return Response.json({ error: { code: 'method_not_allowed', message: 'Unsupported SEC operation.' } }, { status: 405 });
    if (expected === 'POST') {
      const configuredOrigin = env.CLOUDFLARE_HOSTNAME ? `https://${env.CLOUDFLARE_HOSTNAME}` : new URL(request.url).origin;
      if (request.headers.get('Origin') !== configuredOrigin) return Response.json({ error: { code: 'invalid_origin', message: 'Use the dashboard to perform this action.' } }, { status: 403 });
      if (request.headers.get('Content-Type')?.split(';')[0].toLowerCase() !== 'application/json') return Response.json({ error: { code: 'invalid_content_type', message: 'Send application/json.' } }, { status: 415 });
      if (Number(request.headers.get('Content-Length')) > 32768) return Response.json({ error: { code: 'request_too_large', message: 'Request exceeds 32 KiB.' } }, { status: 413 });
    }
    if (!env.SEC_INGESTION) return Response.json({ error: { code: 'ingestion_not_configured', message: 'SEC ingestion is not configured.' } }, { status: 503 });
  }
  if (!sec && !['GET', 'HEAD'].includes(request.method)) return Response.json({ error: { code: 'method_not_allowed', message: 'This application is read-only.' } }, { status: 405, headers: { Allow: 'GET, HEAD' } });
  const target = routeTarget(new URL(request.url).pathname);
  try {
    // Fixed names enforce one instance per service; no user-controlled instance allocation.
    const namespace = env[target];
    const forwarded = new Request(request);
    for (const header of ['Cookie', 'Authorization', 'Cf-Access-Jwt-Assertion', 'Cf-Access-Authenticated-User-Email', 'CF-Access-Client-Id', 'CF-Access-Client-Secret']) forwarded.headers.delete(header);
    const response = sec ? await env.SEC_INGESTION!.fetch(forwarded) : await namespace.get(namespace.idFromName('singleton')).fetch(forwarded);
    const result = new Response(response.body, response);
    result.headers.set('X-Content-Type-Options', 'nosniff');
    result.headers.set('Referrer-Policy', 'strict-origin-when-cross-origin');
    result.headers.set('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'");
    // Authorization happens before routing; private responses are never shared-cache entries.
    result.headers.set('Cache-Control', 'private, no-store');
    return result;
  } catch {
    return Response.json({ error: { code: 'container_unavailable', message: 'The service is starting or temporarily unavailable. Please retry.' } }, { status: 503, headers: { 'Retry-After': '5', 'Cache-Control': 'no-store' } });
  }
}
