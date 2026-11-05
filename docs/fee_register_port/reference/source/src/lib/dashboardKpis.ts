/**
 * The catalog of Overview KPI boxes. The service computes a value for EVERY id
 * below; the user chooses which to show (and their order) in Settings →
 * "Overview boxes". Pure data, shared by the main process and the renderer.
 */
export interface KpiDef {
  id: string
  label: string
  group: 'Billing' | 'Receipts' | 'Memos' | 'Appearances & work' | 'Outstanding' | 'Drafts'
  kind: 'money' | 'count'
  /** Red value text (used for overdue). */
  accent?: 'red'
  /** Where clicking the box goes. */
  link?: 'memos' | 'feebook' | 'outstanding'
}

export const KPI_CATALOG: KpiDef[] = [
  // Billing
  { id: 'billedThisMonth', label: 'Billed This Month', group: 'Billing', kind: 'money', link: 'memos' },
  { id: 'billedThisYear', label: 'Billed This Year', group: 'Billing', kind: 'money', link: 'memos' },
  { id: 'billedLast30', label: 'Billed (Last 30 Days)', group: 'Billing', kind: 'money', link: 'memos' },
  // Receipts (gross, i.e. including TDS)
  { id: 'receivedThisMonth', label: 'Received This Month', group: 'Receipts', kind: 'money', link: 'feebook' },
  { id: 'receivedThisYear', label: 'Received This Year', group: 'Receipts', kind: 'money', link: 'feebook' },
  { id: 'receivedLast30', label: 'Received (Last 30 Days)', group: 'Receipts', kind: 'money', link: 'feebook' },
  // Memos
  { id: 'memosThisMonth', label: 'Memos This Month', group: 'Memos', kind: 'count', link: 'memos' },
  { id: 'memosThisYear', label: 'Memos This Year', group: 'Memos', kind: 'count', link: 'memos' },
  { id: 'memosLast30', label: 'Memos (Last 30 Days)', group: 'Memos', kind: 'count', link: 'memos' },
  // Appearances & work
  { id: 'appearancesThisMonth', label: 'Appearances This Month', group: 'Appearances & work', kind: 'count' },
  { id: 'appearancesThisYear', label: 'Appearances This Year', group: 'Appearances & work', kind: 'count' },
  { id: 'appearancesLast30', label: 'Appearances (Last 30 Days)', group: 'Appearances & work', kind: 'count' },
  { id: 'conferencesThisMonth', label: 'Conferences This Month', group: 'Appearances & work', kind: 'count' },
  { id: 'conferencesThisYear', label: 'Conferences This Year', group: 'Appearances & work', kind: 'count' },
  { id: 'conferencesLast30', label: 'Conferences (Last 30 Days)', group: 'Appearances & work', kind: 'count' },
  { id: 'draftsThisYear', label: 'Drafts (Documents) This Year', group: 'Appearances & work', kind: 'count' },
  { id: 'draftsLast30', label: 'Drafts (Documents), Last 30 Days', group: 'Appearances & work', kind: 'count' },
  // Outstanding
  { id: 'totalOutstanding', label: 'Total Outstanding', group: 'Outstanding', kind: 'money', link: 'outstanding' },
  { id: 'amountOverdue', label: 'Amount Overdue', group: 'Outstanding', kind: 'money', accent: 'red', link: 'outstanding' },
  { id: 'memosAwaitingPayment', label: 'Memos Awaiting Payment', group: 'Outstanding', kind: 'count', link: 'outstanding' },
  { id: 'writtenOffTotal', label: 'Written Off (Total)', group: 'Outstanding', kind: 'money' },
  // Draft memos (not yet issued)
  { id: 'draftMemosCount', label: 'Draft Memos (Count)', group: 'Drafts', kind: 'count', link: 'memos' },
  { id: 'draftMemosTotal', label: 'Draft Memos (Total Amount)', group: 'Drafts', kind: 'money', link: 'memos' },
]

/** The original six boxes, in their original order. */
export const DEFAULT_KPI_IDS = [
  'billedThisMonth',
  'billedThisYear',
  'appearancesThisYear',
  'receivedThisMonth',
  'receivedThisYear',
  'amountOverdue',
]

/** Parses the stored comma-separated selection into known ids ('' → defaults). */
export function parseKpiSelection(stored: string | null | undefined): string[] {
  const known = new Set(KPI_CATALOG.map((k) => k.id))
  const ids = (stored ?? '').split(',').map((s) => s.trim()).filter((s) => known.has(s))
  return ids.length ? ids : DEFAULT_KPI_IDS
}
