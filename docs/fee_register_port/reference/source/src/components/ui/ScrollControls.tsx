import { useEffect, useState, type RefObject } from 'react'

/**
 * Small floating "jump to top / bottom" pair for long pages. Appears only when
 * the page actually scrolls. One control serves every table in the app.
 */
export function ScrollControls({ target }: { target: RefObject<HTMLElement> }) {
  const [state, setState] = useState({ scrollable: false, atTop: true, atBottom: false })

  useEffect(() => {
    const el = target.current
    if (!el) return
    const update = () =>
      setState({
        scrollable: el.scrollHeight > el.clientHeight + 200,
        atTop: el.scrollTop < 40,
        atBottom: el.scrollTop + el.clientHeight >= el.scrollHeight - 40,
      })
    update()
    el.addEventListener('scroll', update, { passive: true })
    const ro = new ResizeObserver(update)
    ro.observe(el)
    if (el.firstElementChild) ro.observe(el.firstElementChild)
    return () => {
      el.removeEventListener('scroll', update)
      ro.disconnect()
    }
  }, [target])

  if (!state.scrollable) return null
  const go = (top: number) => target.current?.scrollTo({ top, behavior: 'smooth' })
  const base =
    'flex h-8 w-8 items-center justify-center rounded-sm border border-gray-900 bg-gray-50 text-gray-900 hover:bg-gray-100 disabled:opacity-30'
  return (
    <div className="pointer-events-none fixed bottom-20 right-4 z-30 flex flex-col gap-2">
      <button className={`${base} pointer-events-auto`} title="Go to top" aria-label="Go to top" disabled={state.atTop} onClick={() => go(0)}>
        ↑
      </button>
      <button
        className={`${base} pointer-events-auto`}
        title="Go to bottom"
        aria-label="Go to bottom"
        disabled={state.atBottom}
        onClick={() => go(target.current?.scrollHeight ?? 0)}
      >
        ↓
      </button>
    </div>
  )
}
