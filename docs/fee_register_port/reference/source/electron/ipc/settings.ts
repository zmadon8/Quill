/**
 * electron/ipc/settings.ts — IPC handlers for Settings and Bank Accounts.
 *
 * uploadTemplate copies the chosen .docx into the app-data directory and stores
 * its path. restoreFromExcel is a stub wired to backupService in Task 11.
 */
import { ipcMain } from 'electron'
import path from 'path'
import fs from 'fs'
import { db } from '@/db/client'
import { AppError } from '@/types/ipc'
import type { SettingsInput } from '@/types/ipc'
import { restoreFromBuffer, generateBackupBuffer, clearAllData } from '@/services/backupService'
import { clearHistory } from '@/services/historyService'
import { openFileWithDialog, saveBufferWithDialog } from './exportDialog'
import { dialog, BrowserWindow } from 'electron'
import {
  getSettings,
  updateSettings,
  setWordTemplatePath,
  listBankAccounts,
  addBankAccount,
  updateBankAccount,
  deleteBankAccount,
} from '@/services/settingsService'
import { wrap, wrapAsync } from './envelope'



function resolveUserDataDir(): string {
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { app } = require('electron') as typeof import('electron')
    if (app && typeof app.getPath === 'function') return app.getPath('userData')
  } catch {
    /* not in electron */
  }
  const home = process.env.HOME ?? process.env.USERPROFILE ?? '.'
  return path.join(home, '.fee-register-dev')
}

export function registerSettingsHandlers(): void {
  ipcMain.handle('settings:get', () => wrap(() => getSettings(db)))
  ipcMain.handle('settings:update', (_e, input: SettingsInput) => wrap(() => updateSettings(db, input)))

  // Backs up all data (user chooses where), then clears everything. The clear
  // only runs if the backup was actually saved — so data is never lost.
  ipcMain.handle('settings:clearAllData', () =>
    wrapAsync(async () => {
      const buffer = await generateBackupBuffer(db)
      const stamp = new Date().toISOString().slice(0, 10)
      const savedPath = await saveBufferWithDialog(`fee-register-backup-before-reset-${stamp}.xlsx`, buffer, [
        { name: 'Excel Workbook', extensions: ['xlsx'] },
      ])
      if (!savedPath) {
        // User cancelled the backup save — do NOT clear.
        return { cleared: false, backupPath: null }
      }
      clearAllData(db)
      clearHistory(db) // snapshots from before the wipe are no longer meaningful
      return { cleared: true, backupPath: savedPath }
    }),
  )

  // Opens a folder picker for the automatic-backup destination and stores it.
  ipcMain.handle('settings:pickBackupDir', () =>
    wrapAsync(async () => {
      const win = BrowserWindow.getFocusedWindow() ?? BrowserWindow.getAllWindows()[0] ?? undefined
      const res = await dialog.showOpenDialog(win!, { properties: ['openDirectory', 'createDirectory'] })
      if (res.canceled || res.filePaths.length === 0) {
        return { chosen: false, settings: getSettings(db) }
      }
      return { chosen: true, settings: updateSettings(db, { autoBackupDir: res.filePaths[0] }) }
    }),
  )

  // Opens a folder picker and just RETURNS the chosen path (does not save it);
  // used by the per-job backup folder choosers.
  ipcMain.handle('settings:pickFolder', () =>
    wrapAsync(async () => {
      const win = BrowserWindow.getFocusedWindow() ?? BrowserWindow.getAllWindows()[0] ?? undefined
      const res = await dialog.showOpenDialog(win!, { properties: ['openDirectory', 'createDirectory'] })
      return res.canceled || res.filePaths.length === 0 ? null : res.filePaths[0]
    }),
  )

  ipcMain.handle('settings:addBankAccount', (_e, name: string) => wrap(() => addBankAccount(db, name)))
  ipcMain.handle('settings:updateBankAccount', (_e, id: number, name: string) =>
    wrap(() => updateBankAccount(db, id, name)),
  )
  ipcMain.handle('settings:deleteBankAccount', (_e, id: number) => wrap(() => deleteBankAccount(db, id)))
  ipcMain.handle('settings:listBankAccounts', () => wrap(() => listBankAccounts(db)))

  ipcMain.handle('settings:uploadTemplate', (_e, sourcePath: string) =>
    wrap(() => {
      if (!sourcePath || !sourcePath.toLowerCase().endsWith('.docx')) {
        throw new AppError('INVALID_TEMPLATE', 'Template must be a .docx file')
      }
      const stat = fs.statSync(sourcePath)
      if (stat.size > 10 * 1024 * 1024) {
        throw new AppError('INVALID_TEMPLATE', 'Template must be at most 10 MB')
      }
      const destDir = path.join(resolveUserDataDir(), 'templates')
      fs.mkdirSync(destDir, { recursive: true })
      const dest = path.join(destDir, 'memo-template.docx')
      fs.copyFileSync(sourcePath, dest)
      return setWordTemplatePath(db, dest)
    }),
  )

  // Opens a file dialog in the main process, then uploads the chosen template.
  ipcMain.handle('settings:pickAndUploadTemplate', () =>
    wrapAsync(async () => {
      const picked = await openFileWithDialog([{ name: 'Word Document', extensions: ['docx'] }])
      if (!picked) return { uploaded: false, settings: getSettings(db) }
      if (!picked.toLowerCase().endsWith('.docx')) {
        throw new AppError('INVALID_TEMPLATE', 'Template must be a .docx file')
      }
      const stat = fs.statSync(picked)
      if (stat.size > 10 * 1024 * 1024) {
        throw new AppError('INVALID_TEMPLATE', 'Template must be at most 10 MB')
      }
      const destDir = path.join(resolveUserDataDir(), 'templates')
      fs.mkdirSync(destDir, { recursive: true })
      const dest = path.join(destDir, 'memo-template.docx')
      fs.copyFileSync(picked, dest)
      return { uploaded: true, settings: setWordTemplatePath(db, dest) }
    }),
  )

  // Opens a file dialog, confirms, then restores all data from the chosen backup.
  ipcMain.handle('settings:pickAndRestore', () =>
    wrapAsync(async () => {
      const picked = await openFileWithDialog([{ name: 'Excel Workbook', extensions: ['xlsx'] }])
      if (!picked) return { restored: false, rowsImported: 0 }
      const { response } = await dialog.showMessageBox(
        BrowserWindow.getFocusedWindow() ?? BrowserWindow.getAllWindows()[0]!,
        {
          type: 'warning',
          buttons: ['Cancel', 'Replace all data'],
          defaultId: 0,
          cancelId: 0,
          message: 'Restore from backup?',
          detail: 'This replaces ALL existing data in the application. This cannot be undone.',
        },
      )
      if (response !== 1) return { restored: false, rowsImported: 0 }
      const buffer = fs.readFileSync(picked)
      const result = await restoreFromBuffer(db, buffer)
      clearHistory(db)
      return { restored: true, rowsImported: result.rowsImported }
    }),
  )

  ipcMain.handle('settings:restoreFromExcel', (_e, filePath: string) =>
    wrapAsync(async () => {
      if (!filePath || !fs.existsSync(filePath)) {
        throw new AppError('RESTORE_FAILED', 'Backup file not found')
      }
      // Confirm the destructive operation before proceeding.
      const win = BrowserWindow.getFocusedWindow() ?? BrowserWindow.getAllWindows()[0] ?? undefined
      const { response } = await dialog.showMessageBox(win!, {
        type: 'warning',
        buttons: ['Cancel', 'Replace all data'],
        defaultId: 0,
        cancelId: 0,
        message: 'Restore from backup?',
        detail: 'This replaces ALL existing data in the application. This cannot be undone.',
      })
      if (response !== 1) return { restored: false, rowsImported: 0 }
      const buffer = fs.readFileSync(filePath)
      const result = await restoreFromBuffer(db, buffer)
      clearHistory(db)
      return { restored: true, rowsImported: result.rowsImported }
    }),
  )
}
