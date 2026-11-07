/**
 * electron/ipc/firms.ts
 *
 * Registers IPC handlers for Firms and Partners. Each handler wraps a pure
 * firmService function using the singleton database, catches errors, and
 * returns a consistent IPCResponse envelope.
 */

import { ipcMain } from 'electron'
import { db } from '@/db/client'
import type { FirmFilter, FirmStatus } from '@/types/ipc'
import {
  createFirm,
  listFirms,
  getFirm,
  updateFirm,
  setFirmStatus,
  addPartner,
  updatePartner,
  removePartner,
} from '@/services/firmService'
import { mutate } from './withHistory'
import { wrap } from './envelope'


export function registerFirmHandlers(): void {
  ipcMain.handle('firms:create', (_e, name: string) => mutate('Create firm', () => createFirm(db, name)))
  ipcMain.handle('firms:list', (_e, filter: FirmFilter) => wrap(() => listFirms(db, filter)))
  ipcMain.handle('firms:get', (_e, id: number) => wrap(() => getFirm(db, id)))
  ipcMain.handle('firms:update', (_e, id: number, data: { name?: string }) =>
    mutate('Edit firm', () => updateFirm(db, id, data)),
  )
  ipcMain.handle('firms:setStatus', (_e, id: number, status: FirmStatus) =>
    mutate(status === 'archived' ? 'Archive firm' : 'Unarchive firm', () => setFirmStatus(db, id, status)),
  )
  ipcMain.handle('firms:addPartner', (_e, firmId: number, name: string) =>
    mutate('Add partner', () => addPartner(db, firmId, name)),
  )
  ipcMain.handle('firms:updatePartner', (_e, firmId: number, partnerId: number, name: string) =>
    mutate('Edit partner', () => updatePartner(db, firmId, partnerId, name)),
  )
  ipcMain.handle('firms:removePartner', (_e, firmId: number, partnerId: number) =>
    mutate('Remove partner', () => removePartner(db, firmId, partnerId)),
  )
}
