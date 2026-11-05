import { describe, it, expect, beforeEach, beforeAll, afterAll } from 'vitest'
import fs from 'fs'
import path from 'path'
import PizZip from 'pizzip'
import type Database from 'better-sqlite3'
import { createSchemaDb, truncateAll } from '../helpers/testDb'
import { createFirm, addPartner } from '@/services/firmService'
import { createMatter } from '@/services/matterService'
import { createMemo, getMemo } from '@/services/memoService'
import {
  buildPlaceholderMap,
  deriveExportFilename,
  generateWordBuffer,
  generateMemosExcel,
} from '@/services/exportService'
import { listMemos } from '@/services/memoService'
import ExcelJS from 'exceljs'

let db: Database.Database
beforeAll(() => { db = createSchemaDb() })
afterAll(() => db.close())
beforeEach(() => truncateAll(db))

const templateBuffer = fs.readFileSync(path.join(__dirname, '../fixtures/template.docx'))

function seedMemo(matterName = 'Varian Arbitration') {
  const f = createFirm(db, 'Firm')
  const p = addPartner(db, f.id, 'P')
  const m = createMatter(db, { name: matterName, firmId: f.id, partnerId: p.id })
  return createMemo(db, {
    date: '2026-07-15', matterId: m.id, addresseeLine1: 'Acme Legal',
    numAppearances: 2, feesPerAppearance: 5000, numConferences: 1,
    feesPerConference: 3000, feesMiscDrafting: 1000,
  })
}

describe('exportService — placeholder map', () => {
  it('excludes internal fields (firm/partner/payment lines)', () => {
    const memo = seedMemo()
    const map = buildPlaceholderMap(memo)
    const keys = Object.keys(map)
    expect(keys).not.toContain('LINE_3_FIRM')
    expect(keys).not.toContain('LINE_4_PARTNER')
    expect(keys.some((k) => /LINE_(25|26|27|28|29|30)/.test(k))).toBe(false)
    expect(map.LINE_24_TOTAL_FEES).toBe('14,000')
    expect(map.LINE_24A_TOTAL_FEES_WORDS).toMatch(/^Rupees .* Only$/)
  })

  it('sets SHOW_* section flags from which fee lines carry data', () => {
    const f = createFirm(db, 'Firm')
    const p = addPartner(db, f.id, 'P')
    const m = createMatter(db, { name: 'Only Appearances', firmId: f.id, partnerId: p.id })
    // A memo with only Appearances data: Conferences and Misc are empty.
    const memo = createMemo(db, {
      date: '2026-07-15', matterId: m.id, addresseeLine1: 'A',
      numAppearances: 2, feesPerAppearance: 5000,
      numConferences: 0, feesPerConference: 0, feesMiscDrafting: 0,
    })
    const map = buildPlaceholderMap(memo)
    expect(map.SHOW_APPEARANCES).toBe(true)
    expect(map.SHOW_CONFERENCES).toBe(false)
    expect(map.SHOW_MISC).toBe(false)
  })

  it('blank optional fields map to empty strings', () => {
    const memo = seedMemo()
    const map = buildPlaceholderMap(memo)
    expect(map.LINE_11_PLAINTIFF).toBe('')
  })
})

describe('exportService — filename', () => {
  it('matches the required format', () => {
    const memo = seedMemo('Varian Arbitration')
    // seedMemo creates the first memo of FY 2026-27 → "2026-27/1".
    expect(deriveExportFilename(memo, 'docx')).toBe('Memo 1 of 2026-27 Ziyad Madon (Varian Arbitration).docx')
  })

  it('sanitises slashes in matter names', () => {
    const memo = seedMemo('A/B Matter')
    expect(deriveExportFilename(memo, 'docx')).toBe('Memo 1 of 2026-27 Ziyad Madon (A-B Matter).docx')
  })
})

describe('exportService — short tags & plurals', () => {
  it('exposes every long tag under a short alias too', () => {
    const map = buildPlaceholderMap(seedMemo())
    expect(map.L1).toBe(map.LINE_1_DATE)
    expect(map.L2).toBe(map.LINE_2_MEMO_NUMBER)
    expect(map.L24).toBe(map.LINE_24_TOTAL_FEES)
    expect(map.L24A).toBe(map.LINE_24A_TOTAL_FEES_WORDS)
    expect(map.IF_APP).toBe(map.SHOW_APPEARANCES)
    expect(map.IF_CONF).toBe(map.SHOW_CONFERENCES)
  })
  it('prints Appearance (singular) for 1 and Appearances (plural) otherwise', () => {
    const base = seedMemo()
    expect(buildPlaceholderMap({ ...base, numAppearances: 1 }).L16W).toBe('1 Appearance')
    expect(buildPlaceholderMap({ ...base, numAppearances: 2 }).L16W).toBe('2 Appearances')
    expect(buildPlaceholderMap({ ...base, numAppearances: 0 }).L16W).toBe('')
  })
  it('prints Conference / Conferences the same way', () => {
    const base = seedMemo()
    expect(buildPlaceholderMap({ ...base, numConferences: 1 }).L19W).toBe('1 Conference')
    expect(buildPlaceholderMap({ ...base, numConferences: 3 }).L19W).toBe('3 Conferences')
  })
  it('uses the matter short name when set, else the full name', () => {
    const memo = seedMemo('Brandwings India Pvt Ltd')
    expect(buildPlaceholderMap(memo).L7).toBe('Brandwings India Pvt Ltd')
    const short = { ...memo, matterShortName: 'Brandwings' }
    expect(buildPlaceholderMap(short).L7).toBe('Brandwings')
    expect(deriveExportFilename(short, 'docx')).toBe('Memo 1 of 2026-27 Ziyad Madon (Brandwings).docx')
  })
  it('formats dates with dots in the Word export', () => {
    expect(buildPlaceholderMap(seedMemo()).L1).toMatch(/^\d{2}\.\d{2}\.\d{4}$/)
  })
})

describe('exportService — Word buffer', () => {
  it('renders a valid .docx containing substituted values', () => {
    const memo = seedMemo()
    const buf = generateWordBuffer(templateBuffer, memo)
    expect(buf.length).toBeGreaterThan(0)
    const zip = new PizZip(buf)
    const xml = zip.file('word/document.xml')!.asText()
    expect(xml).toContain('2026-27/1')
    expect(xml).toContain('Varian Arbitration')
    expect(xml).not.toContain('{{LINE_')
  })

  it('throws INVALID_TEMPLATE on a non-zip buffer', () => {
    const memo = seedMemo()
    try {
      generateWordBuffer(Buffer.from('not a docx'), memo)
      throw new Error('should have thrown')
    } catch (e) {
      expect((e as { code?: string }).code).toBe('INVALID_TEMPLATE')
    }
  })
})

describe('exportService — Memos Excel', () => {
  it('produces a workbook with a header row and one data row per memo', async () => {
    seedMemo()
    const rows = listMemos(db, {})
    const buf = await generateMemosExcel(rows)
    const wb = new ExcelJS.Workbook()
    await wb.xlsx.load(buf)
    const ws = wb.getWorksheet('Memos')!
    expect(ws.getRow(1).getCell(1).value).toBe('Memo Number')
    expect(ws.rowCount).toBe(2) // header + 1
  })
})
