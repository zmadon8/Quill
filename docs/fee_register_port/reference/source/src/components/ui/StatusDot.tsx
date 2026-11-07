import { cn } from '@/lib/cn'
import { useUiPrefsStore } from '@/stores/useUiPrefsStore'

export type MemoStatus = 'Paid' | 'Unpaid' | 'Overdue' | 'Written Off' | 'Draft'

/** Derives a single display status from a memo's flags, in priority order. */
export function memoDisplayStatus(m: {
  writtenOff: boolean
  isOverdue?: boolean
  status: 'Paid' | 'Unpaid'
}): MemoStatus {
  if (m.writtenOff) return 'Written Off'
  if (m.isOverdue) return 'Overdue'
  return m.status
}

/**
 * Status for an Outstanding-list entry (which is unpaid by definition, so it
 * never resolves to 'Paid'). Same priority as memoDisplayStatus, adapted to the
 * OutstandingEntry field names.
 */
export function outstandingEntryStatus(e: { isWrittenOff: boolean; isOverdue: boolean }): MemoStatus {
  if (e.isWrittenOff) return 'Written Off'
  if (e.isOverdue) return 'Overdue'
  return 'Unpaid'
}

const styles: Record<MemoStatus, { dot: string }> = {
  Paid: { dot: 'bg-green-700' },
  Unpaid: { dot: 'bg-amber-600' },
  Overdue: { dot: 'bg-red-700' },
  'Written Off': { dot: 'bg-gray-400' },
  Draft: { dot: 'bg-blue-400' },
}

/**
 * Just the coloured status dot, with the status name as a hover tooltip. Used
 * where space is tight and a legend already explains the colours.
 */
export function StatusDot({ status }: { status: MemoStatus }) {
  // The dots can be switched off entirely in Settings.
  const show = useUiPrefsStore((s) => s.showStatusDots)
  if (!show) return null
  return (
    <span
      title={status}
      aria-label={status}
      className={cn('inline-block h-2.5 w-2.5 shrink-0 rounded-[1px]', styles[status].dot)}
    />
  )
}

/** Status as readable text, with the coloured dot in front when dots are on. */
export function StatusLabel({ status }: { status: MemoStatus }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <StatusDot status={status} />
      <span>{status}</span>
    </span>
  )
}
