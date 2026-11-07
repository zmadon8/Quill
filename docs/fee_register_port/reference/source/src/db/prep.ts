/**
 * prep.ts — shared database helpers used across every service.
 *
 * `prep(db, sql)` returns a cached prepared statement per (db, sql) pair, so
 * services don't recompile the same SQL on every call and the number of native
 * statement handles stays bounded. `round2` is the standard 2-dp rounding used
 * for all monetary maths. Previously both were copy-pasted into each service.
 */
import type Database from 'better-sqlite3'

const stmtCache = new WeakMap<Database.Database, Map<string, Database.Statement>>()

export function prep(db: Database.Database, sql: string): Database.Statement {
  let cache = stmtCache.get(db)
  if (!cache) {
    cache = new Map()
    stmtCache.set(db, cache)
  }
  let stmt = cache.get(sql)
  if (!stmt) {
    stmt = db.prepare(sql)
    cache.set(sql, stmt)
  }
  return stmt
}

/** Rounds to 2 decimal places (the standard for all monetary values). */
export function round2(n: number): number {
  return Math.round((n + Number.EPSILON) * 100) / 100
}
