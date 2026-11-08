/**
 * settingsService.ts
 *
 * Pure business logic for application Settings (single-row table) and Bank
 * Accounts. The Word template path is stored here; the actual file copy is
 * performed by the IPC handler (which has filesystem/app-path access).
 */

import type Database from 'better-sqlite3'
import { AppError } from '@/types/ipc'
import type { SettingsDTO, SettingsInput, BankAccountDTO } from '@/types/ipc'
import { prep } from '@/db/prep'
import { SETTINGS_COLUMNS, type SettingsColumn } from '@/db/settingsColumns'

const MAX_BANK_ACCOUNTS = 50
const MAX_DETAILS = 500

const MAX_SUFFIX = 12

/** Converts a raw DB value to its DTO value for a catalog column. */
function fromDb(col: SettingsColumn, raw: unknown): unknown {
  if (raw === null || raw === undefined) {
    if (col.nullable) return null
    return col.defaultValue
  }
  switch (col.kind) {
    case 'bool':
      return Number(raw) === 1
    case 'int':
    case 'real':
      return Number(raw)
    default:
      return String(raw)
  }
}

/** Converts a DTO value to its DB parameter value for a catalog column. */
function toDb(col: SettingsColumn, v: unknown): string | number | null {
  if (v === null || v === undefined) {
    if (col.nullable) return null
    v = col.defaultValue
  }
  if (col.kind === 'bool') return v ? 1 : 0
  if (col.kind === 'int' || col.kind === 'real') return Number(v)
  return String(v)
}

/** Built-in defaults, used when the (always-seeded) row is somehow missing. */
function defaultSettings(): SettingsDTO {
  const out: Record<string, unknown> = {}
  for (const col of SETTINGS_COLUMNS) out[col.key] = col.nullable ? null : col.defaultValue
  return out as unknown as SettingsDTO
}

export function getSettings(db: Database.Database): SettingsDTO {
  const row = prep(db, 'SELECT * FROM settings WHERE id = 1').get() as Record<string, unknown> | undefined
  if (!row) return defaultSettings()
  const out: Record<string, unknown> = {}
  for (const col of SETTINGS_COLUMNS) out[col.key] = fromDb(col, row[col.name])
  const dto = out as unknown as SettingsDTO
  // Normalisation of legacy / out-of-range stored values.
  // 'full' stays full; legacy 'thousands'/'lacs' map to 'truncated'.
  dto.moneyUnit = dto.moneyUnit === 'full' ? 'full' : 'truncated'
  return dto
}

/** Validates a financial-year string like "2026-27" (YYYY-YY, consecutive). */
function isValidFinancialYear(fy: string): boolean {
  const m = /^(\d{4})-(\d{2})$/.exec(fy)
  if (!m) return false
  const start = Number(m[1])
  const end = Number(m[2])
  return (start + 1) % 100 === end
}

export function updateSettings(db: Database.Database, input: SettingsInput): SettingsDTO {
  if (input.defaultTdsRate !== undefined && (input.defaultTdsRate < 0 || input.defaultTdsRate > 100)) {
    throw new AppError('UNKNOWN', 'TDS rate must be between 0 and 100')
  }
  if (
    input.overdueDays !== undefined &&
    (!Number.isInteger(input.overdueDays) || input.overdueDays < 0 || input.overdueDays > 3650)
  ) {
    throw new AppError('UNKNOWN', 'Overdue days must be a whole number between 0 and 3650')
  }
  if (
    input.autoBackupFrequency !== undefined &&
    !['off', 'daily', 'weekly', 'monthly'].includes(input.autoBackupFrequency)
  ) {
    throw new AppError('UNKNOWN', 'Invalid automatic backup frequency')
  }
  if (
    input.defaultTab !== undefined &&
    !['memos', 'dashboard', 'statistics', 'firms', 'feebook', 'outstanding', 'settings'].includes(input.defaultTab)
  ) {
    throw new AppError('UNKNOWN', 'Invalid default page')
  }
  if (input.initialFinancialYear !== undefined && !isValidFinancialYear(input.initialFinancialYear)) {
    throw new AppError('UNKNOWN', 'Initial financial year must be in the form "2026-27"')
  }
  for (const f of ['memosStartYear', 'feebookStartYear'] as const) {
    if (input[f] !== undefined && !isValidFinancialYear(input[f] as string)) {
      throw new AppError('UNKNOWN', 'Start year must be in the form "2026-27"')
    }
  }
  if (
    input.defaultPaymentAmount !== undefined &&
    !['zero', 'full', 'netOfTds'].includes(input.defaultPaymentAmount)
  ) {
    throw new AppError('UNKNOWN', 'Invalid default payment amount')
  }
  if (input.moneyUnit !== undefined && !['full', 'truncated'].includes(input.moneyUnit)) {
    throw new AppError('UNKNOWN', 'Invalid money display mode')
  }
  for (const f of ['moneySuffixThousands', 'moneySuffixLac', 'moneySuffixCrore'] as const) {
    const v = input[f]
    if (v !== undefined && (typeof v !== 'string' || v.length > MAX_SUFFIX)) {
      throw new AppError('UNKNOWN', `Money suffix must be at most ${MAX_SUFFIX} characters`)
    }
  }
  if (input.zoomFactor !== undefined && !(input.zoomFactor >= 0.6 && input.zoomFactor <= 2)) {
    throw new AppError('UNKNOWN', 'Zoom must be between 60% and 200%')
  }
  if (
    input.backupRetention !== undefined &&
    (!Number.isInteger(input.backupRetention) || input.backupRetention < 0 || input.backupRetention > 1000)
  ) {
    throw new AppError('UNKNOWN', 'Backup retention must be a whole number between 0 and 1000')
  }
  for (const f of ['defaultAdditionalDetailsLeft', 'defaultAdditionalDetailsRight'] as const) {
    const v = input[f]
    if (typeof v === 'string' && v.length > MAX_DETAILS) {
      throw new AppError('UNKNOWN', `${f} must be at most ${MAX_DETAILS} characters`)
    }
  }

  const current = getSettings(db)
  const next = { ...current, ...input } as unknown as Record<string, unknown>
  const params: Record<string, unknown> = {}
  for (const col of SETTINGS_COLUMNS) params[col.key] = toDb(col, next[col.key])
  prep(
    db,
    `UPDATE settings SET
       ${SETTINGS_COLUMNS.map((col) => `${col.name} = @${col.key}`).join(',\n       ')},
       updated_at = datetime('now')
     WHERE id = 1`,
  ).run(params)
  return getSettings(db)
}

export function setWordTemplatePath(db: Database.Database, path: string | null): SettingsDTO {
  return updateSettings(db, { wordTemplatePath: path })
}

// ---------------------------------------------------------------------------
// Bank Accounts
// ---------------------------------------------------------------------------

export function listBankAccounts(db: Database.Database): BankAccountDTO[] {
  return prep(db, 'SELECT id, name FROM bank_accounts ORDER BY lower(name) ASC').all() as BankAccountDTO[]
}

export function addBankAccount(db: Database.Database, name: string): BankAccountDTO {
  const clean = (name ?? '').trim()
  if (clean.length < 1 || clean.length > 200) {
    throw new AppError('UNKNOWN', 'Bank account name must be between 1 and 200 characters')
  }
  const count = (prep(db, 'SELECT COUNT(*) AS c FROM bank_accounts').get() as { c: number }).c
  if (count >= MAX_BANK_ACCOUNTS) {
    throw new AppError('UNKNOWN', `At most ${MAX_BANK_ACCOUNTS} bank accounts are allowed`)
  }
  const dupe = prep(db, 'SELECT id FROM bank_accounts WHERE lower(name) = lower(?)').get(clean) as
    | { id: number }
    | undefined
  if (dupe) throw new AppError('UNKNOWN', `Bank account "${clean}" already exists`)
  const info = prep(db, 'INSERT INTO bank_accounts (name) VALUES (?)').run(clean)
  return { id: Number(info.lastInsertRowid), name: clean }
}

export function updateBankAccount(db: Database.Database, id: number, name: string): BankAccountDTO {
  const clean = (name ?? '').trim()
  if (clean.length < 1 || clean.length > 200) {
    throw new AppError('UNKNOWN', 'Bank account name must be between 1 and 200 characters')
  }
  const existing = prep(db, 'SELECT id FROM bank_accounts WHERE id = ?').get(id) as { id: number } | undefined
  if (!existing) throw new AppError('UNKNOWN', `Bank account ${id} not found`)
  const dupe = prep(db, 'SELECT id FROM bank_accounts WHERE lower(name) = lower(?) AND id != ?').get(
    clean,
    id,
  ) as { id: number } | undefined
  if (dupe) throw new AppError('UNKNOWN', `Bank account "${clean}" already exists`)
  prep(db, 'UPDATE bank_accounts SET name = ? WHERE id = ?').run(clean, id)
  return { id, name: clean }
}

export function deleteBankAccount(db: Database.Database, id: number): void {
  const existing = prep(db, 'SELECT id FROM bank_accounts WHERE id = ?').get(id) as { id: number } | undefined
  if (!existing) throw new AppError('UNKNOWN', `Bank account ${id} not found`)
  prep(db, 'DELETE FROM bank_accounts WHERE id = ?').run(id)
}
