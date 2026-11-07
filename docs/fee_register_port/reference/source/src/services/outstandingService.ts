/**
 * outstandingService.ts
 *
 * Lists Unpaid memos (regardless of matter archived status), grouped by matter,
 * each group sorted by memo number ascending with a subtotal. Used by the
 * Outstanding Memos view and its Excel export.
 */

import type Database from 'better-sqlite3'
import type {
  OutstandingFilter,
  OutstandingGroup,
  OutstandingEntry,
  OutstandingFirmSummary,
  OutstandingScope,
} from '@/types/ipc'
import { effectiveTotalFees, computeLessTds, computeIsOverdue } from './memoService'
import { getSettings } from './settingsService'
import { prep, round2 } from '@/db/prep'

type Row = {
  id: number
  date: string
  memo_number: string
  seq: number
  matter_id: number
  matter_name: string
  firm_id: number
  firm_name: string
  partner_id: number
  partner_name: string
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
}

/** Effective total fees for a row (shared rule; honours custom overrides). */
const rowTotalFees = (r: Row): number => effectiveTotalFees(r)

export function listOutstanding(
  db: Database.Database,
  filter: OutstandingFilter = {},
): OutstandingGroup[] {
  const where: string[] = []
  const params: Record<string, unknown> = {}

  if (filter.firmId !== undefined) {
    where.push('m.firm_id = @firmId')
    params.firmId = filter.firmId
  }
  if (filter.partnerId !== undefined && filter.partnerId !== 'none') {
    where.push('m.partner_id = @partnerId')
    params.partnerId = filter.partnerId
  }
  // Written-off memos are excluded unless explicitly included (Req #7).
  if (!filter.includeWrittenOff) {
    where.push('m.written_off = 0')
  }
  if (filter.selectedMatterIds && filter.selectedMatterIds.length > 0) {
    const names = filter.selectedMatterIds.map((_, i) => `@sm${i}`)
    filter.selectedMatterIds.forEach((v, i) => (params[`sm${i}`] = v))
    where.push(`m.matter_id IN (${names.join(', ')})`)
  } else if (filter.matterId !== undefined) {
    where.push('m.matter_id = @matterId')
    params.matterId = filter.matterId
  }

  // Written-off memos cannot be overdue, so an overdue-only view implies them off.
  const overdueOnly = filter.overdueOnly === true

  // Drafts are never outstanding (no number assigned yet).
  where.push('m.is_draft = 0')
  const whereSqlFinal = `WHERE ${where.join(' AND ')}`

  // Paid is the sum of GROSS allocations (amount + tds) across payment_allocations,
  // consistent with memoService/paymentService (not the legacy net single-memo link).
  const rows = prep(
    db,
    `SELECT m.id, m.date, m.memo_number, m.seq, m.matter_id, mt.name AS matter_name,
            m.firm_id, f.name AS firm_name, m.partner_id, p.name AS partner_name, m.written_off,
            m.num_appearances, m.fees_per_appearance, m.num_conferences,
            m.fees_per_conference, m.fees_misc_drafting,
            m.custom_fees_appearances, m.custom_fees_conferences, m.custom_fees_misc, m.custom_total_fees,
            COALESCE((SELECT SUM(a.amount + a.tds_amount) FROM payment_allocations a WHERE a.memo_id = m.id), 0) AS amount_paid
     FROM memos m
     JOIN matters mt ON mt.id = m.matter_id
     JOIN firms f ON f.id = m.firm_id
     JOIN partners p ON p.id = m.partner_id
     ${whereSqlFinal}
     ORDER BY lower(p.name) ASC, lower(mt.name) ASC, m.seq ASC`,
  ).all(params) as Row[]

  const settings = getSettings(db)
  const overdueDays = settings.overdueDays
  const defaultTdsRate = settings.defaultTdsRate
  const groups = new Map<number, OutstandingGroup>()

  for (const r of rows) {
    const totalFees = rowTotalFees(r)
    const paid = round2(r.amount_paid)
    // Only Unpaid memos.
    if (paid >= totalFees) continue

    const isOverdue = computeIsOverdue(r.date, 'Unpaid', r.written_off === 1, overdueDays)
    if (overdueOnly && !isOverdue) continue

    const netOfTds = round2(totalFees - computeLessTds(totalFees, defaultTdsRate))
    const due = round2(Math.max(0, totalFees - paid))
    const entry: OutstandingEntry = {
      memoId: r.id,
      date: r.date,
      memoNumber: r.memo_number,
      matterId: r.matter_id,
      matterName: r.matter_name,
      firmId: r.firm_id,
      firmName: r.firm_name,
      partnerName: r.partner_name,
      totalFees,
      netOfTds,
      amountPaid: paid,
      due,
      isOverdue,
      isWrittenOff: r.written_off === 1,
    }
    let g = groups.get(r.matter_id)
    if (!g) {
      g = {
        matterId: r.matter_id,
        matterName: r.matter_name,
        firmId: r.firm_id,
        firmName: r.firm_name,
        partnerId: r.partner_id,
        partnerName: r.partner_name,
        entries: [],
        subtotal: 0,
        subtotalTotal: 0,
        subtotalNetOfTds: 0,
        subtotalPaid: 0,
      }
      groups.set(r.matter_id, g)
    }
    g.entries.push(entry)
    g.subtotal = round2(g.subtotal + due)
    g.subtotalTotal = round2(g.subtotalTotal + totalFees)
    g.subtotalNetOfTds = round2(g.subtotalNetOfTds + netOfTds)
    g.subtotalPaid = round2(g.subtotalPaid + paid)
  }

  return Array.from(groups.values())
}

/** Grand total across all outstanding groups. */
export function outstandingGrandTotal(groups: OutstandingGroup[]): number {
  return round2(groups.reduce((acc, g) => acc + g.subtotal, 0))
}

/**
 * Firm-wise outstanding summary (Req #3). Returns one row per firm with the
 * total outstanding (unpaid) across all its memos. `sort` controls ordering:
 *   'name'   — alphabetical by firm name (A→Z)
 *   'amount' — descending by outstanding amount
 */
export function listOutstandingByFirm(
  db: Database.Database,
  filter: OutstandingFilter = {},
  sort: 'name' | 'amount' = 'amount',
): OutstandingFirmSummary[] {
  const where: string[] = ['m.is_draft = 0']
  const params: Record<string, unknown> = {}
  if (filter.firmId !== undefined) {
    where.push('m.firm_id = @firmId')
    params.firmId = filter.firmId
  }
  if (filter.partnerId !== undefined && filter.partnerId !== 'none') {
    where.push('m.partner_id = @partnerId')
    params.partnerId = filter.partnerId
  }
  if (!filter.includeWrittenOff) where.push('m.written_off = 0')
  const overdueOnly = filter.overdueOnly === true
  const overdueDays = getSettings(db).overdueDays

  const rows = prep(
    db,
    `SELECT m.id, m.date, m.memo_number, m.seq, m.matter_id, mt.name AS matter_name,
            m.firm_id, f.name AS firm_name, m.written_off,
            m.num_appearances, m.fees_per_appearance, m.num_conferences,
            m.fees_per_conference, m.fees_misc_drafting,
            m.custom_fees_appearances, m.custom_fees_conferences, m.custom_fees_misc, m.custom_total_fees,
            COALESCE((SELECT SUM(a.amount + a.tds_amount) FROM payment_allocations a WHERE a.memo_id = m.id), 0) AS amount_paid
     FROM memos m
     JOIN matters mt ON mt.id = m.matter_id
     JOIN firms f ON f.id = m.firm_id
     WHERE ${where.join(' AND ')}`,
  ).all(params) as Row[]

  const byFirm = new Map<number, OutstandingFirmSummary>()
  for (const r of rows) {
    const totalFees = rowTotalFees(r)
    const outstanding = round2(totalFees - round2(r.amount_paid))
    if (outstanding <= 0) continue // only unpaid balances
    if (overdueOnly && !computeIsOverdue(r.date, 'Unpaid', r.written_off === 1, overdueDays)) continue
    let s = byFirm.get(r.firm_id)
    if (!s) {
      s = { firmId: r.firm_id, firmName: r.firm_name, outstanding: 0, memoCount: 0 }
      byFirm.set(r.firm_id, s)
    }
    s.outstanding = round2(s.outstanding + outstanding)
    s.memoCount += 1
  }

  const list = Array.from(byFirm.values())
  if (sort === 'name') {
    list.sort((a, b) => a.firmName.toLowerCase().localeCompare(b.firmName.toLowerCase()))
  } else {
    list.sort((a, b) => b.outstanding - a.outstanding)
  }
  return list
}

/**
 * Returns the distinct firms and partners that have at least one qualifying
 * memo in the current Outstanding view — honouring `includeWrittenOff` and
 * `overdueOnly`. Used to populate the Firm/Partner filter dropdowns so only
 * names with applicable items appear.
 */
export function listOutstandingScope(
  db: Database.Database,
  filter: OutstandingFilter = {},
): OutstandingScope {
  const overdueOnly = filter.overdueOnly === true
  const where: string[] = ['m.is_draft = 0']
  if (!filter.includeWrittenOff) where.push('m.written_off = 0')

  const rows = prep(
    db,
    `SELECT m.id, m.date, m.memo_number, m.seq, m.matter_id, mt.name AS matter_name,
            m.firm_id, f.name AS firm_name, m.partner_id, p.name AS partner_name, m.written_off,
            m.num_appearances, m.fees_per_appearance, m.num_conferences,
            m.fees_per_conference, m.fees_misc_drafting,
            m.custom_fees_appearances, m.custom_fees_conferences, m.custom_fees_misc, m.custom_total_fees,
            COALESCE((SELECT SUM(a.amount + a.tds_amount) FROM payment_allocations a WHERE a.memo_id = m.id), 0) AS amount_paid
     FROM memos m
     JOIN matters mt ON mt.id = m.matter_id
     JOIN firms f ON f.id = m.firm_id
     JOIN partners p ON p.id = m.partner_id
     WHERE ${where.join(' AND ')}`,
  ).all() as Array<Row & { partner_id: number; partner_name: string }>

  const overdueDays = getSettings(db).overdueDays
  const firms = new Map<number, string>()
  const partners = new Map<number, { firmId: number; name: string }>()

  for (const r of rows) {
    const totalFees = rowTotalFees(r)
    const paid = round2(r.amount_paid)
    if (paid >= totalFees) continue // only unpaid
    if (overdueOnly) {
      const isOverdue = computeIsOverdue(r.date, 'Unpaid', r.written_off === 1, overdueDays)
      if (!isOverdue) continue
    }
    firms.set(r.firm_id, r.firm_name)
    partners.set(r.partner_id, { firmId: r.firm_id, name: r.partner_name })
  }

  return {
    firms: [...firms.entries()]
      .map(([id, name]) => ({ id, name }))
      .sort((a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase())),
    partners: [...partners.entries()]
      .map(([id, p]) => ({ id, firmId: p.firmId, name: p.name }))
      .sort((a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase())),
  }
}
