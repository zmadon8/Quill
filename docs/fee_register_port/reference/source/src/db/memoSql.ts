/**
 * memoSql.ts — reusable SQL fragments for memo money computations.
 *
 * These centralise the two rules that were previously duplicated (and computed
 * per-row via helper functions, causing N+1 queries) across memoService,
 * outstandingService, statisticsService, dashboardService and paymentService:
 *
 *   1. A memo's EFFECTIVE TOTAL FEES, honouring custom overrides.
 *   2. A memo's paid aggregates from payment_allocations: gross, net, TDS.
 *
 * Expressing them in SQL lets list/stat queries compute totals set-based in a
 * single statement instead of calling a helper once per memo.
 *
 * `m` is assumed to be the alias of the `memos` table in the surrounding query.
 */

/**
 * Effective total fees for memo alias `m`:
 *   custom_total_fees, else the sum of each line's custom override or its
 *   computed value (count × rate for appearances/conferences, raw for misc).
 */
export const MEMO_TOTAL_FEES_SQL = `
  COALESCE(
    m.custom_total_fees,
    COALESCE(m.custom_fees_appearances, m.num_appearances * m.fees_per_appearance)
      + COALESCE(m.custom_fees_conferences, m.num_conferences * m.fees_per_conference)
      + COALESCE(m.custom_fees_misc, m.fees_misc_drafting)
  )
`

/** Gross paid (amount + TDS) for memo alias `m`. */
export const MEMO_PAID_GROSS_SQL = `
  COALESCE((SELECT SUM(a.amount + a.tds_amount) FROM payment_allocations a WHERE a.memo_id = m.id), 0)
`

/** Net received (amount only, excludes TDS) for memo alias `m`. */
export const MEMO_RECEIVED_NET_SQL = `
  COALESCE((SELECT SUM(a.amount) FROM payment_allocations a WHERE a.memo_id = m.id), 0)
`

/** TDS accounted for across a memo's payments, for memo alias `m`. */
export const MEMO_TDS_SQL = `
  COALESCE((SELECT SUM(a.tds_amount) FROM payment_allocations a WHERE a.memo_id = m.id), 0)
`

/**
 * SQL expression giving the financial-year string ("YYYY-YY") for an ISO date
 * column (e.g. "2026-08-25"). The financial year runs 1 April–31 March:
 *   - month >= 4 → "YYYY-(YY+1)"   e.g. 2026-08 → "2026-27"
 *   - month 1–3  → "(YYYY-1)-YY"   e.g. 2027-02 → "2026-27"
 * Pass the fully-qualified date column (e.g. "p.date_of_payment").
 * Mirrors deriveFinancialYear() in memoNumberService.ts.
 */
export function financialYearOfDateSql(dateCol: string): string {
  // startYear = (month >= 4) ? year : year - 1 ; label = startYear-(startYear+1 mod 100, 2-digit)
  const y = `CAST(substr(${dateCol}, 1, 4) AS INTEGER)`
  const mo = `CAST(substr(${dateCol}, 6, 2) AS INTEGER)`
  const startYear = `(CASE WHEN ${mo} >= 4 THEN ${y} ELSE ${y} - 1 END)`
  return `(${startYear} || '-' || substr('0' || ((${startYear} + 1) % 100), -2, 2))`
}

/**
 * Period-key SQL for a payment date, matching the "statistics period" keys:
 *   - FY granularity    → "YYYY-YY"            (financial year of the payment)
 *   - month granularity → "YYYY-YY-MM"         (payment FY + calendar month)
 * Used to attribute RECEIVED amounts to the period the money came in (receipt
 * basis), as opposed to the memo's billing period.
 */
export function paymentPeriodKeySql(dateCol: string, granularity: 'month' | 'financialYear'): string {
  const fy = financialYearOfDateSql(dateCol)
  if (granularity === 'financialYear') return fy
  return `(${fy} || '-' || substr(${dateCol}, 6, 2))`
}
