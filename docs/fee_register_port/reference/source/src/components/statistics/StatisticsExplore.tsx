import { useCallback, useEffect, useMemo, useState } from 'react'
import { useToastStore, errorMessage } from '@/stores/useToastStore'
import { Button } from '@/components/ui/Button'
import { Select } from '@/components/ui/Select'
import { Input } from '@/components/ui/Input'
import { Card } from '@/components/ui/Card'
import { PivotChart, type ChartType } from './PivotChart'
import { MultiSelect } from '@/components/ui/MultiSelect'
import { currentFinancialYear, recentFinancialYears } from '@/lib/financialYear'
import { Money } from '@/components/ui/Money'
import type {
  PivotMeasure,
  PivotRowDim,
  PivotColDim,
  PivotRequest,
  PivotResult,
  SavedView,
  FirmSummary,
} from '@/types/ipc'

const MEASURES: { id: PivotMeasure; label: string; timeOnly?: boolean }[] = [
  { id: 'billed', label: 'Amount Billed' },
  { id: 'received', label: 'Amount Received' },
  { id: 'receivedPlusTds', label: 'Received + TDS' },
  { id: 'appearances', label: 'Appearances' },
  { id: 'conferences', label: 'Conferences' },
  { id: 'drafts', label: 'Drafts' },
  { id: 'memos', label: 'Memos (count)' },
  { id: 'matters', label: 'Matters (distinct)' },
  { id: 'mattersNew', label: 'Matters (new)' },
  { id: 'appearancesPerWeek', label: 'Appearances / Week (time rows)', timeOnly: true },
  { id: 'feesPerWeek', label: 'Fees / Week (time rows)', timeOnly: true },
]

const TIME_ROWS: PivotRowDim[] = ['month', 'quarter', 'financialYear']

const CHART_TYPES: { id: ChartType; label: string }[] = [
  { id: 'bar', label: 'Bars (grouped)' },
  { id: 'stacked', label: 'Bars (stacked)' },
  { id: 'line', label: 'Line' },
  { id: 'area', label: 'Area' },
  { id: 'pie', label: 'Pie (row totals)' },
]

const ROW_DIMS: { id: PivotRowDim; label: string }[] = [
  { id: 'month', label: 'Month' },
  { id: 'quarter', label: 'Quarter' },
  { id: 'financialYear', label: 'Financial Year' },
  { id: 'calendarMonth', label: 'Calendar Month (across years)' },
  { id: 'firm', label: 'Firm' },
  { id: 'partner', label: 'Group' },
  { id: 'matter', label: 'Matter' },
]

const COL_DIMS: { id: PivotColDim; label: string }[] = [
  { id: 'none', label: 'None (single column)' },
  { id: 'financialYear', label: 'Financial Year' },
  { id: 'calendarMonth', label: 'Calendar Month' },
]

/**
 * Flexible statistics explorer implementing Options 1–5:
 *  1. Measure picker (what to count/sum)
 *  2. Pivot builder (rows × columns)
 *  3. Period compare — a 2-column pivot adds a % change column
 *  4. Chart toggle (grouped bar chart)
 *  5. Saved views (persist a configuration)
 */
export function StatisticsExplore() {
  const show = useToastStore((s) => s.show)

  // Initial FY cutoff: Explore must not offer or return data before this year.
  const [initialFy, setInitialFy] = useState('2026-27')
  // Year options, never earlier than the Initial FY (oldest allowed last).
  const fys = useMemo(() => recentFinancialYears(8, initialFy), [initialFy])

  const [measure, setMeasure] = useState<PivotMeasure>('billed')
  const [rowDim, setRowDim] = useState<PivotRowDim>('month')
  const [colDim, setColDim] = useState<PivotColDim>('financialYear')
  // null = all firms; otherwise an explicit selection.
  const [firmSel, setFirmSel] = useState<number[] | null>(null)
  const [chartType, setChartType] = useState<ChartType>('bar')
  const [maWindow, setMaWindow] = useState(0)
  const [fromFy, setFromFy] = useState<string>(currentFinancialYear())
  const [toFy, setToFy] = useState<string>(currentFinancialYear())
  const [showChart, setShowChart] = useState(true)

  const [firms, setFirms] = useState<FirmSummary[]>([])
  const [data, setData] = useState<PivotResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [views, setViews] = useState<SavedView[]>([])

  useEffect(() => {
    void (async () => {
      const f = await window.api.firms.list('all')
      if (f.ok) setFirms(f.data)
      const v = await window.api.statistics.listSavedViews()
      if (v.ok) setViews(v.data)
      const s = await window.api.settings.get()
      if (s.ok) {
        setInitialFy(s.data.initialFinancialYear)
        // Snap the default FY range into the allowed window.
        setFromFy((cur) => (cur < s.data.initialFinancialYear ? s.data.initialFinancialYear : cur))
        setToFy((cur) => (cur < s.data.initialFinancialYear ? s.data.initialFinancialYear : cur))
      }
    })()
  }, [])

  const load = useCallback(async () => {
    if (firmSel !== null && firmSel.length === 0) return // nothing selected
    setLoading(true)
    // Hard guard: never let fromFy drop below the Initial FY, even if a saved
    // view stored an earlier range. The pivot treats fromFy as a >= bound.
    const effectiveFrom = fromFy < initialFy ? initialFy : fromFy
    const effectiveTo = toFy < initialFy ? initialFy : toFy
    const req: PivotRequest = {
      measure,
      rowDim,
      colDim,
      firmIds: firmSel === null ? undefined : firmSel,
      fromFy: effectiveFrom,
      toFy: effectiveTo,
    }
    const res = await window.api.statistics.pivot(req)
    if (res.ok) setData(res.data)
    else show(errorMessage(res.error), 'error')
    setLoading(false)
  }, [measure, rowDim, colDim, firmSel, fromFy, toFy, initialFy])

  useEffect(() => {
    void load()
  }, [load])

  const saveView = async () => {
    const name = window.prompt('Name this view:')
    if (!name) return
    const res = await window.api.statistics.saveSavedView({
      name,
      measure,
      rowDim,
      colDim,
      // Saved views keep a single firm; a multi-selection is saved as "all".
      firmId: firmSel !== null && firmSel.length === 1 ? firmSel[0] : null,
      fromFy,
      toFy,
    })
    if (res.ok) {
      setViews(res.data)
      show('View saved.', 'success')
    } else show(errorMessage(res.error), 'error')
  }

  const applyView = (v: SavedView) => {
    setMeasure(v.measure)
    setRowDim(v.rowDim)
    setColDim(v.colDim)
    setFirmSel(v.firmId === null ? null : [v.firmId])
    // Clamp a saved view's range up to the Initial FY so older views can't
    // reintroduce pre-cutoff years.
    const oldest = fys[fys.length - 1] ?? initialFy
    const from = v.fromFy ?? oldest
    const to = v.toFy ?? (fys[0] ?? initialFy)
    setFromFy(from < initialFy ? initialFy : from)
    setToFy(to < initialFy ? initialFy : to)
  }

  const deleteView = async (id: number) => {
    const res = await window.api.statistics.deleteSavedView(id)
    if (res.ok) setViews(res.data)
  }

  const perWeek = MEASURES.find((m) => m.id === measure)?.timeOnly === true
  // Per-week measures only make sense on time rows, for all firms, one column.
  const changeMeasure = (m: PivotMeasure) => {
    setMeasure(m)
    if (MEASURES.find((x) => x.id === m)?.timeOnly) {
      if (!TIME_ROWS.includes(rowDim)) setRowDim('month')
      setColDim('none')
      setFirmSel(null)
    }
  }

  const fmt = (v: number) => (data?.money ? <>₹ <Money v={v} /></> : String(Math.round(v)))

  // Option 3: when exactly two columns, show a % change (second vs first).
  const showChange = data !== null && data.colDim !== 'none' && data.columns.length === 2
  const pctChange = (row: PivotResult['rows'][number]): string => {
    if (!showChange || !data) return ''
    const a = row.cells[data.columns[0].key] ?? 0
    const b = row.cells[data.columns[1].key] ?? 0
    if (a === 0) return b === 0 ? '0%' : '—'
    const pct = ((b - a) / a) * 100
    return `${pct >= 0 ? '+' : ''}${pct.toFixed(0)}%`
  }

  return (
    <div className="space-y-4">
      {/* Controls */}
      <Card className="flex flex-wrap items-end gap-3 p-3">
        <div>
          <label className="block text-xs text-gray-500">Measure</label>
          <Select value={measure} onChange={(e) => changeMeasure(e.target.value as PivotMeasure)}>
            {MEASURES.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
          </Select>
        </div>
        <div>
          <label className="block text-xs text-gray-500">Rows</label>
          <Select value={rowDim} onChange={(e) => setRowDim(e.target.value as PivotRowDim)}>
            {ROW_DIMS.filter((d) => !perWeek || TIME_ROWS.includes(d.id)).map((d) => (
              <option key={d.id} value={d.id}>{d.label}</option>
            ))}
          </Select>
        </div>
        <div>
          <label className="block text-xs text-gray-500">Columns</label>
          <Select value={colDim} disabled={perWeek} onChange={(e) => setColDim(e.target.value as PivotColDim)}>
            {COL_DIMS.map((d) => <option key={d.id} value={d.id}>{d.label}</option>)}
          </Select>
        </div>
        {perWeek ? (
          <div>
            <label className="block text-xs text-gray-500">Firm</label>
            <span className="inline-block py-2 text-sm text-gray-500">All (per-week is firm-wide)</span>
          </div>
        ) : (
          <MultiSelect
            label="Firms"
            options={firms.map((f) => ({ id: f.id, name: f.name }))}
            selected={firmSel}
            onChange={setFirmSel}
            allLabel="All firms"
          />
        )}
        <div>
          <label className="block text-xs text-gray-500">From FY</label>
          <Select value={fromFy} onChange={(e) => setFromFy(e.target.value)}>
            {fys.map((y) => <option key={y} value={y}>{y}</option>)}
          </Select>
        </div>
        <div>
          <label className="block text-xs text-gray-500">To FY</label>
          <Select value={toFy} onChange={(e) => setToFy(e.target.value)}>
            {fys.map((y) => <option key={y} value={y}>{y}</option>)}
          </Select>
        </div>
        <label className="flex items-center gap-1 text-sm">
          <input type="checkbox" checked={showChart} onChange={(e) => setShowChart(e.target.checked)} />
          Chart
        </label>
        {showChart && (
          <>
            <div>
              <label className="block text-xs text-gray-500">Chart type</label>
              <Select value={chartType} onChange={(e) => setChartType(e.target.value as ChartType)}>
                {CHART_TYPES.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
              </Select>
            </div>
            <div>
              <label className="block text-xs text-gray-500">Moving average</label>
              <Select
                value={maWindow}
                disabled={chartType === 'pie' || chartType === 'stacked'}
                onChange={(e) => setMaWindow(Number(e.target.value))}
              >
                <option value={0}>Off</option>
                <option value={3}>3 periods</option>
                <option value={6}>6 periods</option>
                <option value={12}>12 periods</option>
              </Select>
            </div>
          </>
        )}
        <Button variant="secondary" size="sm" onClick={saveView}>Save View</Button>
      </Card>

      {/* Saved views (Option 5) */}
      {views.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium uppercase text-gray-500">Saved:</span>
          {views.map((v) => (
            <span key={v.id} className="inline-flex items-center gap-1 rounded-sm border border-gray-300 px-2 py-0.5 text-xs text-gray-700">
              <button className="hover:underline" onClick={() => applyView(v)}>{v.name}</button>
              <button className="text-gray-400 hover:text-red-700" onClick={() => void deleteView(v.id)} aria-label="Delete view">×</button>
            </span>
          ))}
        </div>
      )}

      {firmSel !== null && firmSel.length === 0 ? (
        <Card className="p-6 text-center text-sm text-gray-500">Select at least one firm.</Card>
      ) : loading || !data ? (
        <p className="text-sm text-gray-500">Loading…</p>
      ) : data.rows.length === 0 ? (
        <Card className="p-6 text-center text-sm text-gray-500">No data for this selection.</Card>
      ) : (
        <>
          {/* Chart (Option 4) */}
          {showChart && (
            <Card className="p-3">
              <PivotChart data={data} type={chartType} maWindow={maWindow} />
            </Card>
          )}

          {/* Table (Options 1–3) */}
          <Card className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase">
                <tr>
                  <th className="px-3 py-2">
                    {ROW_DIMS.find((d) => d.id === data.rowDim)?.label ?? 'Row'}
                  </th>
                  {data.columns.map((c) => (
                    <th key={c.key} className="px-3 py-2 text-right">{c.label}</th>
                  ))}
                  {showChange && <th className="px-3 py-2 text-right">Change</th>}
                  <th className="px-3 py-2 text-right">Total</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {data.rows.map((r) => (
                  <tr key={r.key}>
                    <td className="px-3 py-2 font-medium">{r.label}</td>
                    {data.columns.map((c) => (
                      <td key={c.key} className="px-3 py-2 text-right tabular-nums">{fmt(r.cells[c.key] ?? 0)}</td>
                    ))}
                    {showChange && (
                      <td className="px-3 py-2 text-right tabular-nums">{pctChange(r)}</td>
                    )}
                    <td className="px-3 py-2 text-right font-semibold tabular-nums">{fmt(r.total)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t-2 bg-gray-50 font-semibold">
                  <td className="px-3 py-2">Total</td>
                  {data.columns.map((c) => (
                    <td key={c.key} className="px-3 py-2 text-right tabular-nums">
                      {fmt(data.columnTotals[c.key] ?? 0)}
                    </td>
                  ))}
                  {showChange && <td className="px-3 py-2" />}
                  <td className="px-3 py-2 text-right tabular-nums">{fmt(data.grandTotal)}</td>
                </tr>
              </tfoot>
            </table>
          </Card>
        </>
      )}
    </div>
  )
}
