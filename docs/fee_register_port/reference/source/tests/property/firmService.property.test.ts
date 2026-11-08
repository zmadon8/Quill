import { describe, it, beforeAll, afterAll } from 'vitest'
import * as fc from 'fast-check'
import type Database from 'better-sqlite3'
import { createSchemaDb, truncateAll } from '../helpers/testDb'
import { createFirm, listFirms, setFirmStatus, addPartner } from '@/services/firmService'

let db: Database.Database
let insertMatter: Database.Statement

beforeAll(() => {
  db = createSchemaDb()
  // Prepare the insert ONCE and reuse it. Creating a new Statement on every
  // fast-check iteration churns thousands of native handles whose finalizers
  // can abort the worker; a single cached statement avoids that.
  insertMatter = db.prepare(
    'INSERT INTO matters (firm_id, partner_id, name, is_archived) VALUES (?, ?, ?, ?)',
  )
})

afterAll(() => db.close())

describe('firmService — property tests', () => {
  it('Property 2: firm status is whatever was last set, independent of its matters', () => {
    fc.assert(
      fc.property(
        fc.array(fc.boolean(), { minLength: 0, maxLength: 10 }),
        fc.boolean(),
        (archivedFlags, archiveFirm) => {
          truncateAll(db)
          const f = createFirm(db, 'Firm X')
          const p = addPartner(db, f.id, 'P')
          archivedFlags.forEach((archived, i) => {
            insertMatter.run(f.id, p.id, `Matter ${i}`, archived ? 1 : 0)
          })
          // Default is 'active'; optionally archive the firm manually.
          const expected: 'active' | 'archived' = archiveFirm ? 'archived' : 'active'
          if (archiveFirm) setFirmStatus(db, f.id, 'archived')
          // Matter archive state must NOT influence the firm's stored status.
          return listFirms(db, 'all')[0].status === expected
        },
      ),
      { numRuns: 100 },
    )
  })

  it('Property 3: listFirms is always alphabetically sorted (case-insensitive)', () => {
    fc.assert(
      fc.property(
        fc.uniqueArray(fc.string({ minLength: 1, maxLength: 20 }), {
          minLength: 1,
          maxLength: 15,
          comparator: (a, b) => a.trim().toLowerCase() === b.trim().toLowerCase(),
        }),
        (names) => {
          const cleaned = names.map((n) => n.trim()).filter((n) => n.length > 0)
          const lowerSet = new Set(cleaned.map((n) => n.toLowerCase()))
          fc.pre(cleaned.length === names.length && lowerSet.size === cleaned.length)

          truncateAll(db)
          for (const n of cleaned) createFirm(db, n)
          const result = listFirms(db, 'all').map((f) => f.name.toLowerCase())
          const expected = [...result].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0))
          return JSON.stringify(result) === JSON.stringify(expected)
        },
      ),
      { numRuns: 80 },
    )
  })
})
