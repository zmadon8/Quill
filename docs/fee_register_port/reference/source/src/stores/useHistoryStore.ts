import { create } from 'zustand'
import type { HistoryState } from '@/types/ipc'

interface HistoryStoreState extends HistoryState {
  /** Refreshes availability from the main process. */
  refresh: () => Promise<void>
  /** Performs an undo and reloads the renderer so every view reflects the restore. */
  undo: () => Promise<void>
  /** Performs a redo and reloads the renderer. */
  redo: () => Promise<void>
}

/**
 * Undo/Redo availability + actions. Because an undo/redo restores a full
 * database snapshot (any table may change), the renderer reloads afterwards so
 * every open view re-reads fresh data. Reloading is cheap for a local app and
 * avoids having to invalidate every store individually.
 */
export const useHistoryStore = create<HistoryStoreState>((set) => ({
  canUndo: false,
  canRedo: false,
  undoLabel: null,
  redoLabel: null,
  undoStack: [],
  redoStack: [],
  refresh: async () => {
    const res = await window.api.history.state()
    if (res.ok) set(res.data)
  },
  undo: async () => {
    const res = await window.api.history.undo()
    if (res.ok) {
      set(res.data)
      window.location.reload()
    }
  },
  redo: async () => {
    const res = await window.api.history.redo()
    if (res.ok) {
      set(res.data)
      window.location.reload()
    }
  },
}))
