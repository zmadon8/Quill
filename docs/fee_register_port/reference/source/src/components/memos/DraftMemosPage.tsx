import { useEffect, useState, useCallback } from 'react'
import { useNavStore } from '@/stores/useNavStore'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { DataTable, ColumnsMenu, useTablePrefs, type DTColumn } from '@/components/ui/DataTable'
import { displayDate } from '@/lib/formatDate'
import type { MemoListItem } from '@/types/ipc'
import { Money } from '@/components/ui/Money'

/** Lists all draft (unnumbered) memos across matters (Req #3). */
export function DraftMemosPage() {
  const [drafts, setDrafts] = useState<MemoListItem[]>([])
  const [loaded, setLoaded] = useState(false)
  const push = useNavStore((s) => s.push)
  const refreshTick = useNavStore((s) => s.refreshTick)

  const load = useCallback(async () => {
    const res = await window.api.memos.listDrafts()
    if (res.ok) setDrafts(res.data)
    setLoaded(true)
  }, [])

  useEffect(() => {
    void load()
  }, [load, refreshTick])

  const columns: Array<DTColumn<MemoListItem>> = [
    {
      key: 'edit', label: '', width: 80, hideable: false,
      cell: (m) => (
        <Button size="sm" onClick={() => push({ kind: 'memoForm', memoId: m.id, title: 'Draft Memo' })}>
          Edit
        </Button>
      ),
      foot: () => 'Total',
    },
    { key: 'date', label: 'Date', width: 100, cell: (m) => displayDate(m.date) || '—' },
    {
      key: 'matter', label: 'Matter', width: 260, hideable: false,
      cell: (m) => (
        <button
          className="text-blue-700 hover:underline"
          onClick={() => push({ kind: 'matterDetail', matterId: m.matterId, title: m.matterName })}
        >
          {m.matterName}
        </button>
      ),
    },
    {
      key: 'firm', label: 'Group', width: 200, hideable: true,
      cell: (m) => (
        <button
          className="text-blue-700 hover:underline"
          onClick={() => push({ kind: 'firmDetail', firmId: m.firmId, title: m.firmName })}
        >
          {m.firmName}
        </button>
      ),
    },
    {
      key: 'total', label: 'Total', width: 120, align: 'right',
      cell: (m) => <>₹ <Money v={m.totalFees} /></>,
      foot: () => <>₹ <Money v={drafts.reduce((a, m) => a + m.totalFees, 0)} /></>,
    },
  ]
  const prefs = useTablePrefs('draftMemos', columns)

  return (
    <div className="space-y-4">
      {!loaded ? (
        <p className="text-sm text-gray-500">Loading…</p>
      ) : drafts.length === 0 ? (
        <p className="text-sm text-gray-500">No draft memos. Create one from a matter and click “Save as Draft”.</p>
      ) : (
        <Card className="overflow-hidden">
          <div className="flex justify-end border-b p-2">
            <ColumnsMenu prefs={prefs} columns={columns} />
          </div>
          <DataTable prefs={prefs} columns={columns} rows={drafts} rowKey={(m) => m.id} />
        </Card>
      )}
    </div>
  )
}
