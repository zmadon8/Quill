import { describe, it, expect, beforeEach, beforeAll, afterAll } from 'vitest'
import type Database from 'better-sqlite3'
import { createSchemaDb, truncateAll } from '../helpers/testDb'
import { createFirm, addPartner } from '@/services/firmService'
import { createMatter, archiveMatter } from '@/services/matterService'
import {
  createMemo,
  getMemo,
  updateMemo,
  deleteMemo,
  listMemos,
  createBasedOn,
  findMemoIdByNumber,
} from '@/services/memoService'
import { addPaymentToMemo } from '@/services/paymentService'
import type { MemoInput } from '@/types/ipc'

let db: Database.Database
beforeAll(() => { db = createSchemaDb() })
afterAll(() => db.close())
beforeEach(() => truncateAll(db))

function expectCode(fn: () => unknown, code: string): void {
  try { fn() } catch (err) { expect((err as { code?: string }).code).toBe(code); return }
  throw new Error(`Expected AppError with code ${code}`)
}

function seedMatter(archived = false) {
  const f = createFirm(db, 'Firm')
  const p = addPartner(db, f.id, 'Partner')
  const m = createMatter(db, { name: 'Matter', firmId: f.id, partnerId: p.id })
  if (archived) archiveMatter(db, m.id)
  return { firmId: f.id, partnerId: p.id, matterId: m.id }
}

function baseInput(matterId: number, over: Partial<MemoInput> = {}): MemoInput {
  return {
    date: '2026-07-15',
    matterId,
    addresseeLine1: 'Acme Legal',
    numAppearances: 2,
    feesPerAppearance: 5000,
    numConferences: 1,
    feesPerConference: 3000,
    feesMiscDrafting: 1000,
    ...over,
  }
}

describe('memoService — create & compute', () => {
  it('creates a memo with generated number and computed fields', () => {
    const { matterId } = seedMatter()
    const memo = createMemo(db, baseInput(matterId))
    expect(memo.memoNumber).toBe('2026-27/1')
    expect(memo.feesAppearances).toBe(10000) // 2 * 5000
    expect(memo.feesConferences).toBe(3000)  // 1 * 3000
    expect(memo.totalFees).toBe(14000)       // 10000 + 3000 + 1000
    expect(memo.netOfTds).toBe(12600)        // 14000 - (14000 * 10% default rate)
    expect(memo.totalFeesInWords).toMatch(/^Rupees .* Only$/)
    expect(memo.status).toBe('Unpaid')
    expect(memo.amountPaid).toBe(0)
  })

  it('rejects creation for an archived matter', () => {
    const { matterId } = seedMatter(true)
    expectCode(() => createMemo(db, baseInput(matterId)), 'MATTER_ARCHIVED')
  })

  it('rejects a missing date', () => {
    const { matterId } = seedMatter()
    expectCode(() => createMemo(db, baseInput(matterId, { date: '' })), 'INVALID_MEMO')
  })

  it('status is Paid when payments cover total fees', () => {
    const { matterId } = seedMatter()
    const memo = createMemo(db, baseInput(matterId))
    addPaymentToMemo(db, memo.id, { amount: 14000, dateOfPayment: '2026-08-01' })
    const after = getMemo(db, memo.id)
    expect(after.amountPaid).toBe(14000)
    expect(after.status).toBe('Paid')
    expect(after.dateOfLastPayment).toBe('2026-08-01')
  })
})

describe('memoService — custom memo number (per-memo)', () => {
  it('uses the auto sequence when no custom number is given', () => {
    const { matterId } = seedMatter()
    const memo = createMemo(db, baseInput(matterId))
    expect(memo.memoNumber).toBe('2026-27/1')
    expect(getMemo(db, memo.id).isCustomNumber).toBe(false)
  })

  it('uses a user-typed custom number verbatim when provided', () => {
    const { matterId } = seedMatter()
    const memo = createMemo(db, baseInput(matterId, { customMemoNumber: 'ABC-2025/7' }))
    expect(memo.memoNumber).toBe('ABC-2025/7')
    const detail = getMemo(db, memo.id)
    expect(detail.isCustomNumber).toBe(true)
    expect(detail.customMemoNumber).toBe('ABC-2025/7')
  })

  it('custom and auto-numbered memos coexist in the same matter', () => {
    const { matterId } = seedMatter()
    const auto = createMemo(db, baseInput(matterId))
    const custom = createMemo(db, baseInput(matterId, { date: '2026-08-01', customMemoNumber: 'X/1' }))
    const auto2 = createMemo(db, baseInput(matterId, { date: '2026-09-01' }))
    expect(auto.memoNumber).toBe('2026-27/1')
    expect(custom.memoNumber).toBe('X/1')
    // The auto sequence is unaffected by the custom memo in between.
    expect(auto2.memoNumber).toBe('2026-27/2')
  })

  it('rejects a blank or duplicate custom number', () => {
    const { matterId } = seedMatter()
    createMemo(db, baseInput(matterId, { customMemoNumber: 'DUP/1' }))
    expectCode(() => createMemo(db, baseInput(matterId, { date: '2026-08-01', customMemoNumber: 'DUP/1' })), 'INVALID_MEMO')
  })
})

describe('memoService — update & delete', () => {
  it('update recomputes totals', () => {
    const { matterId } = seedMatter()
    const memo = createMemo(db, baseInput(matterId))
    const updated = updateMemo(db, memo.id, baseInput(matterId, { numAppearances: 4 }))
    expect(updated.feesAppearances).toBe(20000)
    expect(updated.totalFees).toBe(24000)
  })

  it('update persists an edited date (finalised memo keeps its number & FY)', () => {
    const { matterId } = seedMatter()
    const memo = createMemo(db, baseInput(matterId)) // date 2026-07-15 → 2026-27/1
    const updated = updateMemo(db, memo.id, baseInput(matterId, { date: '2026-08-20' }))
    expect(updated.date).toBe('2026-08-20')
    // Reload from the DB to prove it was persisted, not just echoed back.
    const reloaded = getMemo(db, memo.id)
    expect(reloaded.date).toBe('2026-08-20')
    // The issued number and its FY are stable even if the date moves within/across FY.
    expect(reloaded.memoNumber).toBe('2026-27/1')
    expect(reloaded.financialYear).toBe('2026-27')
  })

  it('editing a draft date re-derives its financial year', () => {
    const { matterId } = seedMatter()
    // Draft: no custom number and saved as draft via createMemo(isDraft=true).
    const draft = createMemo(db, baseInput(matterId, { date: '2026-07-15' }), true)
    expect(draft.financialYear).toBe('2026-27')
    const updated = updateMemo(db, draft.id, baseInput(matterId, { date: '2026-03-31' }))
    const reloaded = getMemo(db, updated.id)
    expect(reloaded.date).toBe('2026-03-31')
    // March 2026 falls in FY 2025-26 for a draft (number not yet issued).
    expect(reloaded.financialYear).toBe('2025-26')
  })

  it('delete does not reuse the memo number', () => {
    const { matterId } = seedMatter()
    const first = createMemo(db, baseInput(matterId))
    expect(first.memoNumber).toBe('2026-27/1')
    deleteMemo(db, first.id)
    const second = createMemo(db, baseInput(matterId))
    expect(second.memoNumber).toBe('2026-27/2') // not reused
  })
})

describe('memoService — list & filters', () => {
  it('lists memos newest first and filters unpaid', () => {
    const { matterId } = seedMatter()
    const a = createMemo(db, baseInput(matterId))
    const b = createMemo(db, baseInput(matterId, { date: '2026-09-01' }))
    addPaymentToMemo(db, b.id, { amount: 14000, dateOfPayment: '2026-10-01' })
    const all = listMemos(db, {})
    expect(all.map((m) => m.memoNumber)).toEqual(['2026-27/2', '2026-27/1'])
    const unpaid = listMemos(db, { unpaidOnly: true })
    expect(unpaid.map((m) => m.id)).toEqual([a.id])
  })

  it('amountReceived excludes TDS while amountPaid (gross) drives Paid status', () => {
    const { matterId } = seedMatter()
    const memo = createMemo(db, baseInput(matterId)) // total 14000
    // Net 12600 received + 1400 TDS = 14000 gross → fully settles the memo.
    addPaymentToMemo(db, memo.id, {
      amount: 12600,
      autoTds: false,
      tdsAmount: 1400,
      dateOfPayment: '2026-08-01',
    })
    const [row] = listMemos(db, {})
    expect(row.amountPaid).toBe(14000) // gross
    expect(row.amountReceived).toBe(12600) // net, excludes TDS
    expect(row.amountTds).toBe(1400) // TDS accounted for
    expect(row.amountDue).toBe(0) // total - gross = 0
    expect(row.status).toBe('Paid') // gross covers the total
  })

  it('amountDue is Total minus gross payments and can be positive', () => {
    const { matterId } = seedMatter()
    const memo = createMemo(db, baseInput(matterId)) // total 14000
    addPaymentToMemo(db, memo.id, { amount: 4000, dateOfPayment: '2026-08-01' })
    const [row] = listMemos(db, {})
    expect(row.amountDue).toBe(10000) // 14000 - 4000 gross
    expect(row.amountTds).toBe(0)
    expect(row.status).toBe('Unpaid')
  })

  it('findMemoIdByNumber resolves a finalised memo number', () => {
    const { matterId } = seedMatter()
    const memo = createMemo(db, baseInput(matterId))
    expect(findMemoIdByNumber(db, memo.memoNumber!)).toBe(memo.id)
    expect(findMemoIdByNumber(db, 'nope/999')).toBeNull()
  })
})

describe('memoService — createBasedOn', () => {
  it('copies non-payment fields, blanks date, carries no id/number', () => {
    const { matterId } = seedMatter()
    const src = createMemo(db, baseInput(matterId, { client: 'Mr X', plaintiffName: 'P' }))
    const form = createBasedOn(db, src.id)
    expect(form.sourceMemoId).toBe(src.id)
    expect(form.date).toBe('')
    expect(form.client).toBe('Mr X')
    expect(form.plaintiffName).toBe('P')
    expect(form.feesPerAppearance).toBe(5000)
    expect('id' in form).toBe(false)
    expect('memoNumber' in form).toBe(false)
  })
})

describe('memoService — drafts, custom amounts, write-off guard', () => {
  it('saves a draft without a number and excludes it from the main list', () => {
    const { matterId } = seedMatter()
    const draft = createMemo(db, baseInput(matterId), true)
    expect(draft.isDraft).toBe(true)
    expect(draft.memoNumber).toBeNull()
    // Not in the main Memos list, but present in drafts.
    expect(listMemos(db, {}).length).toBe(0)
  })

  it('drafts do not consume memo numbers; finalising assigns the next number', async () => {
    const { createMemo: _c } = await import('@/services/memoService')
    void _c
    const { matterId } = seedMatter()
    const draft = createMemo(db, baseInput(matterId), true)
    const numbered = createMemo(db, baseInput(matterId, { date: '2026-08-01' }))
    expect(numbered.memoNumber).toBe('2026-27/1') // draft did not take /1
    const mod = await import('@/services/memoService')
    const finalised = mod.finalizeDraft(db, draft.id)
    expect(finalised.isDraft).toBe(false)
    expect(finalised.memoNumber).toBe('2026-27/2')
  })

  it('honours custom amounts over auto-calculation', () => {
    const { matterId } = seedMatter()
    const memo = createMemo(db, baseInput(matterId, { customTotalFees: 99999 }))
    expect(getMemo(db, memo.id).totalFees).toBe(99999)
  })

  it('refuses to write off a fully paid memo (Req #1)', async () => {
    const mod = await import('@/services/memoService')
    const { matterId } = seedMatter()
    const memo = createMemo(db, baseInput(matterId))
    addPaymentToMemo(db, memo.id, { amount: 14000, dateOfPayment: '2026-08-01' })
    expectCode(() => mod.setMemoWrittenOff(db, memo.id, true), 'INVALID_MEMO')
  })

  it('allows writing off an unpaid memo without touching payments', async () => {
    const mod = await import('@/services/memoService')
    const { matterId } = seedMatter()
    const memo = createMemo(db, baseInput(matterId))
    addPaymentToMemo(db, memo.id, { amount: 1000, dateOfPayment: '2026-08-01' }) // partial
    const off = mod.setMemoWrittenOff(db, memo.id, true)
    expect(off.writtenOff).toBe(true)
    expect(off.amountPaid).toBe(1000) // payment preserved
  })
})
