/**
 * dashboardService.ts
 *
 * At-a-glance KPIs for the Dashboard landing page. All figures are computed
 * with direct aggregate SQL (no per-memo loops) and honour custom fee overrides
 * where relevant, consistent with the rest of the app.
 */

import type Database from 'better-sqlite3'
import type { DashboardSummary } from '@/types/ipc'
import { effectiveTotalFees, computeIsOverdue } from './memoService'
import { deriveFinancialYear } from './memoNumberService'
import { getPeriodStatistics } from './statisticsService'
import { getSettings } from './settingsService'
import { prep, round2 } from '@/db/prep'

type MemoFeeRow = {
  id: number
  date: string
  financial_year: string
  num_appearances: number
  fees_per_appearance: number
  num_conferences: number
  fees_per_conference: number
  fees_misc_drafting: number
  custom_fees_appearances: number | null
  custom_fees_conferences: number | null
  custom_fees_misc: number | null
  custom_total_fees: number | null
  written_off: number
  amount_paid: number
}

/** Effective total fees for a row (shared rule; honours custom overrides). */
const rowTotal = (r: MemoFeeRow): number => effectiveTotalFees(r)

/**
 * Returns the four headline figures for the Dashboard:
 *  - totalOutstanding: sum of (total − gross paid) over unpaid, non-written-off memos
 *  - receivedThisMonth: sum of gross allocations whose payment date is in the current month
 *  - memosAwaitingPayment: count of unpaid, non-written-off, non-draft memos
 *  - writtenOffTotal: sum of totals of written-off memos
 */
export function getDashboardSummary(db: Database.Database, now: Date = new Date()): DashboardSummary {
  const rows = prep(
    db,
    `SELECT m.id, m.date, m.financial_year, m.num_appearances, m.fees_per_appearance, m.num_conferences,
            m.fees_per_conference, m.fees_misc_drafting,
            m.custom_fees_appearances, m.custom_fees_conferences, m.custom_fees_misc, m.custom_total_fees,
            m.written_off,
            COALESCE((SELECT SUM(a.amount + a.tds_amount) FROM payment_allocations a WHERE a.memo_id = m.id), 0) AS amount_paid
     FROM memos m
     WHERE m.is_draft = 0`,
  ).all() as MemoFeeRow[]

  const overdueDays = getSettings(db).overdueDays
  // Use the LOCAL calendar date (not UTC) so a late-evening date near a month or
  // financial-year boundary is attributed to the right period.
  const todayLocal = localIso(now)
  const currentFy = deriveFinancialYear(todayLocal)
  const ym = todayLocal.slice(0, 7)

  let totalOutstanding = 0
  let writtenOffTotal = 0
  let memosAwaitingPayment = 0
  let billedThisMonth = 0
  let billedThisYear = 0
  let amountOverdue = 0

  for (const r of rows) {
    const total = rowTotal(r)
    const inThisFy = r.financial_year === currentFy
    const inThisMonth = r.date.slice(0, 7) === ym

    if (inThisFy) {
      billedThisYear = round2(billedThisYear + total)
    }
    if (inThisMonth) billedThisMonth = round2(billedThisMonth + total)

    if (r.written_off === 1) {
      writtenOffTotal = round2(writtenOffTotal + total)
      continue
    }
    const outstanding = round2(total - round2(r.amount_paid))
    if (outstanding > 0) {
      totalOutstanding = round2(totalOutstanding + outstanding)
      memosAwaitingPayment += 1
      if (computeIsOverdue(r.date, 'Unpaid', false, overdueDays, now)) {
        amountOverdue = round2(amountOverdue + outstanding)
      }
    }
  }

  // Received: gross allocations by payment date (this calendar month / this FY).
  const recvMonth = prep(
    db,
    `SELECT COALESCE(SUM(a.amount + a.tds_amount), 0) AS received
     FROM payment_allocations a JOIN payments p ON p.id = a.payment_id
     WHERE substr(p.date_of_payment, 1, 7) = ?`,
  ).get(ym) as { received: number }

  // Received this financial year: sum allocations whose payment date falls in the
  // current FY window (1 Apr – 31 Mar).
  const [fyStartYear] = currentFy.split('-')
  const fyStart = `${fyStartYear}-04-01`
  const fyEnd = `${Number(fyStartYear) + 1}-03-31`
  const recvYear = prep(
    db,
    `SELECT COALESCE(SUM(a.amount + a.tds_amount), 0) AS received
     FROM payment_allocations a JOIN payments p ON p.id = a.payment_id
     WHERE p.date_of_payment >= ? AND p.date_of_payment <= ?`,
  ).get(fyStart, fyEnd) as { received: number }

  return {
    totalOutstanding,
    receivedThisMonth: round2(recvMonth.received),
    memosAwaitingPayment,
    writtenOffTotal,
    billedThisMonth,
    billedThisYear,
    appearancesThisYear: statsAppearances(db, now).year,
    receivedThisYear: round2(recvYear.received),
    amountOverdue,
  }
}

/** Local calendar date as YYYY-MM-DD. */
export function localIso(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/**
 * Appearances for the current month and financial year, taken from the same
 * engine as the Statistics page so the two ALWAYS agree (it includes the manual
 * "extras" entered in Edit Statistics, which the raw memo counts do not).
 */
function statsAppearances(db: Database.Database, now: Date): { month: number; year: number } {
  const fy = deriveFinancialYear(localIso(now))
  const opts = { excludeFutureMonths: true, proRateCurrentMonth: true }
  const months = getPeriodStatistics(db, 'month', fy, opts, now)
  const years = getPeriodStatistics(db, 'financialYear', null, opts, now)
  return {
    month: months.periods.find((p) => p.month === now.getMonth() + 1)?.numAppearances ?? 0,
    year: years.periods.find((p) => p.key === fy)?.numAppearances ?? 0,
  }
}

/**
 * EVERY Overview KPI as an id → number map (see src/lib/dashboardKpis.ts for the
 * catalog). The user chooses which to display. "Last 30 days" is the 30 calendar
 * days ending today (inclusive), by memo date / payment date.
 */
export function getDashboardKpis(db: Database.Database, now: Date = new Date()): Record<string, number> {
  const base = getDashboardSummary(db, now)
  const today = localIso(now)
  const start30 = localIso(new Date(now.getFullYear(), now.getMonth(), now.getDate() - 29))
  const fy = deriveFinancialYear(today)
  const ym = today.slice(0, 7)

  type Row = MemoFeeRow & { num_conferences: number; num_drafts: number; is_draft: number }
  const memos = prep(
    db,
    `SELECT m.id, m.date, m.financial_year, m.num_appearances, m.fees_per_appearance, m.num_conferences,
            m.fees_per_conference, m.fees_misc_drafting, m.num_drafts, m.is_draft,
            m.custom_fees_appearances, m.custom_fees_conferences, m.custom_fees_misc, m.custom_total_fees,
            m.written_off, 0 AS amount_paid
     FROM memos m`,
  ).all() as Row[]

  let memosThisMonth = 0, memosThisYear = 0, memosLast30 = 0
  let conferencesThisMonth = 0, conferencesThisYear = 0, conferencesLast30 = 0
  let appearancesLast30 = 0, billedLast30 = 0
  let draftsThisYear = 0, draftsLast30 = 0
  let draftMemosCount = 0, draftMemosTotal = 0

  for (const r of memos) {
    const total = rowTotal(r)
    if (r.is_draft === 1) {
      draftMemosCount += 1
      draftMemosTotal = round2(draftMemosTotal + total)
      continue
    }
    const inMonth = r.date.slice(0, 7) === ym
    const inYear = r.financial_year === fy
    const inLast30 = r.date >= start30 && r.date <= today
    if (inMonth) { memosThisMonth += 1; conferencesThisMonth += r.num_conferences }
    if (inYear) { memosThisYear += 1; conferencesThisYear += r.num_conferences; draftsThisYear += r.num_drafts }
    if (inLast30) {
      memosLast30 += 1
      conferencesLast30 += r.num_conferences
      appearancesLast30 += r.num_appearances
      draftsLast30 += r.num_drafts
      billedLast30 = round2(billedLast30 + total)
    }
  }

  const recv30 = prep(
    db,
    `SELECT COALESCE(SUM(a.amount + a.tds_amount), 0) AS received
     FROM payment_allocations a JOIN payments p ON p.id = a.payment_id
     WHERE p.date_of_payment >= ? AND p.date_of_payment <= ?`,
  ).get(start30, today) as { received: number }

  const appearances = statsAppearances(db, now)
  return {
    billedThisMonth: base.billedThisMonth,
    billedThisYear: base.billedThisYear,
    billedLast30,
    receivedThisMonth: base.receivedThisMonth,
    receivedThisYear: base.receivedThisYear,
    receivedLast30: round2(recv30.received),
    memosThisMonth, memosThisYear, memosLast30,
    appearancesThisMonth: appearances.month,
    appearancesThisYear: appearances.year,
    appearancesLast30,
    conferencesThisMonth, conferencesThisYear, conferencesLast30,
    draftsThisYear, draftsLast30,
    totalOutstanding: base.totalOutstanding,
    amountOverdue: base.amountOverdue,
    memosAwaitingPayment: base.memosAwaitingPayment,
    writtenOffTotal: base.writtenOffTotal,
    draftMemosCount, draftMemosTotal,
  }
}
