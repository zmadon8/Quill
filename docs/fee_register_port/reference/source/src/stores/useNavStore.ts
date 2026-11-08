import { create } from 'zustand'

export type TopTab =
  | 'dashboard'
  | 'statistics'
  | 'memos'
  | 'feebook'
  | 'outstanding'
  | 'settings'
  | 'firms'

/** A pushed detail view on top of the active tab. */
export type View =
  | { kind: 'firmDetail'; firmId: number; title: string }
  | { kind: 'matterDetail'; matterId: number; title: string }
  | { kind: 'memoForm'; memoId?: number; basedOnId?: number; matterId?: number; title: string }

interface NavState {
  tab: TopTab
  stack: View[]
  /**
   * Optional navigation guard. When set, it is consulted before any navigation
   * (setTab/push/pop). Returning false cancels the navigation. Used by the memo
   * form to confirm leaving with unsaved edits.
   */
  guard: (() => boolean) | null
  /**
   * Incremented every time a detail view is closed (Back). Pages that stay
   * mounted underneath a detail view watch this to re-load fresh data.
   */
  refreshTick: number
  setGuard: (fn: (() => boolean) | null) => void
  setTab: (tab: TopTab) => void
  push: (view: View) => void
  pop: () => void
  resetTo: (tab: TopTab) => void
  current: () => View | null
}

export const useNavStore = create<NavState>((set, get) => ({
  tab: 'memos',
  stack: [],
  guard: null,
  refreshTick: 0,
  setGuard: (fn) => set({ guard: fn }),
  setTab: (tab) => {
    const g = get().guard
    if (g && !g()) return
    set({ tab, stack: [], guard: null })
  },
  push: (view) => {
    const g = get().guard
    if (g && !g()) return
    set({ stack: [...get().stack, view], guard: null })
  },
  pop: () => {
    const g = get().guard
    if (g && !g()) return
    set({ stack: get().stack.slice(0, -1), guard: null, refreshTick: get().refreshTick + 1 })
  },
  resetTo: (tab) => set({ tab, stack: [], guard: null }),
  current: () => {
    const s = get().stack
    return s.length ? s[s.length - 1] : null
  },
}))
