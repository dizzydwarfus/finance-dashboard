interface AlarmStorage { setAlarm(time: number): Promise<void>; deleteAlarm(): Promise<void>; }
interface QueueState { pending: number; blocked: boolean; retryAt?: string; maintenance: boolean; }
// Storage is durable; queue recovery does not depend on a browser connection or a live container.
export async function recoverQueue(storage: AlarmStorage, ready: () => Promise<Fetcher>, now = Date.now): Promise<void> {
  await storage.setAlarm(now() + 60_000);
  try {
    const port = await ready();
    const response = await port.fetch('http://container/_internal/wake', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    if (!response.ok) return;
    const { data } = await response.json<{ data: QueueState }>();
    if (!data.pending || data.blocked || data.maintenance) await storage.deleteAlarm();
    else {
      const retryAt = data.retryAt ? Date.parse(data.retryAt) : 0;
      await storage.setAlarm(Math.max(now() + 15_000, Number.isFinite(retryAt) ? retryAt : 0));
    }
  } catch { /* Retry startup later; never log raw driver errors or credentials. */ }
}
