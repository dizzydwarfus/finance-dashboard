import { secMethod } from './sec-routes';
import { verifyAccess, type AccessConfig } from './auth';
export interface Env extends AccessConfig {
  SEC_INGESTION?: Fetcher;
  CLOUDFLARE_HOSTNAME?: string;
  API: DurableObjectNamespace;
  WEB: DurableObjectNamespace;
  SEC_READ_MONGODB_URI: string;
  SEC_WORKSPACE_MONGODB_URI?: string;
  DASHBOARD_RELEASE?: string;
}
export function routeTarget(path: string): 'API' | 'WEB' {
  return path === '/api' || path.startsWith('/api/') || path === '/healthz' || path === '/readyz' ? 'API' : 'WEB';
}
export async function gateway(request: Request, env: Env, authenticate: (request: Request, env: Env) => Promise<string | void> = verifyAccess): Promise<Response> {
  let owner;
  try { owner = await authenticate(request, env); }
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
  const workspace = path === '/api/v1/workspaces' || /^\/api\/v1\/workspaces\/[a-f0-9]{24}$/.test(path);
  if (workspace && !owner) return Response.json({error:{message:'Sign in to access private work.'}},{status:403});
  const write = path === '/api/v1/workspaces' && request.method === 'POST' ||
    workspace && path !== '/api/v1/workspaces' && ['PUT','DELETE'].includes(request.method) ||
    path === '/api/v1/model/evaluate' && request.method === 'POST';
  if (write) {
    const origin = env.CLOUDFLARE_HOSTNAME ? 'https://' + env.CLOUDFLARE_HOSTNAME : new URL(request.url).origin;
    if (request.headers.get('Origin') !== origin) return Response.json({error:{message:'Use the dashboard for this action.'}},{status:403});
    if (request.method !== 'DELETE' && request.headers.get('Content-Type')?.split(';')[0] !== 'application/json') return Response.json({error:{message:'Send JSON.'}},{status:415});
  }
  if (!sec && !write && !['GET', 'HEAD'].includes(request.method)) return Response.json({ error: { code: 'method_not_allowed', message: 'This application is read-only.' } }, { status: 405, headers: { Allow: 'GET, HEAD' } });
  const target = routeTarget(new URL(request.url).pathname);
  try {
    // Stateless services receive one container per release. The release key comes from deployment.
    const namespace = env[target];
    const forwarded = new Request(request);
    for (const header of ['Cookie', 'Authorization', 'Cf-Access-Jwt-Assertion', 'Cf-Access-Authenticated-User-Email', 'CF-Access-Client-Id', 'CF-Access-Client-Secret']) forwarded.headers.delete(header);
    forwarded.headers.delete('X-Workspace-Owner');
    if (workspace && owner) forwarded.headers.set('X-Workspace-Owner', owner);
    const response = sec ? await env.SEC_INGESTION!.fetch(forwarded) : await namespace.get(namespace.idFromName(env.DASHBOARD_RELEASE || 'singleton')).fetch(forwarded);
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
