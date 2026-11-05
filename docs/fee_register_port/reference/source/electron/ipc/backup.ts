/**
 * electron/ipc/backup.ts — IPC handler for full data backup to Excel.
 */
import { ipcMain } from 'electron'
import { db } from '@/db/client'
import { generateBackupBuffer } from '@/services/backupService'
import { saveBufferWithDialog } from './exportDialog'
import { wrapAsync } from './envelope'


export function registerBackupHandlers(): void {
  ipcMain.handle('backup:export', () =>
    wrapAsync(async () => {
      const buffer = await generateBackupBuffer(db)
      const path = await saveBufferWithDialog('fee-register-backup.xlsx', buffer, [
        { name: 'Excel Workbook', extensions: ['xlsx'] },
      ])
      return { saved: path !== null, path }
    }),
  )
}
