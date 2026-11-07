import { useEffect } from 'react'
import { Undo2, Redo2 } from 'lucide-react'
import { cn } from '@/lib/cn'
import { useNavStore, type TopTab } from '@/stores/useNavStore'
import { useHistoryStore } from '@/stores/useHistoryStore'
import { GlobalSearch } from '@/components/GlobalSearch'

const TABS: { id: TopTab; label: string }[] = [
  { id: 'dashboard', label: 'Dashboard' },
  { id: 'statistics', label: 'Statistics' },
  { id: 'memos', label: 'Memos' },
  { id: 'firms', label: 'Firms' },
  { id: 'feebook', label: 'Feebook' },
  { id: 'outstanding', label: 'Outstanding' },
  { id: 'settings', label: 'Settings' },
]

export function TopNav() {
  const tab = useNavStore((s) => s.tab)
  const setTab = useNavStore((s) => s.setTab)
  const { canUndo, canRedo, undoLabel, redoLabel, refresh, undo, redo } = useHistoryStore()

  // Keep availability fresh and wire Cmd/Ctrl+Z (undo) and Cmd/Ctrl+Shift+Z
  // (redo). Refresh on focus so the labels reflect the latest action.
  useEffect(() => {
    void refresh()
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey)) return
      if (e.key.toLowerCase() !== 'z') return
      // Don't hijack undo inside text inputs/textareas.
      const t = e.target as HTMLElement | null
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return
      e.preventDefault()
      if (e.shiftKey) void redo()
      else void undo()
    }
    const onFocus = () => void refresh()
    window.addEventListener('keydown', onKey)
    window.addEventListener('focus', onFocus)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('focus', onFocus)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <header className="flex items-end justify-between border-b border-gray-900 bg-gray-50 px-6 pt-3">
      <div className="flex items-end gap-1">
        <span className="mr-6 pb-1.5 font-serif text-xl italic text-gray-900">Fee Register</span>
        <nav className="flex gap-5">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={cn(
                '-mb-px border-b-2 pb-2 text-sm transition-colors',
                tab === t.id
                  ? 'border-blue-600 font-semibold text-gray-900'
                  : 'border-transparent text-gray-500 hover:text-gray-900',
              )}
            >
              {t.label}
            </button>
          ))}
        </nav>
      </div>
      <div className="flex items-center gap-4 pb-2">
        <div className="flex items-center gap-3 text-sm">
          <button
            onClick={() => void undo()}
            disabled={!canUndo}
            title={canUndo ? `Undo: ${undoLabel ?? ''} (⌘Z)` : 'Nothing to undo'}
            className={cn(
              'inline-flex items-center gap-1.5',
              canUndo ? 'text-gray-900 hover:text-blue-700' : 'cursor-default text-gray-300',
            )}
          >
            <Undo2 size={15} strokeWidth={1.6} aria-hidden /> Undo
          </button>
          <button
            onClick={() => void redo()}
            disabled={!canRedo}
            title={canRedo ? `Redo: ${redoLabel ?? ''} (⇧⌘Z)` : 'Nothing to redo'}
            className={cn(
              'inline-flex items-center gap-1.5',
              canRedo ? 'text-gray-900 hover:text-blue-700' : 'cursor-default text-gray-300',
            )}
          >
            <Redo2 size={15} strokeWidth={1.6} aria-hidden /> Redo
          </button>
        </div>
        <GlobalSearch />
      </div>
    </header>
  )
}
