/**
 * electron/ipc/feebook.ts — IPC handlers for the Feebook view + Excel export.
 */
import { ipcMain } from 'electron'
import { db } from '@/db/client'
import type { FeebookFilter } from '@/types/ipc'
import { listFeebook } from '@/services/feebookService'
import { generateFeebookExcel } from '@/services/exportService'
import { saveBufferWithDialog } from './exportDialog'
import { wrap, wrapAsync } from './envelope'


export function registerFeebookHandlers(): void {
  ipcMain.handle('feebook:list', (_e, filter: FeebookFilter) => wrap(() => listFeebook(db, filter)))
  ipcMain.handle('feebook:exportExcel', (_e, filter: FeebookFilter, visibleKeys?: string[]) =>
    wrapAsync(async () => {
      const rows = listFeebook(db, filter)
      const buffer = await generateFeebookExcel(rows, visibleKeys)
      const path = await saveBufferWithDialog(`Feebook ${filter.financialYear ?? 'All Years'}.xlsx`, buffer, [
        { name: 'Excel Workbook', extensions: ['xlsx'] },
      ])
      return { saved: path !== null, path }
    }),
  )
}
