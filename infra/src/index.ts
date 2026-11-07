import { DurableObject } from 'cloudflare:workers';
import { gateway, type Env } from './gateway';
import { Lifecycle } from './lifecycle';

abstract class ServiceContainer extends DurableObject<Env> {
  private lifecycle?: Lifecycle;
  protected abstract backend: boolean;
  async fetch(request: Request): Promise<Response> {
    const container = this.ctx.container;
    if (!container) throw new Error('Container binding missing');
    if (this.backend && !this.env.MONGODB_URI) throw new Error('Database secret missing');
    this.lifecycle ??= new Lifecycle(container, {
      internet: this.backend,
      env: this.backend ? { MONGODB_URI: this.env.MONGODB_URI, MONGODB_DATABASE: this.env.MONGODB_DATABASE || 'FinanceApp' } : {},
      readinessPath: this.backend ? '/readyz' : '/healthz',
    });
    await this.lifecycle.ready();
    const url = new URL(request.url); url.protocol = 'http:'; url.host = 'container';
    const forwarded = new Request(url, request); forwarded.headers.delete('host');
    return container.getTcpPort(8080).fetch(forwarded);
  }
}
export class APIContainer extends ServiceContainer { protected backend = true; }
export class WebContainer extends ServiceContainer { protected backend = false; }
export default { fetch: (request, env) => gateway(request, env) } satisfies ExportedHandler<Env>;
