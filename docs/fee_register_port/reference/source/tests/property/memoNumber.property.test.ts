import { describe, it, beforeEach, beforeAll, afterAll } from 'vitest'
import * as fc from 'fast-check'
import { deriveFinancialYear, generateMemoNumber } from '@/services/memoNumberService'
import type Database from 'better-sqlite3'
import { createSchemaDb, truncateAll } from '../helpers/testDb'

// A single shared in-memory DB is reused across all property iterations.
// Creating thousands of better-sqlite3 instances inside fast-check loops
// can segfault the native worker, so we truncate between iterations instead.
let db: Database.Database
beforeAll(() => { db = createSchemaDb() })
afterAll(() => db.close())

function resetDb(): void {
  truncateAll(db)
}

function dateStr(year: number, month: number): string {
  return `${year}-${String(month).padStart(2, '0')}-15`
}

describe('deriveFinancialYear — property tests', () => {
  it('Property 8a: result always matches YYYY-YY format', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 2000, max: 2050 }),
        fc.integer({ min: 1, max: 12 }),
        (year, month) => {
          const result = deriveFinancialYear(dateStr(year, month))
          return /^\d{4}-\d{2}$/.test(result)
        },
      ),
      { numRuns: 300 },
    )
  })

  it('Property 8b: April–December in year Y → FY starts with Y', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 2000, max: 2050 }),
        fc.integer({ min: 4, max: 12 }),
        (year, month) => {
          const result = deriveFinancialYear(dateStr(year, month))
          return result.startsWith(String(year))
        },
      ),
      { numRuns: 300 },
    )
  })

  it('Property 8c: January–March in year Y → FY starts with Y-1', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 2001, max: 2050 }),
        fc.integer({ min: 1, max: 3 }),
        (year, month) => {
          const result = deriveFinancialYear(dateStr(year, month))
          return result.startsWith(String(year - 1))
        },
      ),
      { numRuns: 300 },
    )
  })
})

describe('generateMemoNumber — property tests', () => {
  beforeEach(() => {
    resetDb()
  })

  it('Property 9: first memo of any new FY ends in /1', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 2000, max: 2050 }),
        fc.integer({ min: 1, max: 12 }),
        (year, month) => {
          resetDb()
          const memo = generateMemoNumber(db, dateStr(year, month))
          return memo.endsWith('/1')
        },
      ),
      { numRuns: 200 },
    )
  })

  it('Property 10: N calls with same date return N distinct values', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 2000, max: 2050 }),
        fc.integer({ min: 4, max: 12 }),
        fc.integer({ min: 1, max: 25 }),
        (year, month, n) => {
          resetDb()
          const results: string[] = []
          for (let i = 0; i < n; i++) {
            results.push(generateMemoNumber(db, dateStr(year, month)))
          }
          return new Set(results).size === n
        },
      ),
      { numRuns: 100 },
    )
  })

  it('Property 11: Nth call returns a number ending in /N (counter never decrements)', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 2000, max: 2050 }),
        fc.integer({ min: 4, max: 12 }),
        fc.integer({ min: 1, max: 25 }),
        (year, month, n) => {
          resetDb()
          let last = ''
          for (let i = 0; i < n; i++) {
            last = generateMemoNumber(db, dateStr(year, month))
          }
          return last.endsWith(`/${n}`)
        },
      ),
      { numRuns: 100 },
    )
  })
})
