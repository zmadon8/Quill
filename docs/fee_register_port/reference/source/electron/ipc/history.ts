/**
 * electron/ipc/history.ts — Undo / Redo IPC.
 *
 * `history:undo` / `history:redo` restore the previous / next whole-database
 * snapshot; `history:state` reports availability for the toolbar buttons.
 *
 * Snapshots are recorded by `recordMutation` (see ./withHistory), which the
 * mutating handlers call just before they change data.
 */
import { ipcMain } from 'electron'
import { db } from '@/db/client'
import type { HistoryState } from '@/types/ipc'
import { undo, redo, historyState } from '@/services/historyService'
import { wrap } from './envelope'

export function registerHistoryHandlers(): void {
  ipcMain.handle('history:state', () => wrap<HistoryState>(() => historyState(db)))
  ipcMain.handle('history:undo', () => wrap<HistoryState>(() => undo(db)))
  ipcMain.handle('history:redo', () => wrap<HistoryState>(() => redo(db)))
}
