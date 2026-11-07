import { useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from 'react'
import { createPortal } from 'react-dom'
import { cn } from '@/lib/cn'

/**
 * A dropdown panel that is drawn on top of the whole page (in a portal, with
 * fixed positioning), so it is never cut off by a table, card or scroll area
 * that contains its button. It opens below the button, or above it when there
 * is more room there, and scrolls internally if it still doesn't fit.
 */
export function Popover({
  anchor,
  onClose,
  align = 'right',
  className,
  children,
}: {
  anchor: RefObject<HTMLElement>
  onClose: () => void
  /** Which edge of the button the panel lines up with. */
  align?: 'left' | 'right'
  className?: string
  children: ReactNode
}) {
  const panel = useRef<HTMLDivElement>(null)
  const [style, setStyle] = useState<React.CSSProperties>({ visibility: 'hidden' })

  useLayoutEffect(() => {
    const place = () => {
      const a = anchor.current?.getBoundingClientRect()
      const p = panel.current
      if (!a || !p) return
      const margin = 8
      const gap = 4
      const naturalH = p.scrollHeight
      const below = window.innerHeight - a.bottom - margin - gap
      const above = a.top - margin - gap
      const openAbove = naturalH > below && above > below
      const room = openAbove ? above : below
      const height = Math.min(naturalH, Math.max(room, 120))
      const width = p.offsetWidth
      let left = align === 'right' ? a.right - width : a.left
      left = Math.max(margin, Math.min(left, window.innerWidth - width - margin))
      setStyle({
        position: 'fixed',
        left,
        top: openAbove ? Math.max(margin, a.top - gap - height) : a.bottom + gap,
        maxHeight: height,
        overflowY: 'auto',
        visibility: 'visible',
      })
    }
    place()
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, true)
    return () => {
      window.removeEventListener('resize', place)
      window.removeEventListener('scroll', place, true)
    }
  }, [anchor, align])

  return createPortal(
    <>
      <div className="fixed inset-0 z-40" onClick={onClose} />
      <div
        ref={panel}
        style={style}
        className={cn(
          'z-50 w-56 rounded-sm border border-gray-300 bg-white p-2 shadow-[0_2px_0_#CFC9BA]',
          className,
        )}
      >
        {children}
      </div>
    </>,
    document.body,
  )
}
