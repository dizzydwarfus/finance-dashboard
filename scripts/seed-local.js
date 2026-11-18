// Only mounted by the disposable Compose fixture profile.
const fixture = EJSON.parse(require('fs').readFileSync('/fixtures/published.json', 'utf8'));
const sec = db.getSiblingDB('SECIngestion');
for (const [collection, records] of Object.entries(fixture)) {
  if (records.length) sec[collection].insertMany(records);
}
sec.createUser({ user: 'sec-reader', pwd: 'local-reader-only', roles: [{ role: 'read', db: 'SECIngestion' }] });
sec.createUser({ user: 'sec-ingestion', pwd: 'local-sec-only', roles: [{ role: 'readWrite', db: 'SECIngestion' }] });
