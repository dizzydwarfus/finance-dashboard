import { describe, expect, it, vi } from 'vitest';
import { Lifecycle } from './lifecycle';
function container() {
  const c = { running: false, monitor: vi.fn(() => new Promise<void>(() => {})), images: { base: 'image-v1' }, start: vi.fn(() => { c.running = true; }), destroy: vi.fn(async () => { c.running = false; }), inspect: vi.fn(async () => ({ image: 'old-image', labels: { config: 'old-config' } })), setInactivityTimeout: vi.fn(async () => { if (!c.running) throw new Error('The container has not been started'); }), getTcpPort: vi.fn(() => ({ fetch: vi.fn(async () => new Response('ok')) })) };
  return c;
}
const config = { internet: true, env: { MONGODB_URI: 'secret' }, readinessPath: '/readyz' };
describe('container lifecycle', () => {
  it('starts once for concurrent requests, reuses warm instances, and restarts after sleep', async () => {
    const c = container(); const lifecycle = new Lifecycle(c as unknown as Container, config);
    await Promise.all([lifecycle.ready(), lifecycle.ready()]); expect(c.start).toHaveBeenCalledTimes(1);
    expect(c.start).toHaveBeenCalledWith(expect.objectContaining({ image: 'image-v1', instance: 'lite', enableInternet: true, env: config.env }));
    await lifecycle.ready(); expect(c.start).toHaveBeenCalledTimes(1);
    c.running = false; await lifecycle.ready(); expect(c.start).toHaveBeenCalledTimes(2);
    expect(c.setInactivityTimeout).toHaveBeenCalledWith(600000);
  });
  it('replaces stale running images on deployment', async () => {
    const c = container(); c.running = true;
    await new Lifecycle(c as unknown as Container, config).ready();
    expect(c.destroy).toHaveBeenCalledTimes(1); expect(c.start).toHaveBeenCalledTimes(1);
  });
  it('restarts when runtime secrets change even if the image is unchanged', async () => {
    const c = container(); c.running = true; c.inspect.mockResolvedValue({ image: 'image-v1', labels: { config: 'old-config' } });
    await new Lifecycle(c as unknown as Container, config).ready();
    expect(c.destroy).toHaveBeenCalledTimes(1); expect(c.start).toHaveBeenCalledTimes(1);
  });
  it('reports process exits without waiting for the readiness deadline', async () => {
    const c = container();
    c.monitor.mockRejectedValue(new Error('Container exited with unexpected exit code: 1'));
    c.getTcpPort.mockReturnValue({ fetch: vi.fn(async () => { throw new Error('Port closed'); }) });
    await expect(new Lifecycle(c as unknown as Container, config).ready()).rejects.toThrow('exit code: 1');
  });
  it('bounds readiness polling and can recover on the next request', async () => {
    vi.useFakeTimers();
    try {
      const c = container(); let ready = false;
      c.getTcpPort.mockReturnValue({ fetch: vi.fn(async () => new Response('', { status: ready ? 200 : 503 })) });
      const lifecycle = new Lifecycle(c as unknown as Container, config);
      const rejected = expect(lifecycle.ready()).rejects.toThrow('readiness timed out');
      await vi.waitFor(() => expect(c.start).toHaveBeenCalled());
      await vi.advanceTimersByTimeAsync(26000); await rejected;
      ready = true; await lifecycle.ready();
    } finally { vi.useRealTimers(); }
  });
});
