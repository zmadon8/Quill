import { describe, it, expect, beforeEach, beforeAll, afterAll } from 'vitest'
import type Database from 'better-sqlite3'
import { createSchemaDb, truncateAll } from '../helpers/testDb'
import { createFirm } from '@/services/firmService'
import { listFirms } from '@/services/firmService'
import {
  recordSnapshot,
  undo,
  redo,
  historyState,
  clearHistory,
} from '@/services/historyService'

let db: Database.Database
beforeAll(() => { db = createSchemaDb() })
afterAll(() => db.close())
beforeEach(() => { truncateAll(db); clearHistory(db) })

describe('historyService — undo/redo', () => {
  it('undo restores the state captured before a mutation; redo re-applies it', () => {
    createFirm(db, 'First')
    expect(listFirms(db, 'all')).toHaveLength(1)

    // Snapshot the current state, then make a change.
    recordSnapshot(db, 'Create firm')
    createFirm(db, 'Second')
    expect(listFirms(db, 'all')).toHaveLength(2)

    // Undo → back to one firm.
    const afterUndo = undo(db)
    expect(afterUndo.canUndo).toBe(false)
    expect(afterUndo.canRedo).toBe(true)
    expect(listFirms(db, 'all').map((f) => f.name)).toEqual(['First'])

    // Redo → the second firm comes back.
    const afterRedo = redo(db)
    expect(afterRedo.canRedo).toBe(false)
    expect(listFirms(db, 'all')).toHaveLength(2)
  })

  it('a new action after undo clears the redo stack', () => {
    createFirm(db, 'A')
    recordSnapshot(db, 'Create B')
    createFirm(db, 'B')
    undo(db) // back to just A; redo available
    expect(historyState(db).canRedo).toBe(true)

    // A fresh recorded action should discard the redo future.
    recordSnapshot(db, 'Create C')
    createFirm(db, 'C')
    expect(historyState(db).canRedo).toBe(false)
    const names = listFirms(db, 'all').map((f) => f.name).sort()
    expect(names).toEqual(['A', 'C'])
  })

  it('undo/redo are no-ops when the stacks are empty', () => {
    expect(undo(db).canUndo).toBe(false)
    expect(redo(db).canRedo).toBe(false)
  })

  it('a full-database snapshot restores related tables together (FK-safe)', () => {
    // Creating a firm also creates its default partner; undo must roll back
    // both so no partner is orphaned.
    createFirm(db, 'A')
    recordSnapshot(db, 'Create firm B')
    createFirm(db, 'B')
    expect(db.prepare('SELECT COUNT(*) AS c FROM firms').get()).toEqual({ c: 2 })

    undo(db)
    expect(db.prepare('SELECT COUNT(*) AS c FROM firms').get()).toEqual({ c: 1 })
    // The partner created alongside firm B is gone too (no orphan).
    const partners = db.prepare('SELECT firm_id FROM partners').all() as { firm_id: number }[]
    const firmIds = new Set((db.prepare('SELECT id FROM firms').all() as { id: number }[]).map((f) => f.id))
    expect(partners.every((p) => firmIds.has(p.firm_id))).toBe(true)
  })
})
