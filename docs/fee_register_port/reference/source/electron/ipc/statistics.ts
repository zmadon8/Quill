/**
 * electron/ipc/statistics.ts — IPC handlers for the Statistics view.
 */
import { ipcMain } from 'electron'
import { db } from '@/db/client'
import type {
  StatBreakdown,
  StatGranularity,
  PeriodAdjustmentDTO,
  PivotRequest,
  SavedViewInput,
  StatOptions,
} from '@/types/ipc'
import {
  getStatistics,
  getPeriodStatistics,
  listAdjustments,
  saveAdjustment,
  getYearEndSummary,
  getPivot,
  getAnnualBreakdown,
  listSavedViews,
  saveSavedView,
  deleteSavedView,
} from '@/services/statisticsService'
import { generateStatisticsExcel, generateAnnualSummaryExcel } from '@/services/exportService'
import { saveBufferWithDialog } from './exportDialog'
import { wrap, wrapAsync } from './envelope'



export function registerStatisticsHandlers(): void {
  ipcMain.handle('statistics:get', (_e, breakdown: StatBreakdown) =>
    wrap(() => getStatistics(db, breakdown)),
  )
  ipcMain.handle(
    'statistics:getPeriods',
    (_e, granularity: StatGranularity, fy: string | null, options?: StatOptions) =>
      wrap(() => getPeriodStatistics(db, granularity, fy, options ?? {})),
  )
  ipcMain.handle(
    'statistics:exportExcel',
    (_e, granularity: StatGranularity, fy: string | null, options?: StatOptions) =>
      wrapAsync(async () => {
        const stats = getPeriodStatistics(db, granularity, fy, options ?? {})
      const buffer = await generateStatisticsExcel(stats)
      const name = granularity === 'month' && fy ? `Statistics ${fy}.xlsx` : 'Statistics.xlsx'
      const path = await saveBufferWithDialog(name, buffer, [
        { name: 'Excel Workbook', extensions: ['xlsx'] },
      ])
      return { saved: path !== null, path }
    }),
  )
  ipcMain.handle('statistics:yearEndSummary', (_e, fy: string, options?: StatOptions) =>
    wrap(() => getYearEndSummary(db, fy, options ?? {})),
  )
  ipcMain.handle('statistics:exportAnnualSummary', (_e, fy: string, options?: StatOptions) =>
    wrapAsync(async () => {
      const opts = options ?? {}
      const buffer = await generateAnnualSummaryExcel({
        financialYear: fy,
        summary: getYearEndSummary(db, fy, opts),
        annual: getPeriodStatistics(db, 'financialYear', null, opts),
        monthly: getPeriodStatistics(db, 'month', fy, opts),
        quarterly: getPeriodStatistics(db, 'quarter', fy, opts),
        byFirm: getAnnualBreakdown(db, fy, 'firm'),
        byMatter: getAnnualBreakdown(db, fy, 'matter'),
      })
      const path = await saveBufferWithDialog(`Annual Summary ${fy}.xlsx`, buffer, [
        { name: 'Excel Workbook', extensions: ['xlsx'] },
      ])
      return { saved: path !== null, path }
    }),
  )
  ipcMain.handle('statistics:exportSummaryText', (_e, fy: string) =>
    wrapAsync(async () => {
      const s = getYearEndSummary(db, fy)
      const inr = (n: number) => Math.round(n).toLocaleString('en-IN')
      const lines = [
        `Tax Summary — ${s.financialYear}`,
        ``,
        `Appearances: ${s.numAppearances}`,
        `Appearances / Week: ${s.appearancesPerWeek}`,
        `Memos: ${s.memoCount}`,
        `New Matters: ${s.newMatters}`,
        `Firms Billed: ${s.activeFirms}`,
        `Billed: ₹ ${inr(s.totalBilled)}`,
        `Received: ₹ ${inr(s.totalReceived)}`,
        `TDS: ₹ ${inr(s.totalTds)}`,
      ]
      const buffer = Buffer.from(lines.join('\n') + '\n', 'utf-8')
      const path = await saveBufferWithDialog(`Tax Summary ${fy}.txt`, buffer, [
        { name: 'Text File', extensions: ['txt'] },
      ])
      return { saved: path !== null, path }
    }),
  )
  ipcMain.handle('statistics:pivot', (_e, req: PivotRequest) => wrap(() => getPivot(db, req)))
  ipcMain.handle('statistics:listSavedViews', () => wrap(() => listSavedViews(db)))
  ipcMain.handle('statistics:saveSavedView', (_e, input: SavedViewInput) =>
    wrap(() => saveSavedView(db, input)),
  )
  ipcMain.handle('statistics:deleteSavedView', (_e, id: number) =>
    wrap(() => deleteSavedView(db, id)),
  )
  ipcMain.handle('statistics:listAdjustments', (_e, fy: string) =>
    wrap(() => listAdjustments(db, fy)),
  )
  ipcMain.handle('statistics:saveAdjustment', (_e, a: PeriodAdjustmentDTO) =>
    wrap(() => {
      saveAdjustment(db, a)
      return listAdjustments(db, a.financialYear)
    }),
  )
}
