import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Popover } from '@/components/ui/Popover'
import { useMemoStore } from '@/stores/useMemoStore'
import { useNavStore } from '@/stores/useNavStore'
import { useSettingsStore } from '@/stores/useSettingsStore'
import { useUiPrefsStore } from '@/stores/useUiPrefsStore'
import { useToastStore, errorMessage } from '@/stores/useToastStore'
import { Button } from '@/components/ui/Button'
import { Select } from '@/components/ui/Select'
import { Card } from '@/components/ui/Card'
import { PaymentModal } from '@/components/memos/PaymentModal'
import { DraftMemosPage } from '@/components/memos/DraftMemosPage'
import { NewMemoDialog } from '@/components/memos/NewMemoDialog'
import { StatusDot, memoDisplayStatus } from '@/components/ui/StatusDot'
import { useColumnWidths, ColResizer } from '@/components/ui/ResizableColumns'
import { cn } from '@/lib/cn'
import { recentFinancialYears } from '@/lib/financialYear'
import { displayDate } from '@/lib/formatDate'
import type { MemoListItem } from '@/types/ipc'
import { Money } from '@/components/ui/Money'

type SubTab = 'memos' | 'drafts'

/** Memos screen with two sub-tabs: finalised Memos and Draft Memos (Req #7). */
export function MemosPage() {
  const [sub, setSub] = useState<SubTab>('memos')
  const [showNewMemo, setShowNewMemo] = useState(false)

  return (
    <div className="mx-auto max-w-6xl space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex gap-5 border-b border-gray-200">
          {([
            { id: 'memos', label: 'Memos' },
            { id: 'drafts', label: 'Draft Memos' },
          ] as const).map((t) => (
            <button
              key={t.id}
              onClick={() => setSub(t.id)}
              className={cn(
                '-mb-px border-b-2 px-1 pb-1.5 text-sm transition-colors',
                sub === t.id ? 'border-blue-600 font-semibold text-gray-900' : 'border-transparent text-gray-500 hover:text-gray-900',
              )}
            >
              {t.label}
            </button>
          ))}
        </div>
        <Button size="sm" onClick={() => setShowNewMemo(true)}>+ New Memo</Button>
      </div>

      {sub === 'memos' ? <MemosList /> : <DraftMemosPage />}

      {showNewMemo && <NewMemoDialog onClose={() => setShowNewMemo(false)} />}
    </div>
  )
}

function MemosList() {
  const { memos, filter, loading, setFilter, load } = useMemoStore()
  const push = useNavStore((s) => s.push)
  const show = useToastStore((s) => s.show)
  const refreshTick = useNavStore((s) => s.refreshTick)
  const hidePaid = useUiPrefsStore((s) => s.hidePaymentWhenPaid)
  const showStatusDots = useUiPrefsStore((s) => s.showStatusDots)

  const exportExcel = async () => {
    const res = await window.api.memos.bulkExportExcel(filter)
    if (!res.ok) show(errorMessage(res.error), 'error')
    else if (res.data.saved) show('Exported to Excel.', 'success')
  }
  // Resizable, persisted column widths (drag the header edges to adjust).
  const cols = useColumnWidths('memosTable', {
    memo: 150,
    date: 96,
    firm: 200,
    matter: 240,
    total: 110,
    net: 120,
    paid: 110,
    tds: 100,
    due: 110,
    paidOn: 110,
    actions: 110,
  })
  const [payFor, setPayFor] = useState<number | null>(null)
  const settings = useSettingsStore((st) => st.settings)
  const memosStart = settings?.memosStartYear
  // Which columns are visible (persisted). memo/actions are always shown.
  const [visibleCols, setVisibleCols] = useState<Record<string, boolean>>(() => {
    try {
      const raw = localStorage.getItem('memosVisibleCols')
      if (raw) return JSON.parse(raw) as Record<string, boolean>
    } catch { /* ignore */ }
    return {
      memo: true, date: true, firm: true, matter: true, total: true,
      net: true, paid: true, tds: true, due: true, paidOn: true, actions: true,
    }
  })
  const [showColMenu, setShowColMenu] = useState(false)
  const colAnchor = useRef<HTMLSpanElement>(null)
  useEffect(() => {
    try { localStorage.setItem('memosVisibleCols', JSON.stringify(visibleCols)) } catch { /* ignore */ }
  }, [visibleCols])
  // Firms/matters that actually have memos in the selected financial year, so
  // the filter dropdowns only offer relevant options (FURTHER #1).
  const [fyScope, setFyScope] = useState<MemoListItem[]>([])

  useEffect(() => {
    void load()
  }, [refreshTick])

  // Rebuild the firm/matter option lists whenever the financial year changes.
  useEffect(() => {
    void (async () => {
      const res = await window.api.memos.list({ financialYear: filter.financialYear })
      if (res.ok) setFyScope(res.data)
    })()
  }, [filter.financialYear, refreshTick])

  // Distinct firms present in the selected FY (sorted by name).
  const firmOptions = useMemo(() => {
    const map = new Map<number, string>()
    for (const m of fyScope) map.set(m.firmId, m.firmName)
    return [...map.entries()]
      .map(([id, name]) => ({ id, name }))
      .sort((a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase()))
  }, [fyScope])

  // Distinct matters present in the selected FY, narrowed to the chosen firm.
  const matterOptions = useMemo(() => {
    const map = new Map<number, string>()
    for (const m of fyScope) {
      if (filter.firmId !== undefined && m.firmId !== filter.firmId) continue
      map.set(m.matterId, m.matterName)
    }
    return [...map.entries()]
      .map(([id, name]) => ({ id, name }))
      .sort((a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase()))
  }, [fyScope, filter.firmId])

  // Column definitions: a single source for header, body cell, footer cell and
  // which can be toggled. memo + actions are mandatory (not hideable).
  type ColKey = 'memo' | 'date' | 'firm' | 'matter' | 'total' | 'net' | 'paid' | 'tds' | 'due' | 'paidOn' | 'actions'
  const money = (v: number) => <>₹ <Money v={v} /></>
  const sum = (f: (m: MemoListItem) => number) => memos.reduce((a, m) => a + f(m), 0)
  const COLUMNS: {
    key: ColKey
    label: string
    align: 'left' | 'right'
    hideable: boolean
    cell: (m: MemoListItem) => ReactNode
    foot?: () => ReactNode
  }[] = [
    {
      key: 'memo', label: 'Memo No.', align: 'left', hideable: false,
      cell: (m) => (
        <span className="flex items-center gap-2">
          <StatusDot status={memoDisplayStatus(m)} />
          <button className="truncate text-blue-700 hover:underline" onClick={() => push({ kind: 'memoForm', memoId: m.id, title: m.memoNumber })}>
            {m.memoNumber}
          </button>
        </span>
      ),
      foot: () => `Totals (${memos.length})`,
    },
    { key: 'date', label: 'Date', align: 'left', hideable: true, cell: (m) => displayDate(m.date) },
    {
      key: 'firm', label: 'Firm', align: 'left', hideable: true,
      cell: (m) => (
        <button className="w-full truncate text-left text-blue-700 hover:underline" onClick={() => push({ kind: 'firmDetail', firmId: m.firmId, title: m.firmName })}>
          {m.firmName}
        </button>
      ),
    },
    {
      key: 'matter', label: 'Matter', align: 'left', hideable: true,
      cell: (m) => (
        <button className="w-full truncate text-left text-blue-700 hover:underline" onClick={() => push({ kind: 'matterDetail', matterId: m.matterId, title: m.matterName })}>
          {m.matterName}
        </button>
      ),
    },
    { key: 'total', label: 'Total', align: 'right', hideable: true, cell: (m) => money(m.totalFees), foot: () => money(sum((m) => m.totalFees)) },
    { key: 'net', label: 'Net of TDS', align: 'right', hideable: true, cell: (m) => money(m.netOfTds), foot: () => money(sum((m) => m.netOfTds)) },
    { key: 'paid', label: 'Paid', align: 'right', hideable: true, cell: (m) => money(m.amountReceived), foot: () => money(sum((m) => m.amountReceived)) },
    { key: 'tds', label: 'TDS', align: 'right', hideable: true, cell: (m) => money(m.amountTds), foot: () => money(sum((m) => m.amountTds)) },
    {
      key: 'due', label: 'Due', align: 'right', hideable: true,
      cell: (m) => <span className="font-bold"><Money v={m.amountDue} /></span>,
      foot: () => <span className="font-bold"><Money v={sum((m) => m.amountDue)} /></span>,
    },
    { key: 'paidOn', label: 'Paid On', align: 'left', hideable: true, cell: (m) => (m.paymentCount > 1 ? 'Multiple' : displayDate(m.dateOfLastPayment) || '—') },
    {
      key: 'actions', label: 'Actions', align: 'right', hideable: false,
      cell: (m) =>
        hidePaid && m.status === 'Paid' ? null : (
          <Button size="sm" variant="success" onClick={() => setPayFor(m.id)}>Payment</Button>
        ),
    },
  ]
  const shownColumns = COLUMNS.filter((c) => visibleCols[c.key] !== false)

  return (
    <div className="space-y-4">
      <Card className="flex flex-wrap items-end gap-3 p-3">
        <div>
          <label className="block text-xs text-gray-500">Financial Year</label>
          <Select
            value={filter.financialYear ?? ''}
            onChange={(e) =>
              // Changing the year clears firm/matter, since those options are
              // year-scoped and may not exist in the newly-selected year.
              setFilter({
                financialYear: e.target.value || undefined,
                firmId: undefined,
                matterId: undefined,
              })
            }
          >
            {recentFinancialYears(8, memosStart).map((y) => (
              <option key={y} value={y}>{y}</option>
            ))}
          </Select>
        </div>
        <div>
          <label className="block text-xs text-gray-500">Firm</label>
          <Select
            value={filter.firmId ?? ''}
            onChange={(e) =>
              setFilter({
                firmId: e.target.value ? Number(e.target.value) : undefined,
                matterId: undefined, // reset matter when firm changes
              })
            }
          >
            <option value="">All</option>
            {firmOptions.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
          </Select>
        </div>
        <div>
          <label className="block text-xs text-gray-500">Matter</label>
          <Select
            value={filter.matterId ?? ''}
            onChange={(e) => setFilter({ matterId: e.target.value ? Number(e.target.value) : undefined })}
          >
            <option value="">All</option>
            {matterOptions.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
          </Select>
        </div>
        <div className="relative ml-auto flex items-center gap-3">
          <label className="flex items-center gap-1 text-sm">
            <input
              type="checkbox"
              checked={filter.unpaidOnly ?? false}
              onChange={(e) => setFilter({ unpaidOnly: e.target.checked || undefined })}
            />
            Unpaid only
          </label>
          <span ref={colAnchor} className="inline-block">
            <Button variant="secondary" size="sm" onClick={() => setShowColMenu((v) => !v)}>
              Columns ▾
            </Button>
          </span>
          {showColMenu && (
            <Popover anchor={colAnchor} onClose={() => setShowColMenu(false)}>
              <div>
                <p className="mb-1 px-1 text-xs font-semibold uppercase text-gray-500">Show columns</p>
                {COLUMNS.filter((c) => c.hideable).map((c) => (
                  <label key={c.key} className="flex cursor-pointer items-center gap-2 rounded px-1 py-1 text-sm hover:bg-gray-50">
                    <input
                      type="checkbox"
                      checked={visibleCols[c.key] !== false}
                      onChange={(e) => setVisibleCols((v) => ({ ...v, [c.key]: e.target.checked }))}
                    />
                    {c.label}
                  </label>
                ))}
              </div>
            </Popover>
          )}
          <Button variant="secondary" size="sm" onClick={exportExcel}>Export to Excel</Button>
        </div>
      </Card>

      {loading && memos.length === 0 ? (
        <p className="text-sm text-gray-500">Loading…</p>
      ) : memos.length === 0 ? (
        <Card className="p-6 text-center text-sm text-gray-500">
          No memos match the current filters. Adjust the filters above or create one with “+ New Memo”.
        </Card>
      ) : (
        <Card className="overflow-hidden">
          {/* Status legend so the badge colours are self-explanatory. Hidden when
              the coloured status dots are switched off in Settings. */}
          {showStatusDots && (
          <div className="flex flex-wrap items-center gap-4 border-b bg-gray-50 px-3 py-2 text-xs text-gray-600">
            <span className="font-medium uppercase text-gray-500">Status:</span>
            {([
              ['Paid', 'bg-green-500'],
              ['Unpaid', 'bg-amber-500'],
              ['Overdue', 'bg-red-500'],
              ['Written Off', 'bg-gray-400'],
            ] as const).map(([label, dot]) => (
              <span key={label} className="inline-flex items-center gap-1.5">
                <span className={`h-1.5 w-1.5 rounded-[1px] ${dot}`} />
                {label}
              </span>
            ))}
          </div>
          )}
          <div className="max-h-[70vh] overflow-auto">
            <table className="w-full table-fixed text-sm">
              <colgroup>
                {shownColumns.map((c) => (
                  <col key={c.key} style={{ width: `${cols.width(c.key)}px` }} />
                ))}
              </colgroup>
              <thead className="sticky top-0 z-10 text-left text-xs uppercase">
                <tr>
                  {shownColumns.map((c) => (
                    <th
                      key={c.key}
                      className={cn('relative px-3 py-2', c.align === 'right' && 'text-right')}
                    >
                      {c.label}
                      {c.key !== 'actions' && <ColResizer onDrag={(dx) => cols.resize(c.key, dx)} />}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y">
                {memos.map((m) => (
                  <tr key={m.id}>
                    {shownColumns.map((c) => (
                      <td
                        key={c.key}
                        className={cn(
                          'px-3 py-2',
                          c.align === 'right' ? 'whitespace-nowrap text-right tabular-nums' : 'truncate',
                        )}
                      >
                        {c.cell(m)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t-2 bg-gray-50 font-semibold">
                  {shownColumns.map((c) => (
                    <td
                      key={c.key}
                      className={cn(
                        'px-3 py-2',
                        c.align === 'right' ? 'whitespace-nowrap text-right tabular-nums' : 'truncate',
                      )}
                    >
                      {c.foot ? c.foot() : null}
                    </td>
                  ))}
                </tr>
              </tfoot>
            </table>
          </div>
        </Card>
      )}

      {payFor !== null && (
        <PaymentModal
          memoId={payFor}
          onClose={() => {
            setPayFor(null)
            void load()
          }}
        />
      )}
    </div>
  )
}
