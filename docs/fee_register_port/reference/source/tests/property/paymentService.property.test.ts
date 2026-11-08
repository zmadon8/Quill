import { describe, it, beforeAll, afterAll } from 'vitest'
import * as fc from 'fast-check'
import type Database from 'better-sqlite3'
import { createSchemaDb, truncateAll } from '../helpers/testDb'
import { createFirm, addPartner } from '@/services/firmService'
import { createMatter } from '@/services/matterService'
import { createMemo } from '@/services/memoService'
import { addPaymentToMemo, totalPaid, paymentType } from '@/services/paymentService'

let db: Database.Database
beforeAll(() => { db = createSchemaDb() })
afterAll(() => db.close())

function freshMemoWithTotal(total: number): number {
  truncateAll(db)
  const f = createFirm(db, 'Firm')
  const p = addPartner(db, f.id, 'P')
  const m = createMatter(db, { name: 'M', firmId: f.id, partnerId: p.id })
  // Encode the whole total as a single misc-drafting fee for simplicity.
  const memo = createMemo(db, {
    date: '2026-07-15', matterId: m.id, addresseeLine1: 'A',
    numAppearances: 0, feesPerAppearance: 0, numConferences: 0,
    feesPerConference: 0, feesMiscDrafting: total,
  })
  return memo.id
}

const positive = fc.integer({ min: 1, max: 100000 })

describe('paymentService — property tests', () => {
  it('Property 19: aggregate payments determine status and payment type together', () => {
    fc.assert(
      fc.property(positive, fc.array(positive, { minLength: 0, maxLength: 6 }), (total, amounts) => {
        const memoId = freshMemoWithTotal(total)
        for (const a of amounts) {
          addPaymentToMemo(db, memoId, { amount: a, dateOfPayment: '2026-08-01' })
        }
        const sum = amounts.reduce((acc, a) => acc + a, 0)
        const paid = totalPaid(db, memoId)
        const type = paymentType(db, memoId)
        const expectFull = sum >= total
        return (
          Math.abs(paid - sum) < 1e-6 &&
          type === (expectFull ? 'Full' : 'Partial')
        )
      }),
      { numRuns: 150 },
    )
  })
})
