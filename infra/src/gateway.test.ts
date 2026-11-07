import { describe, expect, it, vi } from 'vitest';
import { createLocalJWKSet, exportJWK, generateKeyPair, SignJWT } from 'jose';
import { verifyAccess } from './auth';
import { gateway, routeTarget, type Env } from './gateway';
const config = { ACCESS_TEAM_DOMAIN: 'example.cloudflareaccess.com', ACCESS_AUD: 'dashboard' };
describe('Access authentication', () => {
  it('rejects missing configuration and missing tokens', async () => {
    await expect(verifyAccess(new Request('https://example.com'), config)).rejects.toThrow();
    await expect(verifyAccess(new Request('https://example.com'), { ...config, ACCESS_AUD: '' })).rejects.toThrow();
  });
  it('checks signature, issuer, audience, expiration, and required claims', async () => {
    const { publicKey, privateKey } = await generateKeyPair('RS256');
    const jwk = await exportJWK(publicKey); const keys = createLocalJWKSet({ keys: [{ ...jwk, alg: 'RS256' }] });
    const token = async (aud = 'dashboard', exp = '2h', issuer = 'https://example.cloudflareaccess.com') => new SignJWT({ type: 'app' }).setProtectedHeader({ alg: 'RS256' }).setSubject('user').setIssuer(issuer).setAudience(aud).setIssuedAt().setExpirationTime(exp).sign(privateKey);
    const request = (value: string) => new Request('https://example.com', { headers: { 'Cf-Access-Jwt-Assertion': value } });
    await expect(verifyAccess(request(await token()), config, keys)).resolves.toBeUndefined();
    const serviceToken = await new SignJWT({ type: 'app', common_name: 'ci.access' }).setProtectedHeader({ alg: 'RS256' }).setSubject('').setIssuer('https://example.cloudflareaccess.com').setAudience('dashboard').setIssuedAt().setExpirationTime('2h').sign(privateKey);
    await expect(verifyAccess(request(serviceToken), config, keys)).resolves.toBeUndefined();
    for (const bad of [await token('other'), await token('dashboard', '-1h'), await token('dashboard', '2h', 'https://wrong.example'), 'invalid.jwt.value']) await expect(verifyAccess(request(bad), config, keys)).rejects.toThrow();
  });
});
describe('gateway routing', () => {
  it('uses exact API boundaries', () => { expect(routeTarget('/api/v1/tickers')).toBe('API'); expect(routeTarget('/apiculture')).toBe('WEB'); expect(routeTarget('/readyz')).toBe('API'); });
  it('rejects unauthenticated requests before allocating containers', async () => {
    const response = await gateway(new Request('https://example.com/api/v1/tickers'), {} as Env);
    expect(response.status).toBe(401);
  });
  it('forwards only after authentication and strips credentials', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response('ok')); const namespace = { idFromName: vi.fn().mockReturnValue('singleton'), get: vi.fn().mockReturnValue({ fetch }) };
    const response = await gateway(new Request('https://example.com/api/v1/tickers', { headers: { Cookie: 'private', 'Cf-Access-Jwt-Assertion': 'private', 'CF-Access-Client-Secret': 'private' } }), { API: namespace } as unknown as Env, async () => {});
    expect(response.status).toBe(200); expect(response.headers.get('Cache-Control')).toContain('no-store');
    const forwarded = fetch.mock.calls[0][0] as Request; expect(forwarded.headers.has('Cookie')).toBe(false); expect(forwarded.headers.has('Cf-Access-Jwt-Assertion')).toBe(false); expect(forwarded.headers.has('CF-Access-Client-Secret')).toBe(false);
  });
  it('rejects mutations and sanitizes startup failures', async () => {
    expect((await gateway(new Request('https://example.com/api', { method: 'POST' }), {} as Env, async () => {})).status).toBe(405);
    expect((await gateway(new Request('https://example.com/api'), {} as Env, async () => {})).status).toBe(503);
  });
});
