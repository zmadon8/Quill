import { app, BrowserWindow, ipcMain } from 'electron'
import { join } from 'path'

import { registerFirmHandlers } from './ipc/firms'
import { registerMatterHandlers } from './ipc/matters'
import { registerMemoHandlers } from './ipc/memos'
import { registerPaymentHandlers } from './ipc/payments'
import { registerFeebookHandlers } from './ipc/feebook'
import { registerOutstandingHandlers } from './ipc/outstanding'
import { registerStatisticsHandlers } from './ipc/statistics'
import { registerSettingsHandlers } from './ipc/settings'
import { registerBackupHandlers } from './ipc/backup'
import { registerDashboardHandlers } from './ipc/dashboard'
import { registerImportHandlers } from './ipc/import'
import { registerHistoryHandlers } from './ipc/history'
import { startAutoBackup, writeCloseBackup } from './autoBackup'
import { installIpcTiming, getMetrics } from './diagnostics'
import { db } from '@/db/client'
import { getSettings } from '@/services/settingsService'

function registerAllHandlers(): void {
  registerFirmHandlers()
  registerMatterHandlers()
  registerMemoHandlers()
  registerPaymentHandlers()
  registerFeebookHandlers()
  registerOutstandingHandlers()
  registerStatisticsHandlers()
  registerSettingsHandlers()
  registerBackupHandlers()
  registerDashboardHandlers()
  registerImportHandlers()
  registerHistoryHandlers()

  // Expose the app version (for the Settings → About section).
  ipcMain.handle('system:appVersion', () => ({ ok: true, data: app.getVersion() }))

  // Window zoom (Settings → Zoom, ⌘+ / ⌘-).
  ipcMain.handle('system:setZoom', (e, factor: number) => {
    const f = Math.min(2, Math.max(0.6, Number(factor) || 1))
    BrowserWindow.fromWebContents(e.sender)?.webContents.setZoomFactor(f)
    return { ok: true, data: f }
  })

  // Resource usage snapshot for the Diagnostics card.
  ipcMain.handle('system:metrics', () => {
    try {
      return { ok: true, data: getMetrics() }
    } catch (err) {
      return { ok: false, error: 'UNKNOWN', details: (err as Error).message }
    }
  })
}

function createWindow(): void {
  const mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    show: false,
    webPreferences: {
      preload: join(__dirname, '../preload/index.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  })

  mainWindow.on('ready-to-show', () => mainWindow.show())
  // Apply the saved zoom once the page has loaded.
  mainWindow.webContents.on('did-finish-load', () => {
    try {
      mainWindow.webContents.setZoomFactor(getSettings(db).zoomFactor || 1)
    } catch {
      /* keep default zoom */
    }
  })

  if (process.env.ELECTRON_RENDERER_URL) {
    mainWindow.loadURL(process.env.ELECTRON_RENDERER_URL)
  } else {
    mainWindow.loadFile(join(__dirname, '../renderer/index.html'))
  }
}

app.whenReady().then(() => {
  // Importing the db client lazily here ensures the DB file is created under
  // the Electron userData path (not the dev fallback) in the packaged app.
  installIpcTiming() // record per-call timings for Settings → Diagnostics
  registerAllHandlers()
  startAutoBackup()
  createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})

// On quit, write a single self-overwriting "last close" backup (separate from
// the dated periodic backups). We defer the quit once to let the async write
// finish, guarded by a flag so we don't loop.
let closeBackupDone = false
app.on('before-quit', (event) => {
  if (closeBackupDone) return
  event.preventDefault()
  void writeCloseBackup().finally(() => {
    closeBackupDone = true
    app.quit()
  })
})
