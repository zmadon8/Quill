import { useEffect, useMemo, useState } from 'react'
import { useFeebookStore } from '@/stores/useFeebookStore'
import { useNavStore } from '@/stores/useNavStore'
import { useToastStore, errorMessage } from '@/stores/useToastStore'
import { Button } from '@/components/ui/Button'
import { Select } from '@/components/ui/Select'
import { Card } from '@/components/ui/Card'
import { DataTable, ColumnsMenu, useTablePrefs, visibleColumns, type DTColumn } from '@/components/ui/DataTable'
import { recentFinancialYears } from '@/lib/financialYear'
import { displayDate } from '@/lib/formatDate'
import { PaymentEntryModal } from '@/components/feebook/PaymentEntryModal'
import type { BankAccountDTO, FeebookEntry } from '@/types/ipc'
import { Money } from '@/components/ui/Money'
import { formatMoney } from '@/lib/formatMoney'

export function FeebookPage() {
  const { entries, filter, loading, setFilter, load } = useFeebookStore()
  const push = useNavStore((s) => s.push)
  const show = useToastStore((s) => s.show)
  const [banks, setBanks] = useState<BankAccountDTO[]>([])
  // Firms present in the selected financial year's feebook entries, so the Firm
  // dropdown only offers firms with payments in that year (independent of the
  // currently-selected firm, so the list doesn't shrink as you pick one).
  const [fyScope, setFyScope] = useState<FeebookEntry[]>([])
  const [showAddPayment, setShowAddPayment] = useState(false)
  const [editPaymentId, setEditPaymentId] = useState<number | null>(null)
  // The first FY the user actively maintains; the FY filter won't offer years
  // before this (payments pre-dating it are hidden from the Feebook filter).
  const [initialFy, setInitialFy] = useState('2026-27')
  const totals = {
    paid: entries.reduce((a, e) => a + e.amountPaid, 0),
    tds: entries.reduce((a, e) => a + e.tds, 0),
    gross: entries.reduce((a, e) => a + e.paidPlusTds, 0),
  }
  const columns: Array<DTColumn<FeebookEntry>> = [
    { key: 'date', label: 'Date', width: 100, hideable: false, cell: (e) => displayDate(e.dateOfPayment), foot: () => `Totals (${entries.length})` },
    {
      key: 'memo', label: 'Memo No.', width: 130, hideable: false,
      cell: (e) =>
        e.memoNumber ? (
          <span title={e.memoTotal !== null ? `Memo total: ₹ ${formatMoney(e.memoTotal)}` : undefined}>
            {e.memoNumber}
          </span>
        ) : (
          '—'
        ),
    },
    {
      key: 'matter', label: 'Matter', width: 230, hideable: true,
      cell: (e) =>
        e.matterId !== null && e.matterName ? (
          <button
            className="w-full truncate text-left text-blue-700 hover:underline"
            title={e.matterName}
            onClick={() => push({ kind: 'matterDetail', matterId: e.matterId!, title: e.matterName! })}
          >
            {e.matterName}
          </button>
        ) : (
          '—'
        ),
    },
    { key: 'payee', label: 'Payee', width: 170, hideable: true, cell: (e) => e.payee ?? '—' },
    { key: 'paid', label: 'Paid', width: 110, align: 'right', hideable: true, cellClassName: 'font-semibold', cell: (e) => <>₹ <Money v={e.amountPaid} /></>, foot: () => <>₹ <Money v={totals.paid} /></> },
    { key: 'tds', label: 'TDS', width: 90, align: 'right', hideable: true, cell: (e) => <>₹ <Money v={e.tds} /></>, foot: () => <>₹ <Money v={totals.tds} /></> },
    { key: 'gross', label: 'Paid + TDS', width: 110, align: 'right', hideable: true, cell: (e) => <>₹ <Money v={e.paidPlusTds} /></>, foot: () => <>₹ <Money v={totals.gross} /></> },
    { key: 'bank', label: 'Bank', width: 120, hideable: true, cell: (e) => e.bankAccountName ?? '—' },
    { key: 'mode', label: 'Mode', width: 100, hideable: true, cell: (e) => e.paymentMode ?? '—' },
    {
      key: 'type', label: 'Type', width: 110, hideable: true,
      cell: (e) =>
        e.paymentType === 'Multiple' ? (
          <button
            className="text-blue-700 hover:underline"
            title={`Paid together with: ${e.groupMemoNumbers.join(', ')}`}
            onClick={() => show(`Paid together by one payment: ${e.groupMemoNumbers.join(', ')}`, 'info')}
          >
            Multiple ({e.allocationCount})
          </button>
        ) : (
          'Single'
        ),
    },
    {
      key: 'actions', label: '', width: 80, hideable: false,
      cell: (e) => (
        <Button size="sm" variant="secondary" onClick={() => setEditPaymentId(e.paymentId)}>
          Edit
        </Button>
      ),
    },
  ]
  const tablePrefs = useTablePrefs('feebook', columns)
  const refreshTick = useNavStore((s) => s.refreshTick)
  useEffect(() => {
    void load()
    void (async () => {
      const b = await window.api.settings.listBankAccounts()
      if (b.ok) setBanks(b.data)
      const s = await window.api.settings.get()
      if (s.ok) setInitialFy(s.data.feebookStartYear)
    })()
  }, [refreshTick])

  // Years offered in the FY filter: recent years, but never earlier than the
  // configured Initial FY.
  const fyOptions = useMemo(() => recentFinancialYears(8, initialFy), [initialFy])

  // Rebuild the Firm option list whenever the financial year changes.
  useEffect(() => {
    void (async () => {
      const res = await window.api.feebook.list({ financialYear: filter.financialYear })
      if (res.ok) setFyScope(res.data)
    })()
  }, [filter.financialYear, refreshTick])

  const firmOptions = useMemo(() => {
    const map = new Map<number, string>()
    for (const e of fyScope) if (e.firmId !== null && e.firmName) map.set(e.firmId, e.firmName)
    return [...map.entries()]
      .map(([id, name]) => ({ id, name }))
      .sort((a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase()))
  }, [fyScope])

  const exportExcel = async () => {
    const res = await window.api.feebook.exportExcel(
      filter,
      visibleColumns(tablePrefs, columns).map((c) => c.key),
    )
    if (!res.ok) show(errorMessage(res.error), 'error')
    else if (res.data.saved) show('Exported.', 'success')
  }

  return (
    <div className="mx-auto max-w-6xl space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-[1.75rem] font-normal leading-tight">Feebook</h2>
        <div className="flex gap-2">
          <Button variant="success" size="sm" onClick={() => setShowAddPayment(true)}>
            + Payment
          </Button>
          <Button variant="secondary" size="sm" onClick={exportExcel}>Export to Excel</Button>
        </div>
      </div>

      <Card className="flex flex-wrap items-end gap-3 p-3">
        <div>
          <label className="block text-xs text-gray-500">Financial Year</label>
          <Select
            value={filter.financialYear ?? ''}
            onChange={(e) => setFilter({ financialYear: e.target.value || undefined, firmId: undefined })}
          >
            {fyOptions.map((y) => <option key={y} value={y}>{y}</option>)}
          </Select>
        </div>
        <div>
          <label className="block text-xs text-gray-500">Firm</label>
          <Select value={filter.firmId ?? ''} onChange={(e) => setFilter({ firmId: e.target.value ? Number(e.target.value) : undefined })}>
            <option value="">All</option>
            {firmOptions.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
          </Select>
        </div>
        <div>
          <label className="block text-xs text-gray-500">Bank Account</label>
          <Select value={filter.bankAccountId ?? ''} onChange={(e) => setFilter({ bankAccountId: e.target.value ? Number(e.target.value) : undefined })}>
            <option value="">All</option>
            {banks.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
          </Select>
        </div>
        <label className="flex items-center gap-1 text-sm">
          <input type="checkbox" checked={filter.unaccountedOnly ?? false} onChange={(e) => setFilter({ unaccountedOnly: e.target.checked || undefined })} />
          Unaccounted payments only
        </label>
      </Card>

      {loading && entries.length === 0 ? (
        <p className="text-sm text-gray-500">Loading…</p>
      ) : entries.length === 0 ? (
        <p className="text-sm text-gray-500">No payment records match the current filters.</p>
      ) : (
        <Card className="overflow-hidden">
          <div className="flex justify-end border-b p-2">
            <ColumnsMenu prefs={tablePrefs} columns={columns} />
          </div>
          <DataTable
            prefs={tablePrefs}
            columns={columns}
            rows={entries}
            rowKey={(e) => e.allocationId ?? `p${e.paymentId}`}
          />
        </Card>
      )}

      {showAddPayment && (
        <PaymentEntryModal
          onClose={() => setShowAddPayment(false)}
          onSaved={() => {
            setShowAddPayment(false)
            void load()
          }}
        />
      )}

      {editPaymentId !== null && (
        <PaymentEntryModal
          paymentId={editPaymentId}
          onClose={() => setEditPaymentId(null)}
          onSaved={() => {
            setEditPaymentId(null)
            void load()
          }}
        />
      )}
    </div>
  )
}
