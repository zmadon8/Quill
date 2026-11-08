import { describe, it, expect, beforeEach, beforeAll, afterAll } from 'vitest'
import type Database from 'better-sqlite3'
import { createSchemaDb, truncateAll } from '../helpers/testDb'
import {
  getSettings,
  updateSettings,
  listBankAccounts,
  addBankAccount,
  updateBankAccount,
  deleteBankAccount,
} from '@/services/settingsService'

let db: Database.Database
beforeAll(() => { db = createSchemaDb() })
afterAll(() => db.close())
beforeEach(() => {
  truncateAll(db)
  // settings row is seeded by createSchemaDb; truncateAll does not clear it
})

function expectCode(fn: () => unknown, code: string): void {
  try { fn() } catch (err) { expect((err as { code?: string }).code).toBe(code); return }
  throw new Error(`Expected AppError with code ${code}`)
}

describe('settingsService — defaults', () => {
  it('returns seeded defaults (TDS 10)', () => {
    expect(getSettings(db).defaultTdsRate).toBe(10)
  })

  it('updates defaults', () => {
    const s = updateSettings(db, { defaultFeesPerAppearance: 5000, defaultTdsRate: 12 })
    expect(s.defaultFeesPerAppearance).toBe(5000)
    expect(s.defaultTdsRate).toBe(12)
  })

  it('rejects a TDS rate outside 0..100', () => {
    expectCode(() => updateSettings(db, { defaultTdsRate: 150 }), 'UNKNOWN')
  })

  it('defaults the Initial Financial Year to 2026-27 and persists a valid value', () => {
    expect(getSettings(db).initialFinancialYear).toBe('2026-27')
    const s = updateSettings(db, { initialFinancialYear: '2027-28' })
    expect(s.initialFinancialYear).toBe('2027-28')
    expect(getSettings(db).initialFinancialYear).toBe('2027-28')
  })

  it('rejects a malformed Initial Financial Year', () => {
    expectCode(() => updateSettings(db, { initialFinancialYear: '2026' }), 'UNKNOWN')
    expectCode(() => updateSettings(db, { initialFinancialYear: '2026-28' }), 'UNKNOWN')
  })
})

describe('settingsService — bank accounts', () => {
  it('adds, lists (sorted), updates, deletes', () => {
    addBankAccount(db, 'HDFC')
    addBankAccount(db, 'axis')
    expect(listBankAccounts(db).map((b) => b.name)).toEqual(['axis', 'HDFC'])
    const b = addBankAccount(db, 'ICICI')
    updateBankAccount(db, b.id, 'ICICI Bank')
    expect(listBankAccounts(db).some((x) => x.name === 'ICICI Bank')).toBe(true)
    deleteBankAccount(db, b.id)
    expect(listBankAccounts(db).map((x) => x.name)).toEqual(['axis', 'HDFC'])
  })

  it('rejects duplicate bank account (case-insensitive)', () => {
    addBankAccount(db, 'SBI')
    expectCode(() => addBankAccount(db, 'sbi'), 'UNKNOWN')
  })

  it('defaults the payment amount prefill to "zero", persists valid choices and rejects others', () => {
    expect(getSettings(db).defaultPaymentAmount).toBe('zero')
    expect(updateSettings(db, { defaultPaymentAmount: 'netOfTds' }).defaultPaymentAmount).toBe('netOfTds')
    expect(getSettings(db).defaultPaymentAmount).toBe('netOfTds')
    expect(updateSettings(db, { defaultPaymentAmount: 'full' }).defaultPaymentAmount).toBe('full')
    expectCode(() => updateSettings(db, { defaultPaymentAmount: 'half' as never }), 'UNKNOWN')
  })

  it('defaults new-memo line ticks to ON and persists turning them off', () => {
    expect(getSettings(db).defaultLinesEnabled).toBe(true)
    expect(updateSettings(db, { defaultLinesEnabled: false }).defaultLinesEnabled).toBe(false)
    expect(getSettings(db).defaultLinesEnabled).toBe(false)
    expect(updateSettings(db, { defaultLinesEnabled: true }).defaultLinesEnabled).toBe(true)
  })
})
