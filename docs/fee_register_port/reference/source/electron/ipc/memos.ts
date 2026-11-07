/**
 * electron/ipc/memos.ts — IPC handlers for Memos, including Word/Excel export.
 */
import { ipcMain } from 'electron'
import fs from 'fs'
import { db } from '@/db/client'
import { AppError } from '@/types/ipc'
import type { IPCResponse, MemoInput, MemoFilter } from '@/types/ipc'
import {
  createMemo,
  getMemo,
  updateMemo,
  deleteMemo,
  listMemos,
  listDrafts,
  listMemosForMatter,
  finalizeDraft,
  createBasedOn,
  setMemoWrittenOff,
  listRecentMatters,
  findMemoIdByNumber,
} from '@/services/memoService'
import { previewMemoNumber } from '@/services/memoNumberService'
import { getSettings } from '@/services/settingsService'
import {
  generateWordBuffer,
  generateMemosExcel,
  generateStatementExcel,
  generateLedgerExcel,
  deriveExportFilename,
} from '@/services/exportService'
import { getFirm } from '@/services/firmService'
import { getMatter } from '@/services/matterService'
import { buildLedger, type LedgerScope } from '@/services/ledgerService'
import { saveBufferWithDialog } from './exportDialog'
import { wrap, wrapAsync } from './envelope'
import { mutate } from './withHistory'

function loadTemplateBuffer(): Buffer {
  const settings = getSettings(db)
  if (!settings.wordTemplatePath) {
    throw new AppError('NO_TEMPLATE', 'Upload a Word template in Settings before exporting')
  }
  if (!fs.existsSync(settings.wordTemplatePath)) {
    throw new AppError('NO_TEMPLATE', 'The configured Word template file is missing')
  }
  return fs.readFileSync(settings.wordTemplatePath)
}

export function registerMemoHandlers(): void {
  ipcMain.handle('memos:create', (_e, input: MemoInput) =>
    mutate('Create memo', () => createMemo(db, input)),
  )
  ipcMain.handle('memos:saveDraft', (_e, input: MemoInput) =>
    mutate('Save draft', () => createMemo(db, input, true)),
  )
  ipcMain.handle('memos:finalizeDraft', (_e, id: number, customMemoNumber?: string | null) =>
    mutate('Finalise draft', () => finalizeDraft(db, id, customMemoNumber)),
  )
  ipcMain.handle('memos:listDrafts', () => wrap(() => listDrafts(db)))
  ipcMain.handle('memos:listRecentMatters', (_e, limit?: number) =>
    wrap(() => listRecentMatters(db, limit ?? 10)),
  )
  ipcMain.handle('memos:listForMatter', (_e, matterId: number) =>
    wrap(() => listMemosForMatter(db, matterId)),
  )
  ipcMain.handle('memos:get', (_e, id: number) => wrap(() => getMemo(db, id)))
  ipcMain.handle('memos:findByNumber', (_e, memoNumber: string) =>
    wrap(() => findMemoIdByNumber(db, memoNumber)),
  )
  ipcMain.handle('memos:update', (_e, id: number, input: MemoInput) =>
    mutate('Edit memo', () => updateMemo(db, id, input)),
  )
  ipcMain.handle('memos:delete', (_e, id: number) =>
    mutate('Delete memo', () => deleteMemo(db, id)),
  )
  ipcMain.handle('memos:list', (_e, filter: MemoFilter) => wrap(() => listMemos(db, filter)))
  ipcMain.handle('memos:createBasedOn', (_e, sourceMemoId: number) =>
    wrap(() => createBasedOn(db, sourceMemoId)),
  )
  ipcMain.handle('memos:previewNumber', (_e, date: string) =>
    wrap(() => previewMemoNumber(db, date)),
  )
  ipcMain.handle('memos:setWrittenOff', (_e, id: number, writtenOff: boolean) =>
    mutate(writtenOff ? 'Write off memo' : 'Restore memo', () => setMemoWrittenOff(db, id, writtenOff)),
  )

  ipcMain.handle('memos:exportWord', (_e, id: number) =>
    wrapAsync(async () => {
      const memo = getMemo(db, id)
      const buffer = generateWordBuffer(loadTemplateBuffer(), memo)
      const path = await saveBufferWithDialog(deriveExportFilename(memo, 'docx'), buffer, [
        { name: 'Word Document', extensions: ['docx'] },
      ])
      return { saved: path !== null, path }
    }),
  )

  ipcMain.handle('memos:exportStatementExcel', (_e, scope: { firmId?: number; matterId?: number }) =>
    wrapAsync(async () => {
      let title = 'Statement'
      let subtitle = ''
      const filter: MemoFilter = {}
      if (scope.matterId !== undefined) {
        const m = getMatter(db, scope.matterId)
        filter.matterId = scope.matterId
        title = `Statement — ${m.name}`
        subtitle = `${m.firmName} · ${m.partnerName}`
      } else if (scope.firmId !== undefined) {
        const f = getFirm(db, scope.firmId)
        filter.firmId = scope.firmId
        title = `Statement — ${f.name}`
        subtitle = 'All matters'
      }
      const rows = listMemos(db, filter)
      const buffer = await generateStatementExcel({ title, subtitle, rows })
      const safe = title.replace(/[/\\:*?"<>|]/g, '-')
      const path = await saveBufferWithDialog(`${safe}.xlsx`, buffer, [
        { name: 'Excel Workbook', extensions: ['xlsx'] },
      ])
      return { saved: path !== null, path }
    }),
  )

  ipcMain.handle('memos:exportLedgerExcel', (_e, scope: LedgerScope) =>
    wrapAsync(async () => {
      let title = 'Ledger'
      if (scope.matterId !== undefined) title = `Ledger — ${getMatter(db, scope.matterId).name}`
      else if (scope.firmId !== undefined) {
        const firm = getFirm(db, scope.firmId)
        title = `Ledger — ${firm.name}`
        if (scope.partnerId !== undefined) {
          const partner = firm.partners.find((p) => p.id === scope.partnerId)
          title += ` — ${partner?.name ?? 'Partner'}`
        } else if (scope.matterIds && scope.matterIds.length > 0) {
          title +=
            scope.matterIds.length === 1
              ? ` — ${getMatter(db, scope.matterIds[0]).name}`
              : ` — ${scope.matterIds.length} matters`
        }
      }
      const buffer = await generateLedgerExcel(buildLedger(db, scope))
      const safe = title.replace(/[/\\:*?"<>|]/g, '-')
      const path = await saveBufferWithDialog(`${safe}.xlsx`, buffer, [
        { name: 'Excel Workbook', extensions: ['xlsx'] },
      ])
      return { saved: path !== null, path }
    }),
  )

  ipcMain.handle('memos:bulkExportExcel', (_e, filter: MemoFilter) =>
    wrapAsync(async () => {
      const rows = listMemos(db, filter)
      if (rows.length === 0) {
        throw new AppError('EXPORT_FAILED', 'No memos match the current filter to export')
      }
      const buffer = await generateMemosExcel(rows)
      const path = await saveBufferWithDialog(`Memos ${filter.financialYear ?? 'All Years'}.xlsx`, buffer, [
        { name: 'Excel Workbook', extensions: ['xlsx'] },
      ])
      return { saved: path !== null, path }
    }),
  )
}
