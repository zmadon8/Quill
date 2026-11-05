/**
 * statisticsService.ts
 *
 * Two views:
 *  1. getStatistics(breakdown)  — legacy aggregate by FY / firm / partner /
 *     matter (used by the comparison table's secondary breakdown).
 *  2. getPeriodStatistics(...)  — period-based metrics (month or financial
 *     year) including manual per-month adjustments (working days + extra
 *     appearances/conferences/drafts) and per-week figures (Req #6).
 *
 * Per-week formula (confirmed): count * 5 / workingDays.
 */

import type Database from 'better-sqlite3'
import { AppError } from '@/types/ipc'
import type {
  StatBreakdown,
  StatisticsData,
  StatRow,
  StatGranularity,
  PeriodStatistics,
  StatPeriod,
  PeriodAdjustmentDTO,
  YearEndSummary,
  PivotRequest,
  PivotResult,
  PivotRow,
  PivotMeasure,
  PivotRowDim,
  PivotColDim,
  StatOptions,
} from '@/types/ipc'
import { deriveFinancialYear } from './memoNumberService'
import { getSettings } from './settingsService'
import { prep, round2 } from '@/db/prep'
import {
  MEMO_TOTAL_FEES_SQL,
  MEMO_RECEIVED_NET_SQL,
  financialYearOfDateSql,
  paymentPeriodKeySql,
} from '@/db/memoSql'

/** The larger (later) of two FY strings; '' / undefined are ignored. */
function maxFy(a: string | undefined, b: string | undefined): string | undefined {
  if (!a) return b
  if (!b) return a
  return a >= b ? a : b
}

// ---------------------------------------------------------------------------
// Legacy breakdown (by FY / firm / partner / matter)
// ---------------------------------------------------------------------------

type Row = {
  financial_year: string
  firm_id: number
  firm_name: string
  partner_id: number
  partner_name: string
  matter_id: number
  matter_name: string
  memo_id: number
  num_appearances: number
  billed: number
  received: number
}

export function getStatistics(db: Database.Database, breakdown: StatBreakdown): StatisticsData {
  // Billed + appearances come from the memo (billing period). For the
  // financial-year breakdown, received is attributed by PAYMENT date (receipt
  // basis); for firm/partner/matter breakdowns received stays per-memo (the
  // dimension is intrinsic to the memo, not time-sensitive).
  const rows = prep(
    db,
    `SELECT m.id AS memo_id, m.financial_year, m.firm_id, f.name AS firm_name,
            m.partner_id, p.name AS partner_name,
            m.matter_id, mt.name AS matter_name, m.num_appearances,
            ${MEMO_TOTAL_FEES_SQL} AS billed,
            ${MEMO_RECEIVED_NET_SQL} AS received
     FROM memos m
     JOIN firms f ON f.id = m.firm_id
     JOIN partners p ON p.id = m.partner_id
     JOIN matters mt ON mt.id = m.matter_id
     WHERE m.is_draft = 0`,
  ).all() as Row[]

  const groups = new Map<string, StatRow>()
  const totals = { numAppearances: 0, amountBilled: 0, amountReceived: 0 }

  function keyFor(r: Row): { key: string; label: string } {
    switch (breakdown) {
      case 'financialYear': return { key: r.financial_year, label: r.financial_year }
      case 'firm': return { key: `firm:${r.firm_id}`, label: r.firm_name }
      case 'partner': return { key: `partner:${r.partner_id}`, label: r.partner_name }
      case 'matter': return { key: `matter:${r.matter_id}`, label: r.matter_name }
    }
  }

  const byFyReceipt = breakdown === 'financialYear'

  for (const r of rows) {
    const billed = round2(r.billed)
    const { key, label } = keyFor(r)
    let g = groups.get(key)
    if (!g) {
      g = { key, label, numAppearances: 0, amountBilled: 0, amountReceived: 0 }
      groups.set(key, g)
    }
    g.numAppearances += r.num_appearances
    g.amountBilled = round2(g.amountBilled + billed)
    totals.numAppearances += r.num_appearances
    totals.amountBilled = round2(totals.amountBilled + billed)
    // For non-FY breakdowns, received is summed per memo here. For the FY
    // breakdown it is filled below by payment financial year.
    if (!byFyReceipt) {
      const received = round2(r.received)
      g.amountReceived = round2(g.amountReceived + received)
      totals.amountReceived = round2(totals.amountReceived + received)
    }
  }

  if (byFyReceipt) {
    // Received per financial year of the PAYMENT (receipt basis). Ensure a row
    // exists even for an FY that only has receipts (no memos billed that year).
    const recv = prep(
      db,
      `SELECT ${financialYearOfDateSql('p.date_of_payment')} AS fy,
              COALESCE(SUM(a.amount), 0) AS received
       FROM payment_allocations a JOIN payments p ON p.id = a.payment_id
       GROUP BY fy`,
    ).all() as Array<{ fy: string; received: number }>
    for (const r of recv) {
      let g = groups.get(r.fy)
      if (!g) {
        g = { key: r.fy, label: r.fy, numAppearances: 0, amountBilled: 0, amountReceived: 0 }
        groups.set(r.fy, g)
      }
      g.amountReceived = round2(g.amountReceived + round2(r.received))
      totals.amountReceived = round2(totals.amountReceived + round2(r.received))
    }
  }

  let out = Array.from(groups.values())
  if (breakdown === 'financialYear') {
    out = out.sort((a, b) => (a.key < b.key ? 1 : a.key > b.key ? -1 : 0))
  } else {
    out = out.sort((a, b) => a.label.toLowerCase().localeCompare(b.label.toLowerCase()))
  }
  return { breakdown, rows: out, totals }
}

// ---------------------------------------------------------------------------
// Period adjustments CRUD (working days + extra counts per month)
// ---------------------------------------------------------------------------

const ADJ_COLS = `financial_year, month, working_days, extra_appearances, extra_conferences, extra_drafts,
  ov_appearances, ov_conferences, ov_drafts, ov_billed, ov_received, ov_received_plus_tds`

type AdjRow = {
  financial_year: string
  month: number
  working_days: number
  extra_appearances: number
  extra_conferences: number
  extra_drafts: number
  ov_appearances: number | null
  ov_conferences: number | null
  ov_drafts: number | null
  ov_billed: number | null
  ov_received: number | null
  ov_received_plus_tds: number | null
}

export function listAdjustments(db: Database.Database, financialYear: string): PeriodAdjustmentDTO[] {
  const rows = prep(
    db,
    `SELECT ${ADJ_COLS} FROM period_adjustments WHERE financial_year = ? ORDER BY month ASC`,
  ).all(financialYear) as AdjRow[]
  return rows.map((r) => ({
    financialYear: r.financial_year,
    month: r.month,
    workingDays: r.working_days,
    extraAppearances: r.extra_appearances,
    extraConferences: r.extra_conferences,
    extraDrafts: r.extra_drafts,
    overrideAppearances: r.ov_appearances,
    overrideConferences: r.ov_conferences,
    overrideDrafts: r.ov_drafts,
    overrideBilled: r.ov_billed,
    overrideReceived: r.ov_received,
    overrideReceivedPlusTds: r.ov_received_plus_tds,
  }))
}

/** Upserts a month's adjustment row (working days, extras, optional overrides). */
export function saveAdjustment(db: Database.Database, a: PeriodAdjustmentDTO): void {
  prep(
    db,
    `INSERT INTO period_adjustments
       (financial_year, month, working_days, extra_appearances, extra_conferences, extra_drafts,
        ov_appearances, ov_conferences, ov_drafts, ov_billed, ov_received, ov_received_plus_tds, updated_at)
     VALUES (@fy, @month, @wd, @ea, @ec, @ed, @oa, @oc, @od, @ob, @or, @ot, datetime('now'))
     ON CONFLICT(financial_year, month) DO UPDATE SET
       working_days = @wd, extra_appearances = @ea, extra_conferences = @ec,
       extra_drafts = @ed, ov_appearances = @oa, ov_conferences = @oc, ov_drafts = @od,
       ov_billed = @ob, ov_received = @or, ov_received_plus_tds = @ot,
       updated_at = datetime('now')`,
  ).run({
    fy: a.financialYear,
    month: a.month,
    wd: a.workingDays,
    ea: a.extraAppearances,
    ec: a.extraConferences,
    ed: a.extraDrafts,
    oa: a.overrideAppearances ?? null,
    oc: a.overrideConferences ?? null,
    od: a.overrideDrafts ?? null,
    ob: a.overrideBilled ?? null,
    or: a.overrideReceived ?? null,
    ot: a.overrideReceivedPlusTds ?? null,
  })
}

// ---------------------------------------------------------------------------
// Period statistics (month, quarter or financial-year granularity)
// ---------------------------------------------------------------------------

const MONTH_NAMES = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
]

/** FY months in order, and the months of each FY quarter. */
const FY_MONTH_ORDER = [4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3]
const QUARTERS: Array<{ q: number; label: string; months: number[] }> = [
  { q: 1, label: 'Q1 (Apr–Jun)', months: [4, 5, 6] },
  { q: 2, label: 'Q2 (Jul–Sep)', months: [7, 8, 9] },
  { q: 3, label: 'Q3 (Oct–Dec)', months: [10, 11, 12] },
  { q: 4, label: 'Q4 (Jan–Mar)', months: [1, 2, 3] },
]

type MemoAggRow = {
  memo_id: number
  date: string
  financial_year: string
  is_draft: number
  num_appearances: number
  num_conferences: number
  num_drafts: number
  billed: number
}

const pad2 = (n: number) => String(n).padStart(2, '0')

/**
 * Builds period metrics. Everything is computed month by month first (so
 * manual overrides, extras and pro-rating apply in one place) and quarters /
 * financial years are then sums of those months.
 *  - 'month' / 'quarter': a financialYear is required; 12 months / 4 quarters.
 *  - 'financialYear': every FY present (on or after the Initial FY).
 */
export function getPeriodStatistics(
  db: Database.Database,
  granularity: StatGranularity,
  financialYear: string | null,
  options: StatOptions = {},
  now: Date = new Date(),
): PeriodStatistics {
  const proRate = options.proRateCurrentMonth ?? true
  const excludeFuture = options.excludeFutureMonths ?? true
  const excludeCurrent = options.excludeCurrentMonth ?? false
  const includeDrafts = options.includeDrafts ?? false
  // Enforce the Initial-FY cutoff on the server regardless of the renderer:
  // never show data before the configured Initial FY. A caller-supplied
  // minFinancialYear can only narrow further (pick the later bound).
  const initialFy = getSettings(db).initialFinancialYear
  const minFinancialYear = maxFy(options.minFinancialYear, initialFy)
  if (granularity !== 'financialYear' && !financialYear) {
    throw new Error('financialYear is required for month / quarter granularity')
  }
  const curYear = now.getFullYear()
  const curMonth = now.getMonth() + 1 // 1..12
  const curDay = now.getDate()
  const daysInMonth = (y: number, mo: number) => new Date(y, mo, 0).getDate()
  const curFy = deriveFinancialYear(`${curYear}-${pad2(curMonth)}-${pad2(curDay)}`)
  const curKey = `${curFy}-${pad2(curMonth)}`

  /**
   * Working days to use for a month in per-week math: future → 0, current →
   * pro-rated to elapsed days, past → as entered.
   */
  const resolveWorkingDays = (calMonth: number, calYear: number, enteredWd: number) => {
    const isCurrent = calYear === curYear && calMonth === curMonth
    const isFuture = calYear > curYear || (calYear === curYear && calMonth > curMonth)
    if (isFuture) {
      return { effectiveWd: excludeFuture ? 0 : enteredWd, isCurrent, isFuture, daysCompleted: 0 }
    }
    if (isCurrent && proRate) {
      const dim = daysInMonth(calYear, calMonth)
      const done = Math.round(enteredWd * (curDay / dim))
      return { effectiveWd: done, isCurrent, isFuture, daysCompleted: done }
    }
    return { effectiveWd: enteredWd, isCurrent, isFuture, daysCompleted: enteredWd }
  }

  /** The calendar year a given FY-month falls in (Apr-Dec = first year). */
  const calYearForFyMonth = (fy: string, calMonth: number): number => {
    const first = Number(fy.slice(0, 4))
    return calMonth >= 4 ? first : first + 1
  }

  // Billed + counts come from the memo (billing period). Draft memos, when
  // included, count as issued in the CURRENT month.
  const memos = prep(
    db,
    `SELECT m.id AS memo_id, m.date, m.financial_year, m.is_draft,
            m.num_appearances, m.num_conferences, m.num_drafts,
            ${MEMO_TOTAL_FEES_SQL} AS billed
     FROM memos m WHERE ${includeDrafts ? '1 = 1' : 'm.is_draft = 0'}`,
  ).all() as MemoAggRow[]

  type Acc = {
    numAppearances: number
    numConferences: number
    numDrafts: number
    amountBilled: number
    amountReceived: number
    amountReceivedPlusTds: number
    amountRecovered: number
  }
  const acc = new Map<string, Acc>()
  const blank = (): Acc => ({
    numAppearances: 0, numConferences: 0, numDrafts: 0,
    amountBilled: 0, amountReceived: 0, amountReceivedPlusTds: 0, amountRecovered: 0,
  })
  const accFor = (key: string): Acc => {
    let a = acc.get(key)
    if (!a) { a = blank(); acc.set(key, a) }
    return a
  }

  for (const r of memos) {
    const key = r.is_draft === 1 ? curKey : `${r.financial_year}-${r.date.slice(5, 7)}`
    const a = accFor(key)
    a.numAppearances += r.num_appearances
    a.numConferences += r.num_conferences
    a.numDrafts += r.num_drafts
    a.amountBilled = round2(a.amountBilled + r.billed)
  }

  // RECEIVED (receipt basis): by the PAYMENT date's month, whatever memo FY.
  const recvRows = prep(
    db,
    `SELECT ${paymentPeriodKeySql('p.date_of_payment', 'month')} AS period,
            COALESCE(SUM(a.amount), 0) AS received,
            COALESCE(SUM(a.amount + a.tds_amount), 0) AS received_plus_tds
     FROM payment_allocations a
     JOIN payments p ON p.id = a.payment_id
     GROUP BY period`,
  ).all() as Array<{ period: string; received: number; received_plus_tds: number }>
  for (const r of recvRows) {
    const a = accFor(r.period)
    a.amountReceived = round2(a.amountReceived + r.received)
    a.amountReceivedPlusTds = round2(a.amountReceivedPlusTds + r.received_plus_tds)
  }

  // RECOVERED: gross paid against memos ISSUED in the period (billing basis).
  const recoveredRows = prep(
    db,
    `SELECT (m.financial_year || '-' || substr(m.date, 6, 2)) AS period,
            COALESCE(SUM(a.amount + a.tds_amount), 0) AS recovered
     FROM payment_allocations a
     JOIN memos m ON m.id = a.memo_id
     WHERE m.is_draft = 0
     GROUP BY period`,
  ).all() as Array<{ period: string; recovered: number }>
  for (const r of recoveredRows) {
    const a = accFor(r.period)
    a.amountRecovered = round2(a.amountRecovered + r.recovered)
  }

  const adjRows = prep(db, `SELECT ${ADJ_COLS} FROM period_adjustments`).all() as AdjRow[]
  const adjByKey = new Map(adjRows.map((r) => [`${r.financial_year}-${pad2(r.month)}`, r]))

  const perWeek = (count: number, workingDays: number): number =>
    workingDays > 0 ? round2((count * 5) / workingDays) : 0

  /** Fills the derived ratios once a period's base figures are final. */
  const withRatios = (
    p: Omit<StatPeriod, 'appearancesPerWeek' | 'conferencesPerWeek' | 'draftsPerWeek' | 'feesPerWeek' | 'percentRecovered' | 'feesPerDay'>,
    effWd: number,
  ): StatPeriod => ({
    ...p,
    appearancesPerWeek: perWeek(p.numAppearances, effWd),
    conferencesPerWeek: perWeek(p.numConferences, effWd),
    draftsPerWeek: perWeek(p.numDrafts, effWd),
    feesPerWeek: perWeek(p.amountBilled, effWd),
    percentRecovered: p.amountBilled > 0 ? round2((p.amountRecovered / p.amountBilled) * 100) : 0,
    feesPerDay: (p.daysCompleted ?? 0) > 0 ? round2(p.amountBilled / (p.daysCompleted ?? 1)) : 0,
  })

  type MonthPart = { p: StatPeriod; effWd: number; entered: number }
  /** The 12 monthly periods of one FY (overrides, extras and pro-rating applied). */
  const monthsOf = (fy: string): MonthPart[] =>
    FY_MONTH_ORDER.map((month) => {
      const key = `${fy}-${pad2(month)}`
      const a = acc.get(key) ?? blank()
      const adj = adjByKey.get(key)
      const entered = adj?.working_days ?? 0
      const { effectiveWd, isCurrent, isFuture, daysCompleted } = resolveWorkingDays(
        month,
        calYearForFyMonth(fy, month),
        entered,
      )
      const overridden: string[] = []
      const pick = (computed: number, ov: number | null | undefined, name: string) => {
        if (ov !== null && ov !== undefined) {
          overridden.push(name)
          return ov
        }
        return computed
      }
      const extraApp = adj?.extra_appearances ?? 0
      const extraConf = adj?.extra_conferences ?? 0
      const extraDraft = adj?.extra_drafts ?? 0
      const p = withRatios(
        {
          key,
          label: MONTH_NAMES[month - 1],
          financialYear: fy,
          month,
          isCurrentMonth: isCurrent,
          isFuture,
          daysCompleted,
          numAppearances: pick(a.numAppearances + extraApp, adj?.ov_appearances, 'numAppearances'),
          numConferences: pick(a.numConferences + extraConf, adj?.ov_conferences, 'numConferences'),
          numDrafts: pick(a.numDrafts + extraDraft, adj?.ov_drafts, 'numDrafts'),
          extraAppearances: extraApp,
          extraConferences: extraConf,
          extraDrafts: extraDraft,
          amountBilled: pick(a.amountBilled, adj?.ov_billed, 'amountBilled'),
          amountReceived: pick(a.amountReceived, adj?.ov_received, 'amountReceived'),
          amountReceivedPlusTds: pick(a.amountReceivedPlusTds, adj?.ov_received_plus_tds, 'amountReceivedPlusTds'),
          amountRecovered: a.amountRecovered,
          // The ENTERED working days are reported; rates use the effective ones.
          workingDays: entered,
          ...(overridden.length ? { overridden } : {}),
        },
        effectiveWd,
      )
      return { p, effWd: effectiveWd, entered }
    })

  /** Sums month parts into one quarter / year period. */
  const aggregate = (parts: MonthPart[], key: string, label: string, fy: string): StatPeriod => {
    const sum = (f: (x: StatPeriod) => number) => parts.reduce((s, x) => s + f(x.p), 0)
    const overridden = Array.from(new Set(parts.flatMap((x) => x.p.overridden ?? [])))
    const effWd = parts.reduce((s, x) => s + x.effWd, 0)
    return withRatios(
      {
        key,
        label,
        financialYear: fy,
        month: null,
        daysCompleted: effWd,
        numAppearances: sum((x) => x.numAppearances),
        numConferences: sum((x) => x.numConferences),
        numDrafts: sum((x) => x.numDrafts),
        extraAppearances: sum((x) => x.extraAppearances),
        extraConferences: sum((x) => x.extraConferences),
        extraDrafts: sum((x) => x.extraDrafts),
        amountBilled: round2(sum((x) => x.amountBilled)),
        amountReceived: round2(sum((x) => x.amountReceived)),
        amountReceivedPlusTds: round2(sum((x) => x.amountReceivedPlusTds)),
        amountRecovered: round2(sum((x) => x.amountRecovered)),
        // For rolled-up periods "working days" is the effective (elapsed) total.
        workingDays: effWd,
        ...(overridden.length ? { overridden } : {}),
      },
      effWd,
    )
  }

  let periods: StatPeriod[]
  if (granularity === 'month') {
    periods = monthsOf(financialYear as string)
      .map((x) => x.p)
      .filter((p) => !(excludeCurrent && p.isCurrentMonth))
  } else if (granularity === 'quarter') {
    const fy = financialYear as string
    const parts = monthsOf(fy)
    periods = QUARTERS.map((q) =>
      aggregate(
        parts.filter((x) => q.months.includes(x.p.month as number)),
        `${fy}-Q${q.q}`,
        q.label,
        fy,
      ),
    )
  } else {
    const fySet = new Set<string>()
    for (const k of acc.keys()) fySet.add(k.slice(0, -3))
    for (const r of adjRows) fySet.add(r.financial_year)
    // FY strings sort chronologically as plain strings ("2025-26" < "2026-27").
    const fys = Array.from(fySet)
      .filter((fy) => /^\d{4}-\d{2}$/.test(fy) && (!minFinancialYear || fy >= minFinancialYear))
      .sort((x, y) => (x < y ? 1 : -1)) // desc
    periods = fys.map((fy) => aggregate(monthsOf(fy), fy, fy, fy))
  }

  return { granularity, financialYear, periods }
}

// Re-export for callers needing FY derivation alongside stats.
export { deriveFinancialYear }

// ---------------------------------------------------------------------------
// Year-end summary (total billed / received / TDS / written off for an FY)
// ---------------------------------------------------------------------------

export function getYearEndSummary(
  db: Database.Database,
  financialYear: string,
  options: StatOptions = {},
): YearEndSummary {
  // Appearances come from the same period engine as the Statistics table, so
  // the two always agree (extras, overrides and pro-rating included).
  const period = getPeriodStatistics(db, 'financialYear', null, options).periods.find(
    (p) => p.financialYear === financialYear,
  )

  // Billed (effective total fees) is the memo's billing-year total.
  const memos = prep(
    db,
    `SELECT m.written_off,
            ${MEMO_TOTAL_FEES_SQL} AS billed
     FROM memos m WHERE m.is_draft = 0 AND m.financial_year = @fy`,
  ).all({ fy: financialYear }) as Array<{ written_off: number; billed: number }>

  let totalBilled = 0
  let totalWrittenOff = 0
  let memoCount = 0
  for (const m of memos) {
    memoCount += 1
    const billed = round2(m.billed)
    if (m.written_off === 1) {
      totalWrittenOff = round2(totalWrittenOff + billed)
    }
    totalBilled = round2(totalBilled + billed)
  }

  // Received (net) and TDS are attributed by PAYMENT date (receipt basis):
  // money actually received in this financial year, regardless of when the
  // underlying memos were billed.
  const recvRow = prep(
    db,
    `SELECT COALESCE(SUM(a.amount), 0) AS received,
            COALESCE(SUM(a.tds_amount), 0) AS tds
     FROM payment_allocations a
     JOIN payments p ON p.id = a.payment_id
     WHERE ${financialYearOfDateSql('p.date_of_payment')} = @fy`,
  ).get({ fy: financialYear }) as { received: number; tds: number }
  const totalReceived = round2(recvRow.received)
  const tdsRow = { tds: recvRow.tds }

  // New matters = matters whose EARLIEST non-draft memo falls in this FY.
  const newMattersRow = prep(
    db,
    `SELECT COUNT(*) AS c FROM (
       SELECT matter_id, MIN(date) AS first_date, MIN(financial_year) AS first_fy
       FROM memos WHERE is_draft = 0
       GROUP BY matter_id
     ) t WHERE t.first_fy = @fy`,
  ).get({ fy: financialYear }) as { c: number }

  // Distinct firms billed this FY.
  const firmsRow = prep(
    db,
    `SELECT COUNT(DISTINCT firm_id) AS c FROM memos WHERE is_draft = 0 AND financial_year = @fy`,
  ).get({ fy: financialYear }) as { c: number }

  return {
    financialYear,
    memoCount,
    totalBilled,
    totalReceived,
    totalTds: round2(tdsRow.tds),
    totalWrittenOff,
    newMatters: newMattersRow.c,
    activeFirms: firmsRow.c,
    numAppearances: period?.numAppearances ?? 0,
    appearancesPerWeek: period?.appearancesPerWeek ?? 0,
  }
}

// ---------------------------------------------------------------------------
// Annual summary details (per firm / per matter)
// ---------------------------------------------------------------------------

/**
 * Per-firm or per-matter figures for one financial year: billing (memos issued
 * in the FY) plus receipts (payments dated in the FY), side by side.
 */
export function getAnnualBreakdown(
  db: Database.Database,
  financialYear: string,
  by: 'firm' | 'matter',
): import('@/types/ipc').AnnualDetailRow[] {
  const idCol = by === 'firm' ? 'm.firm_id' : 'm.matter_id'
  const nameCol = by === 'firm' ? 'f.name' : 'mt.name'
  const billed = prep(
    db,
    `SELECT ${idCol} AS id, ${nameCol} AS name, f.name AS firm_name,
            COUNT(*) AS memos, COALESCE(SUM(m.num_appearances), 0) AS apps,
            COALESCE(SUM(m.num_conferences), 0) AS confs, COALESCE(SUM(m.num_drafts), 0) AS drafts,
            COALESCE(SUM(${MEMO_TOTAL_FEES_SQL}), 0) AS billed
     FROM memos m JOIN firms f ON f.id = m.firm_id JOIN matters mt ON mt.id = m.matter_id
     WHERE m.is_draft = 0 AND m.financial_year = @fy
     GROUP BY ${idCol}`,
  ).all({ fy: financialYear }) as Array<{
    id: number; name: string; firm_name: string; memos: number; apps: number; confs: number; drafts: number; billed: number
  }>
  const received = prep(
    db,
    `SELECT ${idCol} AS id, ${nameCol} AS name, f.name AS firm_name,
            COALESCE(SUM(a.amount), 0) AS received, COALESCE(SUM(a.tds_amount), 0) AS tds
     FROM payment_allocations a
     JOIN payments p ON p.id = a.payment_id
     JOIN memos m ON m.id = a.memo_id
     JOIN firms f ON f.id = m.firm_id JOIN matters mt ON mt.id = m.matter_id
     WHERE ${financialYearOfDateSql('p.date_of_payment')} = @fy
     GROUP BY ${idCol}`,
  ).all({ fy: financialYear }) as Array<{ id: number; name: string; firm_name: string; received: number; tds: number }>

  const out = new Map<number, import('@/types/ipc').AnnualDetailRow>()
  const row = (id: number, name: string, firmName: string) => {
    let r = out.get(id)
    if (!r) {
      r = { name, firmName, memos: 0, appearances: 0, conferences: 0, drafts: 0, billed: 0, received: 0, tds: 0 }
      out.set(id, r)
    }
    return r
  }
  for (const b of billed) {
    const r = row(b.id, b.name, b.firm_name)
    r.memos = b.memos
    r.appearances = b.apps
    r.conferences = b.confs
    r.drafts = b.drafts
    r.billed = round2(b.billed)
  }
  for (const x of received) {
    const r = row(x.id, x.name, x.firm_name)
    r.received = round2(x.received)
    r.tds = round2(x.tds)
  }
  return [...out.values()].sort((a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase()))
}

// ---------------------------------------------------------------------------
// Pivot statistics (flexible compare — Options 1–4 backend)
// ---------------------------------------------------------------------------

const MONTH_SHORT = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

type PivotMemoRow = {
  memo_id: number
  date: string
  financial_year: string
  firm_id: number
  firm_name: string
  partner_id: number
  partner_name: string
  matter_id: number
  matter_name: string
  num_appearances: number
  num_conferences: number
  num_drafts: number
  billed: number
  received: number
  received_plus_tds: number
}

const MONEY_MEASURES = new Set<PivotMeasure>(['billed', 'received', 'receivedPlusTds', 'feesPerWeek'])

function measureValue(measure: PivotMeasure, r: PivotMemoRow): number {
  switch (measure) {
    case 'appearances':
      return r.num_appearances
    case 'conferences':
      return r.num_conferences
    case 'drafts':
      return r.num_drafts
    case 'billed':
      return r.billed
    case 'received':
      return r.received
    case 'receivedPlusTds':
      return r.received_plus_tds
    case 'memos':
      return 1 // each memo counts once
    case 'matters':
    case 'mattersNew':
    case 'appearancesPerWeek':
    case 'feesPerWeek':
      return 0 // handled separately in getPivot
  }
}

/** FY-quarter: Q1 = Apr-Jun, Q2 = Jul-Sep, Q3 = Oct-Dec, Q4 = Jan-Mar. */
function fyQuarter(calMonth: number): number {
  if (calMonth >= 4 && calMonth <= 6) return 1
  if (calMonth >= 7 && calMonth <= 9) return 2
  if (calMonth >= 10 && calMonth <= 12) return 3
  return 4
}

function rowAxis(r: PivotMemoRow, dim: PivotRowDim): { key: string; label: string; sort: string } {
  const calMonth = Number(r.date.slice(5, 7))
  switch (dim) {
    case 'month':
      return {
        key: `${r.financial_year}-${String(calMonth).padStart(2, '0')}`,
        label: `${MONTH_SHORT[calMonth - 1]} ${r.financial_year}`,
        sort: `${r.financial_year}-${String(calMonth).padStart(2, '0')}`,
      }
    case 'quarter': {
      const q = fyQuarter(calMonth)
      return { key: `${r.financial_year}-Q${q}`, label: `Q${q} ${r.financial_year}`, sort: `${r.financial_year}-${q}` }
    }
    case 'financialYear':
      return { key: r.financial_year, label: r.financial_year, sort: r.financial_year }
    case 'calendarMonth':
      return { key: String(calMonth), label: MONTH_SHORT[calMonth - 1], sort: String(calMonth).padStart(2, '0') }
    case 'firm':
      return { key: `firm:${r.firm_id}`, label: r.firm_name, sort: r.firm_name.toLowerCase() }
    case 'partner':
      return { key: `partner:${r.partner_id}`, label: r.partner_name, sort: r.partner_name.toLowerCase() }
    case 'matter':
      return { key: `matter:${r.matter_id}`, label: r.matter_name, sort: r.matter_name.toLowerCase() }
  }
}

function colAxis(r: PivotMemoRow, dim: PivotColDim): { key: string; label: string; sort: string } {
  const calMonth = Number(r.date.slice(5, 7))
  switch (dim) {
    case 'none':
      return { key: 'value', label: 'Value', sort: '0' }
    case 'financialYear':
      return { key: r.financial_year, label: r.financial_year, sort: r.financial_year }
    case 'calendarMonth':
      return { key: String(calMonth), label: MONTH_SHORT[calMonth - 1], sort: String(calMonth).padStart(2, '0') }
  }
}

/**
 * Flexible pivot: choose a MEASURE and group it by a ROW dimension and an
 * optional COLUMN dimension. Enables month-wise, quarter-wise, year-wise, same
 * month across years (rowDim or colDim = calendarMonth), and firm/partner/
 * matter breakdowns — all from one function.
 */
export function getPivot(db: Database.Database, reqIn: PivotRequest): PivotResult {
  // Enforce the Initial-FY cutoff on the server: clamp the fromFy lower bound
  // up to the configured Initial FY so no pre-cutoff data can be returned,
  // regardless of what the renderer (or a stale saved view) requested.
  const initialFy = getSettings(db).initialFinancialYear
  const req: PivotRequest = { ...reqIn, fromFy: maxFy(reqIn.fromFy, initialFy) }
  if (req.measure === 'appearancesPerWeek' || req.measure === 'feesPerWeek') {
    return getPerWeekPivot(db, req)
  }
  // Received measures are attributed by PAYMENT date (receipt basis): the pivot
  // is driven by payment-allocation rows carrying the payment's date (for the
  // time axes) and the memo's firm/partner/matter (for those axes). All other
  // measures are driven by memo rows (billing period).
  const isReceiptMeasure = req.measure === 'received' || req.measure === 'receivedPlusTds'

  const params: Record<string, unknown> = {}
  let memos: PivotMemoRow[]
  // Firm filter: `firmIds` (multi) wins over the legacy single `firmId`.
  const firmIds = req.firmIds && req.firmIds.length > 0 ? req.firmIds : req.firmId !== undefined ? [req.firmId] : []
  const firmClause = (): string => {
    firmIds.forEach((v, i) => (params[`fm${i}`] = v))
    return `m.firm_id IN (${firmIds.map((_, i) => `@fm${i}`).join(', ')})`
  }

  if (isReceiptMeasure) {
    const where: string[] = ['m.is_draft = 0']
    if (firmIds.length > 0) where.push(firmClause())
    // Range is on the PAYMENT's financial year, since the time axis is the
    // payment date for receipt measures.
    const payFy = financialYearOfDateSql('p.date_of_payment')
    if (req.fromFy) {
      where.push(`${payFy} >= @fromFy`)
      params.fromFy = req.fromFy
    }
    if (req.toFy) {
      where.push(`${payFy} <= @toFy`)
      params.toFy = req.toFy
    }
    // One row per allocation: date/financial_year come from the PAYMENT; the
    // measure value is that allocation's net / gross amount.
    memos = prep(
      db,
      `SELECT m.id AS memo_id, p.date_of_payment AS date, ${payFy} AS financial_year,
              m.firm_id, f.name AS firm_name, m.partner_id, p2.name AS partner_name,
              m.matter_id, mt.name AS matter_name,
              0 AS num_appearances, 0 AS num_conferences, 0 AS num_drafts,
              0 AS billed,
              a.amount AS received,
              (a.amount + a.tds_amount) AS received_plus_tds
       FROM payment_allocations a
       JOIN payments p ON p.id = a.payment_id
       JOIN memos m ON m.id = a.memo_id
       JOIN firms f ON f.id = m.firm_id
       JOIN partners p2 ON p2.id = m.partner_id
       JOIN matters mt ON mt.id = m.matter_id
       WHERE ${where.join(' AND ')}`,
    ).all(params) as PivotMemoRow[]
  } else {
    const where: string[] = ['m.is_draft = 0']
    if (firmIds.length > 0) where.push(firmClause())
    if (req.fromFy) {
      where.push('m.financial_year >= @fromFy')
      params.fromFy = req.fromFy
    }
    if (req.toFy) {
      where.push('m.financial_year <= @toFy')
      params.toFy = req.toFy
    }
    memos = prep(
      db,
      `SELECT m.id AS memo_id, m.date, m.financial_year,
              m.firm_id, f.name AS firm_name, m.partner_id, p.name AS partner_name,
              m.matter_id, mt.name AS matter_name,
              m.num_appearances, m.num_conferences, m.num_drafts,
              ${MEMO_TOTAL_FEES_SQL} AS billed,
              0 AS received,
              0 AS received_plus_tds
       FROM memos m
       JOIN firms f ON f.id = m.firm_id
       JOIN partners p ON p.id = m.partner_id
       JOIN matters mt ON mt.id = m.matter_id
       WHERE ${where.join(' AND ')}`,
    ).all(params) as PivotMemoRow[]
  }

  const colMeta = new Map<string, { label: string; sort: string }>()
  const rowMeta = new Map<string, { label: string; sort: string }>()
  const cells = new Map<string, Map<string, number>>() // rowKey -> colKey -> value
  // For the 'matters' / 'mattersNew' measures we count DISTINCT matters per
  // cell, so track a set of matter IDs keyed by `${rowKey}|${colKey}` instead
  // of summing.
  const matterSets = new Map<string, Set<number>>()
  const isMatters = req.measure === 'matters'
  const isMattersNew = req.measure === 'mattersNew'
  const isDistinctMatters = isMatters || isMattersNew

  // 'mattersNew' counts a matter in the cell of its FIRST-EVER memo. The first
  // memo is resolved globally (earliest date, then lowest id) — honouring the
  // firm filter but IGNORING the FY range, so a matter whose true first memo
  // predates the range is correctly NOT counted as new within the range.
  const firstMemoByMatter = new Map<number, number>()
  if (isMattersNew) {
    const fw: string[] = ['m.is_draft = 0']
    const fp: Record<string, unknown> = {}
    if (firmIds.length > 0) {
      firmIds.forEach((v, i) => (fp[`fm${i}`] = v))
      fw.push(`m.firm_id IN (${firmIds.map((_, i) => `@fm${i}`).join(', ')})`)
    }
    const firstRows = prep(
      db,
      `SELECT m.matter_id AS matter_id, m.id AS memo_id
       FROM memos m
       WHERE ${fw.join(' AND ')}
       ORDER BY m.matter_id ASC, m.date ASC, m.id ASC`,
    ).all(fp) as Array<{ matter_id: number; memo_id: number }>
    for (const row of firstRows) {
      // First row per matter wins (list is ordered by date then id).
      if (!firstMemoByMatter.has(row.matter_id)) firstMemoByMatter.set(row.matter_id, row.memo_id)
    }
  }

  for (const r of memos) {
    // For 'new matters', only the matter's first-ever memo contributes.
    if (isMattersNew && firstMemoByMatter.get(r.matter_id) !== r.memo_id) continue
    const value = measureValue(req.measure, r)
    const ra = rowAxis(r, req.rowDim)
    const ca = colAxis(r, req.colDim)
    if (!rowMeta.has(ra.key)) rowMeta.set(ra.key, { label: ra.label, sort: ra.sort })
    if (!colMeta.has(ca.key)) colMeta.set(ca.key, { label: ca.label, sort: ca.sort })
    let rowCells = cells.get(ra.key)
    if (!rowCells) {
      rowCells = new Map()
      cells.set(ra.key, rowCells)
    }
    if (isDistinctMatters) {
      const sk = `${ra.key}|${ca.key}`
      let set = matterSets.get(sk)
      if (!set) {
        set = new Set()
        matterSets.set(sk, set)
      }
      set.add(r.matter_id)
      rowCells.set(ca.key, set.size)
    } else {
      rowCells.set(ca.key, round2((rowCells.get(ca.key) ?? 0) + value))
    }
  }

  const columns = Array.from(colMeta.entries())
    .map(([key, m]) => ({ key, label: m.label, sort: m.sort }))
    .sort((a, b) => a.sort.localeCompare(b.sort))
    .map(({ key, label }) => ({ key, label }))

  const columnTotals: Record<string, number> = {}
  let grandTotal = 0

  const rows: PivotRow[] = Array.from(rowMeta.entries())
    .map(([key, m]) => ({ key, label: m.label, sort: m.sort }))
    .sort((a, b) => a.sort.localeCompare(b.sort))
    .map(({ key, label }) => {
      const rowCells = cells.get(key) ?? new Map<string, number>()
      const out: Record<string, number> = {}
      let total = 0
      for (const col of columns) {
        const v = round2(rowCells.get(col.key) ?? 0)
        out[col.key] = v
        total = round2(total + v)
        columnTotals[col.key] = round2((columnTotals[col.key] ?? 0) + v)
      }
      grandTotal = round2(grandTotal + total)
      return { key, label, cells: out, total }
    })

  return {
    measure: req.measure,
    rowDim: req.rowDim,
    colDim: req.colDim,
    money: MONEY_MEASURES.has(req.measure),
    columns,
    rows,
    columnTotals,
    grandTotal,
  }
}

/**
 * Per-week measures (appearances / fees per week). They depend on working days,
 * which are recorded per month for ALL firms, so they are only available with
 * time-based rows and no firm filter. Values come from getPeriodStatistics so
 * they always match the Statistics table.
 */
function getPerWeekPivot(db: Database.Database, req: PivotRequest): PivotResult {
  const rowDim = req.rowDim
  if (rowDim !== 'month' && rowDim !== 'quarter' && rowDim !== 'financialYear') {
    throw new AppError('UNKNOWN', 'Per-week measures need Month, Quarter or Financial Year rows.')
  }
  if ((req.firmIds && req.firmIds.length > 0) || req.firmId !== undefined) {
    throw new AppError('UNKNOWN', 'Per-week measures are available for all firms only.')
  }
  const pick = (p: StatPeriod): number =>
    req.measure === 'appearancesPerWeek' ? p.appearancesPerWeek : p.feesPerWeek

  const fys = getPeriodStatistics(db, 'financialYear', null)
    .periods.map((p) => p.financialYear)
    .filter((fy) => (!req.fromFy || fy >= req.fromFy) && (!req.toFy || fy <= req.toFy))
    .sort()

  const rows: PivotRow[] = []
  for (const fy of fys) {
    const periods =
      rowDim === 'financialYear'
        ? getPeriodStatistics(db, 'financialYear', null).periods.filter((p) => p.financialYear === fy)
        : getPeriodStatistics(db, rowDim, fy).periods
    for (const p of periods) {
      if (p.isFuture) continue
      const label =
        rowDim === 'month' ? `${p.label} ${fy}` : rowDim === 'quarter' ? `${p.label.slice(0, 2)} ${fy}` : fy
      const v = pick(p)
      rows.push({ key: p.key, label, cells: { value: v }, total: v })
    }
  }
  const nonZero = rows.filter((r) => r.total > 0)
  const avg = nonZero.length ? round2(nonZero.reduce((a, r) => a + r.total, 0) / nonZero.length) : 0
  return {
    measure: req.measure,
    rowDim: req.rowDim,
    colDim: 'none',
    money: MONEY_MEASURES.has(req.measure),
    columns: [{ key: 'value', label: 'Value' }],
    rows,
    // For a rate the "total" is the average of the periods that have data.
    columnTotals: { value: avg },
    grandTotal: avg,
  }
}

// ---------------------------------------------------------------------------
// Saved views (Option 5)
// ---------------------------------------------------------------------------

export function listSavedViews(db: Database.Database): import('@/types/ipc').SavedView[] {
  const rows = prep(
    db,
    `SELECT id, name, measure, row_dim, col_dim, firm_id, from_fy, to_fy
     FROM saved_views ORDER BY lower(name) ASC`,
  ).all() as Array<{
    id: number
    name: string
    measure: string
    row_dim: string
    col_dim: string
    firm_id: number | null
    from_fy: string | null
    to_fy: string | null
  }>
  return rows.map((r) => ({
    id: r.id,
    name: r.name,
    measure: r.measure as PivotMeasure,
    rowDim: r.row_dim as PivotRowDim,
    colDim: r.col_dim as PivotColDim,
    firmId: r.firm_id,
    fromFy: r.from_fy,
    toFy: r.to_fy,
  }))
}

export function saveSavedView(
  db: Database.Database,
  input: import('@/types/ipc').SavedViewInput,
): import('@/types/ipc').SavedView[] {
  const name = (input.name ?? '').trim()
  if (name.length < 1 || name.length > 100) {
    throw new AppError('UNKNOWN', 'View name must be between 1 and 100 characters')
  }
  prep(
    db,
    `INSERT INTO saved_views (name, measure, row_dim, col_dim, firm_id, from_fy, to_fy)
     VALUES (@name, @measure, @rowDim, @colDim, @firmId, @fromFy, @toFy)`,
  ).run({
    name,
    measure: input.measure,
    rowDim: input.rowDim,
    colDim: input.colDim,
    firmId: input.firmId ?? null,
    fromFy: input.fromFy ?? null,
    toFy: input.toFy ?? null,
  })
  return listSavedViews(db)
}

export function deleteSavedView(db: Database.Database, id: number): import('@/types/ipc').SavedView[] {
  prep(db, 'DELETE FROM saved_views WHERE id = ?').run(id)
  return listSavedViews(db)
}
