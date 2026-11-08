import { create } from 'zustand'
import type { SettingsDTO } from '@/types/ipc'

/**
 * Small UI preferences that many components read: whether to show the coloured
 * status dots, and whether fully-paid memos hide their Payment button. Applied
 * at startup and whenever Settings are saved (see applySettings).
 */
interface UiPrefsState {
  showStatusDots: boolean
  hidePaymentWhenPaid: boolean
  zoomFactor: number
  apply: (s: Pick<SettingsDTO, 'showStatusDots' | 'hidePaymentWhenPaid' | 'zoomFactor'>) => void
}

export const useUiPrefsStore = create<UiPrefsState>((set) => ({
  showStatusDots: true,
  hidePaymentWhenPaid: false,
  zoomFactor: 1,
  apply: (s) =>
    set({
      showStatusDots: s.showStatusDots,
      hidePaymentWhenPaid: s.hidePaymentWhenPaid,
      zoomFactor: s.zoomFactor,
    }),
}))
