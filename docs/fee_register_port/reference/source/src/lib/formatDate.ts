/**
 * Renderer-side date formatting helpers.
 *
 * The app stores dates as ISO 8601 strings (YYYY-MM-DD). Everything the user
 * sees is DD.MM.YYYY (dots) — in tables, forms (see <DateInput/>) and exports.
 * Storage/transport stays ISO; only display is reformatted.
 */

/** Formats an ISO date (YYYY-MM-DD…) as DD.MM.YYYY. Falls back to the raw value. */
export function displayDate(iso: string | null | undefined): string {
  if (!iso) return ''
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso)
  if (!m) return iso
  return `${m[3]}.${m[2]}.${m[1]}`
}

/** Today's date as an ISO string (YYYY-MM-DD) in the local timezone. */
export function todayIso(now: Date = new Date()): string {
  return now.toLocaleDateString('en-CA')
}
