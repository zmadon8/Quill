import { create } from 'zustand'
import type { FeebookEntry, FeebookFilter } from '@/types/ipc'
import { currentFinancialYear } from '@/lib/financialYear'

interface FeebookState {
  entries: FeebookEntry[]
  filter: FeebookFilter
  loading: boolean
  error: string | null
  setFilter: (patch: Partial<FeebookFilter>) => void
  load: () => Promise<void>
}

export const useFeebookStore = create<FeebookState>((set, get) => ({
  entries: [],
  filter: { financialYear: currentFinancialYear() },
  loading: false,
  error: null,
  setFilter: (patch) => {
    set({ filter: { ...get().filter, ...patch } })
    void get().load()
  },
  load: async () => {
    set({ loading: true, error: null })
    const res = await window.api.feebook.list(get().filter)
    if (res.ok) set({ entries: res.data, loading: false })
    else set({ error: res.error, loading: false })
  },
}))
