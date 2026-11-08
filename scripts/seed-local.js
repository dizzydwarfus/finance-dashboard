// Only mounted in the optional local fixture MongoDB service.
const fixture = EJSON.parse(require('fs').readFileSync('/fixtures/financeapp.json', 'utf8'));
const finance = db.getSiblingDB('FinanceApp');
for (const [collection, records] of Object.entries(fixture)) {
  if (records.length) finance[collection].insertMany(records);
}
finance.createUser({ user: 'dashboard', pwd: 'local-fixture-only', roles: [{ role: 'read', db: 'FinanceApp' }] });

const sec = db.getSiblingDB('SECIngestion');
sec.createCollection('schema');
sec.createUser({ user: 'sec-ingestion', pwd: 'local-sec-only', roles: [{ role: 'readWrite', db: 'SECIngestion' }] });
