/**
 * electron/ipc/matters.ts
 *
 * Registers IPC handlers for Matters, wrapping the pure matterService using the
 * singleton database and returning a consistent IPCResponse envelope.
 */

import { ipcMain } from 'electron'
import { db } from '@/db/client'
import type { MatterInput, MatterUpdateInput, MatterFilter } from '@/types/ipc'
import {
  createMatter,
  updateMatter,
  listMatters,
  getMatter,
  archiveMatter,
  unarchiveMatter,
} from '@/services/matterService'
import { wrap } from './envelope'
import { mutate } from './withHistory'

export function registerMatterHandlers(): void {
  ipcMain.handle('matters:create', (_e, input: MatterInput) =>
    mutate('Create matter', () => createMatter(db, input)),
  )
  ipcMain.handle('matters:update', (_e, id: number, input: MatterUpdateInput) =>
    mutate('Edit matter', () => updateMatter(db, id, input)),
  )
  ipcMain.handle('matters:list', (_e, filter: MatterFilter, firmId?: number) =>
    wrap(() => listMatters(db, filter, firmId)),
  )
  ipcMain.handle('matters:get', (_e, id: number) => wrap(() => getMatter(db, id)))
  ipcMain.handle('matters:archive', (_e, id: number) =>
    mutate('Archive matter', () => archiveMatter(db, id)),
  )
  ipcMain.handle('matters:unarchive', (_e, id: number) =>
    mutate('Unarchive matter', () => unarchiveMatter(db, id)),
  )
}
