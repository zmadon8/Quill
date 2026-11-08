/**
 * backupService.ts
 *
 * Full-data backup to an Excel workbook and restore from one. Export and the
 * buffer/workbook handling are pure (no Electron). The IPC layer supplies the
 * save/open dialog and user confirmation.
 *
 * Sheets: Firms, Partners, Matters, Memos, Payments, BankAccounts, Settings.
 * Restore replaces ALL data (truncate in dependency order, re-insert, then
 * recompute memo_number_sequences from the imported memos).
 */

import type Database from 'better-sqlite3'
import ExcelJS from 'exceljs'
import { AppError } from '@/types/ipc'
import { settingsBackupColumns, settingsBackupDefaults } from '@/db/settingsColumns'

type ColSpec = { header: string; key: string }

/** Table definitions in dependency order (parents first for insert). */
const TABLES: Array<{ sheet: string; table: string; columns: string[] }> = [
  { sheet: 'Firms', table: 'firms', columns: ['id', 'name', 'status', 'notes', 'created_at', 'updated_at'] },
  { sheet: 'Partners', table: 'partners', columns: ['id', 'firm_id', 'name', 'created_at'] },
  {
    sheet: 'Matters',
    table: 'matters',
    columns: [
      'id', 'firm_id', 'partner_id', 'name', 'is_archived', 'is_custom',
      'addressee_line1', 'addressee_line2', 'addressee_use_firm_name', 'court_name', 'client',
      'additional_details_left', 'additional_details_right', 'plaintiff_name', 'plaintiff_type',
      'defendant_name', 'defendant_type', 'notes', 'short_name', 'created_at', 'updated_at',
    ],
  },
  { sheet: 'BankAccounts', table: 'bank_accounts', columns: ['id', 'name', 'created_at'] },
  {
    sheet: 'Memos',
    table: 'memos',
    columns: [
      'id', 'memo_number', 'financial_year', 'seq', 'date', 'matter_id', 'firm_id', 'partner_id',
      'addressee_line1', 'addressee_line2', 'court_name', 'additional_details_left',
      'additional_details_right', 'plaintiff_name', 'plaintiff_type', 'defendant_name',
      'defendant_type', 'client', 'num_appearances', 'dates_of_appearances', 'fees_per_appearance',
      'num_conferences', 'dates_of_conferences', 'fees_per_conference', 'misc_drafting_description',
      'fees_misc_drafting', 'num_drafts', 'tds_rate', 'written_off', 'is_draft',
      'custom_fees_appearances', 'custom_fees_conferences', 'custom_fees_misc', 'custom_total_fees',
      'created_at', 'updated_at',
    ],
  },
  {
    sheet: 'Payments',
    table: 'payments',
    columns: [
      'id', 'memo_id', 'amount', 'tds_rate', 'auto_tds', 'tds_amount', 'memo_amount',
      'date_of_payment', 'payee', 'bank_account_id', 'payment_details', 'payment_mode', 'created_at', 'updated_at',
    ],
  },
  {
    sheet: 'PaymentAllocations',
    table: 'payment_allocations',
    columns: ['id', 'payment_id', 'memo_id', 'amount', 'tds_amount', 'created_at'],
  },
  {
    sheet: 'PeriodAdjustments',
    table: 'period_adjustments',
    columns: [
      'id', 'financial_year', 'month', 'working_days',
      'extra_appearances', 'extra_conferences', 'extra_drafts',
      'ov_appearances', 'ov_conferences', 'ov_drafts', 'ov_billed', 'ov_received', 'ov_received_plus_tds',
      'updated_at',
    ],
  },
  {
    sheet: 'SavedViews',
    table: 'saved_views',
    columns: ['id', 'name', 'measure', 'row_dim', 'col_dim', 'firm_id', 'from_fy', 'to_fy', 'created_at'],
  },
  {
    // Settings columns come from the shared SETTINGS_COLUMNS catalog so a new
    // setting is automatically included in backup/restore.
    sheet: 'Settings',
    table: 'settings',
    columns: settingsBackupColumns(),
  },
]

// ---------------------------------------------------------------------------
// Export
// ---------------------------------------------------------------------------

export async function generateBackupBuffer(db: Database.Database): Promise<Buffer> {
  const wb = new ExcelJS.Workbook()
  for (const def of TABLES) {
    const ws = wb.addWorksheet(def.sheet)
    ws.columns = def.columns.map<ColSpec>((c) => ({ header: c, key: c }))
    ws.getRow(1).font = { bold: true }
    const rows = db.prepare(`SELECT ${def.columns.join(', ')} FROM ${def.table}`).all() as Array<
      Record<string, unknown>
    >
    for (const r of rows) ws.addRow(r)
  }
  return Buffer.from(await wb.xlsx.writeBuffer())
}

// ---------------------------------------------------------------------------
// Restore
// ---------------------------------------------------------------------------

function readSheetRows(ws: ExcelJS.Worksheet, columns: string[]): Array<Record<string, unknown>> {
  // Row 1 is the header; map subsequent rows to column keys by header name.
  const headerRow = ws.getRow(1)
  const headerToCol = new Map<string, number>()
  headerRow.eachCell((cell, colNumber) => {
    headerToCol.set(String(cell.value), colNumber)
  })

  // NOT NULL columns with a DB default. If an older backup omits these (header
  // absent), restore must substitute the default rather than insert NULL, which
  // would violate the NOT NULL constraint. Settings-table defaults are merged
  // in from the shared SETTINGS_COLUMNS catalog so they can't be forgotten.
  const settingsDefaults = settingsBackupDefaults()
  const NOT_NULL_INT_DEFAULTS: Record<string, number> = {
    is_archived: 0,
    addressee_use_firm_name: 0,
    auto_tds: 1,
    num_drafts: 0,
    written_off: 0,
    is_draft: 0,
    working_days: 0,
    extra_appearances: 0,
    extra_conferences: 0,
    extra_drafts: 0,
  }
  const NOT_NULL_TEXT_DEFAULTS: Record<string, string> = {}
  for (const [name, val] of Object.entries(settingsDefaults)) {
    if (typeof val === 'number') NOT_NULL_INT_DEFAULTS[name] = val
    else NOT_NULL_TEXT_DEFAULTS[name] = val
  }

  const out: Array<Record<string, unknown>> = []
  for (let i = 2; i <= ws.rowCount; i++) {
    const row = ws.getRow(i)
    if (row.cellCount === 0) continue
    const obj: Record<string, unknown> = {}
    let anyValue = false
    for (const col of columns) {
      const idx = headerToCol.get(col)
      let v: unknown = idx ? row.getCell(idx).value : null
      if (v !== null && v !== undefined && v !== '') anyValue = true
      if (v === '') v = null
      if ((v === null || v === undefined) && col in NOT_NULL_INT_DEFAULTS) {
        v = NOT_NULL_INT_DEFAULTS[col]
      }
      if ((v === null || v === undefined) && col in NOT_NULL_TEXT_DEFAULTS) {
        v = NOT_NULL_TEXT_DEFAULTS[col]
      }
      obj[col] = v ?? null
    }
    if (anyValue) out.push(obj)
  }
  return out
}

export async function restoreFromBuffer(db: Database.Database, buffer: Buffer): Promise<{ rowsImported: number }> {
  const wb = new ExcelJS.Workbook()
  try {
    await wb.xlsx.load(buffer as unknown as ExcelJS.Buffer)
  } catch {
    throw new AppError('RESTORE_FAILED', 'The backup file could not be read')
  }

  // Sheets added in later versions are optional, so backups taken by older
  // builds still restore. Core sheets remain required.
  const OPTIONAL_SHEETS = new Set(['PaymentAllocations', 'PeriodAdjustments', 'SavedViews'])
  for (const def of TABLES) {
    if (!wb.getWorksheet(def.sheet) && !OPTIONAL_SHEETS.has(def.sheet)) {
      throw new AppError('RESTORE_FAILED', `Backup is missing the "${def.sheet}" sheet`)
    }
  }

  const parsed = TABLES.filter((def) => wb.getWorksheet(def.sheet)).map((def) => ({
    def,
    rows: readSheetRows(wb.getWorksheet(def.sheet)!, def.columns),
  }))

  let rowsImported = 0
  const tx = db.transaction(() => {
    // Truncate in reverse dependency order (children first).
    db.exec(`
      DELETE FROM saved_views;
      DELETE FROM payment_allocations;
      DELETE FROM period_adjustments;
      DELETE FROM payments;
      DELETE FROM memos;
      DELETE FROM matters;
      DELETE FROM partners;
      DELETE FROM bank_accounts;
      DELETE FROM firms;
      DELETE FROM memo_number_sequences;
      DELETE FROM settings;
    `)

    for (const { def, rows } of parsed) {
      if (rows.length === 0) continue
      const placeholders = def.columns.map((c) => `@${c}`).join(', ')
      const stmt = db.prepare(
        `INSERT INTO ${def.table} (${def.columns.join(', ')}) VALUES (${placeholders})`,
      )
      for (const r of rows) {
        stmt.run(r)
        rowsImported++
      }
    }

    // Ensure a settings row always exists.
    const hasSettings = (db.prepare('SELECT COUNT(*) AS c FROM settings').get() as { c: number }).c
    if (hasSettings === 0) {
      db.prepare('INSERT INTO settings (id, default_tds_rate) VALUES (1, 10)').run()
    }

    // Recompute memo_number_sequences from imported NON-DRAFT memos (drafts are
    // unnumbered and must not advance the sequence).
    db.exec('DELETE FROM memo_number_sequences')
    const seqRows = db
      .prepare(
        'SELECT financial_year, MAX(seq) AS max_seq FROM memos WHERE is_draft = 0 GROUP BY financial_year',
      )
      .all() as Array<{ financial_year: string; max_seq: number }>
    const seqInsert = db.prepare(
      'INSERT INTO memo_number_sequences (financial_year, last_seq) VALUES (?, ?)',
    )
    for (const s of seqRows) seqInsert.run(s.financial_year, s.max_seq)

    // Backfill allocations for legacy backups that predate payment_allocations:
    // if a payment has a memo_id but no allocation, mirror it into one.
    db.exec(`
      INSERT INTO payment_allocations (payment_id, memo_id, amount, tds_amount)
      SELECT p.id, p.memo_id, p.amount, p.tds_amount
      FROM payments p
      WHERE p.memo_id IS NOT NULL
        AND NOT EXISTS (SELECT 1 FROM payment_allocations a WHERE a.payment_id = p.id)
    `)
  })

  tx()
  return { rowsImported }
}

/**
 * Clears ALL data (same end state as a fresh database): truncates every table
 * in dependency order and re-seeds the single settings row. Intended for the
 * Settings "Clear All Data" action, which backs up first.
 */
export function clearAllData(db: Database.Database): void {
  const tx = db.transaction(() => {
    db.exec(`
      DELETE FROM saved_views;
      DELETE FROM payment_allocations;
      DELETE FROM period_adjustments;
      DELETE FROM payments;
      DELETE FROM memos;
      DELETE FROM matters;
      DELETE FROM partners;
      DELETE FROM bank_accounts;
      DELETE FROM firms;
      DELETE FROM memo_number_sequences;
      DELETE FROM settings;
    `)
    db.prepare('INSERT OR IGNORE INTO settings (id, default_tds_rate) VALUES (1, 10)').run()
  })
  tx()
}
