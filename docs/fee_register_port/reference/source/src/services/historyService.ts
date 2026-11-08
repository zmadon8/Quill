/**
 * historyService.ts
 *
 * App-wide Undo / Redo built on full-database snapshots.
 *
 * Every data-mutating IPC call records a snapshot of the current database state
 * before it runs (see electron/ipc/withHistory.ts). Undo restores the most
 * recent snapshot; redo re-applies one that was undone. Because a snapshot
 * captures every row of every app table, undo/redo works uniformly across all
 * entities with no per-command bookkeeping, and — crucially — can never leave
 * the database in a referentially inconsistent state (the whole graph is
 * restored together).
 *
 * We deliberately keep the WHOLE-DATABASE snapshot rather than per-table diffs:
 * benchmarking at 25,000 memos + 24,000 payments showed a full capture takes
 * ~0.25s and restore is a single transaction, which is comfortably interactive.
 * A partial (per-table) scheme is far more error-prone because foreign keys
 * span tables — restoring a subset risks orphaning rows in tables outside the
 * subset. Correctness wins here; the cost is acceptable at the target scale.
 *
 * The stacks are bounded (MAX_DEPTH) to cap memory. Snapshots live in the main
 * process for the session and are not persisted.
 */

import type Database from 'better-sqlite3'

/** App tables captured by a snapshot, in dependency order (parents first). */
const TABLES = [
  'settings',
  'firms',
  'partners',
  'bank_accounts',
  'matters',
  'memos',
  'memo_number_sequences',
  'payments',
  'payment_allocations',
  'period_adjustments',
  'saved_views',
] as const

/** Order to DELETE rows in (children first) to respect FK references. */
const DELETE_ORDER = [...TABLES].reverse()

type Row = Record<string, unknown>
export type Snapshot = Record<string, Row[]>

// Bounded undo depth. Each entry is a full-database snapshot, so this also caps
// the memory the history can hold.
const MAX_DEPTH = 20

/** A labelled snapshot plus a human description of the action it precedes. */
interface Entry {
  label: string
  snapshot: Snapshot
}

// Per-database history. Keyed by the Database instance so tests get isolation.
interface History {
  undo: Entry[]
  redo: Entry[]
}
const histories = new WeakMap<Database.Database, History>()

function hist(db: Database.Database): History {
  let h = histories.get(db)
  if (!h) {
    h = { undo: [], redo: [] }
    histories.set(db, h)
  }
  return h
}

/** Captures the full current state of every app table. */
export function captureSnapshot(db: Database.Database): Snapshot {
  const snap: Snapshot = {}
  for (const t of TABLES) {
    snap[t] = db.prepare(`SELECT * FROM ${t}`).all() as Row[]
  }
  return snap
}

/** Restores a snapshot: wipe every app table, then bulk re-insert, atomically. */
export function restoreSnapshot(db: Database.Database, snap: Snapshot): void {
  const tx = db.transaction(() => {
    for (const t of DELETE_ORDER) db.prepare(`DELETE FROM ${t}`).run()
    for (const t of TABLES) {
      const rows = snap[t] ?? []
      for (const row of rows) {
        const cols = Object.keys(row)
        if (cols.length === 0) continue
        const placeholders = cols.map((c) => `@${c}`).join(', ')
        db.prepare(
          `INSERT INTO ${t} (${cols.map((c) => `"${c}"`).join(', ')}) VALUES (${placeholders})`,
        ).run(row)
      }
    }
  })
  tx()
}

/**
 * Commits a PRE-CAPTURED snapshot onto the undo stack (used by the IPC mutation
 * wrapper, which snapshots before the mutation and only commits if it
 * succeeded). Clears the redo stack, since a fresh action invalidates the
 * undone-but-not-redone future.
 */
export function pushRecorded(db: Database.Database, label: string, snapshot: Snapshot): void {
  const h = hist(db)
  h.undo.push({ label, snapshot })
  if (h.undo.length > MAX_DEPTH) h.undo.shift()
  h.redo = []
}

/** Records a snapshot of the CURRENT state as an undo entry (snapshot now). */
export function recordSnapshot(db: Database.Database, label: string): void {
  pushRecorded(db, label, captureSnapshot(db))
}

export interface HistoryStateInternal {
  canUndo: boolean
  canRedo: boolean
  undoLabel: string | null
  redoLabel: string | null
  /** Undo action labels, most-recent (next to undo) first. */
  undoStack: string[]
  /** Redo action labels, most-recent (next to redo) first. */
  redoStack: string[]
}

/** Current undo/redo availability + the next action labels (for the UI). */
export function historyState(db: Database.Database): HistoryStateInternal {
  const h = hist(db)
  return {
    canUndo: h.undo.length > 0,
    canRedo: h.redo.length > 0,
    undoLabel: h.undo.length ? h.undo[h.undo.length - 1].label : null,
    redoLabel: h.redo.length ? h.redo[h.redo.length - 1].label : null,
    // Reverse so index 0 is the action that would be undone/redone next.
    undoStack: h.undo.map((e) => e.label).reverse(),
    redoStack: h.redo.map((e) => e.label).reverse(),
  }
}

/**
 * Undo: snapshot the current state onto the redo stack, then restore the most
 * recent undo snapshot. No-op if nothing to undo.
 */
export function undo(db: Database.Database): HistoryStateInternal {
  const h = hist(db)
  const entry = h.undo.pop()
  if (!entry) return historyState(db)
  h.redo.push({ label: entry.label, snapshot: captureSnapshot(db) })
  if (h.redo.length > MAX_DEPTH) h.redo.shift()
  restoreSnapshot(db, entry.snapshot)
  return historyState(db)
}

/**
 * Redo: snapshot the current state onto the undo stack, then restore the most
 * recent redo snapshot. No-op if nothing to redo.
 */
export function redo(db: Database.Database): HistoryStateInternal {
  const h = hist(db)
  const entry = h.redo.pop()
  if (!entry) return historyState(db)
  h.undo.push({ label: entry.label, snapshot: captureSnapshot(db) })
  if (h.undo.length > MAX_DEPTH) h.undo.shift()
  restoreSnapshot(db, entry.snapshot)
  return historyState(db)
}

/** Clears both stacks (e.g. after Clear All Data or Restore). */
export function clearHistory(db: Database.Database): void {
  const h = hist(db)
  h.undo = []
  h.redo = []
}
