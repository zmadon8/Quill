import Database from 'better-sqlite3'
import { SCHEMA_DDL } from '../../src/db/schemaDdl'

/**
 * Creates an in-memory SQLite database with the full application schema.
 *
 * The schema is derived from the SINGLE source of runtime truth,
 * `src/db/schemaDdl.ts` (`SCHEMA_DDL`), so the test database can never drift
 * from what the app actually creates at startup. Previously this helper kept a
 * hand-maintained copy of the DDL, which silently went stale whenever a column
 * was added. Importing `SCHEMA_DDL` removes that whole class of bug.
 */
export function createSchemaDb(): Database.Database {
  const db = new Database(':memory:')
  db.pragma('foreign_keys = ON')
  db.exec(SCHEMA_DDL)
  // Seed the single settings row (the app does this in client.ts after the DDL).
  db.prepare('INSERT OR IGNORE INTO settings (id, default_tds_rate) VALUES (1, 10)').run()
  return db
}

/** Deletes all rows from all tables (keeps the seeded settings row). */
export function truncateAll(db: Database.Database): void {
  truncate(db)()
}

// Cached, prepared DELETE statements per DB. Using cached statements inside a
// single transaction avoids recompiling SQL on every reset, which keeps the
// number of native Statement handles bounded during property-test loops.
const truncateFns = new WeakMap<Database.Database, () => void>()
const TABLES = [
  'payment_allocations',
  'period_adjustments',
  'payments',
  'memos',
  'matters',
  'partners',
  'firms',
  'bank_accounts',
  'memo_number_sequences',
] as const

function truncate(db: Database.Database): () => void {
  let fn = truncateFns.get(db)
  if (!fn) {
    const stmts = TABLES.map((t) => db.prepare(`DELETE FROM ${t}`))
    fn = db.transaction(() => {
      for (const st of stmts) st.run()
    })
    truncateFns.set(db, fn)
  }
  return fn
}

// ---------------------------------------------------------------------------
// Shared singleton DB
// ---------------------------------------------------------------------------
// To avoid the Node 24 "env != nullptr" native finalizer race, the whole test
// run reuses ONE in-memory connection. It is created on first use and never
// explicitly closed, so no finalizer hook fires mid-run. Tests must call
// truncateAll() to reset state between cases.
let shared: Database.Database | null = null

export function sharedSchemaDb(): Database.Database {
  if (shared === null) {
    shared = createSchemaDb()
  }
  return shared
}
