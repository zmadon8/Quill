/**
 * electron/ipc/outstanding.ts — IPC handlers for Outstanding Memos + Excel export.
 */
import { ipcMain } from 'electron'
import { db } from '@/db/client'
import type { OutstandingFilter, OutstandingSort } from '@/types/ipc'
import { listOutstanding, listOutstandingByFirm, listOutstandingScope } from '@/services/outstandingService'
import { generateOutstandingExcel, generateOutstandingByFirmExcel } from '@/services/exportService'
import { saveBufferWithDialog } from './exportDialog'
import { wrap, wrapAsync } from './envelope'


export function registerOutstandingHandlers(): void {
  ipcMain.handle('outstanding:list', (_e, filter: OutstandingFilter) =>
    wrap(() => listOutstanding(db, filter)),
  )
  ipcMain.handle(
    'outstanding:listByFirm',
    (_e, filter: OutstandingFilter, sort: OutstandingSort) =>
      wrap(() => listOutstandingByFirm(db, filter, sort)),
  )
  ipcMain.handle('outstanding:scope', (_e, filter: OutstandingFilter) =>
    wrap(() => listOutstandingScope(db, filter)),
  )
  ipcMain.handle('outstanding:exportExcel', (_e, filter: OutstandingFilter, fileName?: string, visibleKeys?: string[]) =>
    wrapAsync(async () => {
      const groups = listOutstanding(db, filter)
      const buffer = await generateOutstandingExcel(groups, visibleKeys)
      const defaultName = fileName && fileName.trim() ? fileName : 'All Outstanding Memos.xlsx'
      const path = await saveBufferWithDialog(defaultName, buffer, [
        { name: 'Excel Workbook', extensions: ['xlsx'] },
      ])
      return { saved: path !== null, path }
    }),
  )
  ipcMain.handle(
    'outstanding:exportByFirmExcel',
    (_e, filter: OutstandingFilter, sort: OutstandingSort) =>
      wrapAsync(async () => {
        const summary = listOutstandingByFirm(db, filter, sort)
        const buffer = await generateOutstandingByFirmExcel(summary)
        const path = await saveBufferWithDialog('Outstanding — Firm Summary.xlsx', buffer, [
          { name: 'Excel Workbook', extensions: ['xlsx'] },
        ])
        return { saved: path !== null, path }
      }),
  )
}
