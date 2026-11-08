/**
 * electron/ipc/exportDialog.ts
 *
 * Shared helper: shows a Save dialog and writes a Buffer to the chosen path.
 * Returns the written path, or null if the user cancelled.
 */
import { dialog, BrowserWindow } from 'electron'
import fs from 'fs'

export async function saveBufferWithDialog(
  defaultName: string,
  buffer: Buffer,
  filters: Electron.FileFilter[],
): Promise<string | null> {
  const win = BrowserWindow.getFocusedWindow() ?? BrowserWindow.getAllWindows()[0] ?? undefined
  const result = await dialog.showSaveDialog(win!, {
    defaultPath: defaultName,
    filters,
  })
  if (result.canceled || !result.filePath) return null
  fs.writeFileSync(result.filePath, buffer)
  return result.filePath
}

export async function openFileWithDialog(filters: Electron.FileFilter[]): Promise<string | null> {
  const win = BrowserWindow.getFocusedWindow() ?? BrowserWindow.getAllWindows()[0] ?? undefined
  const result = await dialog.showOpenDialog(win!, {
    properties: ['openFile'],
    filters,
  })
  if (result.canceled || result.filePaths.length === 0) return null
  return result.filePaths[0]
}
