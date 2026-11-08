import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavStore } from '@/stores/useNavStore'
import { useToastStore, errorMessage } from '@/stores/useToastStore'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { Select } from '@/components/ui/Select'
import { Money } from '@/components/ui/Money'
import { MultiSelect } from '@/components/ui/MultiSelect'
import { StatusDot, outstandingEntryStatus } from '@/components/ui/StatusDot'
import { DataTable, ColumnsMenu, useTablePrefs, visibleColumns, type DTColumn } from '@/components/ui/DataTable'
import { PaymentEntryModal } from '@/components/feebook/PaymentEntryModal'
import { displayDate } from '@/lib/formatDate'
import type { OutstandingEntry, OutstandingGroup } from '@/types/ipc'

type ViewMode = 'grouped' | 'summary' | 'flat'
type FlatSort = 'firm' | 'partner' | 'matter' | 'date' | 'due'

/** An outstanding memo together with its partner id (from its group). */
type Row = OutstandingEntry & { partnerId: number }

const sum = (rows: Row[], f: (r: Row) => number) => rows.reduce((a, r) => a + f(r), 0)
const byText = (a: string, b: string) => a.toLowerCase().localeCompare(b.toLowerCase())

/**
 * Outstanding memos for one firm, or for ALL firms (firmId === null).
 *  - Grouped:  Partner → Matter → memos, with subtotals.
 *  - Summary:  one line per matter (subtotals only).
 *  - In order: a flat list with Firm / Partner / Matter columns and a sort.
 * Partners and matters can be multi-selected; rows can be ticked to settle
 * several memos with one payment.
 */
export function OutstandingDetail({
  firmId,
  firmName,
  onBack,
}: {
  firmId: number | null
  firmName: string
  onBack: () => void
}) {
  const push = useNavStore((s) => s.push)
  const refreshTick = useNavStore((s) => s.refreshTick)
  const show = useToastStore((s) => s.show)

  const [groups, setGroups] = useState<OutstandingGroup[]>([])
  const [loaded, setLoaded] = useState(false)
  const [includeWrittenOff, setIncludeWrittenOff] = useState(false)
  const [overdueOnly, setOverdueOnly] = useState(false)
  const [mode, setMode] = useState<ViewMode>(firmId === null ? 'flat' : 'grouped')
  const [flatSort, setFlatSort] = useState<FlatSort>('firm')
  const [firmSel, setFirmSel] = useState<number[] | null>(null)
  const [partnerSel, setPartnerSel] = useState<number[] | null>(null)
  const [matterSel, setMatterSel] = useState<number[] | null>(null)
  const [ticked, setTicked] = useState<Set<number>>(new Set())
  const [payMemoIds, setPayMemoIds] = useState<number[] | null>(null)

  const load = useCallback(async () => {
    const res = await window.api.outstanding.list({
      firmId: firmId ?? undefined,
      includeWrittenOff: includeWrittenOff || undefined,
      overdueOnly: overdueOnly || undefined,
    })
    if (res.ok) setGroups(res.data)
    else show(errorMessage(res.error), 'error')
    setLoaded(true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [firmId, includeWrittenOff, overdueOnly])

  useEffect(() => {
    void load()
  }, [load, refreshTick])

  // ---- filter options (derived from what is actually outstanding) ----
  const firmOptions = useMemo(() => {
    const m = new Map<number, string>()
    for (const g of groups) m.set(g.firmId, g.firmName)
    return [...m.entries()].map(([id, name]) => ({ id, name })).sort((a, b) => byText(a.name, b.name))
  }, [groups])

  // Groups of the chosen firms only (everything below is narrowed from this).
  const firmGroups = useMemo(() => {
    if (firmSel === null) return groups
    const ok = new Set(firmSel)
    return groups.filter((g) => ok.has(g.firmId))
  }, [groups, firmSel])

  const partnerOptions = useMemo(() => {
    const m = new Map<number, string>()
    for (const g of firmGroups) m.set(g.partnerId, g.partnerName)
    return [...m.entries()].map(([id, name]) => ({ id, name })).sort((a, b) => byText(a.name, b.name))
  }, [firmGroups])

  const partnerSet = useMemo(
    () => (partnerSel === null ? null : new Set(partnerSel)),
    [partnerSel],
  )

  // Matters offered are those of the chosen partners.
  const matterOptions = useMemo(() => {
    return firmGroups
      .filter((g) => !partnerSet || partnerSet.has(g.partnerId))
      .map((g) => ({ id: g.matterId, name: g.matterName }))
      .sort((a, b) => byText(a.name, b.name))
  }, [firmGroups, partnerSet])

  const matterSet = useMemo(() => {
    const allowed = new Set(matterOptions.map((o) => o.id))
    if (matterSel === null) return allowed
    return new Set(matterSel.filter((id) => allowed.has(id)))
  }, [matterOptions, matterSel])

  const visibleGroups = useMemo(
    () => firmGroups.filter((g) => matterSet.has(g.matterId)),
    [firmGroups, matterSet],
  )

  const rows: Row[] = useMemo(
    () => visibleGroups.flatMap((g) => g.entries.map((e) => ({ ...e, partnerId: g.partnerId }))),
    [visibleGroups],
  )

  const sortedFlat = useMemo(() => {
    const r = [...rows]
    const cmp: Record<FlatSort, (a: Row, b: Row) => number> = {
      firm: (a, b) => byText(a.firmName, b.firmName) || byText(a.partnerName, b.partnerName) || byText(a.matterName, b.matterName) || a.date.localeCompare(b.date),
      partner: (a, b) => byText(a.partnerName, b.partnerName) || byText(a.matterName, b.matterName) || a.date.localeCompare(b.date),
      matter: (a, b) => byText(a.matterName, b.matterName) || a.date.localeCompare(b.date),
      date: (a, b) => a.date.localeCompare(b.date) || a.memoId - b.memoId,
      due: (a, b) => b.due - a.due,
    }
    return r.sort(cmp[flatSort])
  }, [rows, flatSort])

  const partnerSections = useMemo(() => {
    const m = new Map<number, { partnerName: string; groups: OutstandingGroup[]; subtotal: number }>()
    for (const g of visibleGroups) {
      let s = m.get(g.partnerId)
      if (!s) {
        s = { partnerName: g.partnerName, groups: [], subtotal: 0 }
        m.set(g.partnerId, s)
      }
      s.groups.push(g)
      s.subtotal += g.subtotal
    }
    return [...m.values()].sort((a, b) => byText(a.partnerName, b.partnerName))
  }, [visibleGroups])

  const grandDue = sum(rows, (r) => r.due)

  const toggleTick = (id: number) =>
    setTicked((cur) => {
      const n = new Set(cur)
      if (n.has(id)) n.delete(id)
      else n.add(id)
      return n
    })
  // Only memos currently on screen can stay ticked.
  const tickedIds = rows.filter((r) => ticked.has(r.memoId)).map((r) => r.memoId)

  // ---- columns ----
  const buildColumns = (foot: Row[], footLabel: string): Array<DTColumn<Row>> => [
    {
      key: 'select', label: '', width: 36, hideable: false,
      cell: (r) => (
        <input
          type="checkbox"
          aria-label={`Select memo ${r.memoNumber}`}
          checked={ticked.has(r.memoId)}
          onChange={() => toggleTick(r.memoId)}
        />
      ),
    },
    { key: 'date', label: 'Date', width: 100, hideable: false, cell: (r) => displayDate(r.date), foot: () => footLabel },
    {
      key: 'memo', label: 'Memo No.', width: 150, hideable: false,
      cell: (r) => (
        <span className="flex items-center gap-2">
          <StatusDot status={outstandingEntryStatus(r)} />
          <button
            className="text-blue-700 hover:underline"
            onClick={() => push({ kind: 'memoForm', memoId: r.memoId, title: r.memoNumber })}
          >
            {r.memoNumber}
          </button>
        </span>
      ),
    },
    { key: 'firm', label: 'Firm', width: 170, hideable: true, cell: (r) => r.firmName },
    { key: 'partner', label: 'Group', width: 170, hideable: true, cell: (r) => r.partnerName },
    {
      key: 'matter', label: 'Matter', width: 230, hideable: true,
      cell: (r) => (
        <button
          className="w-full truncate text-left text-blue-700 hover:underline"
          title={r.matterName}
          onClick={() => push({ kind: 'matterDetail', matterId: r.matterId, title: r.matterName })}
        >
          {r.matterName}
        </button>
      ),
    },
    { key: 'total', label: 'Total Memo Amount', width: 130, align: 'right', hideable: true, cell: (r) => <>₹ <Money v={r.totalFees} /></>, foot: () => <>₹ <Money v={sum(foot, (r) => r.totalFees)} /></> },
    { key: 'net', label: 'Net of TDS', width: 110, align: 'right', hideable: true, cell: (r) => <>₹ <Money v={r.netOfTds} /></>, foot: () => <>₹ <Money v={sum(foot, (r) => r.netOfTds)} /></> },
    { key: 'paid', label: 'Already Paid', width: 110, align: 'right', hideable: true, cell: (r) => <>₹ <Money v={r.amountPaid} /></>, foot: () => <>₹ <Money v={sum(foot, (r) => r.amountPaid)} /></> },
    { key: 'due', label: 'Due', width: 110, align: 'right', hideable: false, cellClassName: 'font-bold', cell: (r) => <>₹ <Money v={r.due} /></>, foot: () => <span className="font-bold">₹ <Money v={sum(foot, (r) => r.due)} /></span> },
    {
      key: 'actions', label: '', width: 90, hideable: false,
      cell: (r) => (
        <Button size="sm" variant="success" onClick={() => setPayMemoIds([r.memoId])}>
          Payment
        </Button>
      ),
    },
  ]
  const allColumns = buildColumns([], '')
  const prefs = useTablePrefs('outstanding', allColumns)
  // Firm / Partner / Matter are only meaningful as columns in "In order" mode;
  // in the grouped view they are the headings.
  const hiddenInGrouped = new Set(['firm', 'partner', 'matter'])
  const groupedCols = (foot: Row[], label: string) =>
    buildColumns(foot, label).filter((c) => !hiddenInGrouped.has(c.key))

  // Summary view: one line per matter, with its own column set and preferences.
  const summaryRows = useMemo(
    () => [...visibleGroups].sort((a, b) => byText(a.firmName, b.firmName) || byText(a.partnerName, b.partnerName) || byText(a.matterName, b.matterName)),
    [visibleGroups],
  )
  const gsum = (f: (g: OutstandingGroup) => number) => summaryRows.reduce((a, g) => a + f(g), 0)
  const summaryColumns: Array<DTColumn<OutstandingGroup>> = [
    { key: 'firm', label: 'Firm', width: 190, hideable: true, cell: (g) => g.firmName, foot: () => 'Total' },
    { key: 'partner', label: 'Group', width: 190, hideable: true, cell: (g) => g.partnerName },
    {
      key: 'matter', label: 'Matter', width: 260, hideable: false,
      cell: (g) => (
        <button
          className="w-full truncate text-left text-blue-700 hover:underline"
          title={g.matterName}
          onClick={() => push({ kind: 'matterDetail', matterId: g.matterId, title: g.matterName })}
        >
          {g.matterName}
        </button>
      ),
    },
    { key: 'memos', label: 'Memos', width: 80, align: 'right', hideable: true, cell: (g) => g.entries.length, foot: () => gsum((g) => g.entries.length) },
    { key: 'total', label: 'Total', width: 120, align: 'right', hideable: true, cell: (g) => <>₹ <Money v={g.subtotalTotal} /></>, foot: () => <>₹ <Money v={gsum((g) => g.subtotalTotal)} /></> },
    { key: 'paid', label: 'Paid', width: 120, align: 'right', hideable: true, cell: (g) => <>₹ <Money v={g.subtotalPaid} /></>, foot: () => <>₹ <Money v={gsum((g) => g.subtotalPaid)} /></> },
    { key: 'due', label: 'Due', width: 120, align: 'right', hideable: false, cellClassName: 'font-bold', cell: (g) => <>₹ <Money v={g.subtotal} /></>, foot: () => <span className="font-bold">₹ <Money v={gsum((g) => g.subtotal)} /></span> },
  ]
  const summaryPrefs = useTablePrefs('outstandingSummary', summaryColumns)

  // The Columns menu always edits the table that is actually on screen.
  const menuPrefs = mode === 'summary' ? summaryPrefs : prefs
  const menuColumns: Array<{ key: string; label: string; hideable?: boolean; width?: number }> =
    mode === 'summary' ? summaryColumns : mode === 'grouped' ? groupedCols([], '') : allColumns

  // ---- export (honours filters + the visible columns) ----
  const exportExcel = async () => {
    if (visibleGroups.length === 0) {
      show('Nothing to export.', 'error')
      return
    }
    const safe = firmName.replace(/[\\/:*?"<>|]+/g, ' ').trim() || 'Firm'
    const keys = visibleColumns(prefs, allColumns).map((c) => c.key)
    const res = await window.api.outstanding.exportExcel(
      {
        firmId: firmId ?? undefined,
        selectedMatterIds: visibleGroups.map((g) => g.matterId),
        includeWrittenOff: includeWrittenOff || undefined,
        overdueOnly: overdueOnly || undefined,
      },
      firmId === null ? 'All Outstanding Memos.xlsx' : `Outstanding — ${safe}.xlsx`,
      keys,
    )
    if (!res.ok) show(errorMessage(res.error), 'error')
    else if (res.data.saved) show('Exported.', 'success')
  }

  return (
    <div className="mx-auto max-w-6xl space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Button variant="secondary" size="sm" onClick={onBack}>← View all Firms</Button>
          <h2 className="text-[1.75rem] font-normal leading-tight">
            {firmId === null ? 'Outstanding — All Memos' : `Outstanding — ${firmName}`}
          </h2>
        </div>
        <div className="flex items-center gap-2">
          <ColumnsMenu key={mode === 'summary' ? 'summary' : 'memos'} prefs={menuPrefs} columns={menuColumns} />
          <Button variant="secondary" size="sm" onClick={exportExcel}>Export to Excel</Button>
        </div>
      </div>

      <Card className="flex items-center justify-between p-4">
        <span className="text-sm font-medium text-gray-600">
          Total Outstanding ({rows.length} memo{rows.length === 1 ? '' : 's'})
        </span>
        <span className="text-xl font-semibold tabular-nums">₹ <Money v={grandDue} /></span>
      </Card>

      <Card className="flex flex-wrap items-end gap-3 p-3">
        {firmId === null && (
          <MultiSelect
            label="Firm"
            options={firmOptions}
            selected={firmSel}
            onChange={(v) => {
              setFirmSel(v)
              setPartnerSel(null)
              setMatterSel(null)
            }}
            allLabel="All Firms"
          />
        )}
        <MultiSelect
          label="Group"
          options={partnerOptions}
          selected={partnerSel}
          onChange={(v) => {
            setPartnerSel(v)
            setMatterSel(null)
          }}
          allLabel="All Groups"
        />
        <MultiSelect
          label="Matter"
          options={matterOptions}
          selected={matterSel}
          onChange={setMatterSel}
          allLabel="All Matters"
        />
        <div>
          <label className="block text-xs text-gray-500">View</label>
          <Select value={mode} onChange={(e) => setMode(e.target.value as ViewMode)}>
            <option value="grouped">Grouped (Partner → Matter)</option>
            <option value="summary">Summary (matter totals)</option>
            <option value="flat">In order (flat list)</option>
          </Select>
        </div>
        {mode === 'flat' && (
          <div>
            <label className="block text-xs text-gray-500">Sort by</label>
            <Select value={flatSort} onChange={(e) => setFlatSort(e.target.value as FlatSort)}>
              <option value="firm">Firm</option>
              <option value="partner">Group</option>
              <option value="matter">Matter</option>
              <option value="date">Date</option>
              <option value="due">Amount due (high → low)</option>
            </Select>
          </div>
        )}
        <label className="flex items-center gap-1 text-sm">
          <input type="checkbox" checked={includeWrittenOff} onChange={(e) => setIncludeWrittenOff(e.target.checked)} />
          Include Written Off Memos
        </label>
        <label className="flex items-center gap-1 text-sm">
          <input type="checkbox" checked={overdueOnly} onChange={(e) => setOverdueOnly(e.target.checked)} />
          View Overdue Memos Only
        </label>
      </Card>

      {mode !== 'summary' && rows.length > 0 && (
        <div className="flex items-center gap-3 text-sm">
          <button className="text-blue-700 hover:underline" onClick={() => setTicked(new Set(rows.map((r) => r.memoId)))}>
            Tick all
          </button>
          <button className="text-blue-700 hover:underline" onClick={() => setTicked(new Set())}>
            Untick all
          </button>
          <Button size="sm" variant="success" disabled={tickedIds.length === 0} onClick={() => setPayMemoIds(tickedIds)}>
            Mark paid{tickedIds.length > 0 ? ` (${tickedIds.length})` : ''}
          </Button>
          <span className="text-xs text-gray-500">
            Tick several memos and settle them with one payment.
          </span>
        </div>
      )}

      {!loaded ? (
        <p className="text-sm text-gray-500">Loading…</p>
      ) : rows.length === 0 ? (
        <Card className="p-6 text-center text-sm text-gray-500">
          No outstanding memos under the current filters.
        </Card>
      ) : mode === 'flat' ? (
        <Card className="overflow-hidden">
          <DataTable
            prefs={prefs}
            columns={buildColumns(sortedFlat, `Total (${sortedFlat.length})`)}
            rows={sortedFlat}
            rowKey={(r) => r.memoId}
          />
        </Card>
      ) : mode === 'summary' ? (
        <Card className="overflow-hidden">
          <DataTable prefs={summaryPrefs} columns={summaryColumns} rows={summaryRows} rowKey={(g) => g.matterId} />
        </Card>
      ) : (
        <>
          {partnerSections.map((section) => (
            <div key={section.partnerName} className="space-y-2">
              <div className="flex items-baseline justify-between border-b-2 border-gray-900 px-1 py-1.5 text-gray-900">
                <h3 className="text-lg font-medium">Group: {section.partnerName}</h3>
                <span className="text-sm font-medium tabular-nums">₹ <Money v={section.subtotal} /></span>
              </div>
              {section.groups.map((g) => {
                const gRows: Row[] = g.entries.map((e) => ({ ...e, partnerId: g.partnerId }))
                return (
                  <Card key={g.matterId} className="overflow-hidden">
                    <div className="bg-gray-50 px-3 py-2 text-sm font-semibold">
                      <button
                        className="text-blue-700 hover:underline"
                        onClick={() => push({ kind: 'matterDetail', matterId: g.matterId, title: g.matterName })}
                      >
                        {g.matterName}
                      </button>
                    </div>
                    <DataTable
                      prefs={prefs}
                      columns={groupedCols(gRows, 'Subtotal')}
                      rows={gRows}
                      rowKey={(r) => r.memoId}
                    />
                  </Card>
                )
              })}
            </div>
          ))}
          <div className="text-right text-base font-semibold">
            Total Outstanding: ₹ <Money v={grandDue} />
          </div>
        </>
      )}

      {payMemoIds && (
        <PaymentEntryModal
          initialMemoIds={payMemoIds}
          onClose={() => setPayMemoIds(null)}
          onSaved={() => {
            setPayMemoIds(null)
            setTicked(new Set())
            void load()
          }}
        />
      )}
    </div>
  )
}
