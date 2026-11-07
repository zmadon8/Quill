import { create } from 'zustand'
import type { MemoListItem, MemoFilter } from '@/types/ipc'
import { currentFinancialYear } from '@/lib/financialYear'

interface MemoState {
  memos: MemoListItem[]
  filter: MemoFilter
  selectedMattersEnabled: boolean
  loading: boolean
  error: string | null
  setFilter: (patch: Partial<MemoFilter>) => void
  setSelectedMattersEnabled: (on: boolean) => void
  load: () => Promise<void>
}

export const useMemoStore = create<MemoState>((set, get) => ({
  memos: [],
  filter: { financialYear: currentFinancialYear() },
  selectedMattersEnabled: false,
  loading: false,
  error: null,
  setFilter: (patch) => {
    set({ filter: { ...get().filter, ...patch } })
    void get().load()
  },
  setSelectedMattersEnabled: (on) => {
    set({ selectedMattersEnabled: on })
    if (!on) {
      set({ filter: { ...get().filter, selectedMatterIds: undefined } })
      void get().load()
    }
  },
  load: async () => {
    set({ loading: true, error: null })
    const res = await window.api.memos.list(get().filter)
    if (res.ok) set({ memos: res.data, loading: false })
    else set({ error: res.error, loading: false })
  },
}))
