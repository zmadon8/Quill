import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { Popover } from '@/components/ui/Popover'
import { ColResizer } from '@/components/ui/ResizableColumns'
import { Button } from '@/components/ui/Button'
import { cn } from '@/lib/cn'

/**
 * Shared table: every column is resizable, hideable (via <ColumnsMenu/>), and
 * both choices persist per table id. Pages describe their table as a column
 * list; the component owns widths, visibility, the footer row and layout.
 */

/** The parts of a column definition the preferences hook needs. */
interface PrefColumn {
  key: string
  width?: number
  hideable?: boolean
}

export interface DTColumn<T> extends PrefColumn {
  label: string
  align?: 'left' | 'right'
  cell: (row: T, index: number) => ReactNode
  /** Footer cell (totals). Omit for an empty footer cell. */
  foot?: () => ReactNode
  /** Extra classes for body cells of this column. */
  cellClassName?: string
  /** Tooltip for the header cell. */
  headerTitle?: string
}

function readJson<V>(key: string, fallback: V): V {
  try {
    const raw = localStorage.getItem(key)
    return raw ? ({ ...(fallback as object), ...JSON.parse(raw) } as V) : fallback
  } catch {
    return fallback
  }
}

export interface TablePrefs {
  tableId: string
  widths: Record<string, number>
  isVisible: (key: string) => boolean
  setVisible: (key: string, visible: boolean) => void
  resize: (key: string, delta: number) => void
  reset: () => void
}

/** Persisted column widths + visibility for one table. */
export function useTablePrefs(tableId: string, columns: PrefColumn[]): TablePrefs {
  const wKey = `tbl:${tableId}:w`
  const hKey = `tbl:${tableId}:h`
  const [defaults] = useState<Record<string, number>>(() =>
    Object.fromEntries(columns.map((c) => [c.key, c.width ?? 120])),
  )
  const [widths, setWidths] = useState<Record<string, number>>(() => readJson(wKey, defaults))
  const [hidden, setHidden] = useState<Record<string, boolean>>(() => readJson(hKey, {}))

  useEffect(() => {
    try {
      localStorage.setItem(wKey, JSON.stringify(widths))
    } catch {
      /* ignore */
    }
  }, [wKey, widths])
  useEffect(() => {
    try {
      localStorage.setItem(hKey, JSON.stringify(hidden))
    } catch {
      /* ignore */
    }
  }, [hKey, hidden])

  const resize = useCallback((key: string, delta: number) => {
    setWidths((w) => ({ ...w, [key]: Math.max(48, Math.round((w[key] ?? 120) + delta)) }))
  }, [])
  const setVisible = useCallback((key: string, visible: boolean) => {
    setHidden((h) => ({ ...h, [key]: !visible }))
  }, [])
  const reset = useCallback(() => {
    setWidths(defaults)
    setHidden({})
  }, [defaults])

  return {
    tableId,
    widths: { ...defaults, ...widths },
    isVisible: (key) => !hidden[key],
    setVisible,
    resize,
    reset,
  }
}

/** The columns currently on screen (non-hideable columns are always shown). */
export function visibleColumns<T extends PrefColumn>(prefs: TablePrefs, columns: T[]): T[] {
  return columns.filter((c) => c.hideable === false || prefs.isVisible(c.key))
}

/** "Columns ▾" dropdown with a checkbox per hideable column. */
export function ColumnsMenu({
  prefs,
  columns,
}: {
  prefs: TablePrefs
  columns: Array<PrefColumn & { label: string }>
}) {
  const [open, setOpen] = useState(false)
  const anchor = useRef<HTMLDivElement>(null)
  return (
    <div ref={anchor} className="relative">
      <Button variant="secondary" size="sm" onClick={() => setOpen((v) => !v)}>
        Columns ▾
      </Button>
      {open && (
        <Popover anchor={anchor} onClose={() => setOpen(false)}>
          <div>
            <p className="mb-1 px-1 text-xs font-semibold uppercase text-gray-500">Show columns</p>
            {columns
              .filter((c) => c.hideable !== false)
              .map((c) => (
                <label
                  key={c.key}
                  className="flex cursor-pointer items-center gap-2 rounded px-1 py-1 text-sm hover:bg-gray-50"
                >
                  <input
                    type="checkbox"
                    checked={prefs.isVisible(c.key)}
                    onChange={(e) => prefs.setVisible(c.key, e.target.checked)}
                  />
                  {c.label}
                </label>
              ))}
            <button
              className="mt-1 w-full rounded px-1 py-1 text-left text-xs text-blue-700 hover:bg-gray-50"
              onClick={() => prefs.reset()}
            >
              Reset columns &amp; widths
            </button>
          </div>
        </Popover>
      )}
    </div>
  )
}

interface DataTableProps<T> {
  prefs: TablePrefs
  columns: Array<DTColumn<T>>
  rows: T[]
  rowKey: (row: T, index: number) => string | number
  /** Extra classes for a body row. */
  rowClassName?: (row: T) => string | undefined
  className?: string
}

export function DataTable<T>({ prefs, columns, rows, rowKey, rowClassName, className }: DataTableProps<T>) {
  const shown = visibleColumns(prefs, columns)
  const hasFoot = shown.some((c) => c.foot)
  const total = shown.reduce((a, c) => a + (prefs.widths[c.key] ?? 120), 0)
  return (
    <div className={cn('overflow-x-auto', className)}>
      <table className="min-w-full table-fixed text-sm" style={{ width: total }}>
        <colgroup>
          {shown.map((c) => (
            <col key={c.key} style={{ width: prefs.widths[c.key] ?? 120 }} />
          ))}
        </colgroup>
        <thead className="text-left text-xs uppercase">
          <tr>
            {shown.map((c) => (
              <th
                key={c.key}
                title={c.headerTitle}
                className={cn('relative px-3 py-2', c.align === 'right' && 'text-right')}
              >
                {c.label}
                <ColResizer onDrag={(dx) => prefs.resize(c.key, dx)} />
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y">
          {rows.map((row, i) => (
            <tr key={rowKey(row, i)} className={rowClassName?.(row)}>
              {shown.map((c) => (
                <td
                  key={c.key}
                  className={cn(
                    'truncate px-3 py-2',
                    c.align === 'right' && 'text-right tabular-nums',
                    c.cellClassName,
                  )}
                >
                  {c.cell(row, i)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
        {hasFoot && (
          <tfoot>
            <tr className="border-t-2 bg-gray-50 font-semibold">
              {shown.map((c) => (
                <td
                  key={c.key}
                  className={cn('px-3 py-2', c.align === 'right' && 'text-right tabular-nums')}
                >
                  {c.foot?.()}
                </td>
              ))}
            </tr>
          </tfoot>
        )}
      </table>
    </div>
  )
}
