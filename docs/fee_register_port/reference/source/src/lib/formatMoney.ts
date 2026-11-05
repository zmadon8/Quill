/**
 * Renderer-side money formatting. By default amounts are displayed with Indian
 * digit grouping and NO decimal places (Req #1), e.g. 1234567 -> "12,34,567".
 *
 * The display MODE controls how figures appear in tables:
 *   - 'full'      → 3,12,451   (grouped integer, no suffix)
 *   - 'truncated' → auto-scales by magnitude, UP TO 2 decimals (trailing zeros
 *                   trimmed), using Indian units with user-chosen suffixes:
 *                     0–9        → shown as is  e.g. 7        → "7"
 *                     < 1 lac    → thousands    e.g. 5,300    → "5.3k"
 *                     < 1 crore  → lacs         e.g. 6,70,000 → "6.7 lac"
 *                     ≥ 1 crore  → crores       e.g. 3,50,00,000 → "3.5 cr"
 */
export type MoneyUnit = 'full' | 'truncated'

/** The text appended for thousands / lacs / crores in truncated mode. */
export interface MoneySuffixes {
  thousands: string
  lac: string
  crore: string
}

export const DEFAULT_MONEY_SUFFIXES: MoneySuffixes = { thousands: 'k', lac: 'lac', crore: 'cr' }

export function formatMoney(n: number | null | undefined): string {
  const v = typeof n === 'number' && isFinite(n) ? Math.round(n) : 0
  return v.toLocaleString('en-IN', { maximumFractionDigits: 0 })
}

/**
 * Scales a value and renders up to 2 decimals (trailing zeros trimmed), Indian
 * grouping. A multi-character suffix is separated by a space ("6.7 lac"); a
 * single-character one is attached ("5.3k").
 */
function scaled(value: number, divisor: number, suffix: string): string {
  const text = (value / divisor).toLocaleString('en-IN', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  })
  const s = suffix.trim()
  return `${text}${s.length > 1 ? ' ' : ''}${s}`
}

/**
 * Formats a figure for the chosen display mode. 'full' matches formatMoney.
 * 'truncated' auto-selects thousands / lacs / crores by the figure's magnitude
 * (using the absolute value, so negatives scale the same way). Single-digit
 * amounts and 0 are shown as the actual number.
 */
export function formatMoneyUnit(
  n: number | null | undefined,
  unit: MoneyUnit = 'full',
  suffixes: MoneySuffixes = DEFAULT_MONEY_SUFFIXES,
): string {
  const v = typeof n === 'number' && isFinite(n) ? n : 0
  if (unit === 'full') return formatMoney(v)
  const abs = Math.abs(v)
  if (abs < 10) return formatMoney(v) // 0 and single digits: show the real number
  if (abs < 100_000) return scaled(v, 1_000, suffixes.thousands)
  if (abs < 10_000_000) return scaled(v, 100_000, suffixes.lac)
  return scaled(v, 10_000_000, suffixes.crore)
}
