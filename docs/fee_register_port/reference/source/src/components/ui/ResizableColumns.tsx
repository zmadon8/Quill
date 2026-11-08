import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Minimal, dependency-free resizable table columns.
 *
 * Usage:
 *   const cols = useColumnWidths('memosTable', { memo: 110, date: 90, ... })
 *   <table className="table-fixed">
 *     <colgroup>{cols.keys.map(k => <col key={k} style={{ width: cols.width(k) }} />)}</colgroup>
 *     <thead><tr>
 *       <th className="relative ...">Memo No.<ColResizer onDrag={(dx)=>cols.resize('memo', dx)} /></th>
 *       ...
 *
 * Widths persist to localStorage under the given key, so the user's sizing
 * sticks between sessions.
 */
export function useColumnWidths<K extends string>(
  storageKey: string,
  defaults: Record<K, number>,
) {
  const keys = Object.keys(defaults) as K[]
  const [widths, setWidths] = useState<Record<K, number>>(() => {
    try {
      const raw = localStorage.getItem(storageKey)
      if (raw) {
        const saved = JSON.parse(raw) as Partial<Record<K, number>>
        // Merge saved over defaults so newly-added columns still appear.
        return { ...defaults, ...saved }
      }
    } catch {
      /* ignore malformed storage */
    }
    return defaults
  })

  useEffect(() => {
    try {
      localStorage.setItem(storageKey, JSON.stringify(widths))
    } catch {
      /* ignore quota/availability errors */
    }
  }, [storageKey, widths])

  const resize = useCallback((key: K, delta: number) => {
    setWidths((w) => {
      const next = Math.max(48, Math.round(w[key] + delta)) // min 48px
      return { ...w, [key]: next }
    })
  }, [])

  const reset = useCallback(() => setWidths(defaults), [defaults])

  return {
    keys,
    width: (k: K) => widths[k],
    resize,
    reset,
  }
}

/**
 * A thin drag handle rendered at the right edge of a <th>. The parent <th>
 * must be position:relative. Reports the horizontal drag delta per move.
 */
export function ColResizer({ onDrag }: { onDrag: (deltaPx: number) => void }) {
  const lastX = useRef<number | null>(null)

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (lastX.current === null) return
      const dx = e.clientX - lastX.current
      lastX.current = e.clientX
      if (dx !== 0) onDrag(dx)
    }
    const onUp = () => {
      lastX.current = null
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [onDrag])

  return (
    <span
      role="separator"
      aria-orientation="vertical"
      onMouseDown={(e) => {
        e.preventDefault()
        e.stopPropagation()
        lastX.current = e.clientX
        document.body.style.cursor = 'col-resize'
        document.body.style.userSelect = 'none'
      }}
      className="absolute right-0 top-0 z-20 flex h-full w-2 cursor-col-resize items-center justify-center hover:bg-indigo-200/60"
    >
      <span className="h-4 w-px bg-gray-300" />
    </span>
  )
}
