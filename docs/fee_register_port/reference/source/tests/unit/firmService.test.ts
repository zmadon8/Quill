import { describe, it, expect, beforeEach, beforeAll, afterAll } from 'vitest'
import type Database from 'better-sqlite3'
import { createSchemaDb, truncateAll } from '../helpers/testDb'
import {
  createFirm,
  listFirms,
  getFirm,
  updateFirm,
  setFirmStatus,
  addPartner,
  updatePartner,
  removePartner,
} from '@/services/firmService'
import { createMatter } from '@/services/matterService'
import { createMemo, setMemoWrittenOff } from '@/services/memoService'
import { addPaymentToMemo } from '@/services/paymentService'

let db: Database.Database
beforeAll(() => { db = createSchemaDb() })
afterAll(() => db.close())
beforeEach(() => truncateAll(db))

/** Asserts that calling fn throws an AppError with the given code. */
function expectCode(fn: () => unknown, code: string): void {
  try {
    fn()
  } catch (err) {
    expect((err as { code?: string }).code).toBe(code)
    return
  }
  throw new Error(`Expected function to throw AppError with code ${code}`)
}

function seedPartnerAndMatter(d: Database.Database, firmId: number, matterName: string, archived = false) {
  const p = addPartner(d, firmId, 'Partner A')
  d.prepare(
    'INSERT INTO matters (firm_id, partner_id, name, is_archived) VALUES (?, ?, ?, ?)',
  ).run(firmId, p.id, matterName, archived ? 1 : 0)
  return p
}

describe('firmService — create', () => {
  it('creates a firm with a valid name', () => {
    const f = createFirm(db, 'Acme Legal')
    expect(f.name).toBe('Acme Legal')
    expect(f.id).toBeGreaterThan(0)
    expect(f.status).toBe('active') // active by default on creation
  })

  it('rejects a duplicate name (case-insensitive)', () => {
    createFirm(db, 'Acme Legal')
    expectCode(() => createFirm(db, 'ACME LEGAL'), 'DUPLICATE_FIRM_NAME')
  })

  it('rejects an empty name', () => {
    expectCode(() => createFirm(db, '   '), 'INVALID_FIRM_NAME')
  })

  it('rejects a name longer than 200 chars', () => {
    expectCode(() => createFirm(db, 'x'.repeat(201)), 'INVALID_FIRM_NAME')
  })
})

describe('firmService — stored status (manual, not derived from matters)', () => {
  it('is active by default with zero matters', () => {
    createFirm(db, 'Empty Firm')
    expect(listFirms(db, 'all')[0].status).toBe('active')
  })

  it('stays active regardless of matter archive state', () => {
    const f = createFirm(db, 'Firm With Archived Matter')
    seedPartnerAndMatter(db, f.id, 'Matter 1', true)
    expect(listFirms(db, 'all')[0].status).toBe('active')
  })

  it('setFirmStatus archives and unarchives a firm manually', () => {
    const f = createFirm(db, 'Toggle Firm')
    expect(listFirms(db, 'all')[0].status).toBe('active')

    const archived = setFirmStatus(db, f.id, 'archived')
    expect(archived.status).toBe('archived')
    expect(listFirms(db, 'all')[0].status).toBe('archived')
    expect(getFirm(db, f.id).status).toBe('archived')

    const active = setFirmStatus(db, f.id, 'active')
    expect(active.status).toBe('active')
    expect(listFirms(db, 'all')[0].status).toBe('active')
  })

  it('setFirmStatus throws FIRM_NOT_FOUND for an unknown id', () => {
    expectCode(() => setFirmStatus(db, 9999, 'archived'), 'FIRM_NOT_FOUND')
  })
})

describe('firmService — list filtering and sort', () => {
  it('sorts alphabetically case-insensitive', () => {
    createFirm(db, 'zebra')
    createFirm(db, 'Apple')
    createFirm(db, 'mango')
    const names = listFirms(db, 'all').map((f) => f.name)
    expect(names).toEqual(['Apple', 'mango', 'zebra'])
  })

  it('filters by active/archived', () => {
    createFirm(db, 'Active One')
    const b = createFirm(db, 'Archived One')
    setFirmStatus(db, b.id, 'archived')
    expect(listFirms(db, 'active').map((f) => f.name)).toEqual(['Active One'])
    expect(listFirms(db, 'archived').map((f) => f.name)).toEqual(['Archived One'])
  })
})

describe('firmService — partners', () => {
  it('auto-creates a default partner named after the firm', () => {
    const f = createFirm(db, 'Firm')
    expect(getFirm(db, f.id).partners.map((x) => x.name)).toEqual(['Firm'])
  })

  it('adds and removes partners (alongside the default firm-named partner)', () => {
    const f = createFirm(db, 'Firm')
    const p = addPartner(db, f.id, 'Jane Doe')
    // Sorted case-insensitively: Firm, Jane Doe
    expect(getFirm(db, f.id).partners.map((x) => x.name)).toEqual(['Firm', 'Jane Doe'])
    removePartner(db, f.id, p.id)
    expect(getFirm(db, f.id).partners.map((x) => x.name)).toEqual(['Firm'])
  })

  it('rejects duplicate partner within the same firm', () => {
    const f = createFirm(db, 'Firm')
    addPartner(db, f.id, 'Jane')
    expectCode(() => addPartner(db, f.id, 'JANE'), 'DUPLICATE_PARTNER_NAME')
  })

  it('renames a partner and rejects a duplicate rename', () => {
    const f = createFirm(db, 'Firm')
    const p = addPartner(db, f.id, 'Jane')
    const updated = updatePartner(db, f.id, p.id, 'Janet')
    expect(updated.name).toBe('Janet')
    expect(getFirm(db, f.id).partners.map((x) => x.name)).toEqual(['Firm', 'Janet'])
    // Renaming to the existing firm-named partner (case-insensitive) must fail.
    expectCode(() => updatePartner(db, f.id, p.id, 'firm'), 'DUPLICATE_PARTNER_NAME')
  })
})

describe('firmService — update', () => {
  it('renames a firm', () => {
    const f = createFirm(db, 'Old Name')
    const updated = updateFirm(db, f.id, { name: 'New Name' })
    expect(updated.name).toBe('New Name')
  })

  it('rejects renaming to an existing name', () => {
    createFirm(db, 'Taken')
    const f = createFirm(db, 'Mine')
    expectCode(() => updateFirm(db, f.id, { name: 'taken' }), 'DUPLICATE_FIRM_NAME')
  })
})

describe('firmService — matter status rollups (Firm page dots)', () => {
  function mkMatter(firmId: number, partnerId: number, name: string) {
    return createMatter(db, { name, firmId, partnerId }).id
  }
  function mkMemo(matterId: number, total: number, date = '2026-07-15') {
    return createMemo(db, {
      date, matterId, addresseeLine1: 'A',
      numAppearances: 0, feesPerAppearance: 0, numConferences: 0,
      feesPerConference: 0, feesMiscDrafting: total,
    })
  }

  it('a matter is Paid only when every memo is fully paid', () => {
    const f = createFirm(db, 'F')
    const p = addPartner(db, f.id, 'P')
    const mt = mkMatter(f.id, p.id, 'All Paid')
    const a = mkMemo(mt, 1000)
    const b = mkMemo(mt, 500)
    addPaymentToMemo(db, a.id, { amount: 1000, dateOfPayment: '2026-08-01' })
    addPaymentToMemo(db, b.id, { amount: 500, dateOfPayment: '2026-08-01' })
    const matter = getFirm(db, f.id).matters.find((m) => m.id === mt)!
    expect(matter.memoStatus).toBe('Paid')
    expect(matter.hasWrittenOff).toBe(false)
  })

  it('a matter is Unpaid if any memo is unpaid (and none overdue)', () => {
    const f = createFirm(db, 'F')
    const p = addPartner(db, f.id, 'P')
    const mt = mkMatter(f.id, p.id, 'One Unpaid')
    const a = mkMemo(mt, 1000)
    mkMemo(mt, 500) // unpaid, recent date → not overdue (overdueDays default 0 = off)
    addPaymentToMemo(db, a.id, { amount: 1000, dateOfPayment: '2026-08-01' })
    const matter = getFirm(db, f.id).matters.find((m) => m.id === mt)!
    expect(matter.memoStatus).toBe('Unpaid')
  })

  it('a matter with no finalised memos has a null status', () => {
    const f = createFirm(db, 'F')
    const p = addPartner(db, f.id, 'P')
    const mt = mkMatter(f.id, p.id, 'Empty')
    const matter = getFirm(db, f.id).matters.find((m) => m.id === mt)!
    expect(matter.memoStatus).toBeNull()
    expect(matter.hasWrittenOff).toBe(false)
  })

  it('hasWrittenOff is set (alongside the primary status) when a memo is written off', () => {
    const f = createFirm(db, 'F')
    const p = addPartner(db, f.id, 'P')
    const mt = mkMatter(f.id, p.id, 'With WO')
    const a = mkMemo(mt, 1000)
    const off = mkMemo(mt, 500)
    addPaymentToMemo(db, a.id, { amount: 1000, dateOfPayment: '2026-08-01' })
    setMemoWrittenOff(db, off.id, true)
    const matter = getFirm(db, f.id).matters.find((m) => m.id === mt)!
    // The written-off memo is excluded from the "unpaid" roll-up, so the live
    // memo being paid makes the primary status Paid, with the grey flag set.
    expect(matter.memoStatus).toBe('Paid')
    expect(matter.hasWrittenOff).toBe(true)
  })

  it('a matter whose memos are ALL written off shows grey only (no primary status)', () => {
    const f = createFirm(db, 'F')
    const p = addPartner(db, f.id, 'P')
    const mt = mkMatter(f.id, p.id, 'All WO')
    const a = mkMemo(mt, 1000) // unpaid
    const b = mkMemo(mt, 500) // unpaid
    setMemoWrittenOff(db, a.id, true)
    setMemoWrittenOff(db, b.id, true)
    const matter = getFirm(db, f.id).matters.find((m) => m.id === mt)!
    // No live memos remain → no primary dot (null), only the grey written-off dot.
    expect(matter.memoStatus).toBeNull()
    expect(matter.hasWrittenOff).toBe(true)
  })
})
