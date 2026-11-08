import { deploymentKeys } from './env.mjs';
// Wrangler output is buffered before redaction so chunk boundaries cannot expose a secret.
export function createRedactor(env) {
  const values = deploymentKeys.flatMap(key => env[key] ? [env[key]] : []);
  for (const value of [env.MONGODB_URI, env.SEC_MONGODB_URI].filter(Boolean)) {
    try {
      const uri = new URL(value);
      for (const part of [uri.username, uri.password]) {
        if (part) { values.push(part); values.push(decodeURIComponent(part)); }
      }
    } catch { /* Validation reports invalid configuration without logging URI contents. */ }
  }
  const secrets = [...new Set(values.filter(value => value.length >= 4))]
    .flatMap(value => [value, JSON.stringify(value).slice(1, -1)])
    .sort((a, b) => b.length - a.length);
  const abbreviated = secrets.flatMap(secret => {
    const parts = [];
    for (let length = 4; length < secret.length; length++) {
      parts.push(secret.slice(0, length) + '...', secret.slice(0, length) + '…');
    }
    return parts;
  }).sort((a, b) => b.length - a.length);
  return input => [...secrets, ...abbreviated].reduce((output, secret) => output.replaceAll(secret, '[REDACTED]'), input)
    .replace(/([?&](?:_stateHash|token|access_token|sig|signature|password)=)[^&\s"']+/gi, '$1[REDACTED]');
}
