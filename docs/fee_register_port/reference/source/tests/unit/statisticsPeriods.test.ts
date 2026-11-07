import { describe, it, expect, beforeEach, beforeAll, afterAll } from 'vitest'
import type Database from 'better-sqlite3'
import { createSchemaDb, truncateAll } from '../helpers/testDb'
import { createFirm, addPartner } from '@/services/firmService'
import { createMatter } from '@/services/matterService'
import { createMemo } from '@/services/memoService'
import { addPaymentToMemo } from '@/services/paymentService'
import {
  getPeriodStatistics,
  getPivot,
  getYearEndSummary,
  getAnnualBreakdown,
  saveAdjustment,
  listAdjustments,
} from '@/services/statisticsService'
import { updateSettings } from '@/services/settingsService'

let db: Database.Database
beforeAll(() => { db = createSchemaDb() })
afterAll(() => db.close())
beforeEach(() => {
  truncateAll(db)
  updateSettings(db, { initialFinancialYear: '2019-20', feebookStartYear: '2019-20' })
})

// A fixed "now" in the middle of 2025-26 keeps pro-rating out of past months.
const NOW = new Date(2026, 1, 20) // 20 Feb 2026

function world() {
  const f = createFirm(db, 'Firm A')
  const f2 = createFirm(db, 'Firm B')
  const p = addPartner(db, f.id, 'P')
  const p2 = addPartner(db, f2.id, 'P2')
  const m = createMatter(db, { name: 'M1', firmId: f.id, partnerId: p.id })
  const m2 = createMatter(db, { name: 'M2', firmId: f2.id, partnerId: p2.id })
  const mk = (matterId: number, date: string, apps: number, fee: number, extra: Record<string, unknown> = {}) =>
    createMemo(db, {
      date, matterId, addresseeLine1: 'A',
      numAppearances: apps, feesPerAppearance: fee, numConferences: 0,
      feesPerConference: 0, feesMiscDrafting: 0, ...extra,
    })
  return { f, f2, m, m2, mk }
}

describe('quarter-wise statistics', () => {
  it('sums months into FY quarters (Q1 = Apr-Jun) and matches the year total', () => {
    const { m, mk } = world()
    mk(m.id, '2025-04-10', 2, 1000) // Q1
    mk(m.id, '2025-06-10', 1, 1000) // Q1
    mk(m.id, '2025-08-10', 4, 1000) // Q2
    mk(m.id, '2026-01-10', 3, 1000) // Q4
    const q = getPeriodStatistics(db, 'quarter', '2025-26', {}, NOW)
    expect(q.periods.map((p) => p.key)).toEqual(['2025-26-Q1', '2025-26-Q2', '2025-26-Q3', '2025-26-Q4'])
    expect(q.periods.map((p) => p.numAppearances)).toEqual([3, 4, 0, 3])
    expect(q.periods[0].amountBilled).toBe(3000)

    const y = getPeriodStatistics(db, 'financialYear', null, {}, NOW).periods.find((p) => p.key === '2025-26')!
    expect(y.numAppearances).toBe(10)
    expect(y.amountBilled).toBe(10000)
  })
})

describe('recovered, fees per day and overrides', () => {
  it('recovered counts gross paid on memos ISSUED in the period, whenever paid', () => {
    const { m, mk } = world()
    const a = mk(m.id, '2025-04-10', 1, 1000)
    addPaymentToMemo(db, a.id, { amount: 400, dateOfPayment: '2025-07-01' }) // paid in Q2
    const apr = getPeriodStatistics(db, 'month', '2025-26', {}, NOW).periods.find((p) => p.month === 4)!
    expect(apr.amountRecovered).toBe(400)
    expect(apr.percentRecovered).toBe(40)
    const jul = getPeriodStatistics(db, 'month', '2025-26', {}, NOW).periods.find((p) => p.month === 7)!
    expect(jul.amountReceived).toBe(400) // receipt basis
    expect(jul.amountRecovered).toBe(0)
  })

  it('fees per day = billed ÷ days completed', () => {
    const { m, mk } = world()
    mk(m.id, '2025-04-10', 1, 1000)
    saveAdjustment(db, { financialYear: '2025-26', month: 4, workingDays: 20, extraAppearances: 0, extraConferences: 0, extraDrafts: 0 })
    const apr = getPeriodStatistics(db, 'month', '2025-26', {}, NOW).periods.find((p) => p.month === 4)!
    expect(apr.feesPerDay).toBe(50)
  })

  it('a monthly override replaces the computed value and rolls into quarter / year', () => {
    const { m, mk } = world()
    mk(m.id, '2025-04-10', 2, 1000)
    saveAdjustment(db, {
      financialYear: '2025-26', month: 4, workingDays: 0, extraAppearances: 0, extraConferences: 0, extraDrafts: 0,
      overrideAppearances: 9, overrideBilled: 5000,
    })
    const apr = getPeriodStatistics(db, 'month', '2025-26', {}, NOW).periods.find((p) => p.month === 4)!
    expect(apr.numAppearances).toBe(9)
    expect(apr.amountBilled).toBe(5000)
    expect(apr.overridden).toEqual(expect.arrayContaining(['numAppearances', 'amountBilled']))
    const q1 = getPeriodStatistics(db, 'quarter', '2025-26', {}, NOW).periods[0]
    expect(q1.numAppearances).toBe(9)
    const y = getPeriodStatistics(db, 'financialYear', null, {}, NOW).periods.find((p) => p.key === '2025-26')!
    expect(y.amountBilled).toBe(5000)
    // Blank override (null) goes back to the computed figure.
    saveAdjustment(db, { financialYear: '2025-26', month: 4, workingDays: 0, extraAppearances: 0, extraConferences: 0, extraDrafts: 0 })
    expect(listAdjustments(db, '2025-26')[0].overrideAppearances).toBeNull()
    expect(getPeriodStatistics(db, 'month', '2025-26', {}, NOW).periods.find((p) => p.month === 4)!.numAppearances).toBe(2)
  })
})

describe('include draft memos', () => {
  it('counts a draft in the CURRENT month only when asked', () => {
    const { m } = world()
    createMemo(
      db,
      {
        date: '', matterId: m.id, addresseeLine1: 'A',
        numAppearances: 2, feesPerAppearance: 500, numConferences: 0, feesPerConference: 0, feesMiscDrafting: 0,
      },
      true,
    )
    const feb = (opts: object) =>
      getPeriodStatistics(db, 'month', '2025-26', opts, NOW).periods.find((p) => p.month === 2)!
    expect(feb({}).amountBilled).toBe(0)
    expect(feb({ includeDrafts: true }).amountBilled).toBe(1000)
    expect(feb({ includeDrafts: true }).numAppearances).toBe(2)
  })
})

describe('year-end summary and annual breakdown', () => {
  it('year-end appearances agree with the statistics table', () => {
    const { m, mk } = world()
    mk(m.id, '2025-04-10', 3, 100)
    saveAdjustment(db, { financialYear: '2025-26', month: 5, workingDays: 0, extraAppearances: 4, extraConferences: 0, extraDrafts: 0 })
    const ye = getYearEndSummary(db, '2025-26')
    expect(ye.numAppearances).toBe(7)
  })

  it('breaks a year down per firm and per matter, with receipts by payment date', () => {
    const { m, m2, mk } = world()
    const a = mk(m.id, '2025-04-10', 1, 1000)
    mk(m2.id, '2025-05-10', 2, 500)
    addPaymentToMemo(db, a.id, { amount: 600, autoTds: false, tdsAmount: 60, dateOfPayment: '2025-09-01' })
    const byFirm = getAnnualBreakdown(db, '2025-26', 'firm')
    expect(byFirm.map((r) => r.name)).toEqual(['Firm A', 'Firm B'])
    expect(byFirm[0]).toMatchObject({ memos: 1, billed: 1000, received: 600, tds: 60 })
    expect(byFirm[1]).toMatchObject({ memos: 1, appearances: 2, billed: 1000, received: 0 })
    const byMatter = getAnnualBreakdown(db, '2025-26', 'matter')
    expect(byMatter.map((r) => r.firmName)).toEqual(['Firm A', 'Firm B'])
  })
})

describe('pivot extras', () => {
  it('filters by several firms', () => {
    const { f, f2, m, m2, mk } = world()
    mk(m.id, '2025-04-10', 1, 1000)
    mk(m2.id, '2025-04-11', 1, 300)
    const both = getPivot(db, { measure: 'billed', rowDim: 'financialYear', colDim: 'none', firmIds: [f.id, f2.id] })
    expect(both.grandTotal).toBe(1300)
    const one = getPivot(db, { measure: 'billed', rowDim: 'financialYear', colDim: 'none', firmIds: [f2.id] })
    expect(one.grandTotal).toBe(300)
    const all = getPivot(db, { measure: 'billed', rowDim: 'financialYear', colDim: 'none' })
    expect(all.grandTotal).toBe(1300)
  })

  it('per-week measures come from the period engine and need time rows', () => {
    const { m, mk } = world()
    mk(m.id, '2025-04-10', 5, 100)
    saveAdjustment(db, { financialYear: '2025-26', month: 4, workingDays: 20, extraAppearances: 0, extraConferences: 0, extraDrafts: 0 })
    const r = getPivot(db, { measure: 'appearancesPerWeek', rowDim: 'month', colDim: 'none', fromFy: '2025-26', toFy: '2025-26' })
    const apr = r.rows.find((x) => x.label.startsWith('Apr'))!
    expect(apr.total).toBe(1.25) // 5 * 5 / 20
    expect(() => getPivot(db, { measure: 'appearancesPerWeek', rowDim: 'firm', colDim: 'none' })).toThrow()
  })
})
