import { loadEnvironment, requireKeys } from './env.mjs';
import { setMaintenance } from './ingestion-deployment.mjs';
if (process.argv.length !== 3 || !['on','off'].includes(process.argv[2])) throw new Error('Usage: node scripts/sec-maintenance.mjs on|off');
const env = loadEnvironment('production');
requireKeys(env,['CLOUDFLARE_HOSTNAME','CF_ACCESS_CLIENT_ID','CF_ACCESS_CLIENT_SECRET']);
await setMaintenance(env,process.argv[2]==='on');
console.log('SEC maintenance setting updated.');
