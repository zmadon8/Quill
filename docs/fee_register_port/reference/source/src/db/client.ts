/**
 * Database client singleton — Task 2.2
 *
 * Initialises a better-sqlite3 database in the user's app-data directory
 * (via Electron's app.getPath('userData') when running in the main process,
 * or ~/.fee-register-dev/ when running outside Electron, e.g. in tests).
 *
 * Exports:
 *   db      — raw better-sqlite3 Database instance
 *   drizzle — Drizzle ORM client wrapping `db`
 */

import path from 'path'
import fs from 'fs'
import Database, { type Database as DatabaseType } from 'better-sqlite3'
import { drizzle as drizzleOrm } from 'drizzle-orm/better-sqlite3'
import * as schema from './schema'
import { SCHEMA_DDL } from './schemaDdl'
import { SETTINGS_COLUMNS, settingsColumnDef } from './settingsColumns'

// ---------------------------------------------------------------------------
// Resolve the database directory
// ---------------------------------------------------------------------------

function resolveDbDir(): string {
  // Running inside Electron main process — use the proper userData path so
  // the DB lands in ~/Library/Application Support/<appName>/ (macOS) or the
  // platform equivalent.
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { app } = require('electron') as typeof import('electron')
    if (app && typeof app.getPath === 'function') {
      return app.getPath('userData')
    }
  } catch {
    // electron module not available (test environment)
  }

  // Fallback: use ~/.fee-register-dev/ for tests and CLI tooling
  const home = process.env.HOME ?? process.env.USERPROFILE ?? '.'
  return path.join(home, '.fee-register-dev')
}

// ---------------------------------------------------------------------------
// Open (or create) the SQLite database
// ---------------------------------------------------------------------------

const dbDir = resolveDbDir()

// Ensure the directory exists before opening the file
if (!fs.existsSync(dbDir)) {
  fs.mkdirSync(dbDir, { recursive: true })
}

const dbPath = path.join(dbDir, 'fee-register.db')

export const db: DatabaseType = new Database(dbPath)

// ---------------------------------------------------------------------------
// Performance and integrity pragmas
// ---------------------------------------------------------------------------

// Write-Ahead Logging gives much better concurrent read performance and
// reduces the risk of corruption on an unexpected shutdown.
db.pragma('journal_mode = WAL')

// Enforce referential integrity at the SQLite level so FK violations are
// caught early rather than producing silent data anomalies.
db.pragma('foreign_keys = ON')

// ---------------------------------------------------------------------------
// Ensure the schema exists (idempotent). Runs on every startup; CREATE TABLE
// IF NOT EXISTS makes it a no-op once the tables are present.
// ---------------------------------------------------------------------------

db.exec(SCHEMA_DDL)

// ---------------------------------------------------------------------------
// Lightweight, idempotent column migrations
// ---------------------------------------------------------------------------
// `CREATE TABLE IF NOT EXISTS` does not add new columns to a table that already
// exists from an earlier version. For additive columns we check PRAGMA
// table_info and ALTER only when the column is missing, so existing databases
// (e.g. created before firm.status existed) are upgraded in place on startup.

function ensureColumn(
  table: string,
  column: string,
  definition: string,
): void {
  const cols = db.prepare(`PRAGMA table_info(${table})`).all() as Array<{ name: string }>
  if (!cols.some((c) => c.name === column)) {
    db.exec(`ALTER TABLE ${table} ADD COLUMN ${definition}`)
  }
}

// Firms gained a stored `status` column (default 'active'). Existing firms
// become 'active' via the column default applied to all existing rows.
ensureColumn('firms', 'status', "status text DEFAULT 'active' NOT NULL")

// Matters gained matter-level memo-default columns. All are nullable (or a
// boolean flag defaulting to 0) so existing matters are unaffected.
ensureColumn('matters', 'addressee_line1', 'addressee_line1 text')
ensureColumn('matters', 'addressee_line2', 'addressee_line2 text')
ensureColumn('matters', 'addressee_use_firm_name', 'addressee_use_firm_name integer DEFAULT 0 NOT NULL')
ensureColumn('matters', 'court_name', 'court_name text')
ensureColumn('matters', 'client', 'client text')
ensureColumn('matters', 'additional_details_left', 'additional_details_left text')
ensureColumn('matters', 'additional_details_right', 'additional_details_right text')
ensureColumn('matters', 'plaintiff_name', 'plaintiff_name text')
ensureColumn('matters', 'plaintiff_type', 'plaintiff_type text')
ensureColumn('matters', 'defendant_name', 'defendant_name text')
ensureColumn('matters', 'defendant_type', 'defendant_type text')

// Settings data columns are migrated from the shared SETTINGS_COLUMNS catalog
// (the same source that drives the CREATE TABLE DDL and backup). Adding a new
// setting there automatically upgrades existing databases here — no separate
// ensureColumn call to remember. ensureColumn is a no-op when the column exists.
const hadStartYears = (db.prepare("PRAGMA table_info('settings')").all() as Array<{ name: string }>).some(
  (c) => c.name === 'feebook_start_year',
)
for (const col of SETTINGS_COLUMNS) {
  ensureColumn('settings', col.name, `${col.name} ${settingsColumnDef(col)}`)
}
// One time: the former single "Initial FY" becomes the starting value of all three.
if (!hadStartYears) {
  db.exec('UPDATE settings SET memos_start_year = initial_financial_year, feebook_start_year = initial_financial_year')
}

// One-time migration of the legacy single backup schedule (frequency + folder)
// into the per-type backup jobs. The old "last close" backup used the same
// folder, so the close job inherits it too.
db.exec(`
  UPDATE settings SET
    backup_close_enabled = CASE WHEN auto_backup_dir IS NOT NULL THEN 1 ELSE 0 END,
    backup_close_dir = auto_backup_dir,
    backup_daily_enabled = CASE WHEN auto_backup_frequency = 'daily' AND auto_backup_dir IS NOT NULL THEN 1 ELSE 0 END,
    backup_daily_dir = CASE WHEN auto_backup_frequency = 'daily' THEN auto_backup_dir END,
    last_backup_daily = CASE WHEN auto_backup_frequency = 'daily' THEN last_auto_backup END,
    backup_weekly_enabled = CASE WHEN auto_backup_frequency = 'weekly' AND auto_backup_dir IS NOT NULL THEN 1 ELSE 0 END,
    backup_weekly_dir = CASE WHEN auto_backup_frequency = 'weekly' THEN auto_backup_dir END,
    last_backup_weekly = CASE WHEN auto_backup_frequency = 'weekly' THEN last_auto_backup END,
    backup_monthly_enabled = CASE WHEN auto_backup_frequency = 'monthly' AND auto_backup_dir IS NOT NULL THEN 1 ELSE 0 END,
    backup_monthly_dir = CASE WHEN auto_backup_frequency = 'monthly' THEN auto_backup_dir END,
    last_backup_monthly = CASE WHEN auto_backup_frequency = 'monthly' THEN last_auto_backup END,
    backup_migrated = 1
  WHERE id = 1 AND backup_migrated = 0
`)

// VESTIGIAL: matters.is_custom used to flag a "custom matter". Custom numbering
// is now a per-memo choice, so this column is no longer read or written. Kept
// (default 0) so existing databases need no destructive migration.
ensureColumn('matters', 'is_custom', 'is_custom integer DEFAULT 0 NOT NULL')

// Payments gained per-payment TDS: a rate, an auto-calculate flag, alongside
// the existing tds_amount. TDS is now entered at payment time, not on the memo.
ensureColumn('payments', 'tds_rate', 'tds_rate real DEFAULT 0 NOT NULL')
ensureColumn('payments', 'auto_tds', 'auto_tds integer DEFAULT 1 NOT NULL')
ensureColumn('payments', 'payment_mode', 'payment_mode text')

// Memos gained a drafts counter (statistics only) and a written-off flag.
ensureColumn('memos', 'num_drafts', 'num_drafts integer DEFAULT 0 NOT NULL')
ensureColumn('memos', 'written_off', 'written_off integer DEFAULT 0 NOT NULL')

// Memos gained draft support and optional custom-amount overrides. Draft memos
// are not numbered or listed in the main Memos page.
ensureColumn('memos', 'is_draft', 'is_draft integer DEFAULT 0 NOT NULL')
ensureColumn('memos', 'custom_fees_appearances', 'custom_fees_appearances real')
ensureColumn('memos', 'custom_fees_conferences', 'custom_fees_conferences real')
ensureColumn('memos', 'custom_fees_misc', 'custom_fees_misc real')
ensureColumn('memos', 'custom_total_fees', 'custom_total_fees real')

// Firms and Matters gained a free-text Notes field.
ensureColumn('firms', 'notes', 'notes text')
ensureColumn('matters', 'notes', 'notes text')
ensureColumn('matters', 'short_name', 'short_name text')
for (const c of ['appearances', 'conferences', 'drafts', 'billed', 'received', 'received_plus_tds']) {
  ensureColumn('period_adjustments', `ov_${c}`, `ov_${c} real`)
}

// ---------------------------------------------------------------------------
// Backfill payment_allocations from legacy single-memo payments
// ---------------------------------------------------------------------------
// Payments previously linked directly to one memo via payments.memo_id. The new
// model records allocations in payment_allocations. For any payment that has a
// memo_id but no allocation row yet, create a mirroring allocation so paid
// amounts continue to compute identically. Idempotent: runs only for payments
// with zero existing allocations.
db.exec(`
  INSERT INTO payment_allocations (payment_id, memo_id, amount, tds_amount)
  SELECT p.id, p.memo_id, p.amount, p.tds_amount
  FROM payments p
  WHERE p.memo_id IS NOT NULL
    AND NOT EXISTS (SELECT 1 FROM payment_allocations a WHERE a.payment_id = p.id)
`)

// ---------------------------------------------------------------------------
// Drizzle ORM client
// ---------------------------------------------------------------------------

export const drizzle = drizzleOrm(db, { schema })

// ---------------------------------------------------------------------------
// Seed the single-row settings record on first run
// ---------------------------------------------------------------------------
// The settings table enforces a single row via its PK (id = 1).  We use
// INSERT OR IGNORE so this is a no-op on every subsequent startup.

db.prepare(
  `INSERT OR IGNORE INTO settings (
    id,
    default_fees_per_appearance,
    default_fees_per_conference,
    default_fees_misc_drafting,
    default_additional_details_left,
    default_additional_details_right,
    default_tds_rate,
    word_template_path,
    updated_at
  ) VALUES (
    1, 0, 0, 0, NULL, NULL, 10, NULL, datetime('now')
  )`,
).run()
