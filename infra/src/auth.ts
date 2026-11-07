import { createRemoteJWKSet, jwtVerify, type JWTVerifyGetKey } from 'jose';
export interface AccessConfig { ACCESS_TEAM_DOMAIN: string; ACCESS_AUD: string; }
const keysets = new Map<string, JWTVerifyGetKey>();
export async function verifyAccess(request: Request, config: AccessConfig, testKey?: JWTVerifyGetKey): Promise<void> {
  const { ACCESS_TEAM_DOMAIN: domain, ACCESS_AUD: audience } = config;
  if (!/^[a-z0-9-]+\.cloudflareaccess\.com$/.test(domain) || !audience) throw new Error('Access configuration missing');
  const token = request.headers.get('Cf-Access-Jwt-Assertion');
  if (!token) throw new Error('Access token missing');
  const issuer = `https://${domain}`;
  let keys = testKey || keysets.get(issuer);
  if (!keys) { keys = createRemoteJWKSet(new URL(`${issuer}/cdn-cgi/access/certs`)); keysets.set(issuer, keys); }
  const { payload } = await jwtVerify(token, keys, { issuer, audience, algorithms: ['RS256'], requiredClaims: ['exp', 'iat', 'sub'] });
  if (payload.type !== 'app') throw new Error('An application Access token is required');
}
