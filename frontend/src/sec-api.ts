import { ApiError, readAPIResponse } from './api';
import type { components } from './api.generated';
export type SECCompany = components['schemas']['SECCompany'];
export type SECJob = components['schemas']['SECJob'];
export type SECFiling = components['schemas']['SECFiling'];
export type SECFact = components['schemas']['SECFact'];
export interface SECEnvelope<T> { data: T; meta?: { total?: number; offset?: number; limit?: number; suggestions?: SECCompany[]; registryUpdatedAt?: string | null }; }
export const terminal = new Set(['completed', 'partial_failed', 'failed', 'blocked', 'cancelled', 'superseded']);
export class SECError extends ApiError { constructor(status: number, message: string, public code?: string) { super(status, message); } }
export async function secAPI<T>(path: string, options: { method?: 'POST'; body?: unknown; key?: string; signal?: AbortSignal } = {}): Promise<SECEnvelope<T>> {
  const response = await fetch(`/api/v1/sec${path}`, { method: options.method || 'GET', signal: options.signal, credentials: 'same-origin',
    headers: { Accept: 'application/json', ...(options.method ? { 'Content-Type': 'application/json' } : {}), ...(options.key ? { 'Idempotency-Key': options.key } : {}) },
    body: options.method ? JSON.stringify(options.body ?? {}) : undefined });
  const result = await readAPIResponse(response, 'The SEC service');
  if (!response.ok) throw new SECError(response.status, result.error?.message || 'SEC data is unavailable.', result.error?.code);
  return result as SECEnvelope<T>;
}
export function conceptName(value: string) { return value.replace(/^\{[^}]*\}/, '').replace(/^[^:]+:/, ''); }
export function factValue(value: string | null) {
  // Financial values stay decimal strings; never round-trip through a JS number.
  if (value == null) return '—';
  const match = /^(-?)(\d+)(\.\d+)?$/.exec(value);
  return match ? `${match[1]}${match[2].replace(/\B(?=(\d{3})+(?!\d))/g, ',')}${match[3] || ''}` : value;
}
export function sourceLink(value: string) { try { const u = new URL(value); return u.protocol === 'https:' && ['www.sec.gov', 'data.sec.gov'].includes(u.hostname) ? u.href : undefined; } catch { return undefined; } }
