import { useEffect, useMemo, useState } from 'react'
import { useOutstandingStore } from '@/stores/useOutstandingStore'
import { useNavStore } from '@/stores/useNavStore'
import { useToastStore, errorMessage } from '@/stores/useToastStore'
import { Button } from '@/components/ui/Button'
import { Select } from '@/components/ui/Select'
import { Card } from '@/components/ui/Card'
import { Money } from '@/components/ui/Money'
import { OutstandingDetail } from '@/components/outstanding/OutstandingDetail'
import type { OutstandingFirmSummary, OutstandingSort } from '@/types/ipc'

/**
 * Outstanding Memos. Default view is the firm-wise summary; "View" opens a
 * firm's memos and "All memos" opens every firm's memos in one list.
 */
export function OutstandingPage() {
  const push = useNavStore((s) => s.push)
  const refreshTick = useNavStore((s) => s.refreshTick)
  const show = useToastStore((s) => s.show)
  const viewFirmRequest = useOutstandingStore((s) => s.viewFirmRequest)
  const clearViewFirmRequest = useOutstandingStore((s) => s.clearViewFirmRequest)

  const [firmSort, setFirmSort] = useState<OutstandingSort>('amount')
  const [firmRows, setFirmRows] = useState<OutstandingFirmSummary[]>([])
  const [loaded, setLoaded] = useState(false)
  const [summaryIncludeWrittenOff, setSummaryIncludeWrittenOff] = useState(false)
  const [summaryOverdueOnly, setSummaryOverdueOnly] = useState(false)

  // null = firm summary; id null = all firms
  const [view, setView] = useState<{ id: number | null; name: string } | null>(null)

  const summaryFilter = useMemo(
    () => ({
      includeWrittenOff: summaryIncludeWrittenOff || undefined,
      overdueOnly: summaryOverdueOnly || undefined,
    }),
    [summaryIncludeWrittenOff, summaryOverdueOnly],
  )

  useEffect(() => {
    void (async () => {
      const res = await window.api.outstanding.listByFirm(summaryFilter, firmSort)
      if (res.ok) setFirmRows(res.data)
      else show(errorMessage(res.error), 'error')
      setLoaded(true)
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [firmSort, summaryFilter, refreshTick, view])

  // Arrived from a Firm page: open that firm's detail directly.
  useEffect(() => {
    if (viewFirmRequest == null || !loaded) return
    const row = firmRows.find((r) => r.firmId === viewFirmRequest)
    setView({ id: viewFirmRequest, name: row?.firmName ?? 'Firm' })
    clearViewFirmRequest()
  }, [viewFirmRequest, firmRows, loaded, clearViewFirmRequest])

  const firmGrand = firmRows.reduce((a, r) => a + r.outstanding, 0)

  const exportSummary = async () => {
    const res = await window.api.outstanding.exportByFirmExcel(summaryFilter, firmSort)
    if (!res.ok) show(errorMessage(res.error), 'error')
    else if (res.data.saved) show('Exported.', 'success')
  }

  if (view) {
    return <OutstandingDetail firmId={view.id} firmName={view.name} onBack={() => setView(null)} />
  }

  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-[1.75rem] font-normal leading-tight">Outstanding Memos</h2>
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="sm" onClick={exportSummary}>Export Summary</Button>
          <Button size="sm" onClick={() => setView({ id: null, name: 'All Firms' })}>
            All memos, all firms
          </Button>
        </div>
      </div>

      <Card className="flex flex-wrap items-end gap-3 p-3">
        <div>
          <label className="block text-xs text-gray-500">Sort By</label>
          <Select value={firmSort} onChange={(e) => setFirmSort(e.target.value as OutstandingSort)}>
            <option value="amount">Amount (high → low)</option>
            <option value="name">Firm name (A → Z)</option>
          </Select>
        </div>
        <label className="flex items-center gap-1 text-sm">
          <input
            type="checkbox"
            checked={summaryIncludeWrittenOff}
            onChange={(e) => setSummaryIncludeWrittenOff(e.target.checked)}
          />
          Include Written Off Memos
        </label>
        <label className="flex items-center gap-1 text-sm">
          <input
            type="checkbox"
            checked={summaryOverdueOnly}
            onChange={(e) => setSummaryOverdueOnly(e.target.checked)}
          />
          View Overdue Memos Only
        </label>
      </Card>

      {!loaded ? (
        <p className="text-sm text-gray-500">Loading…</p>
      ) : firmRows.length === 0 ? (
        <Card className="p-6 text-center text-sm text-gray-500">
          No outstanding balances match the current filters.
        </Card>
      ) : (
        <Card className="overflow-hidden">
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase">
              <tr>
                <th className="px-3 py-2">Firm</th>
                <th className="px-3 py-2">Action</th>
                <th className="px-3 py-2 text-right">Memos</th>
                <th className="px-3 py-2 text-right">Outstanding</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {firmRows.map((r) => (
                <tr key={r.firmId}>
                  <td className="px-3 py-2">
                    <button
                      className="text-blue-700 hover:underline"
                      onClick={() => push({ kind: 'firmDetail', firmId: r.firmId, title: r.firmName })}
                    >
                      {r.firmName}
                    </button>
                  </td>
                  <td className="px-3 py-2">
                    <Button size="sm" variant="secondary" onClick={() => setView({ id: r.firmId, name: r.firmName })}>
                      View
                    </Button>
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{r.memoCount}</td>
                  <td className="px-3 py-2 text-right tabular-nums">₹ <Money v={r.outstanding} /></td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t-2 bg-gray-50 font-semibold">
                <td className="px-3 py-2">Total ({firmRows.length} firms)</td>
                <td className="px-3 py-2" />
                <td className="px-3 py-2 text-right tabular-nums">
                  {firmRows.reduce((a, r) => a + r.memoCount, 0)}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">₹ <Money v={firmGrand} /></td>
              </tr>
            </tfoot>
          </table>
        </Card>
      )}
    </div>
  )
}
