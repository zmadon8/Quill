/**
 * firmService.ts
 *
 * Pure, testable business logic for Firms and Partners. Every function takes a
 * raw better-sqlite3 Database instance as its first argument so it can be unit-
 * and property-tested against an in-memory database without Electron.
 *
 * Firm status is DERIVED, never stored: a firm is 'active' when it has at least
 * one non-archived matter, otherwise 'archived'.
 *
 * Prepared statements are cached per-database (keyed by SQL text) via a
 * module-level WeakMap. Reusing statements rather than calling db.prepare() on
 * every invocation keeps the number of native Statement handles bounded, which
 * is both a better-sqlite3 best practice and avoids native-finalizer pressure.
 */

import type Database from 'better-sqlite3'
import { AppError } from '@/types/ipc'
import type { FirmSummary, FirmDetail, PartnerDTO, MatterDTO, FirmFilter } from '@/types/ipc'
import { prep, round2 } from '@/db/prep'
import { effectiveTotalFees, computeIsOverdue } from './memoService'
import { getSettings } from './settingsService'

/** Per-matter rolled-up status for the Firm page's matter dots. */
interface MatterRollup {
  memoStatus: 'Paid' | 'Unpaid' | 'Overdue' | null
  hasWrittenOff: boolean
}

/**
 * Computes each matter's rolled-up status for a firm in one pass. For every
 * finalised (non-draft) memo we derive paid-vs-total and overdue, then fold per
 * matter: Overdue if any memo overdue; else Unpaid if any unpaid; else Paid
 * (all paid). `hasWrittenOff` is true if any memo is written off. A matter with
 * no finalised memos gets memoStatus = null.
 */
function matterRollups(db: Database.Database, firmId: number): Map<number, MatterRollup> {
  const overdueDays = getSettings(db).overdueDays
  const rows = prep(
    db,
    `SELECT m.id, m.matter_id, m.date, m.written_off,
            m.num_appearances, m.fees_per_appearance, m.num_conferences,
            m.fees_per_conference, m.fees_misc_drafting,
            m.custom_fees_appearances, m.custom_fees_conferences, m.custom_fees_misc, m.custom_total_fees,
            COALESCE((SELECT SUM(a.amount + a.tds_amount) FROM payment_allocations a WHERE a.memo_id = m.id), 0) AS amount_paid
     FROM memos m
     WHERE m.firm_id = ? AND m.is_draft = 0`,
  ).all(firmId) as Array<{
    id: number
    matter_id: number
    date: string
    written_off: number
    num_appearances: number
    fees_per_appearance: number
    num_conferences: number
    fees_per_conference: number
    fees_misc_drafting: number
    custom_fees_appearances: number | null
    custom_fees_conferences: number | null
    custom_fees_misc: number | null
    custom_total_fees: number | null
    amount_paid: number
  }>

  const acc = new Map<
    number,
    { anyOverdue: boolean; anyUnpaid: boolean; anyWrittenOff: boolean; liveCount: number; hasMemo: boolean }
  >()
  for (const r of rows) {
    const total = effectiveTotalFees(r)
    const paid = round2(r.amount_paid)
    const writtenOff = r.written_off === 1
    const isPaid = paid >= total
    const isOverdue = computeIsOverdue(r.date, isPaid ? 'Paid' : 'Unpaid', writtenOff, overdueDays)

    let a = acc.get(r.matter_id)
    if (!a) {
      a = { anyOverdue: false, anyUnpaid: false, anyWrittenOff: false, liveCount: 0, hasMemo: false }
      acc.set(r.matter_id, a)
    }
    a.hasMemo = true
    if (writtenOff) a.anyWrittenOff = true
    else a.liveCount += 1 // a "live" (not written-off) memo
    if (isOverdue) a.anyOverdue = true
    // "Unpaid" for the roll-up means a live (not written-off) memo with a balance.
    if (!isPaid && !writtenOff) a.anyUnpaid = true
  }

  const out = new Map<number, MatterRollup>()
  for (const [matterId, a] of acc) {
    // Primary status is derived ONLY from live (non-written-off) memos. When a
    // matter has memos but NONE are live (all written off), there is no primary
    // status — only the grey written-off dot shows. 'Paid' means "every live
    // memo is paid" (not merely "nothing unpaid"), so an all-written-off matter
    // never falls through to green.
    const memoStatus: MatterRollup['memoStatus'] = !a.hasMemo
      ? null
      : a.liveCount === 0
        ? null
        : a.anyOverdue
          ? 'Overdue'
          : a.anyUnpaid
            ? 'Unpaid'
            : 'Paid'
    out.set(matterId, { memoStatus, hasWrittenOff: a.anyWrittenOff })
  }
  return out
}

const MAX_PARTNERS = 50
const MAX_NAME = 200

// Per-database cache of prepared statements, keyed by SQL string.

function validateName(
  name: string,
  invalidCode: 'INVALID_FIRM_NAME' | 'INVALID_PARTNER_NAME',
): string {
  const trimmed = (name ?? '').trim()
  if (trimmed.length < 1 || trimmed.length > MAX_NAME) {
    throw new AppError(invalidCode, `Name must be between 1 and ${MAX_NAME} characters`)
  }
  return trimmed
}

/** Narrows a raw status string from the DB to the FirmSummary status union. */
function normalizeStatus(raw: string | null | undefined): 'active' | 'archived' {
  return raw === 'archived' ? 'archived' : 'active'
}

// ---------------------------------------------------------------------------
// Firms
// ---------------------------------------------------------------------------

export function createFirm(db: Database.Database, name: string): FirmSummary {
  const clean = validateName(name, 'INVALID_FIRM_NAME')

  const existing = prep(db, 'SELECT id FROM firms WHERE lower(name) = lower(?)').get(clean) as
    | { id: number }
    | undefined
  if (existing) {
    throw new AppError('DUPLICATE_FIRM_NAME', `A firm named "${clean}" already exists`)
  }

  // Status is stored and defaults to 'active'. New firms are Active immediately.
  // A default partner named after the firm is created alongside it so a matter
  // can be created right away without manually adding a partner first.
  const tx = db.transaction((): number => {
    const info = prep(db, "INSERT INTO firms (name, status) VALUES (?, 'active')").run(clean)
    const firmId = Number(info.lastInsertRowid)
    prep(db, 'INSERT INTO partners (firm_id, name) VALUES (?, ?)').run(firmId, clean)
    return firmId
  })
  const id = tx()
  return { id, name: clean, status: 'active' }
}

export function listFirms(db: Database.Database, filter: FirmFilter): FirmSummary[] {
  const rows = prep(
    db,
    `SELECT id, name, status
     FROM firms
     ORDER BY lower(name) ASC`,
  ).all() as Array<{ id: number; name: string; status: string }>

  const summaries: FirmSummary[] = rows.map((r) => ({
    id: r.id,
    name: r.name,
    status: normalizeStatus(r.status),
  }))

  if (filter === 'all') return summaries
  return summaries.filter((s) => s.status === filter)
}

/** Manually set a firm's status to 'active' or 'archived'. */
export function setFirmStatus(
  db: Database.Database,
  id: number,
  status: 'active' | 'archived',
): FirmSummary {
  const firm = prep(db, 'SELECT id FROM firms WHERE id = ?').get(id) as { id: number } | undefined
  if (!firm) throw new AppError('FIRM_NOT_FOUND', `Firm ${id} not found`)

  prep(db, "UPDATE firms SET status = ?, updated_at = datetime('now') WHERE id = ?").run(
    status,
    id,
  )

  const detail = getFirm(db, id)
  return { id: detail.id, name: detail.name, status: detail.status }
}

export function getFirm(db: Database.Database, id: number): FirmDetail {
  const firm = prep(db, 'SELECT id, name, status, notes FROM firms WHERE id = ?').get(id) as
    | { id: number; name: string; status: string; notes: string | null }
    | undefined
  if (!firm) throw new AppError('FIRM_NOT_FOUND', `Firm ${id} not found`)

  const partners = (
    prep(
      db,
      'SELECT id, firm_id, name FROM partners WHERE firm_id = ? ORDER BY lower(name) ASC',
    ).all(id) as Array<{ id: number; firm_id: number; name: string }>
  ).map<PartnerDTO>((p) => ({ id: p.id, firmId: p.firm_id, name: p.name }))

  const rollups = matterRollups(db, id)
  const matters = (
    prep(
      db,
      'SELECT id, firm_id, partner_id, name, is_archived FROM matters WHERE firm_id = ? ORDER BY lower(name) ASC',
    ).all(id) as Array<{
      id: number
      firm_id: number
      partner_id: number
      name: string
      is_archived: number
    }>
  ).map<MatterDTO>((m) => {
    const roll = rollups.get(m.id)
    return {
      id: m.id,
      firmId: m.firm_id,
      partnerId: m.partner_id,
      name: m.name,
      isArchived: m.is_archived === 1,
      memoStatus: roll ? roll.memoStatus : null,
      hasWrittenOff: roll ? roll.hasWrittenOff : false,
    }
  })

  return {
    id: firm.id,
    name: firm.name,
    status: normalizeStatus(firm.status),
    notes: firm.notes,
    partners,
    matters,
  }
}

export function updateFirm(
  db: Database.Database,
  id: number,
  data: { name?: string; notes?: string },
): FirmSummary {
  const firm = prep(db, 'SELECT id FROM firms WHERE id = ?').get(id) as { id: number } | undefined
  if (!firm) throw new AppError('FIRM_NOT_FOUND', `Firm ${id} not found`)

  if (data.name !== undefined) {
    const clean = validateName(data.name, 'INVALID_FIRM_NAME')
    const dupe = prep(db, 'SELECT id FROM firms WHERE lower(name) = lower(?) AND id != ?').get(
      clean,
      id,
    ) as { id: number } | undefined
    if (dupe) throw new AppError('DUPLICATE_FIRM_NAME', `A firm named "${clean}" already exists`)
    prep(db, "UPDATE firms SET name = ?, updated_at = datetime('now') WHERE id = ?").run(clean, id)
  }

  if (data.notes !== undefined) {
    prep(db, "UPDATE firms SET notes = ?, updated_at = datetime('now') WHERE id = ?").run(
      data.notes || null,
      id,
    )
  }

  const detail = getFirm(db, id)
  return { id: detail.id, name: detail.name, status: detail.status }
}

// ---------------------------------------------------------------------------
// Partners
// ---------------------------------------------------------------------------

export function addPartner(db: Database.Database, firmId: number, name: string): PartnerDTO {
  const firm = prep(db, 'SELECT id FROM firms WHERE id = ?').get(firmId) as
    | { id: number }
    | undefined
  if (!firm) throw new AppError('FIRM_NOT_FOUND', `Firm ${firmId} not found`)

  const clean = validateName(name, 'INVALID_PARTNER_NAME')

  const count = (
    prep(db, 'SELECT COUNT(*) AS c FROM partners WHERE firm_id = ?').get(firmId) as { c: number }
  ).c
  if (count >= MAX_PARTNERS) {
    throw new AppError('TOO_MANY_PARTNERS', `A firm may have at most ${MAX_PARTNERS} partners`)
  }

  const dupe = prep(
    db,
    'SELECT id FROM partners WHERE firm_id = ? AND lower(name) = lower(?)',
  ).get(firmId, clean) as { id: number } | undefined
  if (dupe)
    throw new AppError('DUPLICATE_PARTNER_NAME', `Partner "${clean}" already exists in this firm`)

  const info = prep(db, 'INSERT INTO partners (firm_id, name) VALUES (?, ?)').run(firmId, clean)
  return { id: Number(info.lastInsertRowid), firmId, name: clean }
}

export function updatePartner(
  db: Database.Database,
  firmId: number,
  partnerId: number,
  name: string,
): PartnerDTO {
  const partner = prep(db, 'SELECT id FROM partners WHERE id = ? AND firm_id = ?').get(
    partnerId,
    firmId,
  ) as { id: number } | undefined
  if (!partner) throw new AppError('PARTNER_NOT_FOUND', `Partner ${partnerId} not found`)

  const clean = validateName(name, 'INVALID_PARTNER_NAME')

  const dupe = prep(
    db,
    'SELECT id FROM partners WHERE firm_id = ? AND lower(name) = lower(?) AND id != ?',
  ).get(firmId, clean, partnerId) as { id: number } | undefined
  if (dupe)
    throw new AppError('DUPLICATE_PARTNER_NAME', `Partner "${clean}" already exists in this firm`)

  prep(db, 'UPDATE partners SET name = ? WHERE id = ?').run(clean, partnerId)
  return { id: partnerId, firmId, name: clean }
}

export function removePartner(db: Database.Database, firmId: number, partnerId: number): void {
  const partner = prep(db, 'SELECT id FROM partners WHERE id = ? AND firm_id = ?').get(
    partnerId,
    firmId,
  ) as { id: number } | undefined
  if (!partner) throw new AppError('PARTNER_NOT_FOUND', `Partner ${partnerId} not found`)
  prep(db, 'DELETE FROM partners WHERE id = ?').run(partnerId)
}
