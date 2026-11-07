import { create } from 'zustand'
import type { MatterDetail, MatterFilter } from '@/types/ipc'

interface MatterState {
  matters: MatterDetail[]
  filter: MatterFilter
  firmId?: number
  loading: boolean
  error: string | null
  setFilter: (f: MatterFilter) => void
  setFirmId: (id: number | undefined) => void
  load: () => Promise<void>
}

export const useMatterStore = create<MatterState>((set, get) => ({
  matters: [],
  filter: 'active',
  firmId: undefined,
  loading: false,
  error: null,
  setFilter: (filter) => {
    set({ filter })
    void get().load()
  },
  setFirmId: (firmId) => set({ firmId }),
  load: async () => {
    set({ loading: true, error: null })
    const res = await window.api.matters.list(get().filter, get().firmId)
    if (res.ok) set({ matters: res.data, loading: false })
    else set({ error: res.error, loading: false })
  },
}))
