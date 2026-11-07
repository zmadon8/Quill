/**
 * electron/ipc/dashboard.ts — IPC handler for the Dashboard summary KPIs.
 */
import { ipcMain } from 'electron'
import { db } from '@/db/client'
import { getDashboardSummary, getDashboardKpis } from '@/services/dashboardService'
import { search } from '@/services/searchService'
import { wrap } from './envelope'


export function registerDashboardHandlers(): void {
  ipcMain.handle('dashboard:summary', () => wrap(() => getDashboardSummary(db)))
  ipcMain.handle('dashboard:kpis', () => wrap(() => getDashboardKpis(db)))
  ipcMain.handle('search:query', (_e, query: string) => wrap(() => search(db, query)))
}
