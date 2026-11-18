export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}
export async function readAPIResponse(response: Response, service: string): Promise<{ data?: unknown; meta?: unknown; error?: { message?: string; code?: string } }> {
  const url = response.url ? new URL(response.url) : null;
  const accessRedirect = response.redirected && !!url && (url.hostname.endsWith('.cloudflareaccess.com') || url.pathname.startsWith('/cdn-cgi/access/login'));
  if (response.status === 401 || accessRedirect) throw new ApiError(401, 'Your session has expired. Reload to sign in again.');
  const unexpected = () => new ApiError(response.ok ? 502 : response.status, `${service} returned an unexpected response (HTTP ${response.status}). Please retry.`);
  if (!response.headers.get('content-type')?.toLowerCase().includes('application/json')) throw unexpected();
  let body;
  try { body = await response.json(); } catch { throw unexpected(); }
  if (!body || typeof body !== 'object' || Array.isArray(body) || (response.ok && !Object.hasOwn(body, 'data'))) throw unexpected();
  return body;
}
export async function api<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`/api/v1${path}`, { signal, credentials: 'same-origin', headers: { Accept: 'application/json' } });
  const body = await readAPIResponse(response, 'The financial service');
  if (!response.ok) throw new ApiError(response.status, body.error?.message || 'Unable to load this data.');
  return body.data as T;
}
