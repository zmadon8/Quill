import { describe, it, expect, beforeEach, beforeAll, afterAll } from 'vitest'
import { deriveFinancialYear, generateMemoNumber } from '@/services/memoNumberService'
import { createSchemaDb, truncateAll } from '../helpers/testDb'
import type DatabaseT from 'better-sqlite3'

// ---------------------------------------------------------------------------
// deriveFinancialYear
// ---------------------------------------------------------------------------
describe('deriveFinancialYear', () => {
  it('returns correct FY for a date in April (start of FY)', () => {
    expect(deriveFinancialYear('2027-04-01')).toBe('2027-28')
  })

  it('returns correct FY for a date mid-year (July)', () => {
    expect(deriveFinancialYear('2026-07-15')).toBe('2026-27')
  })

  it('returns correct FY for a date in December', () => {
    expect(deriveFinancialYear('2026-12-31')).toBe('2026-27')
  })

  it('returns correct FY for a date in January (end-of-FY year)', () => {
    expect(deriveFinancialYear('2027-01-01')).toBe('2026-27')
  })

  it('returns correct FY for a date in February', () => {
    expect(deriveFinancialYear('2027-02-01')).toBe('2026-27')
  })

  it('returns correct FY for 31 March (last day of FY)', () => {
    expect(deriveFinancialYear('2027-03-31')).toBe('2026-27')
  })

  it('returns correct FY for 1 April of the next calendar year', () => {
    expect(deriveFinancialYear('2028-04-01')).toBe('2028-29')
  })

  it('zero-pads correctly when the year boundary crosses a decade (e.g. 2029→2030)', () => {
    // April 2029 → FY 2029-30 (last two digits of 2030 = "30")
    expect(deriveFinancialYear('2029-04-15')).toBe('2029-30')
  })

  it('handles century boundary (e.g. 1999→2000)', () => {
    // April 1999 → FY 1999-00 (last two digits of 2000 = "00")
    expect(deriveFinancialYear('1999-04-01')).toBe('1999-00')
  })
})

// ---------------------------------------------------------------------------
// generateMemoNumber — helpers
// ---------------------------------------------------------------------------

/** Creates a fresh in-memory SQLite DB with the memo_number_sequences table. */

// ---------------------------------------------------------------------------
// generateMemoNumber
// ---------------------------------------------------------------------------
describe('generateMemoNumber', () => {
  let db: DatabaseT.Database

  beforeAll(() => {
    db = createSchemaDb()
  })

  afterAll(() => {
    db.close()
  })

  beforeEach(() => {
    truncateAll(db)
  })

  it('first memo of a new FY gets sequence 1', () => {
    const memo = generateMemoNumber(db, '2026-07-15')
    expect(memo).toBe('2026-27/1')
  })

  it('second memo of the same FY gets sequence 2', () => {
    generateMemoNumber(db, '2026-07-15')
    const memo2 = generateMemoNumber(db, '2026-08-01')
    expect(memo2).toBe('2026-27/2')
  })

  it('counter resets to 1 for a new financial year', () => {
    // Generate two memos in 2026-27
    generateMemoNumber(db, '2026-07-15')
    generateMemoNumber(db, '2026-09-01')

    // First memo in the next financial year
    const memo = generateMemoNumber(db, '2027-04-01')
    expect(memo).toBe('2027-28/1')
  })

  it('sequences are independent across different financial years', () => {
    const fy1a = generateMemoNumber(db, '2026-07-15') // 2026-27/1
    const fy2a = generateMemoNumber(db, '2027-05-01') // 2027-28/1
    const fy1b = generateMemoNumber(db, '2026-11-01') // 2026-27/2
    const fy2b = generateMemoNumber(db, '2027-06-01') // 2027-28/2

    expect(fy1a).toBe('2026-27/1')
    expect(fy2a).toBe('2027-28/1')
    expect(fy1b).toBe('2026-27/2')
    expect(fy2b).toBe('2027-28/2')
  })

  it('all generated numbers across multiple calls are unique', () => {
    const dates = [
      '2026-04-01',
      '2026-07-15',
      '2026-12-31',
      '2027-01-01',
      '2027-03-31',
      '2027-04-01',
      '2027-09-01',
    ]
    const memoNumbers = dates.map((d) => generateMemoNumber(db, d))
    const unique = new Set(memoNumbers)
    expect(unique.size).toBe(memoNumbers.length)
  })

  it('last_seq is never decremented — next number is last_seq + 1', () => {
    const first = generateMemoNumber(db, '2026-07-01')
    const second = generateMemoNumber(db, '2026-08-01')
    const third = generateMemoNumber(db, '2026-09-01')

    // The numbers should be 1, 2, 3 with no gaps
    expect(first).toBe('2026-27/1')
    expect(second).toBe('2026-27/2')
    expect(third).toBe('2026-27/3')

    // Manually simulate a "delete" by checking the sequence is unchanged
    const row = db
      .prepare<[string], { last_seq: number }>(
        'SELECT last_seq FROM memo_number_sequences WHERE financial_year = ?',
      )
      .get('2026-27')!
    // last_seq should be 3 even if a memo were deleted externally
    expect(row.last_seq).toBe(3)

    // The next generated number should be 4, not 3 (no reuse)
    const fourth = generateMemoNumber(db, '2026-10-01')
    expect(fourth).toBe('2026-27/4')
  })

  it('returns the correct format "YYYY-YY/N"', () => {
    const memo = generateMemoNumber(db, '2025-06-15')
    expect(memo).toMatch(/^\d{4}-\d{2}\/\d+$/)
  })

  it('January date correctly maps to the prior-year FY and increments independently', () => {
    // 2027-01-15 belongs to FY 2026-27
    const memo = generateMemoNumber(db, '2027-01-15')
    expect(memo).toBe('2026-27/1')
  })
})
