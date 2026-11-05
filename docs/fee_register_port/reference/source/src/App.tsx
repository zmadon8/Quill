import { useEffect, useRef } from 'react'
import { useNavStore, type TopTab } from '@/stores/useNavStore'
import { TopNav } from '@/components/TopNav'
import { Toaster } from '@/components/ui/Toaster'
import { ConfirmModal } from '@/components/ui/ConfirmModal'
import { ScrollControls } from '@/components/ui/ScrollControls'
import { FindBar } from '@/components/FindBar'
import { ArrowLeft } from 'lucide-react'
import { FirmsPage } from '@/components/firms/FirmsPage'
import { FirmDetailPage } from '@/components/firms/FirmDetailPage'
import { MatterDetailPage } from '@/components/matters/MatterDetailPage'
import { MemosPage } from '@/components/memos/MemosPage'
import { MemoFormPage } from '@/components/memos/MemoFormPage'
import { DashboardPage } from '@/components/dashboard/DashboardPage'
import { StatisticsTab } from '@/components/statistics/StatisticsTab'
import { FeebookPage } from '@/components/feebook/FeebookPage'
import { OutstandingPage } from '@/components/outstanding/OutstandingPage'
import { SettingsPage } from '@/components/settings/SettingsPage'
import { applySettings } from '@/lib/applySettings'
import { useSettingsStore } from '@/stores/useSettingsStore'

/** ⌘1…⌘7 jump to these tabs, in the same order as the top bar. */
const TAB_SHORTCUTS: TopTab[] = ['dashboard', 'statistics', 'memos', 'firms', 'feebook', 'outstanding', 'settings']

export default function App() {
  const tab = useNavStore((s) => s.tab)
  const stack = useNavStore((s) => s.stack)
  const pop = useNavStore((s) => s.pop)
  const setTab = useNavStore((s) => s.setTab)
  const current = stack.length ? stack[stack.length - 1] : null
  const mainRef = useRef<HTMLElement>(null)

  // Apply the user's configured default landing tab, font, zoom, money display…
  // once at launch.
  useEffect(() => {
    void (async () => {
      const res = await window.api.settings.get()
      if (res.ok) {
        if (res.data.defaultTab) setTab(res.data.defaultTab as TopTab)
        applySettings(res.data)
      }
    })()
    // Run once on mount only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Remember each screen's scroll position: opening a detail view saves where
  // you were, and Back puts you exactly there (instead of jumping to the top).
  const scrolls = useRef<number[]>([])
  const prevDepth = useRef(0)
  useEffect(() => {
    const el = mainRef.current
    if (!el) return
    if (stack.length > prevDepth.current) {
      // Opened a deeper view: stash the scroll position we are leaving.
      scrolls.current.push(el.dataset.lastScroll ? Number(el.dataset.lastScroll) : 0)
      el.scrollTop = 0
    } else if (stack.length < prevDepth.current) {
      // Went back: restore the position we left from.
      const y = scrolls.current.pop() ?? 0
      requestAnimationFrame(() => {
        if (mainRef.current) mainRef.current.scrollTop = y
      })
    }
    if (stack.length === 0) scrolls.current = []
    prevDepth.current = stack.length
  }, [stack.length])

  // Track the live scroll position so it can be stashed at the moment of a push.
  useEffect(() => {
    const el = mainRef.current
    if (!el) return
    const onScroll = () => {
      el.dataset.lastScroll = String(el.scrollTop)
    }
    el.addEventListener('scroll', onScroll, { passive: true })
    return () => el.removeEventListener('scroll', onScroll)
  }, [])

  // Global keyboard shortcuts (listed in Settings → Keyboard Shortcuts).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || e.altKey) return
      const key = e.key
      // ⌘1…⌘7: jump to a tab.
      if (/^[1-7]$/.test(key)) {
        e.preventDefault()
        setTab(TAB_SHORTCUTS[Number(key) - 1])
        return
      }
      // ⌘[ : back.
      if (key === '[') {
        e.preventDefault()
        if (useNavStore.getState().stack.length > 0) pop()
        return
      }
      // ⌘+ / ⌘- / ⌘0 : zoom.
      if (key === '=' || key === '+' || key === '-' || key === '_' || key === '0') {
        e.preventDefault()
        const cur = useSettingsStore.getState().settings?.zoomFactor ?? 1
        const next =
          key === '0' ? 1 : Math.min(2, Math.max(0.6, Math.round((cur + (key === '-' || key === '_' ? -0.1 : 0.1)) * 10) / 10))
        void (async () => {
          const ok = await useSettingsStore.getState().save({ zoomFactor: next })
          const s = useSettingsStore.getState().settings
          if (ok && s) applySettings(s)
          else void window.api.system.setZoom(next)
        })()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [pop, setTab])

  return (
    // h-screen + overflow-hidden pins the layout to the viewport so only <main>
    // scrolls; the TopNav header and Back bar stay fixed at the top.
    <div className="flex h-screen flex-col overflow-hidden bg-gray-50 text-gray-900">
      <TopNav />

      {stack.length > 0 && (
        <div className="flex items-center gap-3 border-b border-gray-200 bg-gray-50 px-6 py-1.5 text-sm">
          <button
            onClick={pop}
            className="inline-flex items-center gap-1 font-semibold text-gray-900 hover:text-blue-700"
          >
            <ArrowLeft size={14} strokeWidth={1.8} aria-hidden /> Back
          </button>
          <span className="text-gray-500">{current?.title}</span>
        </div>
      )}

      <main ref={mainRef} className="flex-1 overflow-auto px-6 py-5">
        {/* The active tab page stays MOUNTED (just hidden) while a detail view is
            open on top of it, so its filters, sub-tabs and "viewing this firm"
            state survive. Pages watch useNavStore.refreshTick to re-load data. */}
        <div hidden={current !== null}>
          {tab === 'dashboard' && <DashboardPage />}
          {tab === 'statistics' && <StatisticsTab />}
          {tab === 'firms' && <FirmsPage />}
          {tab === 'memos' && <MemosPage />}
          {tab === 'feebook' && <FeebookPage />}
          {tab === 'outstanding' && <OutstandingPage />}
          {tab === 'settings' && <SettingsPage />}
        </div>
        {current && (
          <>
            {current.kind === 'firmDetail' && <FirmDetailPage key={`f${current.firmId}`} firmId={current.firmId} />}
            {current.kind === 'matterDetail' && <MatterDetailPage key={`m${current.matterId}`} matterId={current.matterId} />}
            {current.kind === 'memoForm' && (
              <MemoFormPage
                key={`mf${current.memoId ?? 'new'}-${current.basedOnId ?? ''}-${current.matterId ?? ''}`}
                memoId={current.memoId}
                basedOnId={current.basedOnId}
                matterId={current.matterId}
              />
            )}
          </>
        )}
      </main>

      <ScrollControls target={mainRef as React.RefObject<HTMLElement>} />
      <Toaster />
      <ConfirmModal />
      <FindBar />
    </div>
  )
}
