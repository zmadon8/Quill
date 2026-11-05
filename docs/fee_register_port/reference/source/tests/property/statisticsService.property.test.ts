import { describe, it, beforeAll, afterAll } from 'vitest'
import * as fc from 'fast-check'
import type Database from 'better-sqlite3'
import { createSchemaDb, truncateAll } from '../helpers/testDb'
import { createFirm, addPartner } from '@/services/firmService'
import { createMatter } from '@/services/matterService'
import { createMemo } from '@/services/memoService'
import { getStatistics } from '@/services/statisticsService'

let db: Database.Database
beforeAll(() => { db = createSchemaDb() })
afterAll(() => db.close())

function round2(n: number): number { return Math.round((n + Number.EPSILON) * 100) / 100 }

describe('statisticsService — property tests', () => {
  it('Property 21: aggregates equal the sum of individual memo values', () => {
    fc.assert(
      fc.property(
        fc.array(
          fc.record({
            nApp: fc.integer({ min: 0, max: 50 }),
            fApp: fc.integer({ min: 0, max: 10000 }),
            misc: fc.integer({ min: 0, max: 10000 }),
          }),
          { minLength: 0, maxLength: 8 },
        ),
        (memos) => {
          truncateAll(db)
          const f = createFirm(db, 'Firm')
          const p = addPartner(db, f.id, 'P')
          const m = createMatter(db, { name: 'M', firmId: f.id, partnerId: p.id })

          let expectApp = 0
          let expectBilled = 0
          memos.forEach((spec, i) => {
            createMemo(db, {
              date: '2026-07-15', matterId: m.id, addresseeLine1: 'A',
              numAppearances: spec.nApp, feesPerAppearance: spec.fApp,
              numConferences: 0, feesPerConference: 0, feesMiscDrafting: spec.misc, tdsRate: 10,
            })
            expectApp += spec.nApp
            expectBilled = round2(expectBilled + round2(spec.nApp * spec.fApp) + spec.misc)
          })

          const stats = getStatistics(db, 'firm')
          return (
            stats.totals.numAppearances === expectApp &&
            Math.abs(stats.totals.amountBilled - expectBilled) < 1e-6 &&
            stats.totals.amountReceived === 0
          )
        },
      ),
      { numRuns: 80 },
    )
  })
})
