import { describe, it, expect, beforeEach, beforeAll, afterAll } from 'vitest'
import type Database from 'better-sqlite3'
import { createSchemaDb, truncateAll } from '../helpers/testDb'
import { createFirm, addPartner } from '@/services/firmService'
import { createMatter } from '@/services/matterService'
import { createMemo } from '@/services/memoService'
import { addPayment, addPaymentToMemo, updatePayment, getPayment, listPayeesForMatters } from '@/services/paymentService'
import { listFeebook } from '@/services/feebookService'
import { buildLedger, paymentParticulars } from '@/services/ledgerService'

let db: Database.Database
beforeAll(() => { db = createSchemaDb() })
afterAll(() => db.close())
beforeEach(() => truncateAll(db))

function setup() {
  const f = createFirm(db, 'Firm')
  const p = addPartner(db, f.id, 'P')
  const m = createMatter(db, { name: 'Matter One', firmId: f.id, partnerId: p.id })
  const mk = (date: string, total: number) =>
    createMemo(db, {
      date, matterId: m.id, addresseeLine1: 'A',
      numAppearances: 0, feesPerAppearance: 0, numConferences: 0,
      feesPerConference: 0, feesMiscDrafting: total,
    })
  return { m, mk }
}

describe('ledgerService', () => {
  it('builds a running balance with memos before payments on the same day', () => {
    const { m, mk } = setup()
    const a = mk('2026-07-01', 1000)
    const b = mk('2026-08-01', 500)
    // Payment on the same day as memo b: net 600 + TDS 100.
    addPaymentToMemo(db, a.id, {
      amount: 600, autoTds: false, tdsAmount: 100, dateOfPayment: '2026-08-01',
      payee: 'Acme', paymentMode: 'NEFT',
    })
    const rows = buildLedger(db, { matterId: m.id })
    expect(rows).toHaveLength(3)
    expect(rows[0]).toMatchObject({ memoAmount: 1000, balance: 1000 })
    // Same-day: memo b (debit) comes before the payment (credit).
    expect(rows[1]).toMatchObject({ memoAmount: 500, paymentAmount: null, balance: 1500 })
    expect(rows[2]).toMatchObject({ memoAmount: null, paymentAmount: 600, tds: 100, balance: 800 })
    expect(rows[2].particulars).toBe(`Payment by Acme by NEFT against Memo ${a.memoNumber}`)
    expect(b.memoNumber).toBeTruthy()
  })

  it('omits missing payee / mode from the particulars', () => {
    expect(paymentParticulars(null, null, '5 of 2026-27')).toBe('Payment against Memo 5 of 2026-27')
    expect(paymentParticulars('X', null, '1')).toBe('Payment by X against Memo 1')
  })
})

describe('ledger scopes', () => {
  it('limits the ledger to a partner, to chosen matters, or to the whole firm', () => {
    const f = createFirm(db, 'Firm')
    const p1 = addPartner(db, f.id, 'Alpha')
    const p2 = addPartner(db, f.id, 'Beta')
    const m1 = createMatter(db, { name: 'M1', firmId: f.id, partnerId: p1.id })
    const m2 = createMatter(db, { name: 'M2', firmId: f.id, partnerId: p2.id })
    const m3 = createMatter(db, { name: 'M3', firmId: f.id, partnerId: p2.id })
    const mk = (matterId: number, date: string, total: number) =>
      createMemo(db, {
        date, matterId, addresseeLine1: 'A', numAppearances: 0, feesPerAppearance: 0,
        numConferences: 0, feesPerConference: 0, feesMiscDrafting: total,
      })
    mk(m1.id, '2026-07-01', 100)
    mk(m2.id, '2026-07-02', 200)
    mk(m3.id, '2026-07-03', 400)
    expect(buildLedger(db, { firmId: f.id }).at(-1)!.balance).toBe(700)
    expect(buildLedger(db, { firmId: f.id, partnerId: p2.id }).at(-1)!.balance).toBe(600)
    expect(buildLedger(db, { firmId: f.id, matterIds: [m1.id, m3.id] }).at(-1)!.balance).toBe(500)
    expect(buildLedger(db, { firmId: f.id, matterIds: [m2.id] })).toHaveLength(1)
  })
})

describe('paymentService edit', () => {
  it('stores the payment mode and replaces allocations on update', () => {
    const { mk } = setup()
    const a = mk('2026-07-01', 1000)
    const b = mk('2026-07-02', 1000)
    const pay = addPayment(db, {
      amount: 1000, autoTds: false, tdsAmount: 0, dateOfPayment: '2026-07-10', paymentMode: 'Cheque',
      allocations: [{ memoId: a.id, amount: 1000, tdsAmount: 0 }],
    })
    expect(pay.paymentMode).toBe('Cheque')

    const updated = updatePayment(db, pay.id, {
      amount: 1500, autoTds: false, tdsAmount: 0, dateOfPayment: '2026-07-10', paymentMode: 'UPI',
      allocations: [
        { memoId: a.id, amount: 700, tdsAmount: 0 },
        { memoId: b.id, amount: 800, tdsAmount: 0 },
      ],
    })
    expect(updated.paymentMode).toBe('UPI')
    expect(updated.allocations.map((x) => x.memoId).sort()).toEqual([a.id, b.id].sort())
    expect(listFeebook(db, {}).every((r) => r.paymentMode === 'UPI')).toBe(true)

    // An explicit empty list makes it unaccounted.
    const none = updatePayment(db, pay.id, {
      amount: 1500, autoTds: false, tdsAmount: 0, dateOfPayment: '2026-07-10', allocations: [],
    })
    expect(none.allocations).toHaveLength(0)
    expect(getPayment(db, pay.id).memoId).toBeNull()
  })

  it('feebook rows carry the memo total', () => {
    const { mk } = setup()
    const a = mk('2026-07-01', 1234)
    addPaymentToMemo(db, a.id, { amount: 100, dateOfPayment: '2026-07-05' })
    expect(listFeebook(db, {})[0].memoTotal).toBe(1234)
  })
})

describe('payee suggestions', () => {
  it('lists distinct payees used on a matter, most recent first, ignoring blanks and other matters', () => {
    const f = createFirm(db, 'Firm')
    const p = addPartner(db, f.id, 'P')
    const m1 = createMatter(db, { name: 'M1', firmId: f.id, partnerId: p.id })
    const m2 = createMatter(db, { name: 'M2', firmId: f.id, partnerId: p.id })
    const mk = (matterId: number, date: string) =>
      createMemo(db, {
        date, matterId, addresseeLine1: 'A', numAppearances: 0, feesPerAppearance: 0,
        numConferences: 0, feesPerConference: 0, feesMiscDrafting: 1000,
      })
    const a = mk(m1.id, '2026-07-01')
    const b = mk(m1.id, '2026-07-02')
    const other = mk(m2.id, '2026-07-03')
    addPaymentToMemo(db, a.id, { amount: 100, dateOfPayment: '2026-08-01', payee: 'Acme Ltd' })
    addPaymentToMemo(db, a.id, { amount: 100, dateOfPayment: '2026-08-05', payee: 'acme ltd ' })
    addPaymentToMemo(db, b.id, { amount: 100, dateOfPayment: '2026-09-01', payee: 'Beta Corp' })
    addPaymentToMemo(db, b.id, { amount: 100, dateOfPayment: '2026-09-02', payee: '  ' })
    addPaymentToMemo(db, other.id, { amount: 100, dateOfPayment: '2026-09-03', payee: 'Elsewhere' })
    const r = listPayeesForMatters(db, [m1.id])
    expect(r.map((x) => x.payee)).toEqual(['Beta Corp', 'acme ltd']) // latest spelling wins
    expect(r[1].count).toBe(2)
    expect(listPayeesForMatters(db, [])).toEqual([])
    expect(listPayeesForMatters(db, [m1.id, m2.id]).map((x) => x.payee)).toContain('Elsewhere')
  })
})
