import { describe, it, expect, beforeEach, beforeAll, afterAll } from 'vitest'
import type Database from 'better-sqlite3'
import { createSchemaDb, truncateAll } from '../helpers/testDb'
import { createFirm, addPartner } from '@/services/firmService'
import { createMemo } from '@/services/memoService'
import {
  createMatter,
  updateMatter,
  listMatters,
  getMatter,
  archiveMatter,
  unarchiveMatter,
  isMatterActive,
} from '@/services/matterService'

let db: Database.Database
beforeAll(() => { db = createSchemaDb() })
afterAll(() => db.close())
beforeEach(() => truncateAll(db))

function expectCode(fn: () => unknown, code: string): void {
  try {
    fn()
  } catch (err) {
    expect((err as { code?: string }).code).toBe(code)
    return
  }
  throw new Error(`Expected AppError with code ${code}`)
}

/** Seeds a firm + partner and returns their ids. */
function seedFirmPartner(firmName = 'Firm', partnerName = 'Partner A') {
  const f = createFirm(db, firmName)
  const p = addPartner(db, f.id, partnerName)
  return { firmId: f.id, partnerId: p.id }
}

describe('matterService — create', () => {
  it('creates an active matter', () => {
    const { firmId, partnerId } = seedFirmPartner()
    const m = createMatter(db, { name: 'Smith v Jones', firmId, partnerId })
    expect(m.name).toBe('Smith v Jones')
    expect(m.isArchived).toBe(false)
    expect(m.firmId).toBe(firmId)
    expect(m.partnerId).toBe(partnerId)
  })

  it('rejects an empty name', () => {
    const { firmId, partnerId } = seedFirmPartner()
    expectCode(() => createMatter(db, { name: '  ', firmId, partnerId }), 'INVALID_MATTER_NAME')
  })

  it('rejects a name longer than 150 chars', () => {
    const { firmId, partnerId } = seedFirmPartner()
    expectCode(() => createMatter(db, { name: 'x'.repeat(151), firmId, partnerId }), 'INVALID_MATTER_NAME')
  })

  it('rejects a duplicate name within the same firm (case-insensitive)', () => {
    const { firmId, partnerId } = seedFirmPartner()
    createMatter(db, { name: 'Matter One', firmId, partnerId })
    expectCode(() => createMatter(db, { name: 'MATTER ONE', firmId, partnerId }), 'DUPLICATE_MATTER_NAME')
  })

  it('allows the same matter name in a different firm', () => {
    const a = seedFirmPartner('Firm A', 'P')
    const b = seedFirmPartner('Firm B', 'P')
    createMatter(db, { name: 'Shared Name', firmId: a.firmId, partnerId: a.partnerId })
    const m = createMatter(db, { name: 'Shared Name', firmId: b.firmId, partnerId: b.partnerId })
    expect(m.id).toBeGreaterThan(0)
  })

  it('rejects a partner not belonging to the firm', () => {
    const a = seedFirmPartner('Firm A', 'P')
    const b = seedFirmPartner('Firm B', 'Q')
    expectCode(
      () => createMatter(db, { name: 'X', firmId: a.firmId, partnerId: b.partnerId }),
      'PARTNER_NOT_FOUND',
    )
  })
})

describe('matterService — create and update common memo fields', () => {
  it('persists matter-level memo defaults on create', () => {
    const { firmId, partnerId } = seedFirmPartner()
    const m = createMatter(db, {
      name: 'With Defaults',
      firmId,
      partnerId,
      addresseeLine2: 'Attn: Accounts',
      addresseeUseFirmName: true,
      courtName: 'In the High Court',
      client: 'Acme Corp',
      plaintiffName: 'Acme',
      plaintiffType: 'Plaintiff',
      defendantName: 'Beta',
      defendantType: 'Defendant',
    })
    const got = getMatter(db, m.id)
    expect(got.addresseeUseFirmName).toBe(true)
    expect(got.courtName).toBe('In the High Court')
    expect(got.client).toBe('Acme Corp')
    expect(got.plaintiffName).toBe('Acme')
    expect(got.defendantType).toBe('Defendant')
  })

  it('updates name and common fields; keeps duplicate-name protection', () => {
    const { firmId, partnerId } = seedFirmPartner()
    createMatter(db, { name: 'Existing', firmId, partnerId })
    const m = createMatter(db, { name: 'Editable', firmId, partnerId })

    const updated = updateMatter(db, m.id, {
      name: 'Renamed',
      courtName: 'Updated Cause Title',
      addresseeUseFirmName: false,
      addresseeLine1: 'Custom Addressee',
    })
    expect(updated.name).toBe('Renamed')
    expect(updated.courtName).toBe('Updated Cause Title')
    expect(updated.addresseeLine1).toBe('Custom Addressee')
    expect(updated.addresseeUseFirmName).toBe(false)

    // Renaming onto an existing matter name in the same firm is rejected.
    expectCode(() => updateMatter(db, m.id, { name: 'existing' }), 'DUPLICATE_MATTER_NAME')
  })

  it('updateMatter throws for a missing id', () => {
    expectCode(() => updateMatter(db, 4242, { name: 'X' }), 'MATTER_NOT_FOUND')
  })
})

describe('matterService — list sort and filter', () => {
  it('sorts by partner then matter name, case-insensitive', () => {
    const f = createFirm(db, 'Firm')
    const pB = addPartner(db, f.id, 'Bravo')
    const pA = addPartner(db, f.id, 'alpha')
    createMatter(db, { name: 'zebra', firmId: f.id, partnerId: pA.id })
    createMatter(db, { name: 'Apple', firmId: f.id, partnerId: pA.id })
    createMatter(db, { name: 'mango', firmId: f.id, partnerId: pB.id })
    const list = listMatters(db, 'all', f.id)
    expect(list.map((m) => `${m.partnerName}/${m.name}`)).toEqual([
      'alpha/Apple',
      'alpha/zebra',
      'Bravo/mango',
    ])
  })

  it('filters active vs archived', () => {
    const { firmId, partnerId } = seedFirmPartner()
    const active = createMatter(db, { name: 'Active M', firmId, partnerId })
    const toArchive = createMatter(db, { name: 'Archived M', firmId, partnerId })
    archiveMatter(db, toArchive.id)
    expect(listMatters(db, 'active', firmId).map((m) => m.name)).toEqual(['Active M'])
    expect(listMatters(db, 'archived', firmId).map((m) => m.name)).toEqual(['Archived M'])
    expect(listMatters(db, 'all', firmId)).toHaveLength(2)
    expect(active.isArchived).toBe(false)
  })
})

describe('matterService — archive lifecycle', () => {
  it('archive then unarchive is a round-trip', () => {
    const { firmId, partnerId } = seedFirmPartner()
    const m = createMatter(db, { name: 'M', firmId, partnerId })
    expect(isMatterActive(db, m.id)).toBe(true)
    archiveMatter(db, m.id)
    expect(isMatterActive(db, m.id)).toBe(false)
    expect(getMatter(db, m.id).isArchived).toBe(true)
    unarchiveMatter(db, m.id)
    expect(isMatterActive(db, m.id)).toBe(true)
    expect(getMatter(db, m.id).isArchived).toBe(false)
  })

  it('getMatter throws for a missing id', () => {
    expectCode(() => getMatter(db, 9999), 'MATTER_NOT_FOUND')
  })
})

describe('matterService — reassign firm/partner', () => {
  it('moves the matter and cascades firm/partner to its memos', () => {
    const fa = createFirm(db, 'Firm A')
    const pa = addPartner(db, fa.id, 'PA')
    const fb = createFirm(db, 'Firm B')
    const pb = addPartner(db, fb.id, 'PB')
    const m = createMatter(db, { name: 'Case', firmId: fa.id, partnerId: pa.id })
    const memo = createMemo(db, {
      date: '2026-01-10',
      matterId: m.id,
      addresseeLine1: 'A',
      numAppearances: 1,
      feesPerAppearance: 1000,
      numConferences: 0,
      feesPerConference: 0,
      feesMiscDrafting: 0,
    })

    const updated = updateMatter(db, m.id, { firmId: fb.id, partnerId: pb.id })
    expect(updated.firmId).toBe(fb.id)
    expect(updated.partnerId).toBe(pb.id)
    expect(updated.firmName).toBe('Firm B')

    // The memo's denormalised firm/partner follow the matter.
    const row = db
      .prepare('SELECT firm_id, partner_id FROM memos WHERE id = ?')
      .get(memo.id) as { firm_id: number; partner_id: number }
    expect(row.firm_id).toBe(fb.id)
    expect(row.partner_id).toBe(pb.id)
  })

  it('rejects a partner that does not belong to the target firm', () => {
    const fa = createFirm(db, 'Firm A')
    const pa = addPartner(db, fa.id, 'PA')
    const fb = createFirm(db, 'Firm B')
    addPartner(db, fb.id, 'PB')
    const m = createMatter(db, { name: 'Case', firmId: fa.id, partnerId: pa.id })
    // Partner pa is not in firm fb.
    expectCode(() => updateMatter(db, m.id, { firmId: fb.id, partnerId: pa.id }), 'PARTNER_NOT_FOUND')
  })
})
