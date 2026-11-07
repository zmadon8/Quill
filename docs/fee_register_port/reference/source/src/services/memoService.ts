/**
 * memoService.ts
 *
 * Pure, testable business logic for Memos. Each function takes a raw
 * better-sqlite3 Database as its first argument.
 *
 * Monetary / derived values are COMPUTED at read time and never stored:
 *   feesAppearances  = numAppearances * feesPerAppearance
 *   feesConferences  = numConferences * feesPerConference
 *   totalFees        = feesAppearances + feesConferences + feesMiscDrafting
 *   totalFeesInWords = feesInWords(totalFees)
 *   lessTds          = round2(totalFees * tdsRate / 100)
 *   amountPaid       = SUM(payment_allocations.amount + .tds_amount)  (GROSS)
 *   amountReceived   = SUM(payment_allocations.amount)                (NET of TDS)
 *   amountTds        = SUM(payment_allocations.tds_amount)
 *   amountDue        = totalFees - amountPaid (gross)
 *   dateOfLastPayment= MAX(payments.date_of_payment)
 *   status           = 'Paid' if amountPaid (gross) >= totalFees else 'Unpaid'
 */

import type Database from 'better-sqlite3'
import { AppError } from '@/types/ipc'
import type {
  MemoInput,
  MemoDetail,
  MemoListItem,
  MemoFilter,
  MemoFormData,
  RecentMatterDTO,
} from '@/types/ipc'
import { generateMemoNumber, deriveFinancialYear } from './memoNumberService'
import { feesInWords } from './feesInWordsService'
import { isMatterActive } from './matterService'
import { getSettings } from './settingsService'
import { prep, round2 } from '@/db/prep'

/** Current financial year (1 Apr–31 Mar) from the system clock, "YYYY-YY". */
function currentFinancialYearFromClock(now: Date = new Date()): string {
  const mm = String(now.getMonth() + 1).padStart(2, '0')
  return deriveFinancialYear(`${now.getFullYear()}-${mm}-01`)
}

// ---------------------------------------------------------------------------
// Computed-field helpers
// ---------------------------------------------------------------------------

export function computeFeesAppearances(numAppearances: number, feesPerAppearance: number): number {
  return round2(numAppearances * feesPerAppearance)
}
export function computeFeesConferences(numConferences: number, feesPerConference: number): number {
  return round2(numConferences * feesPerConference)
}
export function computeTotalFees(feesApp: number, feesConf: number, feesMisc: number): number {
  return round2(feesApp + feesConf + feesMisc)
}
export function computeLessTds(totalFees: number, tdsRate: number): number {
  return round2((totalFees * tdsRate) / 100)
}

/** The memo columns that determine a memo's fees (as stored in the DB). */
export interface MemoFeeColumns {
  num_appearances: number
  fees_per_appearance: number
  num_conferences: number
  fees_per_conference: number
  fees_misc_drafting: number
  custom_fees_appearances: number | null
  custom_fees_conferences: number | null
  custom_fees_misc: number | null
  custom_total_fees: number | null
}

/**
 * The SINGLE implementation of the "effective fees" rule (Req #4). Each line
 * uses its custom override when set, else count × rate (misc is a flat
 * amount); a custom TOTAL overrides the sum of the lines entirely.
 *
 * Every service that needs a memo's fees (detail, lists, outstanding,
 * dashboard, firm roll-ups, payments) calls this instead of re-deriving it.
 * The SQL equivalent for aggregate queries is MEMO_TOTAL_FEES_SQL (memoSql.ts).
 */
export function resolveMemoFees(r: MemoFeeColumns): {
  feesAppearances: number
  feesConferences: number
  feesMisc: number
  totalFees: number
} {
  const feesAppearances =
    r.custom_fees_appearances ?? computeFeesAppearances(r.num_appearances, r.fees_per_appearance)
  const feesConferences =
    r.custom_fees_conferences ?? computeFeesConferences(r.num_conferences, r.fees_per_conference)
  const feesMisc = r.custom_fees_misc ?? r.fees_misc_drafting
  const totalFees =
    r.custom_total_fees !== null
      ? round2(r.custom_total_fees)
      : computeTotalFees(feesAppearances, feesConferences, feesMisc)
  return { feesAppearances, feesConferences, feesMisc, totalFees }
}

/** Convenience: just the effective total fees for a memo row. */
export function effectiveTotalFees(r: MemoFeeColumns): number {
  return resolveMemoFees(r).totalFees
}

/**
 * Validates and de-duplicates a user-typed memo number for a custom matter
 * (Req #5). Throws if blank or already used by another memo. The caller runs
 * this inside the create/finalise transaction so the uniqueness check is safe.
 */
function assignCustomMemoNumber(
  db: Database.Database,
  raw: string | null | undefined,
  excludeMemoId?: number,
): string {
  const num = (raw ?? '').trim()
  if (num.length < 1) {
    throw new AppError('INVALID_MEMO', 'A custom memo number cannot be blank')
  }
  if (num.length > 100) {
    throw new AppError('INVALID_MEMO', 'Memo number must be at most 100 characters')
  }
  const dupe = prep(
    db,
    'SELECT id FROM memos WHERE memo_number = ? AND id != ?',
  ).get(num, excludeMemoId ?? -1) as { id: number } | undefined
  if (dupe) {
    throw new AppError('INVALID_MEMO', `Memo number "${num}" is already in use`)
  }
  return num
}

/**
 * Determines whether a memo is Overdue (Req #4): unpaid, not written off, and
 * more than `overdueDays` days past its date. A threshold of 0 disables the
 * flag entirely (returns false).
 */
export function computeIsOverdue(
  date: string,
  status: 'Paid' | 'Unpaid',
  writtenOff: boolean,
  overdueDays: number,
  now: Date = new Date(),
): boolean {
  if (overdueDays <= 0) return false
  if (status === 'Paid' || writtenOff) return false
  const memoDate = new Date(date)
  if (Number.isNaN(memoDate.getTime())) return false
  const ageDays = Math.floor((now.getTime() - memoDate.getTime()) / 86_400_000)
  return ageDays > overdueDays
}

type MemoRow = {
  id: number
  memo_number: string
  financial_year: string
  seq: number
  date: string
  matter_id: number
  firm_id: number
  partner_id: number
  addressee_line1: string
  addressee_line2: string | null
  court_name: string | null
  additional_details_left: string | null
  additional_details_right: string | null
  plaintiff_name: string | null
  plaintiff_type: string | null
  defendant_name: string | null
  defendant_type: string | null
  client: string | null
  num_appearances: number
  dates_of_appearances: string | null
  fees_per_appearance: number
  num_conferences: number
  dates_of_conferences: string | null
  fees_per_conference: number
  misc_drafting_description: string | null
  fees_misc_drafting: number
  num_drafts: number
  tds_rate: number
  written_off: number
  is_draft: number
  custom_fees_appearances: number | null
  custom_fees_conferences: number | null
  custom_fees_misc: number | null
  custom_total_fees: number | null
}

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

function validateInput(input: MemoInput, isDraft = false): void {
  // Drafts may be saved incomplete; only non-drafts require a valid date.
  if (isDraft) return
  const missing: string[] = []
  if (!input.date || !/^\d{4}-\d{2}-\d{2}/.test(input.date)) missing.push('Date')
  if (input.matterId === undefined || input.matterId === null) missing.push('Matter')
  if (missing.length > 0) {
    throw new AppError('INVALID_MEMO', `Missing or invalid required field(s): ${missing.join(', ')}`)
  }
  const feesApp = computeFeesAppearances(input.numAppearances, input.feesPerAppearance)
  const feesConf = computeFeesConferences(input.numConferences, input.feesPerConference)
  const total = computeTotalFees(feesApp, feesConf, input.feesMiscDrafting)
  if (total < 0) {
    throw new AppError('INVALID_MEMO', 'Total Fees must be greater than or equal to 0')
  }
}

// ---------------------------------------------------------------------------
// Create
// ---------------------------------------------------------------------------

export function createMemo(db: Database.Database, input: MemoInput, isDraft = false): MemoDetail {
  validateInput(input, isDraft)

  const matter = prep(db, 'SELECT id, firm_id, partner_id FROM matters WHERE id = ?').get(
    input.matterId,
  ) as { id: number; firm_id: number; partner_id: number } | undefined
  if (!matter) throw new AppError('MATTER_NOT_FOUND', `Matter ${input.matterId} not found`)
  if (!isMatterActive(db, input.matterId)) {
    throw new AppError('MATTER_ARCHIVED', 'Memos can only be created for Active Matters')
  }
  // A memo uses a user-typed CUSTOM NUMBER when one is supplied; otherwise it is
  // auto-numbered. This is a per-memo choice, independent of the matter.
  const hasCustomNumber = !!(input.customMemoNumber ?? '').trim()

  const run = db.transaction((): number => {
    // Draft memos get NO number and do not advance the sequence. Non-drafts are
    // numbered atomically — EXCEPT when the user supplied a custom number, which
    // is stored verbatim. For FY on a draft we still derive it from the date
    // (or current FY if the draft has no date yet) for later filtering.
    let memoNumber: string | null = null
    let financialYear: string
    let seq = 0
    if (isDraft) {
      financialYear = input.date ? deriveFinancialYear(input.date) : currentFinancialYearFromClock()
    } else if (hasCustomNumber) {
      // Custom memo number: use the user-typed value, validated + de-duplicated.
      memoNumber = assignCustomMemoNumber(db, input.customMemoNumber)
      financialYear = input.date ? deriveFinancialYear(input.date) : currentFinancialYearFromClock()
      seq = 0
    } else {
      memoNumber = generateMemoNumber(db, input.date)
      const parts = memoNumber.split('/')
      financialYear = parts[0]
      seq = Number(parts[1])
    }
    const info = prep(
      db,
      `INSERT INTO memos (
        memo_number, financial_year, seq, date, matter_id, firm_id, partner_id,
        addressee_line1, addressee_line2, court_name,
        additional_details_left, additional_details_right,
        plaintiff_name, plaintiff_type, defendant_name, defendant_type, client,
        num_appearances, dates_of_appearances, fees_per_appearance,
        num_conferences, dates_of_conferences, fees_per_conference,
        misc_drafting_description, fees_misc_drafting, num_drafts, tds_rate,
        is_draft, custom_fees_appearances, custom_fees_conferences,
        custom_fees_misc, custom_total_fees
      ) VALUES (
        @memoNumber, @financialYear, @seq, @date, @matterId, @firmId, @partnerId,
        @addresseeLine1, @addresseeLine2, @courtName,
        @additionalDetailsLeft, @additionalDetailsRight,
        @plaintiffName, @plaintiffType, @defendantName, @defendantType, @client,
        @numAppearances, @datesOfAppearances, @feesPerAppearance,
        @numConferences, @datesOfConferences, @feesPerConference,
        @miscDraftingDescription, @feesMiscDrafting, @numDrafts, @tdsRate,
        @isDraft, @customFeesAppearances, @customFeesConferences,
        @customFeesMisc, @customTotalFees
      )`,
    ).run({
      memoNumber,
      financialYear,
      seq,
      date: input.date,
      matterId: input.matterId,
      firmId: matter.firm_id,
      partnerId: matter.partner_id,
      addresseeLine1: input.addresseeLine1,
      addresseeLine2: input.addresseeLine2 ?? null,
      courtName: input.courtName ?? null,
      additionalDetailsLeft: input.additionalDetailsLeft ?? null,
      additionalDetailsRight: input.additionalDetailsRight ?? null,
      plaintiffName: input.plaintiffName ?? null,
      plaintiffType: input.plaintiffType ?? null,
      defendantName: input.defendantName ?? null,
      defendantType: input.defendantType ?? null,
      client: input.client ?? null,
      numAppearances: input.numAppearances,
      datesOfAppearances: input.datesOfAppearances ?? null,
      feesPerAppearance: input.feesPerAppearance,
      numConferences: input.numConferences,
      datesOfConferences: input.datesOfConferences ?? null,
      feesPerConference: input.feesPerConference,
      miscDraftingDescription: input.miscDraftingDescription ?? null,
      feesMiscDrafting: input.feesMiscDrafting,
      numDrafts: input.numDrafts ?? 0,
      // TDS is no longer a memo field; retain the column with a 0 default.
      tdsRate: 0,
      isDraft: isDraft ? 1 : 0,
      customFeesAppearances: input.customFeesAppearances ?? null,
      customFeesConferences: input.customFeesConferences ?? null,
      customFeesMisc: input.customFeesMisc ?? null,
      customTotalFees: input.customTotalFees ?? null,
    })
    return Number(info.lastInsertRowid)
  })

  const id = run()
  return getMemo(db, id)
}

/**
 * Promotes a draft memo to a numbered memo (assigns the next number for its
 * date's financial year). No-op if already finalised.
 */
export function finalizeDraft(db: Database.Database, id: number, customMemoNumber?: string | null): MemoDetail {
  const row = prep(db, 'SELECT id, date, is_draft, matter_id FROM memos WHERE id = ?').get(id) as
    | { id: number; date: string; is_draft: number; matter_id: number }
    | undefined
  if (!row) throw new AppError('MEMO_NOT_FOUND', `Memo ${id} not found`)
  if (row.is_draft === 0) return getMemo(db, id)
  if (!row.date || !/^\d{4}-\d{2}-\d{2}/.test(row.date)) {
    throw new AppError('INVALID_MEMO', 'A valid date is required before finalising a draft')
  }
  // Finalise with a user-typed custom number when one is supplied; otherwise
  // auto-number. This is a per-memo choice, independent of the matter.
  const hasCustomNumber = !!(customMemoNumber ?? '').trim()
  const tx = db.transaction(() => {
    if (hasCustomNumber) {
      // Custom number: finalise with the user-typed value (seq stays 0).
      const memoNumber = assignCustomMemoNumber(db, customMemoNumber, id)
      const fy = deriveFinancialYear(row.date)
      prep(
        db,
        "UPDATE memos SET is_draft = 0, memo_number = ?, financial_year = ?, seq = 0, updated_at = datetime('now') WHERE id = ?",
      ).run(memoNumber, fy, id)
    } else {
      const memoNumber = generateMemoNumber(db, row.date)
      const [fy, seqStr] = memoNumber.split('/')
      prep(
        db,
        "UPDATE memos SET is_draft = 0, memo_number = ?, financial_year = ?, seq = ?, updated_at = datetime('now') WHERE id = ?",
      ).run(memoNumber, fy, Number(seqStr), id)
    }
  })
  tx()
  return getMemo(db, id)
}

// ---------------------------------------------------------------------------
// Read (with computed fields)
// ---------------------------------------------------------------------------

function rowToDetail(db: Database.Database, row: MemoRow): MemoDetail {
  const firm = prep(db, 'SELECT name FROM firms WHERE id = ?').get(row.firm_id) as { name: string } | undefined
  const partner = prep(db, 'SELECT name FROM partners WHERE id = ?').get(row.partner_id) as { name: string } | undefined
  const matter = prep(db, 'SELECT name, short_name FROM matters WHERE id = ?').get(row.matter_id) as
    | { name: string; short_name: string | null }
    | undefined

  // Fee line items honour optional custom overrides (Req #4). A custom total
  // overrides everything; otherwise each line falls back to its custom value
  // or the auto-computed figure.
  const {
    feesAppearances,
    feesConferences,
    feesMisc,
    totalFees,
  } = resolveMemoFees(row)
  // Net of TDS is informational, computed at the Settings default TDS rate.
  const settings = getSettings(db)
  const defaultTdsRate = settings.defaultTdsRate
  const netOfTds = round2(totalFees - computeLessTds(totalFees, defaultTdsRate))

  // amountPaid is the sum of GROSS allocations (amount + tds) applied to this
  // memo; the memo is Paid when that covers the Memo Amount (= totalFees).
  const agg = prep(
    db,
    `SELECT COALESCE(SUM(a.amount + a.tds_amount), 0) AS paid,
            MAX(p.date_of_payment) AS last, COUNT(*) AS cnt
     FROM payment_allocations a JOIN payments p ON p.id = a.payment_id
     WHERE a.memo_id = ?`,
  ).get(row.id) as { paid: number; last: string | null; cnt: number }
  const amountPaid = round2(agg.paid)
  const status: 'Paid' | 'Unpaid' = amountPaid >= totalFees ? 'Paid' : 'Unpaid'

  return {
    id: row.id,
    memoNumber: row.memo_number,
    financialYear: row.financial_year,
    seq: row.seq,
    date: row.date,
    matterId: row.matter_id,
    firmId: row.firm_id,
    partnerId: row.partner_id,
    firmName: firm?.name ?? '',
    partnerName: partner?.name ?? '',
    matterName: matter?.name ?? '',
    matterShortName: matter?.short_name ?? undefined,
    addresseeLine1: row.addressee_line1,
    addresseeLine2: row.addressee_line2 ?? undefined,
    courtName: row.court_name ?? undefined,
    additionalDetailsLeft: row.additional_details_left ?? undefined,
    additionalDetailsRight: row.additional_details_right ?? undefined,
    plaintiffName: row.plaintiff_name ?? undefined,
    plaintiffType: row.plaintiff_type ?? undefined,
    defendantName: row.defendant_name ?? undefined,
    defendantType: row.defendant_type ?? undefined,
    client: row.client ?? undefined,
    numAppearances: row.num_appearances,
    datesOfAppearances: row.dates_of_appearances ?? undefined,
    feesPerAppearance: row.fees_per_appearance,
    numConferences: row.num_conferences,
    datesOfConferences: row.dates_of_conferences ?? undefined,
    feesPerConference: row.fees_per_conference,
    miscDraftingDescription: row.misc_drafting_description ?? undefined,
    feesMiscDrafting: row.fees_misc_drafting,
    numDrafts: row.num_drafts,
    customFeesAppearances: row.custom_fees_appearances,
    customFeesConferences: row.custom_fees_conferences,
    customFeesMisc: row.custom_fees_misc,
    customTotalFees: row.custom_total_fees,
    isDraft: row.is_draft === 1,
    feesAppearances,
    feesConferences,
    totalFees,
    totalFeesInWords: feesInWords(totalFees),
    netOfTds,
    amountPaid,
    dateOfLastPayment: agg.last,
    paymentCount: agg.cnt,
    writtenOff: row.written_off === 1,
    status,
    isOverdue: computeIsOverdue(row.date, status, row.written_off === 1, settings.overdueDays),
    // A finalised memo carries a custom number when it has a number but no
    // auto-sequence (custom numbers store seq = 0; auto numbers store seq >= 1).
    isCustomNumber: row.is_draft === 0 && row.memo_number != null && row.seq === 0,
    customMemoNumber: row.is_draft === 0 && row.seq === 0 ? row.memo_number : null,
  }
}

export function getMemo(db: Database.Database, id: number): MemoDetail {
  const row = prep(db, 'SELECT * FROM memos WHERE id = ?').get(id) as MemoRow | undefined
  if (!row) throw new AppError('MEMO_NOT_FOUND', `Memo ${id} not found`)
  return rowToDetail(db, row)
}

// ---------------------------------------------------------------------------
// Update
// ---------------------------------------------------------------------------

export function updateMemo(db: Database.Database, id: number, input: MemoInput): MemoDetail {
  const existing = prep(db, 'SELECT id, is_draft, financial_year FROM memos WHERE id = ?').get(id) as
    | { id: number; is_draft: number; financial_year: string }
    | undefined
  if (!existing) throw new AppError('MEMO_NOT_FOUND', `Memo ${id} not found`)
  validateInput(input)

  // The memo's date is editable and must persist. For a DRAFT (no number yet)
  // we also re-derive its financial_year from the new date, since nothing
  // depends on a fixed FY yet. For a FINALISED (numbered) memo the number — and
  // the FY embedded in it — are already issued, so we keep financial_year as-is
  // and only change the date. (Reissuing a number is a separate action.)
  const financialYear = existing.is_draft === 1 ? deriveFinancialYear(input.date) : existing.financial_year

  prep(
    db,
    `UPDATE memos SET
      date = @date, financial_year = @financialYear,
      addressee_line1 = @addresseeLine1, addressee_line2 = @addresseeLine2,
      court_name = @courtName,
      additional_details_left = @additionalDetailsLeft,
      additional_details_right = @additionalDetailsRight,
      plaintiff_name = @plaintiffName, plaintiff_type = @plaintiffType,
      defendant_name = @defendantName, defendant_type = @defendantType,
      client = @client,
      num_appearances = @numAppearances, dates_of_appearances = @datesOfAppearances,
      fees_per_appearance = @feesPerAppearance,
      num_conferences = @numConferences, dates_of_conferences = @datesOfConferences,
      fees_per_conference = @feesPerConference,
      misc_drafting_description = @miscDraftingDescription,
      fees_misc_drafting = @feesMiscDrafting,
      num_drafts = @numDrafts,
      custom_fees_appearances = @customFeesAppearances,
      custom_fees_conferences = @customFeesConferences,
      custom_fees_misc = @customFeesMisc,
      custom_total_fees = @customTotalFees,
      updated_at = datetime('now')
     WHERE id = @id`,
  ).run({
    id,
    date: input.date,
    financialYear,
    addresseeLine1: input.addresseeLine1,
    addresseeLine2: input.addresseeLine2 ?? null,
    courtName: input.courtName ?? null,
    additionalDetailsLeft: input.additionalDetailsLeft ?? null,
    additionalDetailsRight: input.additionalDetailsRight ?? null,
    plaintiffName: input.plaintiffName ?? null,
    plaintiffType: input.plaintiffType ?? null,
    defendantName: input.defendantName ?? null,
    defendantType: input.defendantType ?? null,
    client: input.client ?? null,
    numAppearances: input.numAppearances,
    datesOfAppearances: input.datesOfAppearances ?? null,
    feesPerAppearance: input.feesPerAppearance,
    numConferences: input.numConferences,
    datesOfConferences: input.datesOfConferences ?? null,
    feesPerConference: input.feesPerConference,
    miscDraftingDescription: input.miscDraftingDescription ?? null,
    feesMiscDrafting: input.feesMiscDrafting,
    customFeesAppearances: input.customFeesAppearances ?? null,
    customFeesConferences: input.customFeesConferences ?? null,
    customFeesMisc: input.customFeesMisc ?? null,
    customTotalFees: input.customTotalFees ?? null,
    numDrafts: input.numDrafts ?? 0,
  })
  return getMemo(db, id)
}

// ---------------------------------------------------------------------------
// Write-off (bad debt). Excluded from Outstanding unless explicitly included.
// ---------------------------------------------------------------------------

export function setMemoWrittenOff(db: Database.Database, id: number, writtenOff: boolean): MemoDetail {
  const existing = prep(db, 'SELECT id FROM memos WHERE id = ?').get(id) as { id: number } | undefined
  if (!existing) throw new AppError('MEMO_NOT_FOUND', `Memo ${id} not found`)
  // Req #1: only UNPAID (or partly paid) memos may be written off. A fully paid
  // memo cannot be written off. Writing off never alters its payments.
  if (writtenOff) {
    const detail = getMemo(db, id)
    if (detail.status === 'Paid') {
      throw new AppError('INVALID_MEMO', 'A fully paid memo cannot be written off')
    }
  }
  prep(db, "UPDATE memos SET written_off = ?, updated_at = datetime('now') WHERE id = ?").run(
    writtenOff ? 1 : 0,
    id,
  )
  return getMemo(db, id)
}

// ---------------------------------------------------------------------------
// Delete (does NOT decrement the memo-number sequence)
// ---------------------------------------------------------------------------

export function deleteMemo(db: Database.Database, id: number): void {
  const existing = prep(db, 'SELECT id FROM memos WHERE id = ?').get(id) as { id: number } | undefined
  if (!existing) throw new AppError('MEMO_NOT_FOUND', `Memo ${id} not found`)
  const tx = db.transaction(() => {
    // Remove allocations to this memo, then any payments that are now orphaned
    // (no remaining allocations and not linked elsewhere), then the memo.
    prep(db, 'DELETE FROM payment_allocations WHERE memo_id = ?').run(id)
    prep(
      db,
      `DELETE FROM payments
       WHERE memo_id = ?
         AND NOT EXISTS (SELECT 1 FROM payment_allocations a WHERE a.payment_id = payments.id)`,
    ).run(id)
    prep(db, 'DELETE FROM memos WHERE id = ?').run(id)
  })
  tx()
}

// ---------------------------------------------------------------------------
// Draft memos (Req #3): unnumbered, listed only on the Matter page and the
// dedicated Draft Memos view, never in the main Memos list.
// ---------------------------------------------------------------------------

export function listDrafts(db: Database.Database): MemoListItem[] {
  return listMemosInternal(db, {}, 'draftsOnly')
}

/**
 * Resolves a finalised memo number (e.g. "2025-26/144") to its id, or null if
 * no memo carries that number. Used when reassigning a payment to a memo by
 * number from the Feebook. Match is exact (case-insensitive, trimmed).
 */
export function findMemoIdByNumber(db: Database.Database, memoNumber: string): number | null {
  const n = (memoNumber ?? '').trim()
  if (!n) return null
  const row = prep(
    db,
    'SELECT id FROM memos WHERE lower(memo_number) = lower(?) AND is_draft = 0',
  ).get(n) as { id: number } | undefined
  return row ? row.id : null
}

// ---------------------------------------------------------------------------
// List (with filters)
// ---------------------------------------------------------------------------

export function listMemos(db: Database.Database, filter: MemoFilter = {}): MemoListItem[] {
  return listMemosInternal(db, filter, 'excludeDrafts')
}

/**
 * Shared memo listing. `draftMode` controls draft handling:
 *   - 'excludeDrafts' : only finalised (numbered) memos (main Memos page)
 *   - 'draftsOnly'    : only draft memos (Draft Memos page)
 *   - 'all'           : both (used by the Matter page)
 */
function listMemosInternal(
  db: Database.Database,
  filter: MemoFilter = {},
  draftMode: 'excludeDrafts' | 'draftsOnly' | 'all' = 'excludeDrafts',
): MemoListItem[] {
  const where: string[] = []
  const params: Record<string, unknown> = {}

  if (draftMode === 'excludeDrafts') where.push('m.is_draft = 0')
  else if (draftMode === 'draftsOnly') where.push('m.is_draft = 1')

  if (filter.financialYear) {
    where.push('m.financial_year = @financialYear')
    params.financialYear = filter.financialYear
  }
  if (filter.firmId !== undefined) {
    where.push('m.firm_id = @firmId')
    params.firmId = filter.firmId
  }
  if (filter.partnerId === 'none') {
    // reserved for future "unassigned" semantics; no-op for now
  } else if (filter.partnerId !== undefined) {
    where.push('m.partner_id = @partnerId')
    params.partnerId = filter.partnerId
  }
  if (filter.selectedMatterIds && filter.selectedMatterIds.length > 0) {
    const names = filter.selectedMatterIds.map((_, i) => `@sm${i}`)
    filter.selectedMatterIds.forEach((v, i) => (params[`sm${i}`] = v))
    where.push(`m.matter_id IN (${names.join(', ')})`)
  } else if (filter.matterId !== undefined) {
    where.push('m.matter_id = @matterId')
    params.matterId = filter.matterId
  }

  const whereSql = where.length ? `WHERE ${where.join(' AND ')}` : ''

  const rows = prep(
    db,
    `SELECT m.id, m.memo_number, m.financial_year, m.date, m.matter_id, m.firm_id,
            f.name AS firm_name, mt.name AS matter_name,
            m.num_appearances, m.fees_per_appearance,
            m.num_conferences, m.fees_per_conference, m.fees_misc_drafting, m.num_drafts,
            m.written_off, m.is_draft,
            m.custom_fees_appearances, m.custom_fees_conferences, m.custom_fees_misc, m.custom_total_fees,
            COALESCE((SELECT SUM(a.amount + a.tds_amount) FROM payment_allocations a WHERE a.memo_id = m.id), 0) AS amount_paid,
            COALESCE((SELECT SUM(a.amount) FROM payment_allocations a WHERE a.memo_id = m.id), 0) AS amount_received,
            COALESCE((SELECT SUM(a.tds_amount) FROM payment_allocations a WHERE a.memo_id = m.id), 0) AS amount_tds,
            (SELECT MAX(p.date_of_payment) FROM payment_allocations a JOIN payments p ON p.id = a.payment_id WHERE a.memo_id = m.id) AS last_payment,
            (SELECT COUNT(*) FROM payment_allocations a WHERE a.memo_id = m.id) AS payment_count
     FROM memos m
     JOIN firms f ON f.id = m.firm_id
     JOIN matters mt ON mt.id = m.matter_id
     ${whereSql}
     ORDER BY m.is_draft ASC, m.financial_year DESC, m.seq DESC, m.id DESC`,
  ).all(params) as Array<{
    id: number
    memo_number: string | null
    financial_year: string
    date: string
    matter_id: number
    firm_id: number
    firm_name: string
    matter_name: string
    num_appearances: number
    fees_per_appearance: number
    num_conferences: number
    fees_per_conference: number
    fees_misc_drafting: number
    num_drafts: number | null
    written_off: number
    is_draft: number
    custom_fees_appearances: number | null
    custom_fees_conferences: number | null
    custom_fees_misc: number | null
    custom_total_fees: number | null
    amount_paid: number
    amount_received: number
    amount_tds: number
    last_payment: string | null
    payment_count: number
  }>

  const settings = getSettings(db)
  const defaultTdsRate = settings.defaultTdsRate
  let items: MemoListItem[] = rows.map((r) => {
    const totalFees = effectiveTotalFees(r)
    const netOfTds = round2(totalFees - computeLessTds(totalFees, defaultTdsRate))
    const amountPaid = round2(r.amount_paid)
    const amountReceived = round2(r.amount_received)
    const amountTds = round2(r.amount_tds)
    const amountDue = round2(totalFees - amountPaid)
    const status: 'Paid' | 'Unpaid' = amountPaid >= totalFees ? 'Paid' : 'Unpaid'
    return {
      id: r.id,
      memoNumber: r.memo_number ?? '(draft)',
      isDraft: r.is_draft === 1,
      financialYear: r.financial_year,
      date: r.date,
      firmId: r.firm_id,
      firmName: r.firm_name,
      matterId: r.matter_id,
      matterName: r.matter_name,
      totalFees,
      numAppearances: r.num_appearances,
      numConferences: r.num_conferences,
      numDrafts: r.num_drafts ?? 0,
      netOfTds,
      amountPaid,
      amountReceived,
      amountTds,
      amountDue,
      dateOfLastPayment: r.last_payment,
      paymentCount: r.payment_count,
      writtenOff: r.written_off === 1,
      status,
      isOverdue: computeIsOverdue(r.date, status, r.written_off === 1, settings.overdueDays),
    }
  })

  if (filter.unpaidOnly) items = items.filter((i) => i.status === 'Unpaid')
  return items
}

/** Lists both drafts and finalised memos for a matter (Matter page). */
export function listMemosForMatter(db: Database.Database, matterId: number): MemoListItem[] {
  return listMemosInternal(db, { matterId }, 'all')
}

/**
 * Lists the most recently billed matters — those in which memos have been
 * issued — ordered by the date of their latest memo (Req #1, Dashboard). Draft
 * memos are excluded so this reflects matters with real, numbered memos.
 */
export function listRecentMatters(db: Database.Database, limit = 10): RecentMatterDTO[] {
  const rows = prep(
    db,
    `SELECT m.matter_id AS matter_id, mt.name AS matter_name,
            m.firm_id AS firm_id, f.name AS firm_name,
            MAX(m.date) AS last_date,
            COUNT(*) AS memo_count,
            mt.is_archived AS is_archived
     FROM memos m
     JOIN matters mt ON mt.id = m.matter_id
     JOIN firms f ON f.id = m.firm_id
     WHERE m.is_draft = 0
     GROUP BY m.matter_id
     ORDER BY last_date DESC, m.matter_id DESC
     LIMIT @limit`,
  ).all({ limit }) as Array<{
    matter_id: number
    matter_name: string
    firm_id: number
    firm_name: string
    last_date: string
    memo_count: number
    is_archived: number
  }>

  return rows.map((r) => {
    // Fetch the memo number of the latest memo for a nicer label.
    const latest = prep(
      db,
      `SELECT id, memo_number FROM memos
       WHERE matter_id = @matterId AND is_draft = 0
       ORDER BY date DESC, seq DESC, id DESC LIMIT 1`,
    ).get({ matterId: r.matter_id }) as { id: number; memo_number: string | null } | undefined
    return {
      matterId: r.matter_id,
      matterName: r.matter_name,
      firmId: r.firm_id,
      firmName: r.firm_name,
      lastMemoDate: r.last_date,
      lastMemoNumber: latest?.memo_number ?? null,
      lastMemoId: latest?.id ?? null,
      memoCount: r.memo_count,
      isArchived: r.is_archived === 1,
    }
  })
}

// ---------------------------------------------------------------------------
// Create Based On
// ---------------------------------------------------------------------------

export function createBasedOn(db: Database.Database, sourceMemoId: number): MemoFormData {
  const src = getMemo(db, sourceMemoId)
  return {
    sourceMemoId,
    date: '', // blank — user must enter
    matterId: src.matterId,
    addresseeLine1: src.addresseeLine1,
    addresseeLine2: src.addresseeLine2,
    courtName: src.courtName,
    additionalDetailsLeft: src.additionalDetailsLeft,
    additionalDetailsRight: src.additionalDetailsRight,
    plaintiffName: src.plaintiffName,
    plaintiffType: src.plaintiffType,
    defendantName: src.defendantName,
    defendantType: src.defendantType,
    client: src.client,
    numAppearances: src.numAppearances,
    datesOfAppearances: src.datesOfAppearances,
    feesPerAppearance: src.feesPerAppearance,
    numConferences: src.numConferences,
    datesOfConferences: src.datesOfConferences,
    feesPerConference: src.feesPerConference,
    miscDraftingDescription: src.miscDraftingDescription,
    feesMiscDrafting: src.feesMiscDrafting,
    numDrafts: src.numDrafts,
    // Copy EVERYTHING that defines the memo, including custom amount overrides
    // and the payment-details lines (Additional Details Left/Right, copied above).
    customFeesAppearances: src.customFeesAppearances,
    customFeesConferences: src.customFeesConferences,
    customFeesMisc: src.customFeesMisc,
    customTotalFees: src.customTotalFees,
  }
}
