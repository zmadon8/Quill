import { describe, it, expect, beforeEach, beforeAll, afterAll } from 'vitest'
import type Database from 'better-sqlite3'
import { createSchemaDb, truncateAll } from '../helpers/testDb'
import { createFirm, addPartner } from '@/services/firmService'
import { createMatter } from '@/services/matterService'
import { createMemo } from '@/services/memoService'
import { addPaymentToMemo } from '@/services/paymentService'
import { getStatistics, getPivot, getPeriodStatistics, getYearEndSummary } from '@/services/statisticsService'
import { updateSettings } from '@/services/settingsService'

let db: Database.Database
beforeAll(() => { db = createSchemaDb() })
afterAll(() => db.close())
beforeEach(() => {
  truncateAll(db)
  // Statistics now enforce the Initial-FY cutoff server-side (default 2026-27).
  // These tests seed historical FYs (2024-25, 2025-26) on purpose, so set an
  // early Initial FY to exercise the metrics without the cutoff filtering them.
  updateSettings(db, { initialFinancialYear: '2019-20', feebookStartYear: '2019-20' })
})

describe('statisticsService', () => {
  it('aggregates appearances, billed, received by firm', () => {
    const f = createFirm(db, 'Firm')
    const p = addPartner(db, f.id, 'P')
    const m = createMatter(db, { name: 'M', firmId: f.id, partnerId: p.id })
    const memo = createMemo(db, {
      date: '2026-07-15', matterId: m.id, addresseeLine1: 'A',
      numAppearances: 3, feesPerAppearance: 1000, numConferences: 0,
      feesPerConference: 0, feesMiscDrafting: 500, tdsRate: 10,
    })
    addPaymentToMemo(db, memo.id, { amount: 2000, dateOfPayment: '2026-08-01' })

    const stats = getStatistics(db, 'firm')
    expect(stats.rows).toHaveLength(1)
    expect(stats.rows[0].numAppearances).toBe(3)
    expect(stats.rows[0].amountBilled).toBe(3500) // 3*1000 + 500
    expect(stats.rows[0].amountReceived).toBe(2000)
    expect(stats.totals.amountBilled).toBe(3500)
  })

  it('orders financial-year breakdown descending', () => {
    const f = createFirm(db, 'Firm')
    const p = addPartner(db, f.id, 'P')
    const m = createMatter(db, { name: 'M', firmId: f.id, partnerId: p.id })
    createMemo(db, {
      date: '2025-07-15', matterId: m.id, addresseeLine1: 'A',
      numAppearances: 1, feesPerAppearance: 100, numConferences: 0,
      feesPerConference: 0, feesMiscDrafting: 0, tdsRate: 10,
    })
    createMemo(db, {
      date: '2026-07-15', matterId: m.id, addresseeLine1: 'A',
      numAppearances: 1, feesPerAppearance: 100, numConferences: 0,
      feesPerConference: 0, feesMiscDrafting: 0, tdsRate: 10,
    })
    const stats = getStatistics(db, 'financialYear')
    expect(stats.rows.map((r) => r.key)).toEqual(['2026-27', '2025-26'])
  })

  it('year-wise period stats honour the minFinancialYear (Initial FY) cutoff', () => {
    const f = createFirm(db, 'Firm')
    const p = addPartner(db, f.id, 'P')
    const m = createMatter(db, { name: 'M', firmId: f.id, partnerId: p.id })
    const base = { addresseeLine1: 'A', numAppearances: 1, feesPerAppearance: 100, numConferences: 0, feesPerConference: 0, feesMiscDrafting: 0 }
    createMemo(db, { date: '2024-07-15', matterId: m.id, ...base }) // 2024-25
    createMemo(db, { date: '2025-07-15', matterId: m.id, ...base }) // 2025-26
    createMemo(db, { date: '2026-07-15', matterId: m.id, ...base }) // 2026-27

    const all = getPeriodStatistics(db, 'financialYear', null, {})
    expect(all.periods.map((x) => x.key)).toEqual(['2026-27', '2025-26', '2024-25'])

    const capped = getPeriodStatistics(db, 'financialYear', null, { minFinancialYear: '2026-27' })
    expect(capped.periods.map((x) => x.key)).toEqual(['2026-27'])
  })

  it("mattersNew counts a matter only in the FY of its first-ever memo", () => {
    const f = createFirm(db, 'Firm')
    const p = addPartner(db, f.id, 'P')
    const base = { addresseeLine1: 'A', numAppearances: 1, feesPerAppearance: 100, numConferences: 0, feesPerConference: 0, feesMiscDrafting: 0 }

    // Matter A: first memo in 2025-26, another in 2026-27.
    const ma = createMatter(db, { name: 'MA', firmId: f.id, partnerId: p.id })
    createMemo(db, { date: '2025-07-15', matterId: ma.id, ...base })
    createMemo(db, { date: '2026-07-15', matterId: ma.id, ...base })
    // Matter B: born in 2026-27.
    const mb = createMatter(db, { name: 'MB', firmId: f.id, partnerId: p.id })
    createMemo(db, { date: '2026-08-01', matterId: mb.id, ...base })

    const pivot = getPivot(db, { measure: 'mattersNew', rowDim: 'financialYear', colDim: 'none' })
    const byFy: Record<string, number> = {}
    for (const r of pivot.rows) byFy[r.key] = r.total

    expect(byFy['2025-26']).toBe(1) // only MA is new in 2025-26
    expect(byFy['2026-27']).toBe(1) // only MB is new in 2026-27 (MA already existed)
    expect(pivot.grandTotal).toBe(2) // each matter counted exactly once

    // Compare with 'matters' (distinct), where MA appears in BOTH years.
    const distinct = getPivot(db, { measure: 'matters', rowDim: 'financialYear', colDim: 'none' })
    const dByFy: Record<string, number> = {}
    for (const r of distinct.rows) dByFy[r.key] = r.total
    expect(dByFy['2025-26']).toBe(1)
    expect(dByFy['2026-27']).toBe(2) // MA + MB both active in 2026-27
  })

  it('mattersNew ignores memos outside the FY range when deciding "first"', () => {
    const f = createFirm(db, 'Firm')
    const p = addPartner(db, f.id, 'P')
    const base = { addresseeLine1: 'A', numAppearances: 1, feesPerAppearance: 100, numConferences: 0, feesPerConference: 0, feesMiscDrafting: 0 }
    const m = createMatter(db, { name: 'M', firmId: f.id, partnerId: p.id })
    createMemo(db, { date: '2024-07-15', matterId: m.id, ...base }) // true first memo (2024-25)
    createMemo(db, { date: '2026-07-15', matterId: m.id, ...base })

    // Range starts at 2025-26: the matter's first memo predates it, so it is
    // NOT counted as new within the range.
    const pivot = getPivot(db, { measure: 'mattersNew', rowDim: 'financialYear', colDim: 'none', fromFy: '2025-26' })
    expect(pivot.grandTotal).toBe(0)
  })
})

describe('statisticsService — received is attributed by payment date (receipt basis)', () => {
  // A memo billed in FY 2025-26, paid in FY 2026-27.
  function seed() {
    const f = createFirm(db, 'Firm')
    const p = addPartner(db, f.id, 'P')
    const m = createMatter(db, { name: 'M', firmId: f.id, partnerId: p.id })
    const memo = createMemo(db, {
      date: '2026-01-10', matterId: m.id, addresseeLine1: 'A', // FY 2025-26
      numAppearances: 0, feesPerAppearance: 0, numConferences: 0,
      feesPerConference: 0, feesMiscDrafting: 5000,
    })
    // Paid 25 Aug 2026 → FY 2026-27. Net 4500 + 500 TDS = 5000 gross.
    addPaymentToMemo(db, memo.id, { amount: 4500, autoTds: false, tdsAmount: 500, dateOfPayment: '2026-08-25' })
    return { f }
  }

  it('getPeriodStatistics (FY): received counts in the payment year, billed in the memo year', () => {
    seed()
    const byFy = getPeriodStatistics(db, 'financialYear', null, {})
    const p2025 = byFy.periods.find((x) => x.key === '2025-26')!
    const p2026 = byFy.periods.find((x) => x.key === '2026-27')!
    // Billed in 2025-26 (memo year); nothing received that year.
    expect(p2025.amountBilled).toBe(5000)
    expect(p2025.amountReceived).toBe(0)
    // Received in 2026-27 (payment year); nothing billed that year.
    expect(p2026.amountReceived).toBe(4500) // net
    expect(p2026.amountReceivedPlusTds).toBe(5000) // gross
    expect(p2026.amountBilled).toBe(0)
  })

  it('getYearEndSummary: received + TDS fall in the payment year', () => {
    seed()
    const billYear = getYearEndSummary(db, '2025-26')
    expect(billYear.totalBilled).toBe(5000)
    expect(billYear.totalReceived).toBe(0)
    expect(billYear.totalTds).toBe(0)

    const payYear = getYearEndSummary(db, '2026-27')
    expect(payYear.totalBilled).toBe(0)
    expect(payYear.totalReceived).toBe(4500)
    expect(payYear.totalTds).toBe(500)
  })

  it('getStatistics (FY breakdown): received grouped by payment year', () => {
    seed()
    const stats = getStatistics(db, 'financialYear')
    const r2025 = stats.rows.find((x) => x.key === '2025-26')
    const r2026 = stats.rows.find((x) => x.key === '2026-27')
    expect(r2025?.amountBilled).toBe(5000)
    expect(r2025?.amountReceived ?? 0).toBe(0)
    expect(r2026?.amountReceived).toBe(4500)
    // Total received is base-invariant.
    expect(stats.totals.amountReceived).toBe(4500)
  })

  it('getPivot received by financial year uses the payment year', () => {
    seed()
    const pivot = getPivot(db, { measure: 'received', rowDim: 'financialYear', colDim: 'none' })
    const byFy: Record<string, number> = {}
    for (const r of pivot.rows) byFy[r.key] = r.total
    expect(byFy['2026-27']).toBe(4500) // net received, in the payment year
    expect(byFy['2025-26'] ?? 0).toBe(0)
    expect(pivot.grandTotal).toBe(4500)

    const gross = getPivot(db, { measure: 'receivedPlusTds', rowDim: 'financialYear', colDim: 'none' })
    const gByFy: Record<string, number> = {}
    for (const r of gross.rows) gByFy[r.key] = r.total
    expect(gByFy['2026-27']).toBe(5000)
  })
})
