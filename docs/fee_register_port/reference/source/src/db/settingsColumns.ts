/**
 * settingsColumns.ts — the SINGLE source of truth for the `settings` table's
 * data columns.
 *
 * Each entry declares the DB column, its camelCase DTO key, its value kind and
 * default. From this catalog we DERIVE: the CREATE TABLE DDL fragment, the
 * ensureColumn migrations, the backup column list and restore defaults, and the
 * generic row↔DTO mapping and UPDATE statement in settingsService.
 *
 * Adding a setting = one line here + one field on SettingsDTO (src/types/ipc.ts)
 * + (optionally) a validation rule in settingsService.updateSettings.
 */

export type SettingsKind = 'text' | 'int' | 'real' | 'bool'

export interface SettingsColumn {
  /** Column name in the settings table (snake_case). */
  name: string
  /** Property name on SettingsDTO (camelCase). */
  key: string
  kind: SettingsKind
  /** True when the column may be NULL (no NOT NULL / DEFAULT). */
  nullable?: boolean
  /** Default value (ignored for nullable columns, which default to null). */
  defaultValue?: string | number | boolean
}

const c = (
  name: string,
  key: string,
  kind: SettingsKind,
  defaultValue?: string | number | boolean,
): SettingsColumn => ({ name, key, kind, defaultValue, nullable: defaultValue === undefined })

/** Every data column of the settings table, in creation order. */
export const SETTINGS_COLUMNS: SettingsColumn[] = [
  c('default_fees_per_appearance', 'defaultFeesPerAppearance', 'real', 0),
  c('default_fees_per_conference', 'defaultFeesPerConference', 'real', 0),
  c('default_fees_misc_drafting', 'defaultFeesMiscDrafting', 'real', 0),
  c('default_additional_details_left', 'defaultAdditionalDetailsLeft', 'text'),
  c('default_additional_details_right', 'defaultAdditionalDetailsRight', 'text'),
  c('default_court_name', 'defaultCourtName', 'text'),
  c('default_tds_rate', 'defaultTdsRate', 'real', 10),
  c('overdue_days', 'overdueDays', 'int', 0),
  c('default_tab', 'defaultTab', 'text', 'memos'),
  // Legacy single-schedule backup (migrated into the per-type jobs below).
  c('auto_backup_frequency', 'autoBackupFrequency', 'text', 'off'),
  c('auto_backup_dir', 'autoBackupDir', 'text'),
  c('last_auto_backup', 'lastAutoBackup', 'text'),
  c('word_template_path', 'wordTemplatePath', 'text'),
  // Start years: initial_financial_year is the STATISTICS start year; Memos and
  // Feebook have their own.
  c('initial_financial_year', 'initialFinancialYear', 'text', '2026-27'),
  c('memos_start_year', 'memosStartYear', 'text', '2026-27'),
  c('feebook_start_year', 'feebookStartYear', 'text', '2026-27'),
  c('money_unit', 'moneyUnit', 'text', 'full'),
  // Money display: custom suffixes for the truncated mode.
  c('money_suffix_thousands', 'moneySuffixThousands', 'text', 'k'),
  c('money_suffix_lac', 'moneySuffixLac', 'text', 'lac'),
  c('money_suffix_crore', 'moneySuffixCrore', 'text', 'cr'),
  // UI preferences.
  c('hide_payment_when_paid', 'hidePaymentWhenPaid', 'bool', false),
  // New memos start with the Appearances / Conferences / Misc-Drafting ticks on (true) or off (false).
  c('default_lines_enabled', 'defaultLinesEnabled', 'bool', true),
  // Default prefill for the Amount Received box when entering a payment.
  c('default_payment_amount', 'defaultPaymentAmount', 'text', 'zero'),
  c('show_status_dots', 'showStatusDots', 'bool', true),
  c('zoom_factor', 'zoomFactor', 'real', 1),
  // Dashboard KPI selection: comma-separated KPI ids ('' = built-in default set).
  c('dashboard_kpis', 'dashboardKpis', 'text', ''),
  // Four independent backup jobs, each with an enable tick and a folder.
  c('backup_close_enabled', 'backupCloseEnabled', 'bool', false),
  c('backup_close_dir', 'backupCloseDir', 'text'),
  c('backup_daily_enabled', 'backupDailyEnabled', 'bool', false),
  c('backup_daily_dir', 'backupDailyDir', 'text'),
  c('last_backup_daily', 'lastBackupDaily', 'text'),
  c('backup_weekly_enabled', 'backupWeeklyEnabled', 'bool', false),
  c('backup_weekly_dir', 'backupWeeklyDir', 'text'),
  c('last_backup_weekly', 'lastBackupWeekly', 'text'),
  c('backup_monthly_enabled', 'backupMonthlyEnabled', 'bool', false),
  c('backup_monthly_dir', 'backupMonthlyDir', 'text'),
  c('last_backup_monthly', 'lastBackupMonthly', 'text'),
  c('backup_retention', 'backupRetention', 'int', 30),
  // One-time migration marker for the legacy → per-type backup settings.
  c('backup_migrated', 'backupMigrated', 'bool', false),
]

const sqlType = (k: SettingsKind): string => (k === 'text' ? 'text' : k === 'real' ? 'real' : 'integer')

/** SQL value literal for a column default. */
function sqlDefault(col: SettingsColumn): string {
  const v = col.defaultValue as string | number | boolean
  if (col.kind === 'bool') return v ? '1' : '0'
  if (col.kind === 'text') return `'${String(v).replace(/'/g, "''")}'`
  return String(v)
}

/** SQL column definition WITHOUT the name (type + constraints + default). */
export function settingsColumnDef(col: SettingsColumn): string {
  if (col.nullable) return sqlType(col.kind)
  return `${sqlType(col.kind)} DEFAULT ${sqlDefault(col)} NOT NULL`
}

/** The settings data columns as a `name def,` block for a CREATE TABLE body. */
export function settingsColumnsDdl(): string {
  return SETTINGS_COLUMNS.map((col) => `  ${col.name} ${settingsColumnDef(col)}`).join(',\n')
}

/** Column names for backup export/restore (id + data columns + updated_at). */
export function settingsBackupColumns(): string[] {
  return ['id', ...SETTINGS_COLUMNS.map((col) => col.name), 'updated_at']
}

/** Restore defaults for NOT-NULL settings columns, keyed by column name. */
export function settingsBackupDefaults(): Record<string, string | number> {
  const out: Record<string, string | number> = {}
  for (const col of SETTINGS_COLUMNS) {
    if (col.nullable) continue
    const v = col.defaultValue as string | number | boolean
    out[col.name] = typeof v === 'boolean' ? (v ? 1 : 0) : v
  }
  return out
}
