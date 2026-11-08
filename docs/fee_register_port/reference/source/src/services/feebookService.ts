/**
 * feebookService.ts
 *
 * Produces the Feebook view: one row per payment ALLOCATION (a memo's share of
 * a payment), plus a row for each unaccounted payment (no allocation). This way
 * a payment split across several memos shows one line per memo. Payment Type
 * is Single (one memo) or Multiple (split across memos), with the sibling memo
 * numbers surfaced so the user can see which memos were paid together.
 * `payment_details` is excluded.
 */

import type Database from 'better-sqlite3'
import type { FeebookFilter, FeebookEntry } from '@/types/ipc'
import { grossPayment } from './paymentService'
import { getSettings } from './settingsService'
import { effectiveTotalFees, type MemoFeeColumns } from './memoService'
import { prep } from '@/db/prep'
import { financialYearOfDateSql } from '@/db/memoSql'

type AllocRow = MemoFeeColumns & {
  payment_id: number
  allocation_id: number
  memo_id: number
  memo_number: string | null
  firm_id: number | null
  firm_name: string | null
  matter_id: number | null
  matter_name: string | null
  amount: number
  tds_amount: number
  payee: string | null
  date_of_payment: string
  bank_account_id: number | null
  bank_account_name: string | null
  payment_mode: string | null
}

type UnallocRow = {
  payment_id: number
  amount: number
  tds_amount: number
  payee: string | null
  date_of_payment: string
  bank_account_id: number | null
  bank_account_name: string | null
  payment_mode: string | null
}

export function listFeebook(db: Database.Database, filter: FeebookFilter = {}): FeebookEntry[] {
  // Enforce the Initial-FY cutoff on the server: never surface payments whose
  // payment financial year is before the configured Initial FY, regardless of
  // what the renderer requests (payments pre-dating active record-keeping are
  // historical only).
  const initialFy = getSettings(db).feebookStartYear

  // --- Allocated rows (one per memo-share) ---
  const where: string[] = [`${financialYearOfDateSql('p.date_of_payment')} >= @initialFy`]
  const params: Record<string, unknown> = { initialFy }

  if (filter.financialYear) {
    // The Feebook is a record of PAYMENTS, so the financial-year filter is based
    // on the payment date (not the memo's financial year, which is when it was
    // billed). A memo billed in one FY can be paid in a later FY.
    where.push(`${financialYearOfDateSql('p.date_of_payment')} = @financialYear`)
    params.financialYear = filter.financialYear
  }
  if (filter.firmId !== undefined) {
    where.push('m.firm_id = @firmId')
    params.firmId = filter.firmId
  }
  if (filter.partnerId !== undefined && filter.partnerId !== 'none') {
    where.push('m.partner_id = @partnerId')
    params.partnerId = filter.partnerId
  }
  if (filter.bankAccountId !== undefined) {
    where.push('p.bank_account_id = @bankAccountId')
    params.bankAccountId = filter.bankAccountId
  }
  const whereSql = where.length ? `WHERE ${where.join(' AND ')}` : ''

  const entries: FeebookEntry[] = []

  // Per-payment: how many memos it was allocated across, and their memo numbers.
  // Used to label each row Single vs Multiple and to list the memos settled
  // together by one payment.
  const groupByPayment = new Map<number, string[]>()
  {
    const rows = prep(
      db,
      `SELECT a.payment_id AS pid, m.memo_number AS num
       FROM payment_allocations a
       JOIN memos m ON m.id = a.memo_id
       ORDER BY a.payment_id ASC, a.id ASC`,
    ).all() as Array<{ pid: number; num: string | null }>
    for (const r of rows) {
      const list = groupByPayment.get(r.pid) ?? []
      list.push(r.num ?? '(draft)')
      groupByPayment.set(r.pid, list)
    }
  }

  // Unaccounted-only filter: show only payments with zero allocations.
  if (!filter.unaccountedOnly) {
    const allocRows = prep(
      db,
      `SELECT p.id AS payment_id, a.id AS allocation_id, a.memo_id, m.memo_number,
              m.firm_id, f.name AS firm_name, m.matter_id, mt.name AS matter_name,
              a.amount, a.tds_amount, p.payee, p.date_of_payment,
              p.bank_account_id, b.name AS bank_account_name, p.payment_mode,
              m.num_appearances, m.fees_per_appearance, m.num_conferences, m.fees_per_conference,
              m.fees_misc_drafting, m.custom_fees_appearances, m.custom_fees_conferences,
              m.custom_fees_misc, m.custom_total_fees
       FROM payment_allocations a
       JOIN payments p ON p.id = a.payment_id
       JOIN memos m ON m.id = a.memo_id
       LEFT JOIN firms f ON f.id = m.firm_id
       LEFT JOIN matters mt ON mt.id = m.matter_id
       LEFT JOIN bank_accounts b ON b.id = p.bank_account_id
       ${whereSql}
       ORDER BY p.date_of_payment DESC, p.id DESC, a.id ASC`,
    ).all(params) as AllocRow[]

    for (const r of allocRows) {
      const group = groupByPayment.get(r.payment_id) ?? []
      const allocationCount = group.length
      const isMultiple = allocationCount > 1
      entries.push({
        paymentId: r.payment_id,
        allocationId: r.allocation_id,
        memoId: r.memo_id,
        memoNumber: r.memo_number,
        memoTotal: effectiveTotalFees(r),
        firmId: r.firm_id,
        firmName: r.firm_name,
        matterId: r.matter_id,
        matterName: r.matter_name,
        amountPaid: r.amount,
        tds: r.tds_amount,
        paidPlusTds: grossPayment(r.amount, r.tds_amount),
        payee: r.payee,
        dateOfPayment: r.date_of_payment,
        bankAccountId: r.bank_account_id,
        bankAccountName: r.bank_account_name,
        paymentMode: r.payment_mode,
        paymentType: isMultiple ? 'Multiple' : 'Single',
        allocationCount,
        // The memos settled together by this payment (only meaningful if >1).
        groupMemoNumbers: isMultiple ? group : [],
      })
    }
  }

  // --- Unaccounted rows (payments with no allocation) ---
  // Shown always (unless a bank filter excludes them); surfaced via the
  // "Unaccounted memos only" toggle. Not constrained by memo-based filters.
  const unaccWhere: string[] = [
    'NOT EXISTS (SELECT 1 FROM payment_allocations a WHERE a.payment_id = p.id)',
    `${financialYearOfDateSql('p.date_of_payment')} >= @initialFy`,
  ]
  const unaccParams: Record<string, unknown> = { initialFy }
  if (filter.bankAccountId !== undefined) {
    unaccWhere.push('p.bank_account_id = @bankAccountId')
    unaccParams.bankAccountId = filter.bankAccountId
  }
  // Unaccounted payments have a date too, so honour the FY filter by their date.
  if (filter.financialYear) {
    unaccWhere.push(`${financialYearOfDateSql('p.date_of_payment')} = @financialYear`)
    unaccParams.financialYear = filter.financialYear
  }
  const unaccRows = prep(
    db,
    `SELECT p.id AS payment_id, p.amount, p.tds_amount, p.payee, p.date_of_payment,
            p.bank_account_id, b.name AS bank_account_name, p.payment_mode
     FROM payments p
     LEFT JOIN bank_accounts b ON b.id = p.bank_account_id
     WHERE ${unaccWhere.join(' AND ')}
     ORDER BY p.date_of_payment DESC, p.id DESC`,
  ).all(unaccParams) as UnallocRow[]

  for (const r of unaccRows) {
    entries.push({
      paymentId: r.payment_id,
      allocationId: null,
      memoId: null,
      memoNumber: null,
      memoTotal: null,
      firmId: null,
      firmName: null,
      matterId: null,
      matterName: null,
      amountPaid: r.amount,
      tds: r.tds_amount,
      paidPlusTds: grossPayment(r.amount, r.tds_amount),
      payee: r.payee,
      dateOfPayment: r.date_of_payment,
      bankAccountId: r.bank_account_id,
      bankAccountName: r.bank_account_name,
      paymentMode: r.payment_mode,
      paymentType: 'Single',
      allocationCount: 1,
      groupMemoNumbers: [],
    })
  }

  // Sort combined by date desc, then payment id desc.
  entries.sort((a, b) => {
    if (a.dateOfPayment !== b.dateOfPayment) return a.dateOfPayment < b.dateOfPayment ? 1 : -1
    return b.paymentId - a.paymentId
  })

  return entries
}
