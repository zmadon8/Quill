/**
 * searchService.ts
 *
 * Global search across firms, matters, and memos (by number, matter name, firm
 * name, and party names). Returns a small, ranked, typed result list for the
 * header search box. Case-insensitive substring match.
 */

import type Database from 'better-sqlite3'
import type { SearchResult } from '@/types/ipc'
import { prep } from '@/db/prep'

export function search(db: Database.Database, rawQuery: string, limit = 20): SearchResult[] {
  const q = (rawQuery ?? '').trim()
  if (q.length < 2) return []
  const like = `%${q.toLowerCase()}%`
  const results: SearchResult[] = []

  // Firms
  const firms = prep(
    db,
    `SELECT id, name FROM firms WHERE lower(name) LIKE ? ORDER BY lower(name) LIMIT ?`,
  ).all(like, limit) as Array<{ id: number; name: string }>
  for (const f of firms) {
    results.push({ kind: 'firm', id: f.id, title: f.name, subtitle: 'Firm' })
  }

  // Matters
  const matters = prep(
    db,
    `SELECT m.id, m.name, f.name AS firm_name
     FROM matters m JOIN firms f ON f.id = m.firm_id
     WHERE lower(m.name) LIKE ? ORDER BY lower(m.name) LIMIT ?`,
  ).all(like, limit) as Array<{ id: number; name: string; firm_name: string }>
  for (const m of matters) {
    results.push({ kind: 'matter', id: m.id, title: m.name, subtitle: `Matter · ${m.firm_name}` })
  }

  // Memos — match on number, matter name (joined), or party names.
  const memos = prep(
    db,
    `SELECT m.id, m.memo_number, m.is_draft, mt.name AS matter_name, f.name AS firm_name
     FROM memos m
     JOIN matters mt ON mt.id = m.matter_id
     JOIN firms f ON f.id = m.firm_id
     WHERE lower(COALESCE(m.memo_number, '')) LIKE ?
        OR lower(COALESCE(m.plaintiff_name, '')) LIKE ?
        OR lower(COALESCE(m.defendant_name, '')) LIKE ?
        OR lower(COALESCE(m.client, '')) LIKE ?
     ORDER BY m.financial_year DESC, m.seq DESC
     LIMIT ?`,
  ).all(like, like, like, like, limit) as Array<{
    id: number
    memo_number: string | null
    is_draft: number
    matter_name: string
    firm_name: string
  }>
  for (const m of memos) {
    results.push({
      kind: 'memo',
      id: m.id,
      title: m.memo_number ?? '(draft)',
      subtitle: `Memo · ${m.matter_name} · ${m.firm_name}`,
    })
  }

  return results.slice(0, limit)
}
