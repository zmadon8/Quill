/**
 * paymentService.ts
 *
 * Pure, testable business logic for Payments. A received payment can be
 * allocated across one, several, or zero memos via the payment_allocations
 * table (the source of truth for how much a memo has been paid).
 *
 *   - Zero allocations  → an "unaccounted" payment (memo attached later).
 *   - One allocation    → a normal single-memo payment.
 *   - Many allocations  → one payment split across multiple memos.
 *
 * A memo's paid amount = SUM(amount + tds_amount) of its allocations (GROSS,
 * since TDS is money paid on the client's behalf toward the memo).
 *
 * `paymentDetails` is stored but is an internal note — excluded from exports.
 */

import type Database from 'better-sqlite3'
import { AppError } from '@/types/ipc'
import type { PaymentInput, PaymentDTO, PaymentAllocationDTO, MatterPayee } from '@/types/ipc'
import { effectiveTotalFees, type MemoFeeColumns } from './memoService'
import { prep, round2 } from '@/db/prep'

type PaymentRow = {
  id: number
  memo_id: number | null
  amount: number
  tds_rate: number
  auto_tds: number
  tds_amount: number
  memo_amount: number
  date_of_payment: string
  payee: string | null
  bank_account_id: number | null
  payment_details: string | null
  payment_mode: string | null
}

type AllocationRow = {
  id: number
  payment_id: number
  memo_id: number
  amount: number
  tds_amount: number
}

/**
 * Computes the TDS amount for a payment when auto-calculation is on:
 *   tds = amount * 100 / (100 - rate) - amount
 */
export function computeAutoTds(amount: number, tdsRate: number): number {
  if (!(tdsRate > 0)) return 0
  if (tdsRate >= 100) return 0
  return round2((amount * 100) / (100 - tdsRate) - amount)
}

/** Gross payment = net amount received + TDS withheld. */
export function grossPayment(amount: number, tdsAmount: number): number {
  return round2(amount + tdsAmount)
}

function resolveTdsAmount(input: PaymentInput): number {
  const auto = input.autoTds ?? true
  if (auto) return computeAutoTds(input.amount, input.tdsRate ?? 0)
  return round2(input.tdsAmount ?? 0)
}

function listAllocations(db: Database.Database, paymentId: number): PaymentAllocationDTO[] {
  const rows = prep(
    db,
    `SELECT a.id, a.payment_id, a.memo_id, a.amount, a.tds_amount, m.memo_number
     FROM payment_allocations a
     LEFT JOIN memos m ON m.id = a.memo_id
     WHERE a.payment_id = ?
     ORDER BY a.id ASC`,
  ).all(paymentId) as Array<AllocationRow & { memo_number: string | null }>
  return rows.map((r) => ({
    id: r.id,
    paymentId: r.payment_id,
    memoId: r.memo_id,
    memoNumber: r.memo_number,
    amount: r.amount,
    tdsAmount: r.tds_amount,
    grossAmount: grossPayment(r.amount, r.tds_amount),
  }))
}

function toDTO(db: Database.Database, r: PaymentRow): PaymentDTO {
  const allocations = listAllocations(db, r.id)
  // For a single-memo payment, surface its memo for convenience.
  const singleMemoId = allocations.length === 1 ? allocations[0].memoId : null
  const memoAmount = singleMemoId !== null ? memoTotalFees(db, singleMemoId) : r.memo_amount
  return {
    id: r.id,
    memoId: singleMemoId,
    amount: r.amount,
    tdsRate: r.tds_rate,
    autoTds: r.auto_tds === 1,
    tdsAmount: r.tds_amount,
    grossAmount: grossPayment(r.amount, r.tds_amount),
    memoAmount,
    dateOfPayment: r.date_of_payment,
    payee: r.payee,
    bankAccountId: r.bank_account_id,
    paymentDetails: r.payment_details,
    paymentMode: r.payment_mode,
    allocations,
  }
}

function validate(input: PaymentInput): void {
  if (!(input.amount > 0)) {
    throw new AppError('INVALID_PAYMENT', 'Payment amount must be greater than 0')
  }
  if (!input.dateOfPayment || !/^\d{4}-\d{2}-\d{2}/.test(input.dateOfPayment)) {
    throw new AppError('INVALID_PAYMENT', 'A valid date of payment is required')
  }
  if (input.tdsRate !== undefined && (input.tdsRate < 0 || input.tdsRate >= 100)) {
    throw new AppError('INVALID_PAYMENT', 'TDS rate must be between 0 and 100')
  }
}

/** Returns the memo's effective total fees (honouring custom overrides). */
export function memoTotalFees(db: Database.Database, memoId: number): number {
  const m = prep(
    db,
    `SELECT num_appearances, fees_per_appearance, num_conferences,
            fees_per_conference, fees_misc_drafting,
            custom_fees_appearances, custom_fees_conferences, custom_fees_misc, custom_total_fees
     FROM memos WHERE id = ?`,
  ).get(memoId) as MemoFeeColumns | undefined
  if (!m) return 0
  return effectiveTotalFees(m)
}

/** Sum of GROSS allocations (amount + TDS) applied to a memo. */
export function totalPaid(db: Database.Database, memoId: number): number {
  const row = prep(
    db,
    'SELECT COALESCE(SUM(amount + tds_amount), 0) AS paid FROM payment_allocations WHERE memo_id = ?',
  ).get(memoId) as { paid: number }
  return round2(row.paid)
}

/** Sum of NET allocation amounts (excluding TDS) applied to a memo. */
export function totalNetReceived(db: Database.Database, memoId: number): number {
  const row = prep(
    db,
    'SELECT COALESCE(SUM(amount), 0) AS paid FROM payment_allocations WHERE memo_id = ?',
  ).get(memoId) as { paid: number }
  return round2(row.paid)
}

/** Derives Full/Partial for a memo based on gross allocations vs memo amount. */
export function paymentType(db: Database.Database, memoId: number): 'Full' | 'Partial' {
  const total = memoTotalFees(db, memoId)
  const paid = totalPaid(db, memoId)
  return paid >= total ? 'Full' : 'Partial'
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/** Inserts the payments row and returns its new id. */
function insertPaymentRow(db: Database.Database, input: PaymentInput, tdsAmount: number): number {
  const info = prep(
    db,
    `INSERT INTO payments (
       memo_id, amount, tds_rate, auto_tds, tds_amount, memo_amount, date_of_payment,
       payee, bank_account_id, payment_details, payment_mode
     ) VALUES (NULL, @amount, @tdsRate, @autoTds, @tds, 0, @date, @payee, @bank, @details, @mode)`,
  ).run({
    amount: input.amount,
    tdsRate: input.tdsRate ?? 0,
    autoTds: (input.autoTds ?? true) ? 1 : 0,
    tds: tdsAmount,
    date: input.dateOfPayment,
    payee: input.payee ?? null,
    bank: input.bankAccountId ?? null,
    details: input.paymentDetails ?? null,
    mode: input.paymentMode?.trim() || null,
  })
  return Number(info.lastInsertRowid)
}

/**
 * Replaces the allocations for a payment. Each allocation records the memo it
 * applies to and the net + TDS portions. When exactly one allocation exists the
 * payment's legacy memo_id is synced to it (else NULL).
 */
function writeAllocations(
  db: Database.Database,
  paymentId: number,
  allocations: Array<{ memoId: number; amount: number; tdsAmount: number }>,
): void {
  prep(db, 'DELETE FROM payment_allocations WHERE payment_id = ?').run(paymentId)
  const ins = prep(
    db,
    'INSERT INTO payment_allocations (payment_id, memo_id, amount, tds_amount) VALUES (?, ?, ?, ?)',
  )
  for (const a of allocations) {
    const memo = prep(db, 'SELECT id FROM memos WHERE id = ?').get(a.memoId) as { id: number } | undefined
    if (!memo) throw new AppError('MEMO_NOT_FOUND', `Memo ${a.memoId} not found`)
    ins.run(paymentId, a.memoId, round2(a.amount), round2(a.tdsAmount))
  }
  const singleMemo = allocations.length === 1 ? allocations[0].memoId : null
  prep(db, 'UPDATE payments SET memo_id = ? WHERE id = ?').run(singleMemo, paymentId)
}

/**
 * Derives default allocations from a payment input. If the caller supplied an
 * explicit `allocations` array, that is used as-is. Otherwise, when a single
 * memo is targeted the whole payment is allocated to it; with no memo it is
 * left unaccounted (no allocations).
 */
function resolveAllocations(
  input: PaymentInput,
  tdsAmount: number,
  singleMemoId: number | null,
): Array<{ memoId: number; amount: number; tdsAmount: number }> {
  if (input.allocations && input.allocations.length > 0) {
    return input.allocations.map((a) => ({
      memoId: a.memoId,
      amount: round2(a.amount),
      tdsAmount: round2(a.tdsAmount ?? 0),
    }))
  }
  if (singleMemoId !== null) {
    return [{ memoId: singleMemoId, amount: input.amount, tdsAmount }]
  }
  return []
}

// ---------------------------------------------------------------------------
// CRUD
// ---------------------------------------------------------------------------

/** Adds a payment allocated wholly to one memo (used by the memo Payment modal). */
export function addPaymentToMemo(
  db: Database.Database,
  memoId: number,
  input: PaymentInput,
): PaymentDTO {
  const memo = prep(db, 'SELECT id FROM memos WHERE id = ?').get(memoId) as { id: number } | undefined
  if (!memo) throw new AppError('MEMO_NOT_FOUND', `Memo ${memoId} not found`)
  validate(input)
  const tdsAmount = resolveTdsAmount(input)
  const tx = db.transaction(() => {
    const id = insertPaymentRow(db, input, tdsAmount)
    writeAllocations(db, id, resolveAllocations(input, tdsAmount, memoId))
    return id
  })
  return getPayment(db, tx())
}

/**
 * Adds a payment with explicit allocations across zero, one, or several memos.
 * Used by the Feebook "+ Payment" flow (Req #5).
 */
export function addPayment(db: Database.Database, input: PaymentInput): PaymentDTO {
  validate(input)
  const tdsAmount = resolveTdsAmount(input)
  const tx = db.transaction(() => {
    const id = insertPaymentRow(db, input, tdsAmount)
    writeAllocations(db, id, resolveAllocations(input, tdsAmount, null))
    return id
  })
  return getPayment(db, tx())
}

/** Creates an unaccounted payment (no allocations). */
export function addUnaccountedPayment(db: Database.Database, input: PaymentInput): PaymentDTO {
  validate(input)
  const tdsAmount = resolveTdsAmount(input)
  const tx = db.transaction(() => {
    const id = insertPaymentRow(db, input, tdsAmount)
    writeAllocations(db, id, [])
    return id
  })
  return getPayment(db, tx())
}

/**
 * Attaches an unaccounted payment to a memo by allocating its full gross to
 * that memo. No-op-safe if already allocated elsewhere (replaces allocations).
 */
export function assignPaymentToMemo(
  db: Database.Database,
  paymentId: number,
  memoId: number,
): PaymentDTO {
  const pay = prep(db, 'SELECT * FROM payments WHERE id = ?').get(paymentId) as PaymentRow | undefined
  if (!pay) throw new AppError('INVALID_PAYMENT', `Payment ${paymentId} not found`)
  const memo = prep(db, 'SELECT id FROM memos WHERE id = ?').get(memoId) as { id: number } | undefined
  if (!memo) throw new AppError('MEMO_NOT_FOUND', `Memo ${memoId} not found`)
  const tx = db.transaction(() => {
    writeAllocations(db, paymentId, [
      { memoId, amount: pay.amount, tdsAmount: pay.tds_amount },
    ])
  })
  tx()
  return getPayment(db, paymentId)
}

export function getPayment(db: Database.Database, id: number): PaymentDTO {
  const row = prep(db, 'SELECT * FROM payments WHERE id = ?').get(id) as PaymentRow | undefined
  if (!row) throw new AppError('INVALID_PAYMENT', `Payment ${id} not found`)
  return toDTO(db, row)
}

export function updatePayment(db: Database.Database, id: number, input: PaymentInput): PaymentDTO {
  const existing = prep(db, 'SELECT * FROM payments WHERE id = ?').get(id) as PaymentRow | undefined
  if (!existing) throw new AppError('INVALID_PAYMENT', `Payment ${id} not found`)
  validate(input)
  const tdsAmount = resolveTdsAmount(input)
  const tx = db.transaction(() => {
    prep(
      db,
      `UPDATE payments SET
         amount = @amount, tds_rate = @tdsRate, auto_tds = @autoTds, tds_amount = @tds,
         date_of_payment = @date, payee = @payee, bank_account_id = @bank,
         payment_details = @details, payment_mode = @mode, updated_at = datetime('now')
       WHERE id = @id`,
    ).run({
      id,
      amount: input.amount,
      tdsRate: input.tdsRate ?? 0,
      autoTds: (input.autoTds ?? true) ? 1 : 0,
      tds: tdsAmount,
      date: input.dateOfPayment,
      payee: input.payee ?? null,
      bank: input.bankAccountId ?? null,
      details: input.paymentDetails ?? null,
      mode: input.paymentMode?.trim() || null,
    })
    // Re-derive allocations. If explicit allocations are given, use them;
    // otherwise keep the existing single-memo link (if any).
    const existingAllocs = listAllocations(db, id)
    const singleMemo = existingAllocs.length === 1 ? existingAllocs[0].memoId : null
    // An explicit allocations array (even empty) replaces the old split.
    const next =
      input.allocations !== undefined
        ? resolveAllocations({ ...input, allocations: input.allocations }, tdsAmount, null)
        : resolveAllocations(input, tdsAmount, singleMemo)
    writeAllocations(db, id, next)
  })
  tx()
  return getPayment(db, id)
}

export function deletePayment(db: Database.Database, id: number): void {
  const existing = prep(db, 'SELECT id FROM payments WHERE id = ?').get(id) as { id: number } | undefined
  if (!existing) throw new AppError('INVALID_PAYMENT', `Payment ${id} not found`)
  const tx = db.transaction(() => {
    prep(db, 'DELETE FROM payment_allocations WHERE payment_id = ?').run(id)
    prep(db, 'DELETE FROM payments WHERE id = ?').run(id)
  })
  tx()
}

/**
 * Lists payments that have an allocation to the given memo, with the per-memo
 * share surfaced as this payment's amount/tds (so the memo Payment modal shows
 * the portion applied to this memo, not the whole split payment).
 */
export function listPaymentsForMemo(db: Database.Database, memoId: number): PaymentDTO[] {
  const rows = prep(
    db,
    `SELECT p.* FROM payments p
     JOIN payment_allocations a ON a.payment_id = p.id
     WHERE a.memo_id = ?
     ORDER BY p.date_of_payment ASC, p.id ASC`,
  ).all(memoId) as PaymentRow[]
  return rows.map((p) => {
    const dto = toDTO(db, p)
    // Narrow the surfaced amount/tds to this memo's allocation.
    const alloc = dto.allocations.find((x) => x.memoId === memoId)
    if (alloc) {
      return {
        ...dto,
        memoId,
        amount: alloc.amount,
        tdsAmount: alloc.tdsAmount,
        grossAmount: alloc.grossAmount,
      }
    }
    return dto
  })
}

/**
 * The distinct payees already entered on payments against any memo of the
 * given matters, most recent first. Used to suggest a payee when entering a
 * new payment. Blank payees are ignored; names are compared case-insensitively.
 */
export function listPayeesForMatters(db: Database.Database, matterIds: number[]): MatterPayee[] {
  if (matterIds.length === 0) return []
  const ph = matterIds.map(() => '?').join(', ')
  const rows = prep(
    db,
    `SELECT p.payee AS payee, COUNT(DISTINCT p.id) AS n, MAX(p.date_of_payment) AS last_date -- payee = spelling on the latest payment
     FROM payments p
     JOIN payment_allocations a ON a.payment_id = p.id
     JOIN memos m ON m.id = a.memo_id
     WHERE m.matter_id IN (${ph}) AND p.payee IS NOT NULL AND TRIM(p.payee) <> ''
     GROUP BY LOWER(TRIM(p.payee))
     ORDER BY last_date DESC, n DESC`,
  ).all(...matterIds) as Array<{ payee: string; n: number; last_date: string }>
  return rows.map((r) => ({ payee: r.payee.trim(), count: r.n, lastDate: r.last_date }))
}
