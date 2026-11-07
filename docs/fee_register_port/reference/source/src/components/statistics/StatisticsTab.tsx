import { useState } from 'react'
import { StatisticsPage } from '@/components/statistics/StatisticsPage'
import { cn } from '@/lib/cn'

/** The Statistics tab: Standard (period table) and Explore (pivots & charts). */
export function StatisticsTab() {
  const [mode, setMode] = useState<'standard' | 'explore'>('standard')
  return (
    <div className="mx-auto max-w-6xl space-y-4">
      <div className="flex gap-5 border-b border-gray-200">
        {([
          { id: 'standard', label: 'Standard' },
          { id: 'explore', label: 'Explore' },
        ] as const).map((t) => (
          <button
            key={t.id}
            onClick={() => setMode(t.id)}
            className={cn(
              '-mb-px border-b-2 px-1 pb-1.5 text-sm transition-colors',
              mode === t.id ? 'border-blue-600 font-semibold text-gray-900' : 'border-transparent text-gray-500 hover:text-gray-900',
            )}
          >
            {t.label}
          </button>
        ))}
      </div>
      <StatisticsPage mode={mode} />
    </div>
  )
}
