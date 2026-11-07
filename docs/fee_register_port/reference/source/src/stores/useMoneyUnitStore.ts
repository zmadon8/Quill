import { create } from 'zustand'
import {
  DEFAULT_MONEY_SUFFIXES,
  formatMoneyUnit,
  type MoneySuffixes,
  type MoneyUnit,
} from '@/lib/formatMoney'
import type { SettingsDTO } from '@/types/ipc'

/**
 * Global money display preferences for tables: the mode ('full' | 'truncated')
 * and the custom suffixes for truncated mode. Kept in one place so every table
 * formats figures consistently without each page loading the full settings.
 * Loaded at app start and re-applied whenever Settings are saved.
 */
interface MoneyUnitState {
  unit: MoneyUnit
  suffixes: MoneySuffixes
  loaded: boolean
  /** Loads the persisted preferences from settings (idempotent). */
  load: () => Promise<void>
  /** Applies preferences from a settings object (e.g. right after saving). */
  apply: (s: Pick<SettingsDTO, 'moneyUnit' | 'moneySuffixThousands' | 'moneySuffixLac' | 'moneySuffixCrore'>) => void
  /** Formats a figure in the current mode (no ₹ symbol; callers add it). */
  format: (n: number | null | undefined) => string
}

export const useMoneyUnitStore = create<MoneyUnitState>((set, get) => ({
  unit: 'full',
  suffixes: DEFAULT_MONEY_SUFFIXES,
  loaded: false,
  load: async () => {
    const res = await window.api.settings.get()
    if (res.ok) get().apply(res.data)
    set({ loaded: true })
  },
  apply: (s) =>
    set({
      unit: s.moneyUnit,
      suffixes: {
        thousands: s.moneySuffixThousands || DEFAULT_MONEY_SUFFIXES.thousands,
        lac: s.moneySuffixLac || DEFAULT_MONEY_SUFFIXES.lac,
        crore: s.moneySuffixCrore || DEFAULT_MONEY_SUFFIXES.crore,
      },
    }),
  format: (n) => formatMoneyUnit(n, get().unit, get().suffixes),
}))
