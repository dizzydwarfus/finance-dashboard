// Only mounted by the disposable Compose fixture profile.
const fixture = EJSON.parse(require('fs').readFileSync('/fixtures/published.json', 'utf8'));
const sec = db.getSiblingDB('SECIngestion');
for (const [collection, records] of Object.entries(fixture)) {
  if (records.length) sec[collection].insertMany(records);
}
sec.createUser({ user: 'sec-reader', pwd: 'local-reader-only', roles: [{ role: 'read', db: 'SECIngestion' }] });
sec.createUser({ user: 'sec-ingestion', pwd: 'local-sec-only', roles: [{ role: 'readWrite', db: 'SECIngestion' }] });
sec.analyst_workspaces.createIndex({owner:1,symbol:1,kind:1,updated:-1},{name:'owner_symbol_kind_updated'});
sec.createRole({role:'workspaceEditor',privileges:[{resource:{db:'SECIngestion',collection:'analyst_workspaces'},actions:['find','insert','update','remove']}],roles:[]});
sec.createUser({user:'workspace',pwd:'local-only',roles:['workspaceEditor']});
