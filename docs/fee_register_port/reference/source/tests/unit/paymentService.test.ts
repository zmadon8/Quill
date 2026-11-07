import { describe, it, expect, beforeEach, beforeAll, afterAll } from 'vitest'
import type Database from 'better-sqlite3'
import { createSchemaDb, truncateAll } from '../helpers/testDb'
import { createFirm, addPartner } from '@/services/firmService'
import { createMatter } from '@/services/matterService'
import { createMemo } from '@/services/memoService'
import {
  addPaymentToMemo,
  addPayment,
  addUnaccountedPayment,
  assignPaymentToMemo,
  updatePayment,
  deletePayment,
  listPaymentsForMemo,
  paymentType,
  computeAutoTds,
} from '@/services/paymentService'
import { getMemo } from '@/services/memoService'

let db: Database.Database
beforeAll(() => { db = createSchemaDb() })
afterAll(() => db.close())
beforeEach(() => truncateAll(db))

function expectCode(fn: () => unknown, code: string): void {
  try { fn() } catch (err) { expect((err as { code?: string }).code).toBe(code); return }
  throw new Error(`Expected AppError with code ${code}`)
}

function memoWithTotal(total: number): number {
  const f = createFirm(db, 'Firm')
  const p = addPartner(db, f.id, 'P')
  const m = createMatter(db, { name: 'M', firmId: f.id, partnerId: p.id })
  return createMemo(db, {
    date: '2026-07-15', matterId: m.id, addresseeLine1: 'A',
    numAppearances: 0, feesPerAppearance: 0, numConferences: 0,
    feesPerConference: 0, feesMiscDrafting: total,
  }).id
}

describe('paymentService', () => {
  it('auto-populates memoAmount from total fees on first payment', () => {
    const memoId = memoWithTotal(5000)
    const pay = addPaymentToMemo(db, memoId, { amount: 1000, dateOfPayment: '2026-08-01' })
    expect(pay.memoAmount).toBe(5000)
    expect(pay.amount).toBe(1000)
  })

  it('rejects a non-positive amount', () => {
    const memoId = memoWithTotal(5000)
    expectCode(() => addPaymentToMemo(db, memoId, { amount: 0, dateOfPayment: '2026-08-01' }), 'INVALID_PAYMENT')
    expectCode(() => addPaymentToMemo(db, memoId, { amount: -5, dateOfPayment: '2026-08-01' }), 'INVALID_PAYMENT')
  })

  it('supports multiple payments; partial then full', () => {
    const memoId = memoWithTotal(1000)
    addPaymentToMemo(db, memoId, { amount: 400, dateOfPayment: '2026-08-01' })
    expect(paymentType(db, memoId)).toBe('Partial')
    addPaymentToMemo(db, memoId, { amount: 600, dateOfPayment: '2026-09-01' })
    expect(paymentType(db, memoId)).toBe('Full')
    expect(listPaymentsForMemo(db, memoId)).toHaveLength(2)
  })

  it('computeAutoTds grosses up the net amount by the rate', () => {
    // 45000 net at 10% TDS → TDS 5000 (gross 50000).
    expect(computeAutoTds(45000, 10)).toBe(5000)
    expect(computeAutoTds(1000, 0)).toBe(0)
  })

  it('auto TDS makes a single payment clear a memo via gross payment', () => {
    const memoId = memoWithTotal(50000)
    const pay = addPaymentToMemo(db, memoId, {
      amount: 45000,
      tdsRate: 10,
      autoTds: true,
      dateOfPayment: '2026-08-01',
    })
    expect(pay.tdsAmount).toBe(5000)
    expect(pay.grossAmount).toBe(50000)
    // Gross (45000 + 5000) == memo amount → Paid.
    expect(getMemo(db, memoId).status).toBe('Paid')
    expect(getMemo(db, memoId).amountPaid).toBe(50000)
  })

  it('manual TDS (autoTds off) uses the entered tdsAmount', () => {
    const memoId = memoWithTotal(50000)
    const pay = addPaymentToMemo(db, memoId, {
      amount: 45000,
      tdsRate: 10,
      autoTds: false,
      tdsAmount: 3000,
      dateOfPayment: '2026-08-01',
    })
    expect(pay.tdsAmount).toBe(3000)
    expect(pay.grossAmount).toBe(48000)
    // Gross 48000 < 50000 → still Unpaid.
    expect(getMemo(db, memoId).status).toBe('Unpaid')
  })

  it('unaccounted payment can be created then assigned to a memo', () => {
    const memoId = memoWithTotal(5000)
    const pay = addUnaccountedPayment(db, { amount: 5000, dateOfPayment: '2026-08-01' })
    expect(pay.memoId).toBeNull()
    const assigned = assignPaymentToMemo(db, pay.id, memoId)
    expect(assigned.memoId).toBe(memoId)
    // Now the memo sees the payment.
    expect(getMemo(db, memoId).status).toBe('Paid')
  })

  it('updates and deletes payments', () => {
    const memoId = memoWithTotal(1000)
    const pay = addPaymentToMemo(db, memoId, { amount: 100, dateOfPayment: '2026-08-01' })
    const updated = updatePayment(db, pay.id, { amount: 250, dateOfPayment: '2026-08-02', payee: 'X' })
    expect(updated.amount).toBe(250)
    expect(updated.payee).toBe('X')
    deletePayment(db, pay.id)
    expect(listPaymentsForMemo(db, memoId)).toHaveLength(0)
  })
})

describe('paymentService — multi-memo allocation (Req #5)', () => {
  function twoMemos() {
    const f = createFirm(db, 'Firm')
    const p = addPartner(db, f.id, 'P')
    const m = createMatter(db, { name: 'M', firmId: f.id, partnerId: p.id })
    const a = createMemo(db, {
      date: '2026-07-15', matterId: m.id, addresseeLine1: 'A',
      numAppearances: 0, feesPerAppearance: 0, numConferences: 0,
      feesPerConference: 0, feesMiscDrafting: 5000, numDrafts: 0,
    })
    const b = createMemo(db, {
      date: '2026-07-16', matterId: m.id, addresseeLine1: 'A',
      numAppearances: 0, feesPerAppearance: 0, numConferences: 0,
      feesPerConference: 0, feesMiscDrafting: 3000, numDrafts: 0,
    })
    return { a: a.id, b: b.id }
  }

  it('splits one payment across two memos and clears both', () => {
    const { a, b } = twoMemos()
    addPayment(db, {
      amount: 8000,
      dateOfPayment: '2026-08-01',
      allocations: [
        { memoId: a, amount: 5000, tdsAmount: 0 },
        { memoId: b, amount: 3000, tdsAmount: 0 },
      ],
    })
    expect(getMemo(db, a).status).toBe('Paid')
    expect(getMemo(db, a).amountPaid).toBe(5000)
    expect(getMemo(db, b).status).toBe('Paid')
    expect(getMemo(db, b).amountPaid).toBe(3000)
  })

  it('a payment with no allocations is unaccounted and affects no memo', () => {
    const { a } = twoMemos()
    const pay = addPayment(db, { amount: 1000, dateOfPayment: '2026-08-01' })
    expect(pay.memoId).toBeNull()
    expect(pay.allocations).toHaveLength(0)
    expect(getMemo(db, a).amountPaid).toBe(0)
  })

  it('each memo-share appears as its own Feebook row', () => {
    const { a, b } = twoMemos()
    addPayment(db, {
      amount: 8000,
      dateOfPayment: '2026-08-01',
      allocations: [
        { memoId: a, amount: 5000, tdsAmount: 0 },
        { memoId: b, amount: 3000, tdsAmount: 0 },
      ],
    })
    // listPaymentsForMemo narrows to the memo's own share.
    const forA = listPaymentsForMemo(db, a)
    expect(forA).toHaveLength(1)
    expect(forA[0].amount).toBe(5000)
  })
})
