/**
 * Shared IPC types used by both the Electron main process (handlers) and
 * the renderer (via the contextBridge preload API).
 */

/** Standard response envelope for every IPC call. */
export type IPCResponse<T> =
  | { ok: true; data: T }
  | { ok: false; error: string; details?: unknown }

// ---------------------------------------------------------------------------
// Firms / Partners / Matters
// ---------------------------------------------------------------------------

export type FirmFilter = 'all' | 'active' | 'archived'
export type MatterFilter = 'all' | 'active' | 'archived'

/** A firm's stored status. New firms default to 'active'; set manually. */
export type FirmStatus = 'active' | 'archived'

export interface FirmSummary {
  id: number
  name: string
  /** Stored status: defaults to 'active' on creation, toggled manually by the user. */
  status: FirmStatus
}

/** Firm fields editable via updateFirm (name + notes). */
export interface FirmUpdateInput {
  name?: string
  notes?: string
}

export interface PartnerDTO {
  id: number
  firmId: number
  name: string
}

/**
 * Memo defaults stored on a Matter and shared by every memo created within it.
 * All optional; `addresseeUseFirmName`, when true, means Addressee Line 1 is
 * taken from the firm's name rather than the stored addresseeLine1 value.
 */
export interface MatterMemoDefaults {
  addresseeLine1?: string
  addresseeLine2?: string
  addresseeUseFirmName?: boolean
  courtName?: string
  client?: string
  additionalDetailsLeft?: string
  additionalDetailsRight?: string
  plaintiffName?: string
  plaintiffType?: string
  defendantName?: string
  defendantType?: string
  /** Free-text notes for the matter (Req #6). */
  notes?: string
  /** Optional short name used in the Word export instead of the full name. */
  shortName?: string
}

export interface MatterDTO extends MatterMemoDefaults {
  id: number
  firmId: number
  partnerId: number
  name: string
  isArchived: boolean
  /**
   * Rolled-up payment status across the matter's finalised memos, for a status
   * dot on the Firm page. Only populated by getFirm (undefined elsewhere).
   * Rules: 'Overdue' if any memo is overdue; else 'Unpaid' if any memo is
   * unpaid; else 'Paid' (all paid). A matter with no finalised memos is null.
   */
  memoStatus?: 'Paid' | 'Unpaid' | 'Overdue' | null
  /** True when any memo in the matter is written off (shown as an extra grey dot). */
  hasWrittenOff?: boolean
}

export interface MatterInput extends MatterMemoDefaults {
  name: string
  firmId: number
  partnerId: number
}

/** Editable fields when updating an existing matter (name + memo defaults). */
export interface MatterUpdateInput extends MatterMemoDefaults {
  name?: string
  /** Move the matter to a different firm. Requires partnerId of a partner in that firm. */
  firmId?: number
  /** Reassign the matter's partner (must belong to the matter's firm, or firmId when moving). */
  partnerId?: number
}

/** A matter with its firm and partner names resolved, for list/detail views. */
export interface MatterDetail extends MatterDTO {
  firmName: string
  partnerName: string
}

/** A single global-search hit (firm, matter, or memo). */
export interface SearchResult {
  kind: 'firm' | 'matter' | 'memo'
  id: number
  title: string
  subtitle: string
}

/** At-a-glance KPIs for the Dashboard landing page. */
export interface DashboardSummary {
  totalOutstanding: number
  receivedThisMonth: number
  memosAwaitingPayment: number
  writtenOffTotal: number
  // Row 1
  billedThisMonth: number
  billedThisYear: number
  appearancesThisYear: number
  // Row 2
  receivedThisYear: number
  amountOverdue: number
}

/** A matter recently billed, for the Dashboard "recent matters" list (Req #1). */
export interface RecentMatterDTO {
  matterId: number
  matterName: string
  firmId: number
  firmName: string
  /** Date of the most recent memo issued in this matter (ISO). */
  lastMemoDate: string
  /** Memo number of that most recent memo (null if it is a draft). */
  lastMemoNumber: string | null
  /** Id of that most recent memo (for "Copy last memo"). */
  lastMemoId: number | null
  /** Count of memos issued in this matter. */
  memoCount: number
  /** Whether the matter is archived (memos can't be created for archived). */
  isArchived: boolean
}

export interface FirmDetail extends FirmSummary {
  notes: string | null
  partners: PartnerDTO[]
  matters: MatterDTO[]
}

// ---------------------------------------------------------------------------
// Memos
// ---------------------------------------------------------------------------

/** Stored (editable) memo fields. Lines 3,4 are internal; 25-30 are payment-side. */
export interface MemoInput {
  date: string
  matterId: number
  /**
   * Optional user-supplied memo number ("Custom Memo Number"). When provided
   * (non-blank), this memo uses it verbatim instead of the auto-generated
   * sequence. When omitted/blank, the memo is auto-numbered. Applies to any
   * memo regardless of its matter.
   */
  customMemoNumber?: string | null
  addresseeLine1: string
  addresseeLine2?: string
  /** Cause Title (stored in the court_name column for backward compatibility). */
  courtName?: string
  additionalDetailsLeft?: string
  additionalDetailsRight?: string
  plaintiffName?: string
  plaintiffType?: string
  defendantName?: string
  defendantType?: string
  client?: string
  numAppearances: number
  datesOfAppearances?: string
  feesPerAppearance: number
  numConferences: number
  datesOfConferences?: string
  feesPerConference: number
  miscDraftingDescription?: string
  feesMiscDrafting: number
  /** Count of drafts — statistics only; does not affect the memo total. */
  numDrafts: number
  /** Optional custom amount overrides (Req #4). null/undefined = auto-compute. */
  customFeesAppearances?: number | null
  customFeesConferences?: number | null
  customFeesMisc?: number | null
  customTotalFees?: number | null
  // NOTE: TDS is no longer a memo field — it is entered per payment. The
  // underlying memos.tds_rate column is retained but unused.
}

/** A memo row for the list view (with derived fields). */
export interface MemoListItem {
  id: number
  /** "(draft)" for unnumbered draft memos. */
  memoNumber: string
  isDraft: boolean
  financialYear: string
  date: string
  firmId: number
  firmName: string
  matterId: number
  matterName: string
  totalFees: number
  numAppearances: number
  numConferences: number
  /** Number of documents drafted. */
  numDrafts: number
  /** Total Fees minus TDS computed at the Settings default rate (informational). */
  netOfTds: number
  /** Sum of gross payments (amount + tds) applied to this memo. Drives Paid status. */
  amountPaid: number
  /** Sum of NET payments (amount only, excluding TDS) — the money actually received. */
  amountReceived: number
  /** Total TDS accounted for across this memo's payments (SUM of allocation TDS). */
  amountTds: number
  /** Outstanding = Total Fees − gross payments (amount + TDS). Can be 0 or negative. */
  amountDue: number
  dateOfLastPayment: string | null
  /** Number of payments against this memo (so the UI can show "Multiple"). */
  paymentCount: number
  /** Whether the memo has been written off (bad debt). */
  writtenOff: boolean
  /** Paid when total gross payments >= Memo Amount (Total Fees). */
  status: 'Paid' | 'Unpaid'
  /**
   * True when the memo is unpaid, not written off, and older than the Settings
   * "Overdue Days" threshold (Req #4). Always false when the threshold is 0.
   */
  isOverdue: boolean
}

/** Full memo detail: stored fields + all computed fields. */
export interface MemoDetail extends MemoInput {
  id: number
  /** The matter's optional short name (used in the Word export). */
  matterShortName?: string
  /** Null for draft memos (which are not assigned a number). */
  memoNumber: string | null
  isDraft: boolean
  financialYear: string
  seq: number
  firmId: number
  partnerId: number
  firmName: string
  partnerName: string
  matterName: string
  // Computed (never stored)
  feesAppearances: number
  feesConferences: number
  totalFees: number
  totalFeesInWords: string
  /** Total Fees minus TDS at the Settings default rate (informational). */
  netOfTds: number
  /** Sum of gross payments (amount + tds). Memo is Paid when this >= totalFees. */
  amountPaid: number
  dateOfLastPayment: string | null
  paymentCount: number
  writtenOff: boolean
  status: 'Paid' | 'Unpaid'
  /** True when unpaid, not written off, and past the Settings Overdue Days threshold. */
  isOverdue: boolean
  /** True when this memo carries a user-typed custom number (not auto-generated). */
  isCustomNumber: boolean
}

/** Pre-filled form data for "Create Based On" (no id, no number, blank date/payments). */
export interface MemoFormData extends MemoInput {
  sourceMemoId: number
}

export interface MemoFilter {
  financialYear?: string
  firmId?: number
  partnerId?: number | 'none'
  matterId?: number
  selectedMatterIds?: number[]
  unpaidOnly?: boolean
}

// ---------------------------------------------------------------------------
// Payments
// ---------------------------------------------------------------------------

/** One memo's share of a payment that is split across memos (Req #5). */
export interface PaymentAllocationInput {
  memoId: number
  amount: number
  tdsAmount?: number
}

export interface PaymentInput {
  amount: number
  /** TDS rate (%) applied to this payment. Defaults from Settings. */
  tdsRate?: number
  /** When true, tdsAmount is auto-computed; when false, it is user-entered. */
  autoTds?: boolean
  tdsAmount?: number
  memoAmount?: number
  dateOfPayment: string
  payee?: string
  bankAccountId?: number | null
  paymentDetails?: string
  /** How the payment was made (Cheque, NEFT, UPI, Cash, …). */
  paymentMode?: string
  /**
   * Explicit allocation of this payment across memos. Omit for a single-memo
   * or unaccounted payment; provide to split across several memos.
   */
  allocations?: PaymentAllocationInput[]
}

/** A payee already used on payments against a matter's memos. */
export interface MatterPayee {
  payee: string
  /** How many payments carry this payee. */
  count: number
  /** Date of the most recent one (YYYY-MM-DD). */
  lastDate: string
}
export interface PaymentAllocationDTO {
  id: number
  paymentId: number
  memoId: number
  memoNumber: string | null
  amount: number
  tdsAmount: number
  grossAmount: number
}

export interface PaymentDTO {
  id: number
  /** The single memo this payment applies to, or null if split/unaccounted. */
  memoId: number | null
  amount: number
  tdsRate: number
  autoTds: boolean
  tdsAmount: number
  /** Gross payment = amount + tdsAmount. */
  grossAmount: number
  memoAmount: number
  dateOfPayment: string
  payee: string | null
  bankAccountId: number | null
  paymentDetails: string | null
  paymentMode: string | null
  allocations: PaymentAllocationDTO[]
}

// ---------------------------------------------------------------------------
// Settings / Bank Accounts
// ---------------------------------------------------------------------------

export interface BankAccountDTO {
  id: number
  name: string
}

export interface SettingsDTO {
  defaultFeesPerAppearance: number
  defaultFeesPerConference: number
  defaultFeesMiscDrafting: number
  defaultAdditionalDetailsLeft: string | null
  defaultAdditionalDetailsRight: string | null
  /** Default Cause Title pre-filled into new memos (stored as default_court_name). */
  defaultCourtName: string | null
  defaultTdsRate: number
  /**
   * Default value to prefill the Amount Received box with when entering a new
   * payment:
   *   'zero'     - 0 (the previous, and still the default, behaviour)
   *   'full'     - the memo's full total fees
   *   'netOfTds' - the memo's total fees, less TDS at the default rate
   */
  defaultPaymentAmount: DefaultPaymentAmount
  /** Days after a memo's date before an unpaid memo is flagged Overdue (0 = off, Req #4). */
  overdueDays: number
  /** The tab the app opens on at launch (one of the top-level tabs). */
  defaultTab: string
  /** Automatic backup frequency. */
  autoBackupFrequency: 'off' | 'daily' | 'weekly' | 'monthly'
  /** Destination folder for automatic backups (null until chosen). */
  autoBackupDir: string | null
  /** ISO timestamp of the last successful automatic backup (null if never). */
  lastAutoBackup: string | null
  wordTemplatePath: string | null
  /**
   * The first financial year (e.g. "2026-27") for which data is actively
   * maintained. Statistics exclude anything before it, and the Feebook FY
   * filter starts here. Data for earlier years is kept for historical value.
   * Defaults to "2026-27".
   */
  initialFinancialYear: string
  /** First financial year offered in the Memos year filter. */
  memosStartYear: string
  /** First financial year shown in the Feebook (payments before it are hidden). */
  feebookStartYear: string
  /**
   * Money display mode for tables: 'full' (grouped integer) or 'truncated'
   * (auto-scaled to thousands / lacs / crores by magnitude). Defaults to 'full'.
   */
  moneyUnit: 'full' | 'truncated'
  /** Suffix text shown for thousands / lacs / crores in truncated mode. */
  moneySuffixThousands: string
  moneySuffixLac: string
  moneySuffixCrore: string
  /** When true, a fully-paid memo does not show a Payment button. */
  hidePaymentWhenPaid: boolean
  /**
   * Whether the Appearances, Conferences and Misc / Drafting ticks start ON
   * (true, the original behaviour) or OFF on a brand-new memo.
   */
  defaultLinesEnabled: boolean
  /** When false, the coloured status dots are hidden everywhere. */
  showStatusDots: boolean
  /** Window zoom factor (1 = 100%). */
  zoomFactor: number
  /** Comma-separated Overview KPI ids ('' = the built-in default set). */
  dashboardKpis: string
  /** Four independent backup jobs: an enable tick and a folder each. */
  backupCloseEnabled: boolean
  backupCloseDir: string | null
  backupDailyEnabled: boolean
  backupDailyDir: string | null
  lastBackupDaily: string | null
  backupWeeklyEnabled: boolean
  backupWeeklyDir: string | null
  lastBackupWeekly: string | null
  backupMonthlyEnabled: boolean
  backupMonthlyDir: string | null
  lastBackupMonthly: string | null
  /** How many timestamped backups to keep per type (0 = keep all). */
  backupRetention: number
  /** Internal: legacy backup settings have been migrated. */
  backupMigrated: boolean
}

export type DefaultPaymentAmount = 'zero' | 'full' | 'netOfTds'

export type SettingsInput = Partial<SettingsDTO>

// ---------------------------------------------------------------------------
// Feebook
// ---------------------------------------------------------------------------

export interface FeebookFilter {
  financialYear?: string
  firmId?: number
  partnerId?: number | 'none'
  bankAccountId?: number
  unaccountedOnly?: boolean
}

export interface FeebookEntry {
  paymentId: number
  /** The allocation this row represents, or null for an unaccounted payment. */
  allocationId: number | null
  memoId: number | null
  memoNumber: string | null
  /** Total fees of the linked memo (shown on hover); null when unaccounted. */
  memoTotal: number | null
  /** Firm/matter of the linked memo; null for unaccounted payments. */
  firmId: number | null
  firmName: string | null
  matterId: number | null
  matterName: string | null
  amountPaid: number
  tds: number
  /** Paid + TDS (gross) for this row — replaces the old Memo Amount column (#2). */
  paidPlusTds: number
  payee: string | null
  dateOfPayment: string
  bankAccountId: number | null
  bankAccountName: string | null
  paymentMode: string | null
  /**
   * 'Single'   — the payment was allocated to just this one memo.
   * 'Multiple' — the payment was split across several memos (see `groupMemoNumbers`).
   * Unaccounted payments (no memo) are reported as 'Single'.
   */
  paymentType: 'Single' | 'Multiple'
  /** Number of memos this payment was allocated across (1 for Single/unaccounted). */
  allocationCount: number
  /**
   * When Multiple, the memo numbers that were paid together by this one payment
   * (so the user can see which memos were settled by the same payment). Empty
   * for Single/unaccounted rows.
   */
  groupMemoNumbers: string[]
}

// ---------------------------------------------------------------------------
// Outstanding Memos
// ---------------------------------------------------------------------------

export interface OutstandingFilter {
  firmId?: number
  partnerId?: number | 'none'
  matterId?: number
  selectedMatterIds?: number[]
  /** When false/omitted, written-off memos are excluded from Outstanding. */
  includeWrittenOff?: boolean
  /** When true, only memos flagged Overdue (past the Settings threshold) are shown. */
  overdueOnly?: boolean
}

export interface OutstandingEntry {
  memoId: number
  date: string
  memoNumber: string
  matterId: number
  matterName: string
  firmId: number
  /** Firm this memo belongs to (for the all-outstanding export's Firm column). */
  firmName: string
  /** Partner responsible for this memo (for the Partner column). */
  partnerName: string
  /** Total memo amount (gross fees). */
  totalFees: number
  /** Total fees net of TDS at the Settings default rate. */
  netOfTds: number
  /** Amount already paid (gross: amount + TDS allocations). */
  amountPaid: number
  /** Remaining balance due (totalFees − amountPaid, floored at 0). */
  due: number
  /** True when this unpaid memo is past the Settings Overdue Days threshold. */
  isOverdue: boolean
  /** True when this memo is written off (only present when included). */
  isWrittenOff: boolean
}

/** Outstanding memos grouped by matter, each group with a subtotal. */
export interface OutstandingGroup {
  matterId: number
  matterName: string
  firmId: number
  firmName: string
  /** Partner responsible for this matter's memos (used to group matters partner-wise). */
  partnerId: number
  partnerName: string
  entries: OutstandingEntry[]
  /** Subtotal of the balance due across this matter's outstanding memos. */
  subtotal: number
  /** Subtotal of total memo amount across this matter's outstanding memos. */
  subtotalTotal: number
  /** Subtotal of net-of-TDS across this matter's outstanding memos. */
  subtotalNetOfTds: number
  /** Subtotal of amount paid across this matter's outstanding memos. */
  subtotalPaid: number
}

/** Sort order for the firm-wise outstanding summary (Req #3). */
export type OutstandingSort = 'name' | 'amount'

/** One firm's total outstanding balance (Req #3, firm-wise summary). */
export interface OutstandingFirmSummary {
  firmId: number
  firmName: string
  /** Total unpaid balance across all the firm's memos. */
  outstanding: number
  /** Number of memos with an outstanding balance. */
  memoCount: number
}

/** The firms + partners that actually have items in the current Outstanding view. */
export interface OutstandingScope {
  firms: { id: number; name: string }[]
  partners: { id: number; firmId: number; name: string }[]
}

// ---------------------------------------------------------------------------
// Statistics
// ---------------------------------------------------------------------------

export type StatBreakdown = 'financialYear' | 'matter' | 'firm' | 'partner'

/** Legacy breakdown row (kept for the by-firm/partner/matter table). */
export interface StatRow {
  key: string
  label: string
  numAppearances: number
  amountBilled: number
  amountReceived: number
}

export interface StatisticsData {
  breakdown: StatBreakdown
  rows: StatRow[]
  totals: {
    numAppearances: number
    amountBilled: number
    amountReceived: number
  }
}

// --- Period-based statistics (Req #6) ---

export type StatGranularity = 'month' | 'quarter' | 'financialYear'

/** Metrics for one period (a month or a financial year). */
export interface StatPeriod {
  /** Machine key: "YYYY-YY" for FY, or "YYYY-YY-MM" for a month. */
  key: string
  label: string
  financialYear: string
  /** 1..12 for a month period; null for a full-year period. */
  month: number | null
  /** True when this period is the current calendar month. */
  isCurrentMonth?: boolean
  /** True when this period lies entirely in the future (after the current month). */
  isFuture?: boolean
  /**
   * Pro-rated working days actually elapsed for the current month:
   * round(workingDays × dayOfMonth / daysInMonth). Equals workingDays for past
   * months and 0 for future months. Per-week figures use this value.
   */
  daysCompleted?: number
  // Counts INCLUDING the period's manual extras.
  numAppearances: number
  numConferences: number
  numDrafts: number
  // Manual extras shown separately so the UI can display them.
  extraAppearances: number
  extraConferences: number
  extraDrafts: number
  amountBilled: number
  amountReceived: number
  amountReceivedPlusTds: number
  workingDays: number
  // Per-week figures = count * 5 / workingDays (0 when workingDays is 0).
  appearancesPerWeek: number
  conferencesPerWeek: number
  draftsPerWeek: number
  feesPerWeek: number
  /** Gross paid (amount + TDS) against memos ISSUED in this period. */
  amountRecovered: number
  /** amountRecovered ÷ amountBilled × 100 (0 when nothing billed). */
  percentRecovered: number
  /** amountBilled ÷ daysCompleted (0 when no days completed). */
  feesPerDay: number
  /** Metric keys whose value comes from a manual override, not the data. */
  overridden?: string[]
}

export interface PeriodStatistics {
  granularity: StatGranularity
  financialYear: string | null
  periods: StatPeriod[]
}

/** Options controlling how current/future months are treated in statistics. */
export interface StatOptions {
  /** Drop the current calendar month from the output entirely. */
  excludeCurrentMonth?: boolean
  /**
   * Zero out working days (and per-week figures) for months after the current
   * one, so future months with pre-entered working days don't skew rates.
   */
  excludeFutureMonths?: boolean
  /**
   * Pro-rate the current month's working days to those elapsed so far:
   * round(workingDays × dayOfMonth / daysInMonth). On by default.
   */
  proRateCurrentMonth?: boolean
  /**
   * The Initial Financial Year cutoff: in year-wise granularity, financial
   * years earlier than this are excluded entirely (e.g. "2026-27"). Undefined
   * means no cutoff.
   */
  minFinancialYear?: string
  /** Count draft memos as issued in the current month. */
  includeDrafts?: boolean
}

export interface PeriodAdjustmentDTO {
  financialYear: string
  month: number
  workingDays: number
  extraAppearances: number
  extraConferences: number
  extraDrafts: number
  /** Optional replacements for the computed monthly values (null = computed). */
  overrideAppearances?: number | null
  overrideConferences?: number | null
  overrideDrafts?: number | null
  overrideBilled?: number | null
  overrideReceived?: number | null
  overrideReceivedPlusTds?: number | null
}

// --- Pivot statistics (flexible compare, Options 1–5) ---

export type PivotMeasure =
  | 'appearances'
  | 'conferences'
  | 'drafts'
  | 'billed'
  | 'received'
  | 'receivedPlusTds'
  | 'memos'
  | 'matters'
  | 'mattersNew'
  | 'appearancesPerWeek' // time-based rows only
  | 'feesPerWeek' // time-based rows only

/** What runs down the rows of the pivot. */
export type PivotRowDim =
  | 'month' // calendar month within a financial year (Apr-2026 …)
  | 'quarter' // financial-year quarter (Q1 = Apr-Jun …)
  | 'financialYear'
  | 'calendarMonth' // Jan..Dec collapsed across years — "same month across years"
  | 'firm'
  | 'partner'
  | 'matter'

/** What runs across the columns of the pivot ('none' = a single Value column). */
export type PivotColDim = 'none' | 'financialYear' | 'calendarMonth'

export interface PivotRequest {
  measure: PivotMeasure
  rowDim: PivotRowDim
  colDim: PivotColDim
  /** Optional firm filter (single). Prefer `firmIds`. */
  firmId?: number
  /** Optional multi-firm filter; omitted/empty = all firms. */
  firmIds?: number[]
  /** Optional inclusive financial-year range (e.g. '2023-24'..'2026-27'). */
  fromFy?: string
  toFy?: string
}

export interface PivotAxisKey {
  key: string
  label: string
}

export interface PivotRow {
  key: string
  label: string
  /** Value per column key; for colDim 'none' the single key is 'value'. */
  cells: Record<string, number>
  /** Row total across all columns. */
  total: number
}

export interface PivotResult {
  measure: PivotMeasure
  rowDim: PivotRowDim
  colDim: PivotColDim
  /** Whether this measure is monetary (for formatting). */
  money: boolean
  columns: PivotAxisKey[]
  rows: PivotRow[]
  columnTotals: Record<string, number>
  grandTotal: number
}

/** A saved pivot configuration (Option 5). */
export interface SavedView {
  id: number
  name: string
  measure: PivotMeasure
  rowDim: PivotRowDim
  colDim: PivotColDim
  firmId: number | null
  fromFy: string | null
  toFy: string | null
}

export interface SavedViewInput {
  name: string
  measure: PivotMeasure
  rowDim: PivotRowDim
  colDim: PivotColDim
  firmId?: number | null
  fromFy?: string | null
  toFy?: string | null
}

// --- Import memos from a spreadsheet ---

/** The app-side fields a user can map their spreadsheet columns onto. */
export type ImportField =
  | 'firmName'
  | 'matterName'
  | 'partnerName'
  | 'memoNumber'
  | 'date'
  | 'numAppearances'
  | 'feesPerAppearance'
  | 'numConferences'
  | 'feesPerConference'
  | 'numDrafts'
  | 'miscDescription'
  | 'feesMisc'
  | 'totalFees'
  | 'amountPaid'
  | 'paymentDate'
  | 'paymentTds'
  | 'payee'
  | 'partyPlaintiff'
  | 'partyDefendant'
  | 'courtName'
  | 'matterClient'
  | 'paymentGroup'

/** Result of inspecting an uploaded spreadsheet: its headers + a preview. */
export interface ImportInspection {
  /** Column header names found in row 1. */
  headers: string[]
  /** First few data rows (as arrays aligned to `headers`) for preview. */
  sampleRows: string[][]
  /** Total data row count. */
  rowCount: number
  /** The absolute file path the main process cached for the subsequent import. */
  filePath: string
}

/** Maps each app field to a source column header (or null to skip). */
export type ImportMapping = Partial<Record<ImportField, string | null>>

export interface ImportOptions {
  filePath: string
  mapping: ImportMapping
}

export interface ImportResult {
  firmsCreated: number
  mattersCreated: number
  memosCreated: number
  paymentsCreated: number
  rowsProcessed: number
  /** Human-readable messages for rows that were skipped or had issues. */
  warnings: string[]
}

/** One firm's or matter's figures for a financial year (Annual Summary). */
export interface AnnualDetailRow {
  name: string
  /** Matters only: the firm it belongs to. */
  firmName: string
  memos: number
  appearances: number
  conferences: number
  drafts: number
  billed: number
  /** Net received in the FY (by payment date). */
  received: number
  tds: number
}

/** Year-end summary totals for one financial year. */
export interface YearEndSummary {
  financialYear: string
  memoCount: number
  totalBilled: number
  totalReceived: number
  totalTds: number
  totalWrittenOff: number
  /** Matters whose first-ever memo was issued in this financial year. */
  newMatters: number
  /** Distinct firms billed in this financial year. */
  activeFirms: number
  /** Appearances in the year (same figure as the Statistics table). */
  numAppearances: number
  appearancesPerWeek: number
}

// ---------------------------------------------------------------------------
// Undo / Redo history
// ---------------------------------------------------------------------------

/** Availability + next-action labels for the Undo/Redo controls. */
export interface HistoryState {
  canUndo: boolean
  canRedo: boolean
  /** Describes the action that Undo would reverse (e.g. "Edit payment"). */
  undoLabel: string | null
  /** Describes the action that Redo would re-apply. */
  redoLabel: string | null
  /** All pending Undo action labels, most-recent (next to undo) first. */
  undoStack: string[]
  /** All pending Redo action labels, most-recent (next to redo) first. */
  redoStack: string[]
}

// ---------------------------------------------------------------------------
// Error codes
// ---------------------------------------------------------------------------

export type AppErrorCode =
  | 'DUPLICATE_FIRM_NAME'
  | 'INVALID_FIRM_NAME'
  | 'DUPLICATE_PARTNER_NAME'
  | 'INVALID_PARTNER_NAME'
  | 'TOO_MANY_PARTNERS'
  | 'FIRM_NOT_FOUND'
  | 'PARTNER_NOT_FOUND'
  | 'DUPLICATE_MATTER_NAME'
  | 'INVALID_MATTER_NAME'
  | 'MATTER_NOT_FOUND'
  | 'MATTER_ARCHIVED'
  | 'MEMO_NOT_FOUND'
  | 'INVALID_MEMO'
  | 'INVALID_PAYMENT'
  | 'NO_TEMPLATE'
  | 'EXPORT_FAILED'
  | 'BACKUP_FAILED'
  | 'RESTORE_FAILED'
  | 'INVALID_TEMPLATE'
  | 'UNKNOWN'

/** Error carrying a machine-readable code for mapping to UI messages. */
export class AppError extends Error {
  code: AppErrorCode
  constructor(code: AppErrorCode, message?: string) {
    super(message ?? code)
    this.code = code
    this.name = 'AppError'
  }
}

// ---------------------------------------------------------------------------
// Diagnostics (Settings → Diagnostics): resource usage for hosting estimates
// ---------------------------------------------------------------------------

/** Timing summary of one IPC channel (a unit of would-be server work). */
export interface ChannelTiming {
  channel: string
  calls: number
  totalMs: number
  p50Ms: number
  p95Ms: number
  maxMs: number
}

export interface SystemMetrics {
  at: string
  uptimeSec: number
  /** Per-process CPU % and memory (MB) as reported by Electron. */
  processes: Array<{ type: string; pid: number; cpuPercent: number; memoryMb: number }>
  totalMemoryMb: number
  /** Main process (the would-be server) resident memory, heap and CPU time. */
  mainRssMb: number
  mainHeapMb: number
  mainCpuSeconds: number
  dbSizeMb: number
  rowCounts: Record<string, number>
  channels: ChannelTiming[]
}
