import { sqliteTable, integer, text, real, uniqueIndex } from 'drizzle-orm/sqlite-core'
import { sql } from 'drizzle-orm'

// ---------------------------------------------------------------------------
// firms
// ---------------------------------------------------------------------------
export const firms = sqliteTable('firms', {
  id: integer('id').primaryKey({ autoIncrement: true }),
  name: text('name').notNull().unique(),
  status: text('status').notNull().default('active'),
  notes: text('notes'),
  createdAt: text('created_at')
    .notNull()
    .default(sql`(datetime('now'))`),
  updatedAt: text('updated_at')
    .notNull()
    .default(sql`(datetime('now'))`),
})

export type Firm = typeof firms.$inferSelect
export type NewFirm = typeof firms.$inferInsert

// ---------------------------------------------------------------------------
// partners
// ---------------------------------------------------------------------------
export const partners = sqliteTable(
  'partners',
  {
    id: integer('id').primaryKey({ autoIncrement: true }),
    firmId: integer('firm_id')
      .notNull()
      .references(() => firms.id),
    name: text('name').notNull(),
    createdAt: text('created_at')
      .notNull()
      .default(sql`(datetime('now'))`),
  },
  (t) => ({
    firmPartnerUnique: uniqueIndex('partners_firm_id_name_unique').on(t.firmId, t.name),
  }),
)

export type Partner = typeof partners.$inferSelect
export type NewPartner = typeof partners.$inferInsert

// ---------------------------------------------------------------------------
// matters
// ---------------------------------------------------------------------------
export const matters = sqliteTable(
  'matters',
  {
    id: integer('id').primaryKey({ autoIncrement: true }),
    firmId: integer('firm_id')
      .notNull()
      .references(() => firms.id),
    partnerId: integer('partner_id')
      .notNull()
      .references(() => partners.id),
    name: text('name').notNull(),
    isArchived: integer('is_archived').notNull().default(0),
    /**
     * VESTIGIAL: previously flagged a "custom matter". The custom-number choice
     * is now per-memo (a memo with a user-typed number), not per-matter. Column
     * retained (always 0, never read) to avoid a destructive migration.
     */
    isCustom: integer('is_custom').notNull().default(0),
    // Matter-level memo defaults, shared by all memos created in this matter.
    addresseeLine1: text('addressee_line1'),
    addresseeLine2: text('addressee_line2'),
    addresseeUseFirmName: integer('addressee_use_firm_name').notNull().default(0),
    courtName: text('court_name'),
    client: text('client'),
    additionalDetailsLeft: text('additional_details_left'),
    additionalDetailsRight: text('additional_details_right'),
    plaintiffName: text('plaintiff_name'),
    plaintiffType: text('plaintiff_type'),
    defendantName: text('defendant_name'),
    defendantType: text('defendant_type'),
    notes: text('notes'),
    shortName: text('short_name'),
    createdAt: text('created_at')
      .notNull()
      .default(sql`(datetime('now'))`),
    updatedAt: text('updated_at')
      .notNull()
      .default(sql`(datetime('now'))`),
  },
  (t) => ({
    firmMatterUnique: uniqueIndex('matters_firm_id_name_unique').on(t.firmId, t.name),
  }),
)

export type Matter = typeof matters.$inferSelect
export type NewMatter = typeof matters.$inferInsert

// ---------------------------------------------------------------------------
// bank_accounts
// ---------------------------------------------------------------------------
export const bankAccounts = sqliteTable('bank_accounts', {
  id: integer('id').primaryKey({ autoIncrement: true }),
  name: text('name').notNull().unique(),
  createdAt: text('created_at')
    .notNull()
    .default(sql`(datetime('now'))`),
})

export type BankAccount = typeof bankAccounts.$inferSelect
export type NewBankAccount = typeof bankAccounts.$inferInsert

// ---------------------------------------------------------------------------
// memos
// ---------------------------------------------------------------------------
export const memos = sqliteTable('memos', {
  id: integer('id').primaryKey({ autoIncrement: true }),
  memoNumber: text('memo_number').unique(),
  financialYear: text('financial_year').notNull(),
  seq: integer('seq').notNull(),
  date: text('date').notNull(),
  matterId: integer('matter_id')
    .notNull()
    .references(() => matters.id),
  // Denormalised for query performance
  firmId: integer('firm_id')
    .notNull()
    .references(() => firms.id),
  partnerId: integer('partner_id')
    .notNull()
    .references(() => partners.id),
  addresseeLine1: text('addressee_line1').notNull(),
  addresseeLine2: text('addressee_line2'),
  courtName: text('court_name'),
  additionalDetailsLeft: text('additional_details_left'),
  additionalDetailsRight: text('additional_details_right'),
  plaintiffName: text('plaintiff_name'),
  plaintiffType: text('plaintiff_type'),
  defendantName: text('defendant_name'),
  defendantType: text('defendant_type'),
  client: text('client'),
  numAppearances: integer('num_appearances').notNull().default(0),
  datesOfAppearances: text('dates_of_appearances'),
  feesPerAppearance: real('fees_per_appearance').notNull().default(0),
  numConferences: integer('num_conferences').notNull().default(0),
  datesOfConferences: text('dates_of_conferences'),
  feesPerConference: real('fees_per_conference').notNull().default(0),
  miscDraftingDescription: text('misc_drafting_description'),
  feesMiscDrafting: real('fees_misc_drafting').notNull().default(0),
  numDrafts: integer('num_drafts').notNull().default(0),
  /** Vestigial — TDS is recorded per payment now; always 0, never read. */
  tdsRate: real('tds_rate').notNull().default(0),
  writtenOff: integer('written_off').notNull().default(0),
  isDraft: integer('is_draft').notNull().default(0),
  customFeesAppearances: real('custom_fees_appearances'),
  customFeesConferences: real('custom_fees_conferences'),
  customFeesMisc: real('custom_fees_misc'),
  customTotalFees: real('custom_total_fees'),
  createdAt: text('created_at')
    .notNull()
    .default(sql`(datetime('now'))`),
  updatedAt: text('updated_at')
    .notNull()
    .default(sql`(datetime('now'))`),
})

export type Memo = typeof memos.$inferSelect
export type NewMemo = typeof memos.$inferInsert

// ---------------------------------------------------------------------------
// payments
// ---------------------------------------------------------------------------
export const payments = sqliteTable('payments', {
  id: integer('id').primaryKey({ autoIncrement: true }),
  memoId: integer('memo_id').references(() => memos.id), // nullable — unaccounted entries
  amount: real('amount').notNull(),
  tdsRate: real('tds_rate').notNull().default(0),
  autoTds: integer('auto_tds').notNull().default(1),
  tdsAmount: real('tds_amount').notNull().default(0),
  memoAmount: real('memo_amount').notNull().default(0),
  dateOfPayment: text('date_of_payment').notNull(),
  payee: text('payee'),
  bankAccountId: integer('bank_account_id').references(() => bankAccounts.id), // nullable
  paymentDetails: text('payment_details'), // internal only, never exported
  paymentMode: text('payment_mode'), // e.g. Cheque / NEFT / UPI / Cash
  createdAt: text('created_at')
    .notNull()
    .default(sql`(datetime('now'))`),
  updatedAt: text('updated_at')
    .notNull()
    .default(sql`(datetime('now'))`),
})

export type Payment = typeof payments.$inferSelect
export type NewPayment = typeof payments.$inferInsert

// ---------------------------------------------------------------------------
// settings  (single-row table, enforced by CHECK id = 1)
// ---------------------------------------------------------------------------
export const settings = sqliteTable('settings', {
  id: integer('id').primaryKey(),
  defaultFeesPerAppearance: real('default_fees_per_appearance').notNull().default(0),
  defaultFeesPerConference: real('default_fees_per_conference').notNull().default(0),
  defaultFeesMiscDrafting: real('default_fees_misc_drafting').notNull().default(0),
  defaultAdditionalDetailsLeft: text('default_additional_details_left'),
  defaultAdditionalDetailsRight: text('default_additional_details_right'),
  defaultCourtName: text('default_court_name'),
  defaultTdsRate: real('default_tds_rate').notNull().default(10),
  /** Amount Received prefill: 'zero' | 'full' | 'netOfTds'. */
  defaultPaymentAmount: text('default_payment_amount').notNull().default('zero'),
  /** Days after a memo's date before an unpaid memo is flagged Overdue (0 = off). */
  overdueDays: integer('overdue_days').notNull().default(0),
  /** Tab the app opens on at launch. */
  defaultTab: text('default_tab').notNull().default('memos'),
  /** Automatic backup frequency: 'off' | 'daily' | 'weekly' | 'monthly'. */
  autoBackupFrequency: text('auto_backup_frequency').notNull().default('off'),
  /** Destination folder for automatic backups (nullable until chosen). */
  autoBackupDir: text('auto_backup_dir'),
  /** ISO timestamp of the last successful automatic backup (nullable). */
  lastAutoBackup: text('last_auto_backup'),
  wordTemplatePath: text('word_template_path'), // nullable
  /** First financial year actively maintained; earlier data is historical only. */
  initialFinancialYear: text('initial_financial_year').notNull().default('2026-27'),
  memosStartYear: text('memos_start_year').notNull().default('2026-27'),
  feebookStartYear: text('feebook_start_year').notNull().default('2026-27'),
  /** Money display mode for tables: 'full' | 'truncated'. */
  moneyUnit: text('money_unit').notNull().default('full'),
  updatedAt: text('updated_at')
    .notNull()
    .default(sql`(datetime('now'))`),
})

export type Settings = typeof settings.$inferSelect
export type NewSettings = typeof settings.$inferInsert

// ---------------------------------------------------------------------------
// memo_number_sequences
// ---------------------------------------------------------------------------
export const memoNumberSequences = sqliteTable('memo_number_sequences', {
  financialYear: text('financial_year').primaryKey(),
  lastSeq: integer('last_seq').notNull().default(0),
})

export type MemoNumberSequence = typeof memoNumberSequences.$inferSelect
export type NewMemoNumberSequence = typeof memoNumberSequences.$inferInsert

// ---------------------------------------------------------------------------
// payment_allocations — a payment split across one, several, or no memos
// ---------------------------------------------------------------------------
export const paymentAllocations = sqliteTable('payment_allocations', {
  id: integer('id').primaryKey({ autoIncrement: true }),
  paymentId: integer('payment_id')
    .notNull()
    .references(() => payments.id),
  memoId: integer('memo_id')
    .notNull()
    .references(() => memos.id),
  amount: real('amount').notNull().default(0),
  tdsAmount: real('tds_amount').notNull().default(0),
  createdAt: text('created_at')
    .notNull()
    .default(sql`(datetime('now'))`),
})

export type PaymentAllocation = typeof paymentAllocations.$inferSelect
export type NewPaymentAllocation = typeof paymentAllocations.$inferInsert

// ---------------------------------------------------------------------------
// period_adjustments — per-month working days + extra counts for Statistics
// ---------------------------------------------------------------------------
export const periodAdjustments = sqliteTable(
  'period_adjustments',
  {
    id: integer('id').primaryKey({ autoIncrement: true }),
    financialYear: text('financial_year').notNull(),
    month: integer('month').notNull(),
    workingDays: integer('working_days').notNull().default(0),
    extraAppearances: integer('extra_appearances').notNull().default(0),
    extraConferences: integer('extra_conferences').notNull().default(0),
    extraDrafts: integer('extra_drafts').notNull().default(0),
    ovAppearances: real('ov_appearances'),
    ovConferences: real('ov_conferences'),
    ovDrafts: real('ov_drafts'),
    ovBilled: real('ov_billed'),
    ovReceived: real('ov_received'),
    ovReceivedPlusTds: real('ov_received_plus_tds'),
    updatedAt: text('updated_at')
      .notNull()
      .default(sql`(datetime('now'))`),
  },
  (t) => ({
    fyMonthUnique: uniqueIndex('period_adjustments_fy_month').on(t.financialYear, t.month),
  }),
)

export type PeriodAdjustment = typeof periodAdjustments.$inferSelect
export type NewPeriodAdjustment = typeof periodAdjustments.$inferInsert

// ---------------------------------------------------------------------------
// saved_views — persisted Statistics pivot configurations (Option 5)
// ---------------------------------------------------------------------------
export const savedViews = sqliteTable('saved_views', {
  id: integer('id').primaryKey({ autoIncrement: true }),
  name: text('name').notNull(),
  measure: text('measure').notNull(),
  rowDim: text('row_dim').notNull(),
  colDim: text('col_dim').notNull(),
  firmId: integer('firm_id'),
  fromFy: text('from_fy'),
  toFy: text('to_fy'),
  createdAt: text('created_at')
    .notNull()
    .default(sql`(datetime('now'))`),
})

export type SavedView = typeof savedViews.$inferSelect
export type NewSavedView = typeof savedViews.$inferInsert
