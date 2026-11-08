import { create } from 'zustand'
import type { FirmSummary, FirmFilter } from '@/types/ipc'

interface FirmState {
  firms: FirmSummary[]
  filter: FirmFilter
  loading: boolean
  error: string | null
  setFilter: (f: FirmFilter) => void
  load: () => Promise<void>
}

export const useFirmStore = create<FirmState>((set, get) => ({
  firms: [],
  filter: 'active',
  loading: false,
  error: null,
  setFilter: (filter) => {
    set({ filter })
    void get().load()
  },
  load: async () => {
    set({ loading: true, error: null })
    const res = await window.api.firms.list(get().filter)
    if (res.ok) set({ firms: res.data, loading: false })
    else set({ error: res.error, loading: false })
  },
}))
