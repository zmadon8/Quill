import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Popover } from '@/components/ui/Popover'
import { useNavStore } from '@/stores/useNavStore'
import { useToastStore, errorMessage } from '@/stores/useToastStore'
import { Button } from '@/components/ui/Button'
import { Select } from '@/components/ui/Select'
import { Card } from '@/components/ui/Card'
import { StatisticsExplore } from './StatisticsExplore'
import { currentFinancialYear, recentFinancialYears } from '@/lib/financialYear'
import type { StatGranularity, PeriodStatistics, StatPeriod, YearEndSummary, StatOptions } from '@/types/ipc'
import { Money } from '@/components/ui/Money'

type MetricKey = keyof StatPeriod

/** Rows of the comparison table (metrics down, periods across). */
const METRIC_ROWS: Array<{ key: MetricKey; label: string; money?: boolean; suffix?: string }> = [
  { key: 'numAppearances', label: 'Appearances' },
  { key: 'numConferences', label: 'Conferences' },
  { key: 'numDrafts', label: 'Drafts' },
  { key: 'amountBilled', label: 'Amount Billed', money: true },
  { key: 'amountRecovered', label: 'Amount Recovered', money: true },
  { key: 'percentRecovered', label: '% Recovered', suffix: '%' },
  { key: 'amountReceived', label: 'Amount Received', money: true },
  { key: 'amountReceivedPlusTds', label: 'Received + TDS', money: true },
  { key: 'feesPerDay', label: 'Fees / Day', money: true },
  { key: 'daysCompleted', label: 'Days Completed' },
  { key: 'appearancesPerWeek', label: 'Appearances / Week' },
  { key: 'conferencesPerWeek', label: 'Conferences / Week' },
  { key: 'draftsPerWeek', label: 'Drafts / Week' },
  { key: 'feesPerWeek', label: 'Fees / Week', money: true },
]
const METRIC_STORE = 'stats:metrics:hidden'

function loadHidden(): Set<string> {
  try {
    return new Set(JSON.parse(localStorage.getItem(METRIC_STORE) ?? '[]') as string[])
  } catch {
    return new Set()
  }
}

export function StatisticsPage({ mode = 'standard' }: { mode?: 'standard' | 'explore' } = {}) {
  const show = useToastStore((s) => s.show)
  const refreshTick = useNavStore((s) => s.refreshTick)
  const [granularity, setGranularity] = useState<StatGranularity>('month')
  const [fy, setFy] = useState(currentFinancialYear())
  const [data, setData] = useState<PeriodStatistics | null>(null)
  const [yearEnd, setYearEnd] = useState<YearEndSummary | null>(null)
  const [includeDrafts, setIncludeDrafts] = useState(false)
  const [hidden, setHidden] = useState<Set<string>>(loadHidden)
  const [showMetrics, setShowMetrics] = useState(false)
  const metricsAnchor = useRef<HTMLDivElement>(null)
  // Initial FY cutoff: statistics ignore anything before this year.
  const [initialFy, setInitialFy] = useState('2026-27')

  const fyOptions = useMemo(() => recentFinancialYears(8, initialFy), [initialFy])

  useEffect(() => {
    void (async () => {
      const s = await window.api.settings.get()
      if (s.ok) {
        setInitialFy(s.data.initialFinancialYear)
        setFy((cur) => (cur < s.data.initialFinancialYear ? s.data.initialFinancialYear : cur))
      }
    })()
  }, [])

  const options: StatOptions = useMemo(
    () => ({ excludeFutureMonths: true, proRateCurrentMonth: true, minFinancialYear: initialFy, includeDrafts }),
    [initialFy, includeDrafts],
  )

  const load = useCallback(async () => {
    const res = await window.api.statistics.getPeriods(
      granularity,
      granularity === 'financialYear' ? null : fy,
      options,
    )
    if (res.ok) setData(res.data)
    else show(errorMessage(res.error), 'error')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [granularity, fy, options])

  useEffect(() => {
    void load()
  }, [load, refreshTick])

  useEffect(() => {
    void (async () => {
      const res = await window.api.statistics.yearEndSummary(fy, options)
      if (res.ok) setYearEnd(res.data)
    })()
  }, [fy, options, refreshTick])

  const toggleMetric = (key: string) =>
    setHidden((cur) => {
      const next = new Set(cur)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      try {
        localStorage.setItem(METRIC_STORE, JSON.stringify([...next]))
      } catch {
        /* ignore */
      }
      return next
    })

  const taxSummary = async () => {
    const res = await window.api.statistics.exportSummaryText(fy)
    if (!res.ok) show(errorMessage(res.error), 'error')
    else if (res.data.saved) show('Tax summary exported.', 'success')
  }
  const annualSummary = async () => {
    const res = await window.api.statistics.exportAnnualSummary(fy, options)
    if (!res.ok) show(errorMessage(res.error), 'error')
    else if (res.data.saved) show('Annual summary exported.', 'success')
  }
  const exportTableExcel = async () => {
    const res = await window.api.statistics.exportExcel(
      granularity,
      granularity === 'financialYear' ? null : fy,
      options,
    )
    if (!res.ok) show(errorMessage(res.error), 'error')
    else if (res.data.saved) show('Exported to Excel.', 'success')
  }

  const cell = (v: number | undefined, row: (typeof METRIC_ROWS)[number]) => {
    const num = typeof v === 'number' && isFinite(v) ? v : 0
    if (row.money) return <>₹ <Money v={num} /></>
    return row.suffix ? `${num}${row.suffix}` : String(num)
  }

  // Whole-period total for a metric. Counts and amounts sum; rates are
  // recomputed from the summed underlying figures.
  const total = (periods: StatPeriod[], key: MetricKey): number => {
    const sum = (k: MetricKey) =>
      periods.reduce((a, p) => {
        const v = p[k]
        return a + (typeof v === 'number' && isFinite(v) ? v : 0)
      }, 0)
    const days = sum('daysCompleted')
    const perWeek = (count: number) => (days > 0 ? Math.round(((count * 5) / days) * 100) / 100 : 0)
    switch (key) {
      case 'appearancesPerWeek': return perWeek(sum('numAppearances'))
      case 'conferencesPerWeek': return perWeek(sum('numConferences'))
      case 'draftsPerWeek': return perWeek(sum('numDrafts'))
      case 'feesPerWeek': return perWeek(sum('amountBilled'))
      case 'feesPerDay': return days > 0 ? Math.round(sum('amountBilled') / days) : 0
      case 'percentRecovered': {
        const billed = sum('amountBilled')
        return billed > 0 ? Math.round((sum('amountRecovered') / billed) * 10000) / 100 : 0
      }
      default: return sum(key)
    }
  }

  if (mode === 'explore') {
    return (
      <div className="mx-auto max-w-6xl">
        <StatisticsExplore />
      </div>
    )
  }

  const shownRows = METRIC_ROWS.filter((r) => !hidden.has(r.key as string))
  const showTotalCol = granularity !== 'financialYear'

  return (
    <div className="mx-auto max-w-6xl space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-[1.75rem] font-normal leading-tight">Statistics</h2>
        <div className="flex flex-wrap items-center gap-2">
          <Select value={granularity} onChange={(e) => setGranularity(e.target.value as StatGranularity)}>
            <option value="month">Month-wise</option>
            <option value="quarter">Quarter-wise</option>
            <option value="financialYear">Year-wise</option>
          </Select>
          <Select value={fy} onChange={(e) => setFy(e.target.value)}>
            {fyOptions.map((y) => <option key={y} value={y}>{y}</option>)}
          </Select>
          <label
            className="flex items-center gap-1 text-sm text-gray-600"
            title="Count draft memos as if issued in the current month"
          >
            <input type="checkbox" checked={includeDrafts} onChange={(e) => setIncludeDrafts(e.target.checked)} />
            Include draft memos
          </label>
          <div ref={metricsAnchor} className="relative">
            <Button variant="secondary" size="sm" onClick={() => setShowMetrics((v) => !v)}>Metrics ▾</Button>
            {showMetrics && (
              <Popover anchor={metricsAnchor} onClose={() => setShowMetrics(false)}>
                <div>
                  <p className="mb-1 px-1 text-xs font-semibold uppercase text-gray-500">Show rows</p>
                  {METRIC_ROWS.map((r) => (
                    <label key={r.key as string} className="flex cursor-pointer items-center gap-2 rounded px-1 py-1 text-sm hover:bg-gray-50">
                      <input type="checkbox" checked={!hidden.has(r.key as string)} onChange={() => toggleMetric(r.key as string)} />
                      {r.label}
                    </label>
                  ))}
                </div>
              </Popover>
            )}
          </div>
          <Button variant="secondary" size="sm" onClick={exportTableExcel}>Export to Excel</Button>
        </div>
      </div>

      {yearEnd && (
        <Card className="p-4">
          <div className="mb-2 flex items-center justify-between">
            <div className="text-sm font-semibold">Year-End Summary — {yearEnd.financialYear}</div>
            <div className="flex gap-2">
              <Button variant="secondary" size="sm" onClick={taxSummary}>Tax Summary</Button>
              <Button variant="secondary" size="sm" onClick={annualSummary}>Annual Summary</Button>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-8">
            {([
              ['Appearances', String(yearEnd.numAppearances)],
              ['Appearances / Week', String(yearEnd.appearancesPerWeek)],
              ['Memos', String(yearEnd.memoCount)],
              ['New Matters', String(yearEnd.newMatters)],
              ['Firms', String(yearEnd.activeFirms)],
            ] as const).map(([label, v]) => (
              <div key={label}>
                <div className="text-xs uppercase text-gray-500">{label}</div>
                <div className="text-lg font-semibold tabular-nums">{v}</div>
              </div>
            ))}
            {([
              ['Billed', yearEnd.totalBilled],
              ['Received', yearEnd.totalReceived],
              ['TDS', yearEnd.totalTds],
            ] as const).map(([label, v]) => (
              <div key={label}>
                <div className="text-xs uppercase text-gray-500">{label}</div>
                <div className="text-lg font-semibold tabular-nums">₹ <Money v={v} /></div>
              </div>
            ))}
          </div>
          <p className="mt-2 text-xs text-gray-400">
            Working days and manual corrections are edited in Settings → Edit Statistics.
          </p>
        </Card>
      )}

      {!data ? (
        <p className="text-sm text-gray-500">Loading…</p>
      ) : (
        <Card className="max-h-[70vh] overflow-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 z-10 text-left text-xs uppercase">
              <tr>
                <th className="sticky left-0 z-20 whitespace-nowrap bg-gray-50 px-3 py-2">Metric</th>
                {showTotalCol && <th className="whitespace-nowrap bg-gray-100 px-3 py-2 text-right">Total</th>}
                {data.periods.map((p) => (
                  <th
                    key={p.key}
                    className={
                      'whitespace-nowrap px-3 py-2 text-right ' +
                      (p.isCurrentMonth ? 'bg-gray-100' : p.isFuture ? 'text-gray-400' : '')
                    }
                  >
                    {p.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y">
              {shownRows.map((row) => (
                <tr key={row.key as string}>
                  <td className="sticky left-0 z-10 whitespace-nowrap bg-inherit px-3 py-2 font-medium">{row.label}</td>
                  {showTotalCol && (
                    <td className="whitespace-nowrap bg-gray-100/70 px-3 py-2 text-right font-semibold tabular-nums">
                      {cell(total(data.periods, row.key), row)}
                    </td>
                  )}
                  {data.periods.map((p) => {
                    const manual = p.overridden?.includes(row.key as string)
                    return (
                      <td
                        key={p.key}
                        title={manual ? 'Manually set in Settings → Edit Statistics' : undefined}
                        className={
                          'whitespace-nowrap px-3 py-2 text-right tabular-nums ' +
                          (p.isCurrentMonth ? 'bg-gray-100 ' : '') +
                          (manual ? 'italic text-blue-700' : '')
                        }
                      >
                        {cell(p[row.key] as number, row)}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  )
}
