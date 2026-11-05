/**
 * importService.ts
 *
 * Imports a flat list of memos (optionally with an already-paid amount) from a
 * user's own spreadsheet. Firms and matters are found-or-created by name as we
 * go, so the user doesn't have to pre-build the relationship graph. Additive:
 * it never deletes existing data.
 *
 * Rows that carry a memo number are created in a CUSTOM matter so the user's
 * own number is preserved verbatim; rows without a number are saved as drafts.
 */

import type Database from 'better-sqlite3'
import { AppError } from '@/types/ipc'
import type { ImportMapping, ImportResult, ImportField, MemoInput } from '@/types/ipc'
import { createMemo } from './memoService'
import { addPaymentToMemo, addPayment, addUnaccountedPayment } from './paymentService'
import { prep } from '@/db/prep'

/** Parses a cell to a number; blank/non-numeric → 0. Strips ₹ and commas. */
function toNum(v: string | undefined): number {
  if (v === undefined) return 0
  const cleaned = String(v).replace(/[₹,\s]/g, '')
  const n = Number(cleaned)
  return Number.isFinite(n) ? n : 0
}

/** Normalises many common date formats to ISO YYYY-MM-DD; '' if unparseable. */
function toIsoDate(v: string | undefined): string {
  if (!v) return ''
  const s = String(v).trim()
  // Already ISO.
  let m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s)
  if (m) return `${m[1]}-${m[2]}-${m[3]}`
  // DD/MM/YYYY or DD-MM-YYYY (common in India).
  m = /^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$/.exec(s)
  if (m) {
    const d = m[1].padStart(2, '0')
    const mo = m[2].padStart(2, '0')
    return `${m[3]}-${mo}-${d}`
  }
  // Excel may hand us a JS Date string; try Date.parse as a last resort.
  const parsed = new Date(s)
  if (!Number.isNaN(parsed.getTime())) {
    return `${parsed.getFullYear()}-${String(parsed.getMonth() + 1).padStart(2, '0')}-${String(
      parsed.getDate(),
    ).padStart(2, '0')}`
  }
  return ''
}

function findOrCreateFirm(db: Database.Database, name: string, counters: { firms: number }): number {
  const existing = prep(db, 'SELECT id FROM firms WHERE lower(name) = lower(?)').get(name) as
    | { id: number }
    | undefined
  if (existing) return existing.id
  const info = prep(db, "INSERT INTO firms (name, status) VALUES (?, 'active')").run(name)
  counters.firms += 1
  return Number(info.lastInsertRowid)
}

function findOrCreatePartner(db: Database.Database, firmId: number, name?: string): number {
  // Use the named partner when provided; otherwise a single default partner
  // per firm named "—".
  const wanted = (name ?? '').trim() || '—'
  const existing = prep(
    db,
    'SELECT id FROM partners WHERE firm_id = ? AND lower(name) = lower(?)',
  ).get(firmId, wanted) as { id: number } | undefined
  if (existing) return existing.id
  const info = prep(db, 'INSERT INTO partners (firm_id, name) VALUES (?, ?)').run(firmId, wanted)
  return Number(info.lastInsertRowid)
}

function findOrCreateMatter(
  db: Database.Database,
  firmId: number,
  partnerId: number,
  name: string,
  counters: { matters: number },
  defaults?: { courtName?: string; client?: string },
): number {
  const courtName = defaults?.courtName?.trim() || null
  const client = defaults?.client?.trim() || null
  const existing = prep(
    db,
    'SELECT id, court_name, client FROM matters WHERE firm_id = ? AND lower(name) = lower(?)',
  ).get(firmId, name) as
    | { id: number; court_name: string | null; client: string | null }
    | undefined
  if (existing) {
    // Backfill court/client only when the matter doesn't already have them
    // (first non-blank wins, so earlier rows set the matter's cause-title).
    if (courtName && !existing.court_name) {
      prep(db, 'UPDATE matters SET court_name = ? WHERE id = ?').run(courtName, existing.id)
    }
    if (client && !existing.client) {
      prep(db, 'UPDATE matters SET client = ? WHERE id = ?').run(client, existing.id)
    }
    return existing.id
  }
  const info = prep(
    db,
    `INSERT INTO matters (firm_id, partner_id, name, is_archived, court_name, client)
     VALUES (?, ?, ?, 0, ?, ?)`,
  ).run(firmId, partnerId, name, courtName, client)
  counters.matters += 1
  return Number(info.lastInsertRowid)
}

/** Options controlling import behaviour beyond the column mapping. */
export interface ImportRunOptions {
  /**
   * When true, rows that have a valid date but NO mapped/typed memo number are
   * created as finalised, AUTO-NUMBERED memos (in file order) instead of as
   * drafts. Rows are numbered per financial year using the app's sequence, so
   * a file sorted by the intended order reproduces that numbering.
   */
  autoNumber?: boolean
}

/**
 * Executes an import given parsed rows (array of records keyed by source
 * header) and the user's column mapping. Runs in a single transaction so a
 * failure rolls back cleanly.
 */
export function importMemos(
  db: Database.Database,
  rows: Array<Record<string, string>>,
  mapping: ImportMapping,
  options: ImportRunOptions = {},
): ImportResult {
  const get = (row: Record<string, string>, field: ImportField): string | undefined => {
    const col = mapping[field]
    if (!col) return undefined
    const v = row[col]
    return v === undefined || v === null ? undefined : String(v).trim()
  }

  if (!mapping.firmName || !mapping.matterName) {
    throw new AppError('UNKNOWN', 'Firm name and Matter name columns must be mapped')
  }

  const counters = { firms: 0, matters: 0 }
  const warnings: string[] = []
  let memosCreated = 0
  let paymentsCreated = 0
  let rowsProcessed = 0

  // Memo-attached payments are collected first and created AFTER all memos
  // exist, so that rows sharing a "Payment Group" can be merged into a single
  // payment split across those memos (preserving "paid together" grouping).
  type PendingPayment = {
    memoId: number
    net: number
    tds: number
    date: string
    payee?: string
    group: string // '' = ungrouped (its own single-memo payment)
    rowNo: number
  }
  const pending: PendingPayment[] = []

  const run = db.transaction(() => {
    rows.forEach((row, i) => {
      const rowNo = i + 2 // header is row 1
      const firmName = get(row, 'firmName')
      const matterName = get(row, 'matterName')
      const memoNumberRaw = get(row, 'memoNumber')
      const paidForRow = mapping.amountPaid ? toNum(get(row, 'amountPaid')) : 0

      // Unaccounted payment: a row with no firm, matter, or memo number, but a
      // positive paid amount. These are received monies not tied to any memo
      // (they surface under "Unaccounted memos" in Feebook). Handle BEFORE the
      // firm/matter guard below, which would otherwise skip the row.
      if (!firmName && !matterName && !memoNumberRaw && paidForRow > 0) {
        const payDate = mapping.paymentDate ? toIsoDate(get(row, 'paymentDate')) : ''
        const tds = mapping.paymentTds ? toNum(get(row, 'paymentTds')) : 0
        const payee = mapping.payee ? get(row, 'payee') : undefined
        try {
          addUnaccountedPayment(db, {
            amount: paidForRow,
            tdsRate: 0,
            autoTds: false,
            tdsAmount: tds > 0 ? tds : 0,
            payee: payee || undefined,
            dateOfPayment: payDate || new Date().toISOString().slice(0, 10),
          })
          paymentsCreated += 1
          rowsProcessed += 1
        } catch (err) {
          warnings.push(`Row ${rowNo}: unaccounted payment not recorded (${(err as Error).message}).`)
        }
        return
      }

      if (!firmName || !matterName) {
        warnings.push(`Row ${rowNo}: skipped (missing firm or matter name).`)
        return
      }

      const dateIso = toIsoDate(get(row, 'date'))
      const memoNumber = memoNumberRaw
      const hasNumber = !!memoNumber && memoNumber.length > 0
      // Auto-number mode: a row with a valid date but no custom number becomes a
      // finalised, auto-numbered memo (not a draft). Without auto-number mode,
      // a row with no number stays a draft (the historical behaviour).
      const autoNumberThisRow = options.autoNumber === true && !hasNumber && !!dateIso
      const isDraft = !hasNumber && !autoNumberThisRow

      if (hasNumber && !dateIso) {
        warnings.push(`Row ${rowNo}: memo "${memoNumber}" has no valid date — imported as draft.`)
      }

      const courtName = get(row, 'courtName')
      const client = get(row, 'matterClient')
      const firmId = findOrCreateFirm(db, firmName, counters)
      const partnerId = findOrCreatePartner(db, firmId, get(row, 'partnerName'))
      const matterId = findOrCreateMatter(db, firmId, partnerId, matterName, counters, {
        courtName,
        client,
      })

      const totalMapped = mapping.totalFees ? toNum(get(row, 'totalFees')) : 0
      const input: MemoInput = {
        date: dateIso || new Date().toISOString().slice(0, 10),
        matterId,
        customMemoNumber: hasNumber ? memoNumber : null,
        addresseeLine1: firmName,
        // The memo snapshots the matter's cause-title and client at creation.
        courtName: courtName ?? undefined,
        client: client ?? undefined,
        plaintiffName: get(row, 'partyPlaintiff') ?? undefined,
        defendantName: get(row, 'partyDefendant') ?? undefined,
        numAppearances: toNum(get(row, 'numAppearances')),
        feesPerAppearance: toNum(get(row, 'feesPerAppearance')),
        numConferences: toNum(get(row, 'numConferences')),
        feesPerConference: toNum(get(row, 'feesPerConference')),
        miscDraftingDescription: get(row, 'miscDescription') ?? undefined,
        feesMiscDrafting: toNum(get(row, 'feesMisc')),
        numDrafts: mapping.numDrafts ? toNum(get(row, 'numDrafts')) : 0,
        // When a Total column is mapped, use it as the custom total (overrides breakup).
        customTotalFees: mapping.totalFees ? totalMapped : null,
      }

      let memo
      try {
        memo = createMemo(db, input, isDraft || (!dateIso && hasNumber))
      } catch (err) {
        warnings.push(`Row ${rowNo}: ${(err as Error).message}`)
        return
      }
      memosCreated += 1
      rowsProcessed += 1

      // Optional: an already-paid amount. Collected now, created after the loop
      // (so grouped rows can be merged into one split payment).
      const paid = paidForRow
      if (paid > 0 && !memo.isDraft) {
        const payDate = mapping.paymentDate ? toIsoDate(get(row, 'paymentDate')) : ''
        const tds = mapping.paymentTds ? toNum(get(row, 'paymentTds')) : 0
        const payee = mapping.payee ? get(row, 'payee') : undefined
        const group = (mapping.paymentGroup ? get(row, 'paymentGroup') : '') || ''
        pending.push({
          memoId: memo.id,
          net: paid,
          tds: tds > 0 ? tds : 0,
          date: payDate || dateIso || new Date().toISOString().slice(0, 10),
          payee: payee || undefined,
          group,
          rowNo,
        })
      } else if (paid > 0 && memo.isDraft) {
        warnings.push(`Row ${rowNo}: paid amount ignored because the memo is a draft (no number).`)
      }
    })

    // ---- Create the collected payments ----
    // Ungrouped payments (group === '') and single-member groups become a
    // single-memo payment. Groups with 2+ members become ONE payment split
    // across those memos (each memo keeps its own net + TDS as its allocation;
    // the payment's date and payee come from the first member row).
    const groups = new Map<string, PendingPayment[]>()
    for (const p of pending) {
      if (p.group) {
        const list = groups.get(p.group) ?? []
        list.push(p)
        groups.set(p.group, list)
      } else {
        // Ungrouped → its own single-memo payment immediately.
        try {
          addPaymentToMemo(db, p.memoId, {
            amount: p.net,
            tdsRate: 0,
            autoTds: false,
            tdsAmount: p.tds,
            payee: p.payee,
            dateOfPayment: p.date,
          })
          paymentsCreated += 1
        } catch (err) {
          warnings.push(`Row ${p.rowNo}: payment not recorded (${(err as Error).message}).`)
        }
      }
    }
    for (const [, members] of groups) {
      if (members.length === 1) {
        const p = members[0]
        try {
          addPaymentToMemo(db, p.memoId, {
            amount: p.net,
            tdsRate: 0,
            autoTds: false,
            tdsAmount: p.tds,
            payee: p.payee,
            dateOfPayment: p.date,
          })
          paymentsCreated += 1
        } catch (err) {
          warnings.push(`Row ${p.rowNo}: payment not recorded (${(err as Error).message}).`)
        }
        continue
      }
      // A single payment split across several memos. Date/payee from the first
      // member; the payment's amount is the sum of the members' net amounts.
      const first = members[0]
      const totalNet = members.reduce((s, m) => s + m.net, 0)
      try {
        addPayment(db, {
          amount: totalNet,
          autoTds: false,
          tdsAmount: members.reduce((s, m) => s + m.tds, 0),
          dateOfPayment: first.date,
          payee: first.payee,
          allocations: members.map((m) => ({ memoId: m.memoId, amount: m.net, tdsAmount: m.tds })),
        })
        paymentsCreated += 1
      } catch (err) {
        warnings.push(`Payment group: split payment not recorded (${(err as Error).message}).`)
      }
    }
  })

  run()

  return {
    firmsCreated: counters.firms,
    mattersCreated: counters.matters,
    memosCreated,
    paymentsCreated,
    rowsProcessed,
    warnings,
  }
}
