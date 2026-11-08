import { DurableObject } from 'cloudflare:workers';
import { Lifecycle } from './lifecycle';
import { secMethod } from './sec-routes';
import { recoverQueue } from './sec-coordinator';
interface Env {
  INGESTION: DurableObjectNamespace;
  SEC_MONGODB_URI: string;
  SEC_MONGODB_DATABASE: string;
  SEC_USER_AGENT: string;
  SEC_PARSER_VERSION: string;
}
export class SECContainer extends DurableObject<Env> {
  private lifecycle?: Lifecycle;
  private async ready() {
    const container = this.ctx.container;
    if (!container || !this.env.SEC_MONGODB_URI || !this.env.SEC_USER_AGENT) throw new Error('SEC ingestion configuration missing');
    this.lifecycle ??= new Lifecycle(container, {
      internet: true, instance: 'standard-1', readinessPath: '/readyz',
      env: { SEC_MONGODB_URI: this.env.SEC_MONGODB_URI, SEC_MONGODB_DATABASE: this.env.SEC_MONGODB_DATABASE || 'SECIngestion', SEC_USER_AGENT: this.env.SEC_USER_AGENT, SEC_PARSER_VERSION: this.env.SEC_PARSER_VERSION || 'arelle-v1' },
    });
    await this.lifecycle.ready();
    return container.getTcpPort(8080);
  }
  async fetch(request: Request): Promise<Response> {
    // Arm recovery before forwarding a mutation. A lost response cannot orphan accepted work.
    if (request.method === 'POST') await this.ctx.storage.setAlarm(Date.now() + 15_000);
    const port = await this.ready();
    const url = new URL(request.url); url.protocol = 'http:'; url.host = 'container';
    return port.fetch(new Request(url, request));
  }
  async alarm(): Promise<void> {
    await recoverQueue(this.ctx.storage, () => this.ready());
  }
}
export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const method = secMethod(new URL(request.url).pathname);
    if (!method || request.method !== method) return Response.json({ error: { code: 'not_found', message: 'SEC endpoint not found' } }, { status: 404 });
    try { return await env.INGESTION.get(env.INGESTION.idFromName('singleton')).fetch(request); }
    catch { return Response.json({ error: { code: 'ingestion_unavailable', message: 'SEC ingestion is starting or unavailable. Please retry.' } }, { status: 503, headers: { 'Retry-After': '5' } }); }
  },
} satisfies ExportedHandler<Env>;
