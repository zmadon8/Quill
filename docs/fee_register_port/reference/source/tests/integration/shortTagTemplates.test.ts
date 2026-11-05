import { existsSync, readFileSync } from 'fs'
import { resolve } from 'path'
import PizZip from 'pizzip'
import { describe, it, expect, beforeAll, afterAll, beforeEach } from 'vitest'
import type Database from 'better-sqlite3'
import { createSchemaDb, truncateAll } from '../helpers/testDb'
import { createFirm, addPartner } from '@/services/firmService'
import { createMatter } from '@/services/matterService'
import { createMemo, getMemo } from '@/services/memoService'
import { generateWordBuffer } from '@/services/exportService'

// The user's real converted templates live in the project root; the check is
// skipped for any that are absent (e.g. on a fresh checkout).
const TEMPLATES = [
  'Template 10-10-2026 (short tags).docx',
  'Template 10-10-2026 (conditional) (short tags).docx',
  'Template 30-10-2026 (short tags).docx',
].filter((f) => existsSync(resolve(process.cwd(), f)))

let db: Database.Database
beforeAll(() => { db = createSchemaDb() })
afterAll(() => db.close())
beforeEach(() => truncateAll(db))

function text(buf: Buffer): string {
  const xml = new PizZip(buf).file('word/document.xml')!.asText()
  return xml.replace(/<\/w:p>/g, '\n').replace(/<[^>]+>/g, '')
}

describe.skipIf(TEMPLATES.length === 0)('converted short-tag templates render correctly', () => {
  for (const name of TEMPLATES) {
    it(name, () => {
      const f = createFirm(db, 'Firm')
      const p = addPartner(db, f.id, 'P')
      const m = createMatter(db, { name: 'Matter', firmId: f.id, partnerId: p.id })
      const memo = getMemo(db, createMemo(db, {
        date: '2026-10-16', matterId: m.id, addresseeLine1: 'A',
        numAppearances: 1, feesPerAppearance: 1000, numConferences: 2, feesPerConference: 500,
        feesMiscDrafting: 0, datesOfAppearances: '1.1.26', datesOfConferences: '2.1.26',
      }).id)
      const out = text(generateWordBuffer(readFileSync(resolve(process.cwd(), name)), memo))
      expect(out).not.toContain('{{')
      expect(out).toContain('16.10.2026') // dots, not dashes
      expect(out).toMatch(/1 Appearance\b(?!s)/) // singular for 1
      expect(out).toMatch(/2 Conferences/) // plural for 2
      expect(out).not.toMatch(/Appearances Appearances|Conferences Conferences/)
    })
  }
})
