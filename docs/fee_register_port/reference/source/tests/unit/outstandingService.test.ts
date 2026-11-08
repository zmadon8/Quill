import { describe, it, expect, beforeEach, beforeAll, afterAll } from 'vitest'
import type Database from 'better-sqlite3'
import { createSchemaDb, truncateAll } from '../helpers/testDb'
import { createFirm, addPartner } from '@/services/firmService'
import { createMatter, archiveMatter } from '@/services/matterService'
import { createMemo, setMemoWrittenOff } from '@/services/memoService'
import { addPaymentToMemo } from '@/services/paymentService'
import {
  listOutstanding,
  outstandingGrandTotal,
  listOutstandingScope,
  listOutstandingByFirm,
} from '@/services/outstandingService'

let db: Database.Database
beforeAll(() => { db = createSchemaDb() })
afterAll(() => db.close())
beforeEach(() => truncateAll(db))

function setup() {
  const f = createFirm(db, 'Firm')
  const p = addPartner(db, f.id, 'P')
  const m1 = createMatter(db, { name: 'Alpha', firmId: f.id, partnerId: p.id })
  const m2 = createMatter(db, { name: 'Beta', firmId: f.id, partnerId: p.id })
  return { firmId: f.id, partnerId: p.id, m1: m1.id, m2: m2.id }
}

function memo(matterId: number, total: number, date = '2026-07-15') {
  return createMemo(db, {
    date, matterId, addresseeLine1: 'A',
    numAppearances: 0, feesPerAppearance: 0, numConferences: 0,
    feesPerConference: 0, feesMiscDrafting: total,
  })
}

describe('outstandingService', () => {
  it('lists only unpaid memos, grouped by matter with subtotals', () => {
    const { m1, m2 } = setup()
    memo(m1, 1000)
    memo(m1, 500)
    const paid = memo(m2, 800)
    addPaymentToMemo(db, paid.id, { amount: 800, dateOfPayment: '2026-08-01' }) // fully paid -> excluded

    const groups = listOutstanding(db, {})
    expect(groups).toHaveLength(1)
    expect(groups[0].matterName).toBe('Alpha')
    expect(groups[0].entries).toHaveLength(2)
    expect(groups[0].subtotal).toBe(1500)
    expect(outstandingGrandTotal(groups)).toBe(1500)
  })

  it('includes memos from archived matters', () => {
    const { m1 } = setup()
    memo(m1, 1000)
    archiveMatter(db, m1)
    const groups = listOutstanding(db, {})
    expect(groups).toHaveLength(1)
    expect(groups[0].subtotal).toBe(1000)
  })

  it('excludes written-off memos unless includeWrittenOff is set (Req #7)', () => {
    const { m1 } = setup()
    const keep = memo(m1, 1000)
    const off = memo(m1, 700)
    setMemoWrittenOff(db, off.id, true)

    // Default: written-off memo is hidden.
    const def = listOutstanding(db, {})
    expect(def).toHaveLength(1)
    expect(def[0].subtotal).toBe(1000)
    expect(def[0].entries.every((e) => e.memoId !== off.id)).toBe(true)
    expect(keep.id).toBeGreaterThan(0)

    // With includeWrittenOff, both appear.
    const incl = listOutstanding(db, { includeWrittenOff: true })
    expect(incl[0].entries).toHaveLength(2)
    expect(incl[0].subtotal).toBe(1700)
  })

  it('scope lists only firms/partners with applicable items (honours flags)', () => {
    const f1 = createFirm(db, 'Firm One')
    const p1 = addPartner(db, f1.id, 'P1')
    const m1 = createMatter(db, { name: 'A', firmId: f1.id, partnerId: p1.id })
    memo(m1.id, 1000) // outstanding

    // A second firm whose only memo is written off.
    const f2 = createFirm(db, 'Firm Two')
    const p2 = addPartner(db, f2.id, 'P2')
    const m2 = createMatter(db, { name: 'B', firmId: f2.id, partnerId: p2.id })
    const off = memo(m2.id, 500)
    setMemoWrittenOff(db, off.id, true)

    // Default scope: only Firm One (Firm Two's sole memo is written off).
    const base = listOutstandingScope(db, {})
    expect(base.firms.map((f) => f.name)).toEqual(['Firm One'])

    // With written-off included: both firms appear.
    const incl = listOutstandingScope(db, { includeWrittenOff: true })
    expect(incl.firms.map((f) => f.name).sort()).toEqual(['Firm One', 'Firm Two'])
  })

  it('entries carry firm, partner and written-off status for export columns', () => {
    const f = createFirm(db, 'Acme & Co')
    const p = addPartner(db, f.id, 'Jane')
    const mt = createMatter(db, { name: 'Alpha', firmId: f.id, partnerId: p.id })
    const keep = memo(mt.id, 1000)
    const off = memo(mt.id, 500)
    setMemoWrittenOff(db, off.id, true)

    const groups = listOutstanding(db, { firmId: f.id, includeWrittenOff: true })
    const entries = groups.flatMap((g) => g.entries)
    const keepE = entries.find((e) => e.memoId === keep.id)
    const offE = entries.find((e) => e.memoId === off.id)
    expect(keepE?.firmName).toBe('Acme & Co')
    expect(keepE?.partnerName).toBe('Jane')
    expect(keepE?.isWrittenOff).toBe(false)
    expect(offE?.isWrittenOff).toBe(true)
  })

  it('each group carries its partner so matters can be grouped partner-wise', () => {
    const f = createFirm(db, 'Firm')
    const pa = addPartner(db, f.id, 'PA')
    const pb = addPartner(db, f.id, 'PB')
    const ma = createMatter(db, { name: 'Alpha', firmId: f.id, partnerId: pa.id })
    const mb = createMatter(db, { name: 'Beta', firmId: f.id, partnerId: pb.id })
    memo(ma.id, 1000)
    memo(mb.id, 400)

    const groups = listOutstanding(db, { firmId: f.id })
    const alpha = groups.find((g) => g.matterName === 'Alpha')
    const beta = groups.find((g) => g.matterName === 'Beta')
    expect(alpha?.partnerName).toBe('PA')
    expect(alpha?.partnerId).toBe(pa.id)
    expect(beta?.partnerName).toBe('PB')
    expect(beta?.partnerId).toBe(pb.id)
  })

  it('firm-wise summary honours the partner filter', () => {
    const f = createFirm(db, 'Multi')
    const pa = addPartner(db, f.id, 'PA')
    const pb = addPartner(db, f.id, 'PB')
    const ma = createMatter(db, { name: 'MA', firmId: f.id, partnerId: pa.id })
    const mb = createMatter(db, { name: 'MB', firmId: f.id, partnerId: pb.id })
    memo(ma.id, 1000)
    memo(mb.id, 400)

    const all = listOutstandingByFirm(db, {})
    expect(all.find((r) => r.firmId === f.id)?.outstanding).toBe(1400)

    const onlyPa = listOutstandingByFirm(db, { partnerId: pa.id })
    expect(onlyPa.find((r) => r.firmId === f.id)?.outstanding).toBe(1000)
  })

  it('entries and subtotals carry total, net-of-TDS, paid and due (partial payment)', () => {
    const { m1 } = setup()
    const part = memo(m1, 1000) // net of 10% TDS = 900
    addPaymentToMemo(db, part.id, { amount: 300, dateOfPayment: '2026-08-01' }) // partial → still outstanding
    memo(m1, 500) // unpaid; net = 450

    const groups = listOutstanding(db, {})
    expect(groups).toHaveLength(1)
    const g = groups[0]
    const e = g.entries.find((x) => x.memoId === part.id)!
    expect(e.totalFees).toBe(1000)
    expect(e.netOfTds).toBe(900)
    expect(e.amountPaid).toBe(300)
    expect(e.due).toBe(700)

    // Subtotals: total 1500, net 1350, paid 300, due (subtotal) 1200.
    expect(g.subtotalTotal).toBe(1500)
    expect(g.subtotalNetOfTds).toBe(1350)
    expect(g.subtotalPaid).toBe(300)
    expect(g.subtotal).toBe(1200)
  })
})
