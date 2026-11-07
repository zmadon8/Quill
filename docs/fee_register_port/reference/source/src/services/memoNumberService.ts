import type Database from 'better-sqlite3'

/**
 * Derives the financial year string from an ISO 8601 date string.
 *
 * The financial year runs from 1 April (month 4) to 31 March of the following year.
 *   - April–December of year Y  →  "Y-(Y+1 last two digits)"  e.g. "2026-27"
 *   - January–March of year Y   →  "(Y-1)-(Y last two digits)" e.g. "2026-27"
 *
 * @param date - ISO 8601 date string, e.g. "2026-07-15"
 * @returns Financial year string in "YYYY-YY" format, e.g. "2026-27"
 *
 * Examples:
 *   deriveFinancialYear("2026-07-15") → "2026-27"
 *   deriveFinancialYear("2027-02-01") → "2026-27"
 *   deriveFinancialYear("2027-04-01") → "2027-28"
 */
export function deriveFinancialYear(date: string): string {
  const [yearStr, monthStr] = date.split('-')
  const year = parseInt(yearStr, 10)
  const month = parseInt(monthStr, 10)

  if (month >= 4) {
    // April onwards: financial year starts in this calendar year
    const nextYear = year + 1
    return `${year}-${String(nextYear).slice(-2)}`
  } else {
    // January–March: financial year started in the previous calendar year
    const prevYear = year - 1
    return `${prevYear}-${String(year).slice(-2)}`
  }
}

/**
 * Atomically generates the next memo number for the given date's financial year.
 *
 * Uses an EXCLUSIVE TRANSACTION to read and increment the `memo_number_sequences`
 * counter, ensuring no two concurrent calls can produce the same sequence number.
 *
 * - If no row exists for the derived financial year, one is inserted with last_seq = 0,
 *   then incremented to 1.
 * - The counter is monotonically increasing and is never decremented on delete,
 *   so deleted memo numbers are never reused.
 *
 * @param db   - A better-sqlite3 Database instance
 * @param date - ISO 8601 date string used to derive the financial year
 * @returns Memo number string in "YYYY-YY/N" format, e.g. "2026-27/1"
 */
/**
 * Computes the memo number that WOULD be assigned next for the given date,
 * WITHOUT incrementing the sequence. Read-only; safe to call for previews.
 *
 * @param db   - A better-sqlite3 Database instance
 * @param date - ISO 8601 date string used to derive the financial year
 * @returns The prospective memo number in "YYYY-YY/N" format.
 */
export function previewMemoNumber(db: Database.Database, date: string): string {
  const financialYear = deriveFinancialYear(date)
  const row = db
    .prepare('SELECT last_seq FROM memo_number_sequences WHERE financial_year = ?')
    .get(financialYear) as { last_seq: number } | undefined
  const next = (row?.last_seq ?? 0) + 1
  return `${financialYear}/${next}`
}

export function generateMemoNumber(db: Database.Database, date: string): string {
  const financialYear = deriveFinancialYear(date)

  const selectStmt = db.prepare<[string], { last_seq: number }>(
    'SELECT last_seq FROM memo_number_sequences WHERE financial_year = ?',
  )
  const insertStmt = db.prepare(
    'INSERT INTO memo_number_sequences (financial_year, last_seq) VALUES (?, 0)',
  )
  const incrementStmt = db.prepare(
    'UPDATE memo_number_sequences SET last_seq = last_seq + 1 WHERE financial_year = ?',
  )

  const generate = db.transaction((fy: string): number => {
    // Try to fetch the existing sequence row
    const row = selectStmt.get(fy)

    if (row === undefined) {
      // First memo for this financial year — insert a seed row with last_seq = 0
      insertStmt.run(fy)
    }

    // Increment the counter
    incrementStmt.run(fy)

    // Read back the new value
    const updated = selectStmt.get(fy)!
    return updated.last_seq
  })

  // Run as an EXCLUSIVE transaction to prevent duplicate sequence numbers
  // from concurrent access (better-sqlite3 Transaction.exclusive())
  const newSeq = generate.exclusive(financialYear)

  return `${financialYear}/${newSeq}`
}
