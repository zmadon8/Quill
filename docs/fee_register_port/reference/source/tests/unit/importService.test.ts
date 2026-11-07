import { describe, it, expect, beforeEach, beforeAll, afterAll } from 'vitest'
import type Database from 'better-sqlite3'
import { createSchemaDb, truncateAll } from '../helpers/testDb'
import { importMemos } from '@/services/importService'
import { listMemos, getMemo } from '@/services/memoService'
import { listFirms } from '@/services/firmService'
import { listFeebook } from '@/services/feebookService'
import { updateSettings } from '@/services/settingsService'
import type { ImportMapping } from '@/types/ipc'

let db: Database.Database
beforeAll(() => {
  db = createSchemaDb()
})
afterAll(() => db.close())
beforeEach(() => {
  truncateAll(db)
  // Feebook now enforces the Initial-FY cutoff (default 2026-27). These tests
  // import historical FY 2025-26 payments and read them back via listFeebook,
  // so set an early Initial FY to keep them visible.
  updateSettings(db, { initialFinancialYear: '2019-20', feebookStartYear: '2019-20' })
})

const mapping: ImportMapping = {
  firmName: 'Firm',
  matterName: 'Matter',
  memoNumber: 'No',
  date: 'Date',
  totalFees: 'Total',
  amountPaid: 'Paid',
}

describe('importService.importMemos', () => {
  it('creates firms, matters, numbered memos and payments from rows', () => {
    const rows = [
      { Firm: 'Acme Co', Matter: 'Acme v Beta', No: '2025-26/1', Date: '10/06/2025', Total: '1,20,000', Paid: '20000' },
      { Firm: 'Acme Co', Matter: 'Acme v Beta', No: '2025-26/2', Date: '2025-07-01', Total: '80000', Paid: '0' },
      { Firm: 'Delta LLP', Matter: 'Delta Estate', No: '2025-26/5', Date: '15/08/2025', Total: '50000', Paid: '50000' },
    ]
    const res = importMemos(db, rows, mapping)

    expect(res.memosCreated).toBe(3)
    expect(res.firmsCreated).toBe(2)
    expect(res.mattersCreated).toBe(2)
    expect(res.paymentsCreated).toBe(2) // two rows had paid > 0

    const memos = listMemos(db, {})
    expect(memos).toHaveLength(3)
    // Custom numbers preserved verbatim.
    const numbers = memos.map((m) => m.memoNumber).sort()
    expect(numbers).toEqual(['2025-26/1', '2025-26/2', '2025-26/5'])
    // Comma-formatted total parsed.
    const acme1 = memos.find((m) => m.memoNumber === '2025-26/1')!
    expect(acme1.totalFees).toBe(120000)
    // Fully-paid memo shows as Paid.
    const delta = memos.find((m) => m.memoNumber === '2025-26/5')!
    expect(delta.status).toBe('Paid')
    // Imported numbered memos carry their number as a per-memo custom number
    // (the matter itself is NOT flagged custom any more).
    expect(getMemo(db, acme1.id).isCustomNumber).toBe(true)
  })

  it('reuses an existing firm/matter across rows (find-or-create)', () => {
    const rows = [
      { Firm: 'Acme Co', Matter: 'Case A', No: '1', Date: '2025-06-10', Total: '1000', Paid: '0' },
      { Firm: 'acme co', Matter: 'case a', No: '2', Date: '2025-06-11', Total: '2000', Paid: '0' },
    ]
    const res = importMemos(db, rows, mapping)
    expect(res.firmsCreated).toBe(1)
    expect(res.mattersCreated).toBe(1)
    expect(listFirms(db, 'all')).toHaveLength(1)
  })

  it('imports rows without a memo number as drafts', () => {
    const rows = [{ Firm: 'F', Matter: 'M', No: '', Date: '2025-06-10', Total: '1000', Paid: '0' }]
    importMemos(db, rows, mapping)
    const finalised = listMemos(db, {})
    expect(finalised).toHaveLength(0) // drafts are excluded from the main list
  })

  it('throws if firm/matter columns are not mapped', () => {
    expect(() => importMemos(db, [], { firmName: 'Firm' })).toThrow()
  })

  it('auto-numbers memos (in row order) when the memo-number column is unmapped and autoNumber is on', () => {
    // No "No" column mapped; rows carry dates in two financial years.
    const rows = [
      { Firm: 'F', Matter: 'M', Date: '2025-06-10', Total: '1000' },
      { Firm: 'F', Matter: 'M', Date: '2025-06-10', Total: '1000' }, // same day
      { Firm: 'F', Matter: 'M', Date: '2025-08-01', Total: '1000' },
      { Firm: 'F', Matter: 'M', Date: '2026-05-01', Total: '1000' }, // next FY
    ]
    const noNumberMapping: ImportMapping = {
      firmName: 'Firm', matterName: 'Matter', date: 'Date', totalFees: 'Total',
    }
    const res = importMemos(db, rows, noNumberMapping, { autoNumber: true })
    expect(res.memosCreated).toBe(4)
    const numbers = listMemos(db, {}).map((m) => m.memoNumber).sort()
    // 2025-26 gets 1,2,3 in row order (incl. same-day); 2026-27 gets 1.
    expect(numbers).toEqual(['2025-26/1', '2025-26/2', '2025-26/3', '2026-27/1'])
    // None are custom-numbered.
    const details = listMemos(db, {}).map((m) => getMemo(db, m.id))
    expect(details.every((d) => d.isCustomNumber === false)).toBe(true)
  })

  it('without autoNumber, an unmapped memo number still imports as a draft', () => {
    const rows = [{ Firm: 'F', Matter: 'M', Date: '2025-06-10', Total: '1000' }]
    const noNumberMapping: ImportMapping = {
      firmName: 'Firm', matterName: 'Matter', date: 'Date', totalFees: 'Total',
    }
    importMemos(db, rows, noNumberMapping) // autoNumber omitted → false
    expect(listMemos(db, {})).toHaveLength(0) // draft, excluded from main list
  })

  it('imports the number of drafts when mapped', () => {
    const rows = [
      { Firm: 'F', Matter: 'M', No: '2025-26/9', Date: '2025-06-10', Total: '1000', Paid: '0', Drafts: '3' },
    ]
    importMemos(db, rows, { ...mapping, numDrafts: 'Drafts' })
    const memos = listMemos(db, {})
    expect(memos).toHaveLength(1)
    expect(getMemo(db, memos[0].id).numDrafts).toBe(3)
  })

  it('creates an unaccounted payment for a row with no firm/matter/memo but a paid amount', () => {
    const rows = [
      // A normal memo row.
      { Firm: 'F', Matter: 'M', No: '2025-26/1', Date: '2025-06-10', Total: '1000', Paid: '0', Drafts: '0' },
      // An unaccounted payment row: blank firm/matter/memo, positive paid.
      { Firm: '', Matter: '', No: '', Date: '2025-06-15', Total: '', Paid: '5000', Drafts: '' },
    ]
    const res = importMemos(db, rows, {
      ...mapping,
      numDrafts: 'Drafts',
      paymentDate: 'Date',
      payee: 'Payee',
    })
    expect(res.memosCreated).toBe(1)
    expect(res.paymentsCreated).toBe(1) // the unaccounted payment
    // The unaccounted payment has no memo allocation.
    const paid = (db.prepare('SELECT COUNT(*) AS n FROM payments').get() as { n: number }).n
    const allocs = (db.prepare('SELECT COUNT(*) AS n FROM payment_allocations').get() as { n: number }).n
    expect(paid).toBe(1)
    expect(allocs).toBe(0)
  })

  it('merges rows sharing a Payment Group into one payment split across memos', () => {
    const rows = [
      // Three memos paid together by one payment (group "G1").
      { Firm: 'F', Matter: 'M', No: '2025-26/56', Date: '2025-07-01', Total: '20000', Paid: '18000', Tds: '2000', PayDate: '2025-11-27', Grp: 'G1' },
      { Firm: 'F', Matter: 'M', No: '2025-26/83', Date: '2025-08-01', Total: '30000', Paid: '27000', Tds: '3000', PayDate: '2025-11-27', Grp: 'G1' },
      { Firm: 'F', Matter: 'M', No: '2025-26/98', Date: '2025-09-01', Total: '25000', Paid: '22500', Tds: '2500', PayDate: '2025-11-27', Grp: 'G1' },
      // A standalone single-memo payment (no group).
      { Firm: 'F', Matter: 'M', No: '2025-26/120', Date: '2025-10-01', Total: '10000', Paid: '9000', Tds: '1000', PayDate: '2025-12-05', Grp: '' },
    ]
    const grpMapping: ImportMapping = {
      ...mapping,
      paymentTds: 'Tds',
      paymentDate: 'PayDate',
      paymentGroup: 'Grp',
    }
    const res = importMemos(db, rows, grpMapping)
    expect(res.memosCreated).toBe(4)
    // One split payment (G1) + one single payment = 2 payments, 4 allocations.
    expect(res.paymentsCreated).toBe(2)
    const payCount = (db.prepare('SELECT COUNT(*) AS n FROM payments').get() as { n: number }).n
    const allocCount = (db.prepare('SELECT COUNT(*) AS n FROM payment_allocations').get() as { n: number }).n
    expect(payCount).toBe(2)
    expect(allocCount).toBe(4)

    // The three grouped memos show as "Multiple (3)" in the Feebook, paid together.
    const fb = listFeebook(db, {})
    const g56 = fb.find((e) => e.memoNumber === '2025-26/56')!
    expect(g56.paymentType).toBe('Multiple')
    expect(g56.allocationCount).toBe(3)
    expect(g56.groupMemoNumbers.sort()).toEqual(['2025-26/56', '2025-26/83', '2025-26/98'])
    // The standalone one is Single.
    const single = fb.find((e) => e.memoNumber === '2025-26/120')!
    expect(single.paymentType).toBe('Single')
  })
})
