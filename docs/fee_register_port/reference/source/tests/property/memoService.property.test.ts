import { describe, it, beforeAll, afterAll } from 'vitest'
import * as fc from 'fast-check'
import type Database from 'better-sqlite3'
import { createSchemaDb, truncateAll } from '../helpers/testDb'
import { createFirm, addPartner } from '@/services/firmService'
import { createMatter, archiveMatter } from '@/services/matterService'
import {
  createMemo,
  createBasedOn,
  computeFeesAppearances,
  computeFeesConferences,
  computeTotalFees,
  computeLessTds,
} from '@/services/memoService'
import type { MemoInput } from '@/types/ipc'

let db: Database.Database
beforeAll(() => { db = createSchemaDb() })
afterAll(() => db.close())

function freshMatter(archived = false): number {
  truncateAll(db)
  const f = createFirm(db, 'Firm')
  const p = addPartner(db, f.id, 'P')
  const m = createMatter(db, { name: 'M', firmId: f.id, partnerId: p.id })
  if (archived) archiveMatter(db, m.id)
  return m.id
}

const money = fc.float({ min: 0, max: 1_000_000, noNaN: true, noDefaultInfinity: true }).map((n) => Math.round(n * 100) / 100)
const count = fc.integer({ min: 0, max: 9999 })
const rate = fc.float({ min: 0, max: 100, noNaN: true, noDefaultInfinity: true }).map((n) => Math.round(n * 100) / 100)

function round2(n: number): number { return Math.round((n + Number.EPSILON) * 100) / 100 }

describe('memoService — property tests', () => {
  it('Property 12 & 13: fee line items = count * rate, total = sum of three', () => {
    fc.assert(
      fc.property(count, money, count, money, money, (nApp, fApp, nConf, fConf, misc) => {
        const feesApp = computeFeesAppearances(nApp, fApp)
        const feesConf = computeFeesConferences(nConf, fConf)
        const total = computeTotalFees(feesApp, feesConf, misc)
        return (
          feesApp === round2(nApp * fApp) &&
          feesConf === round2(nConf * fConf) &&
          total === round2(feesApp + feesConf + misc)
        )
      }),
      { numRuns: 300 },
    )
  })

  it('Property 15: lessTds = total * rate / 100', () => {
    fc.assert(
      fc.property(money, rate, (total, r) => {
        return computeLessTds(total, r) === round2((total * r) / 100)
      }),
      { numRuns: 300 },
    )
  })

  it('Property 7: archived matters reject all memo creation attempts', () => {
    fc.assert(
      fc.property(count, money, (nApp, fApp) => {
        const matterId = freshMatter(true)
        const input: MemoInput = {
          date: '2026-07-15', matterId, addresseeLine1: 'A',
          numAppearances: nApp, feesPerAppearance: fApp,
          numConferences: 0, feesPerConference: 0, feesMiscDrafting: 0,
        }
        try { createMemo(db, input); return false } catch (e) {
          return (e as { code?: string }).code === 'MATTER_ARCHIVED'
        }
      }),
      { numRuns: 60 },
    )
  })

  it('Property 17: memo creation rejected when date is absent', () => {
    fc.assert(
      fc.property(fc.constantFrom('', '  ', 'not-a-date'), (badDate) => {
        const matterId = freshMatter(false)
        const input: MemoInput = {
          date: badDate, matterId, addresseeLine1: 'A',
          numAppearances: 1, feesPerAppearance: 1, numConferences: 0,
          feesPerConference: 0, feesMiscDrafting: 0,
        }
        try { createMemo(db, input); return false } catch (e) {
          return (e as { code?: string }).code === 'INVALID_MEMO'
        }
      }),
      { numRuns: 20 },
    )
  })

  it('Property 18: createBasedOn preserves non-payment fields, clears id/number/date', () => {
    fc.assert(
      fc.property(count, money, fc.string({ maxLength: 30 }), (nApp, fApp, client) => {
        const matterId = freshMatter(false)
        const src = createMemo(db, {
          date: '2026-07-15', matterId, addresseeLine1: 'A', client,
          numAppearances: nApp, feesPerAppearance: fApp,
          numConferences: 0, feesPerConference: 0, feesMiscDrafting: 0,
        })
        const form = createBasedOn(db, src.id)
        return (
          form.date === '' &&
          form.matterId === matterId &&
          form.numAppearances === nApp &&
          form.feesPerAppearance === fApp &&
          (form.client ?? '') === client &&
          !('id' in form) &&
          !('memoNumber' in form)
        )
      }),
      { numRuns: 80 },
    )
  })
})
