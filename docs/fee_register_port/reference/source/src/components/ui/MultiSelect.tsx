import { useRef, useState } from 'react'
import { Popover } from '@/components/ui/Popover'
import { Button } from '@/components/ui/Button'

export interface MultiOption {
  id: number
  name: string
}

/**
 * Dropdown with a checkbox per option plus All / None shortcuts.
 * `selected === null` means "everything" (so options that appear later are
 * included automatically); an array is an explicit selection.
 */
export function MultiSelect({
  label,
  options,
  selected,
  onChange,
  allLabel = 'All',
}: {
  label: string
  options: MultiOption[]
  selected: number[] | null
  onChange: (next: number[] | null) => void
  allLabel?: string
}) {
  const [open, setOpen] = useState(false)
  const anchor = useRef<HTMLDivElement>(null)
  const sel = selected === null ? new Set(options.map((o) => o.id)) : new Set(selected)
  const count = options.filter((o) => sel.has(o.id)).length
  const summary =
    selected === null || count === options.length
      ? allLabel
      : count === 0
        ? 'None'
        : count === 1
          ? options.find((o) => sel.has(o.id))?.name ?? '1 selected'
          : `${count} selected`

  const toggle = (id: number) => {
    const next = new Set(sel)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    onChange(next.size === options.length ? null : [...next])
  }

  return (
    <div ref={anchor} className="relative">
      <label className="block text-xs text-gray-500">{label}</label>
      <Button variant="secondary" size="md" className="min-w-[10rem] justify-between gap-2" onClick={() => setOpen((v) => !v)}>
        <span className="truncate">{summary}</span>
        <span aria-hidden>▾</span>
      </Button>
      {open && (
        <Popover anchor={anchor} align="left" className="max-h-72 w-72" onClose={() => setOpen(false)}>
          <div>
            <div className="mb-1 flex gap-3 px-1 text-xs">
              <button className="text-blue-700 hover:underline" onClick={() => onChange(null)}>
                Select all
              </button>
              <button className="text-blue-700 hover:underline" onClick={() => onChange([])}>
                Select none
              </button>
            </div>
            {options.length === 0 && <p className="px-1 py-1 text-sm text-gray-500">Nothing to choose.</p>}
            {options.map((o) => (
              <label
                key={o.id}
                className="flex cursor-pointer items-center gap-2 rounded px-1 py-1 text-sm hover:bg-gray-50"
              >
                <input type="checkbox" checked={sel.has(o.id)} onChange={() => toggle(o.id)} />
                <span className="truncate">{o.name}</span>
              </label>
            ))}
          </div>
        </Popover>
      )}
    </div>
  )
}
