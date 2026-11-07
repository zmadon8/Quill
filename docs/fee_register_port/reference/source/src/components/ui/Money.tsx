import { formatMoney } from '@/lib/formatMoney'
import { useMoneyUnitStore } from '@/stores/useMoneyUnitStore'

/**
 * Renders a rupee figure in the user's chosen display mode. In truncated mode
 * the full amount appears on hover, so a shortened "6.7 lac" can always be
 * checked against the real number.
 */
export function Money({ v }: { v: number | null | undefined }) {
  const unit = useMoneyUnitStore((s) => s.unit)
  useMoneyUnitStore((s) => s.suffixes) // re-render when suffixes change
  const format = useMoneyUnitStore((s) => s.format)
  const text = format(v)
  const full = formatMoney(v)
  return <span title={unit === 'truncated' && text !== full ? `₹ ${full}` : undefined}>{text}</span>
}
