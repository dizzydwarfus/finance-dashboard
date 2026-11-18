// Run in mongosh as a collection/index administrator. Safe to repeat.
db.getSiblingDB('SECIngestion').analyst_workspaces.createIndex(
  { owner: 1, symbol: 1, kind: 1, updated: -1 }, { name: 'owner_symbol_kind_updated' }
);
