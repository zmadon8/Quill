import { create } from 'zustand'

export interface ConfirmOptions {
  title: string
  message: string
  confirmLabel?: string
  cancelLabel?: string
  /** When true, the confirm button is styled as a destructive (red) action. */
  destructive?: boolean
}

interface ConfirmState {
  open: boolean
  options: ConfirmOptions | null
  resolve: ((ok: boolean) => void) | null
  /** Opens the dialog and resolves to true (confirmed) or false (cancelled). */
  confirm: (options: ConfirmOptions) => Promise<boolean>
  respond: (ok: boolean) => void
}

export const useConfirmStore = create<ConfirmState>((set, get) => ({
  open: false,
  options: null,
  resolve: null,
  confirm: (options) =>
    new Promise<boolean>((resolve) => {
      set({ open: true, options, resolve })
    }),
  respond: (ok) => {
    get().resolve?.(ok)
    set({ open: false, options: null, resolve: null })
  },
}))

/** Convenience helper usable outside React render (returns a promise<boolean>). */
export function confirmDialog(options: ConfirmOptions): Promise<boolean> {
  return useConfirmStore.getState().confirm(options)
}
