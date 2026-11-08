import { describe, it, beforeEach, beforeAll, afterAll } from 'vitest'
import * as fc from 'fast-check'
import type Database from 'better-sqlite3'
import { createSchemaDb, truncateAll } from '../helpers/testDb'

let db: Database.Database
beforeAll(() => { db = createSchemaDb() })
afterAll(() => db.close())

function resetDb(): void {
  truncateAll(db)
}

describe('schema uniqueness — property tests', () => {
  beforeEach(() => resetDb())

  it('Property 1: inserting the same firm name twice throws a UNIQUE constraint error', () => {
    fc.assert(
      fc.property(fc.string({ minLength: 1, maxLength: 100 }), (name) => {
        resetDb()
        // Prepare statements inside the iteration so no native Statement handle
        // is retained at module scope across test-file boundaries.
        db.prepare('INSERT INTO firms (name) VALUES (?)').run(name)

        let threw = false
        try {
          db.prepare('INSERT INTO firms (name) VALUES (?)').run(name)
        } catch (err) {
          const msg = (err as Error).message
          if (!/UNIQUE/i.test(msg)) throw err
          threw = true
        }

        const count = (db.prepare('SELECT COUNT(*) AS c FROM firms').get() as { c: number }).c
        return threw && count === 1
      }),
      { numRuns: 200 },
    )
  })
})
