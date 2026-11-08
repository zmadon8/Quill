import { useMoneyUnitStore } from '@/stores/useMoneyUnitStore'
import { useUiPrefsStore } from '@/stores/useUiPrefsStore'
import type { SettingsDTO } from '@/types/ipc'

/**
 * Pushes a settings object into every client-side consumer: money display,
 * UI preferences, the application font and the window zoom. Called once at
 * launch and again each time Settings are saved, so changes show instantly.
 */
export function applySettings(s: SettingsDTO): void {
  useMoneyUnitStore.getState().apply(s)
  useUiPrefsStore.getState().apply(s)
  void window.api.system.setZoom(s.zoomFactor || 1)
}
