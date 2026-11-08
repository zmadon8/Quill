import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * In-app "find on page", opened with ⌘/Ctrl+F (Electron has no browser find).
 *
 * Rather than window.find() — which only matches on-screen text and fails to
 * scroll nested overflow:auto containers (our scrolling tables) — this walks
 * the DOM text nodes itself, wraps each match in a <mark>, and scrolls the
 * active match into view with scrollIntoView({block:'center'}). That works for
 * matches anywhere in a scrollable table, including far below the fold.
 */
const HILITE = 'fr-find-hilite'
const ACTIVE = 'fr-find-active'

export function FindBar() {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [count, setCount] = useState(0)
  const [active, setActive] = useState(0) // 1-based index of the current match
  const inputRef = useRef<HTMLInputElement>(null)

  // Remove all highlight wrappers, restoring original text nodes.
  const clearHighlights = useCallback(() => {
    const marks = Array.from(document.querySelectorAll(`mark.${HILITE}`))
    for (const m of marks) {
      const parent = m.parentNode
      if (!parent) continue
      parent.replaceChild(document.createTextNode(m.textContent ?? ''), m)
      parent.normalize() // merge adjacent text nodes back
    }
  }, [])

  // Highlight every occurrence of `q` within the main content area.
  const highlight = useCallback(
    (q: string): number => {
      clearHighlights()
      if (!q || q.length < 1) return 0
      const root = document.querySelector('main') ?? document.body
      const needle = q.toLowerCase()
      // Collect candidate text nodes first (walking live while mutating is unsafe).
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
        acceptNode: (node) => {
          const p = node.parentElement
          if (!p) return NodeFilter.FILTER_REJECT
          // Skip the find bar itself, scripts/styles, and already-marked nodes.
          if (p.closest('.fr-find-bar')) return NodeFilter.FILTER_REJECT
          const tag = p.tagName
          if (tag === 'SCRIPT' || tag === 'STYLE') return NodeFilter.FILTER_REJECT
          if (!node.textContent || !node.textContent.toLowerCase().includes(needle)) {
            return NodeFilter.FILTER_REJECT
          }
          return NodeFilter.FILTER_ACCEPT
        },
      })
      const targets: Text[] = []
      let n = walker.nextNode()
      while (n) {
        targets.push(n as Text)
        n = walker.nextNode()
      }

      let total = 0
      for (const textNode of targets) {
        const text = textNode.textContent ?? ''
        const lower = text.toLowerCase()
        const frag = document.createDocumentFragment()
        let i = 0
        let idx = lower.indexOf(needle, i)
        if (idx === -1) continue
        while (idx !== -1) {
          if (idx > i) frag.appendChild(document.createTextNode(text.slice(i, idx)))
          const mark = document.createElement('mark')
          mark.className = HILITE
          mark.textContent = text.slice(idx, idx + q.length)
          frag.appendChild(mark)
          i = idx + q.length
          total++
          idx = lower.indexOf(needle, i)
        }
        if (i < text.length) frag.appendChild(document.createTextNode(text.slice(i)))
        textNode.parentNode?.replaceChild(frag, textNode)
      }
      return total
    },
    [clearHighlights],
  )

  const marks = () => Array.from(document.querySelectorAll<HTMLElement>(`mark.${HILITE}`))

  const goTo = useCallback((index1: number) => {
    const all = marks()
    if (all.length === 0) return
    const wrapped = ((index1 - 1 + all.length) % all.length) + 1
    all.forEach((m) => m.classList.remove(ACTIVE))
    const el = all[wrapped - 1]
    el.classList.add(ACTIVE)
    el.scrollIntoView({ block: 'center', behavior: 'smooth' })
    setActive(wrapped)
  }, [])

  // Re-run highlight (debounced) whenever the query changes while open.
  useEffect(() => {
    if (!open) return
    const t = setTimeout(() => {
      const total = highlight(query)
      setCount(total)
      if (total > 0) goTo(1)
      else setActive(0)
    }, 150)
    return () => clearTimeout(t)
  }, [query, open, highlight, goTo])

  const next = (back: boolean) => {
    if (count === 0) return
    goTo(active + (back ? -1 : 1))
  }

  const close = useCallback(() => {
    setOpen(false)
    clearHighlights()
    setQuery('')
    setCount(0)
    setActive(0)
  }, [clearHighlights])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && (e.key === 'f' || e.key === 'F')) {
        e.preventDefault()
        setOpen(true)
        setTimeout(() => {
          inputRef.current?.focus()
          inputRef.current?.select()
        }, 0)
      } else if (e.key === 'Escape' && open) {
        close()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, close])

  if (!open) return null

  return (
    <div className="fr-find-bar fixed right-4 top-16 z-50 flex items-center gap-2 rounded-sm border border-gray-900 bg-white px-2 py-1.5">
      <input
        ref={inputRef}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault()
            next(e.shiftKey)
          } else if (e.key === 'Escape') {
            close()
          }
        }}
        placeholder="Find on page…"
        className="w-56 rounded-sm border-0 border-b border-gray-900 bg-transparent px-1 py-1 text-sm focus:outline-none"
      />
      <span className="min-w-[52px] text-center text-xs tabular-nums text-gray-500">
        {count === 0 ? (query ? '0/0' : '') : `${active}/${count}`}
      </span>
      <button className="rounded px-2 py-1 text-sm text-gray-600 hover:bg-gray-100" title="Previous (Shift+Enter)" onClick={() => next(true)}>↑</button>
      <button className="rounded px-2 py-1 text-sm text-gray-600 hover:bg-gray-100" title="Next (Enter)" onClick={() => next(false)}>↓</button>
      <button className="rounded px-2 py-1 text-sm text-gray-400 hover:text-gray-700" title="Close (Esc)" onClick={close}>×</button>
    </div>
  )
}
