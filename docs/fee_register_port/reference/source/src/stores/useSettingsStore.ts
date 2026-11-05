import { create } from 'zustand'
import type { SettingsDTO, SettingsInput, BankAccountDTO } from '@/types/ipc'

interface SettingsState {
  settings: SettingsDTO | null
  bankAccounts: BankAccountDTO[]
  loading: boolean
  error: string | null
  load: () => Promise<void>
  save: (input: SettingsInput) => Promise<boolean>
  reloadBankAccounts: () => Promise<void>
}

export const useSettingsStore = create<SettingsState>((set, get) => ({
  settings: null,
  bankAccounts: [],
  loading: false,
  error: null,
  load: async () => {
    set({ loading: true, error: null })
    const [s, b] = await Promise.all([
      window.api.settings.get(),
      window.api.settings.listBankAccounts(),
    ])
    set({
      settings: s.ok ? s.data : get().settings,
      bankAccounts: b.ok ? b.data : get().bankAccounts,
      loading: false,
      error: s.ok ? null : s.error,
    })
  },
  save: async (input) => {
    const res = await window.api.settings.update(input)
    if (res.ok) {
      set({ settings: res.data })
      return true
    }
    set({ error: res.error })
    return false
  },
  reloadBankAccounts: async () => {
    const b = await window.api.settings.listBankAccounts()
    if (b.ok) set({ bankAccounts: b.data })
  },
}))
