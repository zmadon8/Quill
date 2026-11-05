import { useEffect, useRef, useState } from 'react'
import { displayDate, todayIso } from '@/lib/formatDate'
import { cn } from '@/lib/cn'

/**
 * Date field that always reads and writes DD.MM.YYYY (dots), independent of the
 * computer's regional settings (the native <input type="date"> cannot do this).
 * The value in/out is an ISO string (YYYY-MM-DD) or '' when blank.
 *
 *  - Type a date (dots, dashes or slashes are all accepted); it is validated.
 *  - 📅 opens the calendar; "Today" (when enabled) fills today's date directly.
 */

/** Parses "16.10.2026", "16-10-2026", "16/10/26" or "16102026" into ISO, or null. */
export function parseDisplayDate(text: string): string | null {
  const t = text.trim()
  let d: string, m: string, y: string
  let match = /^(\d{1,2})[./-](\d{1,2})[./-](\d{2}|\d{4})$/.exec(t)
  if (match) {
    ;[, d, m, y] = match
  } else if ((match = /^(\d{2})(\d{2})(\d{4})$/.exec(t))) {
    ;[, d, m, y] = match
  } else return null
  if (y.length === 2) y = `20${y}`
  const day = Number(d)
  const month = Number(m)
  const year = Number(y)
  if (month < 1 || month > 12 || day < 1 || year < 1900 || year > 2200) return null
  const dim = new Date(year, month, 0).getDate()
  if (day > dim) return null
  return `${String(year).padStart(4, '0')}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`
}

interface Props {
  value: string
  onChange: (iso: string) => void
  /** Show a "Today" button that fills today's date without opening the calendar. */
  showToday?: boolean
  disabled?: boolean
  className?: string
}

export function DateInput({ value, onChange, showToday = false, disabled, className }: Props) {
  const [text, setText] = useState(displayDate(value))
  const [invalid, setInvalid] = useState(false)
  const picker = useRef<HTMLInputElement>(null)

  // Keep the visible text in step when the value changes from outside
  // (Today button, calendar, loading a saved memo).
  useEffect(() => {
    setText(displayDate(value))
    setInvalid(false)
  }, [value])

  const commit = (raw: string) => {
    setText(raw)
    if (raw.trim() === '') {
      setInvalid(false)
      onChange('')
      return
    }
    const iso = parseDisplayDate(raw)
    if (iso) {
      setInvalid(false)
      if (iso !== value) onChange(iso)
    } else {
      // Not a complete date yet (still typing): flag it only once it looks finished.
      setInvalid(raw.trim().length >= 8)
    }
  }

  return (
    <div className={cn('flex items-center gap-1', className)}>
      <input
        type="text"
        inputMode="numeric"
        placeholder="dd.mm.yyyy"
        disabled={disabled}
        value={text}
        onChange={(e) => commit(e.target.value)}
        onBlur={() => {
          // Snap back to the last valid date if the text is incomplete/invalid.
          setText(displayDate(value))
          setInvalid(false)
        }}
        aria-invalid={invalid || undefined}
        className={cn(
          'w-full min-w-0 rounded-sm border bg-white px-3 py-1.5 text-sm text-gray-900 focus:outline-none',
          invalid ? 'border-red-500 focus:border-red-500' : 'border-gray-300 focus:border-blue-500',
          disabled && 'bg-gray-100 text-gray-500',
        )}
      />
      <button
        type="button"
        disabled={disabled}
        title="Open calendar"
        aria-label="Open calendar"
        onClick={() => picker.current?.showPicker?.()}
        className="shrink-0 rounded-sm border border-gray-300 bg-white px-2 py-1.5 text-sm hover:bg-gray-50 disabled:opacity-50"
      >
        📅
      </button>
      {showToday && (
        <button
          type="button"
          disabled={disabled}
          onClick={() => onChange(todayIso())}
          className="shrink-0 rounded-sm border border-gray-300 bg-white px-2 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
        >
          Today
        </button>
      )}
      {/* Hidden native control, used only to pop the calendar. */}
      <input
        ref={picker}
        type="date"
        tabIndex={-1}
        aria-hidden
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="pointer-events-none absolute h-0 w-0 opacity-0"
      />
    </div>
  )
}
