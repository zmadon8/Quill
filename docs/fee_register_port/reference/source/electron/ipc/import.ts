/**
 * electron/ipc/import.ts — IPC for the "Import Memos from a spreadsheet" flow.
 *
 * Two steps:
 *   import:inspect — user picks a file; we return its headers + a preview so the
 *                    renderer can show a column-mapping screen.
 *   import:run     — given the file path + mapping, parse all rows and import.
 *
 * Supports .xlsx (via ExcelJS) and .csv (simple parser). Additive import.
 */
import { ipcMain, dialog, BrowserWindow } from 'electron'
import fs from 'fs'
import ExcelJS from 'exceljs'
import { db } from '@/db/client'
import { AppError } from '@/types/ipc'
import type { ImportInspection, ImportMapping, ImportResult } from '@/types/ipc'
import { importMemos } from '@/services/importService'
import { recordSnapshot } from '@/services/historyService'
import { wrapAsync } from './envelope'

/** Minimal CSV parser handling quoted fields and embedded commas/newlines. */
function parseCsv(text: string): string[][] {
  const rows: string[][] = []
  let row: string[] = []
  let field = ''
  let inQuotes = false
  for (let i = 0; i < text.length; i++) {
    const c = text[i]
    if (inQuotes) {
      if (c === '"') {
        if (text[i + 1] === '"') {
          field += '"'
          i++
        } else {
          inQuotes = false
        }
      } else {
        field += c
      }
    } else if (c === '"') {
      inQuotes = true
    } else if (c === ',') {
      row.push(field)
      field = ''
    } else if (c === '\n' || c === '\r') {
      if (c === '\r' && text[i + 1] === '\n') i++
      row.push(field)
      field = ''
      rows.push(row)
      row = []
    } else {
      field += c
    }
  }
  if (field.length > 0 || row.length > 0) {
    row.push(field)
    rows.push(row)
  }
  return rows.filter((r) => r.some((c) => c.trim() !== ''))
}

/** Reads a file into a 2D grid of strings (header row + data rows). */
async function readGrid(filePath: string): Promise<string[][]> {
  const lower = filePath.toLowerCase()
  if (lower.endsWith('.csv')) {
    return parseCsv(fs.readFileSync(filePath, 'utf-8'))
  }
  // Excel
  const wb = new ExcelJS.Workbook()
  await wb.xlsx.readFile(filePath)
  const ws = wb.worksheets[0]
  if (!ws) throw new AppError('UNKNOWN', 'The workbook has no sheets')
  const grid: string[][] = []
  ws.eachRow((row) => {
    const cells: string[] = []
    // row.values is 1-indexed with a leading null.
    const vals = row.values as unknown[]
    for (let i = 1; i < vals.length; i++) {
      const v = vals[i]
      if (v === null || v === undefined) {
        cells.push('')
      } else if (typeof v === 'object' && v !== null && 'text' in (v as object)) {
        cells.push(String((v as { text: unknown }).text ?? ''))
      } else if (v instanceof Date) {
        cells.push(
          `${v.getFullYear()}-${String(v.getMonth() + 1).padStart(2, '0')}-${String(v.getDate()).padStart(2, '0')}`,
        )
      } else {
        cells.push(String(v))
      }
    }
    grid.push(cells)
  })
  return grid.filter((r) => r.some((c) => c.trim() !== ''))
}

export function registerImportHandlers(): void {
  // Step 1: pick a file and report its headers + a small preview.
  ipcMain.handle('import:inspect', () =>
    wrapAsync<ImportInspection | null>(async () => {
      const win = BrowserWindow.getFocusedWindow() ?? BrowserWindow.getAllWindows()[0] ?? undefined
      const res = await dialog.showOpenDialog(win!, {
        properties: ['openFile'],
        filters: [{ name: 'Spreadsheet', extensions: ['xlsx', 'csv'] }],
      })
      if (res.canceled || res.filePaths.length === 0) return null
      const filePath = res.filePaths[0]
      const grid = await readGrid(filePath)
      if (grid.length < 2) {
        throw new AppError('UNKNOWN', 'The file needs a header row and at least one data row')
      }
      const headers = grid[0].map((h) => h.trim())
      const sampleRows = grid.slice(1, 6)
      return { headers, sampleRows, rowCount: grid.length - 1, filePath }
    }),
  )

  // Step 2: run the import with the chosen mapping.
  ipcMain.handle('import:run', (_e, filePath: string, mapping: ImportMapping, autoNumber?: boolean) =>
    wrapAsync<ImportResult>(async () => {
      if (!filePath || !fs.existsSync(filePath)) {
        throw new AppError('UNKNOWN', 'The selected file could not be found. Please pick it again.')
      }
      const grid = await readGrid(filePath)
      const headers = grid[0].map((h) => h.trim())
      const rows = grid.slice(1).map((cells) => {
        const rec: Record<string, string> = {}
        headers.forEach((h, idx) => {
          rec[h] = cells[idx] ?? ''
        })
        return rec
      })
      // Snapshot before a (potentially large) import so it can be undone.
      recordSnapshot(db, 'Import memos')
      return importMemos(db, rows, mapping, { autoNumber: autoNumber === true })
    }),
  )
}
