import { create } from 'zustand'

export interface ToastAction {
  /** Button label, e.g. "Undo". */
  label: string
  /** Invoked when the user clicks the action. The toast is dismissed after. */
  run: () => void | Promise<void>
}

export interface Toast {
  id: number
  message: string
  variant: 'info' | 'success' | 'error'
  action?: ToastAction
}

interface ShowOptions {
  variant?: Toast['variant']
  /** Optional action button (e.g. Undo). Extends the visible duration. */
  action?: ToastAction
  /** Override the auto-dismiss delay in ms. */
  durationMs?: number
}

interface ToastState {
  toasts: Toast[]
  show: (message: string, variantOrOpts?: Toast['variant'] | ShowOptions) => void
  dismiss: (id: number) => void
}

let nextId = 1

export const useToastStore = create<ToastState>((set, get) => ({
  toasts: [],
  show: (message, variantOrOpts) => {
    const opts: ShowOptions =
      typeof variantOrOpts === 'string' ? { variant: variantOrOpts } : variantOrOpts ?? {}
    const variant = opts.variant ?? 'info'
    const id = nextId++
    set({ toasts: [...get().toasts, { id, message, variant, action: opts.action }] })
    // Confirmations disappear in 3 seconds. Errors stay a bit longer so they
    // can be read, and actionable toasts (Undo) linger so there's time to click.
    const delay =
      opts.durationMs ?? (opts.action ? 6000 : variant === 'error' ? 6000 : 3000)
    setTimeout(() => get().dismiss(id), delay)
  },
  dismiss: (id) => set({ toasts: get().toasts.filter((t) => t.id !== id) }),
}))

/** Maps backend error codes to friendly messages. */
export function errorMessage(code: string): string {
  const map: Record<string, string> = {
    DUPLICATE_FIRM_NAME: 'A firm with that name already exists.',
    INVALID_FIRM_NAME: 'Firm name must be 1–200 characters.',
    DUPLICATE_PARTNER_NAME: 'That partner already exists in this firm.',
    INVALID_PARTNER_NAME: 'Partner name must be 1–200 characters.',
    TOO_MANY_PARTNERS: 'A firm may have at most 50 partners.',
    DUPLICATE_MATTER_NAME: 'A matter with that name already exists in this firm.',
    INVALID_MATTER_NAME: 'Matter name must be 1–150 characters.',
    MATTER_ARCHIVED: 'Memos can only be created for active matters.',
    INVALID_MEMO: 'Please complete all required fields (Date and Matter).',
    INVALID_PAYMENT: 'Payment amount must be greater than 0 with a valid date.',
    NO_TEMPLATE: 'Upload a Word template in Settings before exporting.',
    EXPORT_FAILED: 'The export could not be completed.',
    BACKUP_FAILED: 'The backup could not be created.',
    RESTORE_FAILED: 'The backup file could not be restored.',
    INVALID_TEMPLATE: 'The template must be a .docx file under 10 MB.',
    UNKNOWN: 'Something went wrong. Please try again.',
  }
  return map[code] ?? map.UNKNOWN
}
