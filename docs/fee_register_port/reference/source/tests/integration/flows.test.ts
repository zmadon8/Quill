import { describe, it, expect, beforeEach, beforeAll, afterAll } from 'vitest'
import type Database from 'better-sqlite3'
import { createSchemaDb, truncateAll } from '../helpers/testDb'
import { createFirm, addPartner, listFirms } from '@/services/firmService'
import { createMatter, updateMatter, archiveMatter, unarchiveMatter, isMatterActive } from '@/services/matterService'
import { createMemo, getMemo, listMemos, deleteMemo } from '@/services/memoService'
import { addPaymentToMemo } from '@/services/paymentService'
import { listFeebook } from '@/services/feebookService'
import { generateBackupBuffer, restoreFromBuffer } from '@/services/backupService'
import type { MemoInput } from '@/types/ipc'

let db: Database.Database
beforeAll(() => { db = createSchemaDb() })
afterAll(() => db.close())
beforeEach(() => truncateAll(db))

function setup() {
  const f = createFirm(db, 'Acme Legal')
  const p = addPartner(db, f.id, 'Senior Partner')
  const m = createMatter(db, { name: 'Varian Arbitration', firmId: f.id, partnerId: p.id })
  return { firmId: f.id, partnerId: p.id, matterId: m.id }
}

function memoInput(matterId: number, date: string, over: Partial<MemoInput> = {}): MemoInput {
  return {
    date, matterId, addresseeLine1: 'Acme Legal',
    numAppearances: 2, feesPerAppearance: 5000,
    numConferences: 1, feesPerConference: 3000,
    feesMiscDrafting: 1000, ...over,
  }
}

describe('Integration: memo creation & numbering across the financial-year boundary', () => {
  it('numbers within one FY increment, and reset at the next FY', () => {
    const { matterId } = setup()
    const a = createMemo(db, memoInput(matterId, '2026-05-01')) // FY 2026-27
    const b = createMemo(db, memoInput(matterId, '2026-12-31')) // FY 2026-27
    const c = createMemo(db, memoInput(matterId, '2027-03-31')) // FY 2026-27 (March)
    const d = createMemo(db, memoInput(matterId, '2027-04-01')) // FY 2027-28 (new year)
    expect(a.memoNumber).toBe('2026-27/1')
    expect(b.memoNumber).toBe('2026-27/2')
    expect(c.memoNumber).toBe('2026-27/3')
    expect(d.memoNumber).toBe('2027-28/1')
  })

  it('deleting a memo never reuses its number', () => {
    const { matterId } = setup()
    const a = createMemo(db, memoInput(matterId, '2026-05-01'))
    createMemo(db, memoInput(matterId, '2026-06-01'))
    deleteMemo(db, a.id)
    const next = createMemo(db, memoInput(matterId, '2026-07-01'))
    expect(next.memoNumber).toBe('2026-27/3')
  })
})

describe('Integration: payment recording updates memo status', () => {
  it('partial then full payment flips status to Paid and feeds the Feebook', () => {
    const { matterId } = setup()
    const memo = createMemo(db, memoInput(matterId, '2026-07-15')) // total 14000
    expect(getMemo(db, memo.id).status).toBe('Unpaid')

    addPaymentToMemo(db, memo.id, { amount: 4000, dateOfPayment: '2026-08-01' })
    expect(getMemo(db, memo.id).status).toBe('Unpaid')
    expect(getMemo(db, memo.id).amountPaid).toBe(4000)

    addPaymentToMemo(db, memo.id, { amount: 10000, dateOfPayment: '2026-09-01' })
    const paid = getMemo(db, memo.id)
    expect(paid.status).toBe('Paid')
    expect(paid.dateOfLastPayment).toBe('2026-09-01')

    const feebook = listFeebook(db, {})
    expect(feebook).toHaveLength(2)
    // Two separate payments, each allocated to this one memo -> Single.
    expect(feebook.every((e) => e.paymentType === 'Single')).toBe(true)

    // Memos list reflects aggregate and last payment date.
    const row = listMemos(db, {}).find((m) => m.id === memo.id)!
    expect(row.amountPaid).toBe(14000)
    expect(row.status).toBe('Paid')
  })
})

describe('Integration: matter archive lifecycle blocks memo creation', () => {
  it('archive blocks creation; unarchive restores it', () => {
    const { matterId } = setup()

    archiveMatter(db, matterId)
    expect(isMatterActive(db, matterId)).toBe(false)
    try {
      createMemo(db, memoInput(matterId, '2026-07-15'))
      throw new Error('should have thrown')
    } catch (e) {
      expect((e as { code?: string }).code).toBe('MATTER_ARCHIVED')
    }

    unarchiveMatter(db, matterId)
    const memo = createMemo(db, memoInput(matterId, '2026-07-15'))
    expect(memo.memoNumber).toBe('2026-27/1')
  })

  it('firm status is independent of its matters (stored, not derived)', () => {
    const { matterId } = setup()
    // Firms are active by default on creation.
    expect(listFirms(db, 'all')[0].status).toBe('active')
    // Archiving every matter does NOT change the firm's status anymore.
    archiveMatter(db, matterId)
    expect(listFirms(db, 'all')[0].status).toBe('active')
  })
})

describe('Integration: a saved memo is frozen against later matter edits (Req #2)', () => {
  it('editing matter common fields does not change existing memos', () => {
    const { matterId } = setup()
    // Give the matter some common defaults, then create a memo from it.
    updateMatter(db, matterId, { courtName: 'Original Cause Title', client: 'Original Client' })
    const memo = createMemo(db, {
      ...memoInput(matterId, '2026-07-15'),
      courtName: 'Original Cause Title',
      client: 'Original Client',
    })
    expect(getMemo(db, memo.id).courtName).toBe('Original Cause Title')

    // Change the matter's common fields afterwards.
    updateMatter(db, matterId, { courtName: 'Changed Cause Title', client: 'Changed Client' })

    // The already-created memo must retain its original snapshot.
    const after = getMemo(db, memo.id)
    expect(after.courtName).toBe('Original Cause Title')
    expect(after.client).toBe('Original Client')
  })
})

describe('Integration: backup export → restore round-trip', () => {
  it('restores identical firms, matters, memos, and payments', async () => {
    const { matterId } = setup()
    const m1 = createMemo(db, memoInput(matterId, '2026-07-15'))
    createMemo(db, memoInput(matterId, '2026-08-15'))
    addPaymentToMemo(db, m1.id, { amount: 5000, dateOfPayment: '2026-09-01', payee: 'Client' })

    const before = {
      firms: listFirms(db, 'all').length,
      memos: listMemos(db, {}).map((m) => m.memoNumber).sort(),
      paid: getMemo(db, m1.id).amountPaid,
    }

    const buffer = await generateBackupBuffer(db)
    // Corrupt current state, then restore.
    truncateAll(db)
    expect(listMemos(db, {})).toHaveLength(0)
    const result = await restoreFromBuffer(db, buffer)
    expect(result.rowsImported).toBeGreaterThan(0)

    const after = {
      firms: listFirms(db, 'all').length,
      memos: listMemos(db, {}).map((m) => m.memoNumber).sort(),
      paid: getMemo(db, m1.id).amountPaid,
    }
    expect(after).toEqual(before)

    // Numbering continues without reuse after restore.
    const next = createMemo(db, memoInput(matterId, '2026-10-01'))
    expect(next.memoNumber).toBe('2026-27/3')
  })
})
