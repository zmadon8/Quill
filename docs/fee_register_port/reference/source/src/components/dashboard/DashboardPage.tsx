import { useEffect, useState } from 'react'
import { useNavStore } from '@/stores/useNavStore'
import { useSettingsStore } from '@/stores/useSettingsStore'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { cn } from '@/lib/cn'
import { Money } from '@/components/ui/Money'
import { displayDate } from '@/lib/formatDate'
import { KPI_CATALOG, parseKpiSelection, DEFAULT_KPI_IDS } from '@/lib/dashboardKpis'
import type { RecentMatterDTO } from '@/types/ipc'

/**
 * Overview: user-selected KPI boxes plus recently billed matters.
 * (Statistics now has its own top-level tab.)
 */
export function DashboardPage() {
  const setTab = useNavStore((s) => s.setTab)
  const push = useNavStore((s) => s.push)
  const refreshTick = useNavStore((s) => s.refreshTick)
  const settings = useSettingsStore((s) => s.settings)
  const saveSettings = useSettingsStore((s) => s.save)
  const [kpis, setKpis] = useState<Record<string, number>>({})
  const [recentMatters, setRecentMatters] = useState<RecentMatterDTO[]>([])
  const [customising, setCustomising] = useState(false)

  useEffect(() => {
    void (async () => {
      const k = await window.api.dashboard.kpis()
      if (k.ok) setKpis(k.data)
      const rm = await window.api.memos.listRecentMatters(10)
      if (rm.ok) setRecentMatters(rm.data)
    })()
  }, [refreshTick])

  const selected = parseKpiSelection(settings?.dashboardKpis)
  const boxes = selected
    .map((id) => KPI_CATALOG.find((k) => k.id === id))
    .filter((k): k is NonNullable<typeof k> => !!k)

  return (
    <div className="mx-auto max-w-6xl space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-[1.75rem] font-normal leading-tight">Overview</h1>
        <Button size="sm" variant="secondary" onClick={() => setCustomising(true)}>
          Customise
        </Button>
      </div>

      <div className="grid grid-cols-1 border-b border-t-[3px] border-double border-gray-900 md:grid-cols-3">
        {boxes.map((k, i) => {
          const v = kpis[k.id] ?? 0
          const lastRow = i >= Math.floor((boxes.length - 1) / 3) * 3
          return (
            <div
              key={k.id}
              {...(k.link ? { onClick: () => setTab(k.link!), role: 'link', tabIndex: 0 } : {})}
              className={cn(
                'px-4 py-3',
                !lastRow && 'border-b border-gray-200',
                i % 3 !== 0 && 'md:border-l md:border-gray-200',
                i % 3 === 0 && 'md:pl-0',
                k.link && 'cursor-pointer hover:bg-gray-100',
              )}
            >
              <div className={cn('text-[11px] font-semibold uppercase tracking-[0.08em]', k.accent === 'red' ? 'text-blue-700' : 'text-gray-500')}>
                {k.label}
              </div>
              <div className={cn('mt-1 font-serif text-[1.75rem] leading-tight', k.accent === 'red' ? 'text-blue-700' : 'text-gray-900')}>
                {k.kind === 'money' ? (
                  <>
                    ₹ <Money v={v} />
                  </>
                ) : (
                  String(v)
                )}
              </div>
            </div>
          )
        })}
      </div>

      <Card className="overflow-hidden border-0 bg-transparent">
        <div className="border-b border-gray-900 px-3 py-2 font-serif text-lg text-gray-900">
          Recently Billed Matters
        </div>
        {recentMatters.length === 0 ? (
          <p className="px-3 py-6 text-center text-sm text-gray-500">
            No memos issued yet. Create one from a matter or the Memos tab to get started.
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase">
              <tr>
                <th className="px-3 py-2">Matter</th>
                <th className="px-3 py-2">Group</th>
                <th className="px-3 py-2">Last Memo</th>
                <th className="px-3 py-2 text-right">Memos</th>
                <th className="px-3 py-2 text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {recentMatters.map((rm) => (
                <tr key={rm.matterId}>
                  <td className="px-3 py-2">
                    <button
                      className="text-blue-700 hover:underline"
                      onClick={() => push({ kind: 'matterDetail', matterId: rm.matterId, title: rm.matterName })}
                    >
                      {rm.matterName}
                    </button>
                  </td>
                  <td className="px-3 py-2">
                    <button
                      className="text-blue-700 hover:underline"
                      onClick={() => push({ kind: 'firmDetail', firmId: rm.firmId, title: rm.firmName })}
                    >
                      {rm.firmName}
                    </button>
                  </td>
                  <td className="px-3 py-2">
                    {rm.lastMemoNumber ? `${rm.lastMemoNumber} · ` : ''}
                    {displayDate(rm.lastMemoDate)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{rm.memoCount}</td>
                  <td className="px-3 py-2 text-right">
                    {rm.isArchived ? (
                      <span className="text-xs text-gray-400">archived</span>
                    ) : (
                      <div className="flex justify-end gap-1">
                        {rm.lastMemoId != null && (
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={() =>
                              push({
                                kind: 'memoForm',
                                basedOnId: rm.lastMemoId!,
                                title: `Copy of last memo — ${rm.matterName}`,
                              })
                            }
                          >
                            Copy last memo
                          </Button>
                        )}
                        <Button
                          size="sm"
                          onClick={() =>
                            push({ kind: 'memoForm', matterId: rm.matterId, title: `New Memo — ${rm.matterName}` })
                          }
                        >
                          + Memo
                        </Button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {customising && (
        <CustomiseModal
          initial={selected}
          onClose={() => setCustomising(false)}
          onSave={async (ids) => {
            const ok = await saveSettings({ dashboardKpis: ids.join(',') })
            if (ok) setCustomising(false)
          }}
        />
      )}
    </div>
  )
}

function CustomiseModal({
  initial,
  onClose,
  onSave,
}: {
  initial: string[]
  onClose: () => void
  onSave: (ids: string[]) => void
}) {
  const [ids, setIds] = useState<string[]>(initial)
  const groups = Array.from(new Set(KPI_CATALOG.map((k) => k.group)))

  const toggle = (id: string) =>
    setIds((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]))
  const move = (i: number, d: -1 | 1) =>
    setIds((cur) => {
      const j = i + d
      if (j < 0 || j >= cur.length) return cur
      const next = cur.slice()
      ;[next[i], next[j]] = [next[j]!, next[i]!]
      return next
    })

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="max-h-[85vh] w-[720px] overflow-y-auto rounded-sm border border-gray-900 bg-gray-50 p-5 shadow-[0_6px_24px_rgba(28,27,25,0.18)]">
        <h2 className="mb-3 text-xl font-medium">Customise Overview boxes</h2>
        <div className="grid grid-cols-2 gap-5">
          <div className="space-y-3">
            {groups.map((g) => (
              <div key={g}>
                <div className="mb-1 text-xs font-semibold uppercase text-gray-500">{g}</div>
                {KPI_CATALOG.filter((k) => k.group === g).map((k) => (
                  <label key={k.id} className="flex items-center gap-2 py-0.5 text-sm">
                    <input type="checkbox" checked={ids.includes(k.id)} onChange={() => toggle(k.id)} />
                    {k.label}
                  </label>
                ))}
              </div>
            ))}
          </div>
          <div>
            <div className="mb-1 text-xs font-semibold uppercase text-gray-500">Order</div>
            {ids.length === 0 && <p className="text-sm text-gray-500">No boxes selected.</p>}
            {ids.map((id, i) => {
              const k = KPI_CATALOG.find((x) => x.id === id)
              if (!k) return null
              return (
                <div key={id} className="flex items-center justify-between border-b py-1 text-sm">
                  <span>{k.label}</span>
                  <span className="flex gap-1">
                    <Button size="sm" variant="ghost" aria-label={`Move ${k.label} up`} disabled={i === 0} onClick={() => move(i, -1)}>
                      ↑
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-label={`Move ${k.label} down`}
                      disabled={i === ids.length - 1}
                      onClick={() => move(i, 1)}
                    >
                      ↓
                    </Button>
                  </span>
                </div>
              )
            })}
          </div>
        </div>
        <div className="mt-4 flex justify-between">
          <Button variant="ghost" onClick={() => setIds(DEFAULT_KPI_IDS)}>
            Reset to default
          </Button>
          <div className="flex gap-2">
            <Button variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button onClick={() => onSave(ids)}>Save</Button>
          </div>
        </div>
      </div>
    </div>
  )
}
