/**
 * ledgerService.ts
 *
 * A running-balance ledger for a matter (or firm): every issued memo is a debit,
 * every payment allocation is a credit shown as net received plus TDS in separate columns. Rows
 * are in date order; on the same day memos come before payments so the balance
 * never dips below zero because of ordering alone.
 */

import type Database from 'better-sqlite3'
import { prep, round2 } from '@/db/prep'
import { effectiveTotalFees, type MemoFeeColumns } from './memoService'

export interface LedgerRow {
  date: string
  particulars: string
  matterName: string
  /** Debit: the memo's total fees (blank for payment rows). */
  memoAmount: number | null
  /** Credit: amount actually received, EXCLUDING TDS (blank for memo rows). */
  paymentAmount: number | null
  /** Credit: TDS deducted on this payment (blank for memo rows). */
  tds: number | null
  /** Running balance payable after this row. */
  balance: number
}

export interface LedgerScope {
  matterId?: number
  /** Several specific matters (takes effect together with firmId, if given). */
  matterIds?: number[]
  firmId?: number
  /** One group within the firm. */
  partnerId?: number
}

type MemoRow = MemoFeeColumns & {
  id: number
  memo_number: string | null
  date: string
  matter_name: string
  written_off: number
}

type PayRow = {
  memo_number: string | null
  matter_name: string
  amount: number
  tds_amount: number
  date_of_payment: string
  payee: string | null
  payment_mode: string | null
  allocation_id: number
}

/** "Payment by Acme by NEFT against Memo 5 of 2026-27" (omits missing parts). */
export function paymentParticulars(payee: string | null, mode: string | null, memoNumber: string | null): string {
  const parts = ['Payment']
  if (payee && payee.trim()) parts.push(`by ${payee.trim()}`)
  if (mode && mode.trim()) parts.push(`by ${mode.trim()}`)
  parts.push(`against Memo ${memoNumber ?? '(draft)'}`)
  return parts.join(' ')
}

export function buildLedger(db: Database.Database, scope: LedgerScope): LedgerRow[] {
  const where: string[] = ['m.is_draft = 0']
  const params: Record<string, unknown> = {}
  if (scope.matterId !== undefined) {
    where.push('m.matter_id = @matterId')
    params.matterId = scope.matterId
  }
  if (scope.matterIds && scope.matterIds.length > 0) {
    scope.matterIds.forEach((v, i) => (params[`mt${i}`] = v))
    where.push(`m.matter_id IN (${scope.matterIds.map((_, i) => `@mt${i}`).join(', ')})`)
  }
  if (scope.firmId !== undefined) {
    where.push('m.firm_id = @firmId')
    params.firmId = scope.firmId
  }
  if (scope.partnerId !== undefined) {
    where.push('m.partner_id = @partnerId')
    params.partnerId = scope.partnerId
  }
  const whereSql = `WHERE ${where.join(' AND ')}`

  const memos = prep(
    db,
    `SELECT m.id, m.memo_number, m.date, mt.name AS matter_name, m.written_off,
            m.num_appearances, m.fees_per_appearance, m.num_conferences, m.fees_per_conference,
            m.fees_misc_drafting, m.custom_fees_appearances, m.custom_fees_conferences,
            m.custom_fees_misc, m.custom_total_fees
     FROM memos m JOIN matters mt ON mt.id = m.matter_id
     ${whereSql}`,
  ).all(params) as MemoRow[]

  const pays = prep(
    db,
    `SELECT m.memo_number, mt.name AS matter_name, a.amount, a.tds_amount, a.id AS allocation_id,
            p.date_of_payment, p.payee, p.payment_mode
     FROM payment_allocations a
     JOIN payments p ON p.id = a.payment_id
     JOIN memos m ON m.id = a.memo_id
     JOIN matters mt ON mt.id = m.matter_id
     ${whereSql}`,
  ).all(params) as PayRow[]

  // kind 0 = memo, 1 = payment → memos first on the same day.
  type Ev = { date: string; kind: 0 | 1; order: number; row: Omit<LedgerRow, 'balance'> }
  const events: Ev[] = []
  for (const m of memos) {
    events.push({
      date: m.date,
      kind: 0,
      order: m.id,
      row: {
        date: m.date,
        particulars: `Memo ${m.memo_number ?? '(draft)'}${m.written_off ? ' (written off)' : ''}`,
        matterName: m.matter_name,
        memoAmount: effectiveTotalFees(m),
        paymentAmount: null,
        tds: null,
      },
    })
  }
  for (const p of pays) {
    events.push({
      date: p.date_of_payment,
      kind: 1,
      order: p.allocation_id,
      row: {
        date: p.date_of_payment,
        particulars: paymentParticulars(p.payee, p.payment_mode, p.memo_number),
        matterName: p.matter_name,
        memoAmount: null,
        paymentAmount: round2(p.amount),
        tds: round2(p.tds_amount),
      },
    })
  }
  events.sort((a, b) => (a.date !== b.date ? (a.date < b.date ? -1 : 1) : a.kind - b.kind || a.order - b.order))

  let balance = 0
  return events.map((e) => {
    balance = round2(balance + (e.row.memoAmount ?? 0) - (e.row.paymentAmount ?? 0) - (e.row.tds ?? 0))
    return { ...e.row, balance }
  })
}
