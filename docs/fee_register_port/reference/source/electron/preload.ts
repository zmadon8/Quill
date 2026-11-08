import { contextBridge, ipcRenderer } from 'electron'
import type {
  IPCResponse,
  FirmFilter,
  FirmStatus,
  FirmSummary,
  FirmDetail,
  PartnerDTO,
  MatterFilter,
  MatterInput,
  MatterUpdateInput,
  MatterDTO,
  MatterDetail,
  MemoInput,
  MemoFilter,
  MemoListItem,
  MemoDetail,
  MemoFormData,
  RecentMatterDTO,
  DashboardSummary,
  SearchResult,
  ImportInspection,
  ImportMapping,
  ImportResult,
  HistoryState,
  PaymentInput,
  PaymentDTO,
  MatterPayee,
  FeebookFilter,
  FeebookEntry,
  OutstandingFilter,
  OutstandingGroup,
  OutstandingSort,
  OutstandingFirmSummary,
  OutstandingScope,
  StatBreakdown,
  StatisticsData,
  StatGranularity,
  PeriodStatistics,
  PeriodAdjustmentDTO,
  StatOptions,
  YearEndSummary,
  PivotRequest,
  PivotResult,
  SavedView,
  SavedViewInput,
  SettingsDTO,
  SettingsInput,
  BankAccountDTO,
  SystemMetrics,
} from '../src/types/ipc'

type SaveResult = { saved: boolean; path: string | null }

const api = {
  firms: {
    create: (name: string) => ipcRenderer.invoke('firms:create', name) as Promise<IPCResponse<FirmSummary>>,
    list: (filter: FirmFilter) => ipcRenderer.invoke('firms:list', filter) as Promise<IPCResponse<FirmSummary[]>>,
    get: (id: number) => ipcRenderer.invoke('firms:get', id) as Promise<IPCResponse<FirmDetail>>,
    update: (id: number, data: { name?: string; notes?: string }) =>
      ipcRenderer.invoke('firms:update', id, data) as Promise<IPCResponse<FirmSummary>>,
    setStatus: (id: number, status: FirmStatus) =>
      ipcRenderer.invoke('firms:setStatus', id, status) as Promise<IPCResponse<FirmSummary>>,
    addPartner: (firmId: number, name: string) =>
      ipcRenderer.invoke('firms:addPartner', firmId, name) as Promise<IPCResponse<PartnerDTO>>,
    updatePartner: (firmId: number, partnerId: number, name: string) =>
      ipcRenderer.invoke('firms:updatePartner', firmId, partnerId, name) as Promise<
        IPCResponse<PartnerDTO>
      >,
    removePartner: (firmId: number, partnerId: number) =>
      ipcRenderer.invoke('firms:removePartner', firmId, partnerId) as Promise<IPCResponse<void>>,
  },
  matters: {
    create: (input: MatterInput) => ipcRenderer.invoke('matters:create', input) as Promise<IPCResponse<MatterDTO>>,
    update: (id: number, input: MatterUpdateInput) =>
      ipcRenderer.invoke('matters:update', id, input) as Promise<IPCResponse<MatterDetail>>,
    list: (filter: MatterFilter, firmId?: number) =>
      ipcRenderer.invoke('matters:list', filter, firmId) as Promise<IPCResponse<MatterDetail[]>>,
    get: (id: number) => ipcRenderer.invoke('matters:get', id) as Promise<IPCResponse<MatterDetail>>,
    archive: (id: number) => ipcRenderer.invoke('matters:archive', id) as Promise<IPCResponse<MatterDTO>>,
    unarchive: (id: number) => ipcRenderer.invoke('matters:unarchive', id) as Promise<IPCResponse<MatterDTO>>,
  },
  memos: {
    create: (input: MemoInput) => ipcRenderer.invoke('memos:create', input) as Promise<IPCResponse<MemoDetail>>,
    saveDraft: (input: MemoInput) => ipcRenderer.invoke('memos:saveDraft', input) as Promise<IPCResponse<MemoDetail>>,
    finalizeDraft: (id: number, customMemoNumber?: string | null) =>
      ipcRenderer.invoke('memos:finalizeDraft', id, customMemoNumber) as Promise<IPCResponse<MemoDetail>>,
    listDrafts: () => ipcRenderer.invoke('memos:listDrafts') as Promise<IPCResponse<MemoListItem[]>>,
    listRecentMatters: (limit?: number) =>
      ipcRenderer.invoke('memos:listRecentMatters', limit) as Promise<IPCResponse<RecentMatterDTO[]>>,
    listForMatter: (matterId: number) =>
      ipcRenderer.invoke('memos:listForMatter', matterId) as Promise<IPCResponse<MemoListItem[]>>,
    get: (id: number) => ipcRenderer.invoke('memos:get', id) as Promise<IPCResponse<MemoDetail>>,
    findByNumber: (memoNumber: string) =>
      ipcRenderer.invoke('memos:findByNumber', memoNumber) as Promise<IPCResponse<number | null>>,
    update: (id: number, input: MemoInput) =>
      ipcRenderer.invoke('memos:update', id, input) as Promise<IPCResponse<MemoDetail>>,
    delete: (id: number) => ipcRenderer.invoke('memos:delete', id) as Promise<IPCResponse<void>>,
    list: (filter: MemoFilter) => ipcRenderer.invoke('memos:list', filter) as Promise<IPCResponse<MemoListItem[]>>,
    createBasedOn: (sourceMemoId: number) =>
      ipcRenderer.invoke('memos:createBasedOn', sourceMemoId) as Promise<IPCResponse<MemoFormData>>,
    previewNumber: (date: string) =>
      ipcRenderer.invoke('memos:previewNumber', date) as Promise<IPCResponse<string>>,
    setWrittenOff: (id: number, writtenOff: boolean) =>
      ipcRenderer.invoke('memos:setWrittenOff', id, writtenOff) as Promise<IPCResponse<MemoDetail>>,
    exportWord: (id: number) => ipcRenderer.invoke('memos:exportWord', id) as Promise<IPCResponse<SaveResult>>,
    bulkExportExcel: (filter: MemoFilter) =>
      ipcRenderer.invoke('memos:bulkExportExcel', filter) as Promise<IPCResponse<SaveResult>>,
    exportLedgerExcel: (scope: { firmId?: number; matterId?: number; matterIds?: number[]; partnerId?: number }) =>
      ipcRenderer.invoke('memos:exportLedgerExcel', scope) as Promise<IPCResponse<SaveResult>>,
    exportStatementExcel: (scope: { firmId?: number; matterId?: number }) =>
      ipcRenderer.invoke('memos:exportStatementExcel', scope) as Promise<IPCResponse<SaveResult>>,
  },
  payments: {
    addToMemo: (memoId: number, input: PaymentInput) =>
      ipcRenderer.invoke('payments:addToMemo', memoId, input) as Promise<IPCResponse<PaymentDTO>>,
    add: (input: PaymentInput) =>
      ipcRenderer.invoke('payments:add', input) as Promise<IPCResponse<PaymentDTO>>,
    addUnaccounted: (input: PaymentInput) =>
      ipcRenderer.invoke('payments:addUnaccounted', input) as Promise<IPCResponse<PaymentDTO>>,
    assignToMemo: (paymentId: number, memoId: number) =>
      ipcRenderer.invoke('payments:assignToMemo', paymentId, memoId) as Promise<IPCResponse<PaymentDTO>>,
    update: (id: number, input: PaymentInput) =>
      ipcRenderer.invoke('payments:update', id, input) as Promise<IPCResponse<PaymentDTO>>,
    delete: (id: number) => ipcRenderer.invoke('payments:delete', id) as Promise<IPCResponse<void>>,
    get: (id: number) => ipcRenderer.invoke('payments:get', id) as Promise<IPCResponse<PaymentDTO>>,
    payeesForMatters: (matterIds: number[]) =>
      ipcRenderer.invoke('payments:payeesForMatters', matterIds) as Promise<IPCResponse<MatterPayee[]>>,
    listForMemo: (memoId: number) =>
      ipcRenderer.invoke('payments:listForMemo', memoId) as Promise<IPCResponse<PaymentDTO[]>>,
  },
  feebook: {
    list: (filter: FeebookFilter) => ipcRenderer.invoke('feebook:list', filter) as Promise<IPCResponse<FeebookEntry[]>>,
    exportExcel: (filter: FeebookFilter, visibleKeys?: string[]) =>
      ipcRenderer.invoke('feebook:exportExcel', filter, visibleKeys) as Promise<IPCResponse<SaveResult>>,
  },
  outstanding: {
    list: (filter: OutstandingFilter) =>
      ipcRenderer.invoke('outstanding:list', filter) as Promise<IPCResponse<OutstandingGroup[]>>,
    listByFirm: (filter: OutstandingFilter, sort: OutstandingSort) =>
      ipcRenderer.invoke('outstanding:listByFirm', filter, sort) as Promise<
        IPCResponse<OutstandingFirmSummary[]>
      >,
    scope: (filter: OutstandingFilter) =>
      ipcRenderer.invoke('outstanding:scope', filter) as Promise<IPCResponse<OutstandingScope>>,
    exportExcel: (filter: OutstandingFilter, fileName?: string, visibleKeys?: string[]) =>
      ipcRenderer.invoke('outstanding:exportExcel', filter, fileName, visibleKeys) as Promise<IPCResponse<SaveResult>>,
    exportByFirmExcel: (filter: OutstandingFilter, sort: OutstandingSort) =>
      ipcRenderer.invoke('outstanding:exportByFirmExcel', filter, sort) as Promise<
        IPCResponse<SaveResult>
      >,
  },
  statistics: {
    get: (breakdown: StatBreakdown) =>
      ipcRenderer.invoke('statistics:get', breakdown) as Promise<IPCResponse<StatisticsData>>,
    getPeriods: (granularity: StatGranularity, financialYear: string | null, options?: StatOptions) =>
      ipcRenderer.invoke('statistics:getPeriods', granularity, financialYear, options) as Promise<
        IPCResponse<PeriodStatistics>
      >,
    exportExcel: (granularity: StatGranularity, financialYear: string | null, options?: StatOptions) =>
      ipcRenderer.invoke('statistics:exportExcel', granularity, financialYear, options) as Promise<
        IPCResponse<SaveResult>
      >,
    exportAnnualSummary: (financialYear: string, options?: StatOptions) =>
      ipcRenderer.invoke('statistics:exportAnnualSummary', financialYear, options) as Promise<
        IPCResponse<SaveResult>
      >,
    yearEndSummary: (financialYear: string, options?: StatOptions) =>
      ipcRenderer.invoke('statistics:yearEndSummary', financialYear, options) as Promise<
        IPCResponse<YearEndSummary>
      >,
    exportSummaryText: (financialYear: string) =>
      ipcRenderer.invoke('statistics:exportSummaryText', financialYear) as Promise<
        IPCResponse<SaveResult>
      >,
    pivot: (req: PivotRequest) =>
      ipcRenderer.invoke('statistics:pivot', req) as Promise<IPCResponse<PivotResult>>,
    listSavedViews: () =>
      ipcRenderer.invoke('statistics:listSavedViews') as Promise<IPCResponse<SavedView[]>>,
    saveSavedView: (input: SavedViewInput) =>
      ipcRenderer.invoke('statistics:saveSavedView', input) as Promise<IPCResponse<SavedView[]>>,
    deleteSavedView: (id: number) =>
      ipcRenderer.invoke('statistics:deleteSavedView', id) as Promise<IPCResponse<SavedView[]>>,
    listAdjustments: (financialYear: string) =>
      ipcRenderer.invoke('statistics:listAdjustments', financialYear) as Promise<
        IPCResponse<PeriodAdjustmentDTO[]>
      >,
    saveAdjustment: (a: PeriodAdjustmentDTO) =>
      ipcRenderer.invoke('statistics:saveAdjustment', a) as Promise<IPCResponse<PeriodAdjustmentDTO[]>>,
  },
  settings: {
    get: () => ipcRenderer.invoke('settings:get') as Promise<IPCResponse<SettingsDTO>>,
    update: (input: SettingsInput) =>
      ipcRenderer.invoke('settings:update', input) as Promise<IPCResponse<SettingsDTO>>,
    pickFolder: () => ipcRenderer.invoke('settings:pickFolder') as Promise<IPCResponse<string | null>>,
    pickBackupDir: () =>
      ipcRenderer.invoke('settings:pickBackupDir') as Promise<
        IPCResponse<{ chosen: boolean; settings: SettingsDTO }>
      >,
    clearAllData: () =>
      ipcRenderer.invoke('settings:clearAllData') as Promise<
        IPCResponse<{ cleared: boolean; backupPath: string | null }>
      >,
    listBankAccounts: () =>
      ipcRenderer.invoke('settings:listBankAccounts') as Promise<IPCResponse<BankAccountDTO[]>>,
    addBankAccount: (name: string) =>
      ipcRenderer.invoke('settings:addBankAccount', name) as Promise<IPCResponse<BankAccountDTO>>,
    updateBankAccount: (id: number, name: string) =>
      ipcRenderer.invoke('settings:updateBankAccount', id, name) as Promise<IPCResponse<BankAccountDTO>>,
    deleteBankAccount: (id: number) =>
      ipcRenderer.invoke('settings:deleteBankAccount', id) as Promise<IPCResponse<void>>,
    uploadTemplate: (sourcePath: string) =>
      ipcRenderer.invoke('settings:uploadTemplate', sourcePath) as Promise<IPCResponse<SettingsDTO>>,
    restoreFromExcel: (filePath: string) =>
      ipcRenderer.invoke('settings:restoreFromExcel', filePath) as Promise<
        IPCResponse<{ restored: boolean; rowsImported: number }>
      >,
    pickAndUploadTemplate: () =>
      ipcRenderer.invoke('settings:pickAndUploadTemplate') as Promise<
        IPCResponse<{ uploaded: boolean; settings: SettingsDTO }>
      >,
    pickAndRestore: () =>
      ipcRenderer.invoke('settings:pickAndRestore') as Promise<
        IPCResponse<{ restored: boolean; rowsImported: number }>
      >,
  },
  backup: {
    export: () => ipcRenderer.invoke('backup:export') as Promise<IPCResponse<SaveResult>>,
  },
  dashboard: {
    summary: () => ipcRenderer.invoke('dashboard:summary') as Promise<IPCResponse<DashboardSummary>>,
    kpis: () => ipcRenderer.invoke('dashboard:kpis') as Promise<IPCResponse<Record<string, number>>>,
  },
  search: {
    query: (q: string) => ipcRenderer.invoke('search:query', q) as Promise<IPCResponse<SearchResult[]>>,
  },
  import: {
    inspect: () =>
      ipcRenderer.invoke('import:inspect') as Promise<IPCResponse<ImportInspection | null>>,
    run: (filePath: string, mapping: ImportMapping, autoNumber?: boolean) =>
      ipcRenderer.invoke('import:run', filePath, mapping, autoNumber) as Promise<IPCResponse<ImportResult>>,
  },
  history: {
    state: () => ipcRenderer.invoke('history:state') as Promise<IPCResponse<HistoryState>>,
    undo: () => ipcRenderer.invoke('history:undo') as Promise<IPCResponse<HistoryState>>,
    redo: () => ipcRenderer.invoke('history:redo') as Promise<IPCResponse<HistoryState>>,
  },
  system: {
    appVersion: () => ipcRenderer.invoke('system:appVersion') as Promise<IPCResponse<string>>,
    setZoom: (factor: number) => ipcRenderer.invoke('system:setZoom', factor) as Promise<IPCResponse<number>>,
    metrics: () => ipcRenderer.invoke('system:metrics') as Promise<IPCResponse<SystemMetrics>>,
  },
}

export type Api = typeof api

contextBridge.exposeInMainWorld('api', api)
