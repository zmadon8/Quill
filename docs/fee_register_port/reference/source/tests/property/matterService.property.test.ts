import { describe, it, beforeAll, afterAll } from 'vitest'
import * as fc from 'fast-check'
import type Database from 'better-sqlite3'
import { createSchemaDb, truncateAll } from '../helpers/testDb'
import { createFirm, addPartner } from '@/services/firmService'
import { createMatter, listMatters, archiveMatter, unarchiveMatter, getMatter } from '@/services/matterService'

let db: Database.Database
beforeAll(() => { db = createSchemaDb() })
afterAll(() => db.close())

describe('matterService — property tests', () => {
  it('Property 5: new matters always start Active', () => {
    fc.assert(
      fc.property(fc.string({ minLength: 1, maxLength: 40 }), (rawName) => {
        const name = rawName.trim()
        fc.pre(name.length >= 1 && name.length <= 150)
        truncateAll(db)
        const f = createFirm(db, 'Firm')
        const p = addPartner(db, f.id, 'P')
        const m = createMatter(db, { name, firmId: f.id, partnerId: p.id })
        return m.isArchived === false
      }),
      { numRuns: 100 },
    )
  })

  it('Property 6: archive → unarchive is a status round-trip', () => {
    fc.assert(
      fc.property(fc.integer({ min: 1, max: 5 }), (n) => {
        truncateAll(db)
        const f = createFirm(db, 'Firm')
        const p = addPartner(db, f.id, 'P')
        const m = createMatter(db, { name: 'M', firmId: f.id, partnerId: p.id })
        // Apply n archive/unarchive cycles; end state must equal start (active).
        for (let i = 0; i < n; i++) {
          archiveMatter(db, m.id)
          unarchiveMatter(db, m.id)
        }
        return getMatter(db, m.id).isArchived === false
      }),
      { numRuns: 100 },
    )
  })

  it('Property 4: matters within a partner are alphabetically sorted', () => {
    fc.assert(
      fc.property(
        fc.uniqueArray(fc.string({ minLength: 1, maxLength: 20 }), {
          minLength: 1,
          maxLength: 12,
          comparator: (a, b) => a.trim().toLowerCase() === b.trim().toLowerCase(),
        }),
        (names) => {
          const cleaned = names.map((s) => s.trim()).filter((s) => s.length >= 1 && s.length <= 150)
          const lowerSet = new Set(cleaned.map((s) => s.toLowerCase()))
          fc.pre(cleaned.length === names.length && lowerSet.size === cleaned.length)

          truncateAll(db)
          const f = createFirm(db, 'Firm')
          const p = addPartner(db, f.id, 'OnlyPartner')
          for (const n of cleaned) createMatter(db, { name: n, firmId: f.id, partnerId: p.id })

          const result = listMatters(db, 'all', f.id).map((m) => m.name.toLowerCase())
          const expected = [...result].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0))
          return JSON.stringify(result) === JSON.stringify(expected)
        },
      ),
      { numRuns: 80 },
    )
  })
})
