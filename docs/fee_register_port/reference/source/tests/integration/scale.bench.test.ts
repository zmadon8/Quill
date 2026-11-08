/**
 * scale.bench.test.ts — a scale/performance smoke test.
 *
 * Seeds a large, realistic dataset (tens of thousands of memos + payments) and
 * times the hot read paths so we can confirm the app stays responsive as the
 * data grows over many years. Not a strict assertion suite — it logs timings
 * and only fails if a path is pathologically slow (safety ceiling), so index
 * regressions get caught without being flaky on slower machines.
 *
 * Run on demand:  npx vitest run --config vitest.bench.config.ts
 */
import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import type Database from 'better-sqlite3'
import { createSchemaDb } from '../helpers/testDb'
import { createFirm, addPartner } from '@/services/firmService'
import { createMatter } from '@/services/matterService'
import { createMemo } from '@/services/memoService'
import { addPaymentToMemo } from '@/services/paymentService'
import { listMemos } from '@/services/memoService'
import { listOutstanding, listOutstandingByFirm } from '@/services/outstandingService'
import { listFeebook } from '@/services/feebookService'
import { getPeriodStatistics, getPivot } from '@/services/statisticsService'
import { captureSnapshot } from '@/services/historyService'

// Dataset size. ~40 firms, ~1,200 matters, 25,000 memos, ~21,000 payments.
const N_FIRMS = 40
const MATTERS_PER_FIRM = 30
const N_MEMOS = 25_000
const FYS = ['2019-20', '2020-21', '2021-22', '2022-23', '2023-24', '2024-25', '2025-26', '2026-27']
// A memo date within a given FY (FY starts in April). Spread across months.
function dateInFy(fy: string, i: number): string {
  const startYear = Number(fy.slice(0, 4))
  const monthOrder = [4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3]
  const m = monthOrder[i % 12]
  const y = m >= 4 ? startYear : startYear + 1
  const day = String((i % 27) + 1).padStart(2, '0')
  return `${y}-${String(m).padStart(2, '0')}-${day}`
}

let db: Database.Database
const timings: Record<string, number> = {}

function time<T>(label: string, fn: () => T): T {
  const t0 = performance.now()
  const out = fn()
  timings[label] = Math.round(performance.now() - t0)
  return out
}

beforeAll(() => {
  db = createSchemaDb()
  // Seed firms/partners/matters.
  const matterIds: number[] = []
  const seed = db.transaction(() => {
    for (let f = 0; f < N_FIRMS; f++) {
      const firm = createFirm(db, `Firm ${f}`)
      const p = addPartner(db, firm.id, `Partner ${f}`)
      for (let mt = 0; mt < MATTERS_PER_FIRM; mt++) {
        const matter = createMatter(db, { name: `Matter ${f}-${mt}`, firmId: firm.id, partnerId: p.id })
        matterIds.push(matter.id)
      }
    }
  })
  const t0 = performance.now()
  seed()

  // Seed memos spread across FYs and matters; pay ~85% of them.
  const seedMemos = db.transaction(() => {
    for (let i = 0; i < N_MEMOS; i++) {
      const fy = FYS[i % FYS.length]
      const matterId = matterIds[i % matterIds.length]
      const memo = createMemo(db, {
        date: dateInFy(fy, i),
        matterId,
        addresseeLine1: 'A',
        numAppearances: (i % 4) + 1,
        feesPerAppearance: 5000,
        numConferences: i % 2,
        feesPerConference: 3000,
        feesMiscDrafting: 1000,
        numDrafts: i % 3,
      })
      if (i % 20 !== 0) {
        // ~95% get a payment (some partial, some full), with TDS on half.
        const gross = (i % 7 === 0) ? 5000 : 12000
        const tds = i % 2 === 0 ? Math.round(gross * 0.1) : 0
        addPaymentToMemo(db, memo.id, {
          amount: gross - tds,
          autoTds: false,
          tdsAmount: tds,
          dateOfPayment: dateInFy(fy, i),
        })
      }
    }
  })
  seedMemos()
  timings['seed total'] = Math.round(performance.now() - t0)
}, 600_000)

afterAll(() => {
  // Pretty-print the timing report.
  // eslint-disable-next-line no-console
  console.log('\n===== SCALE BENCHMARK (ms) =====')
  for (const [k, v] of Object.entries(timings)) {
    // eslint-disable-next-line no-console
    console.log(`  ${k.padEnd(38)} ${v} ms`)
  }
  db.close()
})

describe(`scale: ${N_MEMOS} memos`, () => {
  it('row counts are as expected', () => {
    const memos = (db.prepare('SELECT COUNT(*) AS c FROM memos').get() as { c: number }).c
    const pays = (db.prepare('SELECT COUNT(*) AS c FROM payments').get() as { c: number }).c
    expect(memos).toBe(N_MEMOS)
    expect(pays).toBeGreaterThan(20_000)
  })

  it('listMemos for one financial year is fast', () => {
    const rows = time('listMemos (1 FY)', () => listMemos(db, { financialYear: '2025-26' }))
    expect(rows.length).toBeGreaterThan(0)
    expect(timings['listMemos (1 FY)']).toBeLessThan(2000)
  })

  it('listMemos ALL years', () => {
    const rows = time('listMemos (all)', () => listMemos(db, {}))
    expect(rows.length).toBe(N_MEMOS)
    expect(timings['listMemos (all)']).toBeLessThan(6000)
  })

  it('outstanding (grouped + by firm) is fast', () => {
    time('listOutstanding (all)', () => listOutstanding(db, {}))
    time('listOutstandingByFirm', () => listOutstandingByFirm(db, {}, 'amount'))
    expect(timings['listOutstanding (all)']).toBeLessThan(6000)
    expect(timings['listOutstandingByFirm']).toBeLessThan(6000)
  })

  it('feebook (one FY) is fast', () => {
    const rows = time('listFeebook (1 FY)', () => listFeebook(db, { financialYear: '2025-26' }))
    expect(rows.length).toBeGreaterThan(0)
    expect(timings['listFeebook (1 FY)']).toBeLessThan(6000)
  })

  it('statistics period + pivot', () => {
    time('getPeriodStatistics (month)', () =>
      getPeriodStatistics(db, 'month', '2025-26', {}),
    )
    time('getPivot billed by firm×FY', () =>
      getPivot(db, { measure: 'billed', rowDim: 'firm', colDim: 'financialYear' }),
    )
    expect(timings['getPeriodStatistics (month)']).toBeLessThan(8000)
    expect(timings['getPivot billed by firm×FY']).toBeLessThan(8000)
  })

  it('undo/redo full-DB snapshot capture cost', () => {
    time('captureSnapshot (full DB)', () => captureSnapshot(db))
    // Logged for awareness; snapshot cost grows with the dataset.
    expect(timings['captureSnapshot (full DB)']).toBeLessThan(10_000)
  })
})
