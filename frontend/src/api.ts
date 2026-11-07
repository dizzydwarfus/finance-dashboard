import type { components } from './api.generated';
export type Company = components['schemas']['Company'];
export type Statement = components['schemas']['Statement'];
export type Metrics = components['schemas']['Metrics'];
export type Price = components['schemas']['Price'];
export type Split = components['schemas']['Split'];
export type Ticker = components['schemas']['Ticker'];
export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}
export async function api<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`/api/v1${path}`, { signal, credentials: 'same-origin', headers: { Accept: 'application/json' } });
  if (response.redirected || !response.headers.get('content-type')?.includes('application/json')) {
    throw new ApiError(401, 'Your session has expired. Reload to sign in again.');
  }
  const body = await response.json();
  if (!response.ok) throw new ApiError(response.status, body.error?.message || 'Unable to load this data.');
  return body.data as T;
}
export function format(value: number | null | undefined, kind = 'currency', currency = 'USD', compact = false): string {
  if (value == null || !Number.isFinite(value)) return '—';
  const options: Intl.NumberFormatOptions = kind === 'percent'
    ? { style: 'percent', maximumFractionDigits: 1 }
    : kind === 'currency'
    ? { ...(/^[A-Z]{3}$/.test(currency) ? { style: 'currency' as const, currency } : {}), maximumFractionDigits: compact ? 1 : 2 }
    : { maximumFractionDigits: 1 };
  if (compact && kind !== 'percent') options.notation = 'compact';
  return new Intl.NumberFormat('en-US', options).format(value);
}
export function label(key: string) { return key.replace(/([A-Z])/g, ' $1').replace(/^./, c => c.toUpperCase()).replace('Eps', 'EPS'); }
