import { describe, it, beforeAll, afterAll } from 'vitest'
import * as fc from 'fast-check'
import type Database from 'better-sqlite3'
import { createSchemaDb, truncateAll } from '../helpers/testDb'
import { createFirm, addPartner } from '@/services/firmService'
import { createMatter } from '@/services/matterService'
import { createMemo } from '@/services/memoService'
import { deriveExportFilename } from '@/services/exportService'

let db: Database.Database
beforeAll(() => { db = createSchemaDb() })
afterAll(() => db.close())

describe('exportService — property tests', () => {
  it('Property 20: filename matches "Memo {seq} of {year} Ziyad Madon ({matter}).docx"', () => {
    fc.assert(
      fc.property(
        fc.string({ minLength: 1, maxLength: 40 }),
        fc.constantFrom<'docx'>('docx'),
        (rawMatter, ext) => {
          const matter = rawMatter.trim()
          fc.pre(matter.length >= 1 && matter.length <= 150)
          truncateAll(db)
          const f = createFirm(db, 'Firm')
          const p = addPartner(db, f.id, 'P')
          const m = createMatter(db, { name: matter, firmId: f.id, partnerId: p.id })
          const memo = createMemo(db, {
            date: '2026-07-15', matterId: m.id, addresseeLine1: 'A',
            numAppearances: 1, feesPerAppearance: 100, numConferences: 0,
            feesPerConference: 0, feesMiscDrafting: 0, tdsRate: 10,
          })
          const sanitized = matter.replace(/[/\\:*?"<>|]/g, '-').trim()
          const expected = `Memo ${memo.seq} of 2026-27 Ziyad Madon (${sanitized}).${ext}`
          return deriveExportFilename(memo, ext) === expected
        },
      ),
      { numRuns: 100 },
    )
  })
})
