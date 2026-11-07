/**
 * Renderer-side financial-year helpers (1 April – 31 March), matching the
 * format produced by the main-process memoNumberService.
 */

/** The financial year ("YYYY-YY") containing `now`. */
export function currentFinancialYear(now: Date = new Date()): string {
  const year = now.getFullYear()
  const month = now.getMonth() + 1 // 1-12
  if (month >= 4) {
    return `${year}-${String(year + 1).slice(-2)}`
  }
  return `${year - 1}-${String(year).slice(-2)}`
}

/**
 * A descending list of recent financial years for FY filter dropdowns, newest
 * first. When `minFinancialYear` is given, years earlier than it are omitted so
 * the dropdown never offers data before the configured Initial FY.
 *
 * e.g. recentFinancialYears(8, '2026-27') in FY 2027-28 → ['2027-28', '2026-27'].
 */
export function recentFinancialYears(count = 8, minFinancialYear?: string): string[] {
  const startYear = Number(currentFinancialYear().slice(0, 4))
  const years = Array.from({ length: count }, (_, i) => {
    const y = startYear - i
    return `${y}-${String(y + 1).slice(-2)}`
  })
  if (!minFinancialYear) return years
  const minStart = Number(minFinancialYear.slice(0, 4))
  return years.filter((y) => Number(y.slice(0, 4)) >= minStart)
}
