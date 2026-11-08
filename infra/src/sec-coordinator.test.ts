import { describe, it, expect, vi } from 'vitest';
import { recoverQueue } from './sec-coordinator';
describe('durable SEC queue recovery', () => {
  const now = () => Date.parse('2026-11-08T12:00:00Z');
  function setup(data: object) {
    const storage = { setAlarm: vi.fn(async (_: number) => {}), deleteAlarm: vi.fn(async () => {}) };
    const fetch = vi.fn(async (_url: RequestInfo | URL, _options?: RequestInit) => Response.json({ data }));
    const ready = vi.fn(async () => ({ fetch }) as unknown as Fetcher);
    return { storage, fetch, ready };
  }
  it('arms a durable retry before waking the private container', async () => {
    const { storage, fetch, ready } = setup({ pending: 2, blocked: false, maintenance: false });
    await recoverQueue(storage, ready, now);
    expect(storage.setAlarm.mock.calls.map(call => call[0])).toEqual([now() + 60000, now() + 15000]);
    expect(storage.setAlarm.mock.invocationCallOrder[0]).toBeLessThan(fetch.mock.invocationCallOrder[0]);
    expect(fetch.mock.calls[0][0]).toBe('http://container/_internal/wake');
  });
  it('retains a retry when startup or database readiness fails', async () => {
    const { storage } = setup({});
    await recoverQueue(storage, async () => { throw new Error('Unavailable'); }, now);
    expect(storage.setAlarm).toHaveBeenCalledWith(now() + 60000);
    expect(storage.deleteAlarm).not.toHaveBeenCalled();
  });
  it('sleeps through a persisted SEC cooldown', async () => {
    const { storage, ready } = setup({ pending: 1, blocked: false, maintenance: false, retryAt: '2026-11-08T12:10:00Z' });
    await recoverQueue(storage, ready, now);
    expect(storage.setAlarm).toHaveBeenLastCalledWith(now() + 600000);
  });
  it.each([{ pending: 0 }, { pending: 2, blocked: true }, { pending: 2, maintenance: true }])('stops automatic waking for %j', async data => {
    const { storage, ready } = setup(data);
    await recoverQueue(storage, ready, now);
    expect(storage.deleteAlarm).toHaveBeenCalledOnce();
  });
});
