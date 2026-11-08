export interface StartConfig { internet: boolean; env: Record<string, string>; readinessPath: string; instance?: 'lite' | 'standard-1'; }
export class Lifecycle {
  private readyImage = '';
  private starting?: Promise<void>;
  constructor(private container: Container, private config: StartConfig) {}
  async ready(): Promise<void> {
    if (this.container.running && this.readyImage === this.container.images.base) {
      await this.container.setInactivityTimeout(10 * 60 * 1000);
      return;
    }
    this.starting ??= this.start();
    try { await this.starting; } finally { this.starting = undefined; }
  }
  private async start() {
    const container = this.container;
    const image = container.images.base;
    const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify({ env: this.config.env, internet: this.config.internet })));
    const configHash = Array.from(new Uint8Array(hash), byte => byte.toString(16).padStart(2, '0')).join('');
    if (!image) throw new Error('Container image missing');
    // Named-image updates do not restart durable_object containers automatically.
    if (container.running) {
      const info = await container.inspect();
      if (info?.image && (info.image !== image || info.labels?.config !== configHash)) await container.destroy();
    }
    if (!container.running) container.start({ image, instance: this.config.instance || 'lite', enableInternet: this.config.internet, env: this.config.env, labels: { config: configHash } });
    // Cloudflare rejects timeout changes before a container has been started.
    await container.setInactivityTimeout(10 * 60 * 1000);
    let startupError: Error | undefined;
    void container.monitor().then(
      () => { startupError = new Error('Container exited before readiness'); },
      error => { startupError = error instanceof Error ? error : new Error('Container startup failed'); },
    );
    const deadline = Date.now() + 25_000;
    const port = container.getTcpPort(8080);
    while (Date.now() < deadline) {
      if (startupError) throw startupError;
      try {
        const response = await port.fetch(`http://container${this.config.readinessPath}`, { signal: AbortSignal.timeout(2000) });
        await response.body?.cancel();
        if (response.ok) { this.readyImage = image; return; }
      } catch { /* Retry while the port or database is becoming ready. */ }
      await new Promise(resolve => setTimeout(resolve, 250));
    }
    if (startupError) throw startupError;
    throw new Error('Container readiness timed out');
  }
}
