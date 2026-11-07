import { describe, it, beforeAll, afterAll, expect } from 'vitest'
import * as fc from 'fast-check'
import type Database from 'better-sqlite3'
import { createSchemaDb, truncateAll } from '../helpers/testDb'
import { createFirm, addPartner } from '@/services/firmService'
import { createMatter } from '@/services/matterService'
import { createMemo, listMemos } from '@/services/memoService'
import { addPaymentToMemo } from '@/services/paymentService'
import { generateBackupBuffer, restoreFromBuffer } from '@/services/backupService'

let db: Database.Database
beforeAll(() => { db = createSchemaDb() })
afterAll(() => db.close())

function snapshot(d: Database.Database) {
  const count = (t: string) => (d.prepare(`SELECT COUNT(*) AS c FROM ${t}`).get() as { c: number }).c
  return {
    firms: count('firms'),
    partners: count('partners'),
    matters: count('matters'),
    memos: count('memos'),
    payments: count('payments'),
    memoNumbers: (d.prepare('SELECT memo_number FROM memos ORDER BY memo_number').all() as Array<{ memo_number: string }>)
      .map((r) => r.memo_number),
  }
}

describe('backupService — property tests', () => {
  it('Property 22: backup → restore preserves all data', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.array(fc.integer({ min: 1, max: 5 }), { minLength: 1, maxLength: 5 }),
        async (memosPerMatter) => {
          truncateAll(db)
          const f = createFirm(db, 'Firm')
          const p = addPartner(db, f.id, 'P')
          memosPerMatter.forEach((nMemos, mi) => {
            const m = createMatter(db, { name: `Matter ${mi}`, firmId: f.id, partnerId: p.id })
            for (let i = 0; i < nMemos; i++) {
              const memo = createMemo(db, {
                date: '2026-07-15', matterId: m.id, addresseeLine1: 'A',
                numAppearances: 1, feesPerAppearance: 1000, numConferences: 0,
                feesPerConference: 0, feesMiscDrafting: 0, tdsRate: 10,
              })
              addPaymentToMemo(db, memo.id, { amount: 500, dateOfPayment: '2026-08-01' })
            }
          })

          const before = snapshot(db)
          const buffer = await generateBackupBuffer(db)
          // Mutate to prove restore truly replaces:
          createMatter(db, { name: 'Noise Matter', firmId: f.id, partnerId: p.id })
          await restoreFromBuffer(db, buffer)
          const after = snapshot(db)

          return JSON.stringify(before) === JSON.stringify(after)
        },
      ),
      { numRuns: 25 },
    )
  })

  it('after restore, new memo numbers continue from the max seq (no reuse)', async () => {
    truncateAll(db)
    const f = createFirm(db, 'Firm')
    const p = addPartner(db, f.id, 'P')
    const m = createMatter(db, { name: 'M', firmId: f.id, partnerId: p.id })
    createMemo(db, { date: '2026-07-15', matterId: m.id, addresseeLine1: 'A', numAppearances: 1, feesPerAppearance: 1, numConferences: 0, feesPerConference: 0, feesMiscDrafting: 0, tdsRate: 10 })
    createMemo(db, { date: '2026-07-16', matterId: m.id, addresseeLine1: 'A', numAppearances: 1, feesPerAppearance: 1, numConferences: 0, feesPerConference: 0, feesMiscDrafting: 0, tdsRate: 10 })
    const buffer = await generateBackupBuffer(db)
    await restoreFromBuffer(db, buffer)
    const next = createMemo(db, { date: '2026-07-17', matterId: m.id, addresseeLine1: 'A', numAppearances: 1, feesPerAppearance: 1, numConferences: 0, feesPerConference: 0, feesMiscDrafting: 0, tdsRate: 10 })
    expect(next.memoNumber).toBe('2026-27/3')
  })
})
