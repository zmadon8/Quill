import { useEffect, useState } from 'react'
import { displayDate } from '@/lib/formatDate'
import type { MatterPayee } from '@/types/ipc'

/**
 * Preview of payees already entered on payments for other memos of the same
 * matter(s). Click one to use it. Shows nothing when there are none.
 */
export function PayeeSuggestions({
  matterIds,
  current,
  onPick,
}: {
  matterIds: number[]
  current: string
  onPick: (payee: string) => void
}) {
  const [payees, setPayees] = useState<MatterPayee[]>([])
  const key = [...new Set(matterIds)].sort((a, b) => a - b).join(',')

  useEffect(() => {
    const ids = key ? key.split(',').map(Number) : []
    if (ids.length === 0) {
      setPayees([])
      return
    }
    let cancelled = false
    void (async () => {
      const res = await window.api.payments.payeesForMatters(ids)
      if (!cancelled && res.ok) setPayees(res.data)
    })()
    return () => {
      cancelled = true
    }
  }, [key])

  if (payees.length === 0) return null
  return (
    <div className="mt-1.5">
      <div className="text-[11px] font-semibold uppercase tracking-[0.07em] text-gray-500">
        Already used for this matter
      </div>
      <div className="mt-1 flex flex-wrap gap-1.5">
        {payees.map((p) => {
          const active = p.payee.toLowerCase() === current.trim().toLowerCase()
          return (
            <button
              key={p.payee}
              type="button"
              onClick={() => onPick(p.payee)}
              title={`${p.count} payment${p.count === 1 ? '' : 's'}, last on ${displayDate(p.lastDate)}`}
              className={
                'rounded-sm border px-2 py-0.5 text-xs ' +
                (active
                  ? 'border-blue-600 bg-blue-50 text-blue-700'
                  : 'border-gray-300 text-gray-700 hover:border-gray-900')
              }
            >
              {p.payee}
              <span className="ml-1 text-gray-400">· {p.count}</span>
            </button>
          )
        })}
      </div>
    </div>
  )
}
