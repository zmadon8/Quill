import { describe, it, expect, beforeEach, beforeAll, afterAll } from 'vitest'
import type Database from 'better-sqlite3'
import { createSchemaDb, truncateAll } from '../helpers/testDb'
import { createFirm, addPartner } from '@/services/firmService'
import { createMatter } from '@/services/matterService'
import { createMemo } from '@/services/memoService'
import { addPaymentToMemo, addPayment } from '@/services/paymentService'
import { addBankAccount } from '@/services/settingsService'
import { listFeebook } from '@/services/feebookService'

let db: Database.Database
beforeAll(() => { db = createSchemaDb() })
afterAll(() => db.close())
beforeEach(() => truncateAll(db))

function memo(total: number, date = '2026-07-15') {
  const f = createFirm(db, 'Firm')
  const p = addPartner(db, f.id, 'P')
  const m = createMatter(db, { name: 'M', firmId: f.id, partnerId: p.id })
  return createMemo(db, {
    date, matterId: m.id, addresseeLine1: 'A',
    numAppearances: 0, feesPerAppearance: 0, numConferences: 0,
    feesPerConference: 0, feesMiscDrafting: total,
  })
}

describe('feebookService', () => {
  it('labels single-memo payments "Single" and never exposes payment_details', () => {
    const bank = addBankAccount(db, 'HDFC')
    const mm = memo(1000)
    addPaymentToMemo(db, mm.id, { amount: 400, dateOfPayment: '2026-08-01', bankAccountId: bank.id, paymentDetails: 'secret note' })
    addPaymentToMemo(db, mm.id, { amount: 600, dateOfPayment: '2026-09-01', bankAccountId: bank.id })
    const rows = listFeebook(db, {})
    expect(rows).toHaveLength(2)
    // Each payment is allocated to one memo -> Single (regardless of coverage).
    expect(rows.every((r) => r.paymentType === 'Single')).toBe(true)
    expect(rows.every((r) => r.allocationCount === 1)).toBe(true)
    expect(rows[0].bankAccountName).toBe('HDFC')
    // payment_details must not be present on feebook entries
    expect(Object.keys(rows[0])).not.toContain('paymentDetails')
  })

  it('labels a payment split across memos "Multiple" and lists the group', () => {
    const f = createFirm(db, 'Firm X')
    const p = addPartner(db, f.id, 'PX')
    const m1 = createMatter(db, { name: 'MA', firmId: f.id, partnerId: p.id })
    const m2 = createMatter(db, { name: 'MB', firmId: f.id, partnerId: p.id })
    const a = createMemo(db, { date: '2026-07-15', matterId: m1.id, addresseeLine1: 'A', numAppearances: 0, feesPerAppearance: 0, numConferences: 0, feesPerConference: 0, feesMiscDrafting: 1000 })
    const b = createMemo(db, { date: '2026-07-16', matterId: m2.id, addresseeLine1: 'A', numAppearances: 0, feesPerAppearance: 0, numConferences: 0, feesPerConference: 0, feesMiscDrafting: 1000 })
    // One payment split across both memos.
    addPayment(db, {
      amount: 1500,
      dateOfPayment: '2026-08-01',
      allocations: [
        { memoId: a.id, amount: 1000, tdsAmount: 0 },
        { memoId: b.id, amount: 500, tdsAmount: 0 },
      ],
    })
    const rows = listFeebook(db, {})
    expect(rows).toHaveLength(2) // one row per memo-share
    expect(rows.every((r) => r.paymentType === 'Multiple')).toBe(true)
    expect(rows.every((r) => r.allocationCount === 2)).toBe(true)
    // Each row lists both memos that were paid together.
    const nums = rows[0].groupMemoNumbers.sort()
    expect(nums).toEqual([a.memoNumber, b.memoNumber].sort())
  })

  it('filters unaccounted (memo-less) payments', () => {
    const mm = memo(1000)
    addPaymentToMemo(db, mm.id, { amount: 500, dateOfPayment: '2026-08-01' })
    // insert an unaccounted payment directly (memo_id NULL)
    db.prepare('INSERT INTO payments (memo_id, amount, date_of_payment) VALUES (NULL, ?, ?)').run(200, '2026-08-05')
    expect(listFeebook(db, {})).toHaveLength(2)
    const unaccounted = listFeebook(db, { unaccountedOnly: true })
    expect(unaccounted).toHaveLength(1)
    expect(unaccounted[0].memoNumber).toBeNull()
  })

  it('shows unaccounted payments even when a financial-year filter is active', () => {
    // Regression: a financial-year (or firm/partner) filter must not hide
    // unaccounted payments, which have no memo and thus no financial year.
    const mm = memo(1000, '2026-07-15') // FY 2026-27
    addPaymentToMemo(db, mm.id, { amount: 500, dateOfPayment: '2026-08-01' })
    db.prepare('INSERT INTO payments (memo_id, amount, date_of_payment) VALUES (NULL, ?, ?)').run(200, '2026-08-05')

    const withFyFilter = listFeebook(db, { financialYear: '2026-27' })
    // Both the accounted payment and the unaccounted one appear.
    expect(withFyFilter).toHaveLength(2)
    expect(withFyFilter.some((r) => r.memoId === null)).toBe(true)

    // And it still surfaces under unaccountedOnly together with the FY filter.
    const unaccounted = listFeebook(db, { financialYear: '2026-27', unaccountedOnly: true })
    expect(unaccounted).toHaveLength(1)
    expect(unaccounted[0].memoId).toBeNull()
  })

  it('filters by the PAYMENT date financial year, not the memo billing year', () => {
    // Memo billed in FY 2025-26 (dated 2026-01-10)...
    const mm = memo(5000, '2026-01-10')
    // ...but paid on 25 Aug 2026, which is FY 2026-27.
    addPaymentToMemo(db, mm.id, { amount: 5000, dateOfPayment: '2026-08-25' })

    // The payment must NOT appear under the memo's billing year (2025-26)...
    expect(listFeebook(db, { financialYear: '2025-26' })).toHaveLength(0)
    // ...it belongs to the payment's financial year (2026-27).
    const paidFy = listFeebook(db, { financialYear: '2026-27' })
    expect(paidFy).toHaveLength(1)
    expect(paidFy[0].dateOfPayment).toBe('2026-08-25')

    // A Jan–Mar payment maps to the FY that started the previous April: a
    // second payment on the same memo, dated 15 Feb 2027, is still FY 2026-27.
    addPaymentToMemo(db, mm.id, { amount: 100, dateOfPayment: '2027-02-15' })
    const feb = listFeebook(db, { financialYear: '2026-27' })
    expect(feb.some((r) => r.dateOfPayment === '2027-02-15')).toBe(true)
    // That Feb payment must NOT fall into FY 2027-28.
    expect(listFeebook(db, { financialYear: '2027-28' })).toHaveLength(0)
  })
})
