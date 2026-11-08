import { useEffect, useRef, useState } from 'react'
import { Search } from 'lucide-react'
import { useNavStore } from '@/stores/useNavStore'
import type { SearchResult } from '@/types/ipc'

/**
 * Header search box: searches firms, matters, memos (number + party names) and
 * navigates to the chosen result. Debounced; results shown in a dropdown.
 */
export function GlobalSearch() {
  const push = useNavStore((s) => s.push)
  const setTab = useNavStore((s) => s.setTab)
  const [q, setQ] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [open, setOpen] = useState(false)
  const boxRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (q.trim().length < 2) {
      setResults([])
      return
    }
    let cancelled = false
    const t = setTimeout(async () => {
      const res = await window.api.search.query(q)
      if (!cancelled && res.ok) {
        setResults(res.data)
        setOpen(true)
      }
    }, 200)
    return () => {
      cancelled = true
      clearTimeout(t)
    }
  }, [q])

  // Close on outside click.
  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [])

  const go = (r: SearchResult) => {
    if (r.kind === 'firm') push({ kind: 'firmDetail', firmId: r.id, title: r.title })
    else if (r.kind === 'matter') push({ kind: 'matterDetail', matterId: r.id, title: r.title })
    else push({ kind: 'memoForm', memoId: r.id, title: r.title })
    setQ('')
    setResults([])
    setOpen(false)
  }

  // Explicit search (button / Enter): runs immediately and opens results. If a
  // single result comes back, jump straight to it.
  const runSearch = async () => {
    if (q.trim().length < 2) return
    const res = await window.api.search.query(q)
    if (res.ok) {
      setResults(res.data)
      setOpen(true)
    }
  }

  return (
    <div ref={boxRef} className="relative flex w-80 items-center">
      <button
        type="button"
        onClick={() => void runSearch()}
        aria-label="Search"
        className="absolute left-1 text-gray-500 hover:text-gray-900"
      >
        <Search size={14} strokeWidth={1.7} aria-hidden />
      </button>
      <input
        type="search"
        value={q}
        placeholder="Search memos, matters, firms, parties…"
        onChange={(e) => setQ(e.target.value)}
        onFocus={() => results.length > 0 && setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') void runSearch()
          if (e.key === 'Escape') setOpen(false)
        }}
        className="w-full border-0 border-b border-gray-900 bg-transparent py-1 pl-6 pr-1 text-sm text-gray-900 placeholder:text-gray-500 focus:outline-none focus:ring-0"
      />
      {open && results.length > 0 && (
        <div className="absolute left-0 right-0 top-full z-50 mt-1 max-h-80 overflow-auto rounded-sm border border-gray-300 bg-white shadow-[0_2px_0_#CFC9BA]">
          {results.map((r) => (
            <button
              key={`${r.kind}-${r.id}`}
              onClick={() => go(r)}
              className="flex w-full flex-col items-start px-3 py-2 text-left hover:bg-gray-50"
            >
              <span className="text-sm font-medium text-gray-900">{r.title}</span>
              <span className="text-xs text-gray-500">{r.subtitle}</span>
            </button>
          ))}
        </div>
      )}
      {open && q.trim().length >= 2 && results.length === 0 && (
        <div className="absolute left-0 right-0 top-full z-50 mt-1 rounded-sm border border-gray-300 bg-white px-3 py-2 text-sm text-gray-500 shadow-[0_2px_0_#CFC9BA]">
          No matches.
        </div>
      )}
    </div>
  )
}
