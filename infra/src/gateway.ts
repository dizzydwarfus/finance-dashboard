import { verifyAccess, type AccessConfig } from './auth';
export interface Env extends AccessConfig {
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
  if (!['GET', 'HEAD'].includes(request.method)) return Response.json({ error: { code: 'method_not_allowed', message: 'This application is read-only.' } }, { status: 405, headers: { Allow: 'GET, HEAD' } });
  const target = routeTarget(new URL(request.url).pathname);
  try {
    // Fixed names enforce one instance per service; no user-controlled instance allocation.
    const namespace = env[target];
    const forwarded = new Request(request);
    for (const header of ['Cookie', 'Authorization', 'Cf-Access-Jwt-Assertion', 'Cf-Access-Authenticated-User-Email', 'CF-Access-Client-Id', 'CF-Access-Client-Secret']) forwarded.headers.delete(header);
    const response = await namespace.get(namespace.idFromName('singleton')).fetch(forwarded);
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
