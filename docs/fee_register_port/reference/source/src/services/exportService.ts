/**
 * exportService.ts
 *
 * Produces export artifacts as in-memory buffers. The pure buffer-generating
 * functions take explicit inputs (no Electron, no filesystem) so they are unit
 * testable. The Electron save-dialog / file-writing glue lives in the IPC layer
 * (electron/ipc/export.ts).
 *
 *   buildPlaceholderMap  — maps a MemoDetail to the template's LINE_* keys
 *   deriveExportFilename — "Memo No {seq} of Ziyad Madon ({matter}).docx"
 *   generateWordBuffer   — fills the template .docx and returns a Buffer
 *   generateStatementExcel — per-firm / per-matter statement as a workbook
 *   generateMemosExcel / generateFeebookExcel / generateOutstandingExcel
 */

import Docxtemplater from 'docxtemplater'
import PizZip from 'pizzip'
import type { LedgerRow } from './ledgerService'
import ExcelJS from 'exceljs'
import { AppError } from '@/types/ipc'
import type {
  MemoDetail,
  MemoListItem,
  FeebookEntry,
  OutstandingGroup,
  OutstandingEntry,
  OutstandingFirmSummary,
  PeriodStatistics,
  YearEndSummary,
  AnnualDetailRow,
} from '@/types/ipc'

const FIRM_OWNER = 'Ziyad Madon'

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

export function formatCurrency(n: number): string {
  // Indian grouping, NO decimal places, no currency symbol (template supplies it).
  return Math.round(n).toLocaleString('en-IN', { maximumFractionDigits: 0 })
}

export function formatDate(iso: string): string {
  // Expecting YYYY-MM-DD; render as DD.MM.YYYY (dots). Fall back to the raw value.
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso)
  if (!m) return iso
  return `${m[3]}.${m[2]}.${m[1]}`
}

/** Sanitises a matter name for safe use in a filename. */
function sanitizeForFilename(name: string): string {
  return name.replace(/[/\\:*?"<>|]/g, '-').trim()
}

// ---------------------------------------------------------------------------
// Placeholder map (Req 9.5: internal fields LINE_3/4 and payment lines excluded)
// ---------------------------------------------------------------------------

/**
 * A line is "shown" in the export when the memo carries any data for it. This
 * mirrors the per-line enable toggles on the memo form: a disabled line is
 * saved with zeroed values, so it is omitted here. Templates wrap each line
 * group in a conditional section ({{#SHOW_*}}...{{/SHOW_*}}) so a false flag
 * removes the entire row/paragraph, not just its values.
 */
/** "1 Appearance" / "2 Appearances"; blank when the count is 0. */
function countWithNoun(n: number, one: string, many: string): string {
  return n > 0 ? `${n} ${n === 1 ? one : many}` : ''
}

/** Short names for the conditional-section flags. */
const FLAG_ALIASES: Record<string, string> = {
  SHOW_APPEARANCES: 'IF_APP',
  SHOW_CONFERENCES: 'IF_CONF',
  SHOW_MISC: 'IF_MISC',
  SHOW_PLAINTIFF: 'IF_PL',
  SHOW_DEFENDANT: 'IF_DEF',
  SHOW_CLIENT: 'IF_CLIENT',
}

/**
 * Template tags are exposed under BOTH names: the original long form
 * (LINE_16_NUM_APPEARANCES, SHOW_APPEARANCES) so existing templates keep
 * working, and the short form (L16, IF_APP) for readable templates.
 */
function withShortAliases(base: Record<string, string | boolean>): Record<string, string | boolean> {
  const out: Record<string, string | boolean> = { ...base }
  for (const [key, value] of Object.entries(base)) {
    const line = /^LINE_(\d+[A-Z]?)_/.exec(key)
    if (line) out[`L${line[1]}`] = value
    else if (FLAG_ALIASES[key]) out[FLAG_ALIASES[key]] = value
  }
  return out
}

export function buildPlaceholderMap(memo: MemoDetail): Record<string, string | boolean> {
  return withShortAliases(buildBaseMap(memo))
}

function buildBaseMap(memo: MemoDetail): Record<string, string | boolean> {
  const showAppearances = memo.numAppearances > 0 || memo.feesPerAppearance > 0
  const showConferences = memo.numConferences > 0 || memo.feesPerConference > 0
  const showMisc = memo.feesMiscDrafting > 0 || !!memo.miscDraftingDescription
  // Req #7: hide these lines entirely when blank.
  const showPlaintiff = !!(memo.plaintiffName && memo.plaintiffName.trim())
  const showDefendant = !!(memo.defendantName && memo.defendantName.trim())
  const showClient = !!(memo.client && memo.client.trim())

  return {
    LINE_1_DATE: formatDate(memo.date),
    LINE_2_MEMO_NUMBER: memo.memoNumber ?? '',
    LINE_5_ADDRESSEE_1: memo.addresseeLine1 ?? '',
    LINE_6_ADDRESSEE_2: memo.addresseeLine2 ?? '',
    // The Short Name (when set) is what appears in the Word export.
    LINE_7_MATTER_NAME: memo.matterShortName || memo.matterName || '',
    LINE_8_COURT_NAME: memo.courtName ?? '',
    LINE_9_ADD_LEFT: memo.additionalDetailsLeft ?? '',
    LINE_10_ADD_RIGHT: memo.additionalDetailsRight ?? '',
    LINE_11_PLAINTIFF: memo.plaintiffName ?? '',
    LINE_12_PLAINTIFF_TYPE: memo.plaintiffType ?? '',
    LINE_13_DEFENDANT: memo.defendantName ?? '',
    LINE_14_DEFENDANT_TYPE: memo.defendantType ?? '',
    LINE_15_CLIENT: memo.client ?? '',
    // Conditional section flags (true => keep the row, false => delete it).
    SHOW_APPEARANCES: showAppearances,
    SHOW_CONFERENCES: showConferences,
    SHOW_MISC: showMisc,
    SHOW_PLAINTIFF: showPlaintiff,
    SHOW_DEFENDANT: showDefendant,
    SHOW_CLIENT: showClient,
    LINE_16_NUM_APPEARANCES: memo.numAppearances ? String(memo.numAppearances) : '',
    // Number + correctly pluralised noun, e.g. "1 Appearance" / "2 Appearances".
    L16W: countWithNoun(memo.numAppearances, 'Appearance', 'Appearances'),
    LINE_17_DATES_APPEARANCES: memo.datesOfAppearances ?? '',
    LINE_18_FEES_PER_APP: memo.feesPerAppearance ? formatCurrency(memo.feesPerAppearance) : '',
    LINE_18A_FEES_APPEARANCES: memo.feesAppearances ? formatCurrency(memo.feesAppearances) : '',
    LINE_19_NUM_CONFERENCES: memo.numConferences ? String(memo.numConferences) : '',
    L19W: countWithNoun(memo.numConferences, 'Conference', 'Conferences'),
    LINE_20_DATES_CONFERENCES: memo.datesOfConferences ?? '',
    LINE_21_FEES_PER_CONF: memo.feesPerConference ? formatCurrency(memo.feesPerConference) : '',
    LINE_21A_FEES_CONFERENCES: memo.feesConferences ? formatCurrency(memo.feesConferences) : '',
    LINE_22_MISC_DESC: memo.miscDraftingDescription ?? '',
    LINE_23_FEES_MISC: memo.feesMiscDrafting ? formatCurrency(memo.feesMiscDrafting) : '',
    LINE_24_TOTAL_FEES: formatCurrency(memo.totalFees),
    LINE_24A_TOTAL_FEES_WORDS: memo.totalFeesInWords,
  }
}

// ---------------------------------------------------------------------------
// Filename (Req 9.3)
// ---------------------------------------------------------------------------

export function deriveExportFilename(memo: MemoDetail, ext: 'docx' = 'docx'): string {
  const num = memo.memoNumber ?? ''
  const slash = num.lastIndexOf('/')
  // "2026-27/5" → number 5, year 2026-27. A number with no "/" is used as is.
  const seq = slash >= 0 ? num.slice(slash + 1) : num || String(memo.seq)
  const year = slash >= 0 ? num.slice(0, slash) : ''
  const matter = sanitizeForFilename(memo.matterShortName || memo.matterName)
  const middle = year ? `Memo ${seq} of ${year}` : `Memo ${seq}`
  return `${sanitizeForFilename(middle)} ${FIRM_OWNER} (${matter}).${ext}`
}

// ---------------------------------------------------------------------------
// Word export (Req 9.1, 9.4)
// ---------------------------------------------------------------------------

/**
 * Fills a template .docx (provided as a Buffer) with the memo's placeholder map
 * and returns the rendered .docx as a Buffer. Blank placeholders render empty,
 * and docxtemplater's nullGetter prevents "undefined" leaking into the output.
 */
export function generateWordBuffer(templateBuffer: Buffer, memo: MemoDetail): Buffer {
  let zip: PizZip
  try {
    zip = new PizZip(templateBuffer)
  } catch {
    throw new AppError('INVALID_TEMPLATE', 'The Word template could not be read')
  }

  let doc: Docxtemplater
  try {
    doc = new Docxtemplater(zip, {
      paragraphLoop: true,
      linebreaks: true,
      nullGetter: () => '',
      delimiters: { start: '{{', end: '}}' },
    })
    doc.render(buildPlaceholderMap(memo))
  } catch (err) {
    throw new AppError('EXPORT_FAILED', `Failed to render template: ${(err as Error).message}`)
  }

  return doc.getZip().generate({ type: 'nodebuffer', compression: 'DEFLATE' }) as Buffer
}

// ---------------------------------------------------------------------------
// Statement (per firm / per matter) — exported to Excel
// ---------------------------------------------------------------------------

export interface StatementData {
  title: string
  subtitle: string
  rows: MemoListItem[]
}

/**
 * Renders a per-firm / per-matter statement to Excel: one row per memo, with a
 * totals row. Columns mirror the on-screen statement — Memo No., Date, Matter,
 * Total, Paid, Outstanding, Status.
 */
export async function generateStatementExcel(data: StatementData): Promise<Buffer> {
  const wb = new ExcelJS.Workbook()
  const ws = wb.addWorksheet('Statement')
  ws.columns = [
    { header: 'Memo No.', key: 'memoNumber', width: 16 },
    { header: 'Date', key: 'date', width: 14 },
    { header: 'Matter Name', key: 'matterName', width: 28 },
    { header: 'Total', key: 'total', width: 14 },
    { header: 'Paid', key: 'paid', width: 14 },
    { header: 'Outstanding', key: 'outstanding', width: 14 },
    { header: 'Status', key: 'status', width: 14 },
  ]
  ws.getRow(1).font = { bold: true }
  applyNumberFormat(ws, ['total', 'paid', 'outstanding'])

  let totalBilled = 0
  let totalPaid = 0
  let totalOutstanding = 0
  for (const m of data.rows) {
    const outstanding = Math.max(0, Math.round((m.totalFees - m.amountPaid) * 100) / 100)
    totalBilled = Math.round((totalBilled + m.totalFees) * 100) / 100
    totalPaid = Math.round((totalPaid + m.amountPaid) * 100) / 100
    totalOutstanding = Math.round((totalOutstanding + outstanding) * 100) / 100
    ws.addRow({
      memoNumber: m.memoNumber ?? '',
      date: formatDate(m.date),
      matterName: m.matterName ?? '',
      total: m.totalFees,
      paid: m.amountPaid,
      outstanding,
      status: m.writtenOff ? 'Written Off' : m.status,
    })
  }
  const totalRow = ws.addRow({
    matterName: `Totals (${data.rows.length})`,
    total: totalBilled,
    paid: totalPaid,
    outstanding: totalOutstanding,
  })
  totalRow.font = { bold: true }

  return Buffer.from(await wb.xlsx.writeBuffer())
}

/** Renders a running-balance ledger (see ledgerService) to Excel. */
export async function generateLedgerExcel(rows: LedgerRow[]): Promise<Buffer> {
  const wb = new ExcelJS.Workbook()
  const ws = wb.addWorksheet('Ledger')
  ws.columns = [
    { header: 'Date', key: 'date', width: 14 },
    { header: 'Particulars', key: 'particulars', width: 52 },
    { header: 'Matter Name', key: 'matterName', width: 28 },
    { header: 'Memo Amount', key: 'memoAmount', width: 16 },
    { header: 'Payment Amount', key: 'paymentAmount', width: 16 },
    { header: 'TDS', key: 'tds', width: 12 },
    { header: 'Balance Payable', key: 'balance', width: 16 },
  ]
  ws.getRow(1).font = { bold: true }
  applyNumberFormat(ws, ['memoAmount', 'paymentAmount', 'tds', 'balance'])
  for (const r of rows) {
    ws.addRow({
      date: formatDate(r.date),
      particulars: r.particulars,
      matterName: r.matterName,
      memoAmount: r.memoAmount ?? undefined,
      paymentAmount: r.paymentAmount ?? undefined,
      tds: r.tds ?? undefined,
      balance: r.balance,
    })
  }
  return Buffer.from(await wb.xlsx.writeBuffer())
}

// ---------------------------------------------------------------------------
// Excel exports (Req 7.13, 10.7, 11.5)
// ---------------------------------------------------------------------------

// Excel number format: comma-separated thousands, no decimal places (Req #2).
const INT_NUM_FMT = '#,##0'

/** Applies the integer number format to the named columns of a worksheet. */
function applyNumberFormat(ws: ExcelJS.Worksheet, keys: string[]): void {
  for (const key of keys) {
    const col = ws.getColumn(key)
    col.numFmt = INT_NUM_FMT
  }
}

export async function generateMemosExcel(rows: MemoListItem[]): Promise<Buffer> {
  const wb = new ExcelJS.Workbook()
  const ws = wb.addWorksheet('Memos')
  ws.columns = [
    { header: 'Memo Number', key: 'memoNumber', width: 16 },
    { header: 'Date', key: 'date', width: 14 },
    { header: 'Firm', key: 'firmName', width: 28 },
    { header: 'Matter Name', key: 'matterName', width: 28 },
    { header: 'Total Fees', key: 'totalFees', width: 14 },
    { header: 'Net of TDS', key: 'netOfTds', width: 14 },
    { header: 'Amount Paid', key: 'amountPaid', width: 14 },
    { header: 'Date of Last Payment', key: 'dateOfLastPayment', width: 18 },
    { header: 'Status', key: 'status', width: 10 },
  ]
  ws.getRow(1).font = { bold: true }
  applyNumberFormat(ws, ['totalFees', 'netOfTds', 'amountPaid'])
  for (const r of rows) {
    ws.addRow({
      memoNumber: r.memoNumber,
      date: formatDate(r.date),
      firmName: r.firmName,
      matterName: r.matterName,
      totalFees: r.totalFees,
      netOfTds: r.netOfTds,
      amountPaid: r.amountPaid,
      dateOfLastPayment: r.dateOfLastPayment ? formatDate(r.dateOfLastPayment) : '',
      status: r.status,
    })
  }
  return Buffer.from(await wb.xlsx.writeBuffer())
}

/** Feebook export columns, in display order. `key` matches the on-screen table. */
const FEEBOOK_EXPORT_COLUMNS: Array<{
  key: string
  header: string
  width: number
  money?: boolean
  value: (r: FeebookEntry) => string | number
}> = [
  { key: 'date', header: 'Date', width: 14, value: (r) => formatDate(r.dateOfPayment) },
  { key: 'memo', header: 'Memo No.', width: 16, value: (r) => r.memoNumber ?? '' },
  { key: 'matter', header: 'Matter Name', width: 26, value: (r) => r.matterName ?? '' },
  { key: 'payee', header: 'Payee', width: 20, value: (r) => r.payee ?? '' },
  { key: 'paid', header: 'Paid', width: 14, money: true, value: (r) => r.amountPaid },
  { key: 'tds', header: 'TDS', width: 12, money: true, value: (r) => r.tds },
  { key: 'gross', header: 'Paid + TDS', width: 14, money: true, value: (r) => r.paidPlusTds },
  { key: 'bank', header: 'Bank', width: 22, value: (r) => r.bankAccountName ?? '' },
  { key: 'mode', header: 'Mode', width: 14, value: (r) => r.paymentMode ?? '' },
  { key: 'type', header: 'Type', width: 12, value: (r) => r.paymentType },
]

/**
 * @param visibleKeys when given, only these on-screen columns are exported
 *   (Memo No. and Date are always kept so rows stay identifiable).
 */
export async function generateFeebookExcel(rows: FeebookEntry[], visibleKeys?: string[]): Promise<Buffer> {
  const wb = new ExcelJS.Workbook()
  const ws = wb.addWorksheet('Feebook')
  const cols = FEEBOOK_EXPORT_COLUMNS.filter(
    (c) => !visibleKeys || visibleKeys.includes(c.key) || c.key === 'date' || c.key === 'memo',
  )
  ws.columns = cols.map((c) => ({ header: c.header, key: c.key, width: c.width }))
  ws.getRow(1).font = { bold: true }
  applyNumberFormat(
    ws,
    cols.filter((c) => c.money).map((c) => c.key),
  )
  for (const r of rows) {
    ws.addRow(Object.fromEntries(cols.map((c) => [c.key, c.value(r)])))
  }
  return Buffer.from(await wb.xlsx.writeBuffer())
}

/** Outstanding export columns; `key` matches the on-screen table's column keys. */
const OUTSTANDING_EXPORT_COLUMNS: Array<{
  key: string
  header: string
  width: number
  money?: boolean
  value: (e: OutstandingEntry) => string | number
}> = [
  { key: 'firm', header: 'Firm', width: 28, value: (e) => e.firmName },
  { key: 'partner', header: 'Group', width: 22, value: (e) => e.partnerName },
  { key: 'date', header: 'Date', width: 14, value: (e) => formatDate(e.date) },
  { key: 'memo', header: 'Memo Number', width: 16, value: (e) => e.memoNumber },
  { key: 'matter', header: 'Matter Name', width: 28, value: (e) => e.matterName },
  { key: 'total', header: 'Total Memo Amount', width: 18, money: true, value: (e) => e.totalFees },
  { key: 'net', header: 'Net of TDS', width: 14, money: true, value: (e) => e.netOfTds },
  { key: 'paid', header: 'Already Paid', width: 14, money: true, value: (e) => e.amountPaid },
  { key: 'due', header: 'Due', width: 14, money: true, value: (e) => e.due },
]

/**
 * @param visibleKeys when given, only these columns are exported (Date, Memo
 *   Number and Due are always kept). Firm / Partner are included by default.
 */
export async function generateOutstandingExcel(
  groups: OutstandingGroup[],
  visibleKeys?: string[],
): Promise<Buffer> {
  const wb = new ExcelJS.Workbook()
  const ws = wb.addWorksheet('Outstanding')
  const cols = OUTSTANDING_EXPORT_COLUMNS.filter(
    (c) => !visibleKeys || visibleKeys.includes(c.key) || ['date', 'memo', 'due'].includes(c.key),
  )
  ws.columns = cols.map((c) => ({ header: c.header, key: c.key, width: c.width }))
  ws.getRow(1).font = { bold: true }
  applyNumberFormat(
    ws,
    cols.filter((c) => c.money).map((c) => c.key),
  )

  let grandTotal = 0
  let grandNet = 0
  let grandPaid = 0
  let grandDue = 0
  for (const g of groups) {
    for (const e of g.entries) {
      ws.addRow(Object.fromEntries(cols.map((c) => [c.key, c.value(e)])))
    }
    grandTotal = Math.round((grandTotal + g.subtotalTotal) * 100) / 100
    grandNet = Math.round((grandNet + g.subtotalNetOfTds) * 100) / 100
    grandPaid = Math.round((grandPaid + g.subtotalPaid) * 100) / 100
    grandDue = Math.round((grandDue + g.subtotal) * 100) / 100
  }
  const labelKey = cols.some((c) => c.key === 'matter') ? 'matter' : 'memo'
  const totalRow = ws.addRow({
    [labelKey]: 'TOTAL',
    total: grandTotal,
    net: grandNet,
    paid: grandPaid,
    due: grandDue,
  })
  totalRow.font = { bold: true }

  return Buffer.from(await wb.xlsx.writeBuffer())
}

// ---------------------------------------------------------------------------
// Statistics Excel (Req #8) — metrics down rows, periods across columns, to
// match the on-screen table.
// ---------------------------------------------------------------------------

type StatMetricKey =
  | 'numAppearances'
  | 'numConferences'
  | 'numDrafts'
  | 'amountBilled'
  | 'amountReceived'
  | 'amountReceivedPlusTds'
  | 'workingDays'
  | 'appearancesPerWeek'
  | 'conferencesPerWeek'
  | 'draftsPerWeek'
  | 'feesPerWeek'
  | 'amountRecovered'
  | 'percentRecovered'
  | 'feesPerDay'

const STAT_METRIC_ROWS: Array<{ key: StatMetricKey; label: string; money?: boolean }> = [
  { key: 'numAppearances', label: 'Appearances' },
  { key: 'numConferences', label: 'Conferences' },
  { key: 'numDrafts', label: 'Drafts' },
  { key: 'amountBilled', label: 'Amount Billed', money: true },
  { key: 'amountRecovered', label: 'Amount Recovered', money: true },
  { key: 'percentRecovered', label: '% Recovered' },
  { key: 'amountReceived', label: 'Amount Received', money: true },
  { key: 'amountReceivedPlusTds', label: 'Received + TDS', money: true },
  { key: 'feesPerDay', label: 'Fees / Day', money: true },
  { key: 'appearancesPerWeek', label: 'Appearances / Week' },
  { key: 'conferencesPerWeek', label: 'Conferences / Week' },
  { key: 'draftsPerWeek', label: 'Drafts / Week' },
  { key: 'feesPerWeek', label: 'Fees / Week', money: true },
]

export async function generateStatisticsExcel(stats: PeriodStatistics): Promise<Buffer> {
  const wb = new ExcelJS.Workbook()
  const ws = wb.addWorksheet('Statistics')

  // Header row: "Metric" + one column per period.
  const header = ['Metric', ...stats.periods.map((p) => p.label)]
  ws.addRow(header)
  ws.getRow(1).font = { bold: true }
  ws.getColumn(1).width = 22
  for (let i = 0; i < stats.periods.length; i++) {
    ws.getColumn(i + 2).width = 14
  }

  for (const row of STAT_METRIC_ROWS) {
    const values = stats.periods.map((p) => p[row.key])
    const added = ws.addRow([row.label, ...values])
    if (row.money) {
      for (let i = 0; i < stats.periods.length; i++) {
        added.getCell(i + 2).numFmt = INT_NUM_FMT
      }
    }
  }

  return Buffer.from(await wb.xlsx.writeBuffer())
}

/** Statistics rows for the Annual Summary / table (key → label). */
function addStatSheet(wb: ExcelJS.Workbook, name: string, stats: PeriodStatistics): void {
  const ws = wb.addWorksheet(name)
  ws.addRow(['Metric', ...stats.periods.map((p) => p.label)])
  ws.getRow(1).font = { bold: true }
  ws.getColumn(1).width = 24
  stats.periods.forEach((_, i) => (ws.getColumn(i + 2).width = 14))
  for (const row of STAT_METRIC_ROWS) {
    const added = ws.addRow([row.label, ...stats.periods.map((p) => p[row.key])])
    if (row.money) stats.periods.forEach((_, i) => (added.getCell(i + 2).numFmt = INT_NUM_FMT))
  }
}

function addDetailSheet(wb: ExcelJS.Workbook, name: string, rows: AnnualDetailRow[], withFirm: boolean): void {
  const ws = wb.addWorksheet(name)
  ws.columns = [
    { header: withFirm ? 'Matter' : 'Firm', key: 'name', width: 34 },
    ...(withFirm ? [{ header: 'Firm', key: 'firmName', width: 28 }] : []),
    { header: 'Memos', key: 'memos', width: 10 },
    { header: 'Appearances', key: 'appearances', width: 14 },
    { header: 'Conferences', key: 'conferences', width: 14 },
    { header: 'Drafts', key: 'drafts', width: 10 },
    { header: 'Billed', key: 'billed', width: 14 },
    { header: 'Received', key: 'received', width: 14 },
    { header: 'TDS', key: 'tds', width: 12 },
  ]
  ws.getRow(1).font = { bold: true }
  applyNumberFormat(ws, ['billed', 'received', 'tds'])
  const tot = { memos: 0, appearances: 0, conferences: 0, drafts: 0, billed: 0, received: 0, tds: 0 }
  for (const r of rows) {
    ws.addRow(r)
    for (const k of Object.keys(tot) as Array<keyof typeof tot>) tot[k] += r[k]
  }
  ws.addRow({ name: 'TOTAL', ...tot }).font = { bold: true }
}

/**
 * Annual Summary workbook: annual figures, month-wise figures, then the
 * per-firm and per-matter breakdowns for one financial year.
 */
export async function generateAnnualSummaryExcel(data: {
  financialYear: string
  summary: YearEndSummary
  annual: PeriodStatistics
  monthly: PeriodStatistics
  quarterly: PeriodStatistics
  byFirm: AnnualDetailRow[]
  byMatter: AnnualDetailRow[]
}): Promise<Buffer> {
  const wb = new ExcelJS.Workbook()
  const s = data.summary
  const head = wb.addWorksheet('Annual')
  head.columns = [{ width: 28 }, { width: 18 }]
  head.addRow([`Annual Summary — ${data.financialYear}`]).font = { bold: true, size: 14 }
  head.addRow([])
  const lines: Array<[string, number]> = [
    ['Appearances', s.numAppearances],
    ['Appearances / Week', s.appearancesPerWeek],
    ['Memos', s.memoCount],
    ['New Matters', s.newMatters],
    ['Firms Billed', s.activeFirms],
    ['Billed', s.totalBilled],
    ['Received', s.totalReceived],
    ['TDS', s.totalTds],
  ]
  for (const [label, v] of lines) {
    const r = head.addRow([label, v])
    if (['Billed', 'Received', 'TDS'].includes(label)) r.getCell(2).numFmt = INT_NUM_FMT
  }
  head.addRow([])
  addStatSheet(wb, 'Annual Stats', data.annual)
  addStatSheet(wb, 'Quarter-wise', data.quarterly)
  addStatSheet(wb, 'Month-wise', data.monthly)
  addDetailSheet(wb, 'Details by Firm', data.byFirm, false)
  addDetailSheet(wb, 'Details by Matter', data.byMatter, true)
  return Buffer.from(await wb.xlsx.writeBuffer())
}

// ---------------------------------------------------------------------------
// Outstanding — firm-wise summary Excel (Req #3)
// ---------------------------------------------------------------------------

export async function generateOutstandingByFirmExcel(
  rows: OutstandingFirmSummary[],
): Promise<Buffer> {
  const wb = new ExcelJS.Workbook()
  const ws = wb.addWorksheet('Outstanding by Firm')
  ws.columns = [
    { header: 'Firm', key: 'firmName', width: 32 },
    { header: 'Memos Outstanding', key: 'memoCount', width: 18 },
    { header: 'Outstanding', key: 'outstanding', width: 16 },
  ]
  ws.getRow(1).font = { bold: true }
  applyNumberFormat(ws, ['outstanding'])

  let grand = 0
  for (const r of rows) {
    ws.addRow({ firmName: r.firmName, memoCount: r.memoCount, outstanding: r.outstanding })
    grand = Math.round((grand + r.outstanding) * 100) / 100
  }
  const totalRow = ws.addRow({ firmName: 'TOTAL', outstanding: grand })
  totalRow.font = { bold: true }

  return Buffer.from(await wb.xlsx.writeBuffer())
}
