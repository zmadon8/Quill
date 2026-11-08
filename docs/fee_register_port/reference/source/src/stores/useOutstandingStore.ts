import { create } from 'zustand'
import type { OutstandingGroup, OutstandingFilter } from '@/types/ipc'

interface OutstandingState {
  groups: OutstandingGroup[]
  filter: OutstandingFilter
  selectedMattersEnabled: boolean
  loading: boolean
  error: string | null
  /**
   * When navigating in from a Firm page ("View Outstanding for this Firm"),
   * this holds the firm the Outstanding page should open directly into its
   * detail view. The summary itself always shows ALL firms, so this is kept
   * separate from `filter` (which must not be scoped to one firm). The page
   * consumes it on mount and then clears it via `clearViewFirmRequest`.
   */
  viewFirmRequest: number | null
  setFilter: (patch: Partial<OutstandingFilter>) => void
  setSelectedMattersEnabled: (on: boolean) => void
  /** Requests the Outstanding page open directly into this firm's detail view. */
  requestViewFirm: (firmId: number) => void
  /** Clears a pending view-firm request once consumed. */
  clearViewFirmRequest: () => void
  load: () => Promise<void>
}

export const useOutstandingStore = create<OutstandingState>((set, get) => ({
  groups: [],
  filter: {},
  selectedMattersEnabled: false,
  loading: false,
  error: null,
  viewFirmRequest: null,
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
  requestViewFirm: (firmId) => {
    // Do NOT scope `filter` to this firm — the summary must keep showing all
    // firms. We only record which firm to open the detail view for.
    set({ viewFirmRequest: firmId })
  },
  clearViewFirmRequest: () => set({ viewFirmRequest: null }),
  load: async () => {
    set({ loading: true, error: null })
    const res = await window.api.outstanding.list(get().filter)
    if (res.ok) set({ groups: res.data, loading: false })
    else set({ error: res.error, loading: false })
  },
}))
