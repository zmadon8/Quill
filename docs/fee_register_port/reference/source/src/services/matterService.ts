/**
 * matterService.ts
 *
 * Pure, testable business logic for Matters. Each function takes a raw
 * better-sqlite3 Database as its first argument so it can be unit- and
 * property-tested against an in-memory database.
 *
 * A Matter belongs to exactly one Firm and one Partner. Matter names are unique
 * within a Firm (case-insensitive). New Matters are Active (is_archived = 0).
 * Prepared statements are cached per-database to bound native handle count.
 */

import type Database from 'better-sqlite3'
import { AppError } from '@/types/ipc'
import type {
  MatterDTO,
  MatterDetail,
  MatterInput,
  MatterUpdateInput,
  MatterFilter,
} from '@/types/ipc'
import { prep } from '@/db/prep'

const MAX_NAME = 150

function validateName(name: string): string {
  const trimmed = (name ?? '').trim()
  if (trimmed.length < 1 || trimmed.length > MAX_NAME) {
    throw new AppError('INVALID_MATTER_NAME', `Matter name must be between 1 and ${MAX_NAME} characters`)
  }
  return trimmed
}

type MatterRow = {
  id: number
  firm_id: number
  partner_id: number
  name: string
  is_archived: number
  addressee_line1: string | null
  addressee_line2: string | null
  addressee_use_firm_name: number
  court_name: string | null
  client: string | null
  additional_details_left: string | null
  additional_details_right: string | null
  plaintiff_name: string | null
  plaintiff_type: string | null
  defendant_name: string | null
  defendant_type: string | null
  notes: string | null
  short_name: string | null
}

// Columns selected whenever we need the full matter (including memo defaults).
const MATTER_COLS =
  'id, firm_id, partner_id, name, is_archived, addressee_line1, addressee_line2, ' +
  'addressee_use_firm_name, court_name, client, additional_details_left, ' +
  'additional_details_right, plaintiff_name, plaintiff_type, defendant_name, defendant_type, notes, short_name'

function toDTO(r: MatterRow): MatterDTO {
  return {
    id: r.id,
    firmId: r.firm_id,
    partnerId: r.partner_id,
    name: r.name,
    isArchived: r.is_archived === 1,
    addresseeLine1: r.addressee_line1 ?? undefined,
    addresseeLine2: r.addressee_line2 ?? undefined,
    addresseeUseFirmName: r.addressee_use_firm_name === 1,
    courtName: r.court_name ?? undefined,
    client: r.client ?? undefined,
    additionalDetailsLeft: r.additional_details_left ?? undefined,
    additionalDetailsRight: r.additional_details_right ?? undefined,
    plaintiffName: r.plaintiff_name ?? undefined,
    plaintiffType: r.plaintiff_type ?? undefined,
    defendantName: r.defendant_name ?? undefined,
    defendantType: r.defendant_type ?? undefined,
    notes: r.notes ?? undefined,
    shortName: r.short_name ?? undefined,
  }
}

// ---------------------------------------------------------------------------
// Create
// ---------------------------------------------------------------------------

export function createMatter(db: Database.Database, input: MatterInput): MatterDTO {
  const name = validateName(input.name)

  const firm = prep(db, 'SELECT id FROM firms WHERE id = ?').get(input.firmId) as
    | { id: number }
    | undefined
  if (!firm) throw new AppError('FIRM_NOT_FOUND', `Firm ${input.firmId} not found`)

  const partner = prep(db, 'SELECT id FROM partners WHERE id = ? AND firm_id = ?').get(
    input.partnerId,
    input.firmId,
  ) as { id: number } | undefined
  if (!partner) {
    throw new AppError('PARTNER_NOT_FOUND', `Partner ${input.partnerId} is not part of firm ${input.firmId}`)
  }

  // Matter names are unique within a firm (case-insensitive).
  const dupe = prep(db, 'SELECT id FROM matters WHERE firm_id = ? AND lower(name) = lower(?)').get(
    input.firmId,
    name,
  ) as { id: number } | undefined
  if (dupe) {
    throw new AppError('DUPLICATE_MATTER_NAME', `A matter named "${name}" already exists in this firm`)
  }

  const info = prep(
    db,
    `INSERT INTO matters (
      firm_id, partner_id, name, is_archived,
      addressee_line1, addressee_line2, addressee_use_firm_name,
      court_name, client, additional_details_left, additional_details_right,
      plaintiff_name, plaintiff_type, defendant_name, defendant_type, notes, short_name
    ) VALUES (
      @firmId, @partnerId, @name, 0,
      @addresseeLine1, @addresseeLine2, @addresseeUseFirmName,
      @courtName, @client, @additionalDetailsLeft, @additionalDetailsRight,
      @plaintiffName, @plaintiffType, @defendantName, @defendantType, @notes, @shortName
    )`,
  ).run({
    firmId: input.firmId,
    partnerId: input.partnerId,
    name,
    addresseeLine1: input.addresseeLine1 ?? null,
    addresseeLine2: input.addresseeLine2 ?? null,
    addresseeUseFirmName: input.addresseeUseFirmName ? 1 : 0,
    courtName: input.courtName ?? null,
    client: input.client ?? null,
    additionalDetailsLeft: input.additionalDetailsLeft ?? null,
    additionalDetailsRight: input.additionalDetailsRight ?? null,
    plaintiffName: input.plaintiffName ?? null,
    plaintiffType: input.plaintiffType ?? null,
    defendantName: input.defendantName ?? null,
    defendantType: input.defendantType ?? null,
    notes: input.notes ?? null,
    shortName: input.shortName?.trim() || null,
  })

  return getMatter(db, Number(info.lastInsertRowid))
}

// ---------------------------------------------------------------------------
// Update (name + matter-level memo defaults)
// ---------------------------------------------------------------------------

export function updateMatter(
  db: Database.Database,
  id: number,
  input: MatterUpdateInput,
): MatterDetail {
  const row = prep(db, 'SELECT id, firm_id, partner_id FROM matters WHERE id = ?').get(id) as
    | { id: number; firm_id: number; partner_id: number }
    | undefined
  if (!row) throw new AppError('MATTER_NOT_FOUND', `Matter ${id} not found`)

  // Resolve the matter's (possibly new) firm/partner. When moving the matter to
  // another firm, the partner must belong to that firm. Changing either here
  // cascades to the matter's memos, which denormalise firm_id/partner_id.
  const targetFirmId = input.firmId ?? row.firm_id
  const targetPartnerId = input.partnerId ?? row.partner_id
  const firmOrPartnerChanged =
    targetFirmId !== row.firm_id || targetPartnerId !== row.partner_id

  if (firmOrPartnerChanged) {
    const firm = prep(db, 'SELECT id FROM firms WHERE id = ?').get(targetFirmId) as
      | { id: number }
      | undefined
    if (!firm) throw new AppError('FIRM_NOT_FOUND', `Firm ${targetFirmId} not found`)
    const partner = prep(db, 'SELECT id FROM partners WHERE id = ? AND firm_id = ?').get(
      targetPartnerId,
      targetFirmId,
    ) as { id: number } | undefined
    if (!partner) {
      throw new AppError(
        'PARTNER_NOT_FOUND',
        `Partner ${targetPartnerId} is not part of firm ${targetFirmId}`,
      )
    }
  }

  // Name uniqueness is checked against the TARGET firm (which may be new).
  if (input.name !== undefined) {
    const name = validateName(input.name)
    const dupe = prep(
      db,
      'SELECT id FROM matters WHERE firm_id = ? AND lower(name) = lower(?) AND id != ?',
    ).get(targetFirmId, name, id) as { id: number } | undefined
    if (dupe) {
      throw new AppError('DUPLICATE_MATTER_NAME', `A matter named "${name}" already exists in this firm`)
    }
    prep(db, "UPDATE matters SET name = ?, updated_at = datetime('now') WHERE id = ?").run(name, id)
  } else if (firmOrPartnerChanged) {
    // Even without a rename, moving firms must not collide with an existing
    // matter name in the target firm.
    const current = prep(db, 'SELECT name FROM matters WHERE id = ?').get(id) as { name: string }
    const dupe = prep(
      db,
      'SELECT id FROM matters WHERE firm_id = ? AND lower(name) = lower(?) AND id != ?',
    ).get(targetFirmId, current.name, id) as { id: number } | undefined
    if (dupe) {
      throw new AppError(
        'DUPLICATE_MATTER_NAME',
        `A matter named "${current.name}" already exists in the target firm`,
      )
    }
  }

  // Apply the firm/partner move to the matter and cascade to its memos. Memos
  // carry denormalised firm_id/partner_id for query performance, so they must
  // stay in sync with the matter.
  if (firmOrPartnerChanged) {
    const move = db.transaction(() => {
      prep(
        db,
        "UPDATE matters SET firm_id = ?, partner_id = ?, updated_at = datetime('now') WHERE id = ?",
      ).run(targetFirmId, targetPartnerId, id)
      prep(db, 'UPDATE memos SET firm_id = ?, partner_id = ? WHERE matter_id = ?').run(
        targetFirmId,
        targetPartnerId,
        id,
      )
    })
    move()
  }

  prep(
    db,
    `UPDATE matters SET
      addressee_line1 = @addresseeLine1,
      addressee_line2 = @addresseeLine2,
      addressee_use_firm_name = @addresseeUseFirmName,
      court_name = @courtName,
      client = @client,
      additional_details_left = @additionalDetailsLeft,
      additional_details_right = @additionalDetailsRight,
      plaintiff_name = @plaintiffName,
      plaintiff_type = @plaintiffType,
      defendant_name = @defendantName,
      defendant_type = @defendantType,
      notes = @notes,
      short_name = @shortName,
      updated_at = datetime('now')
     WHERE id = @id`,
  ).run({
    id,
    addresseeLine1: input.addresseeLine1 ?? null,
    addresseeLine2: input.addresseeLine2 ?? null,
    addresseeUseFirmName: input.addresseeUseFirmName ? 1 : 0,
    courtName: input.courtName ?? null,
    client: input.client ?? null,
    additionalDetailsLeft: input.additionalDetailsLeft ?? null,
    additionalDetailsRight: input.additionalDetailsRight ?? null,
    plaintiffName: input.plaintiffName ?? null,
    plaintiffType: input.plaintiffType ?? null,
    defendantName: input.defendantName ?? null,
    defendantType: input.defendantType ?? null,
    notes: input.notes ?? null,
    shortName: input.shortName?.trim() || null,
  })

  return getMatter(db, id)
}

// ---------------------------------------------------------------------------
// List
// ---------------------------------------------------------------------------

/**
 * Lists matters, optionally scoped to a firm, sorted by partner name then by
 * matter name (both case-insensitive). The filter applies to archived status.
 */
export function listMatters(
  db: Database.Database,
  filter: MatterFilter,
  firmId?: number,
): MatterDetail[] {
  const where: string[] = []
  const params: unknown[] = []

  if (firmId !== undefined) {
    where.push('m.firm_id = ?')
    params.push(firmId)
  }
  if (filter === 'active') where.push('m.is_archived = 0')
  else if (filter === 'archived') where.push('m.is_archived = 1')

  const whereSql = where.length ? `WHERE ${where.join(' AND ')}` : ''

  const rows = prep(
    db,
    `SELECT ${MATTER_COLS.split(', ').map((c) => `m.${c}`).join(', ')},
            f.name AS firm_name, p.name AS partner_name
     FROM matters m
     JOIN firms f ON f.id = m.firm_id
     JOIN partners p ON p.id = m.partner_id
     ${whereSql}
     ORDER BY lower(p.name) ASC, lower(m.name) ASC`,
  ).all(...params) as Array<MatterRow & { firm_name: string; partner_name: string }>

  return rows.map((r) => ({ ...toDTO(r), firmName: r.firm_name, partnerName: r.partner_name }))
}

// ---------------------------------------------------------------------------
// Get
// ---------------------------------------------------------------------------

export function getMatter(db: Database.Database, id: number): MatterDetail {
  const row = prep(
    db,
    `SELECT ${MATTER_COLS.split(', ').map((c) => `m.${c}`).join(', ')},
            f.name AS firm_name, p.name AS partner_name
     FROM matters m
     JOIN firms f ON f.id = m.firm_id
     JOIN partners p ON p.id = m.partner_id
     WHERE m.id = ?`,
  ).get(id) as (MatterRow & { firm_name: string; partner_name: string }) | undefined
  if (!row) throw new AppError('MATTER_NOT_FOUND', `Matter ${id} not found`)
  return { ...toDTO(row), firmName: row.firm_name, partnerName: row.partner_name }
}

// ---------------------------------------------------------------------------
// Archive / Unarchive
// ---------------------------------------------------------------------------

function setArchived(db: Database.Database, id: number, archived: boolean): MatterDTO {
  const row = prep(db, `SELECT ${MATTER_COLS} FROM matters WHERE id = ?`).get(
    id,
  ) as MatterRow | undefined
  if (!row) throw new AppError('MATTER_NOT_FOUND', `Matter ${id} not found`)

  prep(db, "UPDATE matters SET is_archived = ?, updated_at = datetime('now') WHERE id = ?").run(
    archived ? 1 : 0,
    id,
  )
  return { ...toDTO(row), isArchived: archived }
}

export function archiveMatter(db: Database.Database, id: number): MatterDTO {
  return setArchived(db, id, true)
}

export function unarchiveMatter(db: Database.Database, id: number): MatterDTO {
  return setArchived(db, id, false)
}

/** Returns true if the matter exists and is Active (not archived). */
export function isMatterActive(db: Database.Database, id: number): boolean {
  const row = prep(db, 'SELECT is_archived FROM matters WHERE id = ?').get(id) as
    | { is_archived: number }
    | undefined
  return row !== undefined && row.is_archived === 0
}
